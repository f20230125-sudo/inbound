"""Bounded in-memory parsing. No archive contents are written to disk."""

import base64
import io
import zipfile

import pdfplumber
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from inbound.sources.base import MAX_BYTES, safe_attachment_path

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def parse_bytes(data, mime):
    def result(status, text="", reason=""):
        return {"parse_status": status, "text": text, "reason": reason}

    if len(data) > MAX_BYTES:
        return result("unreadable", reason="Attachment size cap exceeded")
    if mime not in {"application/pdf", DOCX}:
        return result("unsupported", reason="Unsupported attachment type")
    if not data:
        return result("unreadable", reason="Empty attachment")
    try:
        stream = io.BytesIO(data)
        if mime == "application/pdf":
            with pdfplumber.open(stream) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        else:
            with zipfile.ZipFile(stream) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(i.file_size for i in entries) > 50 * 1024 * 1024:
                    return result("unreadable", reason="DOCX zip cap exceeded")
                for entry in entries:
                    safe_attachment_path(".", entry.filename.rstrip("/"))
                # Force CRC/decompression checks within the uncompressed cap before XML parsing.
                if archive.testzip():
                    return result("unreadable", reason="Corrupt DOCX member")
            document = Document(stream)
            parts = []

            def walk(container):
                for block in container.iter_inner_content():
                    if isinstance(block, Paragraph):
                        parts.append(block.text)
                    elif isinstance(block, Table):
                        for row in block.rows:
                            seen = set()
                            for cell in row.cells:
                                if cell._tc not in seen:
                                    seen.add(cell._tc)
                                    walk(cell)

            walk(document)
            text = "\n".join(parts)
        return (
            result("parsed", text)
            if text.strip()
            else result("unreadable", reason="No extractable text")
        )
    except Exception:  # noqa: BLE001 - third-party document errors are an untrusted-data boundary.
        # Library errors may contain document contents. Persist only a fixed reason.
        return result("unreadable", reason="Document could not be parsed")


def parse_attachment(attachment):
    safe_attachment_path(attachment.import_root or ".", attachment.name)
    path = None
    if attachment.bytes_path:
        if not attachment.import_root:
            safe_attachment_path(".", attachment.bytes_path)
            return {
                "name": attachment.name,
                "mime": attachment.mime,
                "parse_status": "missing",
                "text": "",
                "reason": "Attachment import root missing; reimport source",
            }
        path = safe_attachment_path(attachment.import_root, attachment.bytes_path)
    if attachment.content_base64:
        try:
            data = base64.b64decode(attachment.content_base64, validate=True)
        except ValueError:
            data = b""
        parsed = parse_bytes(data, attachment.mime)
    elif path is not None and path.is_file():
        if path.stat().st_size > MAX_BYTES:
            parsed = {
                "parse_status": "unreadable",
                "text": "",
                "reason": "Attachment size cap exceeded",
            }
        else:
            parsed = parse_bytes(path.read_bytes(), attachment.mime)
    else:
        parsed = {"parse_status": "missing", "text": "", "reason": "Attachment bytes missing"}
    return dict(name=attachment.name, mime=attachment.mime, **parsed)
