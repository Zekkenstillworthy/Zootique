from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from models import SubscriptionPayment, SubscriptionPlan, ZooSubscription, db


class SubscriptionServiceError(Exception):
    pass


class SubscriptionValidationError(SubscriptionServiceError):
    pass


def _months_to_duration(months: int) -> timedelta:
    return timedelta(days=30 * months)


def _new_subscription_reference(prefix: str, subscription_id: int) -> str:
    return f"{prefix}-{subscription_id}-{secrets.token_hex(4).upper()}"


def renew_zoo_subscription(*, subscription: ZooSubscription, months: int | None = None, amount: float | None = None):
    if not subscription:
        raise SubscriptionValidationError("Subscription not found.")

    plan = subscription.plan
    if not plan or not plan.is_active:
        raise SubscriptionValidationError("Subscription plan is not active.")

    cycle_months = months or int(plan.duration_months or 1)
    if cycle_months < 1:
        raise SubscriptionValidationError("Renewal duration must be at least 1 month.")

    now = datetime.utcnow()
    period_start = subscription.end_date if subscription.end_date and subscription.end_date > now else now
    period_end = period_start + _months_to_duration(cycle_months)

    normalized_amount = float(amount if amount is not None else plan.price * (cycle_months / max(plan.duration_months, 1)))
    if normalized_amount <= 0:
        raise SubscriptionValidationError("Renewal amount must be greater than zero.")

    payment = SubscriptionPayment(
        subscription_id=subscription.id,
        amount=normalized_amount,
        paid_at=now,
        period_start=period_start,
        period_end=period_end,
        reference=_new_subscription_reference("RENEW", subscription.id),
        status="paid",
    )

    subscription.end_date = period_end
    subscription.status = "active"

    db.session.add(payment)
    db.session.commit()
    return payment


def cancel_zoo_subscription(*, subscription: ZooSubscription):
    if not subscription:
        raise SubscriptionValidationError("Subscription not found.")

    now = datetime.utcnow()
    subscription.end_date = now
    subscription.status = "expired"
    db.session.commit()
    return subscription


def change_zoo_subscription_plan(*, subscription: ZooSubscription, new_plan: SubscriptionPlan, bill_now: bool = True):
    if not subscription:
        raise SubscriptionValidationError("Subscription not found.")
    if not new_plan or not new_plan.is_active:
        raise SubscriptionValidationError("Selected plan is not active.")

    now = datetime.utcnow()
    new_end = now + _months_to_duration(max(int(new_plan.duration_months or 1), 1))

    subscription.plan_id = new_plan.id
    subscription.start_date = now
    subscription.end_date = new_end
    subscription.status = "active"

    payment = None
    if bill_now:
        payment = SubscriptionPayment(
            subscription_id=subscription.id,
            amount=float(new_plan.price),
            paid_at=now,
            period_start=now,
            period_end=new_end,
            reference=_new_subscription_reference("PLAN", subscription.id),
            status="paid",
        )
        db.session.add(payment)

    db.session.commit()
    return subscription, payment
