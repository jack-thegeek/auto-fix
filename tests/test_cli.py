import pytest
from typer.testing import CliRunner

from nginx_perf_agent import __version__
from nginx_perf_agent.cli import app
from nginx_perf_agent.config import get_settings

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
