"""Typer command line interface."""

import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from sqlalchemy.engine import Engine, make_url

from nginx_perf_agent import __version__
from nginx_perf_agent.analysis import (
    UNCLASSIFIED,
    analyze_paths,
    group_files_by_language,
    load_internal_networks,
    render_markdown,
    resolve_log_files,
)
from nginx_perf_agent.config import Settings, get_settings
from nginx_perf_agent.db import attachment_languages, init_db, table_names
from nginx_perf_agent.db.queries import LANGUAGES
from nginx_perf_agent.log import configure_logging, get_logger
from nginx_perf_agent.mail import (
    ImapClient,
    ImapConfigError,
    ImapError,
    MailProcessor,
    open_processor,
)
from nginx_perf_agent.projects import ProjectConfigError, load_registry

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


def _open_processor(settings: Settings) -> tuple[Engine, MailProcessor]:
    """Open the processor, turning a broken project registry into a clear exit."""
    try:
        return open_processor(settings)
    except ProjectConfigError as exc:
        typer.echo(f"project registry invalid: {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
    typer.echo(f"slow_threshold = {settings.slow_request_threshold}s")
    typer.echo(f"internal_cidrs = {settings.internal_cidrs_file}")
    typer.echo(f"projects_file  = {settings.projects_file}")


@app.command("analyze")
def analyze(
    paths: Annotated[
        list[Path], typer.Argument(help="Log files or directories containing .log files")
    ],
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Report path")
    ] = None,
    top: Annotated[
        int, typer.Option("--top", min=1, help="Rows per ranking table")
    ] = 10,
    slow_threshold: Annotated[
        float | None,
        typer.Option("--slow-threshold", help="Override NPA_SLOW_REQUEST_THRESHOLD"),
    ] = None,
    hours: Annotated[
        float,
        typer.Option(
            "--hours",
            min=0,
            help="Only analyse this many hours before the newest log line; 0 = all",
        ),
    ] = 24,
) -> None:
    """Analyze local Nginx log files and write one Markdown report per language."""
    settings = _settings()
    threshold = slow_threshold or settings.slow_request_threshold
    networks = load_internal_networks(settings.internal_cidrs_file)
    try:
        files = resolve_log_files(paths)
    except FileNotFoundError as exc:
        typer.echo(f"analysis failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    groups = group_files_by_language(
        files, attachment_languages(settings.database_url)
    )
    # EN, KR, JP, CN first; files with no email attribution last.
    labels = [label for label in LANGUAGES if label in groups]
    labels += [label for label in groups if label not in LANGUAGES]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    default_dir = settings.data_dir / "reports"
    for label in labels:
        try:
            result = analyze_paths(
                groups[label],
                slow_threshold=threshold,
                exclude=settings.excluded_patterns,
                internal_networks=networks,
                hours=hours,
            )
        except (FileNotFoundError, ValueError) as exc:
            typer.echo(f"analysis failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        target = _report_path(output, default_dir, stamp, label, len(labels) > 1)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_markdown(result, top=top, label=label), encoding="utf-8"
        )

        report = result.report
        typer.echo(f"report    = {target}")
        typer.echo(f"language  = {label}")
        typer.echo(f"window    = {f'last {hours:g}h' if hours > 0 else 'all lines'}")
        typer.echo(f"files     = {len(result.files)}")
        typer.echo(f"requests  = {report.requests}")
        typer.echo(f"slow      = {len(report.slow_requests)} (>= {threshold}s)")
        typer.echo(
            f"endpoints = {len(report.endpoints)} slow of {report.total_endpoints}"
        )
        typer.echo(f"networks  = {report.internal_networks} internal CIDR(s)")
        if not report.timing_available:
            typer.echo("warning: logs carry no request timing; slow stats unavailable")


def _report_path(
    output: Path | None, default_dir: Path, stamp: str, label: str, multiple: bool
) -> Path:
    """One file per language; an explicit `-o` is suffixed only when split."""
    suffix = "other" if label == UNCLASSIFIED else label.lower()
    if output is None:
        return default_dir / f"nginx-perf-{stamp}-{suffix}.md"
    if not multiple:
        return output
    return output.with_name(f"{output.stem}-{suffix}{output.suffix}")


@app.command("projects")
def list_projects(
    config_file: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Registry YAML (default: NPA_PROJECTS_FILE)"),
    ] = None,
) -> None:
    """Validate the project registry and list registered repositories."""
    settings = _settings()
    path = config_file or settings.projects_file
    try:
        registry = load_registry(path)
    except ProjectConfigError as exc:
        typer.echo(f"project registry invalid: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    enabled = registry.enabled_projects
    typer.echo(f"registry  = {path}")
    typer.echo(f"projects  = {len(registry.projects)} ({len(enabled)} enabled)")
    for project in registry.projects:
        if not project.enabled:
            status = "disabled"
        elif not project.path.is_dir():
            status = "missing"
        else:
            status = "ok"
        typer.echo(
            f"{project.name:<14} {status:<8} {project.path}  "
            f"prefixes={','.join(project.url_prefixes) or '-'} "
            f"markers={','.join(project.subject_markers) or '-'} "
            f"endpoints={len(project.endpoints)}"
        )

    missing = registry.missing_paths()
    if missing:
        typer.echo(
            "missing enabled repositories: " + ", ".join(p.name for p in missing),
            err=True,
        )
        raise typer.Exit(code=1)


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
    engine, processor = _open_processor(settings)
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
    engine, processor = _open_processor(settings)
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
