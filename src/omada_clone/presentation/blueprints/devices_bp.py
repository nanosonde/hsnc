"""Devices routes: list and detail."""

from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template

from ..auth import login_required

bp = Blueprint("devices", __name__)


@bp.route("/devices")
@login_required
def index():
    container = current_app.config["CONTAINER"]
    rows = container.list_devices.execute()
    return render_template("devices.html", rows=rows, active="devices")


@bp.route("/devices/<device_id>")
@login_required
def detail(device_id: str):
    container = current_app.config["CONTAINER"]
    detail = container.get_device_detail.execute(device_id)
    if detail is None:
        abort(404)
    return render_template("device_detail.html", detail=detail, active="devices")
