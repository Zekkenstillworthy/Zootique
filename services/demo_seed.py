"""Transactional, fixture-backed sample data seeder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import os
import re

from sqlalchemy import inspect

from models import (
    Animal, Booking, BookingPayment, EstablishmentRegistration, Event, Feedback,
    Notification, Promotion, Service, StaffTask, SubscriptionPayment,
    SubscriptionPlan, User, Zoo, ZooAdminFeedback, ZooAdminFeedbackReply,
    ZooSubscription, ZooZone, db,
)
from scripts.sample_data.fixture import SAMPLE_MARKER, SAMPLE_ZOOS, SPECIES_HABITAT_TYPES

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWN_SAMPLE_NAMES = {zoo["name"] for zoo in SAMPLE_ZOOS} | {"Live Pipeline Test Sanctuary"}
LEGACY_MARKERS = ("[zootique-full-demo-v1]", SAMPLE_MARKER)


@dataclass
class SeedSummary:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0


@dataclass
class Plan:
    table: str
    zoo: str
    create: int = 0
    update: int = 0
    delete: int = 0
    rows: tuple[str, ...] = ()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def site_today(now: datetime | None = None):
    return (now or datetime.utcnow()).date()


def local_image(zoo_slug: str, record_type: str, record_slug: str, requested: str | None) -> str | None:
    if not requested:
        return None
    path = REPO_ROOT / "static" / "img" / "seed" / zoo_slug / requested
    if path.is_file():
        return f"/static/img/seed/{zoo_slug}/{requested}"
    return None


def _table_exists(name: str) -> bool:
    return inspect(db.engine).has_table(name)


def _sample_zoos() -> list[Zoo]:
    return Zoo.query.filter(
        (Zoo.name.in_(KNOWN_SAMPLE_NAMES))
        | Zoo.description.ilike("%[zootique-full-demo-v1]%")
        | Zoo.description.ilike("%[zootique-sample-v2]%")
    ).order_by(Zoo.id).all()


def _fixture_by_name() -> dict[str, dict]:
    return {row["name"]: row for row in SAMPLE_ZOOS}


def _desired_dates(now: datetime, row: dict) -> str:
    return (now + timedelta(days=int(row["day_offset"]))).date().isoformat()


def _print_plan(plans: list[Plan], deleted: list[str]) -> None:
    print("DRY RUN: no database writes")
    for plan in plans:
        print(f"{plan.table:24} {plan.zoo:42} create={plan.create:2d} update={plan.update:2d} delete={plan.delete:2d}")
        for row in plan.rows:
            print(f"  DELETE {row}")
    if deleted:
        print("EXACT DELETIONS")
        for row in deleted:
            print(f"- {row}")


def _keyed_rows(query, key):
    return {key(row): row for row in query.all()}


def _plan(now: datetime, reset: bool) -> tuple[list[Plan], list[str]]:
    fixtures = _fixture_by_name()
    existing = {z.name: z for z in _sample_zoos() if z.name != "Live Pipeline Test Sanctuary"}
    plans: list[Plan] = []
    exact: list[str] = []
    for name, fixture in fixtures.items():
        if name == "Live Pipeline Test Sanctuary":
            continue
        zoo = existing.get(name)
        zoo_values = {
            "type": fixture["type"],
            "location": fixture["location"],
            "description": fixture["description"],
            "image_url": None,
        }
        zoo_update = int(bool(zoo and any(getattr(zoo, key, None) != value for key, value in zoo_values.items())))
        plans.append(Plan("zoos", name, create=0 if zoo else 1, update=zoo_update))
        keyed = {
            "zoo_zones": (_keyed_rows(ZooZone.query.filter_by(zoo_id=zoo.id), lambda row: row.name) if zoo else {}, {row["name"] for row in fixture["zones"]}),
            "animals": (_keyed_rows(Animal.query.filter_by(zoo_id=zoo.id), lambda row: row.name) if zoo else {}, {row["name"] for row in fixture["animals"]}),
            "services": (_keyed_rows(Service.query.filter_by(zoo_id=zoo.id), lambda row: row.name) if zoo else {}, {row["name"] for row in fixture["services"]}),
            "events": (_keyed_rows(Event.query.filter_by(zoo_id=zoo.id), lambda row: row.name) if zoo else {}, {row["name"] for row in fixture["events"]}),
            "promotions": (_keyed_rows(Promotion.query.filter_by(zoo_id=zoo.id), lambda row: row.code) if zoo else {}, {row["code"] for row in fixture["promotions"]}),
            "bookings": (_keyed_rows(Booking.query.filter_by(zoo_id=zoo.id), lambda row: row.id) if zoo else {}, {row["code"] for row in fixture["bookings"]}),
            "feedbacks": (_keyed_rows(Feedback.query.filter_by(zoo_id=zoo.id), lambda row: row.visitor_name) if zoo else {}, {f"Sample Reviewer {index + 1}" for index in range(3)}),
            "staff_tasks": (_keyed_rows(StaffTask.query.filter_by(zoo_id=zoo.id), lambda row: row.title) if zoo else {}, {f"Sample task {index + 1}" for index in range(3)}),
            "registrations": (_keyed_rows(EstablishmentRegistration.query.filter_by(establishment_name=name), lambda row: row.establishment_name) if zoo else {}, {name}),
            "subscriptions": (_keyed_rows(ZooSubscription.query.filter_by(zoo_id=zoo.id), lambda row: row.zoo_id) if zoo else {}, {zoo.id} if zoo else {None}),
        }
        for table, (current, desired_keys) in keyed.items():
            stale = [row for key, row in current.items() if key not in desired_keys]
            plan = Plan(table, name, create=len(desired_keys - current.keys()), update=0, delete=len(stale) if reset else 0)
            plans.append(plan)
            if reset:
                plan.rows = tuple(f"{row.id}:{getattr(row, 'name', getattr(row, 'code', getattr(row, 'title', getattr(row, 'visitor_name', ''))))}" for row in stale)
                exact.extend(f"{table}:{name}:{row}" for row in plan.rows)
    if reset:
        orphan_events = Event.query.filter(Event.zoo_id.is_(None)).all()
        for row in orphan_events:
            plan = Plan("events", "orphan", delete=1, rows=(f"{row.id}:{row.name}",))
            plans.append(plan)
            exact.append(f"events:orphan:{row.id}:{row.name}")
        legacy_booking = Booking.query.get("BK-1002")
        orphan_bookings = Booking.query.filter(Booking.zoo_id.is_(None)).all()
        for row in orphan_bookings:
            plans.append(Plan("bookings", "orphan", delete=1, rows=(f"{row.id}:{row.visitor_name}",)))
            exact.append(f"bookings:orphan:{row.id}:{row.visitor_name}")
        if legacy_booking and not any(row.id == legacy_booking.id for row in orphan_bookings):
            plan = Plan("bookings", "orphan", delete=1, rows=(f"{legacy_booking.id}:{legacy_booking.visitor_name}",))
            plans.append(plan)
            exact.append(f"bookings:orphan:{legacy_booking.id}:{legacy_booking.visitor_name}")
    return plans, exact


def fixture_summary() -> None:
    for zoo in SAMPLE_ZOOS:
        print(f"\n{zoo['name']} ({zoo['slug']})")
        print("  zones:", ", ".join(f"{z['name']} [{z['kind']}]" for z in zoo["zones"]))
        print("  animals:", ", ".join(f"{a['name']} ({a['species']} -> {a['zone']})" for a in zoo["animals"]))
        print("  services:", ", ".join(s["name"] for s in zoo["services"]))
        print("  events:", ", ".join(f"{e['name']} ({e['zone']}, +{e['day_offset']}d)" for e in zoo["events"]))


def dry_run(*, reset: bool = False, now: datetime | None = None) -> None:
    plans, exact = _plan(now or datetime.utcnow(), reset)
    fixture_summary()
    _print_plan(plans, exact)


def _upsert(model, filters: dict, values: dict, summary: SeedSummary):
    row = model.query.filter_by(**filters).first()
    if row is None:
        row = model(**filters, **values)
        db.session.add(row)
        summary.created += 1
    else:
        changed = False
        for key, value in values.items():
            if getattr(row, key, None) != value:
                setattr(row, key, value)
                changed = True
        summary.updated += int(changed)
    return row


def _seed_zoo(fixture: dict, now: datetime, summary: SeedSummary, visitors: list[User], staff: list[User], plans: list[SubscriptionPlan], booking_has_user_id: bool) -> Zoo:
    zoo = _upsert(Zoo, {"name": fixture["name"]}, {"type": fixture["type"], "location": fixture["location"], "description": fixture["description"], "image_url": None}, summary)
    db.session.flush()
    zones = {}
    for zone in fixture["zones"]:
        zones[zone["name"]] = _upsert(ZooZone, {"zoo_id": zoo.id, "name": zone["name"]}, {"description": zone["description"], "position_x": zone["position_x"], "position_y": zone["position_y"], "map_image_url": None, "panorama_360_url": None, "created_at": now}, summary)
    services = []
    for service in fixture["services"]:
        services.append(_upsert(Service, {"zoo_id": zoo.id, "name": service["name"]}, {"price": service["price"], "description": service["description"], "image_url": local_image(fixture["slug"], "service", slug(service["name"]), service.get("image"))}, summary))
    for animal in fixture["animals"]:
        _upsert(Animal, {"zoo_id": zoo.id, "name": animal["name"]}, {"species": animal["species"], "habitat": animal["zone"], "status": animal["status"], "description": f"Species-appropriate care for {animal['name']}.", "image_url": local_image(fixture["slug"], "animal", slug(animal["name"]), animal.get("image"))}, summary)
    for event in fixture["events"]:
        _upsert(Event, {"zoo_id": zoo.id, "name": event["name"]}, {"type": event["type"], "time": f"{_desired_dates(now, event)} {event['time']}", "location": event["zone"], "image_url": None}, summary)
    for promo in fixture["promotions"]:
        _upsert(Promotion, {"code": promo["code"]}, {"zoo_id": zoo.id, "name": promo["name"], "promo_type": promo["promo_type"], "country": "Philippines", "discount": promo["discount"], "valid_until": (now + timedelta(days=promo["days"])).date().isoformat(), "image_url": local_image(fixture["slug"], "promotion", slug(promo["code"]), promo.get("image"))}, summary)
    service_by_index = services
    for booking_data in fixture["bookings"]:
        service = service_by_index[booking_data["service_index"]]
        booking_date = _desired_dates(now, booking_data)
        status = booking_data["status"]
        payment_status = "paid" if status in {"Completed", "Confirmed"} else ("refunded" if status == "Cancelled" else "unpaid")
        amount = float(service.price or 0) * booking_data["guests"]
        booking = _upsert(Booking, {"id": booking_data["code"]}, {"zoo_id": zoo.id, "service_id": service.id, "user_id": visitors[booking_data["visitor_index"]].id if booking_has_user_id else None, "visitor_name": visitors[booking_data["visitor_index"]].full_name, "service_name": service.name, "date": booking_date, "time": "10:00 AM", "guests": booking_data["guests"], "status": status, "amount": amount, "payment_status": payment_status, "payment_reference": f"SAMPLE-PAY-{booking_data['code']}", "paid_at": now if payment_status in {"paid", "refunded"} else None, "created_at": now - timedelta(days=abs(booking_data["day_offset"]) + 2)}, summary)
        db.session.flush()
        if payment_status in {"paid", "refunded"}:
            _upsert(BookingPayment, {"booking_id": booking.id}, {"payer_user_id": booking.user_id, "amount": amount, "method": "card", "status": payment_status, "reference": f"SAMPLE-PAY-{booking.id}", "provider": "sample", "created_at": now, "paid_at": now}, summary)
        if status == "Confirmed":
            _upsert(Notification, {"dedupe_key": f"sample-confirmed:{booking.id}"}, {"user_id": booking.user_id, "booking_id": booking.id, "notification_type": "booking_confirmation", "message": f"Booking confirmed: {booking.service_name} on {booking.date} for PHP {booking.amount:.2f}.", "created_at": now}, summary)
    for index in range(3):
        feedback = _upsert(Feedback, {"zoo_id": zoo.id, "visitor_name": f"Sample Reviewer {index + 1}"}, {"user_id": visitors[index].id, "rating": 5 - index, "comment": f"A thoughtful {fixture['name']} visit.", "date": (now - timedelta(days=index + 2)).date().isoformat(), "created_at": now - timedelta(days=index + 2)}, summary)
        if index < 2:
            _upsert(ZooAdminFeedback, {"zoo_id": zoo.id, "category": "Features" if index == 0 else "Support", "comment": f"Sample feedback for {fixture['name']}"}, {"user_id": None, "rating": 5 - index, "created_at": now}, summary)
    for index, status in enumerate(("pending", "in_progress", "done")):
        _upsert(StaffTask, {"zoo_id": zoo.id, "title": f"Sample task {index + 1}"}, {"assigned_to_user_id": staff[0].id if staff else None, "description": f"Fixture task for {fixture['name']}", "due_date": now.date() + timedelta(days=index), "status": status, "created_at": now}, summary)
    plan = plans[0 if zoo.id % 2 else 1]
    sub = _upsert(ZooSubscription, {"zoo_id": zoo.id}, {"plan_id": plan.id, "start_date": now - timedelta(days=30), "end_date": now + timedelta(days=90 if zoo.id % 3 else -2), "status": "active" if zoo.id % 3 else "expired", "created_at": now}, summary)
    db.session.flush()
    _upsert(SubscriptionPayment, {"subscription_id": sub.id, "reference": f"SAMPLE-SUB-{zoo.id}"}, {"amount": plan.price, "paid_at": now, "period_start": now - timedelta(days=30), "period_end": now, "status": "paid"}, summary)
    _upsert(EstablishmentRegistration, {"establishment_name": fixture["name"]}, {"establishment_type": fixture["type"], "location": fixture["location"], "status": ("approved" if zoo.id % 3 == 1 else "pending" if zoo.id % 3 == 2 else "rejected"), "zoo_id": zoo.id, "created_at": now, "updated_at": now}, summary)
    return zoo


def _booking_has_user_id() -> bool:
    return any(c["name"] == "user_id" for c in inspect(db.engine).get_columns("bookings"))


def seed(*, dry_run: bool = False, reset: bool = False, now: datetime | None = None) -> dict[str, SeedSummary]:
    now = now or datetime.utcnow()
    if dry_run:
        dry_run_plan = globals()["dry_run"]
        dry_run_plan(reset=reset, now=now)
        return {}
    if not reset:
        raise ValueError("Applying the sample rebuild requires --reset; use --dry-run to inspect it first.")
    db.session.rollback()
    booking_has_user_id = _booking_has_user_id()
    with db.session.begin():
        sample = _sample_zoos()
        fixture_names = {z["name"] for z in SAMPLE_ZOOS}
        deletable = [z for z in sample if z.name in fixture_names or any(marker in (z.description or "") for marker in LEGACY_MARKERS)]
        for zoo in deletable:
            if zoo.name in fixture_names:
                fixture = _fixture_by_name()[zoo.name]
                desired = {
                    "zones": {row["name"] for row in fixture["zones"]},
                    "animals": {row["name"] for row in fixture["animals"]},
                    "services": {row["name"] for row in fixture["services"]},
                    "events": {row["name"] for row in fixture["events"]},
                    "promotions": {row["code"] for row in fixture["promotions"]},
                    "bookings": {row["code"] for row in fixture["bookings"]},
                    "feedbacks": {f"Sample Reviewer {index + 1}" for index in range(3)},
                    "staff_tasks": {f"Sample task {index + 1}" for index in range(3)},
                }
                for booking in Booking.query.filter_by(zoo_id=zoo.id).all():
                    if booking.id not in desired["bookings"]:
                        Notification.query.filter_by(booking_id=booking.id).delete(synchronize_session=False)
                        BookingPayment.query.filter_by(booking_id=booking.id).delete(synchronize_session=False)
                        db.session.delete(booking)
                for model, query, key, bucket in (
                    (Event, Event.query.filter_by(zoo_id=zoo.id), lambda row: row.name, "events"),
                    (Promotion, Promotion.query.filter_by(zoo_id=zoo.id), lambda row: row.code, "promotions"),
                    (Service, Service.query.filter_by(zoo_id=zoo.id), lambda row: row.name, "services"),
                    (Animal, Animal.query.filter_by(zoo_id=zoo.id), lambda row: row.name, "animals"),
                    (ZooZone, ZooZone.query.filter_by(zoo_id=zoo.id), lambda row: row.name, "zones"),
                    (Feedback, Feedback.query.filter_by(zoo_id=zoo.id), lambda row: row.visitor_name, "feedbacks"),
                    (StaffTask, StaffTask.query.filter_by(zoo_id=zoo.id), lambda row: row.title, "staff_tasks"),
                ):
                    for row in query.all():
                        if key(row) not in desired[bucket]:
                            if model is Feedback:
                                ZooAdminFeedbackReply.query.filter(ZooAdminFeedbackReply.feedback_id == row.id).delete(synchronize_session=False)
                            db.session.delete(row)
                continue
            booking_ids = [b.id for b in Booking.query.filter_by(zoo_id=zoo.id).all()]
            if booking_ids:
                Notification.query.filter(Notification.booking_id.in_(booking_ids)).delete(synchronize_session=False)
                BookingPayment.query.filter(BookingPayment.booking_id.in_(booking_ids)).delete(synchronize_session=False)
            ZooAdminFeedbackReply.query.filter(ZooAdminFeedbackReply.feedback_id.in_(db.session.query(ZooAdminFeedback.id).filter_by(zoo_id=zoo.id))).delete(synchronize_session=False)
            Booking.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            Event.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            Promotion.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            Service.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            Animal.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            ZooZone.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            Feedback.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            StaffTask.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            EstablishmentRegistration.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            ZooSubscription.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            ZooAdminFeedback.query.filter_by(zoo_id=zoo.id).delete(synchronize_session=False)
            db.session.delete(zoo)
        orphan_events = Event.query.filter(Event.zoo_id.is_(None)).all()
        if orphan_events:
            db.session.delete(orphan_events[0])
            for event in orphan_events[1:]: db.session.delete(event)
        orphan_bookings = Booking.query.filter(Booking.zoo_id.is_(None)).all()
        for booking in orphan_bookings:
            Notification.query.filter_by(booking_id=booking.id).delete(synchronize_session=False)
            BookingPayment.query.filter_by(booking_id=booking.id).delete(synchronize_session=False)
            db.session.delete(booking)
        plans = [SubscriptionPlan.query.filter_by(name="Basic").first(), SubscriptionPlan.query.filter_by(name="Premium").first()]
        if not all(plans): raise RuntimeError("Subscription plans are required")
        visitors = []
        staff = []
        for index in range(4):
            visitor, _ = _ensure_sample_user(f"sample.visitor.{index + 1}@example.com", "visitor", f"Sample Visitor {index + 1}", None)
            visitors.append(visitor)
        for fixture in SAMPLE_ZOOS:
            admin, _ = _ensure_sample_user(f"sample.admin.{fixture['slug']}@example.com", "zoo_admin", f"{fixture['name']} Admin", None)
            staff.append(admin)
        summaries = {}
        for fixture in SAMPLE_ZOOS:
            summaries[fixture["name"]] = SeedSummary()
            _seed_zoo(fixture, now, summaries[fixture["name"]], visitors, staff, plans, booking_has_user_id)
    return summaries


def _ensure_sample_user(email: str, role: str, name: str, zoo_id: int | None):
    user = User.query.filter_by(email=email).first()
    created = user is None
    if created:
        user = User(email=email, role=role, full_name=name, zoo_id=zoo_id, status="active")
        user.set_password(os.environ.get("DEMO_PASSWORD", "Password123!"))
        db.session.add(user)
    return user, created


def ensure_demo_data(*, allow_create_tables: bool = True, dry_run: bool = False, reset: bool = False):
    return seed(dry_run=dry_run, reset=reset)
