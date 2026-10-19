from datetime import timedelta

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from blueprints.visitor.routes import visitor_bp
import importlib
import os
import secrets

from flask_migrate import Migrate
from werkzeug.exceptions import RequestEntityTooLarge

from models import db


migrate = Migrate()

def create_app() -> Flask:
    # Load environment variables from .env if present.
    # This keeps secrets out of source control and avoids needing to set env vars manually.
    try:
        dotenv = importlib.import_module("dotenv")
        env_name_for_dotenv = os.environ.get("FLASK_ENV", "development").strip().lower()
        override_dotenv = env_name_for_dotenv in {"development", "dev", "testing", "test"}
        dotenv.load_dotenv(override=override_dotenv)
    except Exception:
        pass

    app = Flask(__name__)
    # Default to development so local runs work out-of-the-box.
    # Production deployments should explicitly set FLASK_ENV=production and SECRET_KEY.
    env_name = os.environ.get("FLASK_ENV", "development").strip().lower()
    secret_key = os.environ.get("SECRET_KEY")
    if env_name in {"development", "dev", "testing", "test"}:
        app.secret_key = secret_key or "zootique-dev-secret-key-2026"
    else:
        if not secret_key:
            raise RuntimeError("SECRET_KEY is required in non-development environments.")
        app.secret_key = secret_key

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = env_name not in {"development", "dev", "testing", "test"}

    # Keep users signed in even if they are idle.
    # Flask sessions are cookie-based; making them permanent avoids browsers
    # dropping the session cookie after inactivity.
    # Can be overridden via env var if desired.
    session_days = int(os.environ.get("SESSION_LIFETIME_DAYS", "3650"))
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=max(session_days, 1))
    app.config["SESSION_REFRESH_EACH_REQUEST"] = True
    app.config["MAX_CONTENT_LENGTH"] = int(4.2 * 1024 * 1024)
    app.config["JSON_SORT_KEYS"] = False

    # UI version label (used in templates). Can be overridden via env var.
    app.config["APP_VERSION"] = (os.environ.get("APP_VERSION") or "2.4.0").strip()
    app.config["SITE_TIMEZONE"] = (os.environ.get("SITE_TIMEZONE") or "Asia/Manila").strip()

    @app.before_request
    def refresh_permanent_session():
        # Ensure logged-in sessions stay alive while the user is active.
        # This avoids browsers treating the cookie as a session-only cookie
        # after long idle times or across reverse proxy deployments.
        auth_by_role = session.get("auth_by_role")
        has_any_role = isinstance(auth_by_role, dict) and len(auth_by_role) > 0
        if session.get("user_id") is not None or has_any_role:
            session.permanent = True
            session.modified = True

    @app.errorhandler(RequestEntityTooLarge)
    def handle_oversized_request(error):
        if request.path in {"/auth/register-step-1", "/auth/register-admin-step1"}:
            flash("Each registration document must be no larger than 4 MB.", "error")
            return redirect(url_for("auth.register_admin_step1"))
        referer = request.referrer
        if referer:
            flash("The uploaded file is too large for cloud storage (maximum 4 MB). Please select a smaller or compressed image.", "error")
            return redirect(referer)
        return "The submitted data exceeds the 4 MB limit.", 413

    @app.context_processor
    def inject_csrf_token():
        """Provide a template helper used by forms across the app."""
        def csrf_token() -> str:
            token = session.get("_csrf_token")
            if not token:
                token = secrets.token_urlsafe(24)
                session["_csrf_token"] = token
            return token

        return {"csrf_token": csrf_token}

    @app.context_processor
    def inject_current_zoo_name():
        """Expose the active/assigned Zoo name, current user full name, and avatar for header display."""
        zoo_name = None
        user_avatar = None
        current_user_name = None
        try:
            role = session.get('role')
            user_id = session.get('user_id')

            auth_by_role = session.get('auth_by_role')
            if isinstance(auth_by_role, dict):
                blueprint = request.blueprint or ''
                if 'staff' in blueprint and 'zoo_staff' in auth_by_role:
                    st = auth_by_role.get('zoo_staff')
                    if isinstance(st, dict):
                        user_id = st.get('user_id') or user_id
                elif 'admin' in blueprint and 'zoo_admin' in auth_by_role:
                    st = auth_by_role.get('zoo_admin')
                    if isinstance(st, dict):
                        user_id = st.get('user_id') or user_id

            from models import User, Zoo  # local import to avoid circulars at app startup

            if user_id:
                user = db.session.get(User, int(user_id))
                if user:
                    user_avatar = user.profile_image
                    current_user_name = user.full_name or user.username
                    if user.zoo_id:
                        zoo = db.session.get(Zoo, int(user.zoo_id))
                        zoo_name = zoo.name if zoo else None

            if role == 'visitor' or (not zoo_name and session.get('selected_zoo_id')):
                selected_zoo_id = session.get('selected_zoo_id')
                if selected_zoo_id:
                    zoo = db.session.get(Zoo, int(selected_zoo_id))
                    zoo_name = zoo.name if zoo else zoo_name
        except Exception:
            pass

        return {
            'current_zoo_name': zoo_name,
            'current_user_avatar': user_avatar or session.get('profile_image'),
            'current_user_name': current_user_name or session.get('full_name'),
        }

    # --- Database configuration (Postgres-only) ---
    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required and must point to Postgres (example: postgresql+psycopg://user:pass@host:5432/dbname)."
        )

    # Normalize to psycopg (v3) driver when users provide a generic URL.
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://") :]
    elif database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://") :]

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # pool_pre_ping recycles dead connections; pool_size/max_overflow sized to support concurrent requests.
    if env_name in {"development", "dev", "testing", "test"}:
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_size": 10,
            "max_overflow": 20,
            "pool_recycle": 300,
        }
    else:
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_size": 5,
            "max_overflow": 10,
            "pool_recycle": 300,
        }
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Supabase Storage credentials (used by services/storage.py)
    app.config["SUPABASE_URL"] = os.environ.get("SUPABASE_URL", "").strip()
    app.config["SUPABASE_KEY"] = os.environ.get("SUPABASE_KEY", "").strip()
    app.config["SUPABASE_STORAGE_BUCKET"] = os.environ.get("SUPABASE_STORAGE_BUCKET", "zootique-images").strip()

    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        backend = db.engine.url.get_backend_name().lower()
        # if backend != "postgresql":
        #     raise RuntimeError(f"Unsupported database backend '{backend}'. Zootique is configured for Postgres only.")

        # In production (Vercel) skip the eager connection probe.
        # Supabase validates the connection on first use via pool_pre_ping.
        # In development we keep the fast-fail check so bad credentials are
        # caught immediately at startup.
        if env_name in {"development", "dev", "testing", "test"}:
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("SELECT 1"))
            except Exception as ex:
                safe_url = db.engine.url.render_as_string(hide_password=True)
                lower_msg = str(ex).lower()
                missing_db_hint = ""
                if "does not exist" in lower_msg and "database" in lower_msg:
                    missing_db_hint = (
                        " The target database does not exist yet. "
                        "Create it first (example: in psql: CREATE DATABASE zootique;)."
                    )
                raise RuntimeError(
                    "Unable to connect to Postgres using DATABASE_URL. "
                    f"Resolved URL: {safe_url}. "
                    "Verify the server is running and the username/password/database are correct."
                    + missing_db_hint
                ) from ex

    # Register Blueprints
    @app.get("/")
    def landing():
        hero_zoos = []
        try:
            from models import Zoo, Service, Feedback, Animal, User
            from sqlalchemy import func as _func
            db_zoos = Zoo.query.order_by(Zoo.id.asc()).all()
            for zoo in db_zoos:
                # Only include establishments that are not suspended
                admin_users = User.query.filter(
                    User.zoo_id == zoo.id,
                    User.role.in_(["admin", "animal_farm_admin", "zoo_admin"])
                ).all()
                if admin_users and all(getattr(u, "status", "active") == "suspended" for u in admin_users):
                    continue

                rating_val = (
                    db.session.query(_func.avg(Feedback.rating))
                    .filter(Feedback.zoo_id == zoo.id)
                    .scalar() or 0
                )
                min_price = (
                    db.session.query(_func.min(Service.price))
                    .filter(Service.zoo_id == zoo.id)
                    .scalar() or 0
                )
                animal_count = (
                    db.session.query(_func.count(Animal.id))
                    .filter(Animal.zoo_id == zoo.id)
                    .scalar() or 0
                )
                hero_zoos.append({
                    "id": zoo.id,
                    "name": zoo.landing_promo_title or zoo.name,
                    "type": (zoo.type or "Zoo Park").strip(),
                    "location": zoo.location or "",
                    "description": zoo.landing_promo_description or zoo.description or "Discover curated wildlife experiences.",
                    "image_url": zoo.landing_promo_image_url or zoo.image_url or "",
                    "rating": round(float(rating_val), 1),
                    "price": float(min_price or 0),
                    "animal_count": int(animal_count or 0),
                })

            platform_stats = None
            if hero_zoos:
                from models import Booking
                total_animals = db.session.query(_func.count(Animal.id)).scalar() or 0
                total_bookings = db.session.query(_func.count(Booking.id)).scalar() or 0
                platform_stats = {
                    "zoos": len(hero_zoos),
                    "species": int(total_animals),
                    "bookings": int(total_bookings),
                }
            subscription_plans = []
            try:
                from models import SubscriptionPlan
                subscription_plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.tier_level.asc(), SubscriptionPlan.price.asc()).all()
            except Exception:
                subscription_plans = []

            from models import Event, Promotion
            upcoming_events = Event.query.order_by(Event.id.desc()).limit(6).all()
            active_promotions = Promotion.query.order_by(Promotion.id.desc()).limit(6).all()
            wildlife_facts = Animal.query.filter(Animal.fun_facts.isnot(None), Animal.fun_facts != '').order_by(Animal.id.desc()).limit(8).all()

            from services.subscription_catalog import TIER_METADATA
        except Exception:
            hero_zoos = []
            platform_stats = None
            subscription_plans = []
            upcoming_events = []
            active_promotions = []
            wildlife_facts = []
            TIER_METADATA = {}
        return render_template(
            "landing.html",
            hero_zoos=hero_zoos,
            stats=platform_stats,
            subscription_plans=subscription_plans,
            tier_catalog=TIER_METADATA,
            upcoming_events=upcoming_events,
            active_promotions=active_promotions,
            wildlife_facts=wildlife_facts,
        )

    app.register_blueprint(visitor_bp, url_prefix="/visitor")

    from blueprints.auth.routes import auth_bp
    from blueprints.zootique_admin.routes import admin_bp
    from blueprints.animal_farm_admin.routes import animal_farm_admin_bp
    from blueprints.animal_farm_staff.routes import zoo_staff_bp
    from blueprints.api.routes import api_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/zootique-admin")
    app.register_blueprint(animal_farm_admin_bp, url_prefix="/animal-farm-admin")
    app.register_blueprint(zoo_staff_bp, url_prefix="/animal-farm-staff")
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.context_processor
    def inject_global_notifications():
        user_id = session.get("user_id")
        role = session.get("role")
        result = {
            "visitor_notifications": [],
            "visitor_unread_count": 0,
            "sa_notifications": [],
            "sa_unread_count": 0,
        }
        if not user_id:
            return result
        try:
            from models import Notification
            notifs = (
                Notification.query.filter_by(user_id=int(user_id))
                .order_by(Notification.created_at.desc())
                .limit(15)
                .all()
            )
            unread_count = sum(1 for n in notifs if not n.read_at)
            result["visitor_notifications"] = notifs
            result["visitor_unread_count"] = unread_count

            if role in ("zootique_admin", "super_admin"):
                from models import EstablishmentRegistration, ZooAdminFeedback, ZooSubscription
                sa_alerts = []

                # Pending registrations
                pending_regs = (
                    EstablishmentRegistration.query.filter(EstablishmentRegistration.status.ilike("pending"))
                    .order_by(EstablishmentRegistration.created_at.desc())
                    .limit(6)
                    .all()
                )
                for pr in pending_regs:
                    sa_alerts.append({
                        "id": f"reg-{pr.id}",
                        "type": "registration",
                        "title": "Registration Pending",
                        "message": f"Review application from {pr.establishment_name} ({pr.establishment_type})",
                        "time": pr.created_at,
                        "url": url_for("zootique_admin.registration_detail", registration_id=pr.id),
                        "icon": "fa-file-circle-check",
                        "badge": "Pending Review",
                    })

                # Open feedback
                open_feedback = (
                    ZooAdminFeedback.query.filter_by(status="open")
                    .order_by(ZooAdminFeedback.created_at.desc())
                    .limit(5)
                    .all()
                )
                for fb in open_feedback:
                    zoo_name = fb.zoo.name if fb.zoo else "Zoo Admin"
                    sa_alerts.append({
                        "id": f"fb-{fb.id}",
                        "type": "feedback",
                        "title": "Zoo Feedback Received",
                        "message": f"{zoo_name}: {fb.subject or 'System feedback submitted'}",
                        "time": fb.created_at,
                        "url": url_for("zootique_admin.view_feedback"),
                        "icon": "fa-comment-dots",
                        "badge": "New Message",
                    })

                # Pending subscriptions
                pending_subs = (
                    ZooSubscription.query.filter(ZooSubscription.status.ilike("pending"))
                    .order_by(ZooSubscription.start_date.desc())
                    .limit(5)
                    .all()
                )
                for ps in pending_subs:
                    zoo_name = ps.zoo.name if ps.zoo else "Zoo"
                    sa_alerts.append({
                        "id": f"sub-{ps.id}",
                        "type": "subscription",
                        "title": "Subscription Activation",
                        "message": f"{zoo_name} has a pending subscription request",
                        "time": ps.start_date,
                        "url": url_for("zootique_admin.manage_subscriptions"),
                        "icon": "fa-credit-card",
                        "badge": "Pending",
                    })

                # Personal user notifications
                for un in notifs:
                    sa_alerts.append({
                        "id": f"notif-{un.id}",
                        "type": "personal",
                        "title": "System Alert",
                        "message": un.message,
                        "time": un.created_at,
                        "url": "#",
                        "icon": "fa-bell",
                        "badge": "Alert",
                    })

                result["sa_notifications"] = sa_alerts
                result["sa_unread_count"] = len(pending_regs) + len(open_feedback) + len(pending_subs) + unread_count

            return result
        except Exception:
            return result

    # --- Friendly URL aliases---
    @app.get("/zoo_admin")
    @app.get("/zoo_admin/")
    @app.get("/zoo_admin/dashboard")
    def zoo_admin_alias():
        return redirect(url_for("animal_farm_admin.dashboard"))

    @app.get("/zoo_staff")
    @app.get("/zoo_staff/")
    @app.get("/zoo_staff/dashboard")
    def zoo_staff_alias():
        return redirect(url_for("animal_farm_staff.dashboard"))

    @app.get("/super_admin")
    @app.get("/super_admin/")
    @app.get("/super_admin/dashboard")
    def super_admin_alias():
        return redirect(url_for("zootique_admin.dashboard"))

    def wants_json() -> bool:
        best = request.accept_mimetypes.best
        return request.path.startswith("/api/") or best == "application/json"

    @app.errorhandler(400)
    def bad_request(error):
        message = getattr(error, "description", "Bad request.")
        if wants_json():
            return jsonify({"error": "bad_request", "message": message}), 400
        return f"400 Bad Request: {message}", 400

    @app.errorhandler(403)
    def forbidden(error):
        message = getattr(error, "description", "Forbidden.")
        if wants_json():
            return jsonify({"error": "forbidden", "message": message}), 403
        return f"403 Forbidden: {message}", 403

    @app.errorhandler(404)
    def not_found(error):
        message = getattr(error, "description", "Not found.")
        if wants_json():
            return jsonify({"error": "not_found", "message": message}), 404
        return f"404 Not Found: {message}", 404

    @app.errorhandler(500)
    def server_error(error):
        if wants_json():
            return jsonify({"error": "server_error", "message": "Unexpected server error."}), 500
        return "500 Internal Server Error", 500

    @app.get("/uploads/establishment_registrations/<path:filename>")
    def registration_uploaded_file(filename: str):
        auth_by_role = session.get("auth_by_role") or {}
        is_super_admin = session.get("role") == "zootique_admin" or (
            isinstance(auth_by_role, dict) and isinstance(auth_by_role.get("zootique_admin"), dict)
        )
        if not is_super_admin:
            abort(403)
        return send_from_directory(
            os.path.join(app.config["UPLOAD_FOLDER"], "establishment_registrations"),
            filename,
        )

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename: str):
        if filename.startswith("establishment_registrations/"):
            abort(403)
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    return app

# Expose the WSGI app at module level so Vercel's Python runtime can discover
# it automatically (it looks for a variable named ``app``).
app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
