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
from services.subscription_catalog import TIER_METADATA, tier_label
from services.subscription_catalog import plan_context

if TYPE_CHECKING:
    from models import Zoo

# Maps tier_level int → human-readable tier name
TIER_NAMES = {
    level: str(metadata["name"])
    for level, metadata in TIER_METADATA.items()
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
    "booking_bundles": 1,
    "pricing_configuration": 1,
    "payment_methods": 1,
    "availability_settings": 1,
    "trivia_management": 1,
    # Pro (tier 2)
    "map_zones": 2,
    "analytics": 2,
    "staff_management": 1,
    "layout_changer": 2,
    "graph_builder": 2,
    "reports": 1,
}


def get_zoo_active_subscription(zoo: "Zoo | None"):
    """Return the most-recent *active* ZooSubscription for a zoo, or None."""
    if zoo is None:
        return None

    from models import ZooSubscription

    subscriptions = (
        ZooSubscription.query.filter_by(zoo_id=zoo.id)
        .order_by(ZooSubscription.end_date.desc())
        .all()
    )
    for sub in subscriptions:
        sub.refresh_status()
    active = [sub for sub in subscriptions if sub.status == "active"]
    if active:
        return max(active, key=lambda sub: sub.end_date)
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


def can_edit_feature(zoo: "Zoo | None", feature_name: str) -> bool:
    """Check whether a zoo admin has sufficient active subscription tier to edit/mutate a feature."""
    if zoo is None:
        return False
    required_tier = FEATURE_TIERS.get(feature_name, 1)
    return get_zoo_subscription_tier(zoo) >= required_tier


def feature_required_tier(feature_name: str) -> int:
    return FEATURE_TIERS.get(feature_name, 1)


def feature_limit(zoo: "Zoo | None", limit_name: str) -> int | None:
    """Return the active plan limit; None means unlimited or unavailable."""
    subscription = get_zoo_active_subscription(zoo)
    if not subscription:
        return 0
    limit = plan_context(subscription.plan)["limits"].get(limit_name)
    if limit is None or int(limit) < 0:
        return None
    return int(limit)


def limit_allows(zoo: "Zoo | None", limit_name: str, current_count: int) -> bool:
    limit = feature_limit(zoo, limit_name)
    return limit is None or current_count < limit


def paywall_redirect(required_tier: int = 1):
    """Flash a paywall message and redirect to the subscriptions page."""
    tier_name = tier_label(required_tier)
    flash(
        f"⚠️ This feature requires an active <strong>{tier_name} Plan</strong> or higher. "
        f"Please subscribe to the Super Admin to continue.",
        "paywall",
    )
    return redirect(url_for("animal_farm_admin.subscriptions"))


def paywall_edit_error(item_name: str, required_tier: int = 1):
    """Flash an edit-lock paywall error and redirect to subscriptions or back."""
    tier_name = tier_label(required_tier)
    flash(
        f"🔒 <strong>Editing Locked:</strong> You cannot add, modify, or delete {item_name} until your establishment is subscribed to the Super Admin ({tier_name} plan or higher).",
        "error",
    )
    return redirect(url_for("animal_farm_admin.subscriptions"))
