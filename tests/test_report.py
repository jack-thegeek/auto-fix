"""Markdown report rendering and the `analyze` CLI command."""

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from nginx_perf_agent.analysis import analyze_paths, render_markdown
from nginx_perf_agent.cli import app
from nginx_perf_agent.config import get_settings

runner = CliRunner()
STAMP = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def line(target, seconds, status=200, method="GET", ts="10/Oct/2026:15:31:37 +0800"):
    return (
        f'1.2.3.4 - - [{ts}] "{method} {target} HTTP/1.1" {status} 10 {seconds} '
        '"-" "ua"\n'
    )


COMBINED = (
    '1.2.3.4 - - [10/Oct/2026:15:31:37 +0800] "GET /no-timing HTTP/1.1" 200 10 '
    '"-" "ua"\n'
)


def write_log(tmp_path, lines, name="access.log"):
    path = tmp_path / name
    path.write_text("".join(lines), encoding="utf-8")
    return path


def test_report_includes_file_metadata(tmp_path):
    path = write_log(tmp_path, [line("/a", "0.2"), line("/a", "6.0")])
    result = analyze_paths([path])
    text = render_markdown(result, generated_at=STAMP)

    assert "# Nginx performance report" in text
    assert "Generated: 2026-11-03 12:00:00" in text
    assert str(path) in text
    assert "| Lines | Parsed | Malformed | Excluded |" in text


def test_report_includes_overall_statistics(tmp_path):
    path = write_log(tmp_path, [line("/a", "0.2"), line("/b", "1.0", status=500)])
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)

    assert "## Overall statistics" in text
    assert "| Requests | 2 |" in text
    assert "| Endpoints | 2 |" in text
    assert "| Errors (4xx/5xx) | 1 |" in text


def test_report_ranks_slow_endpoints(tmp_path):
    path = write_log(
        tmp_path,
        [line("/fast", "0.1"), line("/slow", "9.5"), line("/slow", "6.0")],
    )
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)

    assert "## Slow endpoints (>= 5.000s)" in text
    assert "| 1 | GET | /slow | 2 | 2 | 100.00% | 9.500s | 7.750s |" in text
    assert "/fast" not in text


def test_report_analyses_errors(tmp_path):
    path = write_log(
        tmp_path,
        [
            line("/a", "0.1", status=502),
            line("/a", "0.2", status=502),
            line("/b", "0.1", status=404),
            line("/c", "0.1", status=200),
        ],
    )
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)

    assert "## Error analysis" in text
    assert "| 404 | 1 | 33.33% |" in text
    assert "| 502 | 2 | 66.67% |" in text
    assert "### Endpoints by errors" in text
    assert "| GET | /a | 2 | 100.00% | 502 |" in text


def test_report_has_no_error_section_noise_without_errors(tmp_path):
    path = write_log(tmp_path, [line("/a", "0.1")])
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)
    assert "No 4xx or 5xx responses." in text


def test_percentiles_come_from_observations(tmp_path):
    times = ["0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "10.0"]
    path = write_log(tmp_path, [line("/a", value) for value in times])
    result = analyze_paths([path])

    latency = result.report.latency
    assert latency is not None
    assert latency.count == 10
    assert latency.minimum == pytest.approx(0.1)
    assert latency.maximum == pytest.approx(10.0)
    assert latency.percentiles == {50: 0.5, 90: 0.9, 95: 10.0, 99: 10.0}


def test_report_flags_missing_timing(tmp_path):
    path = write_log(tmp_path, [COMBINED])
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)

    assert "**Timing unavailable**" in text
    assert "never estimated" in text
    assert "## Slow endpoints (>= 5.000s)" in text
    assert "No request took 5.000s or longer." in text


def test_report_notes_partial_missing_timing(tmp_path):
    path = write_log(tmp_path, [COMBINED, line("/a", "6.0")])
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)
    assert "1 request(s) had no valid `$request_time`" in text


def test_query_section_is_last_and_masks_credentials(tmp_path):
    path = write_log(
        tmp_path,
        [line("/api/orders/?page=100&token=secret", "12.8")],
    )
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)

    assert "## Slow query parameters" in text
    assert "`page=100&token=***`" in text
    assert "secret" not in text.split("## Slow query parameters")[1]
    assert text.rstrip().endswith("| 1 | 12.800s |")


def test_query_section_without_queries(tmp_path):
    path = write_log(tmp_path, [line("/api/orders/", "9.0")])
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)
    assert "No slow request carried query parameters." in text


def test_top_option_truncates_and_says_so(tmp_path):
    path = write_log(tmp_path, [line(f"/slow-{index}", "9.0") for index in range(5)])
    text = render_markdown(analyze_paths([path]), top=2, generated_at=STAMP)
    assert "Showing the top 2 of 5 slow endpoints." in text


def test_analyze_expands_directories(tmp_path):
    write_log(tmp_path, [line("/a", "0.1")], name="one.log")
    write_log(tmp_path, [line("/b", "6.0")], name="two.log")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    result = analyze_paths([tmp_path])

    assert len(result.files) == 2
    assert result.report.requests == 2


def test_analyze_rejects_missing_paths(tmp_path):
    with pytest.raises(FileNotFoundError):
        analyze_paths([tmp_path / "missing.log"])


def test_analyze_applies_exclusions(tmp_path):
    path = write_log(tmp_path, [line("/health", "9.0"), line("/a", "9.0")])
    result = analyze_paths([path], exclude=["/health"])
    assert [stats.path for stats in result.report.endpoints] == ["/a"]


def test_analyze_cli_writes_report(monkeypatch, tmp_path):
    monkeypatch.setenv("NPA_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    path = write_log(tmp_path, [line("/slow", "9.0")])
    output = tmp_path / "reports" / "report.md"

    result = runner.invoke(app, ["analyze", str(path), "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "## Slow endpoints" in text
    assert "report    = " in result.stdout
    assert "slow      = 1 (>= 5.0s)" in result.stdout


def test_analyze_cli_default_output_path(monkeypatch, tmp_path):
    monkeypatch.setenv("NPA_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    path = write_log(tmp_path, [line("/a", "0.1")])

    result = runner.invoke(app, ["analyze", str(path)])

    assert result.exit_code == 0, result.output
    assert list((tmp_path / "data" / "reports").glob("nginx-perf-*.md"))


def test_analyze_cli_overrides_threshold(monkeypatch, tmp_path):
    monkeypatch.setenv("NPA_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    path = write_log(tmp_path, [line("/a", "2.5")])
    output = tmp_path / "r.md"

    result = runner.invoke(
        app, ["analyze", str(path), "-o", str(output), "--slow-threshold", "2"]
    )

    assert result.exit_code == 0, result.output
    assert "slow      = 1 (>= 2.0s)" in result.stdout


def test_analyze_cli_reports_missing_files(monkeypatch, tmp_path):
    monkeypatch.setenv("NPA_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    result = runner.invoke(app, ["analyze", str(tmp_path / "nope.log")])
    assert result.exit_code == 1
    assert "analysis failed" in result.stderr
    assert "Traceback" not in result.output
