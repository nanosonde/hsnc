"""Command-line interface: run the dev server, the broker and manage backups."""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path

import click

from ..infrastructure.broker.service import BrokerService
from ..infrastructure.container import Container
from .app import create_app
from .settings import settings_from_env

_log = logging.getLogger("sdnman.cli")


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
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8081, show_default=True, type=int)
def api(host: str, port: int) -> None:
    """Run the REST backend dev server (use gunicorn in production).

    Owns all device I/O: starts the connection pool, reads the baseline on boot
    (when enabled) and runs the poll loop, then serves the /api surface.
    """

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from ..backend.app import create_api_app
    from ..backend.runtime import BackendRuntime

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
    """Run a single device poll sweep and exit (one-shot, broker profile)."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    container = Container(settings_from_env(), profile="broker")
    try:
        count = container.poll_device_state.execute()
        _log.info("Polled %d devices", count)
    finally:
        container.close()


@main.command()
def broker() -> None:
    """Run the Device Broker: own all device connections and serve the IPC API."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = settings_from_env()
    service = BrokerService(settings)

    def _stop(signum, _frame):  # type: ignore[no-untyped-def]
        _log.info("Received signal %s, shutting down broker", signum)
        service.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    service.start()
    try:
        service.run()
    finally:
        service.stop()


@main.command()
def baseline() -> None:
    """Read the live configuration from all devices and record it as the baseline.

    Runs through the broker (web profile), so the broker must be up. No-op when
    SDNMAN_BASELINE_ON_START is disabled.
    """

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = settings_from_env()
    if not settings.baseline_on_start:
        _log.info("Baseline disabled (SDNMAN_BASELINE_ON_START=0); skipping")
        return
    if not _wait_for_broker(settings.broker_socket):
        _log.warning("Broker not reachable; skipping baseline read")
        return
    container = Container(settings, profile="web")
    try:
        result = container.read_baseline.execute()
        seeded = container.seed_desired_from_current()
        _log.info(
            "Baseline: read %d device(s), %d failure(s), changed=%s, seeded_desired=%s",
            len(result.read),
            len(result.failures),
            result.changed,
            seeded,
        )
    finally:
        container.close()


def _wait_for_broker(socket_path, attempts: int = 30, delay: float = 1.0) -> bool:
    """Poll the broker's health endpoint until it answers or attempts run out."""
    from ..infrastructure.broker.client import BrokerClient, BrokerUnavailableError

    client = BrokerClient(socket_path, timeout=5.0)
    for _ in range(attempts):
        try:
            client.health()
            return True
        except BrokerUnavailableError:
            time.sleep(delay)
    return False




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
