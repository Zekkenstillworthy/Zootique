from __future__ import annotations

import json
from typing import Any

from models import SystemSetting, db


SUPPORTED_PAYMENT_METHODS = ("gcash", "maya", "card", "cash_on_arrival")
DEFAULT_PAYMENT_METHODS = list(SUPPORTED_PAYMENT_METHODS)


def _key(zoo_id: int, name: str) -> str:
    return f"zoo:{int(zoo_id)}:{name}"


def get_zoo_setting(zoo_id: int, name: str, default: Any) -> Any:
    setting = SystemSetting.query.filter_by(key=_key(zoo_id, name)).first()
    if not setting:
        return default
    try:
        return json.loads(setting.value)
    except (TypeError, ValueError):
        return default


def save_zoo_setting(zoo_id: int, name: str, value: Any) -> SystemSetting:
    key = _key(zoo_id, name)
    setting = SystemSetting.query.filter_by(key=key).first()
    if not setting:
        setting = SystemSetting(key=key, value="null")
        db.session.add(setting)
    setting.value = json.dumps(value)
    return setting


def get_payment_methods(zoo_id: int) -> list[str]:
    value = get_zoo_setting(zoo_id, "payment_methods", DEFAULT_PAYMENT_METHODS)
    if not isinstance(value, list):
        return list(DEFAULT_PAYMENT_METHODS)
    return [method for method in SUPPORTED_PAYMENT_METHODS if method in value]


def get_availability_settings(zoo_id: int) -> dict[str, Any]:
    defaults = {
        "closure_days": [0],
        "max_advance_days": 90,
    }
    value = get_zoo_setting(zoo_id, "availability", defaults)
    if not isinstance(value, dict):
        return defaults
    return {
        "closure_days": value.get("closure_days", defaults["closure_days"]),
        "max_advance_days": value.get("max_advance_days", defaults["max_advance_days"]),
    }
