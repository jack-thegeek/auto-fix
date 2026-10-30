# Nginx Performance Agent

Collects Nginx access logs from a mailbox (IMAP), analyzes performance,
maps slow endpoints to Django source code, and produces AI-assisted
diagnosis reports.

> Status: Phase 1 (project foundation) complete. Email monitoring, log
> analysis, source discovery and AI diagnosis are not implemented yet.

## Requirements

- Ubuntu (or any Linux)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
uv sync
```

## Configuration

Settings come from environment variables prefixed with `NPA_`, or from a
`.env` file in the working directory.

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `NPA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `NPA_LOG_JSON` | `false` | Emit one JSON object per log line |
| `NPA_DATA_DIR` | `data` | Downloaded logs, extracted archives, reports |
| `NPA_DATABASE_URL` | `sqlite:///data/nginx_perf.db` | SQLAlchemy database URL |

Invalid values fail fast at startup.

## Usage

```bash
uv run nginx-perf-agent --help
uv run nginx-perf-agent version
uv run nginx-perf-agent config     # validate and show effective settings
uv run nginx-perf-agent init-db    # create database and tables
```

The installed entry point is also available directly:

```bash
uv run python -m nginx_perf_agent version
```

## Project layout

```
src/nginx_perf_agent/
├── __init__.py        version
├── __main__.py        python -m entry point
├── cli.py             Typer commands
├── config.py          Pydantic settings
├── log.py             structlog setup
└── db/
    ├── models.py      SQLAlchemy models (emails, attachments, analysis_tasks)
    └── session.py     engine, init_db, session factory
tests/                 pytest suite
```

## Database

SQLite is initialized with `init-db`. Tables:

- `emails` — monitored emails, unique per `(mailbox, uid)`
- `attachments` — extracted files, `sha256` unique for deduplication
- `analysis_tasks` — analysis jobs and their outcome

## Tests

```bash
uv run pytest
```

## Development rules

See `TODO.md` for the phase plan and `AGENTS.md` for working rules.
Never commit `.env`, API keys or mailbox credentials.
