"""REST API blueprint: the single HTTP surface the frontend calls.

Every route is thin: parse the request, call the matching application use case on
the broker-grade container, and serialize the result with :func:`to_jsonable`.
Raised use-case exceptions are turned into a stable error envelope by the app's
error handler (see :mod:`sdnman.backend.app`), so the frontend can re-raise the
same-named exception and flash identical text.
"""

from __future__ import annotations

from flask import Blueprint, Response, abort, current_app, jsonify, request

from ..application.wire import to_jsonable

bp = Blueprint("api", __name__, url_prefix="/api")


def _container():
    return current_app.config["CONTAINER"]


def _ok(obj, status: int = 200) -> Response:
    return current_app.response_class(
        response=jsonify(to_jsonable(obj)).get_data(),
        status=status,
        mimetype="application/json",
    )


def _body() -> dict:
    return request.get_json(silent=True) or {}


# -- health -----------------------------------------------------------------


@bp.get("/health")
def health() -> Response:
    pool = current_app.config.get("POOL")
    connections = pool.snapshot() if pool is not None else []
    settings = current_app.config["SETTINGS"]
    return jsonify(
        {"status": "ok", "mock": settings.use_mock_devices, "connections": connections}
    )


# -- auth -------------------------------------------------------------------


@bp.post("/auth/verify")
def auth_verify() -> Response:
    data = _body()
    result = _container().authenticate_user.execute(
        data.get("username", ""), data.get("password", "")
    )
    if result is None:
        return _ok(
            {"error": {"type": "Unauthorized", "message": "Invalid username or password."}},
            status=401,
        )
    return _ok(result)


# -- dashboard / reads ------------------------------------------------------


@bp.get("/dashboard")
def dashboard() -> Response:
    return _ok(_container().get_dashboard_summary.execute())


@bp.get("/config/diff")
def config_diff() -> Response:
    return _ok(_container().get_config_diff.execute())


@bp.get("/config/plan")
def config_plan() -> Response:
    return _ok(_container().plan_apply.execute())


@bp.get("/devices")
def devices() -> Response:
    return _ok(_container().list_devices.execute())


@bp.get("/devices/<device_id>")
def device_detail(device_id: str) -> Response:
    detail = _container().get_device_detail.execute(device_id)
    if detail is None:
        abort(404)
    return _ok(detail)


@bp.get("/clients")
def clients() -> Response:
    def _int(name: str, default: int) -> int:
        try:
            value = request.args.get(name)
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    paged = _container().list_clients.execute(
        search=request.args.get("search", ""),
        page=_int("page", 1),
        page_size=_int("page_size", 10),
    )
    return _ok(paged)


@bp.get("/topology")
def topology() -> Response:
    return _ok(_container().get_topology.execute())


@bp.get("/history")
def history() -> Response:
    def _int(name: str, default: int) -> int:
        try:
            value = request.args.get(name)
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    return _ok(_container().list_apply_history.execute(limit=_int("limit", 50)))


# -- config edits -----------------------------------------------------------


@bp.post("/config/devices/<device_id>/vlans")
def save_vlan(device_id: str) -> Response:
    data = _body()
    _container().save_vlan.execute(
        device_id,
        vlan_id=int(data["vlan_id"]),
        name=(data.get("name") or "").strip(),
        subnet=(data.get("subnet") or "").strip(),
    )
    return "", 204


@bp.post("/config/devices/<device_id>/vlans/<int:vlan_id>/delete")
def delete_vlan(device_id: str, vlan_id: int) -> Response:
    _container().delete_vlan.execute(device_id, vlan_id)
    return "", 204


@bp.post("/config/devices/<device_id>/ports/<int:number>")
def save_port(device_id: str, number: int) -> Response:
    data = _body()
    _container().save_port.execute(
        device_id,
        number=number,
        name=(data.get("name") or "").strip(),
        enabled=bool(data.get("enabled")),
        mode=data.get("mode", "access"),
        pvid=int(data["pvid"]),
        tagged_vlans=[int(v) for v in data.get("tagged_vlans", [])],
    )
    return "", 204


@bp.post("/config/devices/<device_id>/ssids")
def save_ssids(device_id: str) -> Response:
    data = _body()
    _container().save_ssids.execute(device_id, list(data.get("ssids", [])))
    return "", 204


# -- apply / revert / sync --------------------------------------------------


@bp.post("/config/apply")
def apply_config() -> Response:
    data = _body()
    device_ids = data.get("device_ids")
    result = _container().apply_config.execute(
        device_ids=device_ids, username=data.get("username", "")
    )
    return _ok(result)


@bp.post("/config/revert")
def revert_config() -> Response:
    data = _body()
    reverted = _container().revert_changes.execute(device_ids=data.get("device_ids"))
    return _ok({"reverted": reverted})


@bp.post("/devices/sync")
def sync_devices() -> Response:
    data = _body()
    result = _container().sync_device_config.execute(
        device_ids=data.get("device_ids"), username=data.get("username", "")
    )
    return _ok(result)


@bp.post("/devices/<device_id>/delete")
def delete_device(device_id: str) -> Response:
    detail = _container().get_device_detail.execute(device_id)
    if detail is None:
        abort(404)
    _container().delete_device.execute(device_id)
    return "", 204


# -- backup -----------------------------------------------------------------


@bp.get("/backup/export")
def backup_export() -> Response:
    data = _container().export_backup.execute()
    return Response(data, mimetype="application/zip")


@bp.post("/backup/import")
def backup_import() -> Response:
    _container().import_backup.execute(request.get_data())
    return "", 204
