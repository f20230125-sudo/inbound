"""Transport-neutral messages. Provenance is assigned by the source configuration."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Attachment:
    name: str
    mime: str
    bytes_path: str | None = None
    bytes_available: bool = False
    parse_status: str = "missing"
    import_root: str | None = None
    content_base64: str | None = None


@dataclass(frozen=True)
class Message:
    provider_id: str
    thread_id: str
    sent_at: datetime
    received_at: datetime
    sender: str
    subject: str
    body_text: str
    source: str
    provider: str = "mail"
    to: str = ""
    cc: str = ""
    bcc: str = ""
    labels: str = ""
    body_exported: str = ""
    body_complete: bool = True
    attachments: tuple[Attachment, ...] = field(default_factory=tuple)

    def canonical(self):
        """Ignore transport notes and byte availability, preserve source facts."""
        data = asdict(self)
        for key in ("provider", "body_exported"):
            data.pop(key)
        data["sent_at"] = self.sent_at.isoformat()
        data["received_at"] = self.received_at.isoformat()
        data["attachments"] = [{"name": a.name, "mime": a.mime} for a in self.attachments]
        # MIME encodings may use CRLF; canonical body line endings are LF.
        data["body_text"] = self.body_text.replace("\r\n", "\n").rstrip("\n")
        return data

    @property
    def content_hash(self):
        payload = json.dumps(self.canonical(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
