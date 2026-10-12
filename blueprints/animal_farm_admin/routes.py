from __future__ import annotations

from datetime import datetime, timedelta
import json

import os

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from services.storage import save_uploaded_image as _save_uploaded_image

from models import (
    Animal,
    Booking,
    BookingBundle,
    Event,
    Feedback,
    ParkRule,
    Promotion,
    Service,
    StaffTask,
    SubscriptionPayment,
    SubscriptionPlan,
    TriviaQuestion,
    User,
    Zoo,
    ZooAdminFeedback,
    ZooAdminFeedbackReply,
    ZooSubscription,
    ZooZone, ZooGraphConfig,
    db,
)
from services import BookingValidationError, assign_booking_to_staff
from services import (
    SubscriptionValidationError,
    subscribe_zoo_to_plan,
    get_zoo_subscription_tier,
    paywall_redirect,
    can_edit_feature,
    paywall_edit_error,
)
from services.subscription_guard import FEATURE_TIERS
from services.subscription_guard import feature_limit, limit_allows, feature_required_tier
from services.subscription_catalog import sort_plans
from services.subscription_catalog import plan_context
from services.layout_config import (
    WIDGET_CATALOG,
    build_zoo_dashboard_widget_map,
    get_layout_config_for_zoo,
    order_dashboard_widgets,
    save_layout_config,
)
from services.auth_guard import require_role_guard
from services.graph_builder import (
    GRAPH_CHART_TYPES,
    GRAPH_DATA_SOURCES,
    GRAPH_DATE_RANGES,
    GRAPH_GROUPS,
    build_graph_data,
    save_graph_config,
)
from services.zoo_settings import (
    DEFAULT_PAYMENT_METHODS,
    SUPPORTED_PAYMENT_METHODS,
    get_payment_methods,
    get_availability_settings,
    save_zoo_setting,
)

animal_farm_admin_bp = Blueprint('animal_farm_admin', __name__)



@animal_farm_admin_bp.before_request
def require_zoo_admin():
    result = require_role_guard(expected_role='zoo_admin', login_module='zoo_admin')
    if result is not None:
        return result


@animal_farm_admin_bp.context_processor
def inject_subscription_tier():
    """Inject the current zoo's subscription tier and feature editing permissions into every template."""
    zoo = _current_zoo()
    tier = get_zoo_subscription_tier(zoo)
    return {
        'g_sub_tier': tier,
        'can_edit_feature': lambda f: can_edit_feature(zoo, f),
        'feature_required_tier': feature_required_tier,
    }



def _current_user() -> User | None:
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, int(user_id))


def _current_zoo() -> Zoo | None:
    u = _current_user()
    if not u or not u.zoo_id:
        return None
    return db.session.get(Zoo, int(u.zoo_id))


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

    now = datetime.utcnow()
    layout_config = get_layout_config_for_zoo(zoo.id)
    widget_map = build_zoo_dashboard_widget_map(zoo, now=now)
    dashboard_widgets = order_dashboard_widgets(widget_map, layout_config)
    saved_graphs = ZooGraphConfig.query.filter_by(zoo_id=zoo.id, is_visible=True).order_by(ZooGraphConfig.created_at.desc()).limit(6).all()
    graph_data = {graph.id: build_graph_data(graph) for graph in saved_graphs}

    animals_count = Animal.query.filter_by(zoo_id=zoo.id).count()
    services_count = Service.query.filter_by(zoo_id=zoo.id).count()
    bookings_count = Booking.query.filter_by(zoo_id=zoo.id).count()
    monthly_revenue = widget_map.get('revenue_summary', {}).get('monthly_revenue', 0.0)

    subscription = (
        ZooSubscription.query.filter_by(zoo_id=zoo.id)
        .order_by(ZooSubscription.end_date.desc())
        .first()
    )

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
        layout_config=layout_config,
        layout_style=layout_config.get('layout_style', 'grid'),
        dashboard_widgets=dashboard_widgets,
        widget_map=widget_map,
        saved_graphs=saved_graphs,
        graph_data=graph_data,
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

    plans = sort_plans(SubscriptionPlan.query.filter_by(is_active=True).all())
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
        plan_contexts={plan.id: plan_context(plan) for plan in plans},
        current_plan_context=plan_context(subscription.plan) if subscription else None,
    )


@animal_farm_admin_bp.route('/payment-methods', methods=['GET', 'POST'])
def payment_methods():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    if request.method == 'POST':
        if not can_edit_feature(zoo, 'payment_methods'):
            return paywall_edit_error('Payment Methods', required_tier=FEATURE_TIERS.get('payment_methods', 1))
        selected = [value for value in request.form.getlist('methods') if value in SUPPORTED_PAYMENT_METHODS]
        if not selected:
            flash('Enable at least one payment method.', 'error')
            return redirect(url_for('animal_farm_admin.payment_methods'))
        save_zoo_setting(zoo.id, 'payment_methods', selected)
        db.session.commit()
        flash('Payment methods updated.', 'success')
    return render_template(
        'animal_farm_admin/payment_methods.html',
        zoo=zoo,
        methods=SUPPORTED_PAYMENT_METHODS,
        enabled_methods=get_payment_methods(zoo.id),
        can_edit=can_edit_feature(zoo, 'payment_methods'),
        required_tier=FEATURE_TIERS.get('payment_methods', 1),
    )


@animal_farm_admin_bp.route('/availability-settings', methods=['GET', 'POST'])
def availability_settings():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    services = Service.query.filter_by(zoo_id=zoo.id).order_by(Service.name.asc()).all()
    if request.method == 'POST':
        if not can_edit_feature(zoo, 'availability_settings'):
            return paywall_edit_error('Availability Settings', required_tier=FEATURE_TIERS.get('availability_settings', 1))
        try:
            opening = (request.form.get('opening_time') or '').strip()
            closing = (request.form.get('closing_time') or '').strip()
            datetime.strptime(opening, '%H:%M')
            datetime.strptime(closing, '%H:%M')
            if opening >= closing:
                raise ValueError('Closing time must be later than opening time.')
            slot_duration = int(request.form.get('slot_duration_minutes') or 60)
            daily_capacity = int(request.form.get('daily_capacity') or 0)
            slot_capacity = int(request.form.get('slot_capacity') or 0)
            max_advance_days = int(request.form.get('max_advance_days') or 90)
            if slot_duration < 30 or daily_capacity < 1 or slot_capacity < 1 or max_advance_days < 1:
                raise ValueError('Duration, capacities, and booking window must be positive.')
            closure_days = sorted({int(value) for value in request.form.getlist('closure_days') if value.isdigit() and 0 <= int(value) <= 6})
            for service in services:
                service.opening_time = opening
                service.closing_time = closing
                service.slot_duration_minutes = slot_duration
                service.daily_capacity = daily_capacity
                service.slot_capacity = slot_capacity
            save_zoo_setting(zoo.id, 'availability', {
                'closure_days': closure_days,
                'max_advance_days': max_advance_days,
            })
            db.session.commit()
            flash('Availability settings updated.', 'success')
        except (TypeError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    settings = get_availability_settings(zoo.id)
    reference = services[0] if services else None
    return render_template(
        'animal_farm_admin/availability_settings.html',
        zoo=zoo,
        service=reference,
        settings=settings,
        can_edit=can_edit_feature(zoo, 'availability_settings'),
        required_tier=FEATURE_TIERS.get('availability_settings', 1),
    )


@animal_farm_admin_bp.post('/subscriptions/subscribe')
def self_subscribe():
    """Zoo Admin self-subscribes to a plan. Creates a pending subscription."""
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    plan_id_raw = (request.form.get('plan_id') or '').strip()
    if not plan_id_raw or not plan_id_raw.isdigit():
        flash('Please select a valid plan.', 'error')
        return redirect(url_for('animal_farm_admin.subscriptions'))

    plan = db.session.get(SubscriptionPlan, int(plan_id_raw))
    if not plan or not plan.is_active:
        flash('Selected plan is not available.', 'error')
        return redirect(url_for('animal_farm_admin.subscriptions'))

    # Check if there's already an active subscription — treat as upgrade
    existing = (
        ZooSubscription.query.filter_by(zoo_id=zoo.id)
        .order_by(ZooSubscription.end_date.desc())
        .first()
    )
    if existing:
        existing.refresh_status()
        if existing.status == 'active':
            if existing.plan_id == plan.id:
                flash('This plan is already active for your zoo.', 'error')
                return redirect(url_for('animal_farm_admin.subscriptions'))
            current_tier = int(existing.plan.tier_level or 1)
            requested_tier = int(plan.tier_level or 1)
            if requested_tier < current_tier:
                flash('Downgrades are not supported while your current subscription is active.', 'error')
                return redirect(url_for('animal_farm_admin.subscriptions'))
            if requested_tier == current_tier:
                flash('Choose a plan with a different tier to change your subscription.', 'error')
                return redirect(url_for('animal_farm_admin.subscriptions'))

    try:
        subscribe_zoo_to_plan(
            zoo_id=zoo.id,
            plan=plan,
            auto_approve=False,  # Set True to skip Super Admin approval
        )
        flash(
            f'Your subscription request for <strong>{plan.name}</strong> has been submitted. '
            f'A Super Administrator will review and activate it shortly.',
            'success',
        )
    except SubscriptionValidationError as exc:
        flash(str(exc), 'error')

    return redirect(url_for('animal_farm_admin.subscriptions'))

@animal_farm_admin_bp.get('/layout-changer')
def layout_changer():
    """Zoo Admin: Let zoo admins customise their own dashboard layout."""
    zoo = _current_zoo()
    if not zoo:
        flash('Your account is not linked to a zoo.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    now = datetime.utcnow()
    layout_config = get_layout_config_for_zoo(zoo.id)
    widget_map = build_zoo_dashboard_widget_map(zoo, now=now)
    dashboard_widgets = order_dashboard_widgets(widget_map, layout_config)

    return render_template(
        'animal_farm_admin/layout_changer.html',
        zoo=zoo,
        layout_config=layout_config,
        dashboard_widgets=dashboard_widgets,
        layout_styles=[
            {'value': 'grid',    'label': 'Grid'},
            {'value': 'list',    'label': 'List'},
            {'value': 'compact', 'label': 'Compact'},
        ],
        theme_variants=[
            {'value': 'light',      'label': 'Light'},
            {'value': 'zoo_accent', 'label': 'Zoo Branded'},
        ],
    )


import json as _json

@animal_farm_admin_bp.post('/layout-changer/save')
def save_layout():
    """Persist the zoo admin's chosen dashboard layout."""
    zoo = _current_zoo()
    if not zoo:
        flash('Your account is not linked to a zoo.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    if not can_edit_feature(zoo, 'layout_changer'):
        return paywall_edit_error('Dashboard Layout', required_tier=2)

    # Parse widget order
    widget_order_raw = (request.form.get('widget_order') or '').strip()
    try:
        widget_order = _json.loads(widget_order_raw) if widget_order_raw else []
    except ValueError:
        widget_order = []

    # Collect visibility
    widget_visibility = {w['id']: False for w in WIDGET_CATALOG}
    for wid in request.form.getlist('visible_widgets'):
        if wid in widget_visibility:
            widget_visibility[wid] = True

    layout_style = (request.form.get('layout_style') or 'grid').strip().lower()
    theme_variant = (request.form.get('theme_variant') or 'light').strip().lower()

    save_layout_config(
        zoo_id=zoo.id,
        widget_visibility=widget_visibility,
        widget_order=widget_order,
        layout_style=layout_style,
        theme_variant=theme_variant,
    )
    db.session.commit()
    flash('Dashboard layout saved successfully.', 'success')
    return redirect(url_for('animal_farm_admin.layout_changer'))


@animal_farm_admin_bp.route('/bookings')
def booking_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    status = request.args.get('status')
    assigned_to = (request.args.get('assigned_to') or '').strip()
    query = Booking.query.filter_by(zoo_id=zoo.id)
    valid_statuses = {'Pending', 'Confirmed', 'Cancelled', 'Finished'}
    if status and status in valid_statuses:
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

    services = (
        Service.query
        .filter_by(zoo_id=zoo.id)
        .order_by(Service.name.asc())
        .all()
    )

    return render_template(
        'animal_farm_admin/bookings.html',
        zoo=zoo,
        bookings=bookings,
        selected_status=status,
        staff_members=staff_members,
        services=services,
        selected_assigned_to=assigned_to,
    )


@animal_farm_admin_bp.route('/booking-bundles')
def booking_bundles():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    bundles = BookingBundle.query.filter_by(zoo_id=zoo.id).order_by(BookingBundle.created_at.desc()).all()
    services = Service.query.filter_by(zoo_id=zoo.id).order_by(Service.name.asc()).all()
    return render_template(
        'animal_farm_admin/booking_bundles.html',
        zoo=zoo,
        bundles=bundles,
        services=services,
        can_edit=can_edit_feature(zoo, 'booking_bundles'),
        required_tier=FEATURE_TIERS.get('booking_bundles', 1),
    )


@animal_farm_admin_bp.post('/booking-bundles/create')
def create_booking_bundle():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    if not can_edit_feature(zoo, 'booking_bundles'):
        return paywall_edit_error('Booking Bundles', required_tier=FEATURE_TIERS.get('booking_bundles', 1))
    if not request.form.get('bundle_id') and not limit_allows(
        zoo, 'promo_bundles', BookingBundle.query.filter_by(zoo_id=zoo.id).count()
    ):
        return paywall_edit_error(
            f"Promo Bundles (limit {feature_limit(zoo, 'promo_bundles')})",
            required_tier=FEATURE_TIERS.get('booking_bundles', 1),
        )
    bundle, error = _bundle_from_request(zoo)
    if error:
        flash(error, 'error')
    else:
        db.session.add(bundle)
        db.session.commit()
        flash('Booking bundle created.', 'success')
    return redirect(url_for('animal_farm_admin.booking_bundles'))


@animal_farm_admin_bp.post('/booking-bundles/<int:bundle_id>/update')
def update_booking_bundle(bundle_id: int):
    zoo = _current_zoo()
    bundle = BookingBundle.query.filter_by(id=bundle_id, zoo_id=zoo.id if zoo else None).first()
    if not zoo or not bundle:
        flash('Booking bundle not found.', 'error')
        return redirect(url_for('animal_farm_admin.booking_bundles'))
    if not can_edit_feature(zoo, 'booking_bundles'):
        return paywall_edit_error('Booking Bundles', required_tier=FEATURE_TIERS.get('booking_bundles', 1))
    updated, error = _bundle_from_request(zoo, bundle=bundle)
    if error:
        flash(error, 'error')
    else:
        db.session.commit()
        flash('Booking bundle updated.', 'success')
    return redirect(url_for('animal_farm_admin.booking_bundles'))


@animal_farm_admin_bp.post('/booking-bundles/<int:bundle_id>/toggle')
def toggle_booking_bundle(bundle_id: int):
    zoo = _current_zoo()
    bundle = BookingBundle.query.filter_by(id=bundle_id, zoo_id=zoo.id if zoo else None).first()
    if not zoo or not bundle:
        flash('Booking bundle not found.', 'error')
        return redirect(url_for('animal_farm_admin.booking_bundles'))
    if not can_edit_feature(zoo, 'booking_bundles'):
        return paywall_edit_error('Booking Bundles', required_tier=FEATURE_TIERS.get('booking_bundles', 1))
    bundle.is_active = not bundle.is_active
    db.session.commit()
    flash('Booking bundle status updated.', 'success')
    return redirect(url_for('animal_farm_admin.booking_bundles'))


def _bundle_from_request(zoo: Zoo, bundle: BookingBundle | None = None):
    name = (request.form.get('name') or '').strip()
    if not name:
        return None, 'Bundle name is required.'
    service_id_raw = (request.form.get('service_id') or '').strip()
    service = None
    if service_id_raw:
        if not service_id_raw.isdigit():
            return None, 'Select a valid service.'
        service = Service.query.filter_by(id=int(service_id_raw), zoo_id=zoo.id).first()
        if not service:
            return None, 'Selected service does not belong to this zoo.'
    def number(field, default, integer=False):
        raw = (request.form.get(field) or '').strip()
        try:
            return int(raw) if integer else float(raw)
        except ValueError:
            return default
    min_guests = number('min_guests', 1, True)
    max_guests = number('max_guests', 50, True)
    price = number('price', 0)
    discount_value = number('discount_value', 0)
    discount_type = (request.form.get('discount_type') or 'none').strip().lower()
    if min_guests < 1 or max_guests < min_guests:
        return None, 'Guest limits are invalid.'
    if price < 0 or discount_value < 0 or discount_type not in {'none', 'fixed', 'percent'}:
        return None, 'Bundle pricing is invalid.'
    target = bundle or BookingBundle(zoo_id=zoo.id)
    target.service_id = service.id if service else None
    target.name = name
    target.description = (request.form.get('description') or '').strip() or None
    target.eligibility = (request.form.get('eligibility') or '').strip() or None
    target.min_guests = min_guests
    target.max_guests = max_guests
    target.price = price
    target.discount_type = discount_type
    target.discount_value = discount_value
    target.valid_from = _parse_date(request.form.get('valid_from'))
    target.valid_until = _parse_date(request.form.get('valid_until'))
    target.is_active = request.form.get('is_active') == 'on'
    return target, None



@animal_farm_admin_bp.post('/bookings/create')
def create_booking():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    service_id_raw = (request.form.get('service_id') or '').strip()
    date = (request.form.get('date') or '').strip()
    time = (request.form.get('time') or '').strip()
    guests = request.form.get('guests', type=int) or 1
    amount_raw = (request.form.get('amount') or '').strip()
    status = (request.form.get('status') or 'Pending').strip()
    staff_user_id_raw = (request.form.get('assigned_staff_user_id') or '').strip()
    image_file = request.files.get('image_file')

    if not date or not time:
        flash('Date and time are required.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

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

    assigned_staff_user_id = None
    if staff_user_id_raw and staff_user_id_raw.isdigit():
        staff_user = User.query.filter_by(id=int(staff_user_id_raw), role='zoo_staff', zoo_id=zoo.id).first()
        if staff_user:
            assigned_staff_user_id = staff_user.id

    import secrets
    booking = Booking(
        id=secrets.token_hex(8),
        zoo_id=zoo.id,
        service_id=service.id if service else None,
        service_name=service.name if service else None,
        date=date,
        time=time,
        guests=guests,
        amount=amount or 0,
        status=status if status in {'Pending', 'Confirmed', 'Cancelled', 'Finished'} else 'Pending',
        assigned_staff_user_id=assigned_staff_user_id,
    )
    db.session.add(booking)

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'booking_images')
        if uploaded_url:
            booking.image_url = uploaded_url

    db.session.commit()
    flash('Booking created.', 'success')
    return redirect(url_for('animal_farm_admin.booking_management'))


@animal_farm_admin_bp.post('/bookings/<booking_id>/update')
def update_booking(booking_id: str):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    booking = Booking.query.filter_by(id=booking_id, zoo_id=zoo.id).first()
    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    service_id_raw = (request.form.get('service_id') or '').strip()
    date = (request.form.get('date') or '').strip()
    time = (request.form.get('time') or '').strip()
    guests = request.form.get('guests', type=int) or 1
    amount_raw = (request.form.get('amount') or '').strip()
    status = (request.form.get('status') or '').strip()
    staff_user_id_raw = (request.form.get('assigned_staff_user_id') or '').strip()
    image_file = request.files.get('image_file')

    if not date:
        flash('Booking date is required.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))
    if not time:
        flash('Booking time is required.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))
    if guests < 1:
        guests = 1
    if status and status not in {'Pending', 'Confirmed', 'Cancelled'}:
        flash('Invalid status.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))

    service = None
    if service_id_raw:
        if not service_id_raw.isdigit():
            flash('Invalid service selection.', 'error')
            return redirect(url_for('animal_farm_admin.booking_management'))
        service = Service.query.filter_by(id=int(service_id_raw), zoo_id=zoo.id).first()
        if not service:
            flash('Selected service was not found.', 'error')
            return redirect(url_for('animal_farm_admin.booking_management'))

    assigned_staff_user_id = None
    if staff_user_id_raw:
        if not staff_user_id_raw.isdigit():
            flash('Invalid staff selection.', 'error')
            return redirect(url_for('animal_farm_admin.booking_management'))
        staff_user = User.query.filter_by(id=int(staff_user_id_raw), role='zoo_staff', zoo_id=zoo.id).first()
        if not staff_user:
            flash('Selected staff member was not found.', 'error')
            return redirect(url_for('animal_farm_admin.booking_management'))
        assigned_staff_user_id = staff_user.id

    amount = None
    if amount_raw:
        try:
            amount = float(amount_raw)
        except Exception:
            flash('Amount must be a number.', 'error')
            return redirect(url_for('animal_farm_admin.booking_management'))

    booking.date = date
    booking.time = time
    booking.guests = guests
    if status:
        booking.status = status
    booking.assigned_staff_user_id = assigned_staff_user_id

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
            return redirect(url_for('animal_farm_admin.booking_management'))
        booking.image_url = uploaded_url

    db.session.commit()
    flash('Booking updated.', 'success')
    return redirect(url_for('animal_farm_admin.booking_management'))


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
    if new_status not in {'Pending', 'Confirmed', 'Cancelled', 'Finished'}:
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


@animal_farm_admin_bp.post('/bookings/<booking_id>/delete')
def delete_booking(booking_id: str):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))
    booking = Booking.query.filter_by(id=booking_id, zoo_id=zoo.id).first()
    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('animal_farm_admin.booking_management'))
    db.session.delete(booking)
    db.session.commit()
    flash('Booking removed.', 'success')
    return redirect(url_for('animal_farm_admin.booking_management'))

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
    image_file = request.files.get('image_file')

    if not name:
        flash('Establishment name is required.', 'error')
        return redirect(url_for('animal_farm_admin.establishment_profile'))

    zoo.name = name
    zoo.type = zoo_type
    zoo.location = location
    zoo.description = description

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'zoo_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_admin.establishment_profile'))
        zoo.image_url = uploaded_url
    db.session.commit()

    flash('Establishment profile updated.', 'success')
    return redirect(url_for('animal_farm_admin.establishment_profile'))


@animal_farm_admin_bp.route('/park-rules')
def park_rules_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    rules = ParkRule.query.filter_by(zoo_id=zoo.id).order_by(ParkRule.display_order.asc(), ParkRule.id.asc()).all()
    return render_template('animal_farm_admin/park_rules.html', zoo=zoo, rules=rules)


@animal_farm_admin_bp.post('/park-rules/save')
def save_park_rule():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    if not can_edit_feature(zoo, 'park_rules'):
        return paywall_edit_error('Park Rules', required_tier=1)

    rule_id = request.form.get('rule_id', type=int)
    title = (request.form.get('title') or '').strip()
    description = (request.form.get('description') or '').strip()
    display_order = request.form.get('display_order', type=int)
    if not title or not description:
        flash('Rule title and description are required.', 'error')
        return redirect(url_for('animal_farm_admin.park_rules_management'))

    rule = ParkRule.query.filter_by(id=rule_id, zoo_id=zoo.id).first() if rule_id else None
    if rule_id and not rule:
        flash('Park rule not found.', 'error')
        return redirect(url_for('animal_farm_admin.park_rules_management'))
    if not rule:
        rule = ParkRule(zoo_id=zoo.id)
        db.session.add(rule)
    rule.title = title
    rule.description = description
    rule.display_order = display_order if display_order is not None and display_order >= 0 else 0
    db.session.commit()
    flash('Park rule saved.', 'success')
    return redirect(url_for('animal_farm_admin.park_rules_management'))


@animal_farm_admin_bp.post('/park-rules/<int:rule_id>/delete')
def delete_park_rule(rule_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    if not can_edit_feature(zoo, 'park_rules'):
        return paywall_edit_error('Park Rules', required_tier=1)
    rule = ParkRule.query.filter_by(id=rule_id, zoo_id=zoo.id).first()
    if not rule:
        flash('Park rule not found.', 'error')
        return redirect(url_for('animal_farm_admin.park_rules_management'))
    db.session.delete(rule)
    db.session.commit()
    flash('Park rule deleted.', 'success')
    return redirect(url_for('animal_farm_admin.park_rules_management'))

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
    if not can_edit_feature(zoo, 'services'):
        return paywall_edit_error('Services', required_tier=1)

    service_id = request.form.get('service_id')
    name = (request.form.get('name') or '').strip()
    price_raw = (request.form.get('price') or '').strip()
    description = (request.form.get('description') or '').strip() or None
    image_file = request.files.get('image_file')

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
    service.opening_time = (request.form.get('opening_time') or '08:00').strip()
    service.closing_time = (request.form.get('closing_time') or '17:00').strip()
    service.slot_duration_minutes = request.form.get('slot_duration_minutes', type=int) or 60
    service.daily_capacity = request.form.get('daily_capacity', type=int) or 50
    service.slot_capacity = request.form.get('slot_capacity', type=int) or 15

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'service_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_admin.services_management'))
        service.image_url = uploaded_url

    db.session.commit()
    flash('Service saved.', 'success')
    return redirect(url_for('animal_farm_admin.services_management'))


@animal_farm_admin_bp.post('/services/<int:service_id>/delete')
def delete_service(service_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.services_management'))
    if not can_edit_feature(zoo, 'services'):
        return paywall_edit_error('Services', required_tier=1)
    service = Service.query.filter_by(id=service_id, zoo_id=zoo.id).first()
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
    zones = ZooZone.query.filter_by(zoo_id=zoo.id).order_by(ZooZone.name.asc()).all()
    return render_template('animal_farm_admin/animals.html', zoo=zoo, animals=animals, zones=zones)


@animal_farm_admin_bp.post('/animals/save')
def save_animal():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.animals_management'))
    if not animal_id and not limit_allows(
        zoo, 'animals', Animal.query.filter_by(zoo_id=zoo.id).count()
    ):
        return paywall_edit_error(
            f"Animals (limit {feature_limit(zoo, 'animals')})",
            required_tier=FEATURE_TIERS.get('animals', 1),
        )
    if not can_edit_feature(zoo, 'animals'):
        return paywall_edit_error('Animals', required_tier=1)

    animal_id = request.form.get('animal_id')
    name = (request.form.get('name') or '').strip()
    species = (request.form.get('species') or '').strip() or None
    habitat = (request.form.get('habitat') or '').strip() or None
    status = (request.form.get('status') or '').strip() or None
    description = (request.form.get('description') or '').strip() or None
    age = (request.form.get('age') or '').strip() or None
    fun_facts = (request.form.get('fun_facts') or '').strip() or None
    zone_id = request.form.get('zone_id', type=int) or None
    image_file = request.files.get('image_file')

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
    animal.age = age
    animal.fun_facts = fun_facts
    animal.zone_id = zone_id

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'animal_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_admin.animals_management'))
        animal.image_url = uploaded_url

    db.session.commit()
    flash('Animal saved.', 'success')
    return redirect(url_for('animal_farm_admin.animals_management'))


@animal_farm_admin_bp.post('/animals/<int:animal_id>/delete')
def delete_animal(animal_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.animals_management'))
    if not can_edit_feature(zoo, 'animals'):
        return paywall_edit_error('Animals', required_tier=1)
    animal = Animal.query.filter_by(id=animal_id, zoo_id=zoo.id).first()
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

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'event_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_admin.events_management'))
        event.image_url = uploaded_url

    db.session.commit()
    flash('Event saved.', 'success')
    return redirect(url_for('animal_farm_admin.events_management'))


@animal_farm_admin_bp.post('/events/<int:event_id>/delete')
def delete_event(event_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.events_management'))
    if not can_edit_feature(zoo, 'events'):
        return paywall_edit_error('Events', required_tier=1)
    event = Event.query.filter_by(id=event_id, zoo_id=zoo.id).first()
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

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'promotion_images')
        if not uploaded_url:
            return redirect(url_for('animal_farm_admin.promotions_management'))
        promotion.image_url = uploaded_url

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
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.promotions_management'))
    if not can_edit_feature(zoo, 'promotions'):
        return paywall_edit_error('Promotions', required_tier=1)
    promo = Promotion.query.filter_by(id=promo_id, zoo_id=zoo.id).first()
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
    if get_zoo_subscription_tier(zoo) < 1:
        return paywall_redirect(required_tier=1)

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
            return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))
        zoo.landing_map_image_url = uploaded_url
    zoo.landing_map_updated_at = datetime.utcnow()

    db.session.commit()
    flash('Landing page map settings updated.', 'success')
    return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))


@animal_farm_admin_bp.post('/map-zones/pin-positions/save')
def save_zone_pin_positions():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))
    if not can_edit_feature(zoo, 'map_zones'):
        return paywall_edit_error('Map Pin Positions', required_tier=2)

    try:
        positions = json.loads(request.form.get('pin_positions') or '{}')
        if not isinstance(positions, dict):
            raise ValueError
        zones = {str(zone.id): zone for zone in ZooZone.query.filter_by(zoo_id=zoo.id).all()}
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
        return redirect(url_for('animal_farm_admin.visitor_map_zone_management', tab='pin-editor'))

    db.session.commit()
    flash('Map pin positions saved.', 'success')
    return redirect(url_for('animal_farm_admin.visitor_map_zone_management', tab='pin-editor'))


@animal_farm_admin_bp.post('/map-zones/save')
def save_zone():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))
    if not can_edit_feature(zoo, 'map_zones'):
        return paywall_edit_error('Map Zones', required_tier=2)

    zone_id = request.form.get('zone_id')
    name = (request.form.get('name') or '').strip()
    description = (request.form.get('description') or '').strip() or None
    panorama_360_url = (request.form.get('panorama_360_url') or '').strip() or None
    map_image_file = request.files.get('map_image_file')

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
    zone.panorama_360_url = panorama_360_url

    if map_image_file and map_image_file.filename:
        uploaded_url = _save_uploaded_image(map_image_file, 'zone_maps')
        if not uploaded_url:
            return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))
        zone.map_image_url = uploaded_url

    db.session.commit()
    flash('Zone saved.', 'success')
    return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))


@animal_farm_admin_bp.post('/map-zones/<int:zone_id>/delete')
def delete_zone(zone_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.visitor_map_zone_management'))
    if not can_edit_feature(zoo, 'map_zones'):
        return paywall_edit_error('Map Zones', required_tier=2)
    zone = ZooZone.query.filter_by(id=zone_id, zoo_id=zoo.id).first()
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


@animal_farm_admin_bp.route('/graph-builder')
def graph_builder():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    graphs = ZooGraphConfig.query.filter_by(zoo_id=zoo.id).order_by(ZooGraphConfig.created_at.desc()).all()
    graph_data = {graph.id: build_graph_data(graph) for graph in graphs if graph.is_visible}
    return render_template(
        'animal_farm_admin/graph_builder.html',
        zoo=zoo,
        graphs=graphs,
        graph_data=graph_data,
        chart_types=sorted(GRAPH_CHART_TYPES),
        data_sources=sorted(GRAPH_DATA_SOURCES),
        date_ranges=sorted(GRAPH_DATE_RANGES),
        groups=sorted(GRAPH_GROUPS),
        can_edit=can_edit_feature(zoo, 'graph_builder'),
        required_tier=FEATURE_TIERS.get('graph_builder', 2),
    )


@animal_farm_admin_bp.post('/graph-builder/save')
def save_graph():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    if not can_edit_feature(zoo, 'graph_builder'):
        return paywall_edit_error('Graph Builder', required_tier=FEATURE_TIERS.get('graph_builder', 2))

    graph_id = request.form.get('graph_id', type=int)
    graph = ZooGraphConfig.query.filter_by(id=graph_id, zoo_id=zoo.id).first() if graph_id else None
    try:
        save_graph_config(
            zoo_id=zoo.id,
            config=graph,
            name=(request.form.get('name') or '').strip(),
            chart_type=(request.form.get('chart_type') or '').strip(),
            data_source=(request.form.get('data_source') or '').strip(),
            date_range=(request.form.get('date_range') or '').strip(),
            group_by=(request.form.get('group_by') or '').strip(),
            is_visible=request.form.get('is_visible') == 'on',
        )
        db.session.commit()
        flash('Graph configuration saved.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('animal_farm_admin.graph_builder'))


@animal_farm_admin_bp.post('/graph-builder/<int:graph_id>/delete')
def delete_graph(graph_id: int):
    zoo = _current_zoo()
    graph = ZooGraphConfig.query.filter_by(id=graph_id, zoo_id=zoo.id if zoo else None).first()
    if not zoo or not graph:
        flash('Graph configuration not found.', 'error')
        return redirect(url_for('animal_farm_admin.graph_builder'))
    if not can_edit_feature(zoo, 'graph_builder'):
        return paywall_edit_error('Graph Builder', required_tier=FEATURE_TIERS.get('graph_builder', 2))
    db.session.delete(graph)
    db.session.commit()
    flash('Graph configuration deleted.', 'success')
    return redirect(url_for('animal_farm_admin.graph_builder'))


@animal_farm_admin_bp.route('/staff-management')
def staff_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    staff = User.query.filter_by(role='zoo_staff', zoo_id=zoo.id).order_by(User.full_name.asc()).all()
    tasks = StaffTask.query.filter_by(zoo_id=zoo.id).order_by(StaffTask.created_at.desc()).limit(200).all()
    return render_template('animal_farm_admin/staff_management.html', zoo=zoo, staff=staff, tasks=tasks)


@animal_farm_admin_bp.post('/staff-management/staff/save')
def save_staff_user():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))
    if not can_edit_feature(zoo, 'staff_management'):
        return paywall_edit_error(
            'Staff Users',
            required_tier=FEATURE_TIERS.get('staff_management', 1),
        )

    user_id = (request.form.get('user_id') or '').strip()
    full_name = (request.form.get('full_name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    username = (request.form.get('username') or '').strip() or None
    status = (request.form.get('status') or 'active').strip().lower()
    password = request.form.get('password') or ''
    image_file = request.files.get('profile_image_file')

    if not full_name or not email:
        flash('Full name and email are required.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))
    if status not in {'active', 'suspended'}:
        flash('Invalid staff status.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))

    staff_user = None
    if user_id:
        if not user_id.isdigit():
            flash('Invalid staff user.', 'error')
            return redirect(url_for('animal_farm_admin.staff_management'))
        staff_user = User.query.filter_by(id=int(user_id), role='zoo_staff', zoo_id=zoo.id).first()
        if not staff_user:
            flash('Staff user not found.', 'error')
            return redirect(url_for('animal_farm_admin.staff_management'))

    existing_email = User.query.filter(User.email == email)
    if staff_user:
        existing_email = existing_email.filter(User.id != staff_user.id)
    if existing_email.first():
        flash('Email already exists.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))

    if username:
        existing_username = User.query.filter(User.username == username)
        if staff_user:
            existing_username = existing_username.filter(User.id != staff_user.id)
        if existing_username.first():
            flash('Username already exists.', 'error')
            return redirect(url_for('animal_farm_admin.staff_management'))

    if not staff_user:
        if not limit_allows(
            zoo, 'staff_accounts', User.query.filter_by(role='zoo_staff', zoo_id=zoo.id).count()
        ):
            return paywall_edit_error(
                f"Staff Accounts (limit {feature_limit(zoo, 'staff_accounts')})",
                required_tier=FEATURE_TIERS.get('staff_management', 1),
            )
        if len(password) < 8:
            flash('Password is required (min 8 characters) for new staff.', 'error')
            return redirect(url_for('animal_farm_admin.staff_management'))
        staff_user = User(email=email, role='zoo_staff', zoo_id=zoo.id)
        staff_user.set_password(password)
        db.session.add(staff_user)
    else:
        staff_user.email = email
        if password:
            if len(password) < 8:
                flash('Password must be at least 8 characters.', 'error')
                return redirect(url_for('animal_farm_admin.staff_management'))
            staff_user.set_password(password)

    staff_user.full_name = full_name
    staff_user.username = username
    staff_user.status = status

    if image_file and image_file.filename:
        uploaded_url = _save_uploaded_image(image_file, 'profile_pictures')
        if not uploaded_url:
            return redirect(url_for('animal_farm_admin.staff_management'))
        staff_user.profile_image = uploaded_url

    db.session.commit()
    flash('Staff user saved.', 'success')
    return redirect(url_for('animal_farm_admin.staff_management'))


@animal_farm_admin_bp.post('/staff-management/staff/<int:user_id>/delete')
def delete_staff_user(user_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))
    if not can_edit_feature(zoo, 'staff_management'):
        return paywall_edit_error('Staff Users', required_tier=2)
    staff_user = User.query.filter_by(id=user_id, role='zoo_staff', zoo_id=zoo.id).first()
    if not staff_user:
        flash('Staff user not found.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))

    # Unassign bookings & tasks first to keep UI consistent.
    Booking.query.filter(Booking.assigned_staff_user_id == staff_user.id, Booking.zoo_id == zoo.id).update(
        {Booking.assigned_staff_user_id: None}
    )
    StaffTask.query.filter_by(assigned_to_user_id=staff_user.id, zoo_id=zoo.id).update({StaffTask.assigned_to_user_id: None})

    db.session.delete(staff_user)
    db.session.commit()
    flash('Staff user deleted.', 'success')
    return redirect(url_for('animal_farm_admin.staff_management'))


@animal_farm_admin_bp.post('/staff-management/tasks/save')
def save_staff_task():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))
    if not can_edit_feature(zoo, 'staff_management'):
        return paywall_edit_error('Staff Tasks', required_tier=2)

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
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.staff_management'))
    if not can_edit_feature(zoo, 'staff_management'):
        return paywall_edit_error('Staff Tasks', required_tier=2)
    task = StaffTask.query.filter_by(id=task_id, zoo_id=zoo.id).first()
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


@animal_farm_admin_bp.get('/trivia')
def trivia_management():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))

    questions = (
        TriviaQuestion.query.filter(
            or_(TriviaQuestion.zoo_id == zoo.id, TriviaQuestion.zoo_id.is_(None))
        )
        .order_by(TriviaQuestion.id.desc())
        .all()
    )
    animals = Animal.query.filter_by(zoo_id=zoo.id).order_by(Animal.name.asc()).all()

    return render_template(
        'animal_farm_admin/trivia_management.html',
        zoo=zoo,
        questions=questions,
        animals=animals,
    )


@animal_farm_admin_bp.post('/trivia/save')
def save_trivia_question():
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    if not can_edit_feature(zoo, 'trivia_management'):
        return paywall_edit_error('Trivia Management', required_tier=FEATURE_TIERS.get('trivia_management', 1))

    question_id = request.form.get('question_id', type=int)
    category = (request.form.get('category') or 'General Wildlife').strip()
    animal_id = request.form.get('animal_id', type=int)
    difficulty = (request.form.get('difficulty') or 'medium').strip()
    points_reward = request.form.get('points_reward', type=int) or 20
    question_text = (request.form.get('question') or '').strip()
    explanation = (request.form.get('explanation') or '').strip()
    correct_idx = request.form.get('correct_option_index', type=int) or 0

    options = [
        (request.form.get('option_0') or '').strip(),
        (request.form.get('option_1') or '').strip(),
        (request.form.get('option_2') or '').strip(),
        (request.form.get('option_3') or '').strip(),
    ]

    if not question_text or not any(options):
        flash('Please fill out the question prompt and all four options.', 'error')
        return redirect(url_for('animal_farm_admin.trivia_management'))

    if question_id:
        q = TriviaQuestion.query.filter_by(id=question_id).first()
        if not q or (q.zoo_id is not None and q.zoo_id != zoo.id):
            flash('Question not found or permission denied.', 'error')
            return redirect(url_for('animal_farm_admin.trivia_management'))
    else:
        q = TriviaQuestion(zoo_id=zoo.id)
        db.session.add(q)

    q.category = category
    q.animal_id = animal_id if animal_id else None
    q.difficulty = difficulty
    q.points_reward = points_reward
    q.question = question_text
    q.options = options
    q.correct_option_index = correct_idx
    q.explanation = explanation
    q.is_active = True

    db.session.commit()
    flash('Trivia question saved successfully.', 'success')
    return redirect(url_for('animal_farm_admin.trivia_management'))


@animal_farm_admin_bp.post('/trivia/<int:question_id>/delete')
def delete_trivia_question(question_id: int):
    zoo = _current_zoo()
    if not zoo:
        flash('No zoo assigned.', 'error')
        return redirect(url_for('animal_farm_admin.dashboard'))
    if not can_edit_feature(zoo, 'trivia_management'):
        return paywall_edit_error('Trivia Management', required_tier=FEATURE_TIERS.get('trivia_management', 1))

    q = TriviaQuestion.query.filter_by(id=question_id).first()
    if not q or (q.zoo_id is not None and q.zoo_id != zoo.id):
        flash('Question not found or permission denied.', 'error')
        return redirect(url_for('animal_farm_admin.trivia_management'))

    db.session.delete(q)
    db.session.commit()
    flash('Trivia question deleted.', 'success')
    return redirect(url_for('animal_farm_admin.trivia_management'))
