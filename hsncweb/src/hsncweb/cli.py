"""Web frontend command-line interface: run the dev server."""

from __future__ import annotations

import click

from .app import create_app


@click.group()
def main() -> None:
    """hsnc web frontend control commands."""


@main.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8080, show_default=True, type=int)
@click.option("--debug/--no-debug", default=False)
def serve(host: str, port: int, debug: bool) -> None:
    """Run the development server (use gunicorn in production)."""

    app = create_app()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()

