"""subscription_guard.py — Paywall enforcement helpers for Zoo Admin routes.

Usage in routes:
    from services.subscription_guard import get_zoo_subscription_tier, paywall_redirect

    @animal_farm_admin_bp.route('/animals')
    def animals_management():
        zoo = _current_zoo()
        if tier := get_zoo_subscription_tier(zoo):
            if tier < 1:
                return paywall_redirect(required_tier=1)
        ...
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from flask import flash, redirect, url_for

if TYPE_CHECKING:
    from models import Zoo

# Maps tier_level int → human-readable tier name
TIER_NAMES = {
    0: "Free",
    1: "Standard",
    2: "Pro",
}

# Feature → minimum tier_level required
FEATURE_TIERS: dict[str, int] = {
    # Standard (tier 1)
    "animals": 1,
    "services": 1,
    "events": 1,
    "promotions": 1,
    "park_rules": 1,
    "revenue": 1,
    "visitor_feedback_write": 1,
    # Pro (tier 2)
    "map_zones": 2,
    "analytics": 2,
    "staff_management": 2,
    "layout_changer": 2,
}


def get_zoo_active_subscription(zoo: "Zoo | None"):
    """Return the most-recent *active* ZooSubscription for a zoo, or None."""
    if zoo is None:
        return None

    from models import ZooSubscription

    sub = (
        ZooSubscription.query.filter_by(zoo_id=zoo.id)
        .order_by(ZooSubscription.end_date.desc())
        .first()
    )
    if sub:
        sub.refresh_status()
    if sub and sub.status == "active":
        return sub
    return None


def get_zoo_subscription_tier(zoo: "Zoo | None") -> int:
    """Return the tier_level int for a zoo's active subscription.

    Returns -1 when there is no active subscription (expired / pending / none).
    Returns 0 when the plan has tier_level 0 (free).
    """
    sub = get_zoo_active_subscription(zoo)
    if sub is None:
        return -1
    return int(getattr(sub.plan, "tier_level", 1) or 1)


def paywall_redirect(required_tier: int = 1):
    """Flash a paywall message and redirect to the subscriptions page."""
    tier_name = TIER_NAMES.get(required_tier, f"Tier {required_tier}")
    flash(
        f"⚠️ This feature requires an active <strong>{tier_name} Plan</strong> or higher. "
        f"Please upgrade your subscription to continue.",
        "paywall",
    )
    return redirect(url_for("animal_farm_admin.subscriptions"))
