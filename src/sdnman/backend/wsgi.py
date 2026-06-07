"""WSGI entrypoint for the REST backend (``gunicorn sdnman.backend.wsgi:app``).

Builds the API app and starts the background runtime (connection pool + poll
loop). Run with a single gunicorn worker and without ``--preload`` so the worker
owns the warm SSH runners and the poll thread.
"""

from __future__ import annotations

import atexit

from .app import create_api_app
from .runtime import BackendRuntime

app = create_api_app()

_runtime = BackendRuntime(app.config["CONTAINER"])
app.config["POOL"] = _runtime.pool
_runtime.start()
atexit.register(_runtime.stop)
