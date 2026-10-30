"""Attachment extraction, archive expansion and safe storage."""

import gzip
import io
import zipfile
from email.message import EmailMessage

import pytest

from nginx_perf_agent.mail import StoredFile, UnsafeAttachment, extract_attachments
from nginx_perf_agent.mail.attachments import safe_member_name


def message_with(*attachments: tuple[str, bytes]) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Nginx 日志"
    message.set_content("see attached")
    for name, payload in attachments:
        message.add_attachment(
            payload, maintype="application", subtype="octet-stream", filename=name
        )
    return message


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_plain_log_and_txt_are_stored(tmp_path):
    files = extract_attachments(
        message_with(("access.log", b"line one\n"), ("notes.txt", b"hello")),
        tmp_path,
        max_bytes=1024,
    )
    assert {file.filename for file in files} == {"access.log", "notes.txt"}
    for file in files:
        assert isinstance(file, StoredFile)
        assert file.stored_path.exists()
        assert file.stored_path.read_bytes() == {
            "access.log": b"line one\n",
            "notes.txt": b"hello",
        }[file.filename]


def test_unsupported_attachment_is_ignored(tmp_path):
    files = extract_attachments(
        message_with(("report.pdf", b"%PDF-1.4"), ("access.log", b"x")),
        tmp_path,
        max_bytes=1024,
    )
    assert [file.filename for file in files] == ["access.log"]
    assert not list(tmp_path.rglob("*.pdf"))


def test_gzip_attachment_is_expanded(tmp_path):
    payload = gzip.compress(b"127.0.0.1 - - GET /api 200\n")
    files = extract_attachments(
        message_with(("access.log.gz", payload)), tmp_path, max_bytes=1024
    )
    assert [file.filename for file in files] == ["access.log"]
    assert files[0].stored_path.suffix == ".log"
    assert files[0].stored_path.read_bytes().startswith(b"127.0.0.1")


def test_zip_attachment_is_expanded(tmp_path):
    payload = zip_bytes({"access.log": b"a\n", "error.log": b"b\n", "readme.md": b"x"})
    files = extract_attachments(
        message_with(("logs.zip", payload)), tmp_path, max_bytes=1024
    )
    assert sorted(file.filename for file in files) == ["access.log", "error.log"]


def test_zip_with_nested_gzip_is_expanded(tmp_path):
    payload = zip_bytes({"access.log.gz": gzip.compress(b"nested\n")})
    files = extract_attachments(
        message_with(("logs.zip", payload)), tmp_path, max_bytes=1024
    )
    assert [file.filename for file in files] == ["access.log"]
    assert files[0].stored_path.read_bytes() == b"nested\n"


@pytest.mark.parametrize(
    "member",
    ["../etc/passwd.log", "/etc/passwd.log", "..\\windows\\evil.log", "..", ""],
)
def test_unsafe_member_paths_are_rejected(member):
    with pytest.raises(UnsafeAttachment):
        safe_member_name(member)


def test_zip_with_traversal_member_is_rejected_entirely(tmp_path):
    payload = zip_bytes({"../escape.log": b"evil"})
    files = extract_attachments(
        message_with(("logs.zip", payload)), tmp_path, max_bytes=1024
    )
    assert files == []
    assert not (tmp_path.parent / "escape.log").exists()


def test_zip_symlink_member_is_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("link.log")
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, "/etc/passwd")
    files = extract_attachments(
        message_with(("logs.zip", buffer.getvalue())), tmp_path, max_bytes=1024
    )
    assert files == []


def test_oversized_archive_is_rejected(tmp_path):
    payload = zip_bytes({"access.log": b"x" * 4096})
    files = extract_attachments(
        message_with(("logs.zip", payload)), tmp_path, max_bytes=100
    )
    assert files == []
    assert not list(tmp_path.rglob("*.log"))


def test_corrupt_archive_is_skipped(tmp_path):
    files = extract_attachments(
        message_with(("broken.zip", b"not a zip")), tmp_path, max_bytes=1024
    )
    assert files == []


def test_identical_payloads_are_stored_once(tmp_path):
    files = extract_attachments(
        message_with(("a.log", b"same"), ("copy.log", b"same")), tmp_path, max_bytes=1024
    )
    assert len(files) == 1
    stored = list(tmp_path.rglob("*.log"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == b"same"


def test_repeated_extraction_reuses_the_stored_file(tmp_path):
    first = extract_attachments(message_with(("a.log", b"same")), tmp_path, 1024)
    second = extract_attachments(message_with(("a.log", b"same")), tmp_path, 1024)
    assert first[0].stored_path == second[0].stored_path
    assert first[0].sha256 == second[0].sha256
    assert len(list(tmp_path.rglob("*.log"))) == 1
