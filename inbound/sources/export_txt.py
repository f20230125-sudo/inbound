"""Reader for inbound-export-v1. Headers never supply trusted provenance."""

from pathlib import Path

from inbound.models import Attachment, Message
from inbound.sources.base import (
    SourceError,
    iso_timestamp,
    provenance,
    read_bytes,
    safe_attachment_path,
)

REQUIRED = {
    "id",
    "thread_id",
    "date",
    "from",
    "to",
    "cc",
    "bcc",
    "subject",
    "labels",
    "attachments",
    "body_exported",
    "body_complete",
}


def parse(path, root, source):
    try:
        text = read_bytes(path).decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeError as exc:
        raise SourceError("Export must be UTF-8") from exc
    header, separator, body = text.partition("\n---\n")
    if not separator:
        raise SourceError("Missing export separator")
    values = {}
    for line in header.splitlines():
        key, colon, value = line.partition(":")
        if not colon or key in values:
            raise SourceError("Malformed or duplicate export header")
        values[key] = value.strip()
    if not REQUIRED <= values.keys() or not values["id"] or not values["from"]:
        raise SourceError("Missing required export header")
    if values["body_complete"] not in {"true", "false"}:
        raise SourceError("body_complete must be true or false")
    attachments = []
    for entry in filter(None, (a.strip() for a in values["attachments"].split(";"))):
        parts = entry.split("|")
        if len(parts) not in {2, 3} or not parts[0] or not parts[1]:
            raise SourceError("Malformed attachment metadata")
        name, mime = parts[:2]
        safe_attachment_path(root, name)
        relative = parts[2] if len(parts) == 3 and parts[2] else None
        candidate = safe_attachment_path(root, relative) if relative else None
        available = candidate is not None and candidate.is_file()
        if available and candidate.stat().st_size > 10 * 1024 * 1024:
            raise SourceError("Attachment exceeds 10 MB")
        attachments.append(
            Attachment(name, mime, relative, available, "unsupported" if available else "missing")
        )
    return Message(
        provider_id=values["id"],
        thread_id=values["thread_id"],
        sent_at=iso_timestamp(values["date"]),
        received_at=iso_timestamp(values.get("received_at", values["date"])),
        sender=values["from"],
        to=values["to"],
        cc=values["cc"],
        bcc=values["bcc"],
        subject=values["subject"],
        labels=values["labels"],
        body_text=body.rstrip("\n"),
        body_exported=values["body_exported"],
        body_complete=values["body_complete"] == "true",
        attachments=tuple(attachments),
        source=provenance(source),
    )


def load(root, source):
    provenance(source)
    root = Path(root)
    if not root.is_dir():
        raise SourceError("Import root is not a directory")
    for path in sorted(root.glob("*.txt")):
        yield parse(path, root, source)
