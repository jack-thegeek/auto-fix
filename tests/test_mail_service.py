"""End-to-end email processing against a mocked IMAP server."""

import gzip
import imaplib

import pytest

from nginx_perf_agent.config import Settings
from nginx_perf_agent.db import Attachment, EmailRecord, make_session_factory
from nginx_perf_agent.mail import open_processor
from fake_imap import FakeImap, install, make_email

IMAP_ABORT = imaplib.IMAP4.abort


@pytest.fixture(autouse=True)
def fake_imap(monkeypatch):
    return install(monkeypatch)


@pytest.fixture
def setup(tmp_path):
    settings = Settings(
        imap_host="imap.example.com",
        imap_user="monitor@example.com",
        imap_password="s3cret",
        imap_mailbox="INBOX",
        imap_max_retries=1,
        imap_retry_delay=0,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
    )
    engine, processor = open_processor(settings)
    yield settings, processor, make_session_factory(engine)
    engine.dispose()


def emails(session_factory) -> list[EmailRecord]:
    with session_factory() as session:
        return session.query(EmailRecord).order_by(EmailRecord.uid).all()


def attachments(session_factory) -> list[Attachment]:
    with session_factory() as session:
        return session.query(Attachment).all()


def test_matching_email_is_processed_with_its_attachment(setup):
    _, processor, session_factory = setup
    FakeImap.add(
        1, make_email(attachments=(("access.log.gz", gzip.compress(b"GET / 200\n")),))
    )

    result = processor.process_once()

    assert (result.scanned, result.matched, result.processed) == (1, 1, 1)
    assert result.failed == 0

    [email] = emails(session_factory)
    assert email.uid == "1"
    assert email.status == "processed"
    assert email.subject == "Nginx 日志"
    assert email.sender == "monitor@example.com"
    assert email.received_at is not None
    assert email.error is None

    [attachment] = attachments(session_factory)
    assert attachment.filename == "access.log"
    assert attachment.email_id == email.id
    assert attachment.stored_path.endswith(".log")
    from pathlib import Path

    assert Path(attachment.stored_path).read_bytes() == b"GET / 200\n"
    assert len(attachment.sha256) == 64


def test_non_matching_email_is_ignored(setup):
    _, processor, session_factory = setup
    FakeImap.add(1, make_email(subject="Weekly report"))

    result = processor.process_once()

    assert (result.scanned, result.matched) == (1, 0)
    assert emails(session_factory) == []


def test_second_pass_does_not_reprocess_the_same_email(setup):
    _, processor, session_factory = setup
    FakeImap.add(1, make_email())

    processor.process_once()
    second = processor.process_once()

    assert second.scanned == 0
    assert second.processed == 0
    assert len(emails(session_factory)) == 1


def test_duplicate_attachment_is_stored_once(setup):
    _, processor, session_factory = setup
    payload = gzip.compress(b"same access log\n")
    FakeImap.add(1, make_email(attachments=(("access.log.gz", payload),)))
    FakeImap.add(2, make_email(subject="Nginx 日志 again", attachments=(("copy.log.gz", payload),)))

    result = processor.process_once()

    assert result.processed == 2
    assert len(emails(session_factory)) == 2
    assert [a.filename for a in attachments(session_factory)] == ["access.log"]


def test_failed_email_is_retried_on_the_next_pass(setup):
    _, processor, session_factory = setup
    FakeImap.add(1, make_email(attachments=(("access.log.gz", gzip.compress(b"data")),)))
    FakeImap.fail_next("fetch", IMAP_ABORT("connection dropped"))

    first = processor.process_once()
    assert first.failed == 1
    [failed] = emails(session_factory)
    assert failed.status == "failed"
    assert "connection dropped" in (failed.error or "")
    assert attachments(session_factory) == []

    second = processor.process_once()
    assert (second.scanned, second.processed, second.failed) == (1, 1, 0)
    [email] = emails(session_factory)
    assert email.status == "processed"
    assert email.error is None
    assert len(attachments(session_factory)) == 1


def test_a_broken_email_does_not_stop_the_pass(setup):
    _, processor, session_factory = setup
    FakeImap.add(1, make_email(attachments=(("access.log.gz", gzip.compress(b"one")),)))
    FakeImap.add(2, make_email(attachments=(("access.log.gz", gzip.compress(b"two")),)))
    FakeImap.fail_next("fetch", IMAP_ABORT("boom"))

    result = processor.process_once()

    assert (result.scanned, result.processed, result.failed) == (2, 1, 1)
    assert {email.status for email in emails(session_factory)} == {"failed", "processed"}


def test_mailbox_is_only_read(setup):
    """The processor never deletes, moves or marks emails: the fake IMAP
    exposes no delete/store/expunge command, so any attempt would fail."""
    _, processor, _session_factory = setup
    FakeImap.add(1, make_email())

    processor.process_once()

    conn = FakeImap.instances[-1]
    assert conn.selected == [("INBOX", True)]
    assert conn.closed
