"""Language attribution from email subjects and attachment rows."""

from nginx_perf_agent.db import (
    Attachment,
    EmailRecord,
    attachment_languages,
    init_db,
    make_session_factory,
)
from nginx_perf_agent.db.queries import language_from_subject


def test_language_from_subject_reads_standalone_marker():
    assert language_from_subject("[告警][低] EN Nginx 日志安全分析报告") == "EN"
    assert language_from_subject("KR Nginx 日志性能分析报告") == "KR"
    assert language_from_subject("ENVIRONMENT Nginx 日志") is None
    assert language_from_subject("EN KR Nginx 日志") is None
    assert language_from_subject(None) is None


def test_attachment_languages_maps_sha_to_marker(tmp_path):
    url = f"sqlite:///{tmp_path}/perf.db"
    engine = init_db(url)
    with make_session_factory(engine)() as session:
        email = EmailRecord(
            mailbox="INBOX", uid="1", subject="[低] JP Nginx 日志", status="processed"
        )
        session.add(email)
        session.flush()
        session.add(
            Attachment(
                email_id=email.id,
                filename="jp.log",
                sha256="a" * 64,
                stored_path="data/attachments/aa/a.log",
                size_bytes=1,
            )
        )
        session.commit()
    engine.dispose()

    assert attachment_languages(url) == {"a" * 64: "JP"}
    assert attachment_languages(f"sqlite:///{tmp_path}/missing.db") == {}
