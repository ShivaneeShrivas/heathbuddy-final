"""HealthBuddy application factory."""
from flask import Flask, render_template

APP_BUILD = "2026-08-04-final"   # bump when shipping

from .config import Config
from .db import close_db, init_db


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    init_db(app)
    app.teardown_appcontext(close_db)

    # CORS for the native phone app: its screens are bundled on-device and
    # call this API from a different origin. Tokens travel in the
    # Authorization header (no cookies), so a permissive policy is safe here.
    @app.after_request
    def add_cors_headers(resp):
        from flask import request
        if request.path.startswith("/api"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        return resp

    @app.before_request
    def handle_preflight():
        from flask import request
        if request.method == "OPTIONS" and request.path.startswith("/api"):
            return "", 204

    from .routes.api import api
    app.register_blueprint(api)

    from .routes.features import bp as features_bp
    app.register_blueprint(features_bp)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/sw.js")
    def service_worker():
        """Served from the root (not /static/sw.js) so its default scope is
        '/' and it can actually control the whole app - a service worker
        registered from /static/ can only ever control pages under /static/,
        which silently breaks navigator.serviceWorker.ready on every other
        page. See templates/index.html for the matching registration."""
        from flask import send_from_directory
        response = send_from_directory(app.static_folder, "sw.js")
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"  # always fetch the latest sw.js
        return response

    @app.get("/health/mail")
    def health_mail():
        """Is email actually working? Answers in one look, with no secrets.
        Add ?to=you@example.com to send yourself a real test message."""
        from flask import request
        from .services import mailer
        info = mailer.status()
        target = request.args.get("to")
        if target:
            ok, reason = mailer.send(
                target, "HealthBuddy test email",
                "If you're reading this, HealthBuddy can send email. 🎉",
                "<p>If you're reading this, HealthBuddy can send email. 🎉</p>",
                app.logger)
            info["test_send"] = {"to": target, "ok": ok, "error": reason}
        return info

    @app.get("/health/db")
    def health_db():
        """Which engine is live, and can it actually read and write?
        Open this after deploying — it answers 'is my data safe?' instantly."""
        from .db import is_postgres, query
        try:
            users = query("SELECT COUNT(*) AS n FROM users", one=True)["n"]
            cards = query("SELECT COUNT(*) AS n FROM notification_cards", one=True)["n"]
            return {"engine": "postgres" if is_postgres() else "sqlite (temporary!)",
                    "persistent": bool(is_postgres()), "users": users, "cards": cards, "ok": True}
        except Exception as exc:
            return {"ok": False, "engine": "postgres" if is_postgres() else "sqlite",
                    "error": str(exc)}, 500

    @app.get("/health")
    def health():
        """`build` tells you which version is actually live — if it doesn't
        match what you just pushed, the deploy didn't land."""
        return {"status": "ok", "build": APP_BUILD,
                "features": ["otp-email", "postgres", "buddy-art", "light-theme"]}

    return app
