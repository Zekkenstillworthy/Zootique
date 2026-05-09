from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from models import Animal, Booking, Event, Feedback, StaffTask, User, Zoo, ZooZone, db

zoo_staff_bp = Blueprint('animal_farm_staff', __name__)


@zoo_staff_bp.before_request
def require_zoo_staff():
    if session.get('role') != 'zoo_staff':
        return redirect(url_for('auth.login', module_name='zoo_staff'))
    user_id = session.get('user_id')
    if not user_id:
        session.clear()
        return redirect(url_for('auth.login', module_name='zoo_staff'))
    user = db.session.get(User, int(user_id))
    if not user or (getattr(user, 'status', 'active') or 'active') != 'active':
        session.clear()
        flash('Your account is not active. Please sign in again.', 'error')
        return redirect(url_for('auth.login', module_name='zoo_staff'))


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
    return render_template('animal_farm_staff/dashboard.html')


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
    query = Booking.query.filter_by(zoo_id=zoo.id, assigned_staff_user_id=user.id)
    if selected_status in {'Confirmed', 'Pending', 'Cancelled'}:
        query = query.filter_by(status=selected_status)
    else:
        selected_status = ''

    bookings = query.order_by(Booking.created_at.desc()).limit(300).all()
    all_bookings = Booking.query.filter_by(zoo_id=zoo.id, assigned_staff_user_id=user.id).all()

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
        assigned_staff_user_id=user.id,
    ).first()
    if not booking:
        flash('Assigned booking not found.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))

    new_status = (request.form.get('status') or '').strip()
    if new_status not in {'Pending', 'Confirmed', 'Cancelled'}:
        flash('Invalid booking status.', 'error')
        return redirect(url_for('animal_farm_staff.my_bookings'))

    booking.status = new_status
    db.session.commit()
    flash('Booking status updated.', 'success')
    return redirect(url_for('animal_farm_staff.my_bookings'))


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
    zoo = _current_zoo()
    if not user or not zoo:
        flash('Your account is not linked to an establishment.', 'error')
        return redirect(url_for('animal_farm_staff.dashboard'))

    since = datetime.utcnow() - timedelta(days=7)
    recent_tasks = (
        StaffTask.query
        .filter_by(zoo_id=zoo.id, assigned_to_user_id=user.id)
        .filter(StaffTask.created_at >= since)
        .order_by(StaffTask.created_at.desc())
        .limit(50)
        .all()
    )
    if not recent_tasks:
        recent_tasks = (
            StaffTask.query
            .filter_by(zoo_id=zoo.id)
            .filter(StaffTask.created_at >= since)
            .order_by(StaffTask.created_at.desc())
            .limit(50)
            .all()
        )

    return render_template('animal_farm_staff/notifications.html', recent_tasks=recent_tasks)


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
                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1].lower()
                if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
                    flash('Unsupported image type. Use png/jpg/webp/gif.', 'error')
                    return redirect(url_for('animal_farm_staff.profile'))

                folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'profile_pictures')
                os.makedirs(folder, exist_ok=True)
                stored_name = f"staff_{user.id}_{secrets.token_hex(6)}{ext}"
                file.save(os.path.join(folder, stored_name))
                user.profile_image = f"profile_pictures/{stored_name}"

            db.session.commit()
            session['full_name'] = user.full_name
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
