"""Attachment extraction: only gzipped and tarred log attachments are collected."""

import gzip
import io
import tarfile
from email.message import EmailMessage

from nginx_perf_agent.mail import StoredFile, extract_attachments


def message_with(*attachments: tuple[str, bytes]) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Nginx 日志"
    message.set_content("see attached")
    for name, payload in attachments:
        message.add_attachment(
            payload, maintype="application", subtype="octet-stream", filename=name
        )
    return message


def tar_bytes(*members: tuple[str, bytes], directory: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        if directory:
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
        for name, payload in members:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def test_gzip_attachment_is_decompressed_and_stored(tmp_path):
    payload = gzip.compress(b"127.0.0.1 - - [10/Oct/2026:15:31:37 +0800]\n")
    files = extract_attachments(
        message_with(("access.log.gz", payload)), tmp_path, max_bytes=1024
    )
    assert [file.filename for file in files] == ["access.log"]
    assert isinstance(files[0], StoredFile)
    assert files[0].stored_path.suffix == ".log"
    assert files[0].stored_path.read_bytes().startswith(b"127.0.0.1")


def test_non_archive_attachments_are_ignored(tmp_path):
    files = extract_attachments(
        message_with(
            ("access.log", b"plain\n"),
            ("notes.txt", b"hello"),
            ("report.pdf", b"%PDF-1.4"),
            ("logs.zip", b"PK\x03\x04"),
            ("image.png", b"\x89PNG"),
        ),
        tmp_path,
        max_bytes=1024,
    )
    assert files == []
    assert list(tmp_path.rglob("*")) == []


def test_only_the_gzip_attachment_of_a_mixed_message_is_kept(tmp_path):
    files = extract_attachments(
        message_with(
            ("report.pdf", b"%PDF-1.4"),
            ("access.log.gz", gzip.compress(b"a\n")),
            ("data.csv", b"1,2\n"),
        ),
        tmp_path,
        max_bytes=1024,
    )
    assert [file.filename for file in files] == ["access.log"]
    assert not list(tmp_path.rglob("*.pdf"))
    assert not list(tmp_path.rglob("*.csv"))


def test_gzip_with_unsupported_inner_suffix_is_skipped(tmp_path):
    files = extract_attachments(
        message_with(("dump.gz", gzip.compress(b"binary"))), tmp_path, max_bytes=1024
    )
    assert files == []


def test_oversized_gzip_is_rejected(tmp_path):
    payload = gzip.compress(b"x" * 4096)
    files = extract_attachments(
        message_with(("access.log.gz", payload)), tmp_path, max_bytes=100
    )
    assert files == []
    assert not list(tmp_path.rglob("*.log"))


def test_corrupt_gzip_is_skipped(tmp_path):
    files = extract_attachments(
        message_with(("broken.log.gz", b"not gzip")), tmp_path, max_bytes=1024
    )
    assert files == []


def test_identical_payloads_are_stored_once(tmp_path):
    payload = gzip.compress(b"same")
    files = extract_attachments(
        message_with(("a.log.gz", payload), ("copy.log.gz", payload)),
        tmp_path,
        max_bytes=1024,
    )
    assert len(files) == 1
    stored = list(tmp_path.rglob("*.log"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == b"same"


def test_repeated_extraction_reuses_the_stored_file(tmp_path):
    payload = gzip.compress(b"same")
    first = extract_attachments(message_with(("a.log.gz", payload)), tmp_path, 1024)
    second = extract_attachments(message_with(("a.log.gz", payload)), tmp_path, 1024)
    assert first[0].stored_path == second[0].stored_path
    assert first[0].sha256 == second[0].sha256
    assert len(list(tmp_path.rglob("*.log"))) == 1


def test_tar_members_are_stored_by_basename(tmp_path):
    payload = tar_bytes(
        ("logs/en_2h.log", b"a\n"),
        ("logs/notes.txt", b"b\n"),
        ("image.png", b"\x89PNG"),
        directory="logs/",
    )
    files = extract_attachments(
        message_with(("perf_logs.tar", payload)), tmp_path, max_bytes=1024
    )
    assert sorted(file.filename for file in files) == ["en_2h.log", "notes.txt"]
    assert {file.stored_path.read_bytes() for file in files} == {b"a\n", b"b\n"}


def test_tar_gz_attachment_is_unpacked(tmp_path):
    payload = gzip.compress(tar_bytes(("jp_2h.log", b"j\n")))
    files = extract_attachments(
        message_with(("perf_logs_jp.tar.gz", payload)), tmp_path, max_bytes=20000
    )
    assert [file.filename for file in files] == ["jp_2h.log"]


def test_tar_path_traversal_is_flattened(tmp_path):
    payload = tar_bytes(("../../etc/passwd.log", b"root\n"))
    files = extract_attachments(
        message_with(("evil.tar", payload)), tmp_path, max_bytes=1024
    )
    assert [file.filename for file in files] == ["passwd.log"]
    assert all(file.stored_path.is_relative_to(tmp_path) for file in files)


def test_oversized_tar_members_are_rejected(tmp_path):
    payload = tar_bytes(("a.log", b"x" * 80), ("b.log", b"y" * 80))
    files = extract_attachments(
        message_with(("big.tar", payload)), tmp_path, max_bytes=100
    )
    assert files == []
    assert not list(tmp_path.rglob("*.log"))


def test_corrupt_tar_is_skipped(tmp_path):
    files = extract_attachments(
        message_with(("broken.tar", b"not a tar")), tmp_path, max_bytes=1024
    )
    assert files == []

