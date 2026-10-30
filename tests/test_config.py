import pytest
from pydantic import ValidationError

from nginx_perf_agent.config import Settings, get_settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.log_level == "INFO"
    assert settings.log_json is False
    assert settings.database_url == "sqlite:///data/nginx_perf.db"


def test_env_override(monkeypatch):
    monkeypatch.setenv("NPA_LOG_LEVEL", "debug")
    monkeypatch.setenv("NPA_LOG_JSON", "true")
    monkeypatch.setenv("NPA_DATABASE_URL", "sqlite:///tmp/x.db")
    settings = Settings(_env_file=None)
    assert settings.log_level == "DEBUG"
    assert settings.log_json is True
    assert settings.database_url == "sqlite:///tmp/x.db"


def test_invalid_log_level_rejected(monkeypatch):
    monkeypatch.setenv("NPA_LOG_LEVEL", "verbose")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_empty_database_url_rejected(monkeypatch):
    monkeypatch.setenv("NPA_DATABASE_URL", "")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


def test_ensure_data_dir(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "nested" / "data")
    assert settings.ensure_data_dir().is_dir()
