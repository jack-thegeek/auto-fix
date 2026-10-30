import gzip

import pytest
from typer.testing import CliRunner

import nginx_perf_agent.cli as cli
from fake_imap import FakeImap, install, make_email
from nginx_perf_agent import __version__
from nginx_perf_agent.cli import app
from nginx_perf_agent.config import Settings, get_settings

runner = CliRunner()


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("version", "config", "init-db"):
        assert command in result.stdout


def test_config_prints_effective_values(monkeypatch):
    monkeypatch.setenv("NPA_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("NPA_DATABASE_URL", "postgresql://user:secret@db:5432/app")
    get_settings.cache_clear()
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "log_level      = DEBUG" in result.stdout
    assert "postgresql://user:***@db:5432/app" in result.stdout
    assert "secret" not in result.stdout


def test_init_db_creates_database(monkeypatch, tmp_path):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("NPA_DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0, result.output
    assert "analysis_tasks" in result.stdout
    assert db_path.exists()


def test_invalid_config_exits_with_clean_error(monkeypatch):
    monkeypatch.setenv("NPA_LOG_LEVEL", "verbose")
    get_settings.cache_clear()
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 2
    assert "invalid configuration" in result.stderr
    assert "Traceback" not in result.output


def _mail_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NPA_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("NPA_IMAP_USER", "monitor@example.com")
    monkeypatch.setenv("NPA_IMAP_PASSWORD", "s3cret")
    monkeypatch.setenv("NPA_IMAP_RETRY_DELAY", "0")
    monkeypatch.setenv("NPA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NPA_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    get_settings.cache_clear()


def test_config_masks_imap_password(monkeypatch, tmp_path):
    _mail_env(monkeypatch, tmp_path)
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "imap_password  = ***" in result.stdout
    assert "s3cret" not in result.stdout


def test_mail_test_reports_mailbox(monkeypatch, tmp_path):
    install(monkeypatch)
    _mail_env(monkeypatch, tmp_path)
    FakeImap.add(1, make_email(subject="Nginx 日志"))
    FakeImap.add(2, make_email(subject="unrelated"))

    result = runner.invoke(app, ["mail-test"])

    assert result.exit_code == 0, result.output
    assert "mailbox   = INBOX" in result.stdout
    assert "messages  = 2" in result.stdout
    assert "matching  = 1" in result.stdout
    assert "s3cret" not in result.output


def test_mail_test_without_credentials_exits_cleanly(monkeypatch):
    # Never read the developer's real .env: this test must stay offline.
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    result = runner.invoke(app, ["mail-test"])
    assert result.exit_code == 1
    assert "mail test failed" in result.stderr
    assert "Traceback" not in result.output


def test_process_runs_one_pass(monkeypatch, tmp_path):
    install(monkeypatch)
    _mail_env(monkeypatch, tmp_path)
    FakeImap.add(
        1,
        make_email(attachments=(("access.log.gz", gzip.compress(b"GET / 200\n")),)),
    )

    result = runner.invoke(app, ["process"])

    assert result.exit_code == 0, result.output
    assert "scanned=1 matched=1 processed=1" in result.stdout
    assert (tmp_path / "cli.db").exists()
    assert list((tmp_path / "data" / "attachments").rglob("*.log"))


def test_process_requires_imap_configuration(monkeypatch, tmp_path):
    # Never read the developer's real .env: this test must stay offline.
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'cli.db'}"),
    )
    result = runner.invoke(app, ["process"])
    assert result.exit_code == 2
    assert "IMAP is not configured" in result.stderr


def test_watch_polls_until_interrupted(monkeypatch, tmp_path):
    install(monkeypatch)
    _mail_env(monkeypatch, tmp_path)
    FakeImap.add(1, make_email())
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: (_ for _ in ()).throw(
        KeyboardInterrupt
    ))

    result = runner.invoke(app, ["watch"])

    assert result.exit_code == 0, result.output
    assert "processed=1" in result.stdout
    assert "stopped" in result.stdout
