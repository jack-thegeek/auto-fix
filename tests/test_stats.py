"""Slow-request detection, endpoint aggregation and query summaries."""

import pytest

from nginx_perf_agent.analysis import (
    LogParser,
    PerformanceStats,
    load_internal_networks,
    normalize_endpoint_path,
    parse_line,
    priority_for,
    redact_query,
)

COMBINED = (
    '1.2.3.4 - - [10/Oct/2026:15:31:37 +0800] "GET /about HTTP/1.1" 200 10 "-" "ua"\n'
)


def line(target, seconds, status=200, method="GET", ts="10/Oct/2026:15:31:37 +0800"):
    return (
        f'1.2.3.4 - - [{ts}] "{method} {target} HTTP/1.1" {status} 10 {seconds} '
        '"-" "ua"\n'
    )


def stats_for(*lines, **kwargs):
    stats = PerformanceStats(**kwargs)
    stats.add_many(LogParser().parse_lines(lines))
    return stats.report()


def test_threshold_boundary_is_inclusive():
    report = stats_for(line("/a", "4.999"), line("/b", "5.0"))
    assert [request.path for request in report.slow_requests] == ["/b"]


def test_requests_below_threshold_do_not_count_as_slow():
    report = stats_for(line("/a", "1.0"), line("/a", "4.9"), line("/a", "6.0"))
    endpoint = report.endpoints[0]
    assert (endpoint.total_requests, endpoint.slow_requests) == (3, 1)


def test_configurable_threshold():
    report = stats_for(line("/a", "2.5"), slow_threshold=2.0)
    assert len(report.slow_requests) == 1
    assert report.slow_threshold == 2.0


def test_invalid_threshold_is_rejected():
    with pytest.raises(ValueError):
        PerformanceStats(slow_threshold=0)


def test_same_endpoint_with_different_queries_is_one_entry():
    report = stats_for(
        line("/api/orders/?page=1", "9.0"),
        line("/api/orders/?page=2", "7.0"),
        line("/api/orders/", "0.2"),
    )
    assert len(report.endpoints) == 1
    endpoint = report.endpoints[0]
    assert endpoint.path == "/api/orders/"
    assert endpoint.total_requests == 3
    assert endpoint.slow_requests == 2
    assert [request.url for request in report.slow_requests] == [
        "/api/orders/?page=1",
        "/api/orders/?page=2",
    ]


def test_methods_are_kept_separate():
    report = stats_for(
        line("/api/orders/", "6.0"),
        line("/api/orders/", "7.0", method="POST"),
    )
    assert {endpoint.endpoint for endpoint in report.endpoints} == {
        "GET /api/orders/",
        "POST /api/orders/",
    }


def test_slow_ratio_and_latency_aggregates():
    report = stats_for(
        line("/a", "0.5"),
        line("/a", "6.0"),
        line("/a", "10.0"),
        line("/a", "0.1"),
    )
    endpoint = report.endpoints[0]
    assert endpoint.total_requests == 4
    assert endpoint.slow_requests == 2
    assert endpoint.slow_ratio == pytest.approx(50.0)
    assert endpoint.max_response_time == pytest.approx(10.0)
    assert endpoint.avg_slow_response_time == pytest.approx(8.0)


def test_status_distribution_and_timestamps():
    report = stats_for(
        line("/a", "6.0", status=502, ts="10/Oct/2026:15:00:00 +0800"),
        line("/a", "7.0", status=504, ts="10/Oct/2026:16:00:00 +0800"),
        line("/a", "6.5", status=502, ts="10/Oct/2026:14:00:00 +0800"),
    )
    endpoint = report.endpoints[0]
    assert dict(endpoint.slow_statuses) == {502: 2, 504: 1}
    assert endpoint.first_slow.hour == 14
    assert endpoint.last_slow.hour == 16


def test_endpoints_sorted_by_priority_then_impact():
    report = stats_for(
        # busy: 60 requests, 3 slow -> 高, impact 6.0 * 5% = 0.30
        *(line("/busy", "0.1") for _ in range(57)),
        *(line("/busy", "6.0") for _ in range(3)),
        # quiet: 4 requests, 2 slow -> 中, impact 20.0 * 50% = 10.0
        line("/quiet", "0.1"),
        line("/quiet", "0.1"),
        line("/quiet", "20.0"),
        line("/quiet", "20.0"),
        # rare: 2 requests, 2 slow -> 低 (sample too small)
        line("/rare", "30.0"),
        line("/rare", "30.0"),
    )
    assert [endpoint.path for endpoint in report.endpoints] == [
        "/busy",
        "/quiet",
        "/rare",
    ]
    assert [endpoint.priority for endpoint in report.endpoints] == ["高", "中", "低"]


def test_priority_demotes_small_samples():
    assert priority_for(2, 2) == "低"
    assert priority_for(3, 1) == "低"
    assert priority_for(3, 3) == "中"
    assert priority_for(50, 5) == "高"


def test_internal_ratio_uses_the_forwarded_client(tmp_path):
    cidr = tmp_path / "cidr.txt"
    cidr.write_text("# office\n10.0.0.0/8\n", encoding="utf-8")
    networks = load_internal_networks(cidr)
    assert load_internal_networks(tmp_path / "missing.txt") == ()

    internal = (
        '43.1.2.3 Forwarded for 10.9.9.9 - - [10/Oct/2026:15:31:37 +0800] '
        '"GET /a HTTP/1.1" 200 10 6.0 "-" "ua"\n'
    )
    direct = (
        '10.1.2.3 - - [10/Oct/2026:15:31:37 +0800] '
        '"GET /a HTTP/1.1" 200 10 0.2 "-" "ua"\n'
    )
    external = (
        '43.1.2.3 - - [10/Oct/2026:15:31:37 +0800] '
        '"GET /a HTTP/1.1" 200 10 0.2 "-" "ua"\n'
    )
    stats = PerformanceStats(internal_networks=networks)
    stats.add_many(LogParser().parse_lines([internal, direct, external]))
    report = stats.report()

    assert report.internal_networks == 1
    assert report.endpoints[0].internal_requests == 2
    assert report.endpoints[0].internal_ratio == pytest.approx(66.67, abs=0.01)


def test_query_combinations_are_deduplicated():
    report = stats_for(
        line("/api/orders/?page=100&page_size=500", "12.8"),
        line("/api/orders/?page_size=500&page=100", "11.0"),
        line("/api/orders/?page=100&page_size=500", "9.0"),
        line("/api/orders/?status=pending", "8.4"),
    )
    groups = report.query_groups
    assert len(groups) == 2
    top = groups[0]
    assert top.query == "page=100&page_size=500"
    assert top.slow_requests == 3
    assert top.max_response_time == pytest.approx(12.8)


def test_queries_below_threshold_are_not_listed():
    report = stats_for(
        line("/api/orders/?page=1", "9.0"),
        line("/api/orders/?page=2", "0.3"),
        line("/api/orders/", "0.1"),
    )
    assert [group.query for group in report.query_groups] == ["page=1"]


def test_slow_requests_without_query_are_flagged():
    report = stats_for(line("/api/orders/", "9.0"), line("/api/orders/?page=1", "9.0"))
    assert [request.has_query for request in report.slow_requests] == [False, True]
    assert report.slow_requests[0].query == ""


def test_sensitive_query_values_are_redacted():
    report = stats_for(
        line("/api/login/?access_token=abc123&user=bob", "9.0"),
        line("/api/login/?access_token=def456&user=bob", "8.0"),
    )
    assert [group.query for group in report.query_groups] == [
        "access_token=***&user=bob"
    ]
    assert report.query_groups[0].slow_requests == 2
    # the record keeps the original URL; only the report-facing query is masked
    assert report.slow_requests[0].url == "/api/login/?access_token=abc123&user=bob"
    assert report.slow_requests[0].query == "access_token=***&user=bob"


def test_redact_query_masks_credentials_only():
    assert redact_query("page=2&api_key=secret&slug=x") == "api_key=***&page=2&slug=x"
    assert redact_query("keywords=nginx&search=1") == "keywords=nginx&search=1"


def test_missing_timing_is_counted_and_never_classified():
    report = stats_for(COMBINED, line("/a", "9.0"))
    assert report.requests == 2
    assert report.requests_missing_timing == 1
    assert report.timing_available is True
    assert len(report.slow_requests) == 1


def test_report_flags_logs_without_any_timing():
    report = stats_for(COMBINED, COMBINED.replace("/about", "/other"))
    assert report.requests == 2
    assert report.requests_missing_timing == 2
    assert report.timing_available is False
    assert report.slow_requests == ()
    assert report.endpoints == ()


def test_malformed_lines_are_not_counted_by_stats():
    parser = LogParser()
    entries = list(parser.parse_lines([line("/a", "6.0"), "garbage\n"]))
    stats = PerformanceStats()
    stats.add_many(entries)
    report = stats.report()
    assert report.requests == 1
    assert parser.stats.malformed == 1


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/orders/123/", "/api/orders/{id}/"),
        ("/api/users/8f14e45f-ceea-467a-9c1e-0d3e0c1a2b3c/", "/api/users/{id}/"),
        ("/api/users/user@example.com/", "/api/users/{id}/"),
        ("/api/quote/VB260101-1001abc/", "/api/quote/{code}/"),
        ("/api/bio/NM_000546.6/", "/api/bio/{accession}/"),
        ("/api/bio/ORF123/", "/api/bio/{accession}/"),
        ("/api/vector/pLV_2gRNA/config/", "/api/vector/{vector}/config/"),
        ("/about-us/careers.html", "/about-us/careers.html"),
        ("/", "/"),
    ],
)
def test_dynamic_segments_are_normalized(path, expected):
    assert normalize_endpoint_path(path) == expected


def test_dynamic_segments_merge_but_unknown_ones_do_not():
    report = stats_for(line("/api/orders/123/", "6.0"), line("/api/orders/456/", "7.0"))
    assert report.endpoints[0].path == "/api/orders/{id}/"
    assert report.endpoints[0].total_requests == 2

    literal = stats_for(line("/api/orders/abc/", "6.0"), line("/api/orders/def/", "7.0"))
    assert len(literal.endpoints) == 2


def test_upstream_time_is_reported_only_when_present():
    with_upstream = (
        '1.2.3.4 - - [10/Oct/2026:15:31:37 +0800] "GET /a HTTP/1.1" 200 10 9.0 4.5 '
        '"-" "ua"\n'
    )
    report = stats_for(with_upstream, line("/a", "8.0"))
    endpoint = report.endpoints[0]
    assert endpoint.slow_upstream_times == [4.5]
    assert endpoint.max_upstream_time == pytest.approx(4.5)
    assert report.slow_requests[1].upstream_time is None


def test_stats_stream_over_parsed_entries(tmp_path):
    path = tmp_path / "access.log"
    with open(path, "w", encoding="utf-8") as stream:
        stream.writelines(line("/a", "6.0") for _ in range(5_000))

    stats = PerformanceStats()
    stats.add_many(LogParser().parse_file(path))
    report = stats.report()
    assert report.endpoints[0].slow_requests == 5_000
    assert len(report.slow_requests) == 5_000


def test_parse_line_keeps_the_original_target():
    entry = parse_line(line("/api/orders/?page=2&x=1", "6.0"))
    assert entry is not None
    assert entry.target == "/api/orders/?page=2&x=1"
    assert entry.path == "/api/orders/"
