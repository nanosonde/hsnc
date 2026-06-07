"""Devices routes: list, detail, and inventory actions (re-read, delete)."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)

from ..auth import current_user, login_required, role_required

bp = Blueprint("devices", __name__)


@bp.route("/devices")
@login_required
def index():
    container = current_app.config["API"]
    rows = container.list_devices()
    return render_template("devices.html", rows=rows, active="devices")


@bp.route("/devices/<device_id>")
@login_required
def detail(device_id: str):
    container = current_app.config["API"]
    detail = container.get_device_detail(device_id)
    if detail is None:
        abort(404)
    return render_template("device_detail.html", detail=detail, active="devices")


def _flash_sync_result(result) -> None:
    if result.failures:
        for failure in result.failures:
            flash(f"{failure.device_name}: {failure.message}", "error")
    ok_count = len([r for r in result.results if r.ok])
    if ok_count:
        flash(f"Re-read configuration from {ok_count} device(s).", "success")
    elif not result.results:
        flash("No devices to re-read.", "success")


@bp.route("/devices/sync", methods=["POST"])
@role_required("admin")
def sync_all():
    container = current_app.config["API"]
    user = current_user() or {}
    result = container.sync_device_config(username=user.get("username", ""))
    _flash_sync_result(result)
    return redirect(url_for("devices.index"))


@bp.route("/devices/<device_id>/sync", methods=["POST"])
@role_required("admin")
def sync_device(device_id: str):
    container = current_app.config["API"]
    user = current_user() or {}
    result = container.sync_device_config(
        device_ids=[device_id], username=user.get("username", "")
    )
    _flash_sync_result(result)
    return redirect(url_for("devices.index"))


@bp.route("/devices/<device_id>/delete", methods=["POST"])
@role_required("admin")
def delete_device(device_id: str):
    container = current_app.config["API"]
    device = container.get_device_detail(device_id)
    if device is None:
        abort(404)
    container.delete_device(device_id)
    flash("Device removed from the inventory.", "success")
    return redirect(url_for("devices.index"))
