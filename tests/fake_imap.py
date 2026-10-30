"""In-memory `imaplib.IMAP4_SSL` replacement for the test suite."""

from __future__ import annotations

import imaplib
from email.message import EmailMessage


def make_email(
    subject: str = "Nginx 日志",
    sender: str = "monitor@example.com",
    date: str = "Thu, 29 Oct 2026 10:00:00 +0000",
    attachments: tuple[tuple[str, bytes], ...] = (),
) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["Date"] = date
    message.set_content("attached as requested")
    for name, payload in attachments:
        message.add_attachment(
            payload, maintype="application", subtype="octet-stream", filename=name
        )
    return message.as_bytes()


class FakeImap:
    """Enough of the `imaplib.IMAP4` surface for the mail client."""

    instances: list["FakeImap"] = []
    messages: dict[str, bytes] = {}
    failures: dict[str, list[Exception]] = {}

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.messages = {}
        cls.failures = {}

    @classmethod
    def add(cls, uid: int, raw: bytes) -> None:
        cls.messages[str(uid)] = raw

    @classmethod
    def fail_next(cls, operation: str, exc: Exception) -> None:
        FakeImap.failures.setdefault(operation, []).append(exc)

    def __init__(self, host: str = "", port: int = 993, timeout: float | None = None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logins: list[tuple[str, str]] = []
        self.selected: list[tuple[str, bool]] = []
        self.closed = False
        self.search_criteria: list[str] = []
        FakeImap.instances.append(self)

    def _maybe_fail(self, operation: str) -> None:
        queued = FakeImap.failures.get(operation)
        if queued:
            raise queued.pop(0)

    def login(self, user: str, password: str):
        self._maybe_fail("login")
        self.logins.append((user, password))
        return "OK", [b"logged in"]

    def select(self, mailbox: str = "INBOX", readonly: bool = False):
        self._maybe_fail("select")
        self.selected.append((mailbox, readonly))
        return "OK", [str(len(FakeImap.messages)).encode()]

    def uid(self, command: str, *args: object):
        operation = command
        if command == "fetch":
            operation = "fetch_headers" if "HEADER" in str(args[1]) else "fetch"
        self._maybe_fail(operation)
        if command == "search":
            criteria = str(args[-1])
            self.search_criteria.append(criteria)
            start = int(criteria.split(":")[0])
            uids = sorted(int(uid) for uid in FakeImap.messages)
            selected = [uid for uid in uids if uid >= start]
            if not selected and uids:
                # Real servers return the highest UID for `n:*` even if it is lower.
                selected = [uids[-1]]
            return "OK", [" ".join(str(uid) for uid in selected).encode()]
        if command == "fetch":
            uid = str(args[0])
            return "OK", [
                (f"1 (UID {uid} BODY[])", FakeImap.messages[uid]),
                b")",
            ]
        raise AssertionError(f"unexpected IMAP command: {command}")

    def logout(self):
        self.closed = True
        return "BYE", [b"bye"]

    def shutdown(self) -> None:
        self.closed = True


def install(monkeypatch) -> type[FakeImap]:
    """Route the stdlib IMAP constructors to `FakeImap`."""
    FakeImap.reset()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeImap)
    monkeypatch.setattr(imaplib, "IMAP4", FakeImap)
    return FakeImap
