# hsncweb — web frontend

The frontend half of [hsnc](../README.md): a standalone, server-rendered
Flask app (Jinja2 + HTMX, checked-in CSS). It is a pure presentation tier — it holds
no device connections, database or use-case logic and reaches the [hsnc](../hsnc)
REST backend over HTTP for every read and write.

This package shares no source code with `hsnc`.

## Layout

- `src/hsncweb/app.py` — the Flask application factory.
- `src/hsncweb/api_client.py` — the HTTP client for the hsnc backend.
- `src/hsncweb/viewtypes.py` — web-local view models.
- `src/hsncweb/blueprints` — the page routes.
- `src/hsncweb/templates`, `src/hsncweb/static` — Jinja2 templates and assets.

## Console script

```sh
hsnc-web serve            # run the web app dev server (default 0.0.0.0:8080)
```

Production serving uses gunicorn: `gunicorn hsncweb.wsgi:app`. Point it at the backend
with `HSNC_API_BASE_URL` (and `HSNC_API_TOKEN` when the backend requires a token).

## Develop

```sh
pip install -e .[dev]
# the web test harness boots a real backend in-process, so also install hsnc:
pip install -e ../hsnc
ruff check src tests
pytest
```
