from flask import Flask, jsonify, render_template, request, send_from_directory, session
from blueprints.visitor.routes import visitor_bp
import data
import os
import secrets

from models import db


def _column_exists_sqlite(table_name: str, column_name: str) -> bool:
    rows = db.session.execute(db.text(f"PRAGMA table_info({table_name});")).mappings().all()
    return any(r.get("name") == column_name for r in rows)


def _table_exists_sqlite(table_name: str) -> bool:
    row = db.session.execute(
        db.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).first()
    return row is not None


def _ensure_runtime_schema_compatibility(app: Flask):
    """Best-effort schema sync for environments without migration tooling.

    This keeps existing SQLite installations running after additive model changes.
    """
    with app.app_context():
        backend = db.engine.url.get_backend_name().lower()
        if backend != "sqlite":
            return

        db.create_all()

        if _table_exists_sqlite("bookings"):
            if not _column_exists_sqlite("bookings", "user_id"):
                db.session.execute(
                    db.text("ALTER TABLE bookings ADD COLUMN user_id INTEGER REFERENCES users(id);")
                )
            if not _column_exists_sqlite("bookings", "assigned_staff_user_id"):
                db.session.execute(
                    db.text("ALTER TABLE bookings ADD COLUMN assigned_staff_user_id INTEGER REFERENCES users(id);")
                )
            if not _column_exists_sqlite("bookings", "payment_status"):
                db.session.execute(
                    db.text("ALTER TABLE bookings ADD COLUMN payment_status VARCHAR(20) NOT NULL DEFAULT 'unpaid';")
                )
            if not _column_exists_sqlite("bookings", "payment_reference"):
                db.session.execute(
                    db.text("ALTER TABLE bookings ADD COLUMN payment_reference VARCHAR(100);")
                )
            if not _column_exists_sqlite("bookings", "paid_at"):
                db.session.execute(
                    db.text("ALTER TABLE bookings ADD COLUMN paid_at DATETIME;")
                )

        if _table_exists_sqlite("feedbacks"):
            if not _column_exists_sqlite("feedbacks", "user_id"):
                db.session.execute(
                    db.text("ALTER TABLE feedbacks ADD COLUMN user_id INTEGER REFERENCES users(id);")
                )
            if not _column_exists_sqlite("feedbacks", "created_at"):
                db.session.execute(
                    db.text("ALTER TABLE feedbacks ADD COLUMN created_at DATETIME;")
                )

            db.session.execute(
                db.text(
                    """
                    UPDATE feedbacks
                    SET created_at = CURRENT_TIMESTAMP
                    WHERE created_at IS NULL
                    """
                )
            )

            db.session.execute(
                db.text(
                    """
                    UPDATE feedbacks
                    SET user_id = (
                        SELECT u.id
                        FROM users u
                        WHERE lower(trim(u.email)) = lower(trim(feedbacks.visitor_name))
                        LIMIT 1
                    )
                    WHERE user_id IS NULL
                      AND visitor_name IS NOT NULL
                    """
                )
            )

        if _table_exists_sqlite("zoos"):
            if not _column_exists_sqlite("zoos", "landing_map_title"):
                db.session.execute(
                    db.text("ALTER TABLE zoos ADD COLUMN landing_map_title VARCHAR(160);")
                )
            if not _column_exists_sqlite("zoos", "landing_map_description"):
                db.session.execute(
                    db.text("ALTER TABLE zoos ADD COLUMN landing_map_description TEXT;")
                )
            if not _column_exists_sqlite("zoos", "landing_map_image_url"):
                db.session.execute(
                    db.text("ALTER TABLE zoos ADD COLUMN landing_map_image_url VARCHAR(500);")
                )
            if not _column_exists_sqlite("zoos", "landing_map_updated_at"):
                db.session.execute(
                    db.text("ALTER TABLE zoos ADD COLUMN landing_map_updated_at DATETIME;")
                )

            db.session.execute(
                db.text(
                    """
                    UPDATE feedbacks
                    SET user_id = (
                        SELECT u.id
                        FROM users u
                        WHERE lower(trim(u.full_name)) = lower(trim(feedbacks.visitor_name))
                        LIMIT 1
                    )
                    WHERE user_id IS NULL
                      AND visitor_name IS NOT NULL
                    """
                )
            )

        if not _table_exists_sqlite("booking_payments"):
            db.session.execute(
                db.text(
                    """
                    CREATE TABLE booking_payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        booking_id VARCHAR(20) NOT NULL,
                        payer_user_id INTEGER,
                        amount FLOAT NOT NULL,
                        method VARCHAR(30) NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'paid',
                        reference VARCHAR(100) NOT NULL UNIQUE,
                        provider VARCHAR(50) NOT NULL DEFAULT 'simulated_gateway',
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        paid_at DATETIME,
                        FOREIGN KEY (booking_id) REFERENCES bookings(id),
                        FOREIGN KEY (payer_user_id) REFERENCES users(id)
                    );
                    """
                )
            )

        db.session.execute(
            db.text(
                """
                UPDATE bookings
                SET payment_status = 'unpaid'
                WHERE payment_status IS NULL OR payment_status = ''
                """
            )
        )
        db.session.commit()

def create_app() -> Flask:
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
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    app.config["JSON_SORT_KEYS"] = False

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

    # --- Database configuration (default: SQLite in instance/) ---
    os.makedirs(app.instance_path, exist_ok=True)
    default_sqlite_path = os.path.join(app.instance_path, "zootique.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{default_sqlite_path}",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    _ensure_runtime_schema_compatibility(app)

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

