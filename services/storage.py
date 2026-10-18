"""
services/storage.py
-------------------
Cloud-aware image & document upload helper.

Production (Vercel + Supabase):
  - Uploads to Supabase Storage bucket ``SUPABASE_STORAGE_BUCKET``
    (defaults to "zootique-images") using direct REST API.
  - Supports both standard JWT keys and Supabase secret tokens (sb_secret_...).
  - Returns the public HTTPS URL stored by Supabase.

Local development (no SUPABASE_URL set):
  - Falls back to saving on the local filesystem under UPLOAD_FOLDER.
  - Returns a ``/uploads/...`` relative URL.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
import uuid

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

_ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


def _upload_to_supabase(object_key: str, file_bytes: bytes, content_type: str | None) -> str | None:
    """Upload binary payload directly to Supabase Storage via REST API."""
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_KEY") or "").strip()
    bucket = (os.environ.get("SUPABASE_STORAGE_BUCKET") or "zootique-images").strip()

    if not url or not key:
        return None

    upload_endpoint = f"{url}/storage/v1/object/{bucket}/{object_key}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    }

    try:
        req = urllib.request.Request(upload_endpoint, data=file_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status in (200, 201):
                return f"{url}/storage/v1/object/public/{bucket}/{object_key}"
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        current_app.logger.error("Supabase Storage REST upload failed (HTTP %s): %s", exc.code, err_body)
    except Exception as exc:
        current_app.logger.error("Supabase Storage REST upload error: %s", exc)

    # Fallback to supabase-py library if installed and compatible
    try:
        from supabase import create_client  # type: ignore
        client = create_client(url, key)
        client.storage.from_(bucket).upload(
            path=object_key,
            file=file_bytes,
            file_options={"content-type": content_type or "application/octet-stream", "upsert": "true"},
        )
        return client.storage.from_(bucket).get_public_url(object_key)
    except Exception as exc:
        current_app.logger.debug("Supabase client library fallback failed: %s", exc)

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
    parts = [p for p in (subfolder or "").replace("\\", "/").split("/") if p]
    object_key = "/".join(parts + [stored_name])

    try:
        file_storage.seek(0)
        file_bytes = file_storage.read()
        file_storage.seek(0)
    except Exception as exc:
        current_app.logger.error("Failed to read uploaded file: %s", exc)
        return None

    content_type = getattr(file_storage, "content_type", None) or "application/octet-stream"

    # --- Cloud Storage (Supabase) ---
    public_url = _upload_to_supabase(object_key, file_bytes, content_type)
    if public_url:
        return public_url

    # Guard for Vercel serverless environment: local filesystem is read-only
    if os.environ.get("VERCEL"):
        current_app.logger.error(
            "[Vercel Serverless] Supabase storage upload failed or credentials missing. "
            "Please configure SUPABASE_URL, SUPABASE_KEY, and SUPABASE_STORAGE_BUCKET in Vercel project environment settings."
        )
        return None

    # --- Local filesystem fallback (development) ---
    try:
        folder = os.path.join(current_app.config["UPLOAD_FOLDER"], *parts)
        os.makedirs(folder, exist_ok=True)
        file_storage.seek(0)
        file_storage.save(os.path.join(folder, stored_name))
        return f"/uploads/{object_key}"
    except Exception as exc:
        current_app.logger.error("Local file save failed: %s", exc)
        return None


def save_uploaded_document(file_storage: FileStorage | None, subfolder: str) -> str | None:
    """Save a registration document to Supabase Storage or local development storage."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None

    original_name = secure_filename(file_storage.filename)
    if not original_name:
        return None

    _, ext = os.path.splitext(original_name)
    ext = (ext or "").lower()
    if ext not in _ALLOWED_DOCUMENT_EXTENSIONS:
        return None

    stored_name = f"{uuid.uuid4().hex}{ext}"
    parts = [p for p in (subfolder or "").replace("\\", "/").split("/") if p]
    object_key = "/".join(parts + [stored_name])

    try:
        file_storage.seek(0)
        file_bytes = file_storage.read()
        file_storage.seek(0)
    except Exception as exc:
        current_app.logger.error("Failed to read uploaded document: %s", exc)
        return None

    content_type = getattr(file_storage, "content_type", None) or "application/octet-stream"

    # --- Cloud Storage (Supabase) ---
    public_url = _upload_to_supabase(object_key, file_bytes, content_type)
    if public_url:
        return public_url

    # Guard for Vercel serverless environment: local filesystem is read-only
    if os.environ.get("VERCEL"):
        current_app.logger.error(
            "[Vercel Serverless] Supabase storage upload failed or credentials missing. "
            "Please configure SUPABASE_URL, SUPABASE_KEY, and SUPABASE_STORAGE_BUCKET in Vercel project environment settings."
        )
        return None

    try:
        folder = os.path.join(current_app.config["UPLOAD_FOLDER"], *parts)
        os.makedirs(folder, exist_ok=True)
        file_storage.seek(0)
        file_storage.save(os.path.join(folder, stored_name))
        return f"/uploads/{object_key}"
    except Exception as exc:
        current_app.logger.error("Local document save failed: %s", exc)
        return None
