"""Markdown performance report for a set of local Nginx log files."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nginx_perf_agent.analysis.parser import LogParser
from nginx_perf_agent.analysis.stats import (
    DEFAULT_SLOW_THRESHOLD,
    EndpointStats,
    PerformanceReport,
    PerformanceStats,
)

UNKNOWN = "n/a"


@dataclass(frozen=True, slots=True)
class LogFileMeta:
    """Per-file parse outcome, kept for the report header."""

    name: str
    size_bytes: int
    lines: int
    parsed: int
    malformed: int
    excluded: int


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    report: PerformanceReport
    files: tuple[LogFileMeta, ...]


def resolve_log_files(paths: Iterable[str | Path]) -> list[Path]:
    """Expand directories to their `.log` files; explicit files are kept as given."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*.log") if item.is_file()))
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(f"no such file or directory: {path}")
    if not files:
        raise FileNotFoundError("no .log files found")
    return files


def analyze_paths(
    paths: Iterable[str | Path],
    *,
    slow_threshold: float = DEFAULT_SLOW_THRESHOLD,
    exclude: Iterable[str] = (),
) -> AnalysisResult:
    """Parse every file once, streaming, and aggregate the statistics."""
    stats = PerformanceStats(slow_threshold=slow_threshold)
    metas: list[LogFileMeta] = []
    for path in resolve_log_files(paths):
        parser = LogParser(exclude=exclude)
        stats.add_many(parser.parse_file(path))
        metas.append(
            LogFileMeta(
                name=str(path),
                size_bytes=path.stat().st_size,
                lines=parser.stats.lines,
                parsed=parser.stats.parsed,
                malformed=parser.stats.malformed,
                excluded=parser.stats.excluded,
            )
        )
    return AnalysisResult(report=stats.report(), files=tuple(metas))


def _seconds(value: float | None) -> str:
    return UNKNOWN if value is None else f"{value:.3f}s"


def _count(value: int) -> str:
    return f"{value:,}"


def _percent(value: float) -> str:
    return f"{value:.2f}%"


def _cell(value: object) -> str:
    """Table-safe text: no pipes or newlines can break the row."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list[str]], align: str = "") -> list[str]:
    markers = align or "l" * len(headers)
    separator = [
        {"r": "-" * 6 + ":", "c": ":" + "-" * 6 + ":"}.get(marker, "-" * 7)
        for marker in markers
    ]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(separator) + " |"]
    lines.extend("| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows)
    return lines


def _files_section(files: tuple[LogFileMeta, ...]) -> list[str]:
    rows = [
        [
            meta.name,
            _count(meta.size_bytes),
            _count(meta.lines),
            _count(meta.parsed),
            _count(meta.malformed),
            _count(meta.excluded),
        ]
        for meta in files
    ]
    return [
        "## Log files",
        "",
        *_table(
            ["File", "Bytes", "Lines", "Parsed", "Malformed", "Excluded"], rows, "lrrrrr"
        ),
        "",
    ]


def _overall_section(report: PerformanceReport) -> list[str]:
    slow_ratio = (
        len(report.slow_requests) / report.requests * 100 if report.requests else 0.0
    )
    rows = [
        ["Requests", _count(report.requests)],
        ["Endpoints", _count(report.total_endpoints)],
        ["Requests with timing", _count(report.timed_requests)],
        ["Requests without timing", _count(report.requests_missing_timing)],
        [
            "Slow requests",
            f"{_count(len(report.slow_requests))} ({_percent(slow_ratio)})",
        ],
        ["Errors (4xx/5xx)", _count(report.error_requests)],
    ]
    lines = ["## Overall statistics", "", *_table(["Metric", "Value"], rows), ""]

    latency = report.latency
    if latency is None:
        lines += [
            f"> **Timing unavailable**: no request logged `$request_time` "
            f"({_count(report.requests_missing_timing)} of {_count(report.requests)} "
            "requests). Latency percentiles and slow-request statistics cannot be "
            "produced, and response times are never estimated.",
            "",
        ]
        return lines

    if report.requests_missing_timing:
        lines += [
            f"> {_count(report.requests_missing_timing)} request(s) had no valid "
            "`$request_time` and are excluded from latency and slow-request "
            "statistics.",
            "",
        ]

    percentiles = latency.percentiles
    rows = [
        ["Min", _seconds(latency.minimum)],
        ["Mean", _seconds(latency.mean)],
        *[
            [f"p{percentile}", _seconds(percentiles[percentile])]
            for percentile in percentiles
        ],
        ["Max", _seconds(latency.maximum)],
    ]
    lines += [
        "### Latency (all timed requests)",
        "",
        *_table(["Metric", "Response time"], rows),
        "",
    ]
    return lines


def _slow_endpoint_section(report: PerformanceReport, top: int) -> list[str]:
    endpoints = report.endpoints
    header = f"## Slow endpoints (>= {_seconds(report.slow_threshold)})"
    if not endpoints:
        return [
            header,
            "",
            f"No request took {_seconds(report.slow_threshold)} or longer.",
            "",
        ]

    rows = [
        [
            str(index),
            stats.method,
            stats.path,
            _count(stats.total_requests),
            _count(stats.slow_requests),
            _percent(stats.slow_ratio),
            _seconds(stats.max_response_time),
            _seconds(stats.avg_slow_response_time),
            stats.first_slow.strftime("%Y-%m-%d %H:%M:%S") if stats.first_slow else UNKNOWN,
            stats.last_slow.strftime("%Y-%m-%d %H:%M:%S") if stats.last_slow else UNKNOWN,
            _seconds(stats.max_upstream_time),
        ]
        for index, stats in enumerate(endpoints[:top], start=1)
    ]
    lines = [
        header,
        "",
        *_table(
            [
                "#",
                "Method",
                "Endpoint",
                "Total",
                "Slow",
                "Slow %",
                "Max",
                "Avg slow",
                "First slow",
                "Last slow",
                "Upstream max",
            ],
            rows,
            "rlrrrrrrllr",
        ),
        "",
    ]
    if len(endpoints) > top:
        lines += [f"Showing the top {top} of {len(endpoints)} slow endpoints.", ""]
    if all(stats.max_upstream_time is None for stats in endpoints):
        lines += [
            "`n/a` upstream times mean the log layout does not record "
            "`$upstream_response_time`.",
            "",
        ]
    return lines


def _error_section(report: PerformanceReport, top: int) -> list[str]:
    errors = {
        status: count for status, count in report.status_counts.items() if status >= 400
    }
    if not errors:
        return ["## Error analysis", "", "No 4xx or 5xx responses.", ""]

    total = sum(errors.values())
    rows = [
        [str(status), _count(count), _percent(count / total * 100)]
        for status, count in sorted(errors.items())
    ]
    lines = [
        "## Error analysis",
        "",
        f"{_count(total)} error response(s) out of {_count(report.requests)} requests.",
        "",
        *_table(["Status", "Count", "Share of errors"], rows, "lrr"),
        "",
    ]

    # Only endpoints that actually produced errors; ranking is by error count.
    endpoints = report.error_endpoints
    if endpoints:
        rows = [
            [
                stats.method,
                stats.path,
                _count(stats.error_requests),
                _percent(stats.error_requests / stats.total_requests * 100),
                str(_dominant_error(stats)),
            ]
            for stats in endpoints[:top]
        ]
        lines += [
            "### Endpoints by errors",
            "",
            *_table(
                ["Method", "Endpoint", "Errors", "Error %", "Top status"], rows, "lrrrl"
            ),
            "",
        ]
    return lines


def _dominant_error(stats: EndpointStats) -> int:
    errors: Counter[int] = Counter(
        {status: count for status, count in stats.status_counts.items() if status >= 400}
    )
    return errors.most_common(1)[0][0]


def _query_section(report: PerformanceReport, top: int) -> list[str]:
    groups = report.query_groups
    header = [
        "## Slow query parameters",
        "",
        f"Only requests taking {_seconds(report.slow_threshold)} or longer are "
        "listed; values of credential-like parameters are masked as `***`.",
        "",
    ]
    if not groups:
        return header + ["No slow request carried query parameters.", ""]

    rows = [
        [
            group.method,
            group.path,
            f"`{group.query}`",
            _count(group.slow_requests),
            _seconds(group.max_response_time),
        ]
        for group in groups[:top]
    ]
    lines = header + _table(
        ["Method", "Endpoint", "Query parameters", "Slow requests", "Max response time"],
        rows,
        "llrrr",
    ) + [""]
    if len(groups) > top:
        lines += [f"Showing the top {top} of {len(groups)} combinations.", ""]
    return lines


def render_markdown(
    result: AnalysisResult, *, top: int = 10, generated_at: datetime | None = None
) -> str:
    """Render the report. The query-parameter section always comes last."""
    report = result.report
    stamp = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Nginx performance report",
        "",
        f"Generated: {stamp}",
        "",
        f"Slow threshold: {_seconds(report.slow_threshold)}",
        "",
        *_files_section(result.files),
        *_overall_section(report),
        *_slow_endpoint_section(report, top),
        *_error_section(report, top),
        *_query_section(report, top),
    ]
    return "\n".join(lines).rstrip() + "\n"
