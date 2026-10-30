"""Attachment extraction, archive expansion and content-addressed storage."""

from __future__ import annotations

import gzip
import hashlib
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from email.message import Message
from pathlib import Path, PurePosixPath

from nginx_perf_agent.log import get_logger
from nginx_perf_agent.mail.client import decode_mime

log = get_logger(__name__)

LOG_SUFFIXES = frozenset({".log", ".txt"})
ARCHIVE_SUFFIXES = frozenset({".gz", ".zip"})
MAX_DEPTH = 2
CHUNK = 1024 * 1024


class UnsafeAttachment(ValueError):
    """Raised when an attachment or archive member cannot be read safely."""


@dataclass(frozen=True)
class StoredFile:
    filename: str
    sha256: str
    size_bytes: int
    stored_path: Path


def safe_member_name(name: str) -> str:
    """Reduce an archive member name to a plain file name or reject it."""
    cleaned = name.replace("\\", "/").strip()
    if not cleaned:
        raise UnsafeAttachment("archive member has an empty name")
    path = PurePosixPath(cleaned)
    if path.is_absolute() or any(part in ("..", "") for part in path.parts):
        raise UnsafeAttachment(f"unsafe archive member path: {name!r}")
    if path.name in ("", ".", ".."):
        raise UnsafeAttachment(f"unsafe archive member path: {name!r}")
    return path.name


def iter_email_parts(message: Message) -> Iterator[tuple[str, bytes]]:
    """Yield `(filename, payload)` for every attachment in a message."""
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = decode_mime(part.get_filename())
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        yield filename, payload


def _read_limited(stream: object, max_bytes: int, label: str) -> bytes:
    """Read a stream in chunks, refusing payloads above `max_bytes`."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(CHUNK)  # type: ignore[attr-defined]
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UnsafeAttachment(f"archive expands beyond {max_bytes} bytes: {label!r}")
        chunks.append(chunk)
    return b"".join(chunks)


def _expand(
    filename: str, payload: bytes, max_bytes: int, depth: int
) -> Iterator[tuple[str, bytes]]:
    """Recursively unpack `.gz`/`.zip` payloads; yields leaf files."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ARCHIVE_SUFFIXES:
        yield filename, payload
        return
    if depth >= MAX_DEPTH:
        raise UnsafeAttachment(f"archive nesting too deep: {filename!r}")
    if suffix == ".gz":
        inner_name = filename[: -len(".gz")] or filename
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
                data = _read_limited(stream, max_bytes, filename)
        except (OSError, EOFError) as exc:
            raise UnsafeAttachment(f"cannot decompress {filename!r}: {exc}") from exc
        yield from _expand(inner_name, data, max_bytes, depth + 1)
        return

    total = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise UnsafeAttachment(f"cannot open zip {filename!r}: {exc}") from exc
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UnsafeAttachment(f"refusing symlink in archive: {info.filename!r}")
            member = safe_member_name(info.filename)
            total += info.file_size
            if total > max_bytes:
                raise UnsafeAttachment(
                    f"archive expands beyond {max_bytes} bytes: {filename!r}"
                )
            try:
                with archive.open(info) as stream:
                    data = _read_limited(stream, max_bytes, info.filename)
            except (OSError, EOFError, RuntimeError, zipfile.BadZipFile) as exc:
                raise UnsafeAttachment(f"cannot extract {info.filename!r}: {exc}") from exc
            yield from _expand(member, data, max_bytes, depth + 1)


def store_payload(store_dir: Path, filename: str, payload: bytes) -> StoredFile:
    """Write a payload under its SHA256, skipping the write when present."""
    digest = hashlib.sha256(payload).hexdigest()
    suffix = Path(filename).suffix.lower()
    target = store_dir / digest[:2] / f"{digest}{suffix}"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(payload)
        partial.replace(target)
    return StoredFile(
        filename=filename,
        sha256=digest,
        size_bytes=len(payload),
        stored_path=target,
    )


def extract_attachments(
    message: Message, store_dir: Path, max_bytes: int
) -> list[StoredFile]:
    """Store log attachments of a message, deduplicated by content hash."""
    stored: dict[str, StoredFile] = {}
    for filename, payload in iter_email_parts(message):
        try:
            leaves = list(_expand(filename, payload, max_bytes, depth=0))
        except UnsafeAttachment as exc:
            log.warning("attachment_rejected", filename=filename, reason=str(exc))
            continue
        for leaf_name, leaf_payload in leaves:
            if Path(leaf_name).suffix.lower() not in LOG_SUFFIXES:
                log.info(
                    "attachment_skipped", filename=leaf_name, reason="unsupported type"
                )
                continue
            file = store_payload(store_dir, leaf_name, leaf_payload)
            stored.setdefault(file.sha256, file)
    return list(stored.values())
