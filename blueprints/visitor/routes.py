from __future__ import annotations

from datetime import datetime
from functools import wraps
import math
import os
import re
import secrets
from urllib.parse import urlparse

from flask import Blueprint, render_template, abort, request, redirect, url_for, flash, session
from sqlalchemy import func, or_, inspect
from werkzeug.utils import secure_filename

from services.storage import save_uploaded_image as _save_uploaded_image

from models import db, Zoo, Animal, Service, Booking, BookingPayment, Event, Promotion, Feedback, User, ZooZone, EstablishmentType
from services import (
    BookingAuthorizationError,
    BookingValidationError,
    process_booking_checkout,
    FeedbackAuthorizationError,
    FeedbackValidationError,
    create_visitor_feedback,
    delete_visitor_feedback,
    feedback_aliases_for_user,
    is_feedback_owned_by_user,
    update_visitor_feedback,
)

visitor_bp = Blueprint("visitor", __name__)


def _is_user_active(user: User | None) -> bool:
    if not user:
        return False
    status = getattr(user, "status", "active")
    return str(status or "active").strip().lower() == "active"


@visitor_bp.before_request
def _activate_saved_visitor_role():
    """Activate the saved Visitor role (if present) for all visitor pages.

    Some visitor routes are intentionally public (e.g. promotions/events). Without
    this hook, those pages won't call the login guard and the base navbar will
    render the guest header even when the user has previously signed in as a
    Visitor (stored in session['auth_by_role']).
    """

    auth_by_role = session.get("auth_by_role")
    if not isinstance(auth_by_role, dict):
        return None

    role_state = auth_by_role.get("visitor")
    if not isinstance(role_state, dict):
        return None

    role_user_id = role_state.get("user_id")
    if not role_user_id:
        return None

    # If Visitor role is already active, nothing to do.
    if session.get("role") == "visitor" and session.get("user_id"):
        return None

    try:
        visitor_user_id = int(role_user_id)
    except Exception:
        return None

    user = db.session.get(User, visitor_user_id)
    if not _is_user_active(user):
        # Stored role is stale; remove it so the UI doesn't flip-flop.
        auth_by_role.pop("visitor", None)
        session["auth_by_role"] = auth_by_role
        return None

    session["user_id"] = int(user.id)
    session["role"] = "visitor"
    session["full_name"] = user.full_name or role_state.get("full_name") or session.get("full_name")
    session.permanent = True
    session.modified = True
    return None


def _selected_zoo_id() -> int | None:
    zoo_id = session.get("selected_zoo_id")
    if zoo_id is None:
        return None
    try:
        zoo_id_int = int(zoo_id)
    except Exception:
        return None
    return zoo_id_int if zoo_id_int > 0 else None


def _maybe_filter_by_selected_zoo(query, model):
    """Filter a SQLAlchemy query strictly by the selected zoo."""
    selected_zoo_id = _selected_zoo_id()
    if not selected_zoo_id:
        return query
    if hasattr(model, "zoo_id"):
        return query.filter(model.zoo_id == selected_zoo_id)
    return query


def _strip_mvp_terms(value: str | None) -> str | None:
    if not value:
        return value
    cleaned = re.sub(r"\(\s*mvp\s*\)", "", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmvp\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def _require_visitor_login():
    auth_by_role = session.get("auth_by_role")
    if not isinstance(auth_by_role, dict):
        auth_by_role = {}

    role_state = auth_by_role.get("visitor") if isinstance(auth_by_role, dict) else None
    role_user_id = role_state.get("user_id") if isinstance(role_state, dict) else None

    # If we have a visitor role session saved, activate it for this request.
    if role_user_id:
        session["user_id"] = role_user_id
        session["role"] = "visitor"
        if role_state.get("full_name"):
            session["full_name"] = role_state.get("full_name")

    if session.get("user_id") and session.get("role") == "visitor":
        user = _current_user()
        if _is_user_active(user):
            # Keep role-specific state in sync.
            auth_by_role["visitor"] = {"user_id": int(user.id), "full_name": user.full_name}
            session["auth_by_role"] = auth_by_role
            session.permanent = True
            session.modified = True
            return None
        # Session is stale (user deleted/suspended). Force sign-in for visitor role only.
        auth_by_role.pop("visitor", None)
        session["auth_by_role"] = auth_by_role
        session.pop("user_id", None)
        session.pop("role", None)
    flash("Please sign in as a Visitor to continue.", "error")
    next_url = request.full_path
    if next_url.endswith("?"):
        next_url = next_url[:-1]
    return redirect(url_for("auth.login", module_name="visitor", next=next_url))


def visitor_login_required(view_func):
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        maybe_redirect = _require_visitor_login()
        if maybe_redirect is not None:
            return maybe_redirect

        # MVP: require Zoo selection before accessing protected visitor pages.
        if session.get("role") == "visitor":
            if request.endpoint not in {"visitor.choose_zoo", "visitor.profile"} and not session.get("selected_zoo_id"):
                next_url = request.full_path
                if next_url.endswith("?"):
                    next_url = next_url[:-1]
                return redirect(url_for("visitor.choose_zoo", next=next_url))
        return view_func(*args, **kwargs)

    return _wrapped


def _safe_relative_redirect(target: str | None):
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme == "" and parsed.netloc == "" and parsed.path.startswith("/"):
        return redirect(target)
    return None


@visitor_bp.post("/select-zoo")
def select_zoo():
    """Dedicated POST handler for zoo selection. Separated from the GET so the
    @visitor_login_required decorator doesn't block a cold-start serverless POST.
    We manually re-hydrate the session here from auth_by_role if needed.
    """
    # Re-hydrate session from stored role state (handles Vercel cold-starts)
    auth_by_role = session.get("auth_by_role")
    if isinstance(auth_by_role, dict):
        role_state = auth_by_role.get("visitor")
        if isinstance(role_state, dict) and role_state.get("user_id"):
            if not (session.get("user_id") and session.get("role") == "visitor"):
                session["user_id"] = int(role_state["user_id"])
                session["role"] = "visitor"
                session["full_name"] = role_state.get("full_name", "")
                session.permanent = True
                session.modified = True

    # Must be logged in as visitor to select a zoo
    if not (session.get("user_id") and session.get("role") == "visitor"):
        flash("Please sign in as a Visitor to continue.", "error")
        return redirect(url_for("auth.login", module_name="visitor"))

    zoo_id_raw = (request.form.get("zoo_id") or "").strip()
    next_raw = (request.form.get("next") or "").strip() or None

    if zoo_id_raw.isdigit():
        zoo_id = int(zoo_id_raw)
        if Zoo.query.count() > 0:
            zoo = db.session.get(Zoo, zoo_id)
            if not zoo:
                flash("Selected zoo was not found.", "error")
                return redirect(url_for("visitor.choose_zoo"))

        session["selected_zoo_id"] = zoo_id
        session.modified = True
        stored_next = (session.pop("post_login_next", None) or "").strip() or None
        maybe_next = _safe_relative_redirect(stored_next) or _safe_relative_redirect(next_raw)
        if maybe_next:
            return maybe_next
        return redirect(url_for("visitor.home"))

    flash("Please select a zoo.", "error")
    return redirect(url_for("visitor.choose_zoo"))


@visitor_bp.route("/choose-zoo", methods=["GET"])
@visitor_bp.route("/choose-zoo/<string:category_name>", methods=["GET"])
@visitor_login_required
def choose_zoo(category_name=None):
    if request.method == "GET":
        session.pop("selected_zoo_id", None)

    all_zoos = Zoo.query.order_by(Zoo.id.asc()).all()

    def _zoo_field(zoo_obj, field: str):
        if zoo_obj is None:
            return None
        if hasattr(zoo_obj, field):
            return getattr(zoo_obj, field)
        if isinstance(zoo_obj, dict):
            return zoo_obj.get(field)
        return None

    def _zoo_type(zoo_obj) -> str | None:
        raw = _zoo_field(zoo_obj, "type")
        if raw is None:
            return None
        value = str(raw).strip()
        return value or None

    # Build the list of available categories from active EstablishmentTypes
    active_types = EstablishmentType.query.filter_by(is_active=True).order_by(EstablishmentType.name.asc()).all()

    category_counts: dict[str, int] = {}
    icon_map: dict[str, str] = {
        "Zoo Park": "fa-paw",
        "Farm Animal Attraction": "fa-cow",
        "Farm Attraction": "fa-tractor",
    }

    for et in active_types:
        category_counts[et.name] = 0
        icon = et.icon_class or "fa-tree"
        if " " in icon:
            icon = icon.split()[-1]
        icon_map[et.name] = icon

    for zoo in all_zoos:
        t = _zoo_type(zoo)
        if t:
            category_counts[t] = category_counts.get(t, 0) + 1

    categories = list(category_counts.keys())

    raw_selected = (category_name or request.args.get("type") or "").strip() or None
    selected_type = None
    if raw_selected:
        # Match case-insensitively against known categories or raw string
        matched = next((c for c in category_counts if c.lower().strip() == raw_selected.lower().strip()), raw_selected)
        selected_type = matched

    filtered_zoos = (
        [z for z in all_zoos if _zoo_type(z) and _zoo_type(z).lower().strip() == selected_type.lower().strip()]
        if selected_type
        else []
    )

    selected_zoo = None
    selected_id = session.get("selected_zoo_id")
    if selected_id:
        if isinstance(all_zoos, list) and all_zoos and isinstance(all_zoos[0], dict):
            selected_zoo = next((z for z in all_zoos if z.get("id") == selected_id), None)
        else:
            selected_zoo = db.session.get(Zoo, int(selected_id))

    next_url = (request.args.get("next") or "").strip() or None
    return render_template(
        "visitor/choose_zoo.html",
        zoos=filtered_zoos,
        zoo_categories=categories,
        selected_type=selected_type,
        category_counts=category_counts,
        category_icon_map=icon_map,
        selected_zoo=selected_zoo,
        next_url=next_url,
    )


def _generate_booking_id() -> str:
    """Generate a unique booking ID using cryptographically random hex.

    Uses secrets.token_hex instead of DB max-query to avoid race conditions
    when multiple bookings are created simultaneously.
    """
    return f"BK-{secrets.token_hex(5).upper()}"


def _booking_supports_user_id() -> bool:
    """Detect if the live DB schema has the `bookings.user_id` column.

    Must work across backends (SQLite/Postgres/etc). We can't assume PRAGMA.
    """
    try:
        columns = inspect(db.engine).get_columns("bookings")
        return any((c.get("name") or "").lower() == "user_id" for c in columns)
    except Exception:
        return False


def _booking_owner_aliases(user: User) -> list[str]:
    aliases = sorted(_feedback_owner_aliases(user))
    # Ensure we always have at least one alias.
    if not aliases and user.email:
        aliases = [user.email]
    return aliases


def _booking_owner_filter(user: User):
    if _booking_supports_user_id():
        return Booking.user_id == user.id
    # Legacy fallback (pre-migration)
    return Booking.visitor_name.in_(_booking_owner_aliases(user))


def _booking_owner_filter_by_id(user: User, booking_id: str):
    if _booking_supports_user_id():
        return (Booking.id == booking_id) & (Booking.user_id == user.id)
    return (Booking.id == booking_id) & (Booking.visitor_name.in_(_booking_owner_aliases(user)))


def _feedback_owner_aliases(user: User) -> set[str]:
    return feedback_aliases_for_user(user)


def _feedback_owned_by_user(feedback: Feedback, user: User) -> bool:
    return is_feedback_owned_by_user(feedback, user)

@visitor_bp.get("/")
@visitor_login_required
def home():
    if session.get("user_id") and session.get("role") == "visitor" and not session.get("selected_zoo_id"):
        return redirect(url_for("visitor.choose_zoo"))

    zoos = Zoo.query.order_by(Zoo.id.asc()).all()
    services = _maybe_filter_by_selected_zoo(Service.query, Service).order_by(Service.id.asc()).all()
    promotions = _maybe_filter_by_selected_zoo(Promotion.query, Promotion).order_by(Promotion.id.asc()).all()
    events = _maybe_filter_by_selected_zoo(Event.query, Event).order_by(Event.id.asc()).all()

    selected_zoo_id = _selected_zoo_id()

    user = _current_user()
    bookings: list[Booking] | list[dict]
    if user and session.get("role") == "visitor":
        booking_query = Booking.query.filter(_booking_owner_filter(user))
        if selected_zoo_id:
            booking_query = booking_query.filter(Booking.zoo_id == selected_zoo_id)
        bookings = booking_query.order_by(Booking.created_at.desc()).limit(5).all()
    else:
        # Never return cross-zoo booking data without a valid user context.
        bookings = []

    selected_zoo = None
    if selected_zoo_id:
        if zoos and isinstance(zoos[0], dict):
            selected_zoo = next((z for z in zoos if z.get("id") == selected_zoo_id), None)
        else:
            selected_zoo = db.session.get(Zoo, selected_zoo_id)

    if not selected_zoo:
        # selected_zoo_id in session no longer matches any zoo (deleted zoo, stale session).
        # Clear the stale selection and send the visitor to choose a valid zoo.
        session.pop("selected_zoo_id", None)
        return redirect(url_for("visitor.choose_zoo"))
    landing_map = None

    if selected_zoo:
        if isinstance(selected_zoo, dict):
            image_url = selected_zoo.get("landing_map_image_url")
            if image_url:
                landing_map = {
                    "title": _strip_mvp_terms(selected_zoo.get("landing_map_title") or f"{selected_zoo.get('name', 'Zoo')} Visitor Map") or "",
                    "description": _strip_mvp_terms(selected_zoo.get("landing_map_description") or "Use this map to plan your route before exploring.") or "",
                    "image_url": image_url,
                    "updated_at": selected_zoo.get("landing_map_updated_at"),
                }
        else:
            image_url = (getattr(selected_zoo, "landing_map_image_url", None) or "").strip()
            if not image_url:
                fallback_zone = (
                    ZooZone.query
                    .filter(ZooZone.zoo_id == selected_zoo.id, ZooZone.map_image_url.isnot(None))
                    .order_by(ZooZone.created_at.desc())
                    .first()
                )
                if fallback_zone and (fallback_zone.map_image_url or "").strip():
                    image_url = fallback_zone.map_image_url.strip()

            if image_url:
                landing_map = {
                    "title": _strip_mvp_terms(getattr(selected_zoo, "landing_map_title", None) or f"{selected_zoo.name} Visitor Map") or "",
                    "description": _strip_mvp_terms(getattr(selected_zoo, "landing_map_description", None) or "Use this map to plan your route before exploring.") or "",
                    "image_url": image_url,
                    "updated_at": getattr(selected_zoo, "landing_map_updated_at", None),
                }

    return render_template(
        "visitor/home.html",
        zoo=selected_zoo,
        services=services,
        bookings=bookings,
        promotions=promotions,
        events=events,
        landing_map=landing_map,
    )

@visitor_bp.get("/zoos")
def list_zoos():
    db_zoos = Zoo.query.order_by(Zoo.id.asc()).all()
    if not db_zoos:
        return render_template("visitor/zoos.html", zoos=[])

    zoos = []
    for zoo in db_zoos:
        type_name = (zoo.type or "Zoo Park").strip()
        lowered_type = type_name.lower()
        if "wildlife" in lowered_type:
            type_slug = "wildlife"
        elif "farm" in lowered_type:
            type_slug = "farm"
        else:
            type_slug = "zoo"

        rating_value = (
            db.session.query(func.avg(Feedback.rating))
            .filter(Feedback.zoo_id == zoo.id)
            .scalar()
            or 0
        )
        min_price = (
            db.session.query(func.min(Service.price))
            .filter(Service.zoo_id == zoo.id)
            .scalar()
            or 0
        )

        zoos.append(
            {
                "id": zoo.id,
                "name": zoo.name,
                "type": type_name,
                "type_slug": type_slug,
                "location": zoo.location or "Location unavailable",
                "description": zoo.description or "Discover curated wildlife experiences.",
                "image_url": zoo.image_url or "https://images.unsplash.com/photo-1546182990-dffeafbe841d?w=1200&q=80",
                "rating": round(float(rating_value), 1),
                "price": float(min_price or 0),
            }
        )

    return render_template("visitor/zoos.html", zoos=zoos)

@visitor_bp.get("/zoos/<int:zoo_id>")
def zoo_detail(zoo_id: int):
    zoo = db.session.get(Zoo, zoo_id)
    if zoo:
        zoo_animals = Animal.query.filter_by(zoo_id=zoo_id).order_by(Animal.id.asc()).all()
        zoo_services = Service.query.filter_by(zoo_id=zoo_id).order_by(Service.id.asc()).all()
        return render_template("visitor/zoo_detail.html", zoo=zoo, animals=zoo_animals, services=zoo_services)

    abort(404)

@visitor_bp.get("/animals")
def animals():
    zoo_animals = _maybe_filter_by_selected_zoo(Animal.query, Animal).order_by(Animal.id.asc()).all()
    habitat_count = 0
    try:
        habitat_count = len({(getattr(a, "habitat", None) or "").strip() for a in zoo_animals if (getattr(a, "habitat", None) or "").strip()})
    except Exception:
        habitat_count = 0

    return render_template(
        "visitor/animals.html",
        animals=zoo_animals,
        animal_count=(len(zoo_animals) if isinstance(zoo_animals, list) else 0),
        habitat_count=habitat_count,
    )

@visitor_bp.get("/animals/<int:animal_id>")
def animal_detail(animal_id: int):
    animal = db.session.get(Animal, animal_id)
    if animal:
        selected_zoo_id = _selected_zoo_id()
        if selected_zoo_id and int(getattr(animal, "zoo_id", 0) or 0) != selected_zoo_id:
            abort(404)
        return render_template("visitor/animal_detail.html", animal=animal)

    abort(404)

@visitor_bp.route("/bookings", methods=["GET", "POST"])
@visitor_login_required
def my_bookings():
    user = _current_user()
    if not user:
        return _require_visitor_login()

    if request.method == "POST":
        selected_zoo_id = _selected_zoo_id()
        service_id = request.form.get("service_id", type=int)
        date = (request.form.get("date") or "").strip()
        time = (request.form.get("time") or "").strip()
        guests = request.form.get("guests", type=int) or 1

        if not service_id:
            flash("Please select a service to book.", "error")
            return redirect(url_for("visitor.my_bookings"))
        service = db.session.get(Service, service_id)
        if not service:
            flash("Selected service was not found.", "error")
            return redirect(url_for("visitor.my_bookings"))

        if selected_zoo_id and int(getattr(service, "zoo_id", 0) or 0) != selected_zoo_id:
            flash("Selected service is not available for your chosen zoo.", "error")
            return redirect(url_for("visitor.my_bookings"))
        if not date:
            flash("Please choose a date.", "error")
            return redirect(url_for("visitor.my_bookings"))
        if not time:
            flash("Please choose a time.", "error")
            return redirect(url_for("visitor.my_bookings"))
        if guests < 1:
            guests = 1

        booking = Booking(
            id=_generate_booking_id(),
            user_id=(user.id if _booking_supports_user_id() else None),
            visitor_name=(user.full_name or user.email),
            service_id=service.id,
            zoo_id=service.zoo_id,
            service_name=service.name,
            date=date,
            time=time,
            guests=guests,
            status="Pending",
            amount=float(service.price or 0),
            payment_status="unpaid",
        )
        db.session.add(booking)
        db.session.commit()
        flash("Booking created. Check your bookings list below.", "success")
        return redirect(url_for("visitor.my_bookings"))

    bookings = (
        Booking.query.filter(_booking_owner_filter(user))
        .order_by(Booking.created_at.desc())
        .all()
    )
    selected_zoo_id = _selected_zoo_id()
    if selected_zoo_id:
        bookings = [b for b in bookings if int(getattr(b, "zoo_id", 0) or 0) == selected_zoo_id]
    services = _maybe_filter_by_selected_zoo(Service.query, Service).order_by(Service.name.asc()).all()

    total_bookings = len(bookings)
    total_spent = sum((b.amount or 0) for b in bookings)
    points = total_bookings * 40

    status_counts: dict[str, int] = {"Confirmed": 0, "Pending": 0, "Cancelled": 0, "Other": 0}
    for b in bookings:
        key = (b.status or "Other").title()
        if key not in status_counts:
            key = "Other"
        status_counts[key] += 1

    upcoming = [b for b in bookings if (b.status or "").lower() in {"confirmed", "pending"}]
    next_booking = upcoming[0] if upcoming else None

    return render_template(
        "visitor/bookings.html",
        bookings=bookings,
        services=services,
        next_booking=next_booking,
        total_bookings=total_bookings,
        total_spent=total_spent,
        points=points,
        status_counts=status_counts,
    )


@visitor_bp.post("/bookings/<booking_id>/cancel")
@visitor_login_required
def cancel_booking(booking_id: str):
    user = _current_user()
    if not user:
        return _require_visitor_login()

    booking_query = Booking.query.filter(_booking_owner_filter_by_id(user, booking_id))
    selected_zoo_id = _selected_zoo_id()
    if selected_zoo_id:
        booking_query = booking_query.filter(Booking.zoo_id == selected_zoo_id)
    booking = booking_query.first()
    if not booking:
        abort(404)

    if (booking.status or "").lower() == "cancelled":
        flash("That booking is already cancelled.", "error")
        return redirect(url_for("visitor.my_bookings"))

    booking.status = "Cancelled"
    db.session.commit()
    flash("Booking cancelled.", "success")
    return redirect(url_for("visitor.my_bookings"))


@visitor_bp.post("/bookings/<booking_id>/reschedule")
@visitor_login_required
def reschedule_booking(booking_id: str):
    user = _current_user()
    if not user:
        return _require_visitor_login()

    booking_query = Booking.query.filter(_booking_owner_filter_by_id(user, booking_id))
    selected_zoo_id = _selected_zoo_id()
    if selected_zoo_id:
        booking_query = booking_query.filter(Booking.zoo_id == selected_zoo_id)
    booking = booking_query.first()
    if not booking:
        abort(404)

    if (booking.status or "").lower() == "cancelled":
        flash("Cancelled bookings can’t be rescheduled.", "error")
        return redirect(url_for("visitor.my_bookings"))

    date = (request.form.get("date") or "").strip()
    time = (request.form.get("time") or "").strip()
    guests = request.form.get("guests", type=int) or 1

    if not date:
        flash("Please choose a date.", "error")
        return redirect(url_for("visitor.my_bookings"))
    if not time:
        flash("Please choose a time.", "error")
        return redirect(url_for("visitor.my_bookings"))
    if guests < 1:
        guests = 1

    booking.date = date
    booking.time = time
    booking.guests = guests
    # Reschedule implies reconfirmation
    booking.status = "Pending"
    db.session.commit()
    flash("Booking updated.", "success")
    return redirect(url_for("visitor.my_bookings"))

@visitor_bp.get("/events")
def events():
    # If a Visitor is logged in, require Zoo selection so the page matches
    # the admin module's zoo-scoped view.
    if session.get("user_id") and session.get("role") == "visitor" and not session.get("selected_zoo_id"):
        next_url = request.full_path
        if next_url.endswith("?"):
            next_url = next_url[:-1]
        return redirect(url_for("visitor.choose_zoo", next=next_url))

    selected_zoo_id = _selected_zoo_id()
    query = Event.query
    if selected_zoo_id:
        # Admin events are zoo-scoped; do the same here (exclude global NULL zoo events).
        query = query.filter(Event.zoo_id == selected_zoo_id)

    events = query.order_by(Event.id.asc()).all()
    return render_template("visitor/events.html", events=events)

@visitor_bp.get("/services")
def services():
    if session.get("user_id") and session.get("role") == "visitor" and not session.get("selected_zoo_id"):
        next_url = request.full_path
        if next_url.endswith("?"):
            next_url = next_url[:-1]
        return redirect(url_for("visitor.choose_zoo", next=next_url))

    all_services = _maybe_filter_by_selected_zoo(Service.query, Service).order_by(Service.id.asc()).all()
    return render_template("visitor/services.html", services=all_services)

@visitor_bp.get("/promotions")
def promotions():
    if session.get("user_id") and session.get("role") == "visitor" and not session.get("selected_zoo_id"):
        next_url = request.full_path
        if next_url.endswith("?"):
            next_url = next_url[:-1]
        return redirect(url_for("visitor.choose_zoo", next=next_url))

    selected_zoo_id = _selected_zoo_id()
    query = Promotion.query

    # Keep visitor view consistent with the admin module:
    # show only the current/selected zoo's promotions (no cross-zoo fallbacks).
    if selected_zoo_id:
        query = query.filter(Promotion.zoo_id == selected_zoo_id)

    # Some environments keep promotions scoped by country in the admin UI.
    # Apply the same constraint when the model supports it.
    if getattr(Promotion, "country", None) is not None:
        query = query.filter(Promotion.country == "Philippines")

    promos = query.order_by(Promotion.id.asc()).all()

    ending_soon_count = 0
    try:
        from datetime import date

        today = date.today()
        for promo in promos:
            valid_until = None
            if isinstance(promo, dict):
                valid_until = (promo.get("valid_until") or "").strip() or None
            else:
                valid_until = (getattr(promo, "valid_until", None) or "").strip() or None

            if not valid_until:
                continue

            # Expecting ISO date strings (YYYY-MM-DD). If not parseable, ignore.
            try:
                y, m, d = valid_until.split("-", 2)
                until_date = date(int(y), int(m), int(d))
            except Exception:
                continue

            days_left = (until_date - today).days
            if 0 <= days_left <= 7:
                ending_soon_count += 1
    except Exception:
        ending_soon_count = 0

    return render_template(
        "visitor/promotions.html",
        promotions=promos,
        ending_soon_count=ending_soon_count,
    )

@visitor_bp.route("/feedback", methods=["GET", "POST"])
def feedback():
    user = _current_user()

    if request.method == "POST":
        if not (session.get("user_id") and session.get("role") == "visitor"):
            return _require_visitor_login()

        selected_zoo_id = _selected_zoo_id()
        zoo_id = request.form.get("zoo_id", type=int)
        if selected_zoo_id:
            zoo_id = selected_zoo_id
        rating = request.form.get("rating", type=int)
        comment = (request.form.get("comment") or "").strip()
        try:
            create_visitor_feedback(
                user=user,
                zoo_id=zoo_id,
                rating=rating,
                comment=comment,
            )
        except FeedbackValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("visitor.feedback") + "#write-review")
        except FeedbackAuthorizationError as exc:
            flash(str(exc), "error")
            return _require_visitor_login()

        flash("Thanks! Your review has been submitted.", "success")
        return redirect(url_for("visitor.feedback"))

    zoos = Zoo.query.order_by(Zoo.name.asc()).all()

    selected_zoo_id = request.args.get("zoo_id", type=int) or _selected_zoo_id()
    sort = (request.args.get("sort") or "recent").strip().lower()
    page = request.args.get("page", type=int) or 1
    if page < 1:
        page = 1

    per_page = 10

    base_query = Feedback.query
    stats_query = db.session.query(
        func.count(Feedback.id),
        func.avg(Feedback.rating),
    )

    if selected_zoo_id:
        base_query = base_query.filter(Feedback.zoo_id == selected_zoo_id)
        stats_query = stats_query.filter(Feedback.zoo_id == selected_zoo_id)

    if sort in {"highest", "highest_rated", "rating"}:
        base_query = base_query.order_by(Feedback.rating.desc(), Feedback.id.desc())
        sort = "highest"
    else:
        base_query = base_query.order_by(Feedback.id.desc())
        sort = "recent"

    stats = stats_query.one()
    review_count = int(stats[0] or 0)
    avg_rating = float(stats[1] or 0)

    pages = max(1, int(math.ceil(review_count / per_page)) if review_count else 1)
    if page > pages:
        page = pages

    feedbacks = (
        base_query
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return render_template(
        "visitor/feedback.html",
        feedbacks=feedbacks,
        zoos=zoos,
        review_count=review_count,
        avg_rating=avg_rating,
        page=page,
        pages=pages,
        sort=sort,
        selected_zoo_id=selected_zoo_id,
        current_user_id=(user.id if user else None),
        current_user_aliases=(list(_feedback_owner_aliases(user)) if user else []),
    )


@visitor_bp.post("/feedback/<int:feedback_id>/update")
@visitor_login_required
def update_feedback(feedback_id: int):
    user = _current_user()
    if not user:
        return _require_visitor_login()

    feedback = db.session.get(Feedback, feedback_id)
    selected_zoo_id = _selected_zoo_id()
    if selected_zoo_id and feedback and int(getattr(feedback, "zoo_id", 0) or 0) != selected_zoo_id:
        abort(404)
    zoo_id = request.form.get("zoo_id", type=int)
    if selected_zoo_id:
        zoo_id = selected_zoo_id
    rating = request.form.get("rating", type=int)
    comment = (request.form.get("comment") or "").strip()
    try:
        update_visitor_feedback(
            feedback=feedback,
            user=user,
            zoo_id=zoo_id,
            rating=rating,
            comment=comment,
        )
    except FeedbackValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("visitor.feedback"))
    except FeedbackAuthorizationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("visitor.feedback"))

    flash("Your review was updated.", "success")
    return redirect(url_for("visitor.feedback"))


@visitor_bp.post("/feedback/<int:feedback_id>/delete")
@visitor_login_required
def delete_feedback(feedback_id: int):
    user = _current_user()
    if not user:
        return _require_visitor_login()

    feedback = db.session.get(Feedback, feedback_id)
    selected_zoo_id = _selected_zoo_id()
    if selected_zoo_id and feedback and int(getattr(feedback, "zoo_id", 0) or 0) != selected_zoo_id:
        abort(404)
    try:
        delete_visitor_feedback(feedback=feedback, user=user)
    except FeedbackValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("visitor.feedback"))
    except FeedbackAuthorizationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("visitor.feedback"))

    flash("Your review was deleted.", "success")
    return redirect(url_for("visitor.feedback"))

@visitor_bp.route("/profile", methods=["GET", "POST"])
@visitor_login_required
def profile():
    user = _current_user()
    if not user:
        return _require_visitor_login()

    show_tab = (request.args.get("tab") or "profile").strip().lower()
    allowed_tabs = {"profile", "bookings", "security", "notifications", "visits", "payments", "linked-accounts", "danger"}
    if show_tab not in allowed_tabs:
        show_tab = "profile"

    bookings = Booking.query.filter(_booking_owner_filter(user)).order_by(Booking.created_at.desc()).all()
    review_aliases = list(_feedback_owner_aliases(user))
    reviews = (
        Feedback.query
        .filter(or_(Feedback.user_id == user.id, Feedback.visitor_name.in_(review_aliases)))
        .order_by(Feedback.id.desc())
        .all()
    )
    payment_history = (
        BookingPayment.query
        .join(Booking, BookingPayment.booking_id == Booking.id)
        .filter(or_(Booking.user_id == user.id, BookingPayment.payer_user_id == user.id))
        .order_by(BookingPayment.created_at.desc())
        .all()
    )

    if request.method == "POST":
        action = (request.form.get("action") or show_tab or "profile").strip().lower()

        if action == "profile":
            full_name = (request.form.get("full_name") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            username = (request.form.get("username") or "").strip() or None

            if not full_name:
                flash("Full name is required.", "error")
                return redirect(url_for("visitor.profile", tab="profile", edit=1))

            if email and email != user.email:
                existing = User.query.filter(User.email == email, User.id != user.id).first()
                if existing:
                    flash("That email is already in use.", "error")
                    return redirect(url_for("visitor.profile", tab="profile", edit=1))
                user.email = email

            if username and username != user.username:
                existing_un = User.query.filter(User.username == username, User.id != user.id).first()
                if existing_un:
                    flash("That username is already in use.", "error")
                    return redirect(url_for("visitor.profile", tab="profile", edit=1))
                user.username = username

            profile_picture = request.files.get("profile_picture")
            if profile_picture and profile_picture.filename:
                uploaded_url = _save_uploaded_image(profile_picture, 'profile_pictures')
                if uploaded_url:
                    user.profile_image = uploaded_url

            user.full_name = full_name
            db.session.commit()
            session["full_name"] = user.full_name
            flash("Profile updated.", "success")
            return redirect(url_for("visitor.profile", tab="profile"))

        if action == "security":
            current_password = request.form.get("current_password") or ""
            new_password = request.form.get("new_password") or ""
            confirm_password = request.form.get("confirm_password") or ""

            if not user.check_password(current_password):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("visitor.profile", tab="security"))
            if len(new_password) < 8:
                flash("New password must be at least 8 characters.", "error")
                return redirect(url_for("visitor.profile", tab="security"))
            if new_password != confirm_password:
                flash("New password and confirmation do not match.", "error")
                return redirect(url_for("visitor.profile", tab="security"))

            user.set_password(new_password)
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("visitor.profile", tab="security"))

        if action == "notifications":
            session["visitor_notification_prefs"] = {
                "email_bookings": bool(request.form.get("email_bookings")),
                "email_promos": bool(request.form.get("email_promos")),
                "sms_alerts": bool(request.form.get("sms_alerts")),
                "visit_reminders": bool(request.form.get("visit_reminders")),
            }
            flash("Notification preferences saved.", "success")
            return redirect(url_for("visitor.profile", tab="notifications"))

        flash("Unknown profile action.", "error")
        return redirect(url_for("visitor.profile", tab=show_tab))

    notification_prefs = session.get("visitor_notification_prefs")
    if not isinstance(notification_prefs, dict):
        notification_prefs = {
            "email_bookings": True,
            "email_promos": True,
            "sms_alerts": False,
            "visit_reminders": True,
        }

    total_spent = db.session.query(func.sum(Booking.amount)).filter(_booking_owner_filter(user)).scalar() or 0
    active_bookings = sum(1 for b in bookings if (b.status or "").lower() in {"confirmed", "pending"})
    profile_image_url = url_for("uploaded_file", filename=user.profile_image) if getattr(user, "profile_image", None) else None
    linked_accounts = {
        "email": user.email,
        "username": user.username or "Not set",
        "member_since": user.created_at.strftime("%B %Y") if user.created_at else "Unknown",
    }

    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        username = (request.form.get("username") or "").strip() or None

        if not full_name:
            flash("Full name is required.", "error")
            return redirect(url_for("visitor.profile", edit=1))

        if email and email != user.email:
            existing = User.query.filter(User.email == email, User.id != user.id).first()
            if existing:
                flash("That email is already in use.", "error")
                return redirect(url_for("visitor.profile", edit=1))
            user.email = email

        if username and username != user.username:
            existing_un = User.query.filter(User.username == username, User.id != user.id).first()
            if existing_un:
                flash("That username is already in use.", "error")
                return redirect(url_for("visitor.profile", edit=1))
            user.username = username

        user.full_name = full_name
        db.session.commit()

        session["full_name"] = user.full_name
        flash("Profile updated.", "success")
        return redirect(url_for("visitor.profile"))

    bookings_count = Booking.query.filter(_booking_owner_filter(user)).count()
    review_aliases = list(_feedback_owner_aliases(user))
    reviews_count = (
        Feedback.query
        .filter(or_(Feedback.user_id == user.id, Feedback.visitor_name.in_(review_aliases)))
        .count()
    )
    total_spent = (
        db.session.query(func.sum(Booking.amount))
        .filter(_booking_owner_filter(user))
        .scalar()
        or 0
    )
    points = int(bookings_count * 40)

    return render_template(
        "visitor/profile.html",
        user=user,
        bookings_count=bookings_count,
        reviews_count=reviews_count,
        total_spent=float(total_spent),
        points=points,
        bookings=bookings,
        total_bookings=bookings_count,
        active_bookings=active_bookings,
        recent_reviews=reviews[:5],
        payment_history=payment_history,
        notification_prefs=notification_prefs,
        profile_image_url=profile_image_url,
        linked_accounts=linked_accounts,
        show_tab=show_tab,
        edit=(request.args.get("edit") == "1"),
    )

@visitor_bp.get("/park-info")
def park_info():
    zoo_id = request.args.get("zoo_id", type=int) or _selected_zoo_id()
    if not zoo_id:
        return redirect(url_for("visitor.choose_zoo"))
    zoo = db.session.get(Zoo, zoo_id)
    if not zoo:
        abort(404)
    return render_template("visitor/park_info.html", zoo=zoo)


@visitor_bp.get("/landing")
def general_landing():
    return redirect(url_for("visitor.home"), code=301)


@visitor_bp.get("/visitor-landing")
def visitor_landing():
    return redirect(url_for("visitor.home"), code=301)


@visitor_bp.get("/zoo-homepage")
def zoo_homepage():
    return redirect(url_for("visitor.home"), code=301)


@visitor_bp.get("/exclusive-offers")
def exclusive_offers():
    return redirect(url_for("visitor.promotions"), code=301)


@visitor_bp.get("/wildlife-directory")
def wildlife_directory():
    return redirect(url_for("visitor.animals"), code=301)


@visitor_bp.get("/park-events")
def park_events():
    return redirect(url_for("visitor.events"), code=301)


@visitor_bp.get("/experiences-services")
def experiences_services():
    return redirect(url_for("visitor.services"), code=301)


@visitor_bp.route("/checkout", methods=["GET", "POST"])
@visitor_login_required
def checkout():
    user = _current_user()
    if not user:
        return _require_visitor_login()

    if request.method == "POST":
        booking_id = (request.form.get("booking_id") or "").strip()
        payment_method = (request.form.get("payment_method") or "").strip()

        if not booking_id:
            flash("Booking ID is required for checkout.", "error")
            return redirect(url_for("visitor.checkout"))

        booking_query = Booking.query.filter(_booking_owner_filter_by_id(user, booking_id))
        selected_zoo_id = _selected_zoo_id()
        if selected_zoo_id:
            booking_query = booking_query.filter(Booking.zoo_id == selected_zoo_id)
        booking = booking_query.first()
        if not booking:
            abort(404)

        try:
            payment = process_booking_checkout(
                booking=booking,
                payer=user,
                payment_method=payment_method,
            )
        except BookingValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("visitor.checkout", booking_id=booking_id))
        except BookingAuthorizationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("visitor.checkout"))

        flash(f"Payment successful. Reference: {payment.reference}", "success")
        return redirect(url_for("visitor.my_bookings"))

    booking_id = (request.args.get("booking_id") or "").strip()

    base_query = Booking.query.filter(_booking_owner_filter(user)).order_by(Booking.created_at.desc())
    selected_zoo_id = _selected_zoo_id()
    if selected_zoo_id:
        base_query = base_query.filter(Booking.zoo_id == selected_zoo_id)
    unpaid_bookings = [b for b in base_query.all() if (b.payment_status or "unpaid").lower() != "paid"]

    booking = None
    if booking_id:
        booking_query = Booking.query.filter(_booking_owner_filter_by_id(user, booking_id))
        if selected_zoo_id:
            booking_query = booking_query.filter(Booking.zoo_id == selected_zoo_id)
        booking = booking_query.first()
        if not booking:
            abort(404)
    elif unpaid_bookings:
        booking = unpaid_bookings[0]

    return render_template(
        "visitor/checkout.html",
        booking=booking,
        unpaid_bookings=unpaid_bookings,
        supported_methods=["card", "gcash", "cash_on_arrival"],
    )


@visitor_bp.get("/bookings/<booking_id>/checkout")
@visitor_login_required
def checkout_booking(booking_id: str):
    return redirect(url_for("visitor.checkout", booking_id=booking_id), code=302)
