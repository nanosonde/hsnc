"""Authentication routes: login and logout."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..auth import login_user, logout_user

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        limiter = current_app.config.get("LOGIN_RATELIMITER")
        client_key = request.remote_addr or "unknown"
        if limiter is not None and limiter.is_blocked(client_key):
            flash("Too many failed login attempts. Please wait and try again.", "error")
            return render_template("login.html", username=username), 429
        api = current_app.config["API"]
        result = api.login(username, password)
        if result is None:
            if limiter is not None:
                limiter.record_failure(client_key)
            flash("Invalid username or password.", "error")
            return render_template("login.html", username=username), 401
        if limiter is not None:
            limiter.reset(client_key)
        login_user(result.username, result.display_name, result.role)
        return redirect(url_for("dashboard.index"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
