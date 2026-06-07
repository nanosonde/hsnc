"""Dashboard route."""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from ..auth import login_required, role_required, set_read_only

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    container = current_app.config["API"]
    summary = container.get_dashboard()
    diff = container.get_config_diff()
    return render_template(
        "dashboard.html", summary=summary, diff=diff, active="dashboard"
    )


@bp.route("/system/read-only", methods=["POST"])
@role_required("admin")
def toggle_read_only():
    enabled = request.form.get("enabled") == "on"
    set_read_only(enabled)
    flash(
        "Read-only mode enabled \u2014 device changes are blocked."
        if enabled
        else "Read-only mode disabled \u2014 device changes are allowed.",
        "success",
    )
    return redirect(request.referrer or url_for("dashboard.index"))
