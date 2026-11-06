"""Weixin report delivery through the Hermes gateway."""

import subprocess

import pytest
from typer.testing import CliRunner

import nginx_perf_agent.cli as cli
import nginx_perf_agent.notify as notify
from nginx_perf_agent.cli import app
from nginx_perf_agent.config import Settings, get_settings
from nginx_perf_agent.notify import Delivery

runner = CliRunner()


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("NPA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NPA_DATABASE_URL", f"sqlite:///{tmp_path}/empty.db")
    monkeypatch.setenv("NPA_INTERNAL_CIDRS_FILE", str(tmp_path / "no-cidrs.txt"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_settings(tmp_path, **overrides):
    return Settings(_env_file=None, data_dir=tmp_path, **overrides)


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_send_text_uses_hermes_stdin(monkeypatch, tmp_path):
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls.update(kwargs)
        return Completed()

    monkeypatch.setattr(notify.subprocess, "run", fake_run)

    delivery = notify.send_text("hello", make_settings(tmp_path))

    assert delivery == Delivery("weixin", True, "5 chars")
    assert calls["command"] == ["hermes", "send", "--to", "weixin", "--file", "-"]
    assert calls["input"] == "hello"
    assert calls["timeout"] == 60
    assert calls["check"] is False


def test_send_text_honours_target_and_binary(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(
        notify.subprocess,
        "run",
        lambda command, **_: commands.append(command) or Completed(),
    )

    notify.send_text(
        "x",
        make_settings(
            tmp_path, hermes_bin="/opt/hermes", weixin_target="weixin:abc@im.wechat"
        ),
    )

    assert commands[0] == [
        "/opt/hermes",
        "send",
        "--to",
        "weixin:abc@im.wechat",
        "--file",
        "-",
    ]


def test_send_text_reports_gateway_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        notify.subprocess,
        "run",
        lambda *_, **__: Completed(returncode=1, stderr="gateway down"),
    )

    delivery = notify.send_text("x", make_settings(tmp_path))

    assert delivery.ok is False
    assert delivery.detail == "gateway down"


def test_send_text_reports_timeout(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(notify.subprocess, "run", fake_run)

    delivery = notify.send_text("x", make_settings(tmp_path, hermes_timeout=5))

    assert delivery.ok is False
    assert "timed out after 5s" in delivery.detail


def test_send_text_reports_missing_binary(monkeypatch, tmp_path):
    def fake_run(*_, **__):
        raise FileNotFoundError

    monkeypatch.setattr(notify.subprocess, "run", fake_run)

    delivery = notify.send_text("x", make_settings(tmp_path))

    assert delivery.ok is False
    assert "hermes not found" in delivery.detail


def test_long_text_is_passed_whole(monkeypatch, tmp_path):
    # The Weixin adapter chunks at 2000 chars; the report must not be cut here.
    text = "行" * 5000
    seen = {}
    monkeypatch.setattr(
        notify.subprocess,
        "run",
        lambda command, **kwargs: seen.update(kwargs) or Completed(),
    )

    delivery = notify.send_text(text, make_settings(tmp_path))

    assert delivery.ok
    assert seen["input"] == text


def test_notify_command_sends_report(monkeypatch, tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# 慢请求统计（EN）\n", encoding="utf-8")
    sent = []
    monkeypatch.setattr(
        notify.subprocess,
        "run",
        lambda command, **kwargs: sent.append(kwargs["input"]) or Completed(),
    )

    result = runner.invoke(app, ["notify", str(report)])

    assert result.exit_code == 0, result.output
    assert sent == ["# 慢请求统计（EN）\n"]
    assert "status    = sent (12 chars)" in result.stdout


def test_notify_command_rejects_missing_report(tmp_path):
    result = runner.invoke(app, ["notify", str(tmp_path / "absent.md")])

    assert result.exit_code == 1
    assert "no such report" in result.stderr


def test_analyze_notify_sends_report(monkeypatch, tmp_path):
    log = tmp_path / "access.log"
    log.write_text(
        '1.2.3.4 - - [10/Oct/2026:15:31:37 +0800] "GET /slow HTTP/1.1" 200 10 9.0 '
        '"-" "ua"\n',
        encoding="utf-8",
    )
    sent = []
    monkeypatch.setattr(
        cli,
        "send_text",
        lambda text, settings, target=None: (
            sent.append(text) or Delivery("weixin", True, "chars")
        ),
    )

    result = runner.invoke(app, ["analyze", str(log), "--notify"])

    assert result.exit_code == 0, result.output
    assert "weixin    = sent to weixin" in result.stdout
    assert sent and sent[0].startswith("# 慢请求统计")


def test_analyze_notify_failure_keeps_report(monkeypatch, tmp_path):
    log = tmp_path / "access.log"
    log.write_text(
        '1.2.3.4 - - [10/Oct/2026:15:31:37 +0800] "GET /slow HTTP/1.1" 200 10 9.0 '
        '"-" "ua"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "send_text",
        lambda *_, **__: Delivery("weixin", False, "gateway down"),
    )
    output = tmp_path / "report.md"

    result = runner.invoke(app, ["analyze", str(log), "-o", str(output), "--notify"])

    assert result.exit_code == 1
    assert output.exists()
    assert "weixin delivery failed: gateway down" in result.stderr
