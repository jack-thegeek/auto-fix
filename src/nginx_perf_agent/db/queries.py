"""Read-only database lookups used outside the mail pipeline."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from nginx_perf_agent.db.models import Attachment, EmailRecord
from nginx_perf_agent.db.session import (
    SQLITE_PREFIX,
    create_engine_for,
    make_session_factory,
)

LANGUAGES = ("EN", "KR", "JP", "CN")
_TOKEN = re.compile(r"[A-Za-z0-9]+")


def language_from_subject(subject: str | None) -> str | None:
    """Site marker in an email subject: EN, KR, JP or CN as a standalone word."""
    tokens = set(_TOKEN.findall((subject or "").upper()))
    matches = [language for language in LANGUAGES if language in tokens]
    return matches[0] if len(matches) == 1 else None


def attachment_languages(database_url: str) -> dict[str, str]:
    """Map attachment sha256 to the language marker of its email.

    Returns an empty mapping when the database or tables are missing, so
    `analyze` keeps working on files that were never collected by email.
    """
    if database_url.startswith(SQLITE_PREFIX):
        path = Path(database_url[len(SQLITE_PREFIX) :])
        if not path.is_file():
            return {}

    engine = create_engine_for(database_url)
    try:
        with make_session_factory(engine)() as session:
            rows = session.execute(
                select(Attachment.sha256, EmailRecord.subject).join(
                    EmailRecord, Attachment.email_id == EmailRecord.id
                )
            )
            languages: dict[str, str] = {}
            for sha256, subject in rows:
                language = language_from_subject(subject)
                if language:
                    languages.setdefault(sha256, language)
            return languages
    except SQLAlchemyError:
        return {}
    finally:
        engine.dispose()
