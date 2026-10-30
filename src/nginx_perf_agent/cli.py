"""Typer command line interface."""

import typer
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from nginx_perf_agent import __version__
from nginx_perf_agent.config import Settings, get_settings
from nginx_perf_agent.db import init_db, table_names
from nginx_perf_agent.log import configure_logging, get_logger

app = typer.Typer(
    help="Nginx performance analyzer: collect logs by email, analyze them, diagnose code.",
    no_args_is_help=True,
    add_completion=False,
)


def _settings() -> Settings:
    try:
        settings = get_settings()
    except ValidationError as exc:
        typer.echo(f"invalid configuration:\n{exc}", err=True)
        raise typer.Exit(code=2) from exc
    configure_logging(settings.log_level, settings.log_json)
    return settings


@app.callback()
def main() -> None:
    """Nginx performance analyzer."""


@app.command()
def version() -> None:
    """Print the application version."""
    typer.echo(__version__)


@app.command("config")
def show_config() -> None:
    """Validate the configuration and print the effective values."""
    settings = _settings()
    typer.echo(f"log_level      = {settings.log_level}")
    typer.echo(f"log_json       = {settings.log_json}")
    typer.echo(f"data_dir       = {settings.data_dir}")
    typer.echo(
        f"database_url   = {make_url(settings.database_url).render_as_string(hide_password=True)}"
    )


@app.command("init-db")
def init_db_command() -> None:
    """Create the SQLite database and all tables."""
    settings = _settings()
    log = get_logger(__name__)
    engine = init_db(settings.database_url)
    tables = table_names(engine)
    log.info("database_initialized", tables=tables)
    typer.echo(f"tables: {', '.join(tables)}")


def run() -> None:
    app()


if __name__ == "__main__":
    run()
