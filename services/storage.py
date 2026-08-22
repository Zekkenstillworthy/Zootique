"""
services/storage.py
-------------------
Cloud-aware image upload helper.

Production (Vercel + Supabase):
  - Uploads to Supabase Storage bucket ``SUPABASE_STORAGE_BUCKET``
    (defaults to "zootique-images").
  - Returns the public HTTPS URL stored by Supabase.

Local development (no SUPABASE_URL set):
  - Falls back to saving on the local filesystem under UPLOAD_FOLDER.
  - Returns a ``/uploads/...`` relative URL exactly as before.

Usage::

    from services.storage import save_uploaded_image

    url = save_uploaded_image(request.files.get("image_file"), "animal_images")
    if url:
        animal.image_url = url
"""

from __future__ import annotations

import os
import uuid

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

_ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _get_supabase_client():
    """Return a Supabase client if credentials are configured, else None."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        from supabase import create_client  # type: ignore
        return create_client(url, key)
    except Exception:
        return None


def save_uploaded_image(file_storage: FileStorage | None, subfolder: str) -> str | None:
    """
    Upload *file_storage* to cloud storage (Supabase) when configured, or to the
    local ``uploads/`` directory otherwise.

    Returns the image URL to persist in the database, or ``None`` on failure /
    when no file was provided.
    """
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None

    original_name = secure_filename(file_storage.filename)
    if not original_name:
        return None

    _, ext = os.path.splitext(original_name)
    ext = (ext or "").lower()
    if ext not in _ALLOWED_IMAGE_EXTENSIONS:
        try:
            from flask import flash
            flash("Unsupported image type. Please upload PNG, JPG, JPEG, GIF, or WEBP.", "error")
        except Exception:
            pass
        return None

    stored_name = f"{uuid.uuid4().hex}{ext}"
    # Normalise subfolder to forward-slash path segments (safe on all OSes).
    parts = [p for p in (subfolder or "").replace("\\", "/").split("/") if p]
    object_key = "/".join(parts + [stored_name])

    # --- Supabase Storage (production) ---
    supabase = _get_supabase_client()
    if supabase:
        bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "zootique-images").strip()
        try:
            file_bytes = file_storage.read()
            content_type = getattr(file_storage, "content_type", None) or "application/octet-stream"
            supabase.storage.from_(bucket).upload(
                path=object_key,
                file=file_bytes,
                file_options={"content-type": content_type},
            )
            public_url: str = supabase.storage.from_(bucket).get_public_url(object_key)
            return public_url
        except Exception as exc:
            current_app.logger.error("Supabase Storage upload failed: %s", exc)
            return None

    # --- Local filesystem fallback (development) ---
    try:
        folder = os.path.join(current_app.config["UPLOAD_FOLDER"], *parts)
        os.makedirs(folder, exist_ok=True)
        file_storage.save(os.path.join(folder, stored_name))
        return f"/uploads/{object_key}"
    except Exception as exc:
        current_app.logger.error("Local file save failed: %s", exc)
        return None
