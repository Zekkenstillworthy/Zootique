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
