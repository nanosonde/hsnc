"""Command-line interface: run the dev server and manage backups."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .app import create_app


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
