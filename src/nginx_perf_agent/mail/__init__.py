"""IMAP monitoring: connect, match subjects, extract and store attachments."""

from nginx_perf_agent.mail.attachments import (
    StoredFile,
    UnsafeAttachment,
    extract_attachments,
)
from nginx_perf_agent.mail.client import (
    IDLE_LIMIT,
    ImapClient,
    ImapConfigError,
    ImapError,
    MailboxStatus,
    MailSummary,
    decode_mime,
    subject_matches,
)
from nginx_perf_agent.mail.service import (
    STATUS_FAILED,
    STATUS_PROCESSED,
    STATUS_PROCESSING,
    MailProcessor,
    ProcessResult,
    open_processor,
)

__all__ = [
    "IDLE_LIMIT",
    "ImapClient",
    "ImapConfigError",
    "ImapError",
    "MailProcessor",
    "MailSummary",
    "MailboxStatus",
    "ProcessResult",
    "STATUS_FAILED",
    "STATUS_PROCESSED",
    "STATUS_PROCESSING",
    "StoredFile",
    "UnsafeAttachment",
    "decode_mime",
    "extract_attachments",
    "open_processor",
    "subject_matches",
]
