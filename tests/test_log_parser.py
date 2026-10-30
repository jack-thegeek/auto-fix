"""Nginx log parsing: layouts, normalization, malformed input, exclusions."""

import io
from datetime import datetime, timedelta, timezone

import pytest

from nginx_perf_agent.analysis import LogParser, parse_line

COMBINED = (
    '1.2.3.4 - alice [10/Oct/2026:15:31:37 +0800] "GET /about-us/careers.html '
    'HTTP/1.1" 200 2476 "-" "curl/8.0"\n'
)
EXTENDED = (
    '1.2.3.4 - alice [10/Oct/2026:15:31:37 +0800] "POST /api/v1/quote/ '
    'HTTP/1.1" 201 42 0.386 "https://example.com/cart" "Mozilla/5.0"\n'
)
EXTENDED_UPSTREAM = (
    '1.2.3.4 - - [10/Oct/2026:15:31:37 +0800] "GET /api/v1/info/ HTTP/1.1" '
    '200 17 0.035 0.021 "-" "Mozilla/5.0"\n'
)
SITE_FORMAT = (
    "43.198.72.86 Forwarded for 130.209.48.203 - alberto@example.ac.uk "
    '[10/Oct/2026:15:31:37 +0800] "GET /api/v1/public/vector-data/'
    '?inquiry=true&slug=VB250813-1235rtt HTTP/1.0" 200 67057 0.130 '
    '"https://en.example.com/vector/VB250813-1235rtt.html" "Mozilla/5.0 (Windows '
    'NT 10.0; Win64; x64) Chrome/153.0.0.0 Safari/537.36"\n'
)
SITE_FORMAT_MULTI_XFF = (
    "43.198.72.86 Forwarded for 4.25.27.3, 205.220.46.216 - justin@example.com "
    '[13/Oct/2026:01:17:22 +0800] "GET /tool/orf-search.html HTTP/1.0" 200 '
    '173105 0.165 "-" "Mozilla/5.0"\n'
)


def test_combined_line_parses_without_timing_fields():
    entry = parse_line(COMBINED)
    assert entry is not None
    assert (entry.method, entry.path, entry.status) == ("GET", "/about-us/careers.html", 200)
    assert entry.body_bytes == 2476
    assert entry.request_time is None
    assert entry.upstream_time is None
    assert entry.user == "alice"
    assert entry.referer is None
    assert entry.time_local == datetime(
        2026, 10, 10, 15, 31, 37, tzinfo=timezone(timedelta(hours=8))
    )


def test_extended_line_parses_request_time():
    entry = parse_line(EXTENDED)
    assert entry is not None
    assert (entry.method, entry.path, entry.status) == ("POST", "/api/v1/quote/", 201)
    assert entry.request_time == pytest.approx(0.386)
    assert entry.upstream_time is None
    assert entry.referer == "https://example.com/cart"


def test_upstream_response_time_is_parsed_when_present():
    entry = parse_line(EXTENDED_UPSTREAM)
    assert entry is not None
    assert entry.request_time == pytest.approx(0.035)
    assert entry.upstream_time == pytest.approx(0.021)


def test_upstream_time_lists_keep_the_first_value():
    line = EXTENDED_UPSTREAM.replace("0.035 0.021", "0.035 0.100, 0.021")
    entry = parse_line(line)
    assert entry is not None
    assert entry.upstream_time == pytest.approx(0.100)


def test_site_format_with_forwarded_for():
    entry = parse_line(SITE_FORMAT)
    assert entry is not None
    assert entry.remote_addr == "43.198.72.86"
    assert entry.forwarded_for == ("130.209.48.203",)
    assert entry.user == "alberto@example.ac.uk"
    assert entry.path == "/api/v1/public/vector-data/"
    assert entry.request_time == pytest.approx(0.130)


def test_forwarded_for_with_several_addresses():
    entry = parse_line(SITE_FORMAT_MULTI_XFF)
    assert entry is not None
    assert entry.forwarded_for == ("4.25.27.3", "205.220.46.216")
    assert entry.user_agent == "Mozilla/5.0"


def test_query_string_is_removed_from_the_path():
    entry = parse_line(SITE_FORMAT)
    assert entry is not None
    assert "?" not in entry.path
    assert "slug" not in entry.path


def test_missing_body_bytes_is_none():
    line = COMBINED.replace(" 200 2476 ", " 200 - ")
    entry = parse_line(line)
    assert entry is not None
    assert entry.body_bytes is None


@pytest.mark.parametrize(
    "line",
    [
        "",
        "\n",
        "not a log line at all\n",
        '1.2.3.4 - - [10/Oct/2026:15:31:37 +0800] "GET / HTTP/1.1" 200\n',
        '1.2.3.4 - - [not-a-time] "GET / HTTP/1.1" 200 1 "-" "ua"\n',
        '1.2.3.4 - - [10/Oct/2026:15:31:37 +0800] "-" 400 0 "-" "ua"\n',
        "\x00\x01binary\x02\n",
    ],
)
def test_malformed_lines_are_rejected(line):
    assert parse_line(line) is None


def test_parser_counts_malformed_lines_and_keeps_going():
    lines = [COMBINED, "garbage\n", EXTENDED]
    parser = LogParser()
    entries = list(parser.parse_lines(lines))
    assert len(entries) == 2
    assert parser.stats.lines == 3
    assert parser.stats.parsed == 2
    assert parser.stats.malformed == 1
    assert parser.stats.excluded == 0


def test_endpoints_are_grouped_by_method():
    parser = LogParser()
    entries = list(parser.parse_lines([COMBINED, EXTENDED]))
    assert {entry.endpoint for entry in entries} == {
        "GET /about-us/careers.html",
        "POST /api/v1/quote/",
    }


def test_exclusions_use_path_globs():
    parser = LogParser(exclude=["/health", "/static/*"])
    lines = [
        COMBINED,
        COMBINED.replace("/about-us/careers.html", "/health"),
        COMBINED.replace("/about-us/careers.html", "/static/app.css"),
    ]
    entries = list(parser.parse_lines(lines))
    assert [entry.path for entry in entries] == ["/about-us/careers.html"]
    assert parser.stats.excluded == 2
    assert parser.stats.parsed == 1


def test_large_input_is_streamed_line_by_line(tmp_path):
    path = tmp_path / "access.log"
    line = SITE_FORMAT
    with open(path, "w", encoding="utf-8") as stream:
        stream.writelines(line for _ in range(20_000))

    parser = LogParser()
    count = sum(1 for _ in parser.parse_file(path))

    assert count == 20_000
    assert parser.stats.malformed == 0


def test_parse_lines_accepts_a_stream():
    parser = LogParser()
    entries = list(parser.parse_lines(io.StringIO(COMBINED + EXTENDED)))
    assert len(entries) == 2
