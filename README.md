# Nginx Performance Agent

Collects Nginx access logs from a mailbox (IMAP), analyzes performance,
maps slow endpoints to Django source code, and produces AI-assisted
diagnosis reports.

> Status: Phase 2 (email monitoring) and 3.1 (log parsing) complete.
> Statistics, reports, source discovery and AI diagnosis are not implemented yet.

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
| `NPA_ENDPOINT_EXCLUSIONS` | – | Comma-separated path globs left out of endpoint stats, e.g. `/health,/static/*` |

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
- Only `.gz` attachments are collected; every other format (`.log`, `.txt`,
  `.zip`, `.json`, images, …) is ignored.
- Each `.gz` attachment is decompressed in memory and kept only when the
  inner name ends in `.log` or `.txt`. Payloads expanding above
  `NPA_MAX_ATTACHMENT_BYTES`, nested too deeply or corrupt are rejected.
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
├── analysis/
│   └── parser.py      streaming Nginx access-log parser
├── mail/
│   ├── client.py      read-only IMAP client, retries
│   ├── attachments.py archive expansion, safe storage
│   └── service.py     polling pass, status tracking
└── db/
    ├── models.py      SQLAlchemy models (emails, attachments, analysis_tasks)
    └── session.py     engine, init_db, session factory
tests/                 pytest suite (fake IMAP server in `fake_imap.py`)
```

## Log parsing

`nginx_perf_agent.analysis.LogParser` streams a log file line by line:

- Layouts: standard combined, extended combined (`$request_time`, optional
  `$upstream_response_time`) and this deployment's variant that logs
  `Forwarded for $http_x_forwarded_for` after `$remote_addr`.
- Extracted fields: method, normalized path (query and fragment removed),
  protocol, status, body bytes, request time, upstream time, user,
  forwarded-for list, referer and user agent.
- Endpoint key: `"<METHOD> <path>"`, so the same path under different
  methods stays separate.
- Malformed lines are counted in `parser.stats`, logged at `DEBUG` and
  skipped; missing values stay `None` and are never estimated.
- Exclusions come from `NPA_ENDPOINT_EXCLUSIONS` (path globs).

The production format does not log `$upstream_response_time`, so
`upstream_time` is `None` for every entry from this source.

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
