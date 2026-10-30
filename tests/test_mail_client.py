"""IMAP client behaviour: connection, UID search, headers and retries."""

import imaplib

import pytest

from nginx_perf_agent.config import Settings
from nginx_perf_agent.mail import (
    ImapClient,
    ImapConfigError,
    ImapError,
    subject_matches,
)
from fake_imap import FakeImap, install, make_email

# Captured before the test suite replaces `imaplib.IMAP4` with a fake.
IMAP_ERROR = imaplib.IMAP4.error
IMAP_ABORT = imaplib.IMAP4.abort


@pytest.fixture(autouse=True)
def fake_imap(monkeypatch):
    return install(monkeypatch)


def settings(**overrides) -> Settings:
    values = {
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "imap_user": "monitor@example.com",
        "imap_password": "s3cret",
        "imap_mailbox": "INBOX",
        "imap_max_retries": 3,
        "imap_retry_delay": 0,
    }
    values.update(overrides)
    return Settings(**values)


def test_connects_with_ssl_and_opens_mailbox_read_only():
    client = ImapClient(settings())
    client.connect()
    conn = FakeImap.instances[-1]
    assert (conn.host, conn.port) == ("imap.example.com", 993)
    assert conn.timeout is not None
    assert conn.logins == [("monitor@example.com", "s3cret")]
    assert conn.selected == [("INBOX", True)]
    client.close()
    assert conn.closed


def test_plain_connection_when_ssl_disabled(monkeypatch):
    class NoSsl:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("SSL must not be used when NPA_IMAP_SSL=false")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", NoSsl)
    client = ImapClient(settings(imap_ssl=False))
    client.connect()
    assert FakeImap.instances
    client.close()


def test_missing_credentials_raise_config_error():
    with pytest.raises(ImapConfigError):
        ImapClient(settings(imap_password=None)).connect()


def test_login_failure_is_reported_as_imap_error(fake_imap):
    fake_imap.fail_next("login", IMAP_ERROR("bad credentials"))
    with pytest.raises(ImapError, match="login"):
        ImapClient(settings()).connect()


def test_password_is_not_in_settings_repr():
    assert "s3cret" not in repr(settings())
    assert "s3cret" not in str(settings())


@pytest.mark.parametrize(
    ("subject", "needle", "expected"),
    [
        ("Nginx 日志", "Nginx 日志", True),
        ("RE: nginx 日志 2026-10-29", "Nginx 日志", True),
        ("Nginx  日志", "nginx 日志", True),
        ("Weekly report", "Nginx 日志", False),
        ("", "Nginx 日志", False),
        ("anything", "  ", True),
    ],
)
def test_subject_matching(subject, needle, expected):
    assert subject_matches(subject, needle) is expected


def test_search_returns_uids_after_watermark(fake_imap):
    fake_imap.add(1, make_email())
    fake_imap.add(2, make_email())
    fake_imap.add(5, make_email())
    client = ImapClient(settings())
    assert client.search_uids(None) == ["1", "2", "5"]
    assert client.search_uids(2) == ["5"]
    # `n:*` echoes the highest UID even when it is below the watermark.
    assert client.search_uids(5) == []
    client.close()


def test_fetch_summary_decodes_headers(fake_imap):
    fake_imap.add(7, make_email(subject="Nginx 日志 2026"))
    client = ImapClient(settings())
    summary = client.fetch_summary("7")
    assert summary.uid == "7"
    assert summary.subject == "Nginx 日志 2026"
    assert summary.sender == "monitor@example.com"
    assert summary.received_at is not None
    assert summary.received_at.year == 2026
    client.close()


def test_status_counts_matching_messages(fake_imap):
    fake_imap.add(1, make_email(subject="Nginx 日志"))
    fake_imap.add(2, make_email(subject="unrelated"))
    fake_imap.add(3, make_email(subject="FWD: Nginx 日志"))
    client = ImapClient(settings())
    status = client.status()
    assert status.mailbox == "INBOX"
    assert status.messages == 3
    assert status.matching == 2
    assert status.last_uid == "3"
    client.close()


def test_reconnects_after_connection_abort(fake_imap):
    fake_imap.add(1, make_email())
    fake_imap.fail_next("search", IMAP_ABORT("connection dropped"))
    client = ImapClient(settings())
    assert client.search_uids(None) == ["1"]
    assert len(fake_imap.instances) == 2
    client.close()


def test_gives_up_after_max_retries(fake_imap):
    fake_imap.fail_next("search", IMAP_ABORT("down"))
    fake_imap.fail_next("search", IMAP_ABORT("down"))
    client = ImapClient(settings(imap_max_retries=2))
    with pytest.raises(ImapError, match="2 attempts"):
        client.search_uids(None)
    client.close()
