"""Clients route with HTMX-driven search and pagination."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template, request

from ..auth import login_required

bp = Blueprint("clients", __name__)


def _parse_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


# Bound pagination so a crafted request cannot ask the backend to materialise an
# unbounded result set (memory-exhaustion DoS).
_MAX_PAGE_SIZE = 100


@bp.route("/clients")
@login_required
def index():
    container = current_app.config["API"]
    search = request.args.get("search", "")
    page = max(1, _parse_int(request.args.get("page"), 1))
    page_size = _parse_int(request.args.get("page_size"), 10)
    page_size = max(1, min(page_size, _MAX_PAGE_SIZE))
    paged = container.list_clients(search=search, page=page, page_size=page_size)

    # HTMX requests carry an "HX-Request" header. For those we return just the
    # table fragment so HTMX can swap it into #client-table; a normal browser
    # navigation gets the full page. Both render from the same data.
    template = "partials/client_table.html" if request.headers.get("HX-Request") else "clients.html"
    return render_template(template, paged=paged, search=search, active="clients")
