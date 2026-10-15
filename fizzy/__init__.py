"""Local Fizzy: a Flask reader and writer for a Fizzy SQLite database."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request

from .db import connect
from .errors import FizzyError


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    root = Path(__file__).resolve().parent.parent
    instance = root / "instance"
    instance.mkdir(exist_ok=True)
    secret_path = instance / "secret_key"
    if not secret_path.exists():
        secret_path.write_text(secrets.token_hex(32))
    app.config.update(
        SECRET_KEY=os.environ.get("FIZZY_SECRET") or secret_path.read_text().strip(),
        DATABASE=os.environ.get("FIZZY_DATABASE", str(instance / "fizzy.sqlite3")),
        STORAGE=os.environ.get("FIZZY_STORAGE", str(instance / "storage")),
        TEMPLATES_AUTO_RELOAD=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)
    Path(app.config["STORAGE"]).mkdir(parents=True, exist_ok=True)

    from .routes import bp

    app.register_blueprint(bp)
    app.wsgi_app = _JsonSuffix(app.wsgi_app)

    @app.before_request
    def open_db():
        g.conn = connect(app.config["DATABASE"])
        g.rollback = False
        g.deliver = False

    @app.teardown_request
    def close_db(exc):
        conn = g.pop("conn", None)
        if conn is None:
            return
        try:
            if exc is not None or g.get("rollback"):
                conn.rollback()
            else:
                conn.commit()
        finally:
            conn.close()

    @app.errorhandler(FizzyError)
    def handle_fizzy(err: FizzyError):
        g.rollback = True
        if _wants_json():
            return jsonify(err.errors), err.status
        return render_template("error.html", status=err.status, message=err.message), err.status

    @app.errorhandler(404)
    def missing(_err):
        if _wants_json():
            return jsonify({"error": ["Not found"]}), 404
        return render_template("error.html", status=404, message="That page isn't here."), 404

    @app.errorhandler(Exception)
    def boom(err):
        if isinstance(err, FizzyError):
            return handle_fizzy(err)
        g.rollback = True
        app.logger.exception("request failed")
        if _wants_json():
            return jsonify({"error": ["Something went wrong"]}), 500
        return render_template("error.html", status=500, message="Something went wrong on this machine."), 500

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    return app


def _wants_json() -> bool:
    if request.environ.get("fizzy.json"):
        return True
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


class _JsonSuffix:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path.endswith(".json"):
            environ["PATH_INFO"] = path[:-5] or "/"
            environ["fizzy.json"] = "1"
        return self.app(environ, start_response)
