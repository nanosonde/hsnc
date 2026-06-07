"""Topology route."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

from ..auth import login_required

bp = Blueprint("topology", __name__)


@bp.route("/topology")
@login_required
def index():
    container = current_app.config["API"]
    view = container.get_topology()
    return render_template("topology.html", topology=view, active="topology")
