"""Nginx access-log parsing and analysis."""

from nginx_perf_agent.analysis.parser import LogEntry, LogParser, ParseStats, parse_line
from nginx_perf_agent.analysis.report import (
    AnalysisResult,
    LogFileMeta,
    analyze_paths,
    render_markdown,
    resolve_log_files,
)
from nginx_perf_agent.analysis.stats import (
    DEFAULT_SLOW_THRESHOLD,
    EndpointStats,
    LatencySummary,
    PerformanceReport,
    PerformanceStats,
    QueryGroup,
    SlowRequest,
    normalize_endpoint_path,
    redact_query,
)

__all__ = [
    "DEFAULT_SLOW_THRESHOLD",
    "AnalysisResult",
    "EndpointStats",
    "LatencySummary",
    "LogEntry",
    "LogFileMeta",
    "LogParser",
    "ParseStats",
    "PerformanceReport",
    "PerformanceStats",
    "QueryGroup",
    "SlowRequest",
    "analyze_paths",
    "normalize_endpoint_path",
    "parse_line",
    "redact_query",
    "render_markdown",
    "resolve_log_files",
]
