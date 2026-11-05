"""Markdown report rendering and the `analyze` CLI command."""

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from nginx_perf_agent.analysis import (
    UNCLASSIFIED,
    analyze_paths,
    group_files_by_language,
    render_markdown,
)
from nginx_perf_agent.cli import app
from nginx_perf_agent.config import get_settings

runner = CliRunner()
STAMP = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch, tmp_path):
    # Keep CLI tests independent of whatever internal_cidrs.txt or database
    # exists locally.
    monkeypatch.setenv("NPA_INTERNAL_CIDRS_FILE", str(tmp_path / "no-cidrs.txt"))
    monkeypatch.setenv("NPA_DATABASE_URL", f"sqlite:///{tmp_path}/empty.db")
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


def test_report_header_shows_slow_share(tmp_path):
    path = write_log(tmp_path, [line("/a", "0.2"), line("/a", "6.0")])
    result = analyze_paths([path])
    text = render_markdown(result, generated_at=STAMP)

    assert "# 慢请求统计" in text
    assert "- 生成时间：2026-11-03 12:00:00" in text
    assert "- 慢请求/总请求占比：1/2（50.0%）" in text
    assert "| 接口 | 优先级 |" in text


def test_report_ranks_slow_endpoints(tmp_path):
    path = write_log(
        tmp_path,
        [line("/fast", "0.1"), line("/slow", "9.5"), line("/slow", "6.0")],
    )
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)

    assert "## Top 10 慢请求" in text
    assert "| 接口 | 优先级 | 慢请求/总请求 | 慢率 | 内部调用占比 | 慢请求平均时间 | 最慢用时 |" in text
    assert "| GET /slow | 低 | 2/2 | 100.0% | - | 7.75s | 9.50s |" in text
    assert "/fast" not in text


def test_report_flags_missing_timing(tmp_path):
    path = write_log(tmp_path, [COMBINED])
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)

    assert "没有耗时 ≥ 5.00s 的请求。" in text


def test_query_section_is_last_and_masks_credentials(tmp_path):
    path = write_log(
        tmp_path,
        [line("/api/orders/?page=100&token=secret", "12.8")],
    )
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)

    assert "## 慢查询参数" in text
    assert "`page=100&token=***`" in text
    assert "secret" not in text.split("## 慢查询参数")[1]
    assert text.rstrip().endswith("| 1 | 12.80s |")


def test_query_section_without_queries(tmp_path):
    path = write_log(tmp_path, [line("/api/orders/", "9.0")])
    text = render_markdown(analyze_paths([path]), generated_at=STAMP)
    assert "没有慢请求携带查询参数。" in text


def test_top_option_truncates_and_says_so(tmp_path):
    path = write_log(tmp_path, [line(f"/slow-{index}", "9.0") for index in range(5)])
    text = render_markdown(analyze_paths([path]), top=2, generated_at=STAMP)
    assert "仅显示前 2 个，共 5 个慢接口。" in text


def test_group_files_by_language_uses_attachment_hash(tmp_path):
    english = write_log(tmp_path, [line("/a", "6.0")], name=f"{'a' * 64}.log")
    chinese = write_log(tmp_path, [line("/b", "6.0")], name=f"{'b' * 64}.log")
    unknown = write_log(tmp_path, [line("/c", "6.0")], name="local.log")

    groups = group_files_by_language(
        [english, chinese, unknown], {"a" * 64: "EN", "b" * 64: "CN"}
    )

    assert groups == {"EN": [english], "CN": [chinese], UNCLASSIFIED: [unknown]}


def test_report_heading_carries_the_language(tmp_path):
    path = write_log(tmp_path, [line("/a", "6.0")])
    text = render_markdown(analyze_paths([path]), generated_at=STAMP, label="KR")
    assert text.startswith("# 慢请求统计（KR）")


def test_analyze_cli_splits_reports_by_language(monkeypatch, tmp_path):
    monkeypatch.setenv("NPA_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    english = write_log(tmp_path, [line("/en", "9.0")], name=f"{'a' * 64}.log")
    chinese = write_log(tmp_path, [line("/cn", "9.0")], name=f"{'b' * 64}.log")
    monkeypatch.setattr(
        "nginx_perf_agent.cli.attachment_languages",
        lambda _url: {"a" * 64: "EN", "b" * 64: "CN"},
    )
    output = tmp_path / "reports" / "report.md"

    result = runner.invoke(
        app, ["analyze", str(english), str(chinese), "-o", str(output)]
    )

    assert result.exit_code == 0, result.output
    english_report = (tmp_path / "reports" / "report-en.md").read_text(encoding="utf-8")
    chinese_report = (tmp_path / "reports" / "report-cn.md").read_text(encoding="utf-8")
    assert english_report.startswith("# 慢请求统计（EN）")
    assert chinese_report.startswith("# 慢请求统计（CN）")
    assert "/en" in english_report and "/cn" not in english_report
    assert "/cn" in chinese_report and "/en" not in chinese_report


def test_analyze_keeps_only_the_last_24_hours(tmp_path):
    path = write_log(
        tmp_path,
        [
            line("/old", "9.0", ts="08/Oct/2026:09:00:00 +0800"),
            line("/edge", "9.0", ts="09/Oct/2026:09:00:00 +0800"),
            line("/new", "9.0", ts="10/Oct/2026:09:00:00 +0800"),
        ],
    )
    result = analyze_paths([path])
    # 24h before the newest line is included, anything earlier is dropped.
    assert [stats.path for stats in result.report.endpoints] == ["/edge", "/new"]
    assert analyze_paths([path], hours=0).report.requests == 3


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
    assert "| 接口 | 优先级 |" in text
    assert "report    = " in result.stdout
    assert "window    = last 24h" in result.stdout
    assert "slow      = 1 (>= 5.0s)" in result.stdout
    assert "networks  = 0 internal CIDR(s)" in result.stdout


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
