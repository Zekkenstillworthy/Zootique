"""Canonical subscription plan and feature metadata."""
from __future__ import annotations

from typing import Any
import json


TIER_METADATA: dict[int, dict[str, Any]] = {
    0: {
        "name": "Free",
        "label": "Free Tier",
        "description": "Explore the platform with limited configuration access.",
        "features": ("Dashboard exploration", "Basic visitor and booking visibility"),
        "limits": {
            "staff_accounts": 0,
            "zones": 0,
            "animals": 0,
            "bookings_per_month": 0,
            "promo_bundles": 0,
        },
    },
    1: {
        "name": "Standard",
        "label": "Standard Tier",
        "description": "Core zoo operations and visitor configuration.",
        "features": (
            "Bookings, services, and animals",
            "Promotions, park rules, and revenue",
            "Availability and payment-method settings",
            "Pricing configuration and trivia management",
        ),
        "limits": {
            "staff_accounts": 3,
            "zones": 5,
            "animals": 100,
            "bookings_per_month": 500,
            "promo_bundles": 5,
        },
    },
    2: {
        "name": "Pro",
        "label": "Pro Tier",
        "description": "Advanced operations, reporting, and team management.",
        "features": (
            "Everything in Standard",
            "Map and zone management",
            "Analytics, graph builder, and staff management",
        ),
        "limits": {
            "staff_accounts": -1,
            "zones": -1,
            "animals": -1,
            "bookings_per_month": -1,
            "promo_bundles": -1,
        },
    },
}

PLAN_NAME_TIER: dict[str, int] = {
    "free": 0,
    "standard": 1,
    "pro": 2,
}


def tier_metadata(tier_level: int | None) -> dict[str, Any]:
    """Return canonical metadata for a tier, falling back safely to Standard."""
    try:
        level = int(tier_level)
    except (TypeError, ValueError):
        level = 1
    return TIER_METADATA.get(level, TIER_METADATA[1])


def tier_label(tier_level: int | None) -> str:
    return str(tier_metadata(tier_level)["label"])


def tier_name(tier_level: int | None) -> str:
    return str(tier_metadata(tier_level)["name"])


def infer_tier_level(name: str, requested: int | None = None) -> int:
    """Resolve a stored canonical plan name, preferring its explicit tier."""
    if requested is not None:
        try:
            level = int(requested)
            if level in TIER_METADATA:
                return level
        except (TypeError, ValueError):
            pass
    return PLAN_NAME_TIER.get((name or "").strip().lower(), 1)


def plan_context(plan: Any) -> dict[str, Any]:
    metadata = tier_metadata(getattr(plan, "tier_level", 1))
    raw_limits = getattr(plan, "limits", None)
    try:
        limits = json.loads(raw_limits) if raw_limits else metadata["limits"]
    except (TypeError, ValueError, json.JSONDecodeError):
        limits = metadata["limits"]
    return {
        "id": plan.id,
        "name": plan.name,
        "tier_level": int(getattr(plan, "tier_level", 1) or 1),
        "tier_name": metadata["name"],
        "tier_label": metadata["label"],
        "description": metadata["description"],
        "features": tuple(
            line.strip()
            for line in (getattr(plan, "features", "") or "").splitlines()
            if line.strip()
        ) or tuple(metadata["features"]),
        "price": float(getattr(plan, "price", 0) or 0),
        "duration": getattr(plan, "duration", "monthly") or "monthly",
        "duration_months": int(getattr(plan, "duration_months", 1) or 1),
        "is_active": bool(getattr(plan, "is_active", False)),
        "limits": limits,
    }


def sort_plans(plans: list[Any]) -> list[Any]:
    return sorted(
        plans,
        key=lambda plan: (
            int(getattr(plan, "tier_level", 1) or 1),
            float(getattr(plan, "price", 0) or 0),
            str(getattr(plan, "name", "")).lower(),
        ),
    )


def get_landing_pricing_tiers(plans: list[Any] | None = None) -> list[dict[str, Any]]:
    """Build dynamic pricing tiers list for the landing page based on active Super Admin plans."""
    if plans is None:
        try:
            from models import SubscriptionPlan
            active_plans = SubscriptionPlan.query.filter_by(is_active=True).all()
        except Exception:
            active_plans = []
    else:
        active_plans = [p for p in plans if getattr(p, "is_active", True)]

    sorted_plans = sort_plans(active_plans)
    landing_tiers: list[dict[str, Any]] = []

    monthly_plans: dict[int, Any] = {}
    yearly_plans: dict[int, Any] = {}
    other_plans: list[Any] = []

    for p in sorted_plans:
        tier_lvl = int(getattr(p, "tier_level", 1) or 1)
        dur = (getattr(p, "duration", "monthly") or "monthly").strip().lower()
        if dur == "yearly":
            if tier_lvl not in yearly_plans:
                yearly_plans[tier_lvl] = p
            else:
                other_plans.append(p)
        elif dur == "monthly":
            if tier_lvl not in monthly_plans:
                monthly_plans[tier_lvl] = p
            else:
                other_plans.append(p)
        else:
            other_plans.append(p)

    all_tiers = sorted(set(list(monthly_plans.keys()) + list(yearly_plans.keys())))

    for tier_lvl in all_tiers:
        m_plan = monthly_plans.get(tier_lvl)
        y_plan = yearly_plans.get(tier_lvl)
        primary_plan = m_plan or y_plan
        ctx = plan_context(primary_plan)

        name = primary_plan.name
        display_name = name if name.lower().endswith("tier") else f"{name} Tier"

        if m_plan:
            m_price = float(getattr(m_plan, "price", 0) or 0)
            if y_plan:
                y_price = float(getattr(y_plan, "price", 0) or 0)
                y_equiv = y_price / 12.0
                savings_pct = max(0, round((1.0 - (y_price / (m_price * 12.0 if m_price else 1.0))) * 100))
            else:
                y_price = round(m_price * 12.0 * 0.8)
                y_equiv = round(m_price * 0.8)
                savings_pct = 20
        else:
            y_price = float(getattr(y_plan, "price", 0) or 0)
            y_equiv = round(y_price / 12.0)
            m_price = y_equiv
            savings_pct = 0

        m_formatted = f"{m_price:,.0f}" if m_price == int(m_price) else f"{m_price:,.2f}"
        y_m_formatted = f"{y_equiv:,.0f}" if y_equiv == int(y_equiv) else f"{y_equiv:,.2f}"
        y_tot_formatted = f"{y_price:,.0f}" if y_price == int(y_price) else f"{y_price:,.2f}"

        is_popular = (tier_lvl == 1)
        cta = "Start with Standard" if tier_lvl == 1 else ("Go Pro" if tier_lvl == 2 else f"Start with {primary_plan.name}")

        landing_tiers.append({
            "id": primary_plan.id,
            "monthly_plan_id": m_plan.id if m_plan else None,
            "yearly_plan_id": y_plan.id if y_plan else None,
            "tier_level": tier_lvl,
            "tier_name": ctx["tier_name"],
            "tier_label": ctx["tier_label"],
            "name": display_name,
            "description": ctx["description"],
            "monthly_price": m_price,
            "monthly_price_formatted": m_formatted,
            "yearly_price": y_price,
            "yearly_price_formatted": y_tot_formatted,
            "yearly_monthly_formatted": y_m_formatted,
            "yearly_savings_pct": savings_pct,
            "features": ctx["features"],
            "limits": ctx["limits"],
            "is_popular": is_popular,
            "cta_label": cta,
        })

    for o_plan in other_plans:
        ctx = plan_context(o_plan)
        price_val = float(getattr(o_plan, "price", 0) or 0)
        p_formatted = f"{price_val:,.0f}" if price_val == int(price_val) else f"{price_val:,.2f}"
        landing_tiers.append({
            "id": o_plan.id,
            "tier_level": ctx["tier_level"],
            "tier_name": ctx["tier_name"],
            "tier_label": ctx["tier_label"],
            "name": o_plan.name,
            "description": ctx["description"],
            "monthly_price": price_val,
            "monthly_price_formatted": p_formatted,
            "yearly_price": price_val * 12 * 0.8,
            "yearly_price_formatted": f"{(price_val * 12 * 0.8):,.0f}",
            "yearly_monthly_formatted": f"{(price_val * 0.8):,.0f}",
            "yearly_savings_pct": 20,
            "features": ctx["features"],
            "limits": ctx["limits"],
            "is_popular": False,
            "cta_label": f"Choose {o_plan.name}",
        })

    return landing_tiers
