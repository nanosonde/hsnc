"""Backup routes: export and import (admin only)."""

from __future__ import annotations

import io
from datetime import UTC, datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from ..api_client import ApiError
from ..auth import login_required, role_required

bp = Blueprint("backup", __name__)


@bp.route("/backup")
@login_required
def index():
    return render_template("backup.html", active="backup")


@bp.route("/backup/export")
@role_required("admin")
def export():
    container = current_app.config["API"]
    data = container.export_backup()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return send_file(
        io.BytesIO(data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"sdnman-backup-{stamp}.zip",
    )


@bp.route("/backup/import", methods=["POST"])
@role_required("admin")
def import_backup():
    container = current_app.config["API"]
    file = request.files.get("archive")
    if file is None or not file.filename:
        flash("No backup file selected.", "error")
        return redirect(url_for("backup.index"))
    try:
        container.import_backup(file.read())
    except (ValueError, KeyError, ApiError) as exc:
        flash(f"Import failed: {exc}", "error")
        return redirect(url_for("backup.index"))
    flash("Backup imported successfully.", "success")
    return redirect(url_for("backup.index"))
