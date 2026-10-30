"""Typer command line interface."""

import time
from datetime import datetime

import typer
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from nginx_perf_agent import __version__
from nginx_perf_agent.config import Settings, get_settings
from nginx_perf_agent.db import init_db, table_names
from nginx_perf_agent.log import configure_logging, get_logger
from nginx_perf_agent.mail import ImapClient, ImapConfigError, ImapError, open_processor

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


def _require_imap(settings: Settings) -> None:
    """Fail early with a clear message when IMAP credentials are missing."""
    if not (settings.imap_host and settings.imap_user and settings.imap_password):
        typer.echo(
            "IMAP is not configured: set NPA_IMAP_HOST, NPA_IMAP_USER and NPA_IMAP_PASSWORD",
            err=True,
        )
        raise typer.Exit(code=2)


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
    typer.echo(f"imap_host      = {settings.imap_host or '(unset)'}")
    typer.echo(f"imap_port      = {settings.imap_port}")
    typer.echo(f"imap_ssl       = {settings.imap_ssl}")
    typer.echo(f"imap_user      = {settings.imap_user or '(unset)'}")
    typer.echo(f"imap_password  = {'***' if settings.imap_password else '(unset)'}")
    typer.echo(f"imap_mailbox   = {settings.imap_mailbox}")
    typer.echo(f"imap_subject   = {settings.imap_subject_filter}")
    typer.echo(f"imap_interval  = {settings.imap_poll_interval}s")
    typer.echo(f"exclusions     = {', '.join(settings.excluded_patterns) or '(none)'}")


@app.command("init-db")
def init_db_command() -> None:
    """Create the SQLite database and all tables."""
    settings = _settings()
    log = get_logger(__name__)
    engine = init_db(settings.database_url)
    tables = table_names(engine)
    log.info("database_initialized", tables=tables)
    typer.echo(f"tables: {', '.join(tables)}")


@app.command("mail-test")
def mail_test() -> None:
    """Connect to the mailbox read-only and report its status."""
    settings = _settings()
    try:
        with ImapClient(settings) as client:
            status = client.status()
    except (ImapConfigError, ImapError, OSError) as exc:
        typer.echo(f"mail test failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"mailbox   = {status.mailbox}")
    typer.echo(f"messages  = {status.messages}")
    typer.echo(f"matching  = {status.matching} (newest {min(status.messages, 200)})")
    typer.echo(f"last_uid  = {status.last_uid or '(none)'}")
    typer.echo(f"filter    = {settings.imap_subject_filter}")


@app.command("process")
def process_emails() -> None:
    """Run one polling pass: download attachments of matching emails."""
    settings = _settings()
    _require_imap(settings)
    engine, processor = open_processor(settings)
    try:
        result = processor.process_once()
    except (ImapError, OSError) as exc:
        typer.echo(f"processing failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()
    typer.echo(result.summary())
    if result.failed:
        raise typer.Exit(code=1)


@app.command("watch")
def watch() -> None:
    """Poll the mailbox continuously; stop with Ctrl-C."""
    settings = _settings()
    _require_imap(settings)
    engine, processor = open_processor(settings)
    interval = settings.imap_poll_interval
    typer.echo(
        f"watching {settings.imap_mailbox} every {interval}s "
        f"for {settings.imap_subject_filter!r}; press Ctrl-C to stop"
    )
    failures = 0
    try:
        while True:
            try:
                result = processor.process_once()
                failures = 0
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                typer.echo(f"{stamp} {result.summary()}")
            except (ImapError, OSError) as exc:
                failures += 1
                typer.echo(f"poll failed (consecutive={failures}): {exc}", err=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("stopped")
    finally:
        engine.dispose()


def run() -> None:
    app()


if __name__ == "__main__":
    run()
