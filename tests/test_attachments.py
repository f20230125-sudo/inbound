import io
import zipfile
from dataclasses import replace

import pytest

from inbound.extract.attachments import parse_attachment, parse_bytes
from inbound.models import Attachment
from inbound.sources.base import SourceError
from tests.m2_helpers import message


@pytest.mark.parametrize(
    "identity,status",
    [
        ("P-D15", "parsed"),
        ("P-D16", "unreadable"),
        ("P-D17", "missing"),
        ("P-D18", "parsed"),
        ("P-D19", "parsed"),
        ("P-D20", "missing"),
    ],
)
def test_status(identity, status):
    result = parse_attachment(message(identity).attachments[0])
    assert result["parse_status"] == status
    if status == "parsed":
        assert "Intern" in result["text"]


def test_unsupported_corrupt_and_caps():
    assert parse_bytes(b"x", "image/png")["parse_status"] == "unsupported"
    assert parse_bytes(b"bad", "application/pdf")["parse_status"] == "unreadable"
    assert (
        parse_bytes(b"x" * (10 * 1024 * 1024 + 1), "application/pdf")["parse_status"]
        == "unreadable"
    )
    for entries, size in [(2001, 0), (1, 50 * 1024 * 1024 + 1)]:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for i in range(entries):
                z.writestr(str(i), b"0" * size)
        result = parse_bytes(
            stream.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert result["parse_status"] == "unreadable"
        assert "cap" in result["reason"]


@pytest.mark.parametrize("path", ["../outside.pdf", "C:/outside.pdf", "a/../../x", "CON.pdf"])
def test_traversal(path, tmp_path):
    with pytest.raises(SourceError):
        parse_attachment(
            replace(
                Attachment("jd.pdf", "application/pdf"), bytes_path=path, import_root=str(tmp_path)
            )
        )


def test_zip_paths_rejected():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("../outside.xml", "<x/>")
    assert (
        parse_bytes(
            stream.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )["parse_status"]
        == "unreadable"
    )


def test_generated_document_structures_and_encoded_mime():
    from inbound.sources.eml_dir import load
    from synth.documents import docx_bytes, pdf_bytes

    text = (
        "(1) Backend Intern\nRequirements: Python; SQLite FTS5; BM25\n"
        "(2) Test Intern\nRequirements: pytest"
    )
    pdf = pdf_bytes(text, multipage=True)
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as document:
        assert len(document.pages) == 2
    assert (
        parse_bytes(pdf_bytes(text, image_only=True), "application/pdf")["parse_status"]
        == "unreadable"
    )
    for layout in ("DOCX table", "paragraphs plus table", "merged header"):
        result = parse_bytes(
            docx_bytes(text, layout),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert result["parse_status"] == "parsed" and "Python" in result["text"]
        assert "pytest" in result["text"]
    encoded = next(m for m in load("fixtures/eml_sample", "synthetic") if m.provider_id == "P-D18")
    assert encoded.attachments[0].name == message("P-D18").attachments[0].name
    assert parse_attachment(encoded.attachments[0])["parse_status"] == "parsed"


def test_m1_attachment_without_stored_root_abstains():
    result = parse_attachment(Attachment("jd.pdf", "application/pdf", "attachments/jd.pdf"))
    assert result["parse_status"] == "missing" and "reimport" in result["reason"]
