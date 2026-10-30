# Nginx Performance Agent — TODO

> Project: Nginx Performance Analyzer  
> Stack: Ubuntu + Python 3.12+ + uv + SQLite + Polars + OpenAI API  
> Rule: Complete tasks incrementally. Mark `[x]` immediately after successful implementation and verification.

## Progress

- Total: 6 phases
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
- [x] 2.3 Implement subject matching for `Nginx 日志`.
- [x] 2.4 Implement IMAP UID-based email identification.
- [x] 2.5 Implement attachment extraction.
- [x] 2.6 Support `.log` and `.txt` attachments.
- [x] 2.7 Support `.gz` attachments.
- [x] 2.8 Support `.zip` attachments.
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

- [ ] 3.1.1 Implement standard Nginx combined log parser.
- [ ] 3.1.2 Support extended combined format.
- [ ] 3.1.3 Extract HTTP method, URL, status and response size.
- [ ] 3.1.4 Extract request time when available.
- [ ] 3.1.5 Extract upstream response time when available.
- [ ] 3.1.6 Normalize URL paths and remove query parameters.
- [ ] 3.1.7 Group endpoints by HTTP method.
- [ ] 3.1.8 Handle malformed log entries.
- [ ] 3.1.9 Support large files through streaming.
- [ ] 3.1.10 Support configurable endpoint exclusions.

### 3.2 Performance Statistics

- [ ] 3.2.1 Calculate total request count.
- [ ] 3.2.2 Calculate average response time.
- [ ] 3.2.3 Calculate P50 latency.
- [ ] 3.2.4 Calculate P95 latency.
- [ ] 3.2.5 Calculate P99 latency.
- [ ] 3.2.6 Calculate maximum response time.
- [ ] 3.2.7 Calculate 4xx and 5xx counts and ratios.
- [ ] 3.2.8 Calculate upstream latency statistics.
- [ ] 3.2.9 Identify Top 20 slow endpoints.
- [ ] 3.2.10 Identify Top 20 frequently requested endpoints.
- [ ] 3.2.11 Identify high error-rate endpoints.
- [ ] 3.2.12 Implement configurable performance thresholds.
- [ ] 3.2.13 Add statistics unit tests.

### 3.3 Initial Reports

- [ ] 3.3.1 Generate Markdown reports.
- [ ] 3.3.2 Include log file metadata.
- [ ] 3.3.3 Include overall request statistics.
- [ ] 3.3.4 Include slow endpoint rankings.
- [ ] 3.3.5 Include error analysis.
- [ ] 3.3.6 Clearly indicate missing timing information.
- [ ] 3.3.7 Implement local log analysis CLI command.

**Acceptance criteria:**
- Standard combined logs parse correctly.
- Missing timing fields are never fabricated.
- Percentiles are calculated from actual observations.
- Large log files can be processed without loading everything into memory.
- Reports clearly distinguish available and unavailable metrics.

## 4. Multi-Project Source Code Analysis

### 4.1 Project Registry

- [ ] 4.1.1 Implement multi-project YAML configuration.
- [ ] 4.1.2 Register multiple source code repositories.
- [ ] 4.1.3 Support project enable/disable.
- [ ] 4.1.4 Support project-specific URL prefixes.
- [ ] 4.1.5 Support manual endpoint-to-project mappings.
- [ ] 4.1.6 Implement project validation.
- [ ] 4.1.7 Exclude `.git`, `.venv`, `node_modules` and generated files.
- [ ] 4.1.8 Implement `projects` CLI command.

### 4.2 Django Code Discovery

- [ ] 4.2.1 Implement URL pattern discovery.
- [ ] 4.2.2 Locate Django Views and ViewSets.
- [ ] 4.2.3 Identify handler methods.
- [ ] 4.2.4 Locate related Serializers.
- [ ] 4.2.5 Locate related Models.
- [ ] 4.2.6 Identify related service functions.
- [ ] 4.2.7 Analyze ORM query patterns.
- [ ] 4.2.8 Collect source code context.
- [ ] 4.2.9 Record file paths and line numbers.
- [ ] 4.2.10 Handle ambiguous endpoint mappings.
- [ ] 4.2.11 Add source discovery tests.

**Acceptance criteria:**
- Multiple Django projects can be registered.
- Known endpoints can be mapped to corresponding source code.
- Findings include traceable file paths and line numbers.
- Ambiguous matches are reported instead of guessed.
- Source inspection does not require production database access.

## 5. AI Performance Diagnosis

### 5.1 AI Client

- [ ] 5.1.1 Implement OpenAI-compatible API client.
- [ ] 5.1.2 Support configurable Base URL.
- [ ] 5.1.3 Support configurable API Key.
- [ ] 5.1.4 Support configurable model name.
- [ ] 5.1.5 Implement request timeout.
- [ ] 5.1.6 Implement retry mechanism.
- [ ] 5.1.7 Implement structured JSON response validation.
- [ ] 5.1.8 Add mocked AI API tests.

### 5.2 Code Diagnosis

- [ ] 5.2.1 Build endpoint-specific analysis context.
- [ ] 5.2.2 Include performance statistics.
- [ ] 5.2.3 Include relevant View and ViewSet code.
- [ ] 5.2.4 Include relevant Serializer and Model code.
- [ ] 5.2.5 Implement database performance diagnosis.
- [ ] 5.2.6 Detect potential N+1 queries.
- [ ] 5.2.7 Detect inefficient ORM usage.
- [ ] 5.2.8 Detect potential missing indexes.
- [ ] 5.2.9 Detect excessive serialization.
- [ ] 5.2.10 Detect unnecessary data retrieval.
- [ ] 5.2.11 Detect blocking external requests.
- [ ] 5.2.12 Detect missing caching opportunities.
- [ ] 5.2.13 Detect repeated calculations.
- [ ] 5.2.14 Implement severity and confidence ratings.
- [ ] 5.2.15 Implement optimization recommendations.
- [ ] 5.2.16 Implement verification suggestions.
- [ ] 5.2.17 Prevent unsupported or fabricated findings.

### 5.3 Diagnosis Reports

- [ ] 5.3.1 Integrate AI findings into Markdown reports.
- [ ] 5.3.2 Include source code references.
- [ ] 5.3.3 Include optimization priorities.
- [ ] 5.3.4 Include expected benefits and risks.
- [ ] 5.3.5 Include confidence levels.
- [ ] 5.3.6 Include missing evidence and limitations.

**Acceptance criteria:**
- AI receives only relevant source code context.
- Diagnosis results follow a validated schema.
- Confirmed issues are separated from suspected issues.
- Every finding includes supporting evidence.
- No source code is automatically modified.

## 6. Historical Analysis and Production Deployment

### 6.1 Historical Analysis

- [ ] 6.1.1 Persist endpoint performance statistics.
- [ ] 6.1.2 Persist AI diagnosis results.
- [ ] 6.1.3 Record source project revisions.
- [ ] 6.1.4 Implement historical report lookup.
- [ ] 6.1.5 Compare performance across analysis periods.
- [ ] 6.1.6 Detect P95/P99 latency regressions.
- [ ] 6.1.7 Detect error-rate regressions.
- [ ] 6.1.8 Identify newly slow endpoints.
- [ ] 6.1.9 Implement `tasks` CLI command.
- [ ] 6.1.10 Implement `report` CLI command.

### 6.2 Ubuntu Deployment

- [ ] 6.2.1 Complete Ubuntu installation documentation.
- [ ] 6.2.2 Provide production configuration examples.
- [ ] 6.2.3 Create systemd service unit.
- [ ] 6.2.4 Create systemd timer or document polling mode.
- [ ] 6.2.5 Configure log rotation.
- [ ] 6.2.6 Configure data retention.
- [ ] 6.2.7 Document database backup and recovery.
- [ ] 6.2.8 Document application upgrades.
- [ ] 6.2.9 Verify execution under a non-root user.
- [ ] 6.2.10 Verify unattended email processing.

### 6.3 Final Verification

- [ ] 6.3.1 Run all unit tests.
- [ ] 6.3.2 Run integration tests.
- [ ] 6.3.3 Verify IMAP connectivity.
- [ ] 6.3.4 Verify attachment processing.
- [ ] 6.3.5 Verify real Nginx log parsing.
- [ ] 6.3.6 Verify multi-project source discovery.
- [ ] 6.3.7 Verify AI diagnosis.
- [ ] 6.3.8 Verify report generation.
- [ ] 6.3.9 Verify historical comparison.
- [ ] 6.3.10 Verify systemd deployment.
- [ ] 6.3.11 Complete README documentation.

**Acceptance criteria:**
- The complete pipeline works from email reception to report generation.
- The application runs unattended on Ubuntu.
- All tests pass.
- Deployment and maintenance procedures are documented.

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
- [ ] Phase 3: Log Parsing and Analysis
- [ ] Phase 4: Source Code Analysis
- [ ] Phase 5: AI Diagnosis
- [ ] Phase 6: Historical Analysis and Deployment

**Next action:** Phase 2 verified (read-only IMAP client, UID dedup, status tracking, retries, archive extraction with safety guards, `mail-test`/`process`/`watch`, 61 tests passing against a fake IMAP server). Start Phase 3 (Log Parsing and Analysis) only.
