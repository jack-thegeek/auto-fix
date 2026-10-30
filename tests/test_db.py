import pytest
from sqlalchemy.exc import IntegrityError

from nginx_perf_agent.db import (
    Attachment,
    EmailRecord,
    init_db,
    make_session_factory,
    table_names,
)


@pytest.fixture
def engine(tmp_path):
    eng = init_db(f"sqlite:///{tmp_path / 'sub' / 'test.db'}")
    yield eng
    eng.dispose()


def test_init_db_creates_tables_and_parent_dir(engine, tmp_path):
    assert table_names(engine) == ["analysis_tasks", "attachments", "emails"]
    assert (tmp_path / "sub" / "test.db").exists()


def test_init_db_is_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(url).dispose()
    engine = init_db(url)
    assert table_names(engine) == ["analysis_tasks", "attachments", "emails"]
    engine.dispose()


def test_email_with_attachment_roundtrip(engine):
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        email = EmailRecord(mailbox="INBOX", uid="42", subject="Nginx 日志")
        email.attachments.append(
            Attachment(
                filename="access.log",
                sha256="a" * 64,
                size_bytes=10,
                stored_path="/tmp/access.log",
            )
        )
        session.add(email)
        session.commit()

    with session_factory() as session:
        stored = session.query(EmailRecord).one()
        assert stored.uid == "42"
        assert stored.status == "pending"
        assert stored.created_at is not None
        assert [a.filename for a in stored.attachments] == ["access.log"]


def test_duplicate_attachment_hash_rejected(engine):
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        session.add(EmailRecord(mailbox="INBOX", uid="1", subject="Nginx 日志"))
        session.commit()
        for name in ("a.log", "b.log"):
            session.add(
                Attachment(
                    email_id=1,
                    filename=name,
                    sha256="b" * 64,
                    stored_path="/tmp/x",
                )
            )
        with pytest.raises(IntegrityError):
            session.commit()


def test_duplicate_email_uid_rejected(engine):
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        session.add_all(
            [
                EmailRecord(mailbox="INBOX", uid="7", subject="Nginx 日志"),
                EmailRecord(mailbox="INBOX", uid="7", subject="Nginx 日志"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()
