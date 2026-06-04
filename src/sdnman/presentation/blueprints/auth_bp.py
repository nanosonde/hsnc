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
        container = current_app.config["CONTAINER"]
        result = container.authenticate_user.execute(username, password)
        if result is None:
            flash("Invalid username or password.", "error")
            return render_template("login.html", username=username), 401
        login_user(result.username, result.display_name, result.role)
        return redirect(url_for("dashboard.index"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
