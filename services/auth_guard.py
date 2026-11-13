from __future__ import annotations

from typing import Sequence
from flask import flash, redirect, request, session, url_for

from models import User, db


def require_role_guard(*, expected_role: str | Sequence[str], login_module: str):
    """Enforce a role-based session.

    Returns a Flask response (redirect) when access is not allowed, else None.

    Notes:
    - We keep sessions permanent + modified to reduce idle logouts.
    - We validate the user still exists and is active.
    """

    allowed_roles: tuple[str, ...] = (
        (expected_role,)
        if isinstance(expected_role, str)
        else tuple(expected_role)
    )

    auth_by_role = session.get("auth_by_role")
    if not isinstance(auth_by_role, dict):
        auth_by_role = {}

    active_role = session.get("role")
    matched_role: str | None = None
    user_id = None

    # Priority 1: if currently active session role matches one of allowed_roles
    if active_role in allowed_roles:
        role_state = auth_by_role.get(str(active_role))
        if isinstance(role_state, dict):
            user_id = role_state.get("user_id")
            if user_id:
                matched_role = str(active_role)

    # Priority 2: check any allowed role recorded in auth_by_role
    if not user_id:
        for r in allowed_roles:
            role_state = auth_by_role.get(str(r))
            if isinstance(role_state, dict) and role_state.get("user_id"):
                matched_role = str(r)
                user_id = role_state.get("user_id")
                break

    # Back-compat: allow older sessions that only have top-level keys.
    if not user_id and active_role in allowed_roles:
        user_id = session.get("user_id")
        matched_role = str(active_role)

    if not user_id:
        next_url = request.full_path
        if next_url.endswith("?"):
            next_url = next_url[:-1]
        return redirect(url_for("auth.login", module_name=login_module, next=next_url))

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        if matched_role:
            auth_by_role.pop(matched_role, None)
            session["auth_by_role"] = auth_by_role
        next_url = request.full_path
        if next_url.endswith("?"):
            next_url = next_url[:-1]
        return redirect(url_for("auth.login", module_name=login_module, next=next_url))

    user = db.session.get(User, user_id_int)
    normalized_status = (
        (getattr(user, "status", "active") or "active").strip().lower()
        if user is not None
        else "active"
    )
    if not user or normalized_status != "active":
        if matched_role:
            auth_by_role.pop(matched_role, None)
            session["auth_by_role"] = auth_by_role
        flash("Your account is not active. Please sign in again.", "error")
        next_url = request.full_path
        if next_url.endswith("?"):
            next_url = next_url[:-1]
        return redirect(url_for("auth.login", module_name=login_module, next=next_url))

    if user.role not in allowed_roles:
        # Role mismatch: treat as not authenticated for this module.
        if matched_role:
            auth_by_role.pop(matched_role, None)
            session["auth_by_role"] = auth_by_role
        next_url = request.full_path
        if next_url.endswith("?"):
            next_url = next_url[:-1]
        return redirect(url_for("auth.login", module_name=login_module, next=next_url))

    # Sync role-specific session state and refresh legacy top-level keys.
    auth_by_role[str(user.role)] = {
        "user_id": int(user.id),
        "full_name": user.full_name,
        "profile_image": user.profile_image,
    }
    session["auth_by_role"] = auth_by_role

    session["user_id"] = user.id
    session["role"] = user.role
    session["full_name"] = user.full_name
    session["profile_image"] = user.profile_image

    session.permanent = True
    session.modified = True
    return None
