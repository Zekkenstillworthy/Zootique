"""Demo data seeding helpers.

Goal
----
Populate the database with *real, queryable rows* when tables/sections are empty,
so dashboards and module pages don't render empty states.

Constraints
-----------
- Must be idempotent (safe to run repeatedly).
- Must not overwrite existing customer data.
- Must not depend on Flask app creation (can be called from app startup or scripts).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import os
import re

import sqlalchemy as sa
from sqlalchemy import inspect

import data
from models import (
    Animal,
    Booking,
    Event,
    Feedback,
    Promotion,
    Service,
    StaffTask,
    SubscriptionPayment,
    SubscriptionPlan,
    User,
    Zoo,
    ZooAdminFeedback,
    ZooSubscription,
    ZooZone,
    db,
)


@dataclass
class SeedSummary:
    created: int = 0
    skipped: int = 0

    def bump_created(self, n: int = 1) -> None:
        self.created += n

    def bump_skipped(self, n: int = 1) -> None:
        self.skipped += n


def _truthy_env(name: str, default: str = "") -> bool:
    raw = os.environ.get(name, default)
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _slug(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "zoo"


def _table_exists(table_name: str) -> bool:
    try:
        return inspect(db.engine).has_table(table_name)
    except Exception:
        return False


def _repair_id_sequence(table_name: str) -> None:
    """Repair Postgres serial/identity sequence for `<table_name>.id` if present."""
    if not _table_exists(table_name):
        return

    stmt = sa.text(
        """
        SELECT setval(
            pg_get_serial_sequence(:table_name, 'id'),
            GREATEST(COALESCE((SELECT MAX(id) FROM """ + table_name + """), 1), 1),
            true
        )
        """
    )
    try:
        db.session.execute(stmt, {"table_name": table_name})
        db.session.flush()
    except Exception:
        db.session.rollback()


def _booking_supports_user_id() -> bool:
    try:
        columns = inspect(db.engine).get_columns("bookings")
        return any((c.get("name") or "").lower() == "user_id" for c in columns)
    except Exception:
        return False


def _ensure_user(*, email: str, role: str, full_name: str, password: str, zoo_id: int | None = None) -> tuple[User, bool]:
    email = (email or "").strip().lower()
    user = User.query.filter_by(email=email).first()
    created = False
    if not user:
        user = User(email=email)
        created = True
        db.session.add(user)

    # Do not change role/zoo linkage for existing users; only fill missing safe fields.
    if created:
        user.role = role
        user.zoo_id = zoo_id
        user.status = "active"
        user.full_name = full_name
        user.set_password(password)
    else:
        user.status = (getattr(user, "status", "active") or "active")
        if not user.full_name:
            user.full_name = full_name
    return user, created


def _ensure_subscription_plans(now: datetime) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("subscription_plans"):
        return summary

    plans = [
        {
            "name": "Basic",
            "price": 4999.0,
            "duration": "monthly",
            "duration_months": 1,
            "features": "Bookings, services, basic analytics",
        },
        {
            "name": "Premium",
            "price": 9999.0,
            "duration": "monthly",
            "duration_months": 1,
            "features": "Everything in Basic + advanced analytics + priority support",
        },
    ]

    for payload in plans:
        existing = SubscriptionPlan.query.filter_by(name=payload["name"]).first()
        if existing:
            # Keep existing pricing if already set; only ensure it's active.
            if existing.is_active is False:
                existing.is_active = True
            summary.bump_skipped()
            continue

        plan = SubscriptionPlan(
            name=payload["name"],
            price=float(payload["price"]),
            duration=payload["duration"],
            duration_months=int(payload["duration_months"]),
            features=payload.get("features"),
            is_active=True,
            created_at=now,
        )
        db.session.add(plan)
        summary.bump_created()

    return summary


def _ensure_zoos(now: datetime) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("zoos"):
        return summary

    if Zoo.query.first():
        summary.bump_skipped()
        return summary

    for payload in data.ZOOS:
        zoo = Zoo(
            name=(payload.get("name") or "Unnamed Zoo").strip(),
            type=(payload.get("type") or "Zoo Park").strip(),
            location=(payload.get("location") or "").strip() or None,
            description=(payload.get("description") or "").strip() or None,
            image_url=(payload.get("image_url") or "").strip() or None,
            created_at=now,
        )
        db.session.add(zoo)
        summary.bump_created()

    return summary


def _ensure_animals(zoo: Zoo) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("animals"):
        return summary

    if Animal.query.filter_by(zoo_id=zoo.id).first():
        summary.bump_skipped()
        return summary

    for payload in data.ANIMALS:
        if int(payload.get("zoo_id") or 0) != int(zoo.id):
            continue
        animal = Animal(
            zoo_id=zoo.id,
            name=payload.get("name") or "Unnamed",
            species=payload.get("species"),
            habitat=payload.get("habitat"),
            status=payload.get("status"),
            description=payload.get("description"),
            image_url=payload.get("image_url"),
        )
        db.session.add(animal)
        summary.bump_created()

    # Fallback if data.py doesn't include animals for this zoo.
    if summary.created == 0:
        db.session.add(
            Animal(
                zoo_id=zoo.id,
                name="Demo Animal",
                species="Species",
                habitat="Main Habitat",
                status="Healthy",
                description="Auto-seeded demo animal.",
                image_url=None,
            )
        )
        summary.bump_created()

    return summary


def _ensure_services(zoo: Zoo) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("services"):
        return summary

    if Service.query.filter_by(zoo_id=zoo.id).first():
        summary.bump_skipped()
        return summary

    for payload in data.SERVICES:
        if int(payload.get("zoo_id") or 0) != int(zoo.id):
            continue
        try:
            price = float(payload.get("price") or 0)
        except Exception:
            price = 0.0
        service = Service(
            zoo_id=zoo.id,
            name=payload.get("name") or "Unnamed Service",
            price=price,
            description=payload.get("description"),
            image_url=payload.get("image_url"),
        )
        db.session.add(service)
        summary.bump_created()

    if summary.created == 0:
        db.session.add(
            Service(
                zoo_id=zoo.id,
                name="General Admission",
                price=350.0,
                description="Auto-seeded admission ticket.",
                image_url=None,
            )
        )
        summary.bump_created()
    return summary


def _ensure_zones(zoo: Zoo, now: datetime) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("zoo_zones"):
        return summary

    if ZooZone.query.filter_by(zoo_id=zoo.id).first():
        summary.bump_skipped()
        return summary

    zones = [
        ("Entrance Plaza", "Main entry point and guest services"),
        ("Savannah Zone", "Open habitat exhibits and viewing decks"),
        ("Learning Pavilion", "Education area, talks, and workshops"),
    ]
    for name, desc in zones:
        db.session.add(
            ZooZone(
                zoo_id=zoo.id,
                name=name,
                description=desc,
                map_image_url=None,
                panorama_360_url=None,
                created_at=now,
            )
        )
        summary.bump_created()
    return summary


def _ensure_events(zoo: Zoo) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("events"):
        return summary

    if Event.query.filter_by(zoo_id=zoo.id).first():
        summary.bump_skipped()
        return summary

    rows = [
        ("Animal Feeding Time", "Feeding", "10:00 AM", "Main Habitat"),
        ("Keeper Talk", "Talk", "3:00 PM", "Learning Pavilion"),
    ]
    for name, typ, time_value, location in rows:
        db.session.add(Event(zoo_id=zoo.id, name=name, type=typ, time=time_value, location=location))
        summary.bump_created()
    return summary


def _ensure_promotions(zoo: Zoo, now: datetime) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("promotions"):
        return summary

    if Promotion.query.filter_by(zoo_id=zoo.id).first():
        summary.bump_skipped()
        return summary

    valid_until = (now + timedelta(days=45)).strftime("%Y-%m-%d")
    code1 = f"Z{zoo.id}SAVE10"
    code2 = f"Z{zoo.id}FAM15"

    db.session.add(
        Promotion(
            zoo_id=zoo.id,
            name="Season Pass Promo",
            code=code1,
            promo_type="Seasonal",
            country="Philippines",
            discount="10%",
            valid_until=valid_until,
        )
    )
    db.session.add(
        Promotion(
            zoo_id=zoo.id,
            name="Family Bundle",
            code=code2,
            promo_type="Family",
            country="Philippines",
            discount="15%",
            valid_until=valid_until,
        )
    )
    summary.bump_created(2)
    return summary


def _ensure_feedback(zoo: Zoo, now: datetime) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("feedbacks"):
        return summary

    if Feedback.query.filter_by(zoo_id=zoo.id).first():
        summary.bump_skipped()
        return summary

    entries = [
        ("Elena Torres", 5, "Amazing experience — clean and well organized."),
        ("Ricardo Gomez", 4, "Great exhibits, a bit crowded at peak hours."),
        ("Alyssa Reyes", 5, "Staff were friendly and helpful."),
        ("Martin Santos", 3, "Some areas could use more shade."),
    ]
    for i, (name, rating, comment) in enumerate(entries):
        day = (now - timedelta(days=i + 2)).strftime("%Y-%m-%d")
        db.session.add(
            Feedback(
                zoo_id=zoo.id,
                user_id=None,
                visitor_name=name,
                rating=int(rating),
                comment=comment,
                date=day,
                created_at=now - timedelta(days=i + 2),
            )
        )
        summary.bump_created()
    return summary


def _ensure_bookings(*, zoo: Zoo, now: datetime, visitors: list[User], staff: list[User]) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("bookings"):
        return summary

    existing = Booking.query.filter_by(zoo_id=zoo.id).all()
    if existing:
        # Revenue/analytics pages aggregate by YYYY-MM prefix of Booking.date.
        # If the zoo already has at least one recent ISO-ish booking, do nothing.
        recent_prefixes = {(now - timedelta(days=30 * i)).strftime('%Y-%m') for i in range(0, 6)}
        has_recent_iso = any((str(b.date or '')[:7] in recent_prefixes) for b in existing)
        if has_recent_iso:
            summary.bump_skipped()
            return summary

    services = Service.query.filter_by(zoo_id=zoo.id).order_by(Service.id.asc()).all()
    if not services:
        summary.bump_skipped()
        return summary

    use_user_id = _booking_supports_user_id()
    assigned_staff = staff[0] if staff else None
    base_month = datetime.utcnow().replace(day=1)

    # Generate a BK-#### sequence that won't collide with existing rows.
    # (Booking IDs are global PKs, not scoped per-zoo.)
    last_id = (
        db.session.query(sa.func.max(Booking.id))
        .filter(Booking.id.like("BK-%"))
        .scalar()
    )
    next_suffix = 1001
    if last_id:
        try:
            next_suffix = int(str(last_id).split("BK-", 1)[1]) + 1
        except Exception:
            next_suffix = int(datetime.utcnow().timestamp())

    def _iso(d: datetime) -> str:
        return d.strftime("%Y-%m-%d")

    for i in range(0, min(6, len(services))):
        booking_id = f"BK-{next_suffix + i}"  # BK-1001 style (numeric sequence)
        service = services[i % len(services)]
        visitor = visitors[i % len(visitors)] if visitors else None

        when = base_month - timedelta(days=30 * (5 - (i + 1)))
        guests = 2 + ((i + 1) % 4)
        amount = float(service.price or 0.0) * float(guests)
        status = "Confirmed" if (i + 1) % 3 != 0 else "Pending"
        payment_status = "paid" if status == "Confirmed" else "unpaid"

        b = Booking(
            id=booking_id,
            zoo_id=zoo.id,
            service_id=service.id,
            visitor_name=(visitor.full_name if visitor else "Walk-in Visitor"),
            service_name=service.name,
            date=_iso(when),
            time="10:00 AM",
            guests=int(guests),
            status=status,
            amount=float(amount),
            payment_status=payment_status,
            payment_reference=(f"PAY-{booking_id}" if payment_status == "paid" else None),
            paid_at=(now - timedelta(days=1) if payment_status == "paid" else None),
            created_at=now - timedelta(days=(i + 1) * 2),
        )
        if assigned_staff:
            b.assigned_staff_user_id = int(assigned_staff.id)
        if use_user_id and visitor:
            b.user_id = int(visitor.id)

        db.session.add(b)
        summary.bump_created()

    return summary


def _ensure_staff_tasks(*, zoo: Zoo, now: datetime, staff: list[User]) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("staff_tasks"):
        return summary

    if StaffTask.query.filter_by(zoo_id=zoo.id).first():
        summary.bump_skipped()
        return summary

    assignee = staff[0] if staff else None
    tasks = [
        ("Morning enclosure check", "Inspect enclosures and report issues", "pending", 2),
        ("Prepare feeding supplies", "Stock and prep feed for scheduled sessions", "in_progress", 1),
        ("Close-of-day log", "Record daily operations and incidents", "pending", 0),
    ]
    for title, desc, status, due_in_days in tasks:
        db.session.add(
            StaffTask(
                zoo_id=zoo.id,
                assigned_to_user_id=(int(assignee.id) if assignee else None),
                title=title,
                description=desc,
                due_date=(date.today() + timedelta(days=due_in_days)),
                status=status,
                created_at=now,
            )
        )
        summary.bump_created()
    return summary


def _ensure_zoo_subscription(*, zoo: Zoo, now: datetime) -> SeedSummary:
    summary = SeedSummary()
    if not (_table_exists("zoo_subscriptions") and _table_exists("subscription_plans") and _table_exists("subscription_payments")):
        return summary

    sub = (
        ZooSubscription.query.filter_by(zoo_id=zoo.id)
        .order_by(ZooSubscription.end_date.desc())
        .first()
    )

    if not sub:
        plan = SubscriptionPlan.query.filter_by(name="Premium").first() or SubscriptionPlan.query.filter_by(is_active=True).first()
        if not plan:
            summary.bump_skipped()
            return summary

        start = now - timedelta(days=60)
        end = now + timedelta(days=60)
        sub = ZooSubscription(
            zoo_id=zoo.id,
            plan_id=plan.id,
            start_date=start,
            end_date=end,
            status="active",
            created_at=now,
        )
        db.session.add(sub)
        db.session.flush()
        summary.bump_created()

    # Ensure we have payment history (last 6 months) for dashboards/reports.
    plan = sub.plan or db.session.get(SubscriptionPlan, sub.plan_id)
    if not plan:
        summary.bump_skipped()
        return summary

    existing_refs = {
        (p.reference or "")
        for p in SubscriptionPayment.query.filter_by(subscription_id=sub.id).all()
    }

    cursor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30 * 5)
    for i in range(6):
        period_start = cursor + timedelta(days=30 * i)
        period_end = period_start + timedelta(days=30)
        ref = f"SEED-SUB-{sub.id}-{period_start.strftime('%Y%m')}"
        if ref in existing_refs:
            summary.bump_skipped()
            continue
        db.session.add(
            SubscriptionPayment(
                subscription_id=sub.id,
                amount=float(plan.price or 0.0),
                paid_at=period_start + timedelta(days=2),
                period_start=period_start,
                period_end=period_end,
                reference=ref,
                status="paid",
            )
        )
        summary.bump_created()

    return summary


def _ensure_system_feedback(*, zoo: Zoo, now: datetime) -> SeedSummary:
    summary = SeedSummary()
    if not _table_exists("zoo_admin_feedback"):
        return summary
    if ZooAdminFeedback.query.filter_by(zoo_id=zoo.id).first():
        summary.bump_skipped()
        return summary

    rows = [
        ("Features", 5, "Would love an easier way to export monthly booking reports."),
        ("Support", 4, "Great experience overall — faster response times would be helpful."),
    ]
    for category, rating, comment in rows:
        db.session.add(
            ZooAdminFeedback(
                zoo_id=zoo.id,
                user_id=None,
                category=category,
                rating=int(rating),
                comment=comment,
                created_at=now - timedelta(days=7),
            )
        )
        summary.bump_created()
    return summary


def ensure_demo_data(*, allow_create_tables: bool = True) -> dict[str, SeedSummary]:
    """Seed demo data into the current DB session.

    Call this inside an app context.

    Returns a map of section -> SeedSummary.
    """
    now = datetime.utcnow()

    # Best-effort: create tables in local/dev if schema is missing.
    if allow_create_tables and _truthy_env("AUTO_CREATE_TABLES", "1"):
        try:
            db.create_all()
        except Exception:
            db.session.rollback()

    # Repair sequences that commonly drift in dev.
    for table in (
        "zoos",
        "users",
        "animals",
        "services",
        "events",
        "promotions",
        "feedbacks",
        "zoo_zones",
        "staff_tasks",
        "subscription_plans",
        "zoo_subscriptions",
        "subscription_payments",
        "zoo_admin_feedback",
    ):
        _repair_id_sequence(table)

    summary: dict[str, SeedSummary] = {}
    with db.session.no_autoflush:
        summary["subscription_plans"] = _ensure_subscription_plans(now)
        summary["zoos"] = _ensure_zoos(now)

        demo_password = os.environ.get("DEMO_PASSWORD", "Password123!")
        if len(demo_password) < 8:
            demo_password = "Password123!"

        # Global demo users
        visitors: list[User] = []
        if _table_exists("users"):
            # Ensure a super admin exists for the Zootique Admin module.
            if User.query.filter_by(role="zootique_admin").first() is None:
                _ensure_user(
                    email="superadmin@zootique.local",
                    role="zootique_admin",
                    full_name="Zootique Super Admin",
                    password=demo_password,
                    zoo_id=None,
                )

            v1, c1 = _ensure_user(email="visitor1@example.com", role="visitor", full_name="Visitor One", password=demo_password)
            v2, c2 = _ensure_user(email="visitor2@example.com", role="visitor", full_name="Visitor Two", password=demo_password)
            visitors = [v1, v2]
            summary["visitor_users"] = SeedSummary(created=int(c1) + int(c2), skipped=2 - (int(c1) + int(c2)))
        else:
            summary["visitor_users"] = SeedSummary()

    # Per-zoo data
        zoos = Zoo.query.order_by(Zoo.id.asc()).all() if _table_exists("zoos") else []

        for zoo in zoos:
            zoo_key = f"zoo_{zoo.id}"

            # Demo module accounts
            staff_members: list[User] = []
            if _table_exists("users"):
                admin_email = f"{_slug(zoo.name)}_admin@example.com"
                _ensure_user(
                    email=admin_email,
                    role="zoo_admin",
                    full_name=f"{zoo.name} Admin",
                    password=demo_password,
                    zoo_id=int(zoo.id),
                )

                for idx in range(1, 3):
                    staff_email = f"{_slug(zoo.name)}_staff{idx}@example.com"
                    staff_user, _ = _ensure_user(
                        email=staff_email,
                        role="zoo_staff",
                        full_name=f"{zoo.name} Staff {idx}",
                        password=demo_password,
                        zoo_id=int(zoo.id),
                    )
                    staff_members.append(staff_user)

            summary[f"{zoo_key}_animals"] = _ensure_animals(zoo)
            summary[f"{zoo_key}_services"] = _ensure_services(zoo)
            summary[f"{zoo_key}_zones"] = _ensure_zones(zoo, now)
            summary[f"{zoo_key}_events"] = _ensure_events(zoo)
            summary[f"{zoo_key}_promotions"] = _ensure_promotions(zoo, now)
            summary[f"{zoo_key}_feedback"] = _ensure_feedback(zoo, now)
            summary[f"{zoo_key}_bookings"] = _ensure_bookings(zoo=zoo, now=now, visitors=visitors, staff=staff_members)
            summary[f"{zoo_key}_staff_tasks"] = _ensure_staff_tasks(zoo=zoo, now=now, staff=staff_members)
            summary[f"{zoo_key}_subscription"] = _ensure_zoo_subscription(zoo=zoo, now=now)
            summary[f"{zoo_key}_system_feedback"] = _ensure_system_feedback(zoo=zoo, now=now)

    db.session.commit()
    return summary
