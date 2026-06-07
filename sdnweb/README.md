# sdnweb — web frontend

The frontend half of [sdn-manager](../README.md): a standalone, server-rendered
Flask app (Jinja2 + HTMX, checked-in CSS). It is a pure presentation tier — it holds
no device connections, database or use-case logic and reaches the [sdnman](../sdnman)
REST backend over HTTP for every read and write.

This package shares no source code with `sdnman`.

## Layout

- `src/sdnweb/app.py` — the Flask application factory.
- `src/sdnweb/api_client.py` — the HTTP client for the sdnman backend.
- `src/sdnweb/viewtypes.py` — web-local view models.
- `src/sdnweb/blueprints` — the page routes.
- `src/sdnweb/templates`, `src/sdnweb/static` — Jinja2 templates and assets.

## Console script

```sh
sdnweb serve            # run the web app dev server (default 0.0.0.0:8080)
```

Production serving uses gunicorn: `gunicorn sdnweb.wsgi:app`. Point it at the backend
with `SDNMAN_API_BASE_URL` (and `SDNMAN_API_TOKEN` when the backend requires a token).

## Develop

```sh
pip install -e .[dev]
# the web test harness boots a real backend in-process, so also install sdnman:
pip install -e ../sdnman
ruff check src tests
pytest
```
