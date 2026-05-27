from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash, session
from werkzeug.utils import secure_filename

from models import (
    db,
    Zoo,
    User,
    Booking,
    Feedback,
    SubscriptionPlan,
    ZooSubscription,
    SubscriptionPayment,
    ZooAdminFeedback,
    ZooAdminFeedbackReply,
)
from services import (
    SubscriptionValidationError,
    cancel_zoo_subscription,
    change_zoo_subscription_plan,
    renew_zoo_subscription,
)
from services.auth_guard import require_role_guard

admin_bp = Blueprint("zootique_admin", __name__)


@admin_bp.before_request
def require_zootique_admin():
    result = require_role_guard(expected_role='zootique_admin', login_module='zootique_admin')
    if result is not None:
        return result


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month_start(dt: datetime) -> datetime:
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else (dt.month + 1)
    return dt.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


def _parse_date_yyyy_mm_dd(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None


def _current_user() -> User | None:
    user_id = session.get('user_id')
    if not user_id:
        return None
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        return None
    return db.session.get(User, user_id_int)

@admin_bp.get("/")
def dashboard():
    now = datetime.utcnow()

    month_start = _month_start(now)
    month_end = _next_month_start(now)
    prev_month_end = month_start
    prev_month_start = _month_start(prev_month_end - timedelta(days=1))

    total_zoos = db.session.query(db.func.count(Zoo.id)).scalar() or 0

    zoos_new_this_month = (
        db.session.query(db.func.count(Zoo.id))
        .filter(Zoo.created_at >= month_start)
        .filter(Zoo.created_at < month_end)
        .scalar()
        or 0
    )

    active_subs = db.session.query(db.func.count(ZooSubscription.id)).filter(ZooSubscription.end_date >= now).scalar() or 0
    expired_subs = db.session.query(db.func.count(ZooSubscription.id)).filter(ZooSubscription.end_date < now).scalar() or 0

    total_subs = db.session.query(db.func.count(ZooSubscription.id)).scalar() or 0
    subs_health_pct = int(round((active_subs / total_subs) * 100)) if total_subs else 0

    monthly_revenue = (
        db.session.query(db.func.coalesce(db.func.sum(SubscriptionPayment.amount), 0.0))
        .filter(SubscriptionPayment.paid_at >= month_start)
        .filter(SubscriptionPayment.paid_at < month_end)
        .scalar()
        or 0.0
    )

    prev_month_revenue = (
        db.session.query(db.func.coalesce(db.func.sum(SubscriptionPayment.amount), 0.0))
        .filter(SubscriptionPayment.paid_at >= prev_month_start)
        .filter(SubscriptionPayment.paid_at < prev_month_end)
        .scalar()
        or 0.0
    )

    revenue_change_pct = None
    if prev_month_revenue and prev_month_revenue > 0:
        revenue_change_pct = ((monthly_revenue - prev_month_revenue) / prev_month_revenue) * 100.0
    elif monthly_revenue > 0:
        revenue_change_pct = 100.0

    # Revenue goal + progress (derived from recent performance)
    # Goal = 10% above the higher of: current month revenue vs 6-month average.
    last_6_months_start = _month_start(month_start - timedelta(days=30 * 5))
    rev_last_6 = (
        db.session.query(db.func.coalesce(db.func.sum(SubscriptionPayment.amount), 0.0))
        .filter(SubscriptionPayment.paid_at >= last_6_months_start)
        .filter(SubscriptionPayment.paid_at < month_end)
        .scalar()
        or 0.0
    )
    avg_6 = (rev_last_6 / 6.0) if rev_last_6 else 0.0
    revenue_goal = max(float(monthly_revenue), float(avg_6)) * 1.10 if (monthly_revenue or avg_6) else 0.0
    revenue_goal_pct = int(round((monthly_revenue / revenue_goal) * 100)) if revenue_goal else 0
    revenue_goal_pct = max(0, min(revenue_goal_pct, 100))

    # New Zoo Registrations (last 6 months)
    reg_bars = []
    cursor = _month_start(now) - timedelta(days=5 * 30)
    cursor = _month_start(cursor)
    for _ in range(6):
        start = _month_start(cursor)
        end = _next_month_start(start)
        count = (
            db.session.query(db.func.count(Zoo.id))
            .filter(Zoo.created_at >= start)
            .filter(Zoo.created_at < end)
            .scalar()
            or 0
        )
        reg_bars.append({
            'label': start.strftime('%b'),
            'count': int(count),
        })
        cursor = end

    max_reg = max([b['count'] for b in reg_bars], default=0) or 1
    for b in reg_bars:
        b['pct'] = int((b['count'] / max_reg) * 100)

    # Zoo Performance (tier, rating, revenue contribution)
    zoo_rows = db.session.query(Zoo.id, Zoo.name).order_by(Zoo.name.asc()).all()
    zoo_ids = [zid for zid, _ in zoo_rows]

    # Active subscription tier per zoo (pick the active subscription with the latest end_date)
    active_sub_rows = (
        db.session.query(ZooSubscription)
        .filter(ZooSubscription.zoo_id.in_(zoo_ids) if zoo_ids else db.text('FALSE'))
        .filter(ZooSubscription.end_date >= now)
        .order_by(ZooSubscription.zoo_id.asc(), ZooSubscription.end_date.desc())
        .all()
    )
    tier_by_zoo: dict[int, str] = {}
    for s in active_sub_rows:
        if s.zoo_id not in tier_by_zoo:
            tier_by_zoo[s.zoo_id] = s.plan.name if s.plan else '—'

    rating_rows = (
        db.session.query(
            Feedback.zoo_id,
            db.func.avg(Feedback.rating).label('avg_rating'),
            db.func.count(Feedback.id).label('rating_count'),
        )
        .filter(Feedback.zoo_id.isnot(None))
        .group_by(Feedback.zoo_id)
        .all()
    )
    rating_by_zoo: dict[int, dict] = {
        int(r.zoo_id): {
            'avg': float(r.avg_rating) if r.avg_rating is not None else None,
            'count': int(r.rating_count or 0),
        }
        for r in rating_rows
        if r.zoo_id is not None
    }

    cur_rev_rows = (
        db.session.query(
            ZooSubscription.zoo_id,
            db.func.coalesce(db.func.sum(SubscriptionPayment.amount), 0.0).label('total'),
        )
        .join(SubscriptionPayment, SubscriptionPayment.subscription_id == ZooSubscription.id)
        .filter(SubscriptionPayment.paid_at >= month_start)
        .filter(SubscriptionPayment.paid_at < month_end)
        .group_by(ZooSubscription.zoo_id)
        .all()
    )
    prev_rev_rows = (
        db.session.query(
            ZooSubscription.zoo_id,
            db.func.coalesce(db.func.sum(SubscriptionPayment.amount), 0.0).label('total'),
        )
        .join(SubscriptionPayment, SubscriptionPayment.subscription_id == ZooSubscription.id)
        .filter(SubscriptionPayment.paid_at >= prev_month_start)
        .filter(SubscriptionPayment.paid_at < prev_month_end)
        .group_by(ZooSubscription.zoo_id)
        .all()
    )

    cur_rev_by_zoo = {int(zid): float(total or 0.0) for zid, total in cur_rev_rows}
    prev_rev_by_zoo = {int(zid): float(total or 0.0) for zid, total in prev_rev_rows}

    zoo_performance = []
    for zoo_id, zoo_name in zoo_rows:
        cur_rev = float(cur_rev_by_zoo.get(int(zoo_id), 0.0))
        prev_rev = float(prev_rev_by_zoo.get(int(zoo_id), 0.0))

        rev_delta_pct = None
        if prev_rev > 0:
            rev_delta_pct = ((cur_rev - prev_rev) / prev_rev) * 100.0
        elif cur_rev > 0:
            rev_delta_pct = 100.0

        rating_info = rating_by_zoo.get(int(zoo_id), {'avg': None, 'count': 0})

        zoo_performance.append(
            {
                'zoo_id': int(zoo_id),
                'zoo_name': zoo_name,
                'tier': tier_by_zoo.get(int(zoo_id), '—'),
                'avg_rating': rating_info.get('avg'),
                'rating_count': rating_info.get('count', 0),
                'revenue': cur_rev,
                'revenue_delta_pct': rev_delta_pct,
            }
        )

    zoo_performance.sort(key=lambda r: (r['revenue'], (r['avg_rating'] or 0.0)), reverse=True)
    zoo_performance = zoo_performance[:5]

    stats = {
        'total_zoos': int(total_zoos),
        'zoos_new_this_month': int(zoos_new_this_month),
        'active_subscriptions': int(active_subs),
        'expired_subscriptions': int(expired_subs),
        'subs_health_pct': int(subs_health_pct),
        'monthly_revenue': float(monthly_revenue),
        'revenue_change_pct': float(revenue_change_pct) if revenue_change_pct is not None else None,
        'revenue_goal': float(revenue_goal),
        'revenue_goal_pct': int(revenue_goal_pct),
    }

    return render_template(
        "zootique_admin/dashboard.html",
        stats=stats,
        reg_bars=reg_bars,
        zoo_performance=zoo_performance,
    )

@admin_bp.get("/subscriptions")
def manage_subscriptions():
    now = datetime.utcnow()
    edit_plan_id = request.args.get('edit_plan')
    edit_plan = db.session.get(SubscriptionPlan, int(edit_plan_id)) if (edit_plan_id and edit_plan_id.isdigit()) else None

    subscriptions = (
        db.session.query(ZooSubscription)
        .join(Zoo)
        .join(SubscriptionPlan)
        .order_by(Zoo.name.asc())
        .all()
    )

    sub_rows = []
    active_count = 0
    expired_count = 0
    pending_renewals = 0
    mrr_total = 0.0
    active_by_plan: dict[int, int] = {}
    for s in subscriptions:
        is_active = s.end_date >= now
        if is_active:
            active_count += 1
        else:
            expired_count += 1

        # Pending renewals: active subscriptions ending within the next 30 days.
        if is_active and s.end_date < (now + timedelta(days=30)):
            pending_renewals += 1

        # Monthly recurring revenue: normalize by duration months.
        try:
            duration_months = int(getattr(s.plan, "duration_months", 1) or 1)
        except Exception:
            duration_months = 1
        duration_months = max(duration_months, 1)
        try:
            plan_price = float(getattr(s.plan, "price", 0) or 0)
        except Exception:
            plan_price = 0.0
        if is_active:
            mrr_total += plan_price / duration_months
            if s.plan_id:
                active_by_plan[int(s.plan_id)] = active_by_plan.get(int(s.plan_id), 0) + 1

        latest_payment = (
            SubscriptionPayment.query
            .filter_by(subscription_id=s.id)
            .order_by(SubscriptionPayment.paid_at.desc())
            .first()
        )
        sub_rows.append({
            'subscription_id': s.id,
            'zoo_id': s.zoo_id,
            'zoo_name': s.zoo.name,
            'plan_id': s.plan.id,
            'plan_name': s.plan.name,
            'status': 'Active' if is_active else 'Expired',
            'start_date': s.start_date.date().isoformat(),
            'end_date': s.end_date.date().isoformat(),
            'latest_payment_date': latest_payment.paid_at.date().isoformat() if latest_payment else '—',
            'latest_payment_amount': float(latest_payment.amount) if latest_payment else 0,
        })

    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.price.asc()).all()

    total_subs = len(subscriptions)
    churn_rate = (expired_count / total_subs) * 100 if total_subs else 0.0

    popular_plan_id = None
    if active_by_plan:
        popular_plan_id = max(active_by_plan.items(), key=lambda item: item[1])[0]

    plan_tiers = []
    for plan in plans:
        features = (plan.features or "").strip()
        short_desc = ""
        if features:
            short_desc = (features.splitlines()[0] or "").strip()
        if not short_desc:
            short_desc = "Subscription features"

        duration = (getattr(plan, "duration", "monthly") or "monthly").strip().lower()
        duration_label = "/mo" if duration == "monthly" else "/yr"

        plan_tiers.append({
            "id": plan.id,
            "name": plan.name,
            "description": short_desc,
            "price": float(plan.price or 0),
            "duration_label": duration_label,
            "is_popular": bool(popular_plan_id and plan.id == popular_plan_id),
        })

    return render_template(
        "zootique_admin/subscriptions.html",
        subscriptions=sub_rows,
        plans=plans,
        sub_stats={
            "active": int(active_count),
            "mrr": float(mrr_total),
            "pending_renewals": int(pending_renewals),
            "churn_rate": float(churn_rate),
            "expired": int(expired_count),
            "total": int(total_subs),
        },
        plan_tiers=plan_tiers,
        edit_plan=edit_plan,
    )


@admin_bp.post('/subscriptions/<int:subscription_id>/renew')
def renew_subscription(subscription_id: int):
    subscription = db.session.get(ZooSubscription, subscription_id)
    if not subscription:
        flash('Subscription not found.', 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))

    months_raw = (request.form.get('months') or '').strip()
    amount_raw = (request.form.get('amount') or '').strip()

    months = None
    if months_raw:
        if not months_raw.isdigit() or int(months_raw) < 1:
            flash('Months must be a positive number.', 'error')
            return redirect(url_for('zootique_admin.manage_subscriptions'))
        months = int(months_raw)

    amount = None
    if amount_raw:
        try:
            amount = float(amount_raw)
        except ValueError:
            flash('Amount must be numeric.', 'error')
            return redirect(url_for('zootique_admin.manage_subscriptions'))

    try:
        payment = renew_zoo_subscription(subscription=subscription, months=months, amount=amount)
    except SubscriptionValidationError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))

    flash(
        f"Subscription renewed for {subscription.zoo.name}. Payment ref: {payment.reference}",
        'success',
    )
    return redirect(url_for('zootique_admin.manage_subscriptions'))


@admin_bp.post('/subscriptions/<int:subscription_id>/cancel')
def cancel_subscription(subscription_id: int):
    subscription = db.session.get(ZooSubscription, subscription_id)
    if not subscription:
        flash('Subscription not found.', 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))

    try:
        cancel_zoo_subscription(subscription=subscription)
    except SubscriptionValidationError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))

    flash(f"Subscription for {subscription.zoo.name} cancelled.", 'success')
    return redirect(url_for('zootique_admin.manage_subscriptions'))


@admin_bp.post('/subscriptions/<int:subscription_id>/change-plan')
def change_subscription_plan(subscription_id: int):
    subscription = db.session.get(ZooSubscription, subscription_id)
    if not subscription:
        flash('Subscription not found.', 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))

    plan_id_raw = (request.form.get('plan_id') or '').strip()
    if not plan_id_raw.isdigit():
        flash('A valid plan must be selected.', 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))

    plan = db.session.get(SubscriptionPlan, int(plan_id_raw))
    if not plan:
        flash('Selected plan not found.', 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))

    bill_now = (request.form.get('bill_now') or '1').strip() != '0'

    try:
        _, payment = change_zoo_subscription_plan(
            subscription=subscription,
            new_plan=plan,
            bill_now=bill_now,
        )
    except SubscriptionValidationError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))

    if payment:
        flash(
            f"Plan changed for {subscription.zoo.name}. Payment ref: {payment.reference}",
            'success',
        )
    else:
        flash(f"Plan changed for {subscription.zoo.name}.", 'success')
    return redirect(url_for('zootique_admin.manage_subscriptions'))


@admin_bp.post('/subscriptions/plans/save')
def save_subscription_plan():
    plan_id = request.form.get('plan_id')
    name = (request.form.get('name') or '').strip()
    price = request.form.get('price')
    duration = (request.form.get('duration') or '').strip().lower()
    features = (request.form.get('features') or '').strip()

    if not name:
        flash('Plan name is required.', 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))
    try:
        price_value = float(price)
    except (TypeError, ValueError):
        flash('Price must be a number.', 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))
    if duration not in ('monthly', 'yearly'):
        flash('Duration must be monthly or yearly.', 'error')
        return redirect(url_for('zootique_admin.manage_subscriptions'))

    duration_months = 1 if duration == 'monthly' else 12

    if plan_id and plan_id.isdigit():
        plan = db.session.get(SubscriptionPlan, int(plan_id))
        if not plan:
            flash('Plan not found.', 'error')
            return redirect(url_for('zootique_admin.manage_subscriptions'))
    else:
        plan = SubscriptionPlan()
        db.session.add(plan)

    plan.name = name
    plan.price = price_value
    plan.duration = duration
    plan.duration_months = duration_months
    plan.features = features

    try:
        db.session.commit()
        flash('Subscription plan saved.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to save plan: {e}', 'error')

    return redirect(url_for('zootique_admin.manage_subscriptions'))

@admin_bp.get("/zoo-feedback")
def view_feedback():
    zoo_id = request.args.get('zoo_id')
    rating = request.args.get('rating')
    start_date = _parse_date_yyyy_mm_dd(request.args.get('start_date'))
    end_date = _parse_date_yyyy_mm_dd(request.args.get('end_date'))

    query = db.session.query(ZooAdminFeedback).join(Zoo)
    if zoo_id and zoo_id.isdigit():
        query = query.filter(ZooAdminFeedback.zoo_id == int(zoo_id))
    if rating and rating.isdigit():
        query = query.filter(ZooAdminFeedback.rating == int(rating))
    if start_date:
        query = query.filter(ZooAdminFeedback.created_at >= start_date)
    if end_date:
        query = query.filter(ZooAdminFeedback.created_at < (end_date + timedelta(days=1)))

    feedbacks = query.order_by(ZooAdminFeedback.created_at.desc()).all()
    zoos = Zoo.query.order_by(Zoo.name.asc()).all()

    # Preload the latest reply (if any)
    rows = []
    pending_replies = 0
    rating_sum = 0
    for f in feedbacks:
        latest_reply = None
        if f.replies:
            latest_reply = sorted(f.replies, key=lambda r: r.created_at)[-1]
        if latest_reply is None:
            pending_replies += 1
        try:
            rating_sum += int(f.rating or 0)
        except Exception:
            rating_sum += 0
        rows.append({
            'id': f.id,
            'zoo_name': f.zoo.name,
            'category': f.category,
            'rating': f.rating,
            'comment': f.comment,
            'created_at': f.created_at.strftime('%Y-%m-%d'),
            'latest_reply': latest_reply.reply_text if latest_reply else None,
            'latest_reply_date': latest_reply.created_at.strftime('%Y-%m-%d') if latest_reply else None,
        })

    total_feedback = len(rows)
    avg_rating = (rating_sum / total_feedback) if total_feedback else 0.0

    return render_template(
        "zootique_admin/feedback.html",
        feedbacks=rows,
        zoos=zoos,
        feedback_stats={
            'total': int(total_feedback),
            'avg_rating': float(avg_rating),
            'pending_replies': int(pending_replies),
        },
        filters={
            'zoo_id': zoo_id or '',
            'rating': rating or '',
            'start_date': request.args.get('start_date') or '',
            'end_date': request.args.get('end_date') or '',
        },
    )


@admin_bp.get('/feedback')
def legacy_feedback_redirect():
    return redirect(url_for('zootique_admin.view_feedback'), code=301)


@admin_bp.post('/zoo-feedback/<int:feedback_id>/reply')
def reply_feedback(feedback_id: int):
    reply_text = (request.form.get('reply_text') or '').strip()
    if not reply_text:
        flash('Reply text is required.', 'error')
        return redirect(url_for('zootique_admin.view_feedback'))

    feedback = db.session.get(ZooAdminFeedback, feedback_id)
    if not feedback:
        flash('Feedback not found.', 'error')
        return redirect(url_for('zootique_admin.view_feedback'))

    admin_user = _current_user()
    reply = ZooAdminFeedbackReply(
        feedback_id=feedback_id,
        admin_user_id=admin_user.id if admin_user else None,
        reply_text=reply_text,
    )
    db.session.add(reply)
    db.session.commit()
    flash('Reply sent.', 'success')
    return redirect(url_for('zootique_admin.view_feedback'))


@admin_bp.post('/zoo-feedback/<int:feedback_id>/delete')
def delete_feedback(feedback_id: int):
    feedback = db.session.get(ZooAdminFeedback, feedback_id)
    if not feedback:
        flash('Feedback not found.', 'error')
        return redirect(url_for('zootique_admin.view_feedback'))

    ZooAdminFeedbackReply.query.filter_by(feedback_id=feedback.id).delete(synchronize_session=False)
    db.session.delete(feedback)
    db.session.commit()
    flash('Feedback deleted.', 'success')
    return redirect(url_for('zootique_admin.view_feedback'))

@admin_bp.get("/reports")
def view_reports():
    now = datetime.utcnow()

    total_revenue = db.session.query(db.func.coalesce(db.func.sum(SubscriptionPayment.amount), 0.0)).scalar() or 0.0
    active_subs = db.session.query(db.func.count(ZooSubscription.id)).filter(ZooSubscription.end_date >= now).scalar() or 0
    expired_subs = db.session.query(db.func.count(ZooSubscription.id)).filter(ZooSubscription.end_date < now).scalar() or 0

    plan_distribution = (
        db.session.query(SubscriptionPlan.name, db.func.count(ZooSubscription.id))
        .join(ZooSubscription, ZooSubscription.plan_id == SubscriptionPlan.id)
        .group_by(SubscriptionPlan.name)
        .order_by(db.desc(db.func.count(ZooSubscription.id)))
        .all()
    )
    plan_distribution = [{'plan': n, 'count': int(c)} for n, c in plan_distribution]

    # Zoo performance (bookings & visitors)
    zoo_perf = (
        db.session.query(
            Zoo.name,
            db.func.count(Booking.id).label('bookings'),
            db.func.coalesce(db.func.sum(Booking.guests), 0).label('visitors'),
        )
        .join(Booking, Booking.zoo_id == Zoo.id)
        .group_by(Zoo.name)
        .order_by(db.desc('bookings'))
        .all()
    )

    most_active = [{'zoo': r[0], 'bookings': int(r[1] or 0), 'visitors': int(r[2] or 0)} for r in zoo_perf[:5]]
    least_active = [{'zoo': r[0], 'bookings': int(r[1] or 0), 'visitors': int(r[2] or 0)} for r in zoo_perf[-5:]]

    # Financial (monthly income + recent payments)
    month_income = (
        db.session.query(
            db.func.to_char(SubscriptionPayment.paid_at, 'YYYY-MM').label('month'),
            db.func.coalesce(db.func.sum(SubscriptionPayment.amount), 0.0).label('total'),
        )
        .group_by('month')
        .order_by('month')
        .all()
    )
    month_income = [{'month': m, 'total': float(t)} for m, t in month_income][-12:]

    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    year_end = year_start.replace(year=year_start.year + 1)
    yearly_income = (
        db.session.query(db.func.coalesce(db.func.sum(SubscriptionPayment.amount), 0.0))
        .filter(SubscriptionPayment.paid_at >= year_start)
        .filter(SubscriptionPayment.paid_at < year_end)
        .scalar()
        or 0.0
    )

    recent_payments = (
        db.session.query(SubscriptionPayment)
        .join(ZooSubscription)
        .join(Zoo)
        .order_by(SubscriptionPayment.paid_at.desc())
        .limit(20)
        .all()
    )
    payment_rows = []
    for p in recent_payments:
        payment_rows.append({
            'paid_at': p.paid_at.strftime('%Y-%m-%d'),
            'zoo_name': p.subscription.zoo.name,
            'plan_name': p.subscription.plan.name,
            'amount': float(p.amount),
            'reference': p.reference or '—',
            'status': p.status,
        })

    return render_template(
        "zootique_admin/reports.html",
        subs_report={
            'total_revenue': float(total_revenue),
            'active': int(active_subs),
            'expired': int(expired_subs),
            'plan_distribution': plan_distribution,
        },
        perf_report={
            'most_active': most_active,
            'least_active': least_active,
        },
        financial_report={
            'month_income': month_income,
            'yearly_income': float(yearly_income),
            'year': int(year_start.year),
            'payments': payment_rows,
        },
    )

@admin_bp.get("/user-management")
def user_management():
    edit_user_id = request.args.get('edit_user')
    edit_user = db.session.get(User, int(edit_user_id)) if (edit_user_id and edit_user_id.isdigit()) else None
    if edit_user and edit_user.role != 'zoo_admin':
        flash('Only Zoo Admin users can be edited here.', 'error')
        edit_user = None

    users = (
        User.query
        .filter(User.role == 'zoo_admin')
        .order_by(User.full_name.asc(), User.email.asc())
        .all()
    )
    zoos = Zoo.query.order_by(Zoo.name.asc()).all()

    user_rows = []
    for u in users:
        user_rows.append({
            'id': u.id,
            'full_name': u.full_name or '—',
            'email': u.email,
            'role': u.role,
            'assigned_zoo': u.zoo.name if u.zoo else '—',
            'status': (u.status or 'active').title(),
        })

    return render_template(
        "zootique_admin/user_management.html",
        users=user_rows,
        zoos=zoos,
        edit_user=edit_user,
    )


@admin_bp.post('/user-management/users/save')
def save_user():
    user_id = request.form.get('user_id')
    full_name = (request.form.get('full_name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    zoo_id = request.form.get('zoo_id')
    status = (request.form.get('status') or 'active').strip().lower()
    password = request.form.get('password')

    def _back_to_form(edit_id: int | None = None):
        if edit_id is not None:
            return redirect(url_for('zootique_admin.user_management', edit_user=edit_id) + '#sa_user_form')
        return redirect(url_for('zootique_admin.user_management') + '#sa_user_form')

    if not email:
        flash('Email is required.', 'error')
        return _back_to_form(int(user_id) if (user_id and user_id.isdigit()) else None)
    if status not in ('active', 'suspended'):
        status = 'active'

    is_new_user = not (user_id and user_id.isdigit())

    if user_id and user_id.isdigit():
        user = db.session.get(User, int(user_id))
        if not user or user.role != 'zoo_admin':
            flash('User not found.', 'error')
            return redirect(url_for('zootique_admin.user_management'))
    else:
        user = User(role='zoo_admin')
        db.session.add(user)

    # uniqueness check when changing/creating email
    existing = User.query.filter(User.email == email, User.id != getattr(user, 'id', None)).first()
    if existing:
        flash('Email already exists.', 'error')
        return _back_to_form(user.id if getattr(user, 'id', None) else None)

    if not full_name:
        flash('Full name is required.', 'error')
        return _back_to_form(user.id if getattr(user, 'id', None) else None)

    generated_password = None
    if is_new_user and not password:
        generated_password = secrets.token_urlsafe(9)
        password = generated_password

    if password and len(password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return _back_to_form(user.id if getattr(user, 'id', None) else None)

    user.full_name = full_name
    user.email = email
    user.status = status
    user.role = 'zoo_admin'
    user.zoo_id = int(zoo_id) if (zoo_id and zoo_id.isdigit()) else None
    if password:
        user.set_password(password)

    db.session.commit()
    if generated_password:
        flash(f'User saved. Temporary password for {user.email}: {generated_password}', 'success')
    else:
        flash('User saved.', 'success')
    return redirect(url_for('zootique_admin.user_management'))


@admin_bp.post('/user-management/users/<int:user_id>/toggle-status')
def toggle_user_status(user_id: int):
    user = db.session.get(User, user_id)
    if not user or user.role != 'zoo_admin':
        flash('User not found.', 'error')
        return redirect(url_for('zootique_admin.user_management'))

    user.status = 'suspended' if (user.status == 'active') else 'active'
    db.session.commit()
    flash('User status updated.', 'success')
    return redirect(url_for('zootique_admin.user_management'))


@admin_bp.post('/user-management/users/<int:user_id>/reset-password')
def reset_user_password(user_id: int):
    user = db.session.get(User, user_id)
    if not user or user.role != 'zoo_admin':
        flash('User not found.', 'error')
        return redirect(url_for('zootique_admin.user_management'))

    temp_password = secrets.token_urlsafe(9)
    user.set_password(temp_password)
    db.session.commit()
    flash(f"Temporary password for {user.email}: {temp_password}", 'success')
    return redirect(url_for('zootique_admin.user_management'))


@admin_bp.post('/user-management/users/<int:user_id>/delete')
def delete_user(user_id: int):
    user = db.session.get(User, user_id)
    if not user or user.role != 'zoo_admin':
        flash('User not found.', 'error')
        return redirect(url_for('zootique_admin.user_management'))

    db.session.delete(user)
    db.session.commit()
    flash('User deleted.', 'success')
    return redirect(url_for('zootique_admin.user_management'))

@admin_bp.get("/users")
def user_management_legacy_redirect():
    return redirect(url_for('zootique_admin.user_management'), code=301)


@admin_bp.get('/settings')
def settings():
    user = _current_user()
    if not user:
        return redirect(url_for('auth.login', module_name='zootique_admin'))

    return render_template('zootique_admin/settings.html', user=user)


@admin_bp.post('/settings/profile')
def update_profile():
    user = _current_user()
    if not user:
        return redirect(url_for('auth.login', module_name='zootique_admin'))

    full_name = (request.form.get('full_name') or '').strip()
    username = (request.form.get('username') or '').strip() or None
    email = (request.form.get('email') or '').strip().lower()

    if not full_name or not email:
        flash('Full name and email are required.', 'error')
        return redirect(url_for('zootique_admin.settings'))

    if email and email != user.email:
        if User.query.filter(User.email == email, User.id != user.id).first():
            flash('Email already exists.', 'error')
            return redirect(url_for('zootique_admin.settings'))
        user.email = email

    if username and username != user.username:
        if User.query.filter(User.username == username, User.id != user.id).first():
            flash('Username already exists.', 'error')
            return redirect(url_for('zootique_admin.settings'))
        user.username = username

    user.full_name = full_name

    file = request.files.get('profile_picture')
    if file and file.filename:
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
            flash('Unsupported image type. Use png/jpg/webp/gif.', 'error')
            return redirect(url_for('zootique_admin.settings'))

        folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'profile_pictures')
        os.makedirs(folder, exist_ok=True)
        stored_name = f"admin_{user.id}_{secrets.token_hex(6)}{ext}"
        file.save(os.path.join(folder, stored_name))
        user.profile_image = f"profile_pictures/{stored_name}"

    db.session.commit()
    session['full_name'] = user.full_name
    flash('Profile updated.', 'success')
    return redirect(url_for('zootique_admin.settings'))


@admin_bp.post('/settings/security')
def update_security():
    user = _current_user()
    if not user:
        return redirect(url_for('auth.login', module_name='zootique_admin'))

    new_username = (request.form.get('new_username') or '').strip()
    current_password = request.form.get('current_password') or ''
    new_password = request.form.get('new_password') or ''
    confirm_password = request.form.get('confirm_password') or ''

    if not user.check_password(current_password):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('zootique_admin.settings'))

    if new_username and new_username != user.username:
        if User.query.filter(User.username == new_username, User.id != user.id).first():
            flash('Username already exists.', 'error')
            return redirect(url_for('zootique_admin.settings'))
        user.username = new_username

    if new_password:
        if new_password != confirm_password:
            flash('New password and confirmation do not match.', 'error')
            return redirect(url_for('zootique_admin.settings'))
        if len(new_password) < 8:
            flash('New password must be at least 8 characters.', 'error')
            return redirect(url_for('zootique_admin.settings'))
        user.set_password(new_password)

    db.session.commit()
    flash('Security settings updated.', 'success')
    return redirect(url_for('zootique_admin.settings'))
