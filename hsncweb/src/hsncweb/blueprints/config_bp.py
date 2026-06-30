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

from ..api_client import ConfigEditError, DeviceNotFoundError
from ..auth import current_user, login_required, role_required

bp = Blueprint("config", __name__)


def _container():
    return current_app.config["API"]


_VLAN_MIN = 1
_VLAN_MAX = 4094


def _int_field(name: str, *, min_value: int, max_value: int) -> int:
    """Read a required integer form field, validating its range.

    Raises ``ValueError`` (which every caller already turns into a user-facing
    flash) for a missing, non-numeric or out-of-range value, instead of letting
    a ``KeyError``/``ValueError`` escape as a 500.
    """
    raw = request.form.get(name, "").strip()
    if not raw:
        raise ValueError(f"{name.replace('_', ' ').title()} is required.")
    value = int(raw)
    if not min_value <= value <= max_value:
        raise ValueError(
            f"{name.replace('_', ' ').title()} must be between {min_value} and {max_value}."
        )
    return value


def _parse_vlan_list(raw: str) -> list[int]:
    if not raw.strip():
        return []
    result: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        vid = int(chunk)
        if not _VLAN_MIN <= vid <= _VLAN_MAX:
            raise ValueError(f"VLAN ID {vid} is out of range ({_VLAN_MIN}-{_VLAN_MAX}).")
        result.append(vid)
        if len(result) > _VLAN_MAX:
            raise ValueError("Too many tagged VLANs.")
    return result


@bp.route("/devices/<device_id>/edit")
@login_required
def edit(device_id: str):
    container = _container()
    detail = container.get_device_detail(device_id)
    if detail is None:
        abort(404)
    return render_template("device_edit.html", detail=detail, active="devices")


@bp.route("/devices/<device_id>/vlans", methods=["POST"])
@role_required("admin")
def save_vlan(device_id: str):
    container = _container()
    try:
        container.save_vlan(
            device_id,
            vlan_id=_int_field("vlan_id", min_value=_VLAN_MIN, max_value=_VLAN_MAX),
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
        container.delete_vlan(device_id, vlan_id)
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
        container.save_port(
            device_id,
            number=number,
            name=request.form.get("name", "").strip(),
            enabled=request.form.get("enabled") == "on",
            mode=request.form.get("mode", "access"),
            pvid=_int_field("pvid", min_value=_VLAN_MIN, max_value=_VLAN_MAX),
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
        container.save_ssids(device_id, ssids)
    except DeviceNotFoundError as exc:
        flash(f"Could not save SSIDs: {exc}", "error")
    else:
        flash("SSIDs saved.", "success")
    return redirect(url_for("config.edit", device_id=device_id))


@bp.route("/config/pending")
@login_required
def pending():
    container = _container()
    diff = container.get_config_diff()
    plan = container.get_apply_plan()
    return render_template(
        "pending_changes.html", diff=diff, plan=plan, active="pending"
    )


def _flash_apply_result(result) -> None:
    applied = [r for r in result.results if r.ok]
    failures = result.failures
    if applied:
        flash(f"Configuration applied to {len(applied)} device(s).", "success")
    for failure in failures:
        flash(f"{failure.device_name}: {failure.message}", "error")
    if not applied and not failures:
        flash("Nothing to apply.", "success")


@bp.route("/config/apply", methods=["POST"])
@role_required("admin")
def apply():
    container = _container()
    user = current_user() or {}
    result = container.apply_config(username=user.get("username", ""))
    _flash_apply_result(result)
    return redirect(url_for("config.pending"))


@bp.route("/config/apply/<device_id>", methods=["POST"])
@role_required("admin")
def apply_device(device_id: str):
    container = _container()
    user = current_user() or {}
    result = container.apply_config(
        device_ids=[device_id], username=user.get("username", "")
    )
    _flash_apply_result(result)
    return redirect(url_for("config.pending"))


@bp.route("/config/revert", methods=["POST"])
@role_required("admin")
def revert():
    container = _container()
    reverted = container.revert_changes()
    if reverted:
        flash(f"Reverted {reverted} device(s) to the last applied configuration.", "success")
    else:
        flash("Nothing to revert.", "success")
    return redirect(url_for("config.pending"))


@bp.route("/config/revert/<device_id>", methods=["POST"])
@role_required("admin")
def revert_device(device_id: str):
    container = _container()
    reverted = container.revert_changes(device_ids=[device_id])
    if reverted:
        flash("Device reverted to the last applied configuration.", "success")
    else:
        flash("Nothing to revert.", "success")
    return redirect(url_for("config.pending"))


@bp.route("/config/history")
@login_required
def history():
    container = _container()
    events = container.list_apply_history()
    return render_template("apply_history.html", events=events, active="history")
