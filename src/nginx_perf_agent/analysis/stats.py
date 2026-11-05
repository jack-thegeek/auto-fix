"""Slow-request and per-endpoint statistics from parsed log entries.

Response times are never estimated: an entry without `$request_time` only
counts towards `requests_missing_timing` and cannot be classified as slow.
"""

from __future__ import annotations

import ipaddress
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl

from nginx_perf_agent.analysis.parser import LogEntry

DEFAULT_SLOW_THRESHOLD = 5.0
REDACTED = "***"

# Priority tiers: too few requests or slow samples stay low so one-off slow
# calls do not outrank busy endpoints.
LOW_TOTAL = 3
MIN_SLOW = 2
MID_TOTAL = 50
PRIORITY_ORDER = {"高": 0, "中": 1, "低": 2}

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

# Parameter name tokens whose values are credentials or session material.
_SENSITIVE_HINTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "key",
    "auth",
    "session",
    "cookie",
    "sign",
    "credential",
)

_PARAM_TOKEN = re.compile(r"[^a-z0-9]+")

_UUID_SEGMENT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
_HEX_SEGMENT = re.compile(r"^[0-9a-f]{16,}$", re.I)
_DIGITS_SEGMENT = re.compile(r"^\d+$")
_EMAIL_SEGMENT = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# VB260101-1001abc / P260101-1001abc-r1
_CODE_SEGMENT = re.compile(r"^(?:VB|P|Lib)\d{6,}-\w+(?:-\w+)*$", re.I)
# NM_000546.6 / ORF123
_ACCESSION_SEGMENT = re.compile(r"^(?:NM|NR|XM|XR|NP|YP)_\d+\.\d+$")
_ORF_SEGMENT = re.compile(r"^ORF\d+$", re.I)
# pLV_2gRNA / pET16b
_VECTOR_SEGMENT = re.compile(r"^p(?=.*[_A-Z0-9])[A-Za-z0-9_]+$")


def _segment_placeholder(segment: str) -> str | None:
    if (
        _UUID_SEGMENT.match(segment)
        or _HEX_SEGMENT.match(segment)
        or _DIGITS_SEGMENT.match(segment)
        or _EMAIL_SEGMENT.match(segment)
    ):
        return "{id}"
    if _CODE_SEGMENT.match(segment):
        return "{code}"
    if _ACCESSION_SEGMENT.match(segment) or _ORF_SEGMENT.match(segment):
        return "{accession}"
    if _VECTOR_SEGMENT.match(segment):
        return "{vector}"
    return None


def normalize_endpoint_path(path: str) -> str:
    """Collapse known dynamic path segments to placeholders.

    Recognized: ids (digits, UUID, hex, email), `{code}` (VB/P/Lib numbers),
    `{accession}` (GenBank/ORF accessions) and `{vector}` (plasmid names).
    Anything else stays literal so two endpoints are never merged on a guess.
    """
    return "/".join(
        _segment_placeholder(segment) or segment for segment in path.split("/")
    )


def priority_for(total: int, slow: int) -> str:
    """Priority tier from request volume; small samples are always low."""
    if total < LOW_TOTAL or slow < MIN_SLOW:
        return "低"
    return "中" if total < MID_TOTAL else "高"


def load_internal_networks(path: str | Path) -> tuple[Network, ...]:
    """Read one CIDR per line; blank lines and `#` comments are ignored.

    A missing file means "no internal networks known" rather than an error.
    """
    file = Path(path)
    if not file.is_file():
        return ()
    networks: list[Network] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            networks.append(ipaddress.ip_network(line, strict=False))
    return tuple(networks)


def _client_ip(entry: LogEntry) -> str:
    """First forwarded address when present, otherwise the direct peer."""
    return entry.forwarded_for[0] if entry.forwarded_for else entry.remote_addr


def _is_internal(ip: str, networks: Iterable[Network]) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in network for network in networks)


def _is_sensitive(name: str) -> bool:
    """Match whole name tokens so `keywords` is not treated as `key`."""
    tokens = [token for token in _PARAM_TOKEN.split(name.lower()) if token]
    return any(token.endswith(_SENSITIVE_HINTS) for token in tokens)


def redact_query(query: str) -> str:
    """Canonical `name=value` form with sensitive values masked.

    Sorting by name only keeps repeated names in their original order, and
    makes `a=1&b=2` and `b=2&a=1` one combination.
    """
    pairs = sorted(parse_qsl(query, keep_blank_values=True), key=lambda pair: pair[0])
    return "&".join(
        f"{name}={REDACTED if _is_sensitive(name) else value}" for name, value in pairs
    )


@dataclass(frozen=True, slots=True)
class SlowRequest:
    """One request at or above the threshold, kept for investigation."""

    timestamp: datetime
    method: str
    path: str
    url: str
    response_time: float
    status: int
    upstream_time: float | None
    query: str

    @property
    def has_query(self) -> bool:
        return bool(self.query)


@dataclass(slots=True)
class EndpointStats:
    """Aggregates for one method plus normalized path."""

    method: str
    path: str
    total_requests: int = 0
    slow_requests: int = 0
    internal_requests: int = 0
    status_counts: Counter[int] = field(default_factory=Counter)
    slow_times: list[float] = field(default_factory=list)
    slow_statuses: Counter[int] = field(default_factory=Counter)
    slow_upstream_times: list[float] = field(default_factory=list)
    first_slow: datetime | None = None
    last_slow: datetime | None = None

    @property
    def endpoint(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def slow_ratio(self) -> float:
        """Slow requests as a percentage of every request to this endpoint."""
        return self.slow_requests / self.total_requests * 100 if self.total_requests else 0.0

    @property
    def max_response_time(self) -> float:
        return max(self.slow_times, default=0.0)

    @property
    def avg_slow_response_time(self) -> float | None:
        return sum(self.slow_times) / len(self.slow_times) if self.slow_times else None

    @property
    def max_upstream_time(self) -> float | None:
        return max(self.slow_upstream_times) if self.slow_upstream_times else None

    @property
    def internal_ratio(self) -> float:
        """Share of requests that came from an internal network, as a percentage."""
        return self.internal_requests / self.total_requests * 100 if self.total_requests else 0.0

    @property
    def priority(self) -> str:
        return priority_for(self.total_requests, self.slow_requests)

    @property
    def impact(self) -> float:
        """Average slow seconds × slow ratio: how slow and how widely it hurts."""
        if not self.total_requests:
            return 0.0
        return (self.avg_slow_response_time or 0.0) * self.slow_requests / self.total_requests

    @property
    def error_requests(self) -> int:
        """Requests answered with 4xx or 5xx."""
        return sum(
            count for status, count in self.status_counts.items() if status >= 400
        )


@dataclass(frozen=True, slots=True)
class QueryGroup:
    """One distinct (redacted) parameter combination of a slow endpoint."""

    method: str
    path: str
    query: str
    slow_requests: int
    max_response_time: float


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    slow_threshold: float
    requests: int
    requests_missing_timing: int
    total_endpoints: int
    status_counts: dict[int, int]
    slow_requests: tuple[SlowRequest, ...]
    endpoints: tuple[EndpointStats, ...]
    error_endpoints: tuple[EndpointStats, ...]
    query_groups: tuple[QueryGroup, ...]
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    internal_networks: int

    @property
    def timing_available(self) -> bool:
        """False when the log layout carries no `$request_time` at all."""
        return self.requests_missing_timing < self.requests

    @property
    def error_requests(self) -> int:
        return sum(count for status, count in self.status_counts.items() if status >= 400)


class PerformanceStats:
    """Accumulates entries one at a time; slow requests are the only list kept."""

    def __init__(
        self,
        slow_threshold: float = DEFAULT_SLOW_THRESHOLD,
        normalize_paths: bool = True,
        internal_networks: Iterable[Network] = (),
    ) -> None:
        if slow_threshold <= 0:
            raise ValueError("slow_threshold must be positive")
        self.slow_threshold = slow_threshold
        self._normalize = normalize_paths
        self._networks = tuple(internal_networks)
        self.requests = 0
        self.requests_missing_timing = 0
        self._first_time: datetime | None = None
        self._last_time: datetime | None = None
        self._endpoints: dict[tuple[str, str], EndpointStats] = {}
        self._slow: list[SlowRequest] = []
        self._queries: dict[tuple[str, str, str], list[float]] = {}
        self._statuses: Counter[int] = Counter()

    def add(self, entry: LogEntry) -> None:
        path = normalize_endpoint_path(entry.path) if self._normalize else entry.path
        stats = self._endpoints.get((entry.method, path))
        if stats is None:
            stats = self._endpoints[(entry.method, path)] = EndpointStats(entry.method, path)
        self.requests += 1
        self._statuses[entry.status] += 1
        stats.total_requests += 1
        stats.status_counts[entry.status] += 1
        if self._first_time is None or entry.time_local < self._first_time:
            self._first_time = entry.time_local
        if self._last_time is None or entry.time_local > self._last_time:
            self._last_time = entry.time_local
        if self._networks and _is_internal(_client_ip(entry), self._networks):
            stats.internal_requests += 1

        if entry.request_time is None:
            self.requests_missing_timing += 1
            return
        if entry.request_time < self.slow_threshold:
            return

        query = redact_query(entry.target.split("?", 1)[1]) if "?" in entry.target else ""
        self._slow.append(
            SlowRequest(
                timestamp=entry.time_local,
                method=entry.method,
                path=path,
                url=entry.target,
                response_time=entry.request_time,
                status=entry.status,
                upstream_time=entry.upstream_time,
                query=query,
            )
        )
        stats.slow_requests += 1
        stats.slow_times.append(entry.request_time)
        stats.slow_statuses[entry.status] += 1
        if entry.upstream_time is not None:
            stats.slow_upstream_times.append(entry.upstream_time)
        if stats.first_slow is None or entry.time_local < stats.first_slow:
            stats.first_slow = entry.time_local
        if stats.last_slow is None or entry.time_local > stats.last_slow:
            stats.last_slow = entry.time_local
        if query:
            self._queries.setdefault((entry.method, path, query), []).append(
                entry.request_time
            )

    def add_many(self, entries: Iterable[LogEntry]) -> None:
        for entry in entries:
            self.add(entry)

    def report(self) -> PerformanceReport:
        # Priority first, then impact (avg slow time × slow ratio), then volume.
        endpoints = sorted(
            (stats for stats in self._endpoints.values() if stats.slow_requests),
            key=lambda stats: (
                PRIORITY_ORDER[stats.priority],
                -stats.impact,
                -stats.slow_requests,
            ),
        )
        groups = sorted(
            (
                QueryGroup(
                    method=method,
                    path=path,
                    query=query,
                    slow_requests=len(times),
                    max_response_time=max(times),
                )
                for (method, path, query), times in self._queries.items()
            ),
            key=lambda group: (group.slow_requests, group.max_response_time),
            reverse=True,
        )
        error_endpoints = sorted(
            (stats for stats in self._endpoints.values() if stats.error_requests),
            key=lambda stats: stats.error_requests,
            reverse=True,
        )
        return PerformanceReport(
            slow_threshold=self.slow_threshold,
            requests=self.requests,
            requests_missing_timing=self.requests_missing_timing,
            total_endpoints=len(self._endpoints),
            status_counts=dict(self._statuses.most_common()),
            slow_requests=tuple(self._slow),
            endpoints=tuple(endpoints),
            error_endpoints=tuple(error_endpoints),
            query_groups=tuple(groups),
            first_timestamp=self._first_time,
            last_timestamp=self._last_time,
            internal_networks=len(self._networks),
        )

