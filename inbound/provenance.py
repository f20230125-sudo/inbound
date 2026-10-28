"""Document locations supplement frozen extraction facts without changing their rules."""

import base64
import io
import json

import pdfplumber
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from inbound.extract.attachments import parse_attachment
from inbound.models import Attachment
from inbound.pause import check
from inbound.sources.base import MAX_BYTES, safe_attachment_path


def locations(attachment):
    # Reuse the existing bounded/CRC-checked parser before inspecting document structure.
    if parse_attachment(attachment)["parse_status"] != "parsed":
        return []
    if attachment.content_base64:
        payload = base64.b64decode(attachment.content_base64, validate=True)
    else:
        path = safe_attachment_path(attachment.import_root, attachment.bytes_path)
        if path.stat().st_size > MAX_BYTES:
            return []
        payload = path.read_bytes()
    result = []
    stream = io.BytesIO(payload)
    if attachment.mime == "application/pdf":
        with pdfplumber.open(stream) as pdf:
            result = [
                {"kind": "pdf_page", "page": i, "source_text": page.extract_text() or ""}
                for i, page in enumerate(pdf.pages, 1)
            ]
    else:
        document = Document(stream)

        def walk(container, prefix=""):
            for i, block in enumerate(container.iter_inner_content(), 1):
                location = f"{prefix}/block[{i}]"
                if isinstance(block, Paragraph):
                    result.append(
                        {"kind": "docx_paragraph", "location": location, "source_text": block.text}
                    )
                elif isinstance(block, Table):
                    for row_i, row in enumerate(block.rows, 1):
                        seen = set()
                        for cell_i, cell in enumerate(row.cells, 1):
                            if cell._tc not in seen:
                                seen.add(cell._tc)
                                cell_location = f"{location}/row[{row_i}]/cell[{cell_i}]"
                                result.append(
                                    {
                                        "kind": "docx_table_cell",
                                        "location": cell_location,
                                        "source_text": cell.text,
                                    }
                                )
                                walk(cell, cell_location)

        walk(document)
    return result


def index_locations(db):
    check(db)
    rows = db.execute(
        "SELECT a.* FROM attachments a LEFT JOIN attachment_locations l "
        "ON l.attachment_id=a.id WHERE a.parse_status='parsed' "
        "AND l.attachment_id IS NULL"
    ).fetchall()
    for row in rows:
        check(db)
        attachment = Attachment(
            row["filename"],
            row["mime"],
            row["bytes_path"],
            bool(row["bytes_available"]),
            row["parse_status"],
            row["import_root"],
            row["content_base64"],
        )
        result = locations(attachment)
        with db:
            check(db)
            db.execute(
                "INSERT INTO attachment_locations VALUES (?,?)", (row["id"], json.dumps(result))
            )
