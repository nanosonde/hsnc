"""Configuration management routes: edit device config and apply changes.

All mutating endpoints are admin-only. Edits write through to YAML (validated +
auto-backed-up); the apply workflow pushes the desired config to devices and
records the applied snapshot so the pending-changes diff clears.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ...application.use_cases.edit_device_config import (
    ConfigEditError,
    DeviceNotFoundError,
)
from ..auth import login_required, role_required

bp = Blueprint("config", __name__)


def _container():
    return current_app.config["CONTAINER"]


def _parse_vlan_list(raw: str) -> list[int]:
    if not raw.strip():
        return []
    result: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            result.append(int(chunk))
    return result


@bp.route("/devices/<device_id>/edit")
@login_required
def edit(device_id: str):
    container = _container()
    detail = container.get_device_detail.execute(device_id)
    if detail is None:
        abort(404)
    return render_template("device_edit.html", detail=detail, active="devices")


@bp.route("/devices/<device_id>/vlans", methods=["POST"])
@role_required("admin")
def save_vlan(device_id: str):
    container = _container()
    try:
        container.save_vlan.execute(
            device_id,
            vlan_id=int(request.form["vlan_id"]),
            name=request.form.get("name", "").strip(),
            subnet=request.form.get("subnet", "").strip(),
        )
    except (DeviceNotFoundError, ConfigEditError, ValueError) as exc:
        flash(f"Could not save VLAN: {exc}", "error")
    else:
        flash("VLAN saved.", "success")
    return redirect(url_for("config.edit", device_id=device_id))


@bp.route("/devices/<device_id>/vlans/<int:vlan_id>/delete", methods=["POST"])
@role_required("admin")
def delete_vlan(device_id: str, vlan_id: int):
    container = _container()
    try:
        container.delete_vlan.execute(device_id, vlan_id)
    except (DeviceNotFoundError, ConfigEditError) as exc:
        flash(f"Could not delete VLAN: {exc}", "error")
    else:
        flash("VLAN removed.", "success")
    return redirect(url_for("config.edit", device_id=device_id))


@bp.route("/devices/<device_id>/ports/<int:number>", methods=["POST"])
@role_required("admin")
def save_port(device_id: str, number: int):
    container = _container()
    try:
        container.save_port.execute(
            device_id,
            number=number,
            name=request.form.get("name", "").strip(),
            enabled=request.form.get("enabled") == "on",
            mode=request.form.get("mode", "access"),
            pvid=int(request.form["pvid"]),
            tagged_vlans=_parse_vlan_list(request.form.get("tagged_vlans", "")),
        )
    except (DeviceNotFoundError, ConfigEditError, ValueError) as exc:
        flash(f"Could not save port: {exc}", "error")
    else:
        flash(f"Port {number} saved.", "success")
    return redirect(url_for("config.edit", device_id=device_id))


@bp.route("/devices/<device_id>/ssids", methods=["POST"])
@role_required("admin")
def save_ssids(device_id: str):
    container = _container()
    raw = request.form.get("ssids", "")
    ssids = [line.strip() for line in raw.splitlines() if line.strip()]
    try:
        container.save_ssids.execute(device_id, ssids)
    except DeviceNotFoundError as exc:
        flash(f"Could not save SSIDs: {exc}", "error")
    else:
        flash("SSIDs saved.", "success")
    return redirect(url_for("config.edit", device_id=device_id))


@bp.route("/config/pending")
@login_required
def pending():
    container = _container()
    diff = container.get_config_diff.execute()
    return render_template("pending_changes.html", diff=diff, active="devices")


@bp.route("/config/apply", methods=["POST"])
@role_required("admin")
def apply():
    container = _container()
    result = container.apply_config.execute()
    if result.ok:
        flash("Configuration applied to all devices.", "success")
    else:
        for failure in result.failures:
            flash(f"{failure.device_name}: {failure.message}", "error")
    return redirect(url_for("config.pending"))
