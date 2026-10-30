"""Minimal IMAP client wrapper around the standard library's `imaplib`.

The mailbox is always opened read-only, so emails are never deleted, moved
or marked as seen.
"""

from __future__ import annotations

import imaplib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import TypeVar

from nginx_perf_agent.config import Settings
from nginx_perf_agent.log import get_logger

log = get_logger(__name__)

CONNECT_TIMEOUT = 30.0
STATUS_SAMPLE = 200

# Captured at import time so tests can replace `imaplib.IMAP4` wholesale.
IMAP_ERROR = imaplib.IMAP4.error
IMAP_ABORT = imaplib.IMAP4.abort

T = TypeVar("T")


class ImapError(RuntimeError):
    """Raised when the IMAP connection cannot complete an operation."""


class ImapConfigError(ValueError):
    """Raised when IMAP settings are incomplete."""


def decode_mime(value: str | None) -> str:
    """Decode an RFC 2047 encoded header into readable text."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (ValueError, LookupError):
        return value


def subject_matches(subject: str, needle: str) -> bool:
    """Case-insensitive substring match, whitespace-normalized."""
    if not needle.strip():
        return True
    return " ".join(needle.split()).casefold() in " ".join(subject.split()).casefold()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MailSummary:
    """Headers of one email, enough to decide whether it is interesting."""

    uid: str
    subject: str
    sender: str | None
    received_at: datetime | None


@dataclass(frozen=True)
class MailboxStatus:
    mailbox: str
    messages: int
    matching: int
    last_uid: str | None


def _extract_payload(data: list[bytes | tuple[bytes, bytes]]) -> bytes:
    for item in data:
        if isinstance(item, tuple) and len(item) == 2:
            return bytes(item[1])
    raise ImapError("unexpected IMAP fetch response")


class ImapClient:
    """Read-only IMAP access with UID-based lookups and reconnect retries."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn: imaplib.IMAP4 | None = None

    @property
    def mailbox(self) -> str:
        return self._settings.imap_mailbox

    def __enter__(self) -> "ImapClient":
        return self.connect()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- connection -----------------------------------------------------

    def _open(self) -> None:
        s = self._settings
        if not (s.imap_host and s.imap_user and s.imap_password):
            raise ImapConfigError(
                "NPA_IMAP_HOST, NPA_IMAP_USER and NPA_IMAP_PASSWORD must be set"
            )
        factory = imaplib.IMAP4_SSL if s.imap_ssl else imaplib.IMAP4
        conn = factory(s.imap_host, s.imap_port, timeout=CONNECT_TIMEOUT)
        try:
            conn.login(s.imap_user, s.imap_password.get_secret_value())
            typ, data = conn.select(s.imap_mailbox, readonly=True)
        except IMAP_ERROR as exc:
            conn.shutdown()
            raise ImapError(f"IMAP login or mailbox selection failed: {exc}") from exc
        if typ != "OK":
            conn.shutdown()
            raise ImapError(f"cannot open mailbox {s.imap_mailbox!r}: {data!r}")
        self._conn = conn

    def connect(self) -> "ImapClient":
        self._call(lambda _conn: None, "connect")
        return self

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.logout()
        except (IMAP_ERROR, OSError):
            pass

    def _call(self, action: Callable[[imaplib.IMAP4], T], description: str) -> T:
        """Run `action`, reconnecting on connection-level failures."""
        attempts = self._settings.imap_max_retries
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if self._conn is None:
                    self._open()
                return action(self._conn)  # type: ignore[arg-type]
            except (IMAP_ABORT, OSError) as exc:
                last_error = exc
                self.close()
                log.warning(
                    "imap_retry",
                    operation=description,
                    attempt=attempt,
                    max_attempts=attempts,
                    error=str(exc),
                )
                if attempt < attempts and self._settings.imap_retry_delay:
                    time.sleep(self._settings.imap_retry_delay * attempt)
        raise ImapError(f"{description} failed after {attempts} attempts: {last_error}")

    # -- mailbox queries ------------------------------------------------

    def search_uids(self, since_uid: int | None = None) -> list[str]:
        """UIDs newer than `since_uid`; an unset value scans the whole mailbox."""
        start = (since_uid or 0) + 1

        def action(conn: imaplib.IMAP4) -> list[str]:
            typ, data = conn.uid("search", None, f"{start}:*")
            if typ != "OK":
                raise ImapError(f"search failed: {data!r}")
            uids = [uid.decode() for uid in (data[0] or b"").split()]
            # `n:*` also returns the highest UID even when it is below n.
            return [uid for uid in uids if int(uid) >= start]

        return self._call(action, f"search uids since {since_uid or 0}")

    def fetch_summary(self, uid: str) -> MailSummary:
        def action(conn: imaplib.IMAP4) -> MailSummary:
            typ, data = conn.uid(
                "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])"
            )
            if typ != "OK":
                raise ImapError(f"cannot read headers of uid {uid}: {data!r}")
            headers = message_from_bytes(_extract_payload(data))
            return MailSummary(
                uid=uid,
                subject=decode_mime(headers.get("Subject")),
                sender=decode_mime(headers.get("From")) or None,
                received_at=_parse_date(headers.get("Date")),
            )

        return self._call(action, f"fetch headers of uid {uid}")

    def fetch_message(self, uid: str) -> Message:
        """Download the full message body (attachments included)."""

        def action(conn: imaplib.IMAP4) -> Message:
            typ, data = conn.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK":
                raise ImapError(f"cannot download uid {uid}: {data!r}")
            return message_from_bytes(_extract_payload(data))

        return self._call(action, f"fetch message of uid {uid}")

    def status(self) -> MailboxStatus:
        """Mailbox counters for `mail-test`; never modifies the mailbox."""

        def action(conn: imaplib.IMAP4) -> int:
            typ, data = conn.select(self.mailbox, readonly=True)
            if typ != "OK":
                raise ImapError(f"cannot open mailbox {self.mailbox!r}: {data!r}")
            return int(data[0] or 0)

        messages = self._call(action, "select mailbox")
        uids = self.search_uids()
        recent = uids[-STATUS_SAMPLE:]
        matching = sum(
            1
            for uid in recent
            if subject_matches(
                self.fetch_summary(uid).subject, self._settings.imap_subject_filter
            )
        )
        return MailboxStatus(
            mailbox=self.mailbox,
            messages=messages,
            matching=matching,
            last_uid=uids[-1] if uids else None,
        )
