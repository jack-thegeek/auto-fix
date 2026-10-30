# Nginx Performance Agent

Collects Nginx access logs from a mailbox (IMAP), analyzes performance,
maps slow endpoints to Django source code, and produces AI-assisted
diagnosis reports.

> Status: Phase 2 (email monitoring) complete. Log analysis, source
> discovery and AI diagnosis are not implemented yet.

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
| `NPA_IMAP_HOST` | – | IMAP server hostname |
| `NPA_IMAP_PORT` | `993` | IMAP port |
| `NPA_IMAP_SSL` | `true` | Use IMAPS; set `false` for plain IMAP |
| `NPA_IMAP_USER` | – | Mailbox login |
| `NPA_IMAP_PASSWORD` | – | Mailbox password or app password (masked everywhere) |
| `NPA_IMAP_MAILBOX` | `INBOX` | Mailbox opened read-only |
| `NPA_IMAP_SUBJECT_FILTER` | `Nginx 日志` | Subject substring; case-insensitive |
| `NPA_IMAP_POLL_INTERVAL` | `300` | Seconds between `watch` passes |
| `NPA_IMAP_MAX_RETRIES` | `3` | Retries per IMAP operation before giving up |
| `NPA_IMAP_RETRY_DELAY` | `2` | Backoff base in seconds between retries |
| `NPA_MAX_ATTACHMENT_BYTES` | `268435456` | Reject archives expanding beyond this |

Invalid values fail fast at startup.

## Usage

```bash
uv run nginx-perf-agent --help
uv run nginx-perf-agent version
uv run nginx-perf-agent config     # validate and show effective settings
uv run nginx-perf-agent init-db    # create database and tables
uv run nginx-perf-agent mail-test  # read-only IMAP connectivity check
uv run nginx-perf-agent process    # one polling pass
uv run nginx-perf-agent watch      # poll every NPA_IMAP_POLL_INTERVAL seconds
```

The installed entry point is also available directly:

```bash
uv run python -m nginx_perf_agent version
```

## Email monitoring

`mail-test`, `process` and `watch` open the mailbox **read-only**: emails are
never deleted, moved or marked as read.

- Matching is a case-insensitive substring test on the decoded `Subject`.
- Already-processed emails are skipped by `(mailbox, uid)`; failed ones are
  retried on the next pass.
- Attachments are unpacked (`.gz`, `.zip`, including one nested level).
  Only `.log` and `.txt` leaves inside archives are kept.
- Archive members with absolute paths, `..`, symlinks or an expanded size
  above `NPA_MAX_ATTACHMENT_BYTES` are rejected.
- Stored files are content-addressed: `data/attachments/<sha256[:2]>/<sha256>.<ext>`.
  Identical files are stored and recorded once.

## Project layout

```
src/nginx_perf_agent/
├── __init__.py        version
├── __main__.py        python -m entry point
├── cli.py             Typer commands
├── config.py          Pydantic settings
├── log.py             structlog setup
├── mail/
│   ├── client.py      read-only IMAP client, retries
│   ├── attachments.py archive expansion, safe storage
│   └── service.py     polling pass, status tracking
└── db/
    ├── models.py      SQLAlchemy models (emails, attachments, analysis_tasks)
    └── session.py     engine, init_db, session factory
tests/                 pytest suite (fake IMAP server in `fake_imap.py`)
```

## Database

SQLite is initialized with `init-db`. Tables:

- `emails` — monitored emails, unique per `(mailbox, uid)`, status `processing` / `processed` / `failed`
- `attachments` — extracted files, `sha256` unique for deduplication, stored under `data/attachments`
- `analysis_tasks` — analysis jobs and their outcome

## Tests

```bash
uv run pytest
```

## Development rules

See `TODO.md` for the phase plan and `AGENTS.md` for working rules.
Never commit `.env`, API keys or mailbox credentials.
