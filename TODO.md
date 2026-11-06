# Nginx Performance Agent — TODO

> Project: Nginx Performance Analyzer  
> Stack: Ubuntu + Python 3.12+ + uv + SQLite + Polars + OpenAI API  
> Rule: Complete tasks incrementally. Mark `[x]` immediately after successful implementation and verification.

## Progress

- Total: 5 phases
- Rule: Never mark a task complete without verification.
- Update this file after every implementation session.
- Do not skip unfinished tasks or silently mark partially implemented features as complete.

---

## 1. Project Foundation

- [x] 1.1 Initialize Python project using `uv`.
- [x] 1.2 Configure Python version and dependencies in `pyproject.toml`.
- [x] 1.3 Create the modular project directory structure.
- [x] 1.4 Implement Pydantic-based configuration management.
- [x] 1.5 Create `.env.example` and `.gitignore`.
- [x] 1.6 Implement SQLite database initialization.
- [x] 1.7 Define SQLAlchemy database models.
- [x] 1.8 Implement Typer CLI entry point.
- [x] 1.9 Configure structured logging.
- [x] 1.10 Add initial unit tests.
- [x] 1.11 Write basic README documentation.

**Acceptance criteria:**
- Application starts successfully.
- Configuration validation works.
- SQLite initializes correctly.
- CLI commands are available.
- All initial tests pass.

## 2. Email Monitoring (IMAP)

- [x] 2.1 Implement IMAP connection with SSL support.
- [x] 2.2 Implement mailbox configuration.
- [x] 2.3 Implement subject matching for `Nginx 日志性能分析`.
- [x] 2.4 Implement IMAP UID-based email identification.
- [x] 2.5 Implement attachment extraction.
- [x] 2.6 Collect only `.gz` and `.tar` attachments; every other format is ignored.
- [x] 2.7 Decompress `.gz` and unpack `.tar` attachments to plain `.log` files.
- [x] 2.8 Safe decompression (size limit, nesting depth, corrupt archives).
- [x] 2.9 Implement attachment SHA256 deduplication.
- [x] 2.10 Implement safe archive extraction.
- [x] 2.11 Implement email processing status tracking.
- [x] 2.12 Implement retry and reconnect mechanisms.
- [x] 2.13 Implement configurable polling interval.
- [x] 2.14 Implement `mail-test` CLI command.
- [x] 2.15 Implement `watch` and `process` CLI commands.
- [x] 2.16 Add email integration tests using mocked IMAP responses.

**Acceptance criteria:**
- Matching emails are detected automatically.
- Attachments are downloaded correctly.
- Duplicate emails and attachments are not processed repeatedly.
- Failed tasks can be retried.
- Original emails are never deleted.

## 3. Nginx Log Parsing and Analysis

### 3.1 Log Parsing

- [x] 3.1.1 Implement standard Nginx combined log parser.
- [x] 3.1.2 Support extended combined format.
- [x] 3.1.3 Extract HTTP method, URL, status and response size.
- [x] 3.1.4 Extract request time when available.
- [x] 3.1.5 Extract upstream response time when available.
- [x] 3.1.6 Normalize URL paths and remove query parameters.
- [x] 3.1.7 Group endpoints by HTTP method.
- [x] 3.1.8 Handle malformed log entries.
- [x] 3.1.9 Support large files through streaming.
- [x] 3.1.10 Support configurable endpoint exclusions.

**Observed production format** (12 real attachments, 182,887 lines, 0 malformed):

```
$remote_addr Forwarded for $http_x_forwarded_for $remote_ident $remote_user
[$time_local] "$request" $status $body_bytes_sent $request_time
"$http_referer" "$http_user_agent"
```

- `$http_x_forwarded_for` may hold several comma-separated addresses.
- `$upstream_response_time` is **not** logged: upstream latency is always
  unavailable for this source and must never be estimated.

### 3.2 Performance Statistics

#### 3.2.1 Slow Request Detection

- [x] Identify all requests with response time >= 5 seconds.
- [x] Use a configurable threshold, defaulting to 5 seconds.
- [x] Only classify requests with valid timing data.
- [x] Explicitly report when standard combined logs lack request timing fields.
- [x] Record malformed entries and requests with missing or invalid timing data.

#### 3.2.2 Endpoint Aggregation

- [x] Aggregate requests by HTTP method and normalized endpoint path.
- [x] Treat requests to the same endpoint with different query parameters as the same endpoint.
- [x] Exclude query parameters from endpoint grouping.
- [x] Keep different HTTP methods (GET, POST, etc.) separate.
- [x] Normalize dynamic path segments where reliably identifiable.
- [x] Preserve original request URLs and query parameters for slow requests.
- [x] Avoid merging endpoints when their identities cannot be reliably determined.

#### 3.2.3 Slow Endpoint Statistics

For every endpoint with at least one request taking >= 5 seconds, report:

- [x] HTTP method (GET, POST, PUT, DELETE, etc.).
- [x] Normalized endpoint path.
- [x] Total request count.
- [x] Slow request count (response time >= 5 seconds).
- [x] Slow request ratio: `slow request count / total request count * 100%`.
- [x] Maximum response time.
- [x] Average response time of slow requests.
- [x] Earliest and latest slow request timestamps, when available.
- [x] HTTP status code distribution among slow requests.
- [x] Upstream response time for slow requests, when available.
- [x] Sort results by slow request count descending, then maximum response time descending.

#### 3.2.4 Slow Request Details

- [x] Preserve individual slow request records for further investigation.
- [x] Record request timestamp, HTTP method, original URL, response time and status code.
- [x] Record upstream response time and upstream address when available.
- [x] Identify slow requests containing query parameters.
- [x] Collect the distinct query parameter combinations for each affected endpoint.
- [x] Deduplicate identical parameter combinations.
- [x] Preserve parameter values without exposing sensitive credentials or tokens in reports.

#### 3.2.5 Slow Query Parameter Summary

At the end of the report, generate a separate section listing endpoints with slow requests containing query parameters.

For each endpoint, include:

- [x] HTTP method.
- [x] Normalized endpoint path.
- [x] Query parameter names and observed values.
- [x] Number of slow requests for each distinct parameter combination.
- [x] Response time of each occurrence, or the maximum response time for each combination.

Example:

| Method | Endpoint | Query parameters | Slow requests | Max response time |
|---|---|---|---:|---:|
| GET | `/api/orders/` | `page=100&page_size=500` | 3 | 12.8s |
| GET | `/api/orders/` | `status=pending` | 2 | 8.4s |
| POST | `/api/reports/` | `format=excel` | 1 | 15.2s |

The values above are illustrative only.

- [x] Include only parameter combinations associated with requests taking >= 5 seconds.
- [x] Do not include query parameters from requests below the threshold.
- [x] Clearly indicate endpoints with no query parameters separately only if useful.
- [x] Keep this section at the end of the performance report.

#### 3.2.6 Testing

- [x] Test the >= 5-second threshold boundary.
- [x] Test that requests below 5 seconds are excluded from slow request counts.
- [x] Test aggregation of identical endpoints with different query parameters.
- [x] Test separation of different HTTP methods.
- [x] Test total request counts and slow request ratios.
- [x] Test maximum and average slow-request latency calculations.
- [x] Test query parameter combination deduplication.
- [x] Test missing timing data and malformed log entries.
- [x] Test sensitive query parameter redaction.

**Acceptance criteria:**

- Every valid request taking >= 5 seconds is included in slow request analysis.
- Requests to the same endpoint with different query parameters are aggregated into one endpoint entry per HTTP method.
- Each slow endpoint reports total requests, slow requests, slow request ratio, maximum response time and other available diagnostic metrics.
- A separate section at the end lists query parameters associated with slow requests.
- Missing timing information is explicitly reported; response times are never fabricated.
- All statistics are covered by automated tests.

### 3.3 Initial Reports

- [x] 3.3.1 Generate Markdown reports.
- [x] 3.3.2 Include log file metadata.
- [x] 3.3.3 Include overall request statistics.
- [x] 3.3.4 Include slow endpoint rankings.
- [x] 3.3.5 Include error analysis.
- [x] 3.3.6 Clearly indicate missing timing information.
- [x] 3.3.7 Implement local log analysis CLI command.

**Acceptance criteria:**
- Standard combined logs parse correctly.
- Missing timing fields are never fabricated.
- Percentiles are calculated from actual observations.
- Large log files can be processed without loading everything into memory.
- Reports clearly distinguish available and unavailable metrics.

## 4. Multi-Project Source Code Analysis

### 4.1 Project Registry

- [x] 4.1.1 Implement multi-project YAML configuration.
- [x] 4.1.2 Register multiple source code repositories.
- [x] 4.1.3 Support project enable/disable.
- [x] 4.1.4 Support project-specific URL prefixes.
- [x] 4.1.5 Support manual endpoint-to-project mappings.
- [x] 4.1.6 Implement project validation.
- [x] 4.1.7 Exclude `.git`, `.venv`, `node_modules` and generated files.
- [x] 4.1.8 Implement `projects` CLI command.
- [x] 4.1.9 Map email subject markers to projects (KR/EN/JP -> vb-en, CN -> vb-cn).

## 5. Weixin Report Delivery

Push each generated report to WeChat as a **text message** through the Hermes
Weixin gateway. Delivery is outbound only; no interactive bot behaviour.

- [x] 5.1 Implement report delivery through the Hermes CLI (`hermes send`).
- [x] 5.2 Make the delivery target configurable (`NPA_WEIXIN_TARGET`), default `weixin` (home channel).
- [x] 5.3 Make the Hermes executable configurable (`NPA_HERMES_BIN`), default `hermes`.
- [x] 5.4 Send the Markdown report body as text; pass it on stdin or via `--file` so no shell quoting is involved.
- [x] 5.5 Handle long reports by relying on the gateway's own chunking (verified limit: 2000 characters per message); never truncate locally.
- [x] 5.6 Apply a timeout and treat a non-zero `hermes send` exit code as a delivery failure.
- [x] 5.7 Record delivery outcome (sent/failed, target, timestamp, error) without aborting the analysis pipeline.
- [x] 5.8 Add a `notify` CLI command that re-sends an existing report file, and a `--notify` flag on the report-producing command.
- [x] 5.9 Add tests with a mocked `hermes` subprocess: success, non-zero exit, timeout, missing binary, long text passed whole.
- [x] 5.10 Synchronize README and `.env.example` with the new settings and command.

**Acceptance criteria:**
- A generated report can be delivered to Weixin as one or more text messages.
- A delivery failure is reported clearly but never loses the generated report or stops log analysis.
- No WeChat credentials are stored in this project; the gateway owns them.
- Long reports are never silently truncated.
- All delivery paths are covered by automated tests.

---

## Global Development Rules

1. Always read `AGENTS.md` before implementation.
2. Work on one phase at a time.
3. Update this TODO file immediately after completing each task.
4. Only check `[x]` after implementation and verification.
5. Keep unfinished tasks unchecked.
6. Run relevant tests after every significant change.
7. Do not fabricate log metrics, source locations or AI findings.
8. Never expose API keys or email credentials.
9. Never automatically modify production source code.
10. Automatically `git add` newly created files; do not commit unless explicitly requested.
11. If sudo is required, provide the exact command for the user to execute.
12. Keep README and configuration examples synchronized with implementation.

## Current Status

- [x] Phase 1: Project Foundation
- [x] Phase 2: Email Monitoring
- [x] Phase 3: Log Parsing and Analysis
- [x] Phase 4: Project Registry
- [x] Phase 5: Weixin Report Delivery

**Next action:** Phase 5 complete. `notify.py` sends report text through `hermes send --to <target> --file -` (stdin, no quoting), with `NPA_WEIXIN_TARGET` (default `weixin`), `NPA_HERMES_BIN` and `NPA_HERMES_TIMEOUT`. `analyze --notify` pushes every report after writing it; `notify <report>` re-sends one file. Long reports rely on the Weixin adapter's 2000-character chunking, so nothing is truncated locally. Failures (non-zero exit, timeout, missing binary) are logged and reported, never lose the report, and make the command exit `1`. Live delivery to the configured Weixin home channel verified. 162 tests pass. No further phases planned.
