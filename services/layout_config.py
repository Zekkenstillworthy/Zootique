from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from models import Booking, Feedback, StaffTask, Zoo, ZooLayoutConfig, ZooSubscription, db


WIDGET_CATALOG = [
    {
        'id': 'revenue_summary',
        'label': 'Revenue Summary',
        'description': 'This month revenue, change, and target progress',
        'icon': 'fa-solid fa-chart-line',
    },
    {
        'id': 'membership_stats',
        'label': 'Membership Stats',
        'description': 'Plan status, days remaining, and operational counts',
        'icon': 'fa-solid fa-id-card',
    },
    {
        'id': 'recent_feedback',
        'label': 'Recent Feedback',
        'description': 'Latest visitor feedback for this zoo',
        'icon': 'fa-regular fa-message',
    },
    {
        'id': 'upcoming_renewals',
        'label': 'Upcoming Renewals',
        'description': 'Renewal status and upcoming billing date',
        'icon': 'fa-solid fa-calendar-days',
    },
]

DEFAULT_LAYOUT_STYLE = 'grid'
DEFAULT_THEME_VARIANT = 'light'
VALID_LAYOUT_STYLES = {'grid', 'list', 'compact'}
VALID_THEME_VARIANTS = {'light', 'zoo_accent'}
DEFAULT_WIDGET_ORDER = [item['id'] for item in WIDGET_CATALOG]
DEFAULT_WIDGET_VISIBILITY = {item['id']: True for item in WIDGET_CATALOG}


def _coerce_bool_map(raw_value: Any) -> dict[str, bool]:
    visibility = dict(DEFAULT_WIDGET_VISIBILITY)
    if isinstance(raw_value, dict):
        for widget_id in DEFAULT_WIDGET_ORDER:
            if widget_id in raw_value:
                visibility[widget_id] = bool(raw_value.get(widget_id))
    return visibility


def _coerce_widget_order(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        return list(DEFAULT_WIDGET_ORDER)

    order: list[str] = []
    for widget_id in raw_value:
        if widget_id in DEFAULT_WIDGET_VISIBILITY and widget_id not in order:
            order.append(widget_id)

    for widget_id in DEFAULT_WIDGET_ORDER:
        if widget_id not in order:
            order.append(widget_id)

    return order


def normalize_layout_config(raw_config: ZooLayoutConfig | dict[str, Any] | None, zoo_id: int | None = None) -> dict[str, Any]:
    if raw_config is None:
        raw_visibility: Any = {}
        raw_order: Any = []
        layout_style = DEFAULT_LAYOUT_STYLE
        theme_variant = DEFAULT_THEME_VARIANT
        config_zoo_id = zoo_id
    elif isinstance(raw_config, dict):
        raw_visibility = raw_config.get('widget_visibility')
        raw_order = raw_config.get('widget_order')
        layout_style = raw_config.get('layout_style') or DEFAULT_LAYOUT_STYLE
        theme_variant = raw_config.get('theme_variant') or DEFAULT_THEME_VARIANT
        config_zoo_id = raw_config.get('zoo_id', zoo_id)
    else:
        raw_visibility = raw_config.widget_visibility
        raw_order = raw_config.widget_order
        layout_style = raw_config.layout_style or DEFAULT_LAYOUT_STYLE
        theme_variant = raw_config.theme_variant or DEFAULT_THEME_VARIANT
        config_zoo_id = raw_config.zoo_id

    layout_style = layout_style if layout_style in VALID_LAYOUT_STYLES else DEFAULT_LAYOUT_STYLE
    theme_variant = theme_variant if theme_variant in VALID_THEME_VARIANTS else DEFAULT_THEME_VARIANT

    return {
        'zoo_id': config_zoo_id,
        'widget_visibility': _coerce_bool_map(raw_visibility),
        'widget_order': _coerce_widget_order(raw_order),
        'layout_style': layout_style,
        'theme_variant': theme_variant,
    }


def get_layout_config_for_zoo(zoo_id: int | None) -> dict[str, Any]:
    if zoo_id is None:
        return normalize_layout_config(None)

    config = ZooLayoutConfig.query.filter_by(zoo_id=zoo_id).first()
    return normalize_layout_config(config, zoo_id=zoo_id)


def save_layout_config(
    zoo_id: int,
    widget_visibility: dict[str, bool],
    widget_order: list[str],
    layout_style: str,
    theme_variant: str,
) -> ZooLayoutConfig:
    config = ZooLayoutConfig.query.filter_by(zoo_id=zoo_id).first()
    if config is None:
        config = ZooLayoutConfig(zoo_id=zoo_id)
        db.session.add(config)

    config.widget_visibility = _coerce_bool_map(widget_visibility)
    config.widget_order = _coerce_widget_order(widget_order)
    config.layout_style = layout_style if layout_style in VALID_LAYOUT_STYLES else DEFAULT_LAYOUT_STYLE
    config.theme_variant = theme_variant if theme_variant in VALID_THEME_VARIANTS else DEFAULT_THEME_VARIANT
    return config


def build_zoo_dashboard_widget_map(zoo: Zoo | None, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    now = now or datetime.utcnow()
    if zoo is None:
        return {}

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = month_start.replace(
        year=month_start.year + (1 if month_start.month == 12 else 0),
        month=1 if month_start.month == 12 else month_start.month + 1,
    )
    prev_month_end = month_start
    prev_month_start = (prev_month_end - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    bookings = Booking.query.filter(Booking.zoo_id == zoo.id).all()
    monthly_bookings = [b for b in bookings if (b.date or '').startswith(now.strftime('%Y-%m'))]
    monthly_revenue = sum(float(b.amount or 0) for b in monthly_bookings)
    prev_month_bookings = [b for b in bookings if (b.date or '').startswith(prev_month_start.strftime('%Y-%m'))]
    prev_month_revenue = sum(float(b.amount or 0) for b in prev_month_bookings)
    revenue_change_pct = None
    if prev_month_revenue > 0:
        revenue_change_pct = ((monthly_revenue - prev_month_revenue) / prev_month_revenue) * 100.0
    elif monthly_revenue > 0:
        revenue_change_pct = 100.0

    month_bookings_count = len(monthly_bookings)
    month_open_tasks = StaffTask.query.filter_by(zoo_id=zoo.id).filter(StaffTask.status != 'done').count()
    active_subscription = (
        ZooSubscription.query.filter_by(zoo_id=zoo.id)
        .order_by(ZooSubscription.end_date.desc())
        .first()
    )
    feedback_rows = (
        Feedback.query.filter_by(zoo_id=zoo.id)
        .order_by(Feedback.created_at.desc())
        .limit(5)
        .all()
    )

    revenue_goal = max(monthly_revenue, prev_month_revenue) * 1.10 if (monthly_revenue or prev_month_revenue) else 0.0
    revenue_goal_pct = int(round((monthly_revenue / revenue_goal) * 100)) if revenue_goal else 0
    revenue_goal_pct = max(0, min(revenue_goal_pct, 100))

    days_remaining = None
    renewal_status = 'No active subscription'
    if active_subscription:
        days_remaining = (active_subscription.end_date - now).days
        renewal_status = 'Active' if active_subscription.end_date >= now else 'Expired'

    return {
        'revenue_summary': {
            'id': 'revenue_summary',
            'label': 'Revenue Summary',
            'icon': 'fa-solid fa-chart-line',
            'monthly_revenue': float(monthly_revenue),
            'revenue_change_pct': float(revenue_change_pct) if revenue_change_pct is not None else None,
            'revenue_goal': float(revenue_goal),
            'revenue_goal_pct': revenue_goal_pct,
            'booking_count': int(month_bookings_count),
            'prev_month_revenue': float(prev_month_revenue),
            'month_start': month_start,
            'next_month': next_month,
        },
        'membership_stats': {
            'id': 'membership_stats',
            'label': 'Membership Stats',
            'icon': 'fa-solid fa-id-card',
            'open_tasks': int(month_open_tasks),
            'subscription': active_subscription,
            'status': renewal_status,
            'days_remaining': days_remaining,
        },
        'recent_feedback': {
            'id': 'recent_feedback',
            'label': 'Recent Feedback',
            'icon': 'fa-regular fa-message',
            'items': [
                {
                    'visitor_name': row.visitor_name,
                    'rating': int(row.rating or 0),
                    'comment': row.comment or '',
                    'date': row.created_at.strftime('%Y-%m-%d') if row.created_at else (row.date or '—'),
                }
                for row in feedback_rows
            ],
        },
        'upcoming_renewals': {
            'id': 'upcoming_renewals',
            'label': 'Upcoming Renewals',
            'icon': 'fa-solid fa-calendar-days',
            'subscription': active_subscription,
            'days_remaining': days_remaining,
            'status': renewal_status,
            'next_due_date': active_subscription.end_date.strftime('%Y-%m-%d') if active_subscription else None,
        },
    }


def order_dashboard_widgets(widget_map: dict[str, dict[str, Any]], layout_config: dict[str, Any]) -> list[dict[str, Any]]:
    ordered_widgets: list[dict[str, Any]] = []
    visibility = layout_config.get('widget_visibility', {}) if isinstance(layout_config, dict) else {}
    order = layout_config.get('widget_order', []) if isinstance(layout_config, dict) else []

    for widget_id in order:
        widget = widget_map.get(widget_id)
        if not widget:
            continue
        widget_copy = dict(widget)
        widget_copy['visible'] = bool(visibility.get(widget_id, True))
        ordered_widgets.append(widget_copy)

    for widget_id, widget in widget_map.items():
        if widget_id in order:
            continue
        widget_copy = dict(widget)
        widget_copy['visible'] = bool(visibility.get(widget_id, True))
        ordered_widgets.append(widget_copy)

    return ordered_widgets