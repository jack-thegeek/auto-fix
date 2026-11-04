# Nginx Performance Agent

Collects Nginx access logs from a mailbox (IMAP), analyzes performance,
maps slow endpoints to Django source code, and produces AI-assisted
diagnosis reports.

> Status: Phase 4.1 (project registry) complete. Django source discovery
> and AI diagnosis are not implemented yet.

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
| `NPA_PROJECTS_FILE` | `projects.yaml` | YAML registry of source repositories |
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
| `NPA_SLOW_REQUEST_THRESHOLD` | `5` | Seconds at or above which a request counts as slow |

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
uv run nginx-perf-agent analyze data/attachments   # Markdown report of local logs
uv run nginx-perf-agent projects   # validate and list registered repositories
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
- The subject marker (`KR`/`EN`/`JP` or `CN`) is stored as `emails.project`;
  no marker or two markers leave it empty and log a warning rather than
  guessing. An invalid registry makes `process`/`watch` fail; a missing file
  disables attribution.
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
│   ├── parser.py      streaming Nginx access-log parser
│   ├── stats.py       slow-request and endpoint statistics
│   └── report.py      Markdown report and local analysis driver
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

## Performance statistics

`nginx_perf_agent.analysis.PerformanceStats` consumes parsed entries one at a
time and produces a `PerformanceReport`:

- Slow requests: `request_time >= NPA_SLOW_REQUEST_THRESHOLD` (default 5s).
  Each record keeps timestamp, method, normalized path, original URL,
  response time, status and upstream time when logged.
- Endpoints are keyed by `"<METHOD> <path>"`; query strings never split an
  endpoint. Numeric and UUID path segments collapse to `{id}`; any other
  segment stays literal so endpoints are never merged on a guess.
- Per slow endpoint: total requests, slow requests, slow ratio, maximum
  response time, average slow response time, first/last slow timestamp,
  status distribution and upstream times when present. Sorted by slow count,
  then maximum response time.
- Query summary: distinct (redacted) parameter combinations of slow requests
  only, with counts and maximum response time.
- Entries without `$request_time` are counted in `requests_missing_timing`
  and can never be classified as slow; `timing_available` is `False` when the
  layout carries no timing at all.

```python
from nginx_perf_agent.analysis import LogParser, PerformanceStats

parser, stats = LogParser(), PerformanceStats()
stats.add_many(parser.parse_file("access.log"))
report = stats.report()
```

## Reports

`analyze` reads local `.log` files (directories are expanded to their `.log`
files) and writes a Markdown report, by default to
`data/reports/nginx-perf-<timestamp>.md`:

```bash
uv run nginx-perf-agent analyze data/attachments --top 20
uv run nginx-perf-agent analyze one.log two.log -o report.md
uv run nginx-perf-agent analyze data/attachments --slow-threshold 3
```

Sections, in order:

1. Log file metadata: path, size, lines, parsed, malformed, excluded.
2. Overall statistics: requests, endpoints, timed/missing-timing counts, slow
   requests, error count, and latency min/mean/p50/p90/p95/p99/max.
3. Slow endpoint ranking, sorted by slow count then maximum response time.
4. Error analysis: 4xx/5xx distribution and the endpoints producing them.
5. Slow query parameters: one row per redacted parameter combination.

Percentiles use the nearest-rank method over every observed `$request_time`,
so they are exact rather than interpolated. When a log layout has no timing
field the report says so explicitly and omits latency percentiles instead of
guessing. Upstream times show `n/a` because this deployment does not log
`$upstream_response_time`.

## Projects

`projects` validates the registry and prints every repository with its status.
The registry is a YAML file (`NPA_PROJECTS_FILE`, default `projects.yaml`);
copy `projects.example.yaml` and adjust the checkout paths:

```yaml
projects:
  - name: vb-en
    path: /home/jackson/workplace/vb-en
    enabled: true
    url_prefixes: ["/en/"]        # longest prefix wins
    endpoints: ["GET /api/v1/orders/"]  # manual mapping, overrides prefixes
    subject_markers: [KR, EN, JP]       # email subjects carrying these logs
```

- `name` is required and unique; `path` must exist for enabled projects.
- `enabled: false` keeps an entry registered but out of matching.
- `endpoints` entries are normalized endpoint paths, optionally prefixed with
  an HTTP method; a bare path claims every method.
- `url_prefixes` map by longest matching prefix after manual mappings.
- `subject_markers` tie incoming emails to a project: the marker must appear
  as a standalone token in the subject (`EN` matches `... EN Nginx 日志 ...`
  but not `ENVIRONMENT`). Markers must be unique across projects, so `KR`,
  `EN` and `JP` all map to `vb-en` while `CN` maps to `vb-cn`.
- Unknown keys and duplicate names or endpoint mappings are rejected.
- `projects` exits `1` when an enabled checkout is missing or the file is
  invalid.

The registry is not needed by `analyze`; phases 4.2+ use it to locate source.

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
