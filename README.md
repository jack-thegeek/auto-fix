# Nginx Performance Agent

Collects Nginx access logs from a mailbox (IMAP), analyzes performance,
maps slow endpoints to Django source code, and produces AI-assisted
diagnosis reports.

> Status: Phase 5 (Weixin report delivery) complete. Django source discovery
> and AI diagnosis are not implemented yet.

## Requirements

- Ubuntu (or any Linux)
- Python 3.14+ (IMAP IDLE support in `imaplib`)
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
| `NPA_IMAP_SUBJECT_FILTER` | `Nginx 日志性能分析` | Subject substring; case-insensitive |
| `NPA_IMAP_POLL_INTERVAL` | `300` | Seconds between `watch` passes |
| `NPA_IMAP_MAX_RETRIES` | `3` | Retries per IMAP operation before giving up |
| `NPA_IMAP_RETRY_DELAY` | `2` | Backoff base in seconds between retries |
| `NPA_MAX_ATTACHMENT_BYTES` | `268435456` | Reject archives expanding beyond this |
| `NPA_ENDPOINT_EXCLUSIONS` | – | Comma-separated path globs left out of endpoint stats, e.g. `/health,/static/*` |
| `NPA_SLOW_REQUEST_THRESHOLD` | `5` | Seconds at or above which a request counts as slow |
| `NPA_INTERNAL_CIDRS_FILE` | `internal_cidrs.txt` | One CIDR per line; requests from these networks count as internal calls |
| `NPA_WEIXIN_TARGET` | `weixin` | Hermes delivery target; `weixin` means the home channel |
| `NPA_HERMES_BIN` | `hermes` | Hermes executable used for delivery |
| `NPA_HERMES_TIMEOUT` | `60` | Seconds before a delivery attempt is abandoned |

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
uv run nginx-perf-agent watch --idle  # wait for server push, poll as fallback
uv run nginx-perf-agent watch --notify  # poll, then report and push new logs
uv run nginx-perf-agent watch --idle --notify  # real-time push + report
uv run nginx-perf-agent analyze data/attachments   # Markdown report of local logs
uv run nginx-perf-agent analyze data/attachments --notify  # also push to Weixin
uv run nginx-perf-agent notify data/reports/nginx-perf-<stamp>-en.md  # re-send a report
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
- Only `.gz` and `.tar` attachments are collected (including `.tar.gz`);
  every other format (`.log`, `.txt`, `.zip`, `.json`, images, …) is ignored.
- Archives are unpacked in memory and kept only when the inner name ends in
  `.log` or `.txt`. Tar members are stored by basename, so `..` or absolute
  paths cannot escape the store; only regular files are read. Payloads
  expanding above `NPA_MAX_ATTACHMENT_BYTES` (the budget is shared across the
  members of one tar), nested too deeply or corrupt are rejected.
- Stored files are content-addressed: `data/attachments/<sha256[:2]>/<sha256>.<ext>`.
  Identical files are stored and recorded once.
- `process --notify` and `watch --notify` close the loop: when a pass stored a
  new log file, the reports are regenerated and pushed to Weixin. A pass with
  no new attachment, or only duplicate content, pushes nothing.
- `watch --idle` holds an IMAP IDLE connection instead of only polling: the
  server pushes `EXISTS` as soon as mail arrives, so the pass starts within
  seconds. The wait expires after `NPA_IMAP_POLL_INTERVAL` (capped at 29 min)
  and a normal scan still runs as a fallback. The server must advertise
  `IDLE`; otherwise `watch --idle` exits `2` and says to drop the flag.

## Project layout

```
src/nginx_perf_agent/
├── __init__.py        version
├── __main__.py        python -m entry point
├── cli.py             Typer commands
├── config.py          Pydantic settings
├── log.py             structlog setup
├── notify.py          Weixin delivery through the Hermes gateway
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
    ├── queries.py     attachment sha256 -> site marker (EN/KR/JP/CN)
    └── session.py     engine, init_db, session factory
tests/                 pytest suite (fake IMAP server in `fake_imap.py`)
deploy/                systemd user unit for `watch --idle --notify`
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
  endpoint. Dynamic segments collapse to `{id}` (digits, UUID, hex, email),
  `{code}` (`VB260101-1001abc`), `{accession}` (`NM_000546.6`, `ORF123`) and
  `{vector}` (`pLV_2gRNA`); anything else stays literal so endpoints are
  never merged on a guess.
- Per slow endpoint: total requests, slow requests, slow ratio, maximum
  response time, average slow response time, first/last slow timestamp,
  status distribution and upstream times when present.
- Ranking mirrors the proxy-log report: priority tier (高/中/低; fewer than
  3 requests or 2 slow requests is always 低, under 50 requests is 中),
  then impact (average slow seconds × slow ratio), then slow count.
- Internal call ratio: the first `X-Forwarded-For` address (or
  `$remote_addr`) is tested against `NPA_INTERNAL_CIDRS_FILE`; the column
  shows `-` when no file is present.
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
uv run nginx-perf-agent analyze data/attachments --hours 0   # every line
```

Only the last 24 hours are analysed by default. The window ends at the newest
parsed timestamp rather than at wall-clock now, so old attachments still
produce a report; `--hours 0` disables the window.

Reports are split per site: EN, KR, JP and CN are analysed and written
separately, never merged. The site comes from the marker in the subject of the
email that carried the attachment (`emails.subject`, looked up by the
attachment's sha256 in the database); files with no email attribution go to a
`未分类` report. Each language gets its own 24h window. Output names are
`nginx-perf-<timestamp>-<en|kr|jp|cn|other>.md`; with `-o report.md` and more
than one site the suffix is inserted (`report-en.md`, `report-cn.md`), while a
single site writes exactly the given path.

The report is written in Chinese, headed `# 慢请求统计（EN）` (or KR/JP/CN),
and opens with the slow-request table used by the proxy-log report:

| 接口 | 优先级 | 慢请求/总请求 | 慢率 | 内部调用占比 | 慢请求平均时间 | 最慢用时 |

The header lists generation time, log time span and the overall slow share
(slow requests / total requests). Sections, in order:

1. `## Top N 慢请求`: slow endpoint ranking (priority → impact → slow count).
2. Slow query parameters: one row per redacted parameter combination.

An upstream column appears only when a log actually records
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

## Run as a service

`deploy/nginx-perf-agent.service` runs `watch --idle --notify` as a systemd
user service, so it keeps running after logout and restarts on failure.

```bash
mkdir -p ~/.config/systemd/user
cp deploy/nginx-perf-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now nginx-perf-agent
loginctl enable-linger $USER   # start at boot without logging in
```

- The unit assumes the checkout is at `~/workplace/auto-fix`; adjust
  `WorkingDirectory` and `ExecStart` if it lives elsewhere.
- `PATH` includes `~/.local/bin` because `hermes` is installed there.
- Logs go to the journal: `journalctl --user -u nginx-perf-agent -f`.
- Stop it with `systemctl --user disable --now nginx-perf-agent`.
- `Restart=always` with a 10 second delay; a broken `.env` shows up as a
  restart loop in the journal.

## Weixin delivery

Reports can be pushed to WeChat as text messages through the Hermes gateway.
Hermes owns the WeChat credentials; this project stores none.

```bash
uv run nginx-perf-agent analyze data/attachments --notify
uv run nginx-perf-agent notify data/reports/nginx-perf-20261106-120000-en.md
uv run nginx-perf-agent notify report.md --target weixin:o9cq...@im.wechat
```

- Delivery shells out to `hermes send --to <target> --file -` and writes the
  report body to stdin, so no shell quoting or credential handling is needed.
- `NPA_WEIXIN_TARGET` defaults to `weixin` (the configured home channel);
  `notify --target` overrides it for one run.
- Long reports are not truncated here: the Weixin adapter splits them into
  chunks of at most 2000 characters at Markdown boundaries.
- A non-zero exit, missing `hermes` binary or timeout is reported as a
  failure and logged; `analyze` still writes every report, then exits `1`.
- `hermes send --list` shows the configured targets.

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
