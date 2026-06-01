"""Dashboard route."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

from ..auth import login_required

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    container = current_app.config["CONTAINER"]
    summary = container.get_dashboard_summary.execute()
    diff = container.get_config_diff.execute()
    return render_template(
        "dashboard.html", summary=summary, diff=diff, active="dashboard"
    )
