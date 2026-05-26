from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request, session
from sqlalchemy import or_, inspect

from models import (
    Animal,
    Booking,
    Event,
    Feedback,
    Promotion,
    Service,
    StaffTask,
    SubscriptionPlan,
    SubscriptionPayment,
    User,
    Zoo,
    ZooAdminFeedback,
    ZooAdminFeedbackReply,
    ZooSubscription,
    ZooZone,
    db,
)
from services import (
    BookingAuthorizationError,
    BookingValidationError,
    FeedbackAuthorizationError,
    FeedbackValidationError,
    SubscriptionValidationError,
    assign_booking_to_staff,
    cancel_zoo_subscription,
    change_zoo_subscription_plan,
    create_visitor_feedback,
    delete_visitor_feedback,
    feedback_aliases_for_user,
    is_feedback_owned_by_user,
    process_booking_checkout,
    renew_zoo_subscription,
    update_visitor_feedback,
)

api_bp = Blueprint("api", __name__)


def _error(message: str, status: int = 400, code: str = "bad_request"):
    return jsonify({"error": code, "message": message}), status


def _current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, int(user_id))


def _set_auth_session(user: User):
    session.permanent = True
    session["user_id"] = user.id
    session["role"] = user.role
    session["full_name"] = user.full_name


def _booking_supports_user_id() -> bool:
    try:
        columns = inspect(db.engine).get_columns("bookings")
        return any((c.get("name") or "").lower() == "user_id" for c in columns)
    except Exception:
        return False


def _json_payload() -> dict:
    payload = request.get_json(silent=True)
    if payload is None:
        raise ValueError("JSON body is required.")
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object.")
    return payload


def _str_field(payload: dict, key: str, *, required: bool = False, lower: bool = False):
    value = payload.get(key)
    if value is None:
        if required:
            raise ValueError(f"{key} is required.")
        return None
    value = str(value).strip()
    if required and not value:
        raise ValueError(f"{key} is required.")
    if not value:
        return None
    return value.lower() if lower else value


def _int_field(payload: dict, key: str, *, required: bool = False, minimum: int | None = None, maximum: int | None = None):
    value = payload.get(key)
    if value is None:
        if required:
            raise ValueError(f"{key} is required.")
        return None

    try:
        value = int(value)
    except Exception as exc:
        raise ValueError(f"{key} must be numeric.") from exc

    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{key} must be <= {maximum}.")
    return value


def _float_field(payload: dict, key: str, *, required: bool = False, minimum: float | None = None):
    value = payload.get(key)
    if value is None:
        if required:
            raise ValueError(f"{key} is required.")
        return None

    try:
        value = float(value)
    except Exception as exc:
        raise ValueError(f"{key} must be numeric.") from exc

    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be >= {minimum}.")
    return value


def _parse_date_yyyy_mm_dd(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def require_role(*roles: str):
    def _decorator(view_func):
        @wraps(view_func)
        def _wrapped(*args, **kwargs):
            user = _current_user()
            if not user:
                return _error("Authentication required.", 401, "unauthorized")
            if (user.status or "active") != "active":
                return _error("Account is suspended.", 403, "forbidden")
            if user.role not in roles:
                return _error("Insufficient role for this endpoint.", 403, "forbidden")
            return view_func(*args, **kwargs)

        return _wrapped

    return _decorator


def _serialize_user(user: User):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
        "zoo_id": user.zoo_id,
        "status": user.status,
        "profile_image": user.profile_image,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _serialize_booking(booking: Booking):
    return {
        "id": booking.id,
        "zoo_id": booking.zoo_id,
        "service_id": booking.service_id,
        "service_name": booking.service_name,
        "visitor_name": booking.visitor_name,
        "date": booking.date,
        "time": booking.time,
        "guests": booking.guests,
        "status": booking.status,
        "amount": float(booking.amount or 0),
        "payment_status": booking.payment_status,
        "payment_reference": booking.payment_reference,
        "assigned_staff_user_id": booking.assigned_staff_user_id,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
    }


def _serialize_feedback(feedback: Feedback):
    return {
        "id": feedback.id,
        "zoo_id": feedback.zoo_id,
        "user_id": feedback.user_id,
        "visitor_name": feedback.visitor_name,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "date": feedback.date,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    }


def _serialize_system_feedback(feedback: ZooAdminFeedback):
    latest_reply = None
    if feedback.replies:
        latest_reply = sorted(feedback.replies, key=lambda item: item.created_at)[-1]

    return {
        "id": feedback.id,
        "zoo_id": feedback.zoo_id,
        "zoo_name": feedback.zoo.name if feedback.zoo else None,
        "user_id": feedback.user_id,
        "category": feedback.category,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
        "latest_reply": {
            "id": latest_reply.id,
            "reply_text": latest_reply.reply_text,
            "created_at": latest_reply.created_at.isoformat() if latest_reply and latest_reply.created_at else None,
        } if latest_reply else None,
    }


def _current_zoo_id_for_user(user: User) -> int | None:
    return int(user.zoo_id) if user and user.zoo_id else None


def _require_user_zoo(user: User):
    zoo_id = _current_zoo_id_for_user(user)
    if not zoo_id:
        raise ValueError("Your account is not linked to an establishment.")
    return zoo_id


def _generate_booking_id() -> str:
    for _ in range(10):
        booking_id = f"BK-{secrets.token_hex(5).upper()}"
        if not Booking.query.filter_by(id=booking_id).first():
            return booking_id
    raise RuntimeError("Unable to generate a unique booking ID.")


@api_bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "zootique-backend"})


@api_bp.post("/auth/login")
def api_login():
    try:
        payload = _json_payload()
        email = _str_field(payload, "email", required=True, lower=True)
        password = _str_field(payload, "password", required=True)
        role = _str_field(payload, "role")

        query = User.query.filter_by(email=email)
        if role:
            query = query.filter_by(role=role)
        user = query.first()

        if not user or not user.check_password(password or ""):
            return _error("Invalid credentials.", 401, "unauthorized")
        if (user.status or "active") != "active":
            return _error("Account is suspended.", 403, "forbidden")

        _set_auth_session(user)
        return jsonify({"user": _serialize_user(user)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.post("/auth/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@api_bp.get("/auth/me")
def api_me():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")
    return jsonify({"user": _serialize_user(user)})


@api_bp.get("/visitor/profile")
@require_role("visitor")
def visitor_profile_get():
    user = _current_user()
    return jsonify({"profile": _serialize_user(user)})


@api_bp.patch("/visitor/profile")
@require_role("visitor")
def visitor_profile_patch():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    try:
        payload = _json_payload()
        full_name = _str_field(payload, "full_name")
        username = _str_field(payload, "username")
        email = _str_field(payload, "email", lower=True)

        if email and email != user.email:
            if User.query.filter(User.email == email, User.id != user.id).first():
                return _error("Email is already in use.", 409, "conflict")
            user.email = email

        if "username" in payload:
            if username and username != user.username:
                if User.query.filter(User.username == username, User.id != user.id).first():
                    return _error("Username is already in use.", 409, "conflict")
            user.username = username

        if full_name is not None:
            if not full_name:
                return _error("full_name cannot be empty.", 400, "validation_error")
            user.full_name = full_name

        db.session.commit()
        session["full_name"] = user.full_name
        return jsonify({"profile": _serialize_user(user)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.get("/visitor/bookings")
@require_role("visitor")
def visitor_bookings():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    status = (request.args.get("status") or "").strip().lower()

    if _booking_supports_user_id():
        query = Booking.query.filter_by(user_id=user.id)
    else:
        aliases = list(feedback_aliases_for_user(user))
        query = Booking.query.filter(Booking.visitor_name.in_(aliases))

    if status:
        query = query.filter(db.func.lower(Booking.status) == status)

    bookings = query.order_by(Booking.created_at.desc()).limit(200).all()
    return jsonify({"bookings": [_serialize_booking(item) for item in bookings]})


@api_bp.post("/visitor/bookings")
@require_role("visitor")
def visitor_create_booking():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    try:
        payload = _json_payload()
        service_id = _int_field(payload, "service_id", required=True, minimum=1)
        date_value = _str_field(payload, "date", required=True)
        time_value = _str_field(payload, "time", required=True)
        guests = _int_field(payload, "guests", minimum=1) or 1

        service = db.session.get(Service, service_id)
        if not service:
            return _error("Service not found.", 404, "not_found")

        booking = Booking(
            id=_generate_booking_id(),
            zoo_id=service.zoo_id,
            service_id=service.id,
            user_id=(user.id if _booking_supports_user_id() else None),
            visitor_name=(user.full_name or user.email),
            service_name=service.name,
            date=date_value,
            time=time_value,
            guests=guests,
            status="Pending",
            amount=float(service.price or 0),
            payment_status="unpaid",
        )
        db.session.add(booking)
        db.session.commit()
        return jsonify({"booking": _serialize_booking(booking)}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.patch("/visitor/bookings/<booking_id>/reschedule")
@require_role("visitor")
def visitor_reschedule_booking(booking_id: str):
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    if _booking_supports_user_id():
        booking = Booking.query.filter_by(id=booking_id, user_id=user.id).first()
    else:
        booking = Booking.query.filter(
            Booking.id == booking_id,
            Booking.visitor_name.in_(list(feedback_aliases_for_user(user))),
        ).first()
    if not booking:
        return _error("Booking not found.", 404, "not_found")

    if (booking.status or "").lower() == "cancelled":
        return _error("Cancelled bookings cannot be rescheduled.", 400, "validation_error")

    try:
        payload = _json_payload()
        date_value = _str_field(payload, "date", required=True)
        time_value = _str_field(payload, "time", required=True)
        guests = _int_field(payload, "guests", minimum=1)

        booking.date = date_value
        booking.time = time_value
        if guests:
            booking.guests = guests
        booking.status = "Pending"
        db.session.commit()
        return jsonify({"booking": _serialize_booking(booking)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.post("/visitor/bookings/<booking_id>/cancel")
@require_role("visitor")
def visitor_cancel_booking(booking_id: str):
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    if _booking_supports_user_id():
        booking = Booking.query.filter_by(id=booking_id, user_id=user.id).first()
    else:
        booking = Booking.query.filter(
            Booking.id == booking_id,
            Booking.visitor_name.in_(list(feedback_aliases_for_user(user))),
        ).first()
    if not booking:
        return _error("Booking not found.", 404, "not_found")

    booking.status = "Cancelled"
    db.session.commit()
    return jsonify({"booking": _serialize_booking(booking)})


@api_bp.post("/visitor/bookings/<booking_id>/checkout")
@require_role("visitor")
def visitor_checkout_booking(booking_id: str):
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    if _booking_supports_user_id():
        booking = Booking.query.filter_by(id=booking_id, user_id=user.id).first()
    else:
        booking = Booking.query.filter(
            Booking.id == booking_id,
            Booking.visitor_name.in_(list(feedback_aliases_for_user(user))),
        ).first()

    if not booking:
        return _error("Booking not found.", 404, "not_found")

    payload = request.get_json(silent=True) or {}
    payment_method = payload.get("payment_method") or "card"

    try:
        payment = process_booking_checkout(
            booking=booking,
            payer=user,
            payment_method=payment_method,
        )
    except BookingValidationError as exc:
        return _error(str(exc), 400, "validation_error")
    except BookingAuthorizationError as exc:
        return _error(str(exc), 403, "forbidden")

    return jsonify(
        {
            "booking_id": booking.id,
            "payment_reference": payment.reference,
            "payment_status": payment.status,
            "booking_status": booking.status,
        }
    )


@api_bp.get("/visitor/feedback")
@require_role("visitor")
def visitor_feedback_list():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    zoo_id = request.args.get("zoo_id", type=int)
    only_mine = (request.args.get("only_mine") or "").strip().lower() in {"1", "true", "yes"}

    query = Feedback.query
    if zoo_id:
        query = query.filter_by(zoo_id=zoo_id)

    if only_mine:
        aliases = list(feedback_aliases_for_user(user))
        query = query.filter(or_(Feedback.user_id == user.id, Feedback.visitor_name.in_(aliases)))

    feedbacks = query.order_by(Feedback.id.desc()).limit(300).all()
    return jsonify({"feedbacks": [_serialize_feedback(item) for item in feedbacks]})


@api_bp.post("/visitor/feedback")
@require_role("visitor")
def visitor_feedback_create():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    try:
        payload = _json_payload()
        feedback = create_visitor_feedback(
            user=user,
            zoo_id=_int_field(payload, "zoo_id", required=True, minimum=1),
            rating=_int_field(payload, "rating", required=True, minimum=1, maximum=5),
            comment=_str_field(payload, "comment", required=True),
        )
        return jsonify({"feedback": _serialize_feedback(feedback)}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")
    except FeedbackValidationError as exc:
        return _error(str(exc), 400, "validation_error")
    except FeedbackAuthorizationError as exc:
        return _error(str(exc), 403, "forbidden")


@api_bp.patch("/visitor/feedback/<int:feedback_id>")
@require_role("visitor")
def visitor_feedback_patch(feedback_id: int):
    user = _current_user()
    feedback = db.session.get(Feedback, feedback_id)
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    try:
        payload = _json_payload()
        updated = update_visitor_feedback(
            feedback=feedback,
            user=user,
            zoo_id=_int_field(payload, "zoo_id", required=True, minimum=1),
            rating=_int_field(payload, "rating", required=True, minimum=1, maximum=5),
            comment=_str_field(payload, "comment", required=True),
        )
        return jsonify({"feedback": _serialize_feedback(updated)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")
    except FeedbackValidationError as exc:
        return _error(str(exc), 400, "validation_error")
    except FeedbackAuthorizationError as exc:
        return _error(str(exc), 403, "forbidden")


@api_bp.delete("/visitor/feedback/<int:feedback_id>")
@require_role("visitor")
def visitor_feedback_delete(feedback_id: int):
    user = _current_user()
    feedback = db.session.get(Feedback, feedback_id)
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    try:
        delete_visitor_feedback(feedback=feedback, user=user)
        return jsonify({"ok": True})
    except FeedbackValidationError as exc:
        return _error(str(exc), 400, "validation_error")
    except FeedbackAuthorizationError as exc:
        return _error(str(exc), 403, "forbidden")


@api_bp.get("/staff/profile")
@require_role("zoo_staff")
def staff_profile_get():
    user = _current_user()
    return jsonify({"profile": _serialize_user(user)})


@api_bp.patch("/staff/profile")
@require_role("zoo_staff")
def staff_profile_patch():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    try:
        payload = _json_payload()
        full_name = _str_field(payload, "full_name")
        username = _str_field(payload, "username")
        email = _str_field(payload, "email", lower=True)

        if email and email != user.email:
            if User.query.filter(User.email == email, User.id != user.id).first():
                return _error("Email is already in use.", 409, "conflict")
            user.email = email

        if "username" in payload:
            if username and username != user.username:
                if User.query.filter(User.username == username, User.id != user.id).first():
                    return _error("Username is already in use.", 409, "conflict")
            user.username = username

        if full_name is not None:
            if not full_name:
                return _error("full_name cannot be empty.", 400, "validation_error")
            user.full_name = full_name

        db.session.commit()
        session["full_name"] = user.full_name
        return jsonify({"profile": _serialize_user(user)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.get("/staff/tasks")
@require_role("zoo_staff")
def staff_tasks_list():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    tasks = (
        StaffTask.query
        .filter_by(zoo_id=user.zoo_id, assigned_to_user_id=user.id)
        .order_by(StaffTask.due_date.asc().nullslast(), StaffTask.created_at.desc())
        .limit(300)
        .all()
    )
    return jsonify(
        {
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                    "status": t.status,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tasks
            ]
        }
    )


@api_bp.patch("/staff/tasks/<int:task_id>/status")
@require_role("zoo_staff")
def staff_tasks_status_patch(task_id: int):
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    task = StaffTask.query.filter_by(id=task_id, zoo_id=user.zoo_id, assigned_to_user_id=user.id).first()
    if not task:
        return _error("Task not found.", 404, "not_found")

    try:
        payload = _json_payload()
        status = _str_field(payload, "status", required=True)
        if status not in {"pending", "in_progress", "done"}:
            return _error("Invalid task status.", 400, "validation_error")

        task.status = status
        db.session.commit()
        return jsonify({"task_id": task.id, "status": task.status})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.get("/staff/notifications")
@require_role("zoo_staff")
def staff_notifications_list():
    user = _current_user()
    if not user or not user.zoo_id:
        return _error("Your account is not linked to an establishment.", 400, "validation_error")

    since = datetime.utcnow() - timedelta(days=7)
    notifications = (
        StaffTask.query
        .filter_by(zoo_id=user.zoo_id, assigned_to_user_id=user.id)
        .filter(StaffTask.created_at >= since)
        .order_by(StaffTask.created_at.desc())
        .limit(100)
        .all()
    )
    return jsonify(
        {
            "notifications": [
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                }
                for task in notifications
            ]
        }
    )


@api_bp.get("/staff/bookings/assigned")
@require_role("zoo_staff")
def staff_assigned_bookings():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    status = (request.args.get("status") or "").strip().lower()

    query = Booking.query.filter_by(assigned_staff_user_id=user.id, zoo_id=user.zoo_id)
    if status:
        query = query.filter(db.func.lower(Booking.status) == status)

    bookings = query.order_by(Booking.created_at.desc()).limit(300).all()
    return jsonify({"bookings": [_serialize_booking(item) for item in bookings]})


@api_bp.patch("/staff/bookings/assigned/<booking_id>/status")
@require_role("zoo_staff")
def staff_assigned_booking_status_patch(booking_id: str):
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    booking = Booking.query.filter_by(
        id=booking_id,
        zoo_id=user.zoo_id,
        assigned_staff_user_id=user.id,
    ).first()
    if not booking:
        return _error("Assigned booking not found.", 404, "not_found")

    try:
        payload = _json_payload()
        status = _str_field(payload, "status", required=True)
        if status not in {"Pending", "Confirmed", "Cancelled"}:
            return _error("Invalid booking status.", 400, "validation_error")

        booking.status = status
        db.session.commit()
        return jsonify({"booking": _serialize_booking(booking)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.get("/staff/events")
@require_role("zoo_staff")
def staff_events_list():
    user = _current_user()
    if not user or not user.zoo_id:
        return _error("Your account is not linked to an establishment.", 400, "validation_error")

    events = Event.query.filter_by(zoo_id=user.zoo_id).order_by(Event.id.desc()).all()
    return jsonify(
        {
            "events": [
                {
                    "id": event.id,
                    "zoo_id": event.zoo_id,
                    "name": event.name,
                    "type": event.type,
                    "time": event.time,
                    "location": event.location,
                }
                for event in events
            ]
        }
    )


@api_bp.post("/staff/events")
@require_role("zoo_staff")
def staff_events_create():
    user = _current_user()
    if not user or not user.zoo_id:
        return _error("Your account is not linked to an establishment.", 400, "validation_error")

    try:
        payload = _json_payload()
        name = _str_field(payload, "name", required=True)
        event = Event(
            zoo_id=user.zoo_id,
            name=name,
            type=_str_field(payload, "type"),
            time=_str_field(payload, "time"),
            location=_str_field(payload, "location"),
        )
        db.session.add(event)
        db.session.commit()
        return jsonify({"event": {"id": event.id, "name": event.name, "type": event.type, "time": event.time, "location": event.location}}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.patch("/staff/events/<int:event_id>")
@require_role("zoo_staff")
def staff_events_patch(event_id: int):
    user = _current_user()
    if not user or not user.zoo_id:
        return _error("Your account is not linked to an establishment.", 400, "validation_error")

    event = Event.query.filter_by(id=event_id, zoo_id=user.zoo_id).first()
    if not event:
        return _error("Event not found.", 404, "not_found")

    try:
        payload = _json_payload()
        if "name" in payload:
            name = _str_field(payload, "name", required=True)
            event.name = name
        if "type" in payload:
            event.type = _str_field(payload, "type")
        if "time" in payload:
            event.time = _str_field(payload, "time")
        if "location" in payload:
            event.location = _str_field(payload, "location")

        db.session.commit()
        return jsonify({"event": {"id": event.id, "name": event.name, "type": event.type, "time": event.time, "location": event.location}})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.delete("/staff/events/<int:event_id>")
@require_role("zoo_staff")
def staff_events_delete(event_id: int):
    user = _current_user()
    if not user or not user.zoo_id:
        return _error("Your account is not linked to an establishment.", 400, "validation_error")

    event = Event.query.filter_by(id=event_id, zoo_id=user.zoo_id).first()
    if not event:
        return _error("Event not found.", 404, "not_found")

    db.session.delete(event)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/staff/feedback")
@require_role("zoo_staff")
def staff_feedback_list():
    user = _current_user()
    if not user or not user.zoo_id:
        return _error("Your account is not linked to an establishment.", 400, "validation_error")

    rating = request.args.get("rating", type=int)
    query = Feedback.query.filter_by(zoo_id=user.zoo_id)
    if rating:
        query = query.filter_by(rating=rating)

    feedbacks = query.order_by(Feedback.id.desc()).limit(300).all()
    return jsonify({"feedbacks": [_serialize_feedback(item) for item in feedbacks]})


@api_bp.get("/admin/profile")
@require_role("zoo_admin")
def admin_profile_get():
    user = _current_user()
    return jsonify({"profile": _serialize_user(user)})


@api_bp.patch("/admin/profile")
@require_role("zoo_admin")
def admin_profile_patch():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    try:
        payload = _json_payload()
        full_name = _str_field(payload, "full_name")
        username = _str_field(payload, "username")
        email = _str_field(payload, "email", lower=True)

        if email and email != user.email:
            if User.query.filter(User.email == email, User.id != user.id).first():
                return _error("Email is already in use.", 409, "conflict")
            user.email = email

        if "username" in payload:
            if username and username != user.username:
                if User.query.filter(User.username == username, User.id != user.id).first():
                    return _error("Username is already in use.", 409, "conflict")
            user.username = username

        if full_name is not None:
            if not full_name:
                return _error("full_name cannot be empty.", 400, "validation_error")
            user.full_name = full_name

        db.session.commit()
        session["full_name"] = user.full_name
        return jsonify({"profile": _serialize_user(user)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


def _admin_zoo_or_error(user: User):
    zoo_id = _current_zoo_id_for_user(user)
    if not zoo_id:
        return None, _error("Your account is not linked to an establishment.", 400, "validation_error")
    return zoo_id, None


@api_bp.get("/admin/bookings")
@require_role("zoo_admin")
def admin_bookings_list():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    status = (request.args.get("status") or "").strip()
    assigned_to = request.args.get("assigned_to_user_id", type=int)

    query = Booking.query.filter_by(zoo_id=zoo_id)
    if status:
        query = query.filter_by(status=status)
    if assigned_to:
        query = query.filter_by(assigned_staff_user_id=assigned_to)

    bookings = query.order_by(Booking.created_at.desc()).limit(500).all()
    return jsonify({"bookings": [_serialize_booking(item) for item in bookings]})


@api_bp.patch("/admin/bookings/<booking_id>/status")
@require_role("zoo_admin")
def admin_booking_status_patch(booking_id: str):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    booking = Booking.query.filter_by(id=booking_id, zoo_id=zoo_id).first()
    if not booking:
        return _error("Booking not found.", 404, "not_found")

    try:
        payload = _json_payload()
        new_status = _str_field(payload, "status", required=True)
        if new_status not in {"Pending", "Confirmed", "Cancelled"}:
            return _error("Invalid booking status.", 400, "validation_error")
        booking.status = new_status
        db.session.commit()
        return jsonify({"booking": _serialize_booking(booking)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.post("/admin/bookings/<booking_id>/assign")
@require_role("zoo_admin")
def admin_assign_booking(booking_id: str):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    booking = Booking.query.filter_by(id=booking_id, zoo_id=zoo_id).first()
    if not booking:
        return _error("Booking not found.", 404, "not_found")

    payload = request.get_json(silent=True) or {}
    staff_user_id = payload.get("staff_user_id")

    if staff_user_id in (None, ""):
        booking.assigned_staff_user_id = None
        db.session.commit()
        return jsonify({"booking": _serialize_booking(booking)})

    try:
        staff_user_id = int(staff_user_id)
    except Exception:
        return _error("staff_user_id must be numeric.", 400, "validation_error")

    staff_user = User.query.filter_by(id=staff_user_id, role="zoo_staff", zoo_id=zoo_id).first()
    if not staff_user:
        return _error("Staff user not found in this establishment.", 404, "not_found")

    try:
        assign_booking_to_staff(booking=booking, staff_user=staff_user, zoo_id=zoo_id)
    except BookingValidationError as exc:
        return _error(str(exc), 400, "validation_error")

    return jsonify({"booking": _serialize_booking(booking)})


@api_bp.get("/admin/animals")
@require_role("zoo_admin")
def admin_animals_list():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    animals = Animal.query.filter_by(zoo_id=zoo_id).order_by(Animal.id.desc()).all()
    return jsonify(
        {
            "animals": [
                {
                    "id": animal.id,
                    "zoo_id": animal.zoo_id,
                    "name": animal.name,
                    "species": animal.species,
                    "habitat": animal.habitat,
                    "status": animal.status,
                    "description": animal.description,
                    "image_url": animal.image_url,
                }
                for animal in animals
            ]
        }
    )


@api_bp.post("/admin/animals")
@require_role("zoo_admin")
def admin_animals_create():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    try:
        payload = _json_payload()
        name = _str_field(payload, "name", required=True)
        animal = Animal(
            zoo_id=zoo_id,
            name=name,
            species=_str_field(payload, "species"),
            habitat=_str_field(payload, "habitat"),
            status=_str_field(payload, "status"),
            description=_str_field(payload, "description"),
            image_url=_str_field(payload, "image_url"),
        )
        db.session.add(animal)
        db.session.commit()
        return jsonify({"animal_id": animal.id}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.patch("/admin/animals/<int:animal_id>")
@require_role("zoo_admin")
def admin_animals_patch(animal_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    animal = Animal.query.filter_by(id=animal_id, zoo_id=zoo_id).first()
    if not animal:
        return _error("Animal not found.", 404, "not_found")

    try:
        payload = _json_payload()
        if "name" in payload:
            name = _str_field(payload, "name", required=True)
            animal.name = name
        if "species" in payload:
            animal.species = _str_field(payload, "species")
        if "habitat" in payload:
            animal.habitat = _str_field(payload, "habitat")
        if "status" in payload:
            animal.status = _str_field(payload, "status")
        if "description" in payload:
            animal.description = _str_field(payload, "description")
        if "image_url" in payload:
            animal.image_url = _str_field(payload, "image_url")

        db.session.commit()
        return jsonify({"animal_id": animal.id})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.delete("/admin/animals/<int:animal_id>")
@require_role("zoo_admin")
def admin_animals_delete(animal_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    animal = Animal.query.filter_by(id=animal_id, zoo_id=zoo_id).first()
    if not animal:
        return _error("Animal not found.", 404, "not_found")

    db.session.delete(animal)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/admin/services")
@require_role("zoo_admin")
def admin_services_list():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    services = Service.query.filter_by(zoo_id=zoo_id).order_by(Service.id.desc()).all()
    return jsonify(
        {
            "services": [
                {
                    "id": service.id,
                    "zoo_id": service.zoo_id,
                    "name": service.name,
                    "price": float(service.price or 0),
                    "description": service.description,
                    "image_url": service.image_url,
                }
                for service in services
            ]
        }
    )


@api_bp.post("/admin/services")
@require_role("zoo_admin")
def admin_services_create():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    try:
        payload = _json_payload()
        service = Service(
            zoo_id=zoo_id,
            name=_str_field(payload, "name", required=True),
            price=_float_field(payload, "price", required=True, minimum=0),
            description=_str_field(payload, "description"),
            image_url=_str_field(payload, "image_url"),
        )
        db.session.add(service)
        db.session.commit()
        return jsonify({"service_id": service.id}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.patch("/admin/services/<int:service_id>")
@require_role("zoo_admin")
def admin_services_patch(service_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    service = Service.query.filter_by(id=service_id, zoo_id=zoo_id).first()
    if not service:
        return _error("Service not found.", 404, "not_found")

    try:
        payload = _json_payload()
        if "name" in payload:
            service.name = _str_field(payload, "name", required=True)
        if "price" in payload:
            service.price = _float_field(payload, "price", required=True, minimum=0)
        if "description" in payload:
            service.description = _str_field(payload, "description")
        if "image_url" in payload:
            service.image_url = _str_field(payload, "image_url")

        db.session.commit()
        return jsonify({"service_id": service.id})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.delete("/admin/services/<int:service_id>")
@require_role("zoo_admin")
def admin_services_delete(service_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    service = Service.query.filter_by(id=service_id, zoo_id=zoo_id).first()
    if not service:
        return _error("Service not found.", 404, "not_found")

    db.session.delete(service)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/admin/events")
@require_role("zoo_admin")
def admin_events_list():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    events = Event.query.filter_by(zoo_id=zoo_id).order_by(Event.id.desc()).all()
    return jsonify(
        {
            "events": [
                {
                    "id": event.id,
                    "zoo_id": event.zoo_id,
                    "name": event.name,
                    "type": event.type,
                    "time": event.time,
                    "location": event.location,
                }
                for event in events
            ]
        }
    )


@api_bp.post("/admin/events")
@require_role("zoo_admin")
def admin_events_create():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    try:
        payload = _json_payload()
        event = Event(
            zoo_id=zoo_id,
            name=_str_field(payload, "name", required=True),
            type=_str_field(payload, "type"),
            time=_str_field(payload, "time"),
            location=_str_field(payload, "location"),
        )
        db.session.add(event)
        db.session.commit()
        return jsonify({"event_id": event.id}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.patch("/admin/events/<int:event_id>")
@require_role("zoo_admin")
def admin_events_patch(event_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    event = Event.query.filter_by(id=event_id, zoo_id=zoo_id).first()
    if not event:
        return _error("Event not found.", 404, "not_found")

    try:
        payload = _json_payload()
        if "name" in payload:
            event.name = _str_field(payload, "name", required=True)
        if "type" in payload:
            event.type = _str_field(payload, "type")
        if "time" in payload:
            event.time = _str_field(payload, "time")
        if "location" in payload:
            event.location = _str_field(payload, "location")

        db.session.commit()
        return jsonify({"event_id": event.id})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.delete("/admin/events/<int:event_id>")
@require_role("zoo_admin")
def admin_events_delete(event_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    event = Event.query.filter_by(id=event_id, zoo_id=zoo_id).first()
    if not event:
        return _error("Event not found.", 404, "not_found")

    db.session.delete(event)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/admin/promotions")
@require_role("zoo_admin")
def admin_promotions_list():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    promo_type = (request.args.get("promo_type") or "").strip()
    query = Promotion.query.filter_by(zoo_id=zoo_id)
    if promo_type:
        query = query.filter_by(promo_type=promo_type)

    promotions = query.order_by(Promotion.id.desc()).all()
    return jsonify(
        {
            "promotions": [
                {
                    "id": promo.id,
                    "zoo_id": promo.zoo_id,
                    "name": promo.name,
                    "code": promo.code,
                    "promo_type": promo.promo_type,
                    "country": promo.country,
                    "discount": promo.discount,
                    "valid_until": promo.valid_until,
                }
                for promo in promotions
            ]
        }
    )


@api_bp.post("/admin/promotions")
@require_role("zoo_admin")
def admin_promotions_create():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    try:
        payload = _json_payload()
        promotion = Promotion(
            zoo_id=zoo_id,
            name=_str_field(payload, "name", required=True),
            code=(_str_field(payload, "code", required=True) or "").upper(),
            promo_type=_str_field(payload, "promo_type"),
            country=_str_field(payload, "country") or "Philippines",
            discount=_str_field(payload, "discount"),
            valid_until=_str_field(payload, "valid_until"),
        )
        db.session.add(promotion)
        db.session.commit()
        return jsonify({"promotion_id": promotion.id}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")
    except Exception:
        db.session.rollback()
        return _error("Promotion code must be unique.", 409, "conflict")


@api_bp.patch("/admin/promotions/<int:promo_id>")
@require_role("zoo_admin")
def admin_promotions_patch(promo_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    promo = Promotion.query.filter_by(id=promo_id, zoo_id=zoo_id).first()
    if not promo:
        return _error("Promotion not found.", 404, "not_found")

    try:
        payload = _json_payload()
        if "name" in payload:
            promo.name = _str_field(payload, "name", required=True)
        if "code" in payload:
            promo.code = (_str_field(payload, "code", required=True) or "").upper()
        if "promo_type" in payload:
            promo.promo_type = _str_field(payload, "promo_type")
        if "country" in payload:
            promo.country = _str_field(payload, "country")
        if "discount" in payload:
            promo.discount = _str_field(payload, "discount")
        if "valid_until" in payload:
            promo.valid_until = _str_field(payload, "valid_until")

        db.session.commit()
        return jsonify({"promotion_id": promo.id})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")
    except Exception:
        db.session.rollback()
        return _error("Promotion code must be unique.", 409, "conflict")


@api_bp.delete("/admin/promotions/<int:promo_id>")
@require_role("zoo_admin")
def admin_promotions_delete(promo_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    promo = Promotion.query.filter_by(id=promo_id, zoo_id=zoo_id).first()
    if not promo:
        return _error("Promotion not found.", 404, "not_found")

    db.session.delete(promo)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/admin/zones")
@require_role("zoo_admin")
def admin_zones_list():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    zones = ZooZone.query.filter_by(zoo_id=zoo_id).order_by(ZooZone.created_at.desc()).all()
    return jsonify(
        {
            "zones": [
                {
                    "id": zone.id,
                    "zoo_id": zone.zoo_id,
                    "name": zone.name,
                    "description": zone.description,
                    "map_image_url": zone.map_image_url,
                    "panorama_360_url": zone.panorama_360_url,
                    "created_at": zone.created_at.isoformat() if zone.created_at else None,
                }
                for zone in zones
            ]
        }
    )


@api_bp.post("/admin/zones")
@require_role("zoo_admin")
def admin_zones_create():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    try:
        payload = _json_payload()
        zone = ZooZone(
            zoo_id=zoo_id,
            name=_str_field(payload, "name", required=True),
            description=_str_field(payload, "description"),
            map_image_url=_str_field(payload, "map_image_url"),
            panorama_360_url=_str_field(payload, "panorama_360_url"),
        )
        db.session.add(zone)
        db.session.commit()
        return jsonify({"zone_id": zone.id}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.patch("/admin/zones/<int:zone_id>")
@require_role("zoo_admin")
def admin_zones_patch(zone_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    zone = ZooZone.query.filter_by(id=zone_id, zoo_id=zoo_id).first()
    if not zone:
        return _error("Zone not found.", 404, "not_found")

    try:
        payload = _json_payload()
        if "name" in payload:
            zone.name = _str_field(payload, "name", required=True)
        if "description" in payload:
            zone.description = _str_field(payload, "description")
        if "map_image_url" in payload:
            zone.map_image_url = _str_field(payload, "map_image_url")
        if "panorama_360_url" in payload:
            zone.panorama_360_url = _str_field(payload, "panorama_360_url")

        db.session.commit()
        return jsonify({"zone_id": zone.id})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.delete("/admin/zones/<int:zone_id>")
@require_role("zoo_admin")
def admin_zones_delete(zone_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    zone = ZooZone.query.filter_by(id=zone_id, zoo_id=zoo_id).first()
    if not zone:
        return _error("Zone not found.", 404, "not_found")

    db.session.delete(zone)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/admin/staff-tasks")
@require_role("zoo_admin")
def admin_staff_tasks_list():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    tasks = StaffTask.query.filter_by(zoo_id=zoo_id).order_by(StaffTask.created_at.desc()).limit(500).all()
    return jsonify(
        {
            "tasks": [
                {
                    "id": task.id,
                    "zoo_id": task.zoo_id,
                    "assigned_to_user_id": task.assigned_to_user_id,
                    "assigned_to_name": task.assigned_to_user.full_name if task.assigned_to_user else None,
                    "title": task.title,
                    "description": task.description,
                    "due_date": task.due_date.isoformat() if task.due_date else None,
                    "status": task.status,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                }
                for task in tasks
            ]
        }
    )


@api_bp.post("/admin/staff-tasks")
@require_role("zoo_admin")
def admin_staff_tasks_create():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    try:
        payload = _json_payload()
        assigned_to_user_id = _int_field(payload, "assigned_to_user_id", minimum=1)
        if assigned_to_user_id:
            assigned_user = User.query.filter_by(id=assigned_to_user_id, role="zoo_staff", zoo_id=zoo_id).first()
            if not assigned_user:
                return _error("Assigned staff user not found.", 404, "not_found")

        task = StaffTask(
            zoo_id=zoo_id,
            assigned_to_user_id=assigned_to_user_id,
            title=_str_field(payload, "title", required=True),
            description=_str_field(payload, "description"),
            due_date=_parse_date_yyyy_mm_dd(_str_field(payload, "due_date")),
            status=_str_field(payload, "status") or "pending",
        )
        if task.status not in {"pending", "in_progress", "done"}:
            return _error("Invalid task status.", 400, "validation_error")

        db.session.add(task)
        db.session.commit()
        return jsonify({"task_id": task.id}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.patch("/admin/staff-tasks/<int:task_id>")
@require_role("zoo_admin")
def admin_staff_tasks_patch(task_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    task = StaffTask.query.filter_by(id=task_id, zoo_id=zoo_id).first()
    if not task:
        return _error("Task not found.", 404, "not_found")

    try:
        payload = _json_payload()
        if "assigned_to_user_id" in payload:
            assigned_to_user_id = _int_field(payload, "assigned_to_user_id", minimum=1)
            if assigned_to_user_id:
                assigned_user = User.query.filter_by(id=assigned_to_user_id, role="zoo_staff", zoo_id=zoo_id).first()
                if not assigned_user:
                    return _error("Assigned staff user not found.", 404, "not_found")
            task.assigned_to_user_id = assigned_to_user_id

        if "title" in payload:
            task.title = _str_field(payload, "title", required=True)
        if "description" in payload:
            task.description = _str_field(payload, "description")
        if "due_date" in payload:
            task.due_date = _parse_date_yyyy_mm_dd(_str_field(payload, "due_date"))
        if "status" in payload:
            status = _str_field(payload, "status", required=True)
            if status not in {"pending", "in_progress", "done"}:
                return _error("Invalid task status.", 400, "validation_error")
            task.status = status

        db.session.commit()
        return jsonify({"task_id": task.id})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.delete("/admin/staff-tasks/<int:task_id>")
@require_role("zoo_admin")
def admin_staff_tasks_delete(task_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    task = StaffTask.query.filter_by(id=task_id, zoo_id=zoo_id).first()
    if not task:
        return _error("Task not found.", 404, "not_found")

    db.session.delete(task)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/admin/visitor-feedback")
@require_role("zoo_admin")
def admin_visitor_feedback_list():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    rating = request.args.get("rating", type=int)
    query = Feedback.query.filter_by(zoo_id=zoo_id)
    if rating:
        query = query.filter_by(rating=rating)

    feedbacks = query.order_by(Feedback.id.desc()).limit(500).all()
    return jsonify({"feedbacks": [_serialize_feedback(item) for item in feedbacks]})


@api_bp.delete("/admin/visitor-feedback/<int:feedback_id>")
@require_role("zoo_admin")
def admin_visitor_feedback_delete(feedback_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    feedback = Feedback.query.filter_by(id=feedback_id, zoo_id=zoo_id).first()
    if not feedback:
        return _error("Feedback not found.", 404, "not_found")

    db.session.delete(feedback)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/admin/system-feedback")
@require_role("zoo_admin")
def admin_system_feedback_list():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    feedbacks = (
        ZooAdminFeedback.query
        .filter_by(zoo_id=zoo_id)
        .order_by(ZooAdminFeedback.created_at.desc())
        .all()
    )
    return jsonify({"feedbacks": [_serialize_system_feedback(item) for item in feedbacks]})


@api_bp.post("/admin/system-feedback")
@require_role("zoo_admin")
def admin_system_feedback_create():
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    try:
        payload = _json_payload()
        category = _str_field(payload, "category", required=True)
        if category not in {"Features", "Support", "Billing", "Other"}:
            return _error("Invalid feedback category.", 400, "validation_error")

        feedback = ZooAdminFeedback(
            zoo_id=zoo_id,
            user_id=user.id,
            category=category,
            rating=_int_field(payload, "rating", required=True, minimum=1, maximum=5),
            comment=_str_field(payload, "comment", required=True),
        )
        db.session.add(feedback)
        db.session.commit()
        return jsonify({"feedback": _serialize_system_feedback(feedback)}), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.patch("/admin/system-feedback/<int:feedback_id>")
@require_role("zoo_admin")
def admin_system_feedback_patch(feedback_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    feedback = ZooAdminFeedback.query.filter_by(id=feedback_id, zoo_id=zoo_id).first()
    if not feedback:
        return _error("Feedback not found.", 404, "not_found")
    if feedback.replies:
        return _error("Feedback with an existing reply can no longer be edited.", 400, "validation_error")

    try:
        payload = _json_payload()
        if "category" in payload:
            category = _str_field(payload, "category", required=True)
            if category not in {"Features", "Support", "Billing", "Other"}:
                return _error("Invalid feedback category.", 400, "validation_error")
            feedback.category = category
        if "rating" in payload:
            feedback.rating = _int_field(payload, "rating", required=True, minimum=1, maximum=5)
        if "comment" in payload:
            feedback.comment = _str_field(payload, "comment", required=True)

        db.session.commit()
        return jsonify({"feedback": _serialize_system_feedback(feedback)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.delete("/admin/system-feedback/<int:feedback_id>")
@require_role("zoo_admin")
def admin_system_feedback_delete(feedback_id: int):
    user = _current_user()
    zoo_id, err = _admin_zoo_or_error(user)
    if err:
        return err

    feedback = ZooAdminFeedback.query.filter_by(id=feedback_id, zoo_id=zoo_id).first()
    if not feedback:
        return _error("Feedback not found.", 404, "not_found")

    ZooAdminFeedbackReply.query.filter_by(feedback_id=feedback.id).delete(synchronize_session=False)
    db.session.delete(feedback)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/super-admin/profile")
@require_role("zootique_admin")
def super_admin_profile_get():
    user = _current_user()
    return jsonify({"profile": _serialize_user(user)})


@api_bp.patch("/super-admin/profile")
@require_role("zootique_admin")
def super_admin_profile_patch():
    user = _current_user()
    if not user:
        return _error("Authentication required.", 401, "unauthorized")

    try:
        payload = _json_payload()
        full_name = _str_field(payload, "full_name")
        username = _str_field(payload, "username")
        email = _str_field(payload, "email", lower=True)

        if email and email != user.email:
            if User.query.filter(User.email == email, User.id != user.id).first():
                return _error("Email is already in use.", 409, "conflict")
            user.email = email

        if "username" in payload:
            if username and username != user.username:
                if User.query.filter(User.username == username, User.id != user.id).first():
                    return _error("Username is already in use.", 409, "conflict")
            user.username = username

        if full_name is not None:
            if not full_name:
                return _error("full_name cannot be empty.", 400, "validation_error")
            user.full_name = full_name

        db.session.commit()
        session["full_name"] = user.full_name
        return jsonify({"profile": _serialize_user(user)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.get("/super-admin/users")
@require_role("zootique_admin")
def super_admin_users_list():
    role = (request.args.get("role") or "").strip()
    query = User.query
    if role:
        query = query.filter_by(role=role)

    users = query.order_by(User.created_at.desc()).limit(500).all()
    return jsonify({"users": [_serialize_user(item) for item in users]})


@api_bp.post("/super-admin/users")
@require_role("zootique_admin")
def super_admin_users_create():
    try:
        payload = _json_payload()
        role = _str_field(payload, "role") or "zoo_admin"
        if role not in {"zootique_admin", "zoo_admin", "zoo_staff", "visitor"}:
            return _error("Invalid role.", 400, "validation_error")

        email = _str_field(payload, "email", required=True, lower=True)
        if User.query.filter_by(email=email).first():
            return _error("Email already exists.", 409, "conflict")

        username = _str_field(payload, "username")
        if username and User.query.filter_by(username=username).first():
            return _error("Username already exists.", 409, "conflict")

        zoo_id = _int_field(payload, "zoo_id", minimum=1)
        if zoo_id and not db.session.get(Zoo, zoo_id):
            return _error("zoo_id does not exist.", 404, "not_found")

        password = _str_field(payload, "password")
        generated_password = None
        if not password:
            generated_password = secrets.token_urlsafe(9)
            password = generated_password
        if len(password) < 8:
            return _error("Password must be at least 8 characters.", 400, "validation_error")

        user = User(
            email=email,
            username=username,
            role=role,
            full_name=_str_field(payload, "full_name"),
            zoo_id=zoo_id,
            status=_str_field(payload, "status") or "active",
        )
        if user.status not in {"active", "suspended"}:
            return _error("Invalid status.", 400, "validation_error")

        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        body = {"user": _serialize_user(user)}
        if generated_password:
            body["temporary_password"] = generated_password
        return jsonify(body), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.patch("/super-admin/users/<int:user_id>")
@require_role("zootique_admin")
def super_admin_users_patch(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        return _error("User not found.", 404, "not_found")

    try:
        payload = _json_payload()

        if "email" in payload:
            email = _str_field(payload, "email", required=True, lower=True)
            if User.query.filter(User.email == email, User.id != user.id).first():
                return _error("Email already exists.", 409, "conflict")
            user.email = email

        if "username" in payload:
            username = _str_field(payload, "username")
            if username and User.query.filter(User.username == username, User.id != user.id).first():
                return _error("Username already exists.", 409, "conflict")
            user.username = username

        if "full_name" in payload:
            user.full_name = _str_field(payload, "full_name")

        if "role" in payload:
            role = _str_field(payload, "role", required=True)
            if role not in {"zootique_admin", "zoo_admin", "zoo_staff", "visitor"}:
                return _error("Invalid role.", 400, "validation_error")
            user.role = role

        if "status" in payload:
            status = _str_field(payload, "status", required=True)
            if status not in {"active", "suspended"}:
                return _error("Invalid status.", 400, "validation_error")
            user.status = status

        if "zoo_id" in payload:
            zoo_id = _int_field(payload, "zoo_id", minimum=1)
            if zoo_id and not db.session.get(Zoo, zoo_id):
                return _error("zoo_id does not exist.", 404, "not_found")
            user.zoo_id = zoo_id

        if "password" in payload:
            password = _str_field(payload, "password", required=True)
            if len(password) < 8:
                return _error("Password must be at least 8 characters.", 400, "validation_error")
            user.set_password(password)

        db.session.commit()
        return jsonify({"user": _serialize_user(user)})
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.delete("/super-admin/users/<int:user_id>")
@require_role("zootique_admin")
def super_admin_users_delete(user_id: int):
    actor = _current_user()
    if actor and actor.id == user_id:
        return _error("You cannot delete your own account.", 400, "validation_error")

    user = db.session.get(User, user_id)
    if not user:
        return _error("User not found.", 404, "not_found")

    db.session.delete(user)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/super-admin/zoo-feedback")
@require_role("zootique_admin")
def super_admin_feedback_list():
    zoo_id = request.args.get("zoo_id", type=int)
    rating = request.args.get("rating", type=int)

    query = ZooAdminFeedback.query
    if zoo_id:
        query = query.filter_by(zoo_id=zoo_id)
    if rating:
        query = query.filter_by(rating=rating)

    start_date = _parse_date_yyyy_mm_dd(request.args.get("start_date"))
    end_date = _parse_date_yyyy_mm_dd(request.args.get("end_date"))
    if start_date:
        query = query.filter(ZooAdminFeedback.created_at >= start_date)
    if end_date:
        query = query.filter(ZooAdminFeedback.created_at < (end_date + timedelta(days=1)))

    feedbacks = query.order_by(ZooAdminFeedback.created_at.desc()).limit(500).all()
    return jsonify({"feedbacks": [_serialize_system_feedback(item) for item in feedbacks]})


@api_bp.post("/super-admin/zoo-feedback/<int:feedback_id>/reply")
@require_role("zootique_admin")
def super_admin_feedback_reply(feedback_id: int):
    feedback = db.session.get(ZooAdminFeedback, feedback_id)
    if not feedback:
        return _error("Feedback not found.", 404, "not_found")

    admin_user = _current_user()
    try:
        payload = _json_payload()
        reply_text = _str_field(payload, "reply_text", required=True)

        reply = ZooAdminFeedbackReply(
            feedback_id=feedback_id,
            admin_user_id=admin_user.id if admin_user else None,
            reply_text=reply_text,
        )
        db.session.add(reply)
        db.session.commit()
        return jsonify(
            {
                "reply": {
                    "id": reply.id,
                    "feedback_id": feedback_id,
                    "reply_text": reply.reply_text,
                    "created_at": reply.created_at.isoformat() if reply.created_at else None,
                }
            }
        ), 201
    except ValueError as exc:
        return _error(str(exc), 400, "validation_error")


@api_bp.delete("/super-admin/zoo-feedback/<int:feedback_id>")
@require_role("zootique_admin")
def super_admin_feedback_delete(feedback_id: int):
    feedback = db.session.get(ZooAdminFeedback, feedback_id)
    if not feedback:
        return _error("Feedback not found.", 404, "not_found")

    ZooAdminFeedbackReply.query.filter_by(feedback_id=feedback_id).delete(synchronize_session=False)
    db.session.delete(feedback)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/super-admin/subscriptions")
@require_role("zootique_admin")
def super_admin_subscriptions_list():
    now = datetime.utcnow()
    subscriptions = (
        db.session.query(ZooSubscription)
        .join(Zoo)
        .join(SubscriptionPlan)
        .order_by(Zoo.name.asc())
        .all()
    )

    rows = []
    for subscription in subscriptions:
        latest_payment = (
            SubscriptionPayment.query
            .filter_by(subscription_id=subscription.id)
            .order_by(SubscriptionPayment.paid_at.desc())
            .first()
        )
        rows.append(
            {
                "subscription_id": subscription.id,
                "zoo_id": subscription.zoo_id,
                "zoo_name": subscription.zoo.name if subscription.zoo else None,
                "plan_id": subscription.plan_id,
                "plan_name": subscription.plan.name if subscription.plan else None,
                "status": "Active" if subscription.end_date >= now else "Expired",
                "start_date": subscription.start_date.isoformat() if subscription.start_date else None,
                "end_date": subscription.end_date.isoformat() if subscription.end_date else None,
                "latest_payment": {
                    "amount": float(latest_payment.amount),
                    "paid_at": latest_payment.paid_at.isoformat() if latest_payment and latest_payment.paid_at else None,
                    "reference": latest_payment.reference,
                } if latest_payment else None,
            }
        )

    return jsonify({"subscriptions": rows})


@api_bp.post("/super-admin/subscriptions/<int:subscription_id>/renew")
@require_role("zootique_admin")
def super_admin_renew_subscription(subscription_id: int):
    subscription = db.session.get(ZooSubscription, subscription_id)
    if not subscription:
        return _error("Subscription not found.", 404, "not_found")

    payload = request.get_json(silent=True) or {}
    months = payload.get("months")
    amount = payload.get("amount")

    if months is not None:
        try:
            months = int(months)
        except Exception:
            return _error("months must be numeric.", 400, "validation_error")

    if amount is not None:
        try:
            amount = float(amount)
        except Exception:
            return _error("amount must be numeric.", 400, "validation_error")

    try:
        payment = renew_zoo_subscription(subscription=subscription, months=months, amount=amount)
    except SubscriptionValidationError as exc:
        return _error(str(exc), 400, "validation_error")

    return jsonify(
        {
            "subscription_id": subscription.id,
            "payment_reference": payment.reference,
            "new_end_date": subscription.end_date.isoformat(),
        }
    )


@api_bp.post("/super-admin/subscriptions/<int:subscription_id>/cancel")
@require_role("zootique_admin")
def super_admin_cancel_subscription(subscription_id: int):
    subscription = db.session.get(ZooSubscription, subscription_id)
    if not subscription:
        return _error("Subscription not found.", 404, "not_found")

    try:
        cancel_zoo_subscription(subscription=subscription)
    except SubscriptionValidationError as exc:
        return _error(str(exc), 400, "validation_error")

    return jsonify({"subscription_id": subscription.id, "status": subscription.status})


@api_bp.post("/super-admin/subscriptions/<int:subscription_id>/change-plan")
@require_role("zootique_admin")
def super_admin_change_plan(subscription_id: int):
    subscription = db.session.get(ZooSubscription, subscription_id)
    if not subscription:
        return _error("Subscription not found.", 404, "not_found")

    payload = request.get_json(silent=True) or {}
    plan_id = payload.get("plan_id")
    bill_now = bool(payload.get("bill_now", True))

    if plan_id is None:
        return _error("plan_id is required.", 400, "validation_error")

    try:
        plan_id = int(plan_id)
    except Exception:
        return _error("plan_id must be numeric.", 400, "validation_error")

    plan = db.session.get(SubscriptionPlan, plan_id)
    if not plan:
        return _error("Plan not found.", 404, "not_found")

    try:
        updated, payment = change_zoo_subscription_plan(
            subscription=subscription,
            new_plan=plan,
            bill_now=bill_now,
        )
    except SubscriptionValidationError as exc:
        return _error(str(exc), 400, "validation_error")

    return jsonify(
        {
            "subscription_id": updated.id,
            "plan_id": updated.plan_id,
            "status": updated.status,
            "payment_reference": payment.reference if payment else None,
        }
    )
