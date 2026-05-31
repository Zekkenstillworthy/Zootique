from datetime import timedelta

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from blueprints.visitor.routes import visitor_bp
import data
import importlib
import os
import secrets

from flask_migrate import Migrate

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
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    app.config["JSON_SORT_KEYS"] = False

    # UI version label (used in templates). Can be overridden via env var.
    app.config["APP_VERSION"] = (os.environ.get("APP_VERSION") or "2.4.0").strip()

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
        """Expose the active/assigned Zoo name for header display."""
        zoo_name = None
        try:
            role = session.get('role')
            user_id = session.get('user_id')

            from models import User, Zoo  # local import to avoid circulars at app startup

            if role in {'zoo_admin', 'zoo_staff'} and user_id:
                user = db.session.get(User, int(user_id))
                if user and user.zoo_id:
                    zoo = db.session.get(Zoo, int(user.zoo_id))
                    zoo_name = zoo.name if zoo else None

            if role == 'visitor':
                selected_zoo_id = session.get('selected_zoo_id')
                if selected_zoo_id:
                    zoo = db.session.get(Zoo, int(selected_zoo_id))
                    zoo_name = zoo.name if zoo else zoo_name
        except Exception:
            zoo_name = None

        return {'current_zoo_name': zoo_name}

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
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        backend = db.engine.url.get_backend_name().lower()
        if backend != "postgresql":
            raise RuntimeError(f"Unsupported database backend '{backend}'. Zootique is configured for Postgres only.")

        # Fail fast if Postgres is unreachable or credentials are invalid.
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

        # Auto-seed demo data in development/testing so pages don't render empty states.
        # Idempotent: only inserts when the relevant tables/sections are empty.
        auto_seed = os.environ.get("AUTO_SEED_DEMO_DATA", "1").strip().lower() not in {"0", "false", "no", "off"}
        if env_name in {"development", "dev", "testing", "test"} and auto_seed:
            try:
                from services.demo_seed import ensure_demo_data

                ensure_demo_data(allow_create_tables=True)
            except Exception:
                # Seeding is best-effort; the app should still boot even if seeding fails.
                db.session.rollback()

    # Inject mock data into application config
    app.config["ANIMALS"]    = data.ANIMALS
    app.config["ZOOS"]       = data.ZOOS
    app.config["SERVICES"]   = data.SERVICES
    app.config["BOOKINGS"]   = data.BOOKINGS
    app.config["EVENTS"]     = data.EVENTS
    app.config["PROMOTIONS"] = data.PROMOTIONS
    app.config["FEEDBACKS"]  = data.FEEDBACKS

    # Register Blueprints
    @app.get("/")
    def landing():
        return render_template("landing.html")

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

    # --- Friendly URL aliases (MVP flow expects these paths) ---
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

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename: str):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    return app

if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=True)

