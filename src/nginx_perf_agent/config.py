"""Application configuration loaded from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Runtime settings. Environment variables use the `NPA_` prefix."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="NPA_",
        extra="ignore",
    )

    log_level: LogLevel = "INFO"
    log_json: bool = False
    data_dir: Path = Path("data")
    database_url: str = Field(default="sqlite:///data/nginx_perf.db", min_length=1)

    # IMAP mailbox (Phase 2). Credentials are optional so that non-mail
    # commands keep working; mail commands validate them.
    imap_host: str | None = None
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_ssl: bool = True
    imap_user: str | None = None
    imap_password: SecretStr | None = None
    imap_mailbox: str = "INBOX"
    imap_subject_filter: str = "Nginx 日志"
    imap_poll_interval: int = Field(default=300, ge=5)
    imap_max_retries: int = Field(default=3, ge=1, le=10)
    imap_retry_delay: float = Field(default=2.0, ge=0)

    # Attachment handling
    max_attachment_bytes: int = Field(default=256 * 1024 * 1024, ge=1)

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
