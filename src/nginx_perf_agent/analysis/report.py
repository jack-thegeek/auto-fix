"""Markdown performance report for a set of local Nginx log files."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from nginx_perf_agent.analysis.parser import LogEntry, LogParser
from nginx_perf_agent.analysis.stats import (
    DEFAULT_SLOW_THRESHOLD,
    Network,
    PerformanceReport,
    PerformanceStats,
)

UNKNOWN = "n/a"
DEFAULT_WINDOW_HOURS = 24.0
UNCLASSIFIED = "未分类"
# proxy.log is universal-service's detailed log and repeats those calls;
# skip it in directory scans until it gets a dedicated report.
PROXY_LOG_SUFFIX = "-proxy.log"
_HEX64 = re.compile(r"[0-9a-f]{64}")


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
    """Expand directories to their `.log` files; explicit files are kept as given.

    Directory scans skip `*-proxy.log` (universal-service detail, ignored for
    now); naming an explicit proxy file still analyses it.
    """
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(
                sorted(
                    item
                    for item in path.rglob("*.log")
                    if item.is_file() and not item.name.endswith(PROXY_LOG_SUFFIX)
                )
            )
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(f"no such file or directory: {path}")
    if not files:
        raise FileNotFoundError("no .log files found")
    return files


def file_sha256(path: Path) -> str:
    """Content hash; stored attachments are already named by their sha256."""
    if _HEX64.fullmatch(path.stem):
        return path.stem
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def group_files_by_language(
    files: Iterable[Path], languages: Mapping[str, str]
) -> dict[str, list[Path]]:
    """Group log files by site marker; unmapped files go to 未分类."""
    groups: dict[str, list[Path]] = {}
    for path in files:
        language = languages.get(file_sha256(path), UNCLASSIFIED)
        groups.setdefault(language, []).append(path)
    return groups


def _newest_timestamp(files: Iterable[Path]) -> datetime | None:
    """Newest `$time_local` across all files; `None` when nothing parses."""
    newest: datetime | None = None
    for path in files:
        for entry in LogParser().parse_file(path):
            if newest is None or entry.time_local > newest:
                newest = entry.time_local
    return newest


def _within_window(
    entries: Iterator[LogEntry], cutoff: datetime | None
) -> Iterator[LogEntry]:
    if cutoff is None:
        yield from entries
        return
    for entry in entries:
        if entry.time_local >= cutoff:
            yield entry


def analyze_paths(
    paths: Iterable[str | Path],
    *,
    slow_threshold: float = DEFAULT_SLOW_THRESHOLD,
    exclude: Iterable[str] = (),
    internal_networks: Iterable[Network] = (),
    hours: float = DEFAULT_WINDOW_HOURS,
) -> AnalysisResult:
    """Aggregate statistics, keeping only the last `hours` of log time.

    The window ends at the newest parsed timestamp, not at wall-clock now, so
    old attachments still produce a report. `hours=0` analyses every line.
    """
    files = resolve_log_files(paths)
    cutoff = None
    if hours > 0:
        newest = _newest_timestamp(files)
        if newest is not None:
            cutoff = newest - timedelta(hours=hours)

    stats = PerformanceStats(
        slow_threshold=slow_threshold, internal_networks=internal_networks
    )
    metas: list[LogFileMeta] = []
    for path in files:
        parser = LogParser(exclude=exclude)
        stats.add_many(_within_window(parser.parse_file(path), cutoff))
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
    return UNKNOWN if value is None else f"{value:.2f}s"


def _count(value: int) -> str:
    return f"{value:,}"


def _percent(value: float) -> str:
    return f"{value:.1f}%"


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


def _log_time(report: PerformanceReport) -> str:
    first, last = report.first_timestamp, report.last_timestamp
    if first is None or last is None:
        return "-"
    hours = (last - first).total_seconds() / 3600
    return f"{first:%Y-%m-%d %H:%M:%S} ~ {last:%Y-%m-%d %H:%M:%S}（{hours:.2f} h）"


def _header(report: PerformanceReport, stamp: str, label: str | None) -> list[str]:
    slow_ratio = (
        len(report.slow_requests) / report.requests * 100 if report.requests else 0.0
    )
    heading = f"# 慢请求统计（{label}）" if label else "# 慢请求统计"
    return [
        heading,
        "",
        f"- 生成时间：{stamp}",
        f"- 日志时间：{_log_time(report)}",
        f"- 慢请求/总请求占比：{_count(len(report.slow_requests))}/"
        f"{_count(report.requests)}（{_percent(slow_ratio)}）",
        "",
    ]


def _slow_table(report: PerformanceReport, top: int) -> list[str]:
    header = [f"## Top {top} 慢请求", ""]
    endpoints = report.endpoints
    if not endpoints:
        return header + [f"没有耗时 ≥ {_seconds(report.slow_threshold)} 的请求。", ""]

    has_upstream = any(stats.max_upstream_time is not None for stats in endpoints)
    headers = [
        "接口",
        "优先级",
        "慢请求/总请求",
        "慢率",
        "内部调用占比",
        "慢请求平均时间",
        "最慢用时",
    ]
    if has_upstream:
        headers.append("上游最慢")
    rows = [
        [
            stats.endpoint,
            stats.priority,
            f"{stats.slow_requests}/{stats.total_requests}",
            _percent(stats.slow_ratio),
            _percent(stats.internal_ratio) if report.internal_networks else "-",
            _seconds(stats.avg_slow_response_time),
            _seconds(stats.max_response_time),
        ]
        for stats in endpoints[:top]
    ]
    if has_upstream:
        for row, stats in zip(rows, endpoints[:top]):
            row.append(_seconds(stats.max_upstream_time))

    lines = [
        *header,
        *_table(headers, rows, "lc" + "r" * (len(headers) - 2)),
        "",
    ]
    if len(endpoints) > top:
        lines += [f"仅显示前 {top} 个，共 {len(endpoints)} 个慢接口。", ""]
    return lines


def _query_section(report: PerformanceReport, top: int) -> list[str]:
    groups = report.query_groups
    header = [
        "## 慢查询参数",
        "",
        f"仅统计耗时 ≥ {_seconds(report.slow_threshold)} 的请求；"
        "疑似凭证类参数的值已脱敏为 `***`。",
        "",
    ]
    if not groups:
        return header + ["没有慢请求携带查询参数。", ""]

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
        ["方法", "接口", "查询参数", "慢请求数", "最大耗时"],
        rows,
        "llrrr",
    ) + [""]
    if len(groups) > top:
        lines += [f"仅显示前 {top} 个，共 {len(groups)} 种参数组合。", ""]
    return lines


def render_markdown(
    result: AnalysisResult,
    *,
    top: int = 10,
    generated_at: datetime | None = None,
    label: str | None = None,
) -> str:
    """Render the report. The query-parameter section always comes last."""
    report = result.report
    stamp = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        *_header(report, stamp, label),
        *_slow_table(report, top),
        *_query_section(report, top),
    ]
    return "\n".join(lines).rstrip() + "\n"
