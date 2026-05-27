from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

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
    ZooAdminFeedbackReply,
    ZooSubscription,
    ZooZone,
    db,
)
from services import BookingValidationError, assign_booking_to_staff
from services.auth_guard import require_role_guard

animal_farm_admin_bp = Blueprint('animal_farm_admin', __name__)


@animal_farm_admin_bp.before_request
def require_zoo_admin():
    result = require_role_guard(expected_role='zoo_admin', login_module='zoo_admin')
    if result is not None:
        return result


def _current_user() -> User | None:
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(int(user_id))


def _current_zoo() -> Zoo | None:
    u = _current_user()
    if not u or not u.zoo_id:
        return None
    return Zoo.query.get(int(u.zoo_id))


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None

@animal_farm_admin_bp.route('/')
def dashboard():
    zoo = _current_zoo()
    if not zoo:
        flash('Your account is not linked to a zoo. Please contact support.', 'error')
        return render_template('animal_farm_admin/dashboard.html', zoo=None)

    # KPIs
    animals_count = Animal.query.filter_by(zoo_id=zoo.id).count()
    services_count = Service.query.filter_by(zoo_id=zoo.id).count()
    bookings_count = Booking.query.filter_by(zoo_id=zoo.id).count()

    # Revenue (current month, from bookings)
    now = datetime.utcnow()
    month_prefix = now.strftime('%Y-%m')
    month_bookings = Booking.query.filter(
        Booking.zoo_id == zoo.id,
        Booking.date.like(f"{month_prefix}%"),
    ).all()
    monthly_revenue = sum([float(b.amount or 0) for b in month_bookings])

    # Subscription status
    subscription = (
        ZooSubscription.query.filter_by(zoo_id=zoo.id)
        .order_by(ZooSubscription.end_date.desc())
        .first()
    )
    if subscription:
        subscription.refresh_status(now)
        db.session.commit()

    open_tasks = StaffTask.query.filter_by(zoo_id=zoo.id).filter(StaffTask.status != 'done').count()

    return render_template(
        'animal_farm_admin/dashboard.html',
        zoo=zoo,
        animals_count=animals_count,
        services_count=services_count,
        bookings_count=bookings_count,
        monthly_revenue=monthly_revenue,
        subscription=subscription,
        open_tasks=open_tasks,
    )


@animal_farm_admin_bp.route('/subscriptions')
def subscriptions():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    subscription = (
        ZooSubscription.query.filter_by(zoo_id=zoo.id)
        .order_by(ZooSubscription.end_date.desc())
        .first()
    )
    if subscription:
        subscription.refresh_status()
        db.session.commit()

    plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.price.asc()).all()
    payments = []
    if subscription:
        payments = (
            SubscriptionPayment.query.filter_by(subscription_id=subscription.id)
            .order_by(SubscriptionPayment.paid_at.desc())
            .limit(25)
            .all()
        )

    return render_template(
        'animal_farm_admin/subscriptions.html',
        zoo=zoo,
        subscription=subscription,
        plans=plans,
        payments=payments,
    )

@animal_farm_admin_bp.route('/bookings')
def booking_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    status = request.args.get('status')
    assigned_to = (request.args.get('assigned_to') or '').strip()
    query = Booking.query.filter_by(zoo_id=zoo.id)
    if status:
        query = query.filter_by(status=status)
    if assigned_to.isdigit():
        query = query.filter_by(assigned_staff_user_id=int(assigned_to))
    bookings = query.order_by(Booking.created_at.desc()).limit(200).all()

    staff_members = (
        User.query
        .filter_by(role='zoo_staff', zoo_id=zoo.id)
        .order_by(User.full_name.asc())
        .all()
    )

    return render_template(
        'animal_farm_admin/bookings.html',
        zoo=zoo,
        bookings=bookings,
        selected_status=status,
        staff_members=staff_members,
        selected_assigned_to=assigned_to,
    )


@animal_farm_admin_bp.post('/bookings/<booking_id>/status')
def update_booking_status(booking_id: str):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    booking = Booking.query.filter_by(id=booking_id, zoo_id=zoo.id).first()
    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    new_status = request.form.get('status')
    if new_status not in {'Pending', 'Confirmed', 'Cancelled'}:
        flash('Invalid status.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    booking.status = new_status
    db.session.commit()
    flash('Booking status updated.', 'success')
    return redirect(url_for('animal_farm_admin.booking_management'))


@animal_farm_admin_bp.post('/bookings/<booking_id>/assign')
def assign_booking(booking_id: str):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    booking = Booking.query.filter_by(id=booking_id, zoo_id=zoo.id).first()
    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    staff_user_id_raw = (request.form.get('staff_user_id') or '').strip()
    if not staff_user_id_raw:
        booking.assigned_staff_user_id = None
        db.session.commit()
        flash('Booking unassigned.', 'success')
        return redirect(url_for('animal_farm_admin.booking_management'))

    if not staff_user_id_raw.isdigit():
        flash('Invalid staff selection.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    staff_user = User.query.filter_by(
        id=int(staff_user_id_raw),
        role='zoo_staff',
        zoo_id=zoo.id,
    ).first()
    if not staff_user:
        flash('Selected staff member was not found.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    try:
        assign_booking_to_staff(booking=booking, staff_user=staff_user, zoo_id=zoo.id)
    except BookingValidationError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    flash('Booking assigned to staff.', 'success')
    return redirect(url_for('animal_farm_admin.booking_management'))

@animal_farm_admin_bp.route('/booking-management')
def booking_management_legacy_redirect():
    return redirect(url_for('animal_farm_admin.booking_management'), code=301)

@animal_farm_admin_bp.route('/profile')
def establishment_profile():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    return render_template('animal_farm_admin/profile.html', zoo=zoo)


@animal_farm_admin_bp.post('/profile/save')
def save_establishment_profile():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    name = (request.form.get('name') or '').strip()
    zoo_type = (request.form.get('type') or '').strip() or None
    location = (request.form.get('location') or '').strip() or None
    description = (request.form.get('description') or '').strip() or None
    image_url = (request.form.get('image_url') or '').strip() or None

    if not name:
        flash('Establishment name is required.', 'error')
        return redirect(url_for('animal_farm_admin.establishment_profile'))

    zoo.name = name
    zoo.type = zoo_type
    zoo.location = location
    zoo.description = description
    zoo.image_url = image_url
    db.session.commit()

    flash('Establishment profile updated.', 'success')
    return redirect(url_for('animal_farm_admin.establishment_profile'))

@animal_farm_admin_bp.route('/establishment-profile')
def establishment_profile_legacy_redirect():
    return redirect(url_for('animal_farm_admin.establishment_profile'), code=301)

@animal_farm_admin_bp.route('/services')
def services_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    services = Service.query.filter_by(zoo_id=zoo.id).order_by(Service.id.desc()).all()
    return render_template('animal_farm_admin/services.html', zoo=zoo, services=services)


@animal_farm_admin_bp.post('/services/save')
def save_service():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.services_management'))

    service_id = request.form.get('service_id')
    name = (request.form.get('name') or '').strip()
    price_raw = (request.form.get('price') or '').strip()
    description = (request.form.get('description') or '').strip() or None
    image_url = (request.form.get('image_url') or '').strip() or None

    if not name:
        flash('Service name is required.', 'error')
        return redirect(url_for('animal_farm_admin.services_management'))
    try:
        price = float(price_raw)
    except Exception:
        flash('Price must be a number.', 'error')
        return redirect(url_for('animal_farm_admin.services_management'))

    service = None
    if service_id:
        service = Service.query.filter_by(id=int(service_id), zoo_id=zoo.id).first()
    if not service:
        service = Service(zoo_id=zoo.id)
        db.session.add(service)

    service.name = name
    service.price = price
    service.description = description
    service.image_url = image_url

    db.session.commit()
    flash('Service saved.', 'success')
    return redirect(url_for('animal_farm_admin.services_management'))


@animal_farm_admin_bp.post('/services/<int:service_id>/delete')
def delete_service(service_id: int):
    zoo = _current_zoo()
    service = Service.query.filter_by(id=service_id, zoo_id=(zoo.id if zoo else None)).first()
    if not service:
        flash('Service not found.', 'error')
        return redirect(url_for('animal_farm_admin.services_management'))
    db.session.delete(service)
    db.session.commit()
    flash('Service deleted.', 'success')
    return redirect(url_for('animal_farm_admin.services_management'))


@animal_farm_admin_bp.route('/animals')
def animals_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    animals = Animal.query.filter_by(zoo_id=zoo.id).order_by(Animal.id.desc()).all()
    return render_template('animal_farm_admin/animals.html', zoo=zoo, animals=animals)


@animal_farm_admin_bp.post('/animals/save')
def save_animal():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.animals_management'))

    animal_id = request.form.get('animal_id')
    name = (request.form.get('name') or '').strip()
    species = (request.form.get('species') or '').strip() or None
    habitat = (request.form.get('habitat') or '').strip() or None
    status = (request.form.get('status') or '').strip() or None
    description = (request.form.get('description') or '').strip() or None
    image_url = (request.form.get('image_url') or '').strip() or None

    if not name:
        flash('Animal name is required.', 'error')
        return redirect(url_for('animal_farm_admin.animals_management'))

    animal = None
    if animal_id:
        animal = Animal.query.filter_by(id=int(animal_id), zoo_id=zoo.id).first()
    if not animal:
        animal = Animal(zoo_id=zoo.id)
        db.session.add(animal)

    animal.name = name
    animal.species = species
    animal.habitat = habitat
    animal.status = status
    animal.description = description
    animal.image_url = image_url

    db.session.commit()
    flash('Animal saved.', 'success')
    return redirect(url_for('animal_farm_admin.animals_management'))


@animal_farm_admin_bp.post('/animals/<int:animal_id>/delete')
def delete_animal(animal_id: int):
    zoo = _current_zoo()
    animal = Animal.query.filter_by(id=animal_id, zoo_id=(zoo.id if zoo else None)).first()
    if not animal:
        flash('Animal not found.', 'error')
        return redirect(url_for('animal_farm_admin.animals_management'))
    db.session.delete(animal)
    db.session.commit()
    flash('Animal deleted.', 'success')
    return redirect(url_for('animal_farm_admin.animals_management'))

@animal_farm_admin_bp.route('/services-management')
def services_management_legacy_redirect():
    return redirect(url_for('animal_farm_admin.services_management'), code=301)

@animal_farm_admin_bp.route('/events')
def events_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    events = Event.query.filter_by(zoo_id=zoo.id).order_by(Event.id.desc()).all()
    return render_template('animal_farm_admin/events.html', zoo=zoo, events=events)


@animal_farm_admin_bp.post('/events/save')
def save_event():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.events_management'))

    event_id = request.form.get('event_id')
    name = (request.form.get('name') or '').strip()
    event_type = (request.form.get('type') or '').strip() or None
    time = (request.form.get('time') or '').strip() or None
    location = (request.form.get('location') or '').strip() or None

    if not name:
        flash('Event name is required.', 'error')
        return redirect(url_for('animal_farm_admin.events_management'))

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

    db.session.commit()
    flash('Event saved.', 'success')
    return redirect(url_for('animal_farm_admin.events_management'))


@animal_farm_admin_bp.post('/events/<int:event_id>/delete')
def delete_event(event_id: int):
    zoo = _current_zoo()
    event = Event.query.filter_by(id=event_id, zoo_id=(zoo.id if zoo else None)).first()
    if not event:
        flash('Event not found.', 'error')
        return redirect(url_for('animal_farm_admin.events_management'))
    db.session.delete(event)
    db.session.commit()
    flash('Event deleted.', 'success')
    return redirect(url_for('animal_farm_admin.events_management'))

@animal_farm_admin_bp.route('/events-management')
def events_management_legacy_redirect():
    return redirect(url_for('animal_farm_admin.events_management'), code=301)

@animal_farm_admin_bp.route('/promotions')
def promotions_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    promo_type = request.args.get('promo_type')
    query = Promotion.query.filter_by(zoo_id=zoo.id, country='Philippines')
    if promo_type:
        query = query.filter_by(promo_type=promo_type)
    promotions = query.order_by(Promotion.id.desc()).all()
    promo_types = ['Family', 'Group Tour', 'Student', 'Senior', 'Seasonal']

    return render_template(
        'animal_farm_admin/promotions.html',
        zoo=zoo,
        promotions=promotions,
        promo_types=promo_types,
        selected_promo_type=promo_type,
    )


@animal_farm_admin_bp.post('/promotions/save')
def save_promotion():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.promotions_management'))

    promo_id = request.form.get('promo_id')
    name = (request.form.get('name') or '').strip()
    code = (request.form.get('code') or '').strip().upper()
    discount = (request.form.get('discount') or '').strip() or None
    valid_until = (request.form.get('valid_until') or '').strip() or None
    promo_type = (request.form.get('promo_type') or '').strip() or None

    if not name or not code:
        flash('Promotion name and code are required.', 'error')
        return redirect(url_for('animal_farm_admin.promotions_management'))

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

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Promotion code must be unique.', 'error')
        return redirect(url_for('animal_farm_admin.promotions_management'))

    flash('Promotion saved.', 'success')
    return redirect(url_for('animal_farm_admin.promotions_management'))


@animal_farm_admin_bp.post('/promotions/<int:promo_id>/delete')
def delete_promotion(promo_id: int):
    zoo = _current_zoo()
    promo = Promotion.query.filter_by(id=promo_id, zoo_id=(zoo.id if zoo else None)).first()
    if not promo:
        flash('Promotion not found.', 'error')
        return redirect(url_for('animal_farm_admin.promotions_management'))
    db.session.delete(promo)
    db.session.commit()
    flash('Promotion deleted.', 'success')
    return redirect(url_for('animal_farm_admin.promotions_management'))

@animal_farm_admin_bp.route('/promotions-management')
def promotions_management_legacy_redirect():
    return redirect(url_for('animal_farm_admin.promotions_management'), code=301)

@animal_farm_admin_bp.route('/feedback')
def visitor_feedback_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    rating = request.args.get('rating')
    query = Feedback.query.filter_by(zoo_id=zoo.id)
    if rating and rating.isdigit():
        query = query.filter_by(rating=int(rating))
    feedbacks = query.order_by(Feedback.id.desc()).limit(200).all()
    return render_template('animal_farm_admin/feedback.html', zoo=zoo, feedbacks=feedbacks, selected_rating=rating)


@animal_farm_admin_bp.post('/feedback/<int:feedback_id>/delete')
def delete_visitor_feedback(feedback_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    feedback = Feedback.query.filter_by(id=feedback_id, zoo_id=zoo.id).first()
    if not feedback:
        flash('Feedback not found.', 'error')
        return redirect(url_for('animal_farm_admin.visitor_feedback_management'))

    db.session.delete(feedback)
    db.session.commit()
    flash('Visitor feedback deleted.', 'success')
    return redirect(url_for('animal_farm_admin.visitor_feedback_management'))

@animal_farm_admin_bp.route('/visitor-feedback-management')
def visitor_feedback_management_legacy_redirect():
    return redirect(url_for('animal_farm_admin.visitor_feedback_management'), code=301)

@animal_farm_admin_bp.route('/map-zones')
def visitor_map_zone_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    zones = ZooZone.query.filter_by(zoo_id=zoo.id).order_by(ZooZone.created_at.desc()).all()
    landing_map = {
        'title': (zoo.landing_map_title or f'{zoo.name} Visitor Map').strip(),
        'description': (zoo.landing_map_description or '').strip(),
        'image_url': (zoo.landing_map_image_url or '').strip(),
        'updated_at': zoo.landing_map_updated_at,
    }
    return render_template('animal_farm_admin/map_zones.html', zoo=zoo, zones=zones, landing_map=landing_map)


@animal_farm_admin_bp.post('/map-zones/landing-map/save')
def save_landing_map():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))

    title = (request.form.get('landing_map_title') or '').strip()
    description = (request.form.get('landing_map_description') or '').strip() or None
    image_url = (request.form.get('landing_map_image_url') or '').strip() or None

    if image_url and not (
        image_url.startswith('http://')
        or image_url.startswith('https://')
        or image_url.startswith('/uploads/')
    ):
        flash('Map image URL must start with http://, https://, or /uploads/.', 'error')
        return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))

    zoo.landing_map_title = title or None
    zoo.landing_map_description = description
    zoo.landing_map_image_url = image_url
    zoo.landing_map_updated_at = datetime.utcnow()

    db.session.commit()
    flash('Landing page map settings updated.', 'success')
    return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))


@animal_farm_admin_bp.post('/map-zones/save')
def save_zone():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))

    zone_id = request.form.get('zone_id')
    name = (request.form.get('name') or '').strip()
    description = (request.form.get('description') or '').strip() or None
    map_image_url = (request.form.get('map_image_url') or '').strip() or None
    panorama_360_url = (request.form.get('panorama_360_url') or '').strip() or None

    if not name:
        flash('Zone name is required.', 'error')
        return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))

    zone = None
    if zone_id:
        zone = ZooZone.query.filter_by(id=int(zone_id), zoo_id=zoo.id).first()
    if not zone:
        zone = ZooZone(zoo_id=zoo.id)
        db.session.add(zone)

    zone.name = name
    zone.description = description
    zone.map_image_url = map_image_url
    zone.panorama_360_url = panorama_360_url

    db.session.commit()
    flash('Zone saved.', 'success')
    return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))


@animal_farm_admin_bp.post('/map-zones/<int:zone_id>/delete')
def delete_zone(zone_id: int):
    zoo = _current_zoo()
    zone = ZooZone.query.filter_by(id=zone_id, zoo_id=(zoo.id if zoo else None)).first()
    if not zone:
        flash('Zone not found.', 'error')
        return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))
    db.session.delete(zone)
    db.session.commit()
    flash('Zone deleted.', 'success')
    return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))

@animal_farm_admin_bp.route('/visitor-map-zone-management')
def visitor_map_zone_management_legacy_redirect():
    return redirect(url_for('animal_farm_admin.visitor_map_zone_management'), code=301)

@animal_farm_admin_bp.route('/revenue')
def payment_revenue_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    # last 6 months income (from bookings)
    now = datetime.utcnow()
    months = [(now - timedelta(days=30 * i)).strftime('%Y-%m') for i in range(5, -1, -1)]

    # Simpler: aggregate in Python based on Booking.date prefix
    bookings = Booking.query.filter_by(zoo_id=zoo.id).all()
    income_by_month = {m: 0.0 for m in months}
    for b in bookings:
        if not b.date:
            continue
        prefix = str(b.date)[:7]
        if prefix in income_by_month:
            income_by_month[prefix] += float(b.amount or 0)

    recent_bookings = (
        Booking.query.filter_by(zoo_id=zoo.id)
        .order_by(Booking.created_at.desc())
        .limit(15)
        .all()
    )
    total_revenue = sum([float(b.amount or 0) for b in bookings])

    return render_template(
        'animal_farm_admin/revenue.html',
        zoo=zoo,
        income_by_month=income_by_month,
        months=months,
        total_revenue=total_revenue,
        recent_bookings=recent_bookings,
    )

@animal_farm_admin_bp.route('/payment-revenue-management')
def payment_revenue_management_legacy_redirect():
    return redirect(url_for('animal_farm_admin.payment_revenue_management'), code=301)

@animal_farm_admin_bp.route('/analytics')
def analytics_reports():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    bookings = Booking.query.filter_by(zoo_id=zoo.id).all()
    total_bookings = len(bookings)
    total_visitors = sum([int(b.guests or 0) for b in bookings])
    total_income = sum([float(b.amount or 0) for b in bookings])

    # Top services by bookings
    service_counts: dict[str, int] = {}
    for b in bookings:
        key = b.service_name or (b.service.name if b.service else 'Unknown')
        service_counts[key] = service_counts.get(key, 0) + 1
    top_services = sorted(service_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return render_template(
        'animal_farm_admin/analytics.html',
        zoo=zoo,
        total_bookings=total_bookings,
        total_visitors=total_visitors,
        total_income=total_income,
        top_services=top_services,
    )


@animal_farm_admin_bp.route('/staff-management')
def staff_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    staff = User.query.filter_by(role='zoo_staff', zoo_id=zoo.id).order_by(User.full_name.asc()).all()
    tasks = StaffTask.query.filter_by(zoo_id=zoo.id).order_by(StaffTask.created_at.desc()).limit(200).all()
    return render_template('animal_farm_admin/staff_management.html', zoo=zoo, staff=staff, tasks=tasks)


@animal_farm_admin_bp.post('/staff-management/tasks/save')
def save_staff_task():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))

    task_id = request.form.get('task_id')
    title = (request.form.get('title') or '').strip()
    description = (request.form.get('description') or '').strip() or None
    due_date = _parse_date(request.form.get('due_date'))
    status = (request.form.get('status') or 'pending').strip()
    assigned_to = request.form.get('assigned_to_user_id')
    assigned_to_user_id = int(assigned_to) if assigned_to and assigned_to.isdigit() else None

    if not title:
        flash('Task title is required.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))
    if status not in {'pending', 'in_progress', 'done'}:
        flash('Invalid task status.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))
    if assigned_to_user_id:
        staff_user = User.query.filter_by(id=assigned_to_user_id, role='zoo_staff', zoo_id=zoo.id).first()
        if not staff_user:
            flash('Assigned staff user not found.', 'error')
            return redirect(url_for('animal_farm_admin.staff_management'))

    task = None
    if task_id:
        task = StaffTask.query.filter_by(id=int(task_id), zoo_id=zoo.id).first()
    if not task:
        task = StaffTask(zoo_id=zoo.id)
        db.session.add(task)

    task.title = title
    task.description = description
    task.due_date = due_date
    task.status = status
    task.assigned_to_user_id = assigned_to_user_id

    db.session.commit()
    flash('Task saved.', 'success')
    return redirect(url_for('animal_farm_admin.staff_management'))


@animal_farm_admin_bp.post('/staff-management/tasks/<int:task_id>/delete')
def delete_staff_task(task_id: int):
    zoo = _current_zoo()
    task = StaffTask.query.filter_by(id=task_id, zoo_id=(zoo.id if zoo else None)).first()
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted.', 'success')
    return redirect(url_for('animal_farm_admin.staff_management'))

@animal_farm_admin_bp.route('/analytics-reports')
def analytics_reports_legacy_redirect():
    return redirect(url_for('animal_farm_admin.analytics_reports'), code=301)

@animal_farm_admin_bp.route('/settings')
def settings():
    user = _current_user()
    zoo = _current_zoo()
    return render_template('animal_farm_admin/settings.html', zoo=zoo, user=user)


@animal_farm_admin_bp.post('/settings/profile')
def update_profile():
    user = _current_user()
    if not user:
        flash('Not logged in.', 'error')
        return redirect(url_for('animal_farm_admin.settings'))

    full_name = (request.form.get('full_name') or '').strip()
    username = (request.form.get('username') or '').strip() or None
    email = (request.form.get('email') or '').strip().lower()

    if not full_name or not email:
        flash('Full name and email are required.', 'error')
        return redirect(url_for('animal_farm_admin.settings'))

    if email != user.email:
        existing_email = User.query.filter(User.email == email, User.id != user.id).first()
        if existing_email:
            flash('Email already exists.', 'error')
            return redirect(url_for('animal_farm_admin.settings'))

    if username and username != user.username:
        existing_username = User.query.filter(User.username == username, User.id != user.id).first()
        if existing_username:
            flash('Username already exists.', 'error')
            return redirect(url_for('animal_farm_admin.settings'))

    user.full_name = full_name
    user.username = username
    user.email = email

    db.session.commit()
    session['full_name'] = user.full_name
    flash('Profile updated.', 'success')
    return redirect(url_for('animal_farm_admin.settings'))


@animal_farm_admin_bp.post('/settings/security')
def update_security():
    user = _current_user()
    if not user:
        flash('Not logged in.', 'error')
        return redirect(url_for('animal_farm_admin.settings'))

    current_password = request.form.get('current_password') or ''
    new_password = request.form.get('new_password') or ''
    confirm_password = request.form.get('confirm_password') or ''

    if not user.check_password(current_password):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('animal_farm_admin.settings'))

    if len(new_password) < 8:
        flash('New password must be at least 8 characters.', 'error')
        return redirect(url_for('animal_farm_admin.settings'))
    if new_password != confirm_password:
        flash('New password and confirmation do not match.', 'error')
        return redirect(url_for('animal_farm_admin.settings'))

    user.set_password(new_password)
    db.session.commit()
    flash('Password updated.', 'success')
    return redirect(url_for('animal_farm_admin.settings'))


@animal_farm_admin_bp.route('/system-feedback', methods=['GET', 'POST'])
def system_feedback():
    zoo = _current_zoo()
    user = _current_user()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    categories = ['Features', 'Support', 'Billing', 'Other']

    if request.method == 'POST':
        rating = request.form.get('rating', type=int)
        category = (request.form.get('category') or '').strip()
        comment = (request.form.get('comment') or '').strip()

        if category not in categories:
            flash('Please choose a valid feedback category.', 'error')
            return redirect(url_for('animal_farm_admin.system_feedback'))
        if not rating or rating < 1 or rating > 5:
            flash('Rating must be from 1 to 5.', 'error')
            return redirect(url_for('animal_farm_admin.system_feedback'))
        if not comment:
            flash('Comment is required.', 'error')
            return redirect(url_for('animal_farm_admin.system_feedback'))

        feedback = ZooAdminFeedback(
            zoo_id=zoo.id,
            user_id=user.id if user else None,
            category=category,
            rating=rating,
            comment=comment,
        )
        db.session.add(feedback)
        db.session.commit()
        flash('System feedback submitted.', 'success')
        return redirect(url_for('animal_farm_admin.system_feedback'))

    feedbacks = (
        ZooAdminFeedback.query
        .filter_by(zoo_id=zoo.id)
        .order_by(ZooAdminFeedback.created_at.desc())
        .all()
    )
    return render_template(
        'animal_farm_admin/system_feedback.html',
        zoo=zoo,
        feedbacks=feedbacks,
        categories=categories,
    )


@animal_farm_admin_bp.post('/system-feedback/<int:feedback_id>/update')
def update_system_feedback(feedback_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    feedback = ZooAdminFeedback.query.filter_by(id=feedback_id, zoo_id=zoo.id).first()
    if not feedback:
        flash('Feedback not found.', 'error')
        return redirect(url_for('animal_farm_admin.system_feedback'))
    if feedback.replies:
        flash('Feedback with an existing admin reply can no longer be edited.', 'error')
        return redirect(url_for('animal_farm_admin.system_feedback'))

    categories = {'Features', 'Support', 'Billing', 'Other'}
    rating = request.form.get('rating', type=int)
    category = (request.form.get('category') or '').strip()
    comment = (request.form.get('comment') or '').strip()

    if category not in categories:
        flash('Please choose a valid feedback category.', 'error')
        return redirect(url_for('animal_farm_admin.system_feedback'))
    if not rating or rating < 1 or rating > 5:
        flash('Rating must be from 1 to 5.', 'error')
        return redirect(url_for('animal_farm_admin.system_feedback'))
    if not comment:
        flash('Comment is required.', 'error')
        return redirect(url_for('animal_farm_admin.system_feedback'))

    feedback.category = category
    feedback.rating = rating
    feedback.comment = comment
    db.session.commit()
    flash('System feedback updated.', 'success')
    return redirect(url_for('animal_farm_admin.system_feedback'))


@animal_farm_admin_bp.post('/system-feedback/<int:feedback_id>/delete')
def delete_system_feedback(feedback_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    feedback = ZooAdminFeedback.query.filter_by(id=feedback_id, zoo_id=zoo.id).first()
    if not feedback:
        flash('Feedback not found.', 'error')
        return redirect(url_for('animal_farm_admin.system_feedback'))

    ZooAdminFeedbackReply.query.filter_by(feedback_id=feedback.id).delete(synchronize_session=False)
    db.session.delete(feedback)
    db.session.commit()
    flash('System feedback deleted.', 'success')
    return redirect(url_for('animal_farm_admin.system_feedback'))


@animal_farm_admin_bp.route('/support-feedback')
def support_feedback_legacy_redirect():
    return redirect(url_for('animal_farm_admin.system_feedback'), code=301)


@animal_farm_admin_bp.route('/logout')
def logout_legacy():
    return redirect(url_for('auth.logout'))
