"""Backend command-line interface: run the REST API server, poll devices, manage backups."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from ..container import Container
from .settings import settings_from_env

_log = logging.getLogger("hsnc.backend.cli")


@click.group()
def main() -> None:
    """hsnc backend control commands."""


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8081, show_default=True, type=int)
def api(host: str, port: int) -> None:
    """Run the REST backend dev server (use gunicorn in production).

    Owns all device I/O: starts the connection pool, reads the baseline on boot
    (when enabled) and runs the poll loop, then serves the /api surface.
    """

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from .app import create_api_app
    from .runtime import BackendRuntime

    app = create_api_app()
    runtime = BackendRuntime(app.config["CONTAINER"])
    app.config["POOL"] = runtime.pool
    runtime.start()
    try:
        app.run(host=host, port=port)
    finally:
        runtime.stop()


@main.command()
def poll() -> None:
    """Run a single device poll sweep and exit (one-shot)."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    container = Container(settings_from_env())
    try:
        count = container.poll_device_state.execute()
        _log.info("Polled %d devices", count)
    finally:
        container.close()


@main.group()
def backup() -> None:
    """Export or import controller backups."""


@backup.command("export")
@click.argument("path", type=click.Path(dir_okay=False, writable=True))
def backup_export(path: str) -> None:
    """Export config + runtime history to a ZIP archive at PATH."""

    container = Container(settings_from_env())
    try:
        data = container.export_backup.execute()
        Path(path).write_bytes(data)
        click.echo(f"Backup written to {path} ({len(data)} bytes)")
    finally:
        container.close()


@backup.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def backup_import(path: str) -> None:
    """Restore config + runtime history from a ZIP archive at PATH."""

    container = Container(settings_from_env())
    try:
        container.import_backup.execute(Path(path).read_bytes())
    except (ValueError, KeyError) as exc:
        click.echo(f"Import failed: {exc}", err=True)
        sys.exit(1)
    finally:
        container.close()
    click.echo("Backup imported successfully.")


if __name__ == "__main__":
    main()
