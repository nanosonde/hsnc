"""Command-line interface: run the dev server, the poller and manage backups."""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path

import click

from ..infrastructure.container import Container
from .app import create_app
from .settings import settings_from_env

_log = logging.getLogger("sdnman.poller")


@click.group()
def main() -> None:
    """sdn-manager control commands."""


@main.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8080, show_default=True, type=int)
@click.option("--debug/--no-debug", default=False)
def serve(host: str, port: int, debug: bool) -> None:
    """Run the development server (use gunicorn in production)."""

    app = create_app()
    app.run(host=host, port=port, debug=debug)


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


@main.command("poll-daemon")
def poll_daemon() -> None:
    """Continuously poll devices on the configured interval (the poller process)."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = settings_from_env()
    container = Container(settings)
    interval = settings.poll_interval_seconds

    stopping = False

    def _stop(signum, _frame):  # type: ignore[no-untyped-def]
        nonlocal stopping
        stopping = True
        _log.info("Received signal %s, shutting down poller", signum)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    _log.info("Poller started (interval=%ss, retention=%sd)", interval, settings.retention_days)
    try:
        while not stopping:
            try:
                count = container.poll_device_state.execute()
                _log.info("Polled %d devices", count)
            except Exception:  # noqa: BLE001 - never let one sweep kill the loop
                _log.exception("Poll sweep failed")
            # Sleep in short slices so signals are handled promptly.
            slept = 0.0
            while slept < interval and not stopping:
                time.sleep(min(1.0, interval - slept))
                slept += 1.0
    finally:
        container.close()
        _log.info("Poller stopped")


@main.group()
def backup() -> None:
    """Export or import controller backups."""


@backup.command("export")
@click.argument("path", type=click.Path(dir_okay=False, writable=True))
def backup_export(path: str) -> None:
    """Export config + runtime history to a ZIP archive at PATH."""

    container = create_app().config["CONTAINER"]
    data = container.export_backup.execute()
    Path(path).write_bytes(data)
    click.echo(f"Backup written to {path} ({len(data)} bytes)")


@backup.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def backup_import(path: str) -> None:
    """Restore config + runtime history from a ZIP archive at PATH."""

    container = create_app().config["CONTAINER"]
    try:
        container.import_backup.execute(Path(path).read_bytes())
    except (ValueError, KeyError) as exc:
        click.echo(f"Import failed: {exc}", err=True)
        sys.exit(1)
    click.echo("Backup imported successfully.")


if __name__ == "__main__":
    main()
