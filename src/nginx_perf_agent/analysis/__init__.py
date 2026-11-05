"""Nginx access-log parsing and analysis."""

from nginx_perf_agent.analysis.parser import LogEntry, LogParser, ParseStats, parse_line
from nginx_perf_agent.analysis.report import (
    DEFAULT_WINDOW_HOURS,
    UNCLASSIFIED,
    AnalysisResult,
    LogFileMeta,
    analyze_paths,
    file_sha256,
    group_files_by_language,
    render_markdown,
    resolve_log_files,
)
from nginx_perf_agent.analysis.stats import (
    DEFAULT_SLOW_THRESHOLD,
    EndpointStats,
    PerformanceReport,
    PerformanceStats,
    QueryGroup,
    SlowRequest,
    load_internal_networks,
    normalize_endpoint_path,
    priority_for,
    redact_query,
)

__all__ = [
    "DEFAULT_SLOW_THRESHOLD",
    "DEFAULT_WINDOW_HOURS",
    "UNCLASSIFIED",
    "AnalysisResult",
    "EndpointStats",
    "LogEntry",
    "LogFileMeta",
    "LogParser",
    "ParseStats",
    "PerformanceReport",
    "PerformanceStats",
    "QueryGroup",
    "SlowRequest",
    "analyze_paths",
    "file_sha256",
    "group_files_by_language",
    "load_internal_networks",
    "normalize_endpoint_path",
    "parse_line",
    "priority_for",
    "redact_query",
    "render_markdown",
    "resolve_log_files",
]
