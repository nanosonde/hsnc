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
from ..auth import current_user, login_required, role_required

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
    plan = container.plan_apply.execute()
    return render_template(
        "pending_changes.html", diff=diff, plan=plan, active="devices"
    )


def _flash_apply_result(result) -> None:
    if result.ok:
        applied = len(result.results)
        if applied:
            flash(f"Configuration applied to {applied} device(s).", "success")
        else:
            flash("Nothing to apply.", "success")
    else:
        for failure in result.failures:
            flash(f"{failure.device_name}: {failure.message}", "error")


@bp.route("/config/apply", methods=["POST"])
@role_required("admin")
def apply():
    container = _container()
    user = current_user() or {}
    result = container.apply_config.execute(username=user.get("username", ""))
    _flash_apply_result(result)
    return redirect(url_for("config.pending"))


@bp.route("/config/apply/<device_id>", methods=["POST"])
@role_required("admin")
def apply_device(device_id: str):
    container = _container()
    user = current_user() or {}
    result = container.apply_config.execute(
        device_ids=[device_id], username=user.get("username", "")
    )
    _flash_apply_result(result)
    return redirect(url_for("config.pending"))


@bp.route("/config/revert", methods=["POST"])
@role_required("admin")
def revert():
    container = _container()
    reverted = container.revert_changes.execute()
    if reverted:
        flash(f"Reverted {reverted} device(s) to the last applied configuration.", "success")
    else:
        flash("Nothing to revert.", "success")
    return redirect(url_for("config.pending"))


@bp.route("/config/history")
@login_required
def history():
    container = _container()
    events = container.list_apply_history.execute()
    return render_template("apply_history.html", events=events, active="devices")
