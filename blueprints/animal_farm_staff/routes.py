from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, date

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from services.storage import save_uploaded_image as _save_uploaded_image

from models import Animal, Booking, BookingTicket, BookingTicketScan, Event, Feedback, Notification, StaffTask, User, Zoo, ZooZone, Service, db
from services.auth_guard import require_role_guard
from services.tickets import verify_ticket

zoo_staff_bp = Blueprint('animal_farm_staff', __name__)


@zoo_staff_bp.before_request
def require_zoo_staff():
    result = require_role_guard(expected_role='zoo_staff', login_module='zoo_staff')
    if result is not None:
        return result


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
        from models import StaffTask, Animal
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
    return render_template(
        'animal_farm_staff/dashboard.html',
        user=user,
        zoo=zoo,
        tasks_pending=tasks_pending,
        tasks_done=tasks_done,
        recent_tasks=recent_tasks,
        animals_count=animals_count,
        bookings_count=bookings_count,
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


@zoo_staff_bp.route('/bookings')
def my_bookings():
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

    return render_template(
        'animal_farm_staff/bookings.html',
        zoo=zoo,
        bookings=bookings,
        selected_status=selected_status,
        total=total,
        confirmed=confirmed,
        pending=pending,
        cancelled=cancelled,
        today_bookings=today_bookings,
        today_guests=today_guests,
        today_remaining=today_remaining,
    )


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
    db.session.commit()
    flash('Booking status updated.', 'success')
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
            return {'ok': False, 'message': 'Your account is not linked to an establishment.'}
        try:
            ticket = verify_ticket(payload)
        except ValueError as exc:
            db.session.add(BookingTicketScan(
                zoo_id=zoo.id,
                staff_user_id=user.id,
                result='rejected',
                reason=str(exc),
            ))
            db.session.commit()
            return {'ok': False, 'message': str(exc)}

        booking = ticket.booking
        if not booking or booking.zoo_id != zoo.id:
            reason = 'This ticket does not belong to your establishment.'
            db.session.add(BookingTicketScan(
                ticket_id=ticket.id, booking_id=booking.id if booking else None,
                zoo_id=zoo.id, staff_user_id=user.id, result='rejected', reason=reason,
            ))
            db.session.commit()
            return {'ok': False, 'message': reason}
        if ticket.status != 'issued':
            reason = f'Ticket is already {ticket.status.replace("_", " ")}.'
            db.session.add(BookingTicketScan(
                ticket_id=ticket.id, booking_id=booking.id, zoo_id=zoo.id,
                staff_user_id=user.id, result='rejected', reason=reason,
            ))
            db.session.commit()
            return {'ok': False, 'message': reason, 'booking': booking}
        if (booking.status or '').lower() in {'cancelled', 'refunded'} or (booking.payment_status or '').lower() not in {'paid', 'cash_paid'}:
            reason = 'The booking is not eligible for entrance.'
            db.session.add(BookingTicketScan(
                ticket_id=ticket.id, booking_id=booking.id, zoo_id=zoo.id,
                staff_user_id=user.id, result='rejected', reason=reason,
            ))
            db.session.commit()
            return {'ok': False, 'message': reason, 'booking': booking}
        ticket.status = 'checked_in'
        ticket.checked_in_at = datetime.utcnow()
        ticket.checked_in_by = user.id
        db.session.add(BookingTicketScan(
            ticket_id=ticket.id, booking_id=booking.id, zoo_id=zoo.id,
            staff_user_id=user.id, result='checked_in', reason='Ticket accepted at entrance.',
        ))
        db.session.commit()
        return {'ok': True, 'message': 'Ticket accepted. Visitor checked in.', 'booking': booking}


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

@zoo_staff_bp.route('/events', methods=['GET', 'POST'])
def events_management():
    zoo = _current_zoo()
    if not zoo:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    if request.method == 'POST':
        event_id = (request.form.get('event_id') or '').strip()
        name = (request.form.get('name') or '').strip()
        event_type = (request.form.get('type') or '').strip() or None
        time_value = (request.form.get('time') or '').strip() or None
        location = (request.form.get('location') or '').strip() or None

        if not name:
            flash('Event name is required.', 'error')
            return redirect(url_for('animal_farm_staff.events_management'))

        event = None
        if event_id.isdigit():
            event = Event.query.filter_by(id=int(event_id), zoo_id=zoo.id).first()
            if not event:
                flash('Event not found.', 'error')
                return redirect(url_for('animal_farm_staff.events_management'))
        if not event:
            event = Event(zoo_id=zoo.id)
            db.session.add(event)

        event.name = name
        event.type = event_type
        event.time = time_value
        event.location = location
        db.session.commit()
        flash('Event saved.', 'success')
        return redirect(url_for('animal_farm_staff.events_management'))

    events = Event.query.filter_by(zoo_id=zoo.id).order_by(Event.id.desc()).all()
    return render_template('animal_farm_staff/events.html', zoo=zoo, events=events)


@zoo_staff_bp.post('/events/<int:event_id>/delete')
def delete_event(event_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    event = Event.query.filter_by(id=event_id, zoo_id=zoo.id).first()
    if not event:
        flash('Event not found.', 'error')
        return redirect(url_for('animal_farm_staff.events_management'))

    db.session.delete(event)
    db.session.commit()
    flash('Event deleted.', 'success')
    return redirect(url_for('animal_farm_staff.events_management'))


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


@zoo_staff_bp.route('/map-zones')
def map_zones():
    zoo = _current_zoo()
    if not zoo:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))
    zones = ZooZone.query.filter_by(zoo_id=zoo.id).order_by(ZooZone.created_at.desc()).all()
    return render_template('animal_farm_staff/map_zones.html', zoo=zoo, zones=zones)


@zoo_staff_bp.route('/notifications')
def notifications():
    user = _current_user()
    if not user:
        return redirect(url_for('auth.login', module_name='zoo_staff'))
    items = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(100).all()
    unread = sum(1 for item in items if item.read_at is None)
    return render_template('animal_farm_staff/notifications.html', notifications=items, unread=unread)


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
