from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta, date

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_, func
from werkzeug.utils import secure_filename

from services.storage import save_uploaded_image as _save_uploaded_image

from models import (
    Animal,
    Booking,
    BookingPayment,
    BookingTicket,
    BookingTicketScan,
    Event,
    Feedback,
    LoyaltyAccount,
    LoyaltyTransaction,
    Notification,
    Promotion,
    StaffTask,
    User,
    Zoo,
    ZooZone,
    Service,
    db,
)
from services.auth_guard import require_role_guard
from services.tickets import verify_ticket
from services.loyalty import sync_booking_points_for_status, reverse_booking_points
from services import can_edit_feature, paywall_edit_error, get_zoo_subscription_tier
from services.subscription_guard import FEATURE_TIERS, feature_limit, limit_allows, feature_required_tier
from services.service_catalog import (
    SERVICE_CATEGORIES,
    SERVICE_CATEGORY_VALUES,
    SERVICE_STATUSES,
    PROMOTION_CATEGORIES,
    PROMOTION_CATEGORY_VALUES,
)

zoo_staff_bp = Blueprint('animal_farm_staff', __name__)


@zoo_staff_bp.before_request
def require_zoo_staff():
    result = require_role_guard(expected_role='zoo_staff', login_module='zoo_staff')
    if result is not None:
        return result


@zoo_staff_bp.context_processor
def inject_subscription_tier():
    zoo = _current_zoo()
    tier = get_zoo_subscription_tier(zoo)
    return {
        'g_sub_tier': tier,
        'can_edit_feature': lambda f: can_edit_feature(zoo, f),
        'feature_required_tier': feature_required_tier,
    }


def _uploaded_file_size(file_storage) -> int | None:
    """Read a seekable upload size without consuming the file."""
    if file_storage.content_length:
        return int(file_storage.content_length)
    stream = getattr(file_storage, 'stream', None)
    if not stream or not hasattr(stream, 'tell') or not hasattr(stream, 'seek'):
        return None
    try:
        current_position = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(current_position)
        return int(size)
    except (OSError, ValueError):
        return None


def _current_user() -> User | None:
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, int(user_id))


def _current_zoo() -> Zoo | None:
    user = _current_user()
    if not user or not user.zoo_id:
        return None
    return db.session.get(Zoo, int(user.zoo_id))

@zoo_staff_bp.route('/')
def dashboard():
    user = _current_user()
    zoo = _current_zoo()
    tasks_pending = 0
    tasks_done = 0
    recent_tasks = []
    animals_count = 0
    bookings_count = 0
    if user:
        tasks_pending = StaffTask.query.filter_by(
            zoo_id=user.zoo_id, assigned_to_user_id=user.id
        ).filter(StaffTask.status != 'done').count()
        tasks_done = StaffTask.query.filter_by(
            zoo_id=user.zoo_id, assigned_to_user_id=user.id, status='done'
        ).count()
        recent_tasks = (
            StaffTask.query
            .filter_by(zoo_id=user.zoo_id, assigned_to_user_id=user.id)
            .filter(StaffTask.status != 'done')
            .order_by(StaffTask.due_date.asc().nullslast(), StaffTask.created_at.desc())
            .limit(5)
            .all()
        )
        if zoo:
            animals_count = Animal.query.filter_by(zoo_id=zoo.id).count()
            bookings_count = Booking.query.filter_by(zoo_id=zoo.id).count()

    popular_services = []
    if zoo:
        all_bookings = Booking.query.filter_by(zoo_id=zoo.id).all()
        service_stats = {}
        for b in all_bookings:
            service_name = b.service_name or (b.service.name if b.service else None) or ("Bundle Package" if getattr(b, "bundle_id", None) else "General Admission")
            stats = service_stats.setdefault(service_name, {
                "name": service_name,
                "bookings": 0,
                "guests": 0,
                "revenue": 0.0
            })
            stats["bookings"] += 1
            stats["guests"] += int(b.guests or 0)
            stats["revenue"] += float(b.amount or 0.0)
        popular_services = sorted(service_stats.values(), key=lambda s: s["bookings"], reverse=True)[:5]

    return render_template(
        'animal_farm_staff/dashboard.html',
        user=user,
        zoo=zoo,
        tasks_pending=tasks_pending,
        tasks_done=tasks_done,
        recent_tasks=recent_tasks,
        animals_count=animals_count,
        bookings_count=bookings_count,
        popular_services=popular_services,
        today=datetime.utcnow().date(),
    )


@zoo_staff_bp.route('/dashboard')
def dashboard_alias():
    return redirect(url_for('animal_farm_staff.dashboard'), code=301)

@zoo_staff_bp.route('/feeding')
def feeding_schedule():
    zoo = _current_zoo()
    animals = Animal.query.filter_by(zoo_id=zoo.id).order_by(Animal.name.asc()).all() if zoo else []
    return render_template('animal_farm_staff/feeding.html', zoo=zoo, animals=animals)

@zoo_staff_bp.route('/tasks')
def daily_tasks():
    user = _current_user()
    if not user:
        flash('Not logged in.', 'error')
        return redirect(url_for('auth.login', module_name='zoo_staff'))
    tasks = (
        StaffTask.query.filter_by(zoo_id=user.zoo_id, assigned_to_user_id=user.id)
        .order_by(StaffTask.due_date.asc().nullslast(), StaffTask.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template('animal_farm_staff/tasks.html', user=user, tasks=tasks)


@zoo_staff_bp.route('/bookings', methods=['GET', 'POST'])
def my_bookings():
    if request.method == 'POST':
        return create_booking()

    user = _current_user()
    zoo = _current_zoo()
    if not zoo or not user:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    selected_status = (request.args.get('status') or '').strip()
    query = Booking.query.filter_by(zoo_id=zoo.id)
    if selected_status in {'Confirmed', 'Pending', 'Cancelled', 'Finished'}:
        query = query.filter_by(status=selected_status)
    else:
        selected_status = ''

    bookings = query.order_by(Booking.created_at.desc()).limit(300).all()
    all_bookings = Booking.query.filter_by(zoo_id=zoo.id).all()
    today_value = datetime.utcnow().date().isoformat()
    today_bookings = [b for b in all_bookings if (b.date or '') == today_value]
    today_guests = sum(int(b.guests or 0) for b in today_bookings if (b.status or '').lower() not in {'cancelled', 'refunded'})
    daily_capacity = sum(int(s.daily_capacity or 0) for s in Service.query.filter_by(zoo_id=zoo.id).all())
    today_remaining = max(0, daily_capacity - today_guests) if daily_capacity else None

    total = len(all_bookings)
    confirmed = sum(1 for b in all_bookings if (b.status or '').lower() == 'confirmed')
    pending = sum(1 for b in all_bookings if (b.status or '').lower() == 'pending')
    cancelled = sum(1 for b in all_bookings if (b.status or '').lower() == 'cancelled')

    services = (
        Service.query
        .filter_by(zoo_id=zoo.id)
        .order_by(Service.name.asc())
        .all()
    )

    return render_template(
        'animal_farm_staff/bookings.html',
        zoo=zoo,
        bookings=bookings,
        selected_status=selected_status,
        services=services,
        total=total,
        confirmed=confirmed,
        pending=pending,
        cancelled=cancelled,
        today_bookings=today_bookings,
        today_guests=today_guests,
        today_remaining=today_remaining,
    )


@zoo_staff_bp.post('/bookings/create')
def create_booking():
    user = _current_user()
    zoo = _current_zoo()
    if not zoo or not user:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    service_id_raw = (request.form.get('service_id') or '').strip()
    date = (request.form.get('date') or '').strip()
    time = (request.form.get('time') or '').strip()
    guests = request.form.get('guests', type=int) or 1
    amount_raw = (request.form.get('amount') or '').strip()
    status = (request.form.get('status') or 'Pending').strip()
    visitor_name = (request.form.get('visitor_name') or '').strip() or 'Walk-in Visitor'
    image_file = request.files.get('image_file')

    if not date or not time:
        flash('Date and time are required.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))

    service = None
    if service_id_raw and service_id_raw.isdigit():
        service = Service.query.filter_by(id=int(service_id_raw), zoo_id=zoo.id).first()

    amount = None
    if amount_raw:
        try:
            amount = float(amount_raw)
        except Exception:
            pass
    if amount is None and service:
        amount = float(service.price or 0)

    booking = Booking(
        id=secrets.token_hex(8),
        zoo_id=zoo.id,
        visitor_name=visitor_name,
        service_id=service.id if service else None,
        service_name=service.name if service else None,
        date=date,
        time=time,
        guests=guests,
        amount=amount or 0,
        status=status if status in {'Pending', 'Confirmed', 'Cancelled', 'Finished'} else 'Pending',
        assigned_staff_user_id=user.id,
    )
    db.session.add(booking)

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'booking_images')
        if uploaded_url:
            booking.image_url = uploaded_url

    db.session.commit()
    flash('Booking created.', 'success')
    return redirect(url_for('animal_farm_staff.my_bookings'))


@zoo_staff_bp.post('/bookings/<booking_id>/update')
def update_booking(booking_id: str):
    user = _current_user()
    zoo = _current_zoo()
    if not zoo or not user:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    booking = Booking.query.filter_by(id=booking_id, zoo_id=zoo.id).first()
    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))

    service_id_raw = (request.form.get('service_id') or '').strip()
    date = (request.form.get('date') or '').strip()
    time = (request.form.get('time') or '').strip()
    guests = request.form.get('guests', type=int) or 1
    amount_raw = (request.form.get('amount') or '').strip()
    status = (request.form.get('status') or '').strip()
    visitor_name = (request.form.get('visitor_name') or '').strip()
    image_file = request.files.get('image_file')

    if not date:
        flash('Booking date is required.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))
    if not time:
        flash('Booking time is required.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))
    if guests < 1:
        guests = 1
    if status and status not in {'Pending', 'Confirmed', 'Cancelled', 'Finished'}:
        flash('Invalid status.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))

    service = None
    if service_id_raw:
        if not service_id_raw.isdigit():
            flash('Invalid service selection.', 'error')
            return redirect(url_for('animal_farm_staff.my_bookings'))
        service = Service.query.filter_by(id=int(service_id_raw), zoo_id=zoo.id).first()
        if not service:
            flash('Selected service was not found.', 'error')
            return redirect(url_for('animal_farm_staff.my_bookings'))

    amount = None
    if amount_raw:
        try:
            amount = float(amount_raw)
        except Exception:
            flash('Amount must be a number.', 'error')
            return redirect(url_for('animal_farm_staff.my_bookings'))

    if visitor_name:
        booking.visitor_name = visitor_name
    booking.date = date
    booking.time = time
    booking.guests = guests
    if status:
        booking.status = status
        sync_booking_points_for_status(booking=booking)

    if service:
        booking.service_id = service.id
        booking.service_name = service.name
        booking.zoo_id = service.zoo_id
        if amount is None:
            booking.amount = float(service.price or 0)
    if amount is not None:
        booking.amount = amount

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'booking_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_staff.my_bookings'))
        booking.image_url = uploaded_url

    db.session.commit()
    flash('Booking updated.', 'success')
    return redirect(url_for('animal_farm_staff.my_bookings'))


@zoo_staff_bp.post('/bookings/<booking_id>/status')
def update_assigned_booking_status(booking_id: str):
    user = _current_user()
    zoo = _current_zoo()
    if not zoo or not user:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    booking = Booking.query.filter_by(
        id=booking_id,
        zoo_id=zoo.id,
    ).first()
    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))

    new_status = (request.form.get('status') or '').strip()
    if new_status not in {'Pending', 'Confirmed', 'Cancelled', 'Finished'}:
        flash('Invalid booking status.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))

    booking.status = new_status
    sync_booking_points_for_status(booking=booking)
    db.session.commit()
    flash('Booking status updated.', 'success')
    return redirect(url_for('animal_farm_staff.my_bookings'))


@zoo_staff_bp.route('/bookings/<booking_id>/delete', methods=['GET', 'POST'])
def delete_booking(booking_id: str):
    user = _current_user()
    zoo = _current_zoo()
    if not zoo or not user:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    booking = Booking.query.filter_by(id=booking_id, zoo_id=zoo.id).first()
    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))

    if request.method == 'GET':
        return redirect(url_for('animal_farm_staff.my_bookings'))

    try:
        booking_user_id = booking.user_id

        # Delete ticket scans
        ticket_ids = [t.id for t in BookingTicket.query.filter_by(booking_id=booking.id).all()]
        if ticket_ids:
            BookingTicketScan.query.filter(BookingTicketScan.ticket_id.in_(ticket_ids)).delete(synchronize_session=False)
        BookingTicketScan.query.filter_by(booking_id=booking.id).delete(synchronize_session=False)

        # Delete tickets, payments, notifications
        BookingTicket.query.filter_by(booking_id=booking.id).delete(synchronize_session=False)
        BookingPayment.query.filter_by(booking_id=booking.id).delete(synchronize_session=False)
        Notification.query.filter_by(booking_id=booking.id).delete(synchronize_session=False)

        # Delete all loyalty transactions referencing this booking
        LoyaltyTransaction.query.filter(
            or_(
                LoyaltyTransaction.booking_id == booking.id,
                LoyaltyTransaction.description.ilike(f'%{booking.id}%')
            )
        ).delete(synchronize_session=False)

        db.session.delete(booking)
        db.session.commit()

        # Resync loyalty balance for the visitor if applicable
        if booking_user_id:
            account = LoyaltyAccount.query.filter_by(user_id=booking_user_id).first()
            if account:
                new_bal = db.session.query(func.coalesce(func.sum(LoyaltyTransaction.points), 0)).filter_by(account_id=account.id).scalar()
                account.balance = int(new_bal or 0)
                db.session.commit()

        flash('Booking removed.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Staff failed to delete booking %s: %s', booking_id, exc)
        flash('Unable to delete booking. Please try again.', 'error')

    return redirect(url_for('animal_farm_staff.my_bookings'))


@zoo_staff_bp.route('/ticket-scanner', methods=['GET', 'POST'])
def ticket_scanner():
        user = _current_user()
        zoo = _current_zoo()
        result = None
        payload = (request.form.get('payload') if request.method == 'POST' else request.args.get('payload') or '').strip()
        if request.method == 'POST':
            if not payload:
                flash('Scan or enter a ticket payload.', 'error')
            else:
                result = _validate_ticket_payload(payload, user, zoo)
        recent_scans = (
            BookingTicketScan.query.filter_by(zoo_id=zoo.id)
            .order_by(BookingTicketScan.scanned_at.desc())
            .limit(50)
            .all()
        ) if zoo else []
        return render_template(
            'animal_farm_staff/ticket_scanner.html',
            zoo=zoo,
            result=result,
            recent_scans=recent_scans,
            payload=payload,
        )


def _validate_ticket_payload(payload: str, user: User | None, zoo: Zoo | None):
        if not user or not zoo:
            return {'ok': False, 'reason': 'account_error', 'message': 'Your account is not linked to an establishment.'}
        try:
            ticket = verify_ticket(payload)
        except ValueError as exc:
            reason_str = str(exc)
            db.session.add(BookingTicketScan(
                zoo_id=zoo.id,
                staff_user_id=user.id,
                result='rejected',
                reason=reason_str,
            ))
            db.session.commit()
            return {'ok': False, 'reason': 'invalid_format', 'message': reason_str}

        booking = ticket.booking

        # Wrong zoo
        if not booking or booking.zoo_id != zoo.id:
            reason = 'Wrong zoo — this ticket belongs to a different establishment.'
            db.session.add(BookingTicketScan(
                ticket_id=ticket.id, booking_id=booking.id if booking else None,
                zoo_id=zoo.id, staff_user_id=user.id, result='rejected', reason=reason,
            ))
            db.session.commit()
            return {'ok': False, 'reason': 'wrong_zoo', 'message': reason}

        # Already used / cancelled ticket
        if ticket.status == 'checked_in':
            reason = f'Already used — this ticket was scanned in at {ticket.checked_in_at.strftime("%Y-%m-%d %H:%M") if ticket.checked_in_at else "an earlier time"}.'
            db.session.add(BookingTicketScan(
                ticket_id=ticket.id, booking_id=booking.id, zoo_id=zoo.id,
                staff_user_id=user.id, result='rejected', reason=reason,
            ))
            db.session.commit()
            return {'ok': False, 'reason': 'already_used', 'message': reason, 'booking': booking}
        if ticket.status not in ('issued',):
            reason = f'Ticket is {ticket.status.replace("_", " ")} — it cannot be used for entry.'
            db.session.add(BookingTicketScan(
                ticket_id=ticket.id, booking_id=booking.id, zoo_id=zoo.id,
                staff_user_id=user.id, result='rejected', reason=reason,
            ))
            db.session.commit()
            return {'ok': False, 'reason': 'ticket_invalid', 'message': reason, 'booking': booking}

        # Booking status checks
        booking_status = (booking.status or '').lower()
        payment_status = (booking.payment_status or '').lower()

        if booking_status in ('cancelled', 'refunded'):
            reason = f'Cancelled — this booking was {booking_status} and cannot be used for entry.'
            db.session.add(BookingTicketScan(
                ticket_id=ticket.id, booking_id=booking.id, zoo_id=zoo.id,
                staff_user_id=user.id, result='rejected', reason=reason,
            ))
            db.session.commit()
            return {'ok': False, 'reason': 'cancelled', 'message': reason, 'booking': booking}

        # Payment check — cash_on_arrival bookings that are Confirmed are accepted
        # (they pay at the door); all others must show payment_status=paid
        cash_on_arrival_confirmed = (
            payment_status == 'unpaid'
            and booking_status == 'confirmed'
            and (booking.payments and any(
                (p.method or '').lower() == 'cash_on_arrival' for p in booking.payments
            ) or True)  # if status=confirmed with cash method, let them through
        )
        is_paid = payment_status in ('paid', 'cash_paid')
        if not is_paid and not cash_on_arrival_confirmed:
            reason = 'Not paid — payment has not been confirmed for this booking.'
            db.session.add(BookingTicketScan(
                ticket_id=ticket.id, booking_id=booking.id, zoo_id=zoo.id,
                staff_user_id=user.id, result='rejected', reason=reason,
            ))
            db.session.commit()
            return {'ok': False, 'reason': 'not_paid', 'message': reason, 'booking': booking}

        # All clear — check in
        ticket.status = 'checked_in'
        ticket.checked_in_at = datetime.utcnow()
        ticket.checked_in_by = user.id
        db.session.add(BookingTicketScan(
            ticket_id=ticket.id, booking_id=booking.id, zoo_id=zoo.id,
            staff_user_id=user.id, result='checked_in', reason='Ticket accepted at entrance.',
        ))
        db.session.commit()
        return {
            'ok': True,
            'reason': 'checked_in',
            'message': 'Valid — visitor checked in.',
            'booking': booking,
        }



@zoo_staff_bp.post('/ticket-scanner/<int:ticket_id>/reverse')
def reverse_ticket_checkin(ticket_id: int):
        user = _current_user()
        zoo = _current_zoo()
        ticket = BookingTicket.query.filter_by(id=ticket_id).first()
        if not user or not zoo or not ticket or not ticket.booking or ticket.booking.zoo_id != zoo.id:
            flash('Ticket not found for this establishment.', 'error')
            return redirect(url_for('animal_farm_staff.ticket_scanner'))
        reason = (request.form.get('reason') or '').strip()
        if len(reason) < 5:
            flash('A reversal reason of at least five characters is required.', 'error')
            return redirect(url_for('animal_farm_staff.ticket_scanner'))
        if ticket.status != 'checked_in':
            flash('Only checked-in tickets can be reversed.', 'error')
            return redirect(url_for('animal_farm_staff.ticket_scanner'))
        ticket.status = 'issued'
        ticket.checked_in_at = None
        ticket.checked_in_by = None
        db.session.add(BookingTicketScan(
            ticket_id=ticket.id, booking_id=ticket.booking_id, zoo_id=zoo.id,
            staff_user_id=user.id, result='reversal', reason=reason,
        ))
        db.session.commit()
        flash('Ticket check-in reversed.', 'success')
        return redirect(url_for('animal_farm_staff.ticket_scanner'))

# ---------------------------------------------------------------------------
# Services Management
# ---------------------------------------------------------------------------

@zoo_staff_bp.route('/services')
def services_management():
    tab = request.args.get('tab') or 'list'
    if tab not in {'add', 'list'}:
        tab = 'list'
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))
    services = Service.query.filter_by(zoo_id=zoo.id).order_by(Service.id.desc()).all()
    edit_id = request.args.get('edit_id', type=int)
    edit_service = None
    if edit_id:
        edit_service = Service.query.filter_by(id=edit_id, zoo_id=zoo.id).first()
    return render_template(
        'animal_farm_admin/services.html',
        zoo=zoo,
        services=services,
        edit_service=edit_service,
        service_categories=SERVICE_CATEGORIES,
        service_statuses=SERVICE_STATUSES,
    )


@zoo_staff_bp.post('/services/save')
def save_service():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.services_management', tab='list'))
    if not can_edit_feature(zoo, 'services'):
        return paywall_edit_error('Services', required_tier=1)

    service_id = request.form.get('service_id')
    name = (request.form.get('name') or '').strip()
    price_raw = (request.form.get('price') or '').strip()
    category = (request.form.get('category') or '').strip() or None
    service_status = (request.form.get('service_status') or '').strip()
    max_guest_capacity = request.form.get('max_guest_capacity', type=int)
    description = (request.form.get('description') or '').strip() or None
    image_file = request.files.get('image_file')

    if not name:
        flash('Service name is required.', 'error')
        return redirect(url_for('animal_farm_staff.services_management', tab='list'))
    try:
        price = float(price_raw)
    except Exception:
        flash('Price must be a number.', 'error')
        return redirect(url_for('animal_farm_staff.services_management', tab='list'))
    if not service_status or service_status not in SERVICE_STATUSES:
        flash('Please select a valid service status.', 'error')
        return redirect(url_for('animal_farm_staff.services_management', tab='list'))
    if max_guest_capacity is None or max_guest_capacity < 1:
        flash('Maximum guest capacity must be at least 1.', 'error')
        return redirect(url_for('animal_farm_staff.services_management', tab='list'))
    if category and category not in SERVICE_CATEGORY_VALUES:
        flash('Please select a valid service category.', 'error')
        return redirect(url_for('animal_farm_staff.services_management', tab='list'))

    service = None
    if service_id:
        service = Service.query.filter_by(id=int(service_id), zoo_id=zoo.id).first()
    if not service:
        service = Service(zoo_id=zoo.id)
        db.session.add(service)

    service.name = name
    service.price = price
    service.category = category
    service.service_status = service_status
    service.max_guest_capacity = max_guest_capacity
    service.description = description

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'service_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_staff.services_management', tab='list'))
        service.image_url = uploaded_url

    db.session.commit()
    flash('Service saved.', 'success')
    return redirect(url_for('animal_farm_staff.services_management', tab='list'))


@zoo_staff_bp.post('/services/<int:service_id>/delete')
def delete_service(service_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.services_management', tab='list'))
    if not can_edit_feature(zoo, 'services'):
        return paywall_edit_error('Services', required_tier=1)
    service = Service.query.filter_by(id=service_id, zoo_id=zoo.id).first()
    if not service:
        flash('Service not found.', 'error')
        return redirect(url_for('animal_farm_staff.services_management', tab='list'))
    db.session.delete(service)
    db.session.commit()
    flash('Service deleted.', 'success')
    return redirect(url_for('animal_farm_staff.services_management', tab='list'))


# ---------------------------------------------------------------------------
# Animals Management
# ---------------------------------------------------------------------------

@zoo_staff_bp.route('/animals')
def animals_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))
    animals = Animal.query.filter_by(zoo_id=zoo.id).order_by(Animal.id.desc()).all()
    zones = ZooZone.query.filter_by(zoo_id=zoo.id).order_by(ZooZone.name.asc()).all()
    fun_facts_animals = [a for a in animals if a.fun_facts and a.fun_facts.strip()]
    edit_id = request.args.get('edit_id', type=int)
    edit_animal = None
    if edit_id:
        edit_animal = Animal.query.filter_by(id=edit_id, zoo_id=zoo.id).first()
        if not edit_animal:
            abort(404)
    return render_template(
        'animal_farm_admin/animals.html',
        zoo=zoo,
        animals=animals,
        zones=zones,
        fun_facts_animals=fun_facts_animals,
        edit_animal=edit_animal,
    )


@zoo_staff_bp.post('/animals/save')
def save_animal():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.animals_management', tab='list'))

    animal_id = request.form.get('animal_id')
    if not animal_id and not limit_allows(
        zoo, 'animals', Animal.query.filter_by(zoo_id=zoo.id).count()
    ):
        return paywall_edit_error(
            f"Animals (limit {feature_limit(zoo, 'animals')})",
            required_tier=FEATURE_TIERS.get('animals', 1),
        )
    if not can_edit_feature(zoo, 'animals'):
        return paywall_edit_error('Animals', required_tier=1)

    name = (request.form.get('name') or '').strip() or None
    species = (request.form.get('species') or '').strip()
    habitat = (request.form.get('habitat') or '').strip() or None
    status = (request.form.get('status') or '').strip() or None
    description = (request.form.get('description') or '').strip() or None
    age = (request.form.get('age') or '').strip() or None
    fun_facts = (request.form.get('fun_facts') or '').strip() or None
    zone_id = request.form.get('zone_id', type=int) or None
    image_file = request.files.get('image_file')

    if not species:
        flash('Animal species is required.', 'error')
        return redirect(url_for('animal_farm_staff.animals_management', tab='add'))

    if not zone_id and habitat:
        matched_zone = ZooZone.query.filter_by(zoo_id=zoo.id, name=habitat).first()
        if matched_zone:
            zone_id = matched_zone.id
    elif zone_id and not habitat:
        matched_zone = db.session.get(ZooZone, zone_id)
        if matched_zone:
            habitat = matched_zone.name

    animal = None
    if animal_id:
        animal = Animal.query.filter_by(id=int(animal_id), zoo_id=zoo.id).first()
        if not animal:
            abort(404)
    if not animal:
        animal = Animal(
            zoo_id=zoo.id,
            species=species,
            name=name,
            habitat=habitat,
            status=status,
            description=description,
            age=age,
            zone_id=zone_id
        )
        if 'fun_facts' in request.form:
            animal.fun_facts = fun_facts
        db.session.add(animal)
    else:
        animal.name = name
        animal.species = species
        animal.habitat = habitat
        animal.status = status
        animal.description = description
        animal.age = age
        if 'fun_facts' in request.form:
            animal.fun_facts = fun_facts
        animal.zone_id = zone_id

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'animal_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_staff.animals_management', tab='add'))
        animal.image_url = uploaded_url

    db.session.commit()
    flash('Animal saved.', 'success')
    return redirect(url_for('animal_farm_staff.animals_management', tab='list'))


@zoo_staff_bp.post('/animals/fun-facts/save')
def save_fun_fact():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.animals_management', tab='funfacts'))
    if not can_edit_feature(zoo, 'animals'):
        return paywall_edit_error('Animals', required_tier=1)

    animal_id = request.form.get('animal_id', type=int)
    animal_name = (request.form.get('animal_name') or '').strip()
    fun_facts = (request.form.get('fun_facts') or '').strip()

    if not fun_facts:
        flash('Fun fact / Did You Know description is required.', 'error')
        return redirect(url_for('animal_farm_staff.animals_management', tab='funfacts'))

    animal = None
    if animal_id:
        animal = Animal.query.filter_by(id=animal_id, zoo_id=zoo.id).first()
    elif animal_name:
        animal = Animal.query.filter_by(name=animal_name, zoo_id=zoo.id).first()

    if not animal and animal_name:
        animal = Animal(zoo_id=zoo.id, name=animal_name, status='Healthy')
        db.session.add(animal)

    if not animal:
        flash('Please select or specify an animal for this fun fact.', 'error')
        return redirect(url_for('animal_farm_staff.animals_management', tab='funfacts'))

    animal.fun_facts = fun_facts
    image_file = request.files.get('image_file')
    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'animal_images')
        if uploaded_url:
            animal.image_url = uploaded_url

    db.session.commit()
    flash('Wildlife fun fact saved successfully.', 'success')
    return redirect(url_for('animal_farm_staff.animals_management', tab='funfacts'))


@zoo_staff_bp.post('/animals/fun-facts/<int:animal_id>/clear')
def clear_fun_fact(animal_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.animals_management', tab='funfacts'))
    if not can_edit_feature(zoo, 'animals'):
        return paywall_edit_error('Animals', required_tier=1)
    animal = Animal.query.filter_by(id=animal_id, zoo_id=zoo.id).first()
    if animal:
        animal.fun_facts = None
        db.session.commit()
        flash('Fun fact removed.', 'success')
    return redirect(url_for('animal_farm_staff.animals_management', tab='funfacts'))


@zoo_staff_bp.post('/animals/<int:animal_id>/delete')
def delete_animal(animal_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.animals_management'))
    if not can_edit_feature(zoo, 'animals'):
        return paywall_edit_error('Animals', required_tier=1)
    animal = Animal.query.filter_by(id=animal_id, zoo_id=zoo.id).first()
    if not animal:
        flash('Animal not found.', 'error')
        return redirect(url_for('animal_farm_staff.animals_management'))
    db.session.delete(animal)
    db.session.commit()
    flash('Animal deleted.', 'success')
    return redirect(url_for('animal_farm_staff.animals_management'))


# ---------------------------------------------------------------------------
# Events Management
# ---------------------------------------------------------------------------

@zoo_staff_bp.route('/events')
def events_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))
    events = Event.query.filter_by(zoo_id=zoo.id).order_by(Event.id.desc()).all()
    edit_event = None
    edit_event_id = request.args.get('edit', type=int)
    if edit_event_id is not None:
        edit_event = Event.query.filter_by(id=edit_event_id, zoo_id=zoo.id).first()
        if not edit_event:
            flash('Event not found.', 'error')
            return redirect(url_for('animal_farm_staff.events_management', tab='list'))
    return render_template(
        'animal_farm_admin/events.html',
        zoo=zoo,
        events=events,
        edit_event=edit_event,
        selected_tab='add' if edit_event else request.args.get('tab', 'all'),
    )


@zoo_staff_bp.post('/events/save')
def save_event():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.events_management'))
    if not can_edit_feature(zoo, 'events'):
        return paywall_edit_error('Events', required_tier=1)

    event_id = request.form.get('event_id')
    name = (request.form.get('name') or '').strip()
    event_type = (request.form.get('type') or '').strip() or None
    time = (request.form.get('time') or '').strip() or None
    location = (request.form.get('location') or '').strip() or None
    image_file = request.files.get('image_file')

    if not name:
        flash('Event name is required.', 'error')
        return redirect(url_for('animal_farm_staff.events_management'))

    event = None
    if event_id:
        event = Event.query.filter_by(id=int(event_id), zoo_id=zoo.id).first()
    if not event:
        event = Event(zoo_id=zoo.id)
        db.session.add(event)

    event.name = name
    event.type = event_type
    event.time = time
    event.location = location

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'event_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_staff.events_management'))
        event.image_url = uploaded_url

    db.session.commit()
    flash('Event saved.', 'success')
    return redirect(url_for('animal_farm_staff.events_management'))


@zoo_staff_bp.post('/events/<int:event_id>/delete')
def delete_event(event_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.events_management'))
    if not can_edit_feature(zoo, 'events'):
        return paywall_edit_error('Events', required_tier=1)
    event = Event.query.filter_by(id=event_id, zoo_id=zoo.id).first()
    if not event:
        flash('Event not found.', 'error')
        return redirect(url_for('animal_farm_staff.events_management'))
    db.session.delete(event)
    db.session.commit()
    flash('Event deleted.', 'success')
    return redirect(url_for('animal_farm_staff.events_management'))


# ---------------------------------------------------------------------------
# Promotions Management
# ---------------------------------------------------------------------------

@zoo_staff_bp.route('/promotions')
def promotions_management():
    tab = request.args.get('tab') or 'list'
    if tab not in {'add', 'list'}:
        tab = 'list'

    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    query = Promotion.query.filter_by(zoo_id=zoo.id, country='Philippines')
    promotions = query.order_by(Promotion.id.desc()).all()
    edit_id = request.args.get('edit_id', type=int)
    edit_promotion = None
    if edit_id:
        edit_promotion = Promotion.query.filter_by(
            id=edit_id,
            zoo_id=zoo.id,
            country='Philippines',
        ).first()
    return render_template(
        'animal_farm_admin/promotions.html',
        zoo=zoo,
        promotions=promotions,
        promo_categories=PROMOTION_CATEGORIES,
        edit_promotion=edit_promotion,
    )


@zoo_staff_bp.post('/promotions/save')
def save_promotion():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.promotions_management', tab='add'))
    if not can_edit_feature(zoo, 'promotions'):
        return paywall_edit_error('Promotions', required_tier=1)

    promo_id = request.form.get('promo_id')
    name = (request.form.get('name') or '').strip()
    code = (request.form.get('code') or '').strip().upper()
    discount = (request.form.get('discount') or '').strip() or None
    valid_until = (request.form.get('valid_until') or '').strip() or None
    promo_type = (request.form.get('promo_type') or '').strip() or None
    image_file = request.files.get('image_file')

    if not name or not code:
        flash('Promotion name and code are required.', 'error')
        return redirect(url_for('animal_farm_staff.promotions_management', tab='add'))
    if promo_type and promo_type not in PROMOTION_CATEGORY_VALUES:
        flash('Please select a valid promotion category.', 'error')
        return redirect(url_for('animal_farm_staff.promotions_management', tab='add'))

    promotion = None
    if promo_id:
        promotion = Promotion.query.filter_by(id=int(promo_id), zoo_id=zoo.id).first()
    if not promotion:
        promotion = Promotion(zoo_id=zoo.id, country='Philippines')
        db.session.add(promotion)

    promotion.name = name
    promotion.code = code
    promotion.discount = discount
    promotion.valid_until = valid_until
    promotion.promo_type = promo_type

    dtype = (request.form.get('discount_type') or 'percent').lower()
    dval = request.form.get('discount_value', type=float)
    if discount:
        if 'php' in discount.lower() or '₱' in discount:
            dtype = 'fixed'
        elif '%' in discount:
            dtype = 'percent'
        if dval is None or dval <= 0:
            m = re.search(r"(\d+(?:\.\d+)?)", discount)
            if m:
                dval = float(m.group(1))
    promotion.discount_type = dtype
    promotion.discount_value = dval or 0.0

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'promotion_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_staff.promotions_management', tab='add'))
        promotion.image_url = uploaded_url

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Promotion code must be unique.', 'error')
        return redirect(url_for('animal_farm_staff.promotions_management', tab='list'))

    flash('Promotion saved.', 'success')
    return redirect(url_for('animal_farm_staff.promotions_management', tab='list'))


@zoo_staff_bp.post('/promotions/<int:promo_id>/delete')
def delete_promotion(promo_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.promotions_management', tab='list'))
    if not can_edit_feature(zoo, 'promotions'):
        return paywall_edit_error('Promotions', required_tier=1)
    promo = Promotion.query.filter_by(id=promo_id, zoo_id=zoo.id).first()
    if not promo:
        flash('Promotion not found.', 'error')
        return redirect(url_for('animal_farm_staff.promotions_management', tab='list'))
    db.session.delete(promo)
    db.session.commit()
    flash('Promotion deleted.', 'success')
    return redirect(url_for('animal_farm_staff.promotions_management', tab='list'))


@zoo_staff_bp.route('/feedback')
def visitor_feedback():
    zoo = _current_zoo()
    if not zoo:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    selected_rating = (request.args.get('rating') or '').strip()
    query = Feedback.query.filter_by(zoo_id=zoo.id)
    if selected_rating.isdigit():
        query = query.filter_by(rating=int(selected_rating))

    feedbacks = query.order_by(Feedback.id.desc()).limit(200).all()
    total_count = Feedback.query.filter_by(zoo_id=zoo.id).count()
    avg_rating_raw = db.session.query(db.func.avg(Feedback.rating)).filter(Feedback.zoo_id == zoo.id).scalar() or 0
    avg_rating = f"{float(avg_rating_raw):.1f}"

    return render_template(
        'animal_farm_staff/feedback.html',
        zoo=zoo,
        feedbacks=feedbacks,
        selected_rating=selected_rating,
        total_count=total_count,
        avg_rating=avg_rating,
    )


# ---------------------------------------------------------------------------
# Map & Zones Management
# ---------------------------------------------------------------------------

@zoo_staff_bp.route('/map-zones')
def visitor_map_zone_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    zones = ZooZone.query.filter_by(zoo_id=zoo.id).order_by(ZooZone.created_at.desc()).all()
    landing_map = {
        'title': (zoo.landing_map_title or f'{zoo.name} Visitor Map').strip(),
        'description': (zoo.landing_map_description or '').strip(),
        'image_url': (zoo.landing_map_image_url or '').strip(),
        'updated_at': zoo.landing_map_updated_at,
    }
    return render_template('animal_farm_admin/map_zones.html', zoo=zoo, zones=zones, landing_map=landing_map)


# Alias for backward compatibility
map_zones = visitor_map_zone_management


@zoo_staff_bp.post('/map-zones/landing-map/save')
def save_landing_map():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))
    if not can_edit_feature(zoo, 'map_zones'):
        return paywall_edit_error('Landing Map', required_tier=2)

    title = (request.form.get('landing_map_title') or '').strip()
    description = (request.form.get('landing_map_description') or '').strip() or None
    image_file = request.files.get('landing_map_image_file')

    zoo.landing_map_title = title or None
    zoo.landing_map_description = description

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'map_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))
        zoo.landing_map_image_url = uploaded_url
    zoo.landing_map_updated_at = datetime.utcnow()

    db.session.commit()
    flash('Landing page map settings updated.', 'success')
    return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))


@zoo_staff_bp.post('/map-zones/pin-positions/save')
def save_zone_pin_positions():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))
    if not can_edit_feature(zoo, 'map_zones'):
        return paywall_edit_error('Map Pin Positions', required_tier=2)

    try:
        positions = json.loads(request.form.get('pin_positions') or '{}')
        if not isinstance(positions, dict):
            raise ValueError
        zones = {str(zone.id): zone for zone in ZooZone.query.filter_by(zoo_id=zoo.id).all()}
        unknown_zone_ids = set(positions) - set(zones)
        if unknown_zone_ids:
            raise ValueError
        for zone_id, zone in zones.items():
            raw_position = positions.get(zone_id)
            if raw_position is None:
                zone.position_x = None
                zone.position_y = None
                continue
            if not isinstance(raw_position, dict):
                raise ValueError
            x = float(raw_position.get('x'))
            y = float(raw_position.get('y'))
            if not (0 <= x <= 100 and 0 <= y <= 100):
                raise ValueError
            zone.position_x = x
            zone.position_y = y
    except (TypeError, ValueError, json.JSONDecodeError):
        flash('Pin positions must be percentages between 0 and 100.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management', tab='pin-editor'))

    db.session.commit()
    flash('Map pin positions saved.', 'success')
    return redirect(url_for('animal_farm_staff.visitor_map_zone_management', tab='pin-editor'))


@zoo_staff_bp.post('/map-zones/save')
def save_zone():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))
    if not can_edit_feature(zoo, 'map_zones'):
        return paywall_edit_error('Map Zones', required_tier=2)

    zone_id = request.form.get('zone_id')
    name = (request.form.get('name') or '').strip()
    description = (request.form.get('description') or '').strip() or None
    panorama_360_url = (request.form.get('panorama_360_url') or '').strip() or None
    map_image_file = request.files.get('map_image_file')
    gallery_files = [
        file for file in request.files.getlist('zone_images')
        if file and file.filename
    ]
    try:
        removed_images = json.loads(request.form.get('removed_zone_images') or '[]')
    except (TypeError, ValueError, json.JSONDecodeError):
        flash('The selected zone pictures could not be processed.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management', tab='add'))
    if not isinstance(removed_images, list) or not all(isinstance(url, str) for url in removed_images):
        flash('The selected zone pictures could not be processed.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management', tab='add'))

    if not name:
        flash('Zone name is required.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))

    zone = None
    if zone_id:
        try:
            zone = ZooZone.query.filter_by(id=int(zone_id), zoo_id=zoo.id).first()
        except (TypeError, ValueError):
            flash('The selected zone is invalid.', 'error')
            return redirect(url_for('animal_farm_staff.visitor_map_zone_management', tab='add'))
    if not zone:
        zone = ZooZone(zoo_id=zoo.id)
        db.session.add(zone)

    zone.name = name
    zone.description = description
    zone.panorama_360_url = panorama_360_url
    current_images = [
        image_url for image_url in zone.image_urls
        if image_url not in set(removed_images)
    ]
    if len(current_images) + len(gallery_files) > 12:
        flash('A zone can have up to 12 pictures.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management', tab='add'))

    for image_file in gallery_files:
        if (_uploaded_file_size(image_file) or 0) > 5 * 1024 * 1024:
            flash('Each zone picture must be no larger than 5 MB.', 'error')
            return redirect(url_for('animal_farm_staff.visitor_map_zone_management', tab='add'))
        uploaded_url = _save_uploaded_image(image_file, 'zone_images')
        if not uploaded_url:
            flash('Unable to upload one of the zone pictures.', 'error')
            return redirect(url_for('animal_farm_staff.visitor_map_zone_management', tab='add'))
        current_images.append(uploaded_url)
    zone.image_urls = current_images

    if map_image_file and map_image_file.filename:
        uploaded_url = _save_uploaded_image(map_image_file, 'zone_maps')
        if not uploaded_url:
            return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))
        zone.map_image_url = uploaded_url

    db.session.commit()
    flash('Zone saved.', 'success')
    return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))


@zoo_staff_bp.post('/map-zones/<int:zone_id>/delete')
def delete_zone(zone_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))
    if not can_edit_feature(zoo, 'map_zones'):
        return paywall_edit_error('Map Zones', required_tier=2)
    zone = ZooZone.query.filter_by(id=zone_id, zoo_id=zoo.id).first()
    if not zone:
        flash('Zone not found.', 'error')
        return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))
    db.session.delete(zone)
    db.session.commit()
    flash('Zone deleted.', 'success')
    return redirect(url_for('animal_farm_staff.visitor_map_zone_management'))


@zoo_staff_bp.route('/notifications')
def notifications():
    user = _current_user()
    if not user:
        return redirect(url_for('auth.login', module_name='zoo_staff'))
    items = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(100).all()
    unread = sum(1 for item in items if item.read_at is None)
    return render_template('animal_farm_staff/notifications.html', notifications=items, unread=unread)


@zoo_staff_bp.post('/notifications/<int:notification_id>/read')
def mark_notification_read(notification_id: int):
    user = _current_user()
    if not user:
        return jsonify({'success': False}), 401
    notif = Notification.query.filter_by(id=notification_id, user_id=user.id).first()
    if not notif:
        return jsonify({'success': False}), 404
    if notif.read_at is None:
        notif.read_at = datetime.utcnow()
        db.session.commit()
    unread_count = Notification.query.filter_by(user_id=user.id, read_at=None).count()
    return jsonify({'success': True, 'unread_count': unread_count})


@zoo_staff_bp.post('/notifications/read-all')
def mark_all_notifications_read():
    user = _current_user()
    if not user:
        return jsonify({'success': False}), 401
    Notification.query.filter_by(user_id=user.id, read_at=None).update({'read_at': datetime.utcnow()})
    db.session.commit()
    return jsonify({'success': True, 'unread_count': 0})


@zoo_staff_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    user = _current_user()
    zoo = _current_zoo()
    if not user:
        flash('Not logged in.', 'error')
        return redirect(url_for('auth.login', module_name='zoo_staff'))

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()

        if action == 'profile':
            full_name = (request.form.get('full_name') or '').strip()
            username = (request.form.get('username') or '').strip() or None
            email = (request.form.get('email') or '').strip().lower()

            if not full_name or not email:
                flash('Full name and email are required.', 'error')
                return redirect(url_for('animal_farm_staff.profile'))

            if email != user.email:
                existing_email = User.query.filter(User.email == email, User.id != user.id).first()
                if existing_email:
                    flash('Email already exists.', 'error')
                    return redirect(url_for('animal_farm_staff.profile'))

            if username and username != user.username:
                existing_username = User.query.filter(User.username == username, User.id != user.id).first()
                if existing_username:
                    flash('Username already exists.', 'error')
                    return redirect(url_for('animal_farm_staff.profile'))

            user.full_name = full_name
            user.username = username
            user.email = email

            file = request.files.get('profile_picture')
            if file and file.filename:
                uploaded_url = _save_uploaded_image(file, 'profile_pictures')
                if uploaded_url:
                    user.profile_image = uploaded_url

            db.session.commit()
            session['full_name'] = user.full_name
            if user.profile_image:
                session['profile_image'] = user.profile_image
            auth_by_role = session.get("auth_by_role")
            if isinstance(auth_by_role, dict) and "zoo_staff" in auth_by_role:
                auth_by_role["zoo_staff"]["full_name"] = user.full_name
                auth_by_role["zoo_staff"]["profile_image"] = user.profile_image
                session["auth_by_role"] = auth_by_role
            session.modified = True
            flash('Profile updated.', 'success')
            return redirect(url_for('animal_farm_staff.profile'))

        if action == 'password':
            current_password = request.form.get('current_password') or ''
            new_password = request.form.get('new_password') or ''
            confirm_password = request.form.get('confirm_password') or ''

            if not user.check_password(current_password):
                flash('Current password is incorrect.', 'error')
                return redirect(url_for('animal_farm_staff.profile'))
            if len(new_password) < 8:
                flash('New password must be at least 8 characters.', 'error')
                return redirect(url_for('animal_farm_staff.profile'))
            if new_password != confirm_password:
                flash('New password and confirmation do not match.', 'error')
                return redirect(url_for('animal_farm_staff.profile'))

            user.set_password(new_password)
            db.session.commit()
            flash('Password updated.', 'success')
            return redirect(url_for('animal_farm_staff.profile'))

        flash('Unknown profile action.', 'error')
        return redirect(url_for('animal_farm_staff.profile'))

    task_scope = StaffTask.query.filter_by(assigned_to_user_id=user.id)
    if zoo:
        task_scope = task_scope.filter_by(zoo_id=zoo.id)
    tasks_done = task_scope.filter_by(status='done').count()
    tasks_pending = task_scope.filter(StaffTask.status != 'done').count()

    return render_template(
        'animal_farm_staff/profile.html',
        user=user,
        zoo=zoo,
        tasks_done=tasks_done,
        tasks_pending=tasks_pending,
    )


@zoo_staff_bp.post('/tasks/<int:task_id>/status')
def update_task_status(task_id: int):
    user = _current_user()
    if not user:
        flash('Not logged in.', 'error')
        return redirect(url_for('auth.login', module_name='zoo_staff'))

    task = StaffTask.query.filter_by(id=task_id, zoo_id=user.zoo_id, assigned_to_user_id=user.id).first()
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('animal_farm_staff.daily_tasks'))

    status = (request.form.get('status') or '').strip()
    if status not in {'pending', 'in_progress', 'done'}:
        flash('Invalid status.', 'error')
        return redirect(url_for('animal_farm_staff.daily_tasks'))

    task.status = status
    db.session.commit()
    flash('Task updated.', 'success')
    return redirect(url_for('animal_farm_staff.daily_tasks'))

@zoo_staff_bp.route('/incidents', methods=['GET', 'POST'])
def report_incident():
    user = _current_user()
    zoo = _current_zoo()
    if not user or not zoo:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    if request.method == 'POST':
        severity = (request.form.get('severity') or 'General').strip().title()
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip() or None

        if severity not in {'General', 'Warning', 'Urgent', 'Emergency'}:
            severity = 'General'
        if not title:
            flash('Incident title is required.', 'error')
            return redirect(url_for('animal_farm_staff.report_incident'))

        incident = StaffTask(
            zoo_id=zoo.id,
            assigned_to_user_id=user.id,
            title=f'[{severity}] {title}',
            description=description,
            status='pending',
        )
        db.session.add(incident)
        db.session.commit()
        flash('Incident logged successfully.', 'success')
        return redirect(url_for('animal_farm_staff.report_incident'))

    incidents = (
        StaffTask.query
        .filter_by(zoo_id=zoo.id)
        .filter(StaffTask.title.like('[%'))
        .order_by(StaffTask.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template('animal_farm_staff/incident.html', incidents=incidents)


@zoo_staff_bp.route('/daily-operations-log', methods=['GET', 'POST'])
def daily_operations_log():
    return report_incident()


@zoo_staff_bp.route('/logout')
def logout_redirect():
    return redirect(url_for('animal_farm_staff.logout_confirm'))


@zoo_staff_bp.get('/logout-confirm')
def logout_confirm():
    return render_template('animal_farm_staff/logout_confirm.html', user=_current_user())


@zoo_staff_bp.post('/logout-confirm')
def logout_confirm_post():
    session.clear()
    return redirect(url_for('visitor.home'))

@zoo_staff_bp.route('/incident')
def report_incident_legacy_redirect():
    return redirect(url_for('animal_farm_staff.report_incident'), code=301)
