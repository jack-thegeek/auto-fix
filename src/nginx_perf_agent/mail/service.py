"""Turn matching monitoring emails into stored log attachments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, Integer, cast, func
from sqlalchemy.orm import Session, sessionmaker

from nginx_perf_agent.config import Settings
from nginx_perf_agent.db import (
    Attachment,
    EmailRecord,
    init_db,
    make_session_factory,
)
from nginx_perf_agent.log import get_logger
from nginx_perf_agent.mail.attachments import StoredFile, extract_attachments
from nginx_perf_agent.mail.client import ImapClient, subject_matches

log = get_logger(__name__)

STATUS_PROCESSING = "processing"
STATUS_PROCESSED = "processed"
STATUS_FAILED = "failed"


@dataclass
class ProcessResult:
    """Counters for one polling pass."""

    scanned: int = 0
    matched: int = 0
    processed: int = 0
    duplicates: int = 0
    failed: int = 0

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} matched={self.matched} "
            f"processed={self.processed} duplicates={self.duplicates} "
            f"failed={self.failed}"
        )


class MailProcessor:
    """Polls the mailbox and records every matched email in the database."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        client: ImapClient | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._client = client or ImapClient(settings)

    @property
    def client(self) -> ImapClient:
        return self._client

    def process_once(self) -> ProcessResult:
        """Scan emails newer than the last recorded UID; process matches."""
        result = ProcessResult()
        since_uid = self._last_uid()
        with self._client as client:
            for uid in client.search_uids(since_uid):
                result.scanned += 1
                summary = client.fetch_summary(uid)
                if not subject_matches(
                    summary.subject, self._settings.imap_subject_filter
                ):
                    log.debug("email_skipped", uid=uid, subject=summary.subject)
                    continue
                result.matched += 1
                outcome = self._process(client, uid, summary.subject, summary.sender,
                                        summary.received_at)
                if outcome == STATUS_PROCESSED:
                    result.processed += 1
                elif outcome == STATUS_FAILED:
                    result.failed += 1
                else:
                    result.duplicates += 1
        log.info(
            "mail_pass_finished",
            scanned=result.scanned,
            matched=result.matched,
            processed=result.processed,
            duplicates=result.duplicates,
            failed=result.failed,
        )
        return result

    # -- internals ------------------------------------------------------

    def _last_uid(self) -> int | None:
        """Highest UID already processed; failed emails stay behind it and retry."""
        # shortcut: UIDVALIDITY is not tracked, so a recreated mailbox can skip
        # old emails; add a mailbox-state table if that becomes a concern.
        with self._session_factory() as session:
            highest = (
                session.query(func.max(cast(EmailRecord.uid, Integer)))
                .filter(
                    EmailRecord.mailbox == self._settings.imap_mailbox,
                    EmailRecord.status == STATUS_PROCESSED,
                )
                .scalar()
            )
        return int(highest) if highest is not None else None

    def _process(
        self,
        client: ImapClient,
        uid: str,
        subject: str,
        sender: str | None,
        received_at: datetime | None,
    ) -> str:
        mailbox = self._settings.imap_mailbox
        email_id = self._begin(mailbox, uid, subject, sender, received_at)
        if email_id is None:
            log.info("email_duplicate", mailbox=mailbox, uid=uid)
            return "duplicate"

        try:
            message = client.fetch_message(uid)
            files = extract_attachments(
                message,
                self._settings.attachments_dir,
                self._settings.max_attachment_bytes,
            )
        except Exception as exc:  # one bad email must not stop the polling loop
            log.error("email_failed", mailbox=mailbox, uid=uid, error=str(exc))
            self._finish(email_id, STATUS_FAILED, str(exc))
            return STATUS_FAILED

        self._attach(email_id, files)
        self._finish(email_id, STATUS_PROCESSED, None)
        log.info("email_processed", mailbox=mailbox, uid=uid, attachments=len(files))
        return STATUS_PROCESSED

    def _begin(
        self,
        mailbox: str,
        uid: str,
        subject: str,
        sender: str | None,
        received_at: datetime | None,
    ) -> int | None:
        """Create or retry an email record; `None` means already processed."""
        with self._session_factory() as session:
            record = (
                session.query(EmailRecord)
                .filter_by(mailbox=mailbox, uid=uid)
                .one_or_none()
            )
            if record is not None and record.status == STATUS_PROCESSED:
                return None
            if record is None:
                record = EmailRecord(mailbox=mailbox, uid=uid, subject=subject)
                session.add(record)
            else:
                # Retry: drop leftovers from the previous partial run.
                session.query(Attachment).filter(
                    Attachment.email_id == record.id
                ).delete()
            record.subject = subject
            record.sender = sender
            record.received_at = received_at
            record.status = STATUS_PROCESSING
            record.error = None
            session.commit()
            return record.id

    def _attach(self, email_id: int, files: list[StoredFile]) -> None:
        with self._session_factory() as session:
            for file in files:
                if session.query(Attachment.id).filter_by(sha256=file.sha256).first():
                    log.info("attachment_duplicate", sha256=file.sha256)
                    continue
                session.add(
                    Attachment(
                        email_id=email_id,
                        filename=file.filename,
                        sha256=file.sha256,
                        size_bytes=file.size_bytes,
                        stored_path=str(file.stored_path),
                    )
                )
            session.commit()

    def _finish(self, email_id: int, status: str, error: str | None) -> None:
        with self._session_factory() as session:
            record = session.get(EmailRecord, email_id)
            if record is None:
                return
            record.status = status
            record.error = error[:2000] if error else None
            session.commit()


def open_processor(settings: Settings) -> tuple[Engine, MailProcessor]:
    """Create the database engine and a processor bound to it."""
    engine = init_db(settings.database_url)
    return engine, MailProcessor(settings, make_session_factory(engine))
