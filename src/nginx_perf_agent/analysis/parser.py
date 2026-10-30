"""Stream Nginx access-log lines into structured entries.

Supported layouts:

- combined: `$remote_addr - $remote_user [$time_local] "$request" $status
  $body_bytes_sent "$http_referer" "$http_user_agent"`
- extended combined: the same, with `$request_time` and optionally
  `$upstream_response_time` after `$body_bytes_sent`
- this deployment's variant, which logs `Forwarded for
  $http_x_forwarded_for` between `$remote_addr` and `$remote_ident`
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from nginx_perf_agent.log import get_logger

log = get_logger(__name__)

_TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"

# Optional groups are tried left to right, so a combined line without timing
# fields still matches; the trailing quoted fields anchor the match.
_LINE = re.compile(
    r"^(?P<remote_addr>\S+)\s+"
    r"(?:Forwarded\s+for\s+(?P<forwarded_for>[^\[\]]*?)\s+)?"
    r"(?P<ident>\S+)\s+(?P<user>\S+)\s+"
    r"\[(?P<time_local>[^\]]+)\]\s+"
    r'"(?P<request>[^"]*)"\s+'
    r"(?P<status>\d{3})\s+(?P<body_bytes>\d+|-)"
    r"(?:\s+(?P<request_time>[\d.]+|-))?"
    r"(?:\s+(?P<upstream_time>[-\d.,\s]+?))?"
    r'\s+"(?P<referer>[^"]*)"\s+"(?P<user_agent>[^"]*)"\s*$'
)


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One parsed request."""

    remote_addr: str
    forwarded_for: tuple[str, ...]
    user: str | None
    time_local: datetime
    method: str
    path: str
    protocol: str
    status: int
    body_bytes: int | None
    request_time: float | None
    upstream_time: float | None
    referer: str | None
    user_agent: str | None

    @property
    def endpoint(self) -> str:
        """Endpoint key: HTTP method plus normalized path."""
        return f"{self.method} {self.path}"


@dataclass
class ParseStats:
    """What the parser did with the input."""

    lines: int = 0
    parsed: int = 0
    malformed: int = 0
    excluded: int = 0

    def summary(self) -> str:
        return (
            f"lines={self.lines} parsed={self.parsed} "
            f"malformed={self.malformed} excluded={self.excluded}"
        )


def normalize_path(target: str) -> str:
    """Drop the query string and fragment, keeping the logged path."""
    path = target.split("?", 1)[0].split("#", 1)[0]
    return path or "/"


def _to_float(raw: str | None) -> float | None:
    if not raw or raw == "-":
        return None
    try:
        # Nginx lists one value per upstream attempt; keep the first.
        return float(raw.split(",", 1)[0])
    except ValueError:
        return None


def _to_optional(raw: str | None) -> str | None:
    return None if raw in (None, "", "-") else raw


def parse_line(line: str) -> LogEntry | None:
    """Parse one log line; `None` means it does not match a known layout."""
    match = _LINE.match(line)
    if match is None:
        return None
    fields = match.groupdict()
    try:
        time_local = datetime.strptime(fields["time_local"], _TIME_FORMAT)
    except ValueError:
        return None
    request = fields["request"].split()
    if not request or request[0] == "-":
        return None
    return LogEntry(
        remote_addr=fields["remote_addr"],
        forwarded_for=tuple(
            ip.strip() for ip in (fields["forwarded_for"] or "").split(",") if ip.strip()
        ),
        user=_to_optional(fields["user"]),
        time_local=time_local,
        method=request[0],
        path=normalize_path(request[1] if len(request) > 1 else "/"),
        protocol=request[2] if len(request) > 2 else "",
        status=int(fields["status"]),
        body_bytes=(
            None if fields["body_bytes"] == "-" else int(fields["body_bytes"])
        ),
        request_time=_to_float(fields["request_time"]),
        upstream_time=_to_float(fields["upstream_time"]),
        referer=_to_optional(fields["referer"]),
        user_agent=_to_optional(fields["user_agent"]),
    )


class LogParser:
    """Turns log lines into entries, skipping malformed and excluded ones."""

    def __init__(self, exclude: Iterable[str] = ()) -> None:
        self._exclude = tuple(exclude)
        self.stats = ParseStats()

    def parse_lines(self, lines: Iterable[str]) -> Iterator[LogEntry]:
        """Consume lines one at a time; nothing is buffered."""
        for line in lines:
            self.stats.lines += 1
            entry = parse_line(line)
            if entry is None:
                self.stats.malformed += 1
                log.debug("log_line_malformed", line=line[:200].rstrip())
                continue
            if any(fnmatch(entry.path, pattern) for pattern in self._exclude):
                self.stats.excluded += 1
                continue
            self.stats.parsed += 1
            yield entry

    def parse_file(self, path: str | Path) -> Iterator[LogEntry]:
        """Stream a log file without loading it into memory."""
        with open(path, encoding="utf-8", errors="replace") as stream:
            yield from self.parse_lines(stream)
