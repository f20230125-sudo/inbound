"""Stdlib MIME reader. It never extracts or executes attachments."""

import base64
from datetime import UTC
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from inbound.models import Attachment, Message
from inbound.sources.base import (
    SourceError,
    iso_timestamp,
    provenance,
    read_bytes,
    safe_attachment_path,
)


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag == "br" and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def decoded(part):
    raw = part.get_payload(decode=True)
    if raw is None:
        return str(part.get_payload())
    try:
        return raw.decode(part.get_content_charset() or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def parse(path, root, source):
    return parse_bytes(read_bytes(path), root, source)


def parse_bytes(data, root, source, *, identity=None, thread_id=None, labels=None,
                keep_oversized=False):
    """Parse one RFC 822 message. Gmail sync passes its own message/thread ids and labels.

    `keep_oversized`: live mail keeps the message and records an attachment over 10 MB
    without its bytes (unsupported), instead of rejecting the whole email.
    """
    mail = BytesParser(policy=policy.default).parsebytes(data)
    identity = identity or str(mail.get("Message-ID", "")).strip().strip("<>")
    if not identity or not mail.get("Date") or not mail.get("From"):
        raise SourceError("EML lacks identity/date/sender")
    # Synthetic alternates use the same mail identity namespace as the export.
    if identity.endswith("@inbound.demo.invalid"):
        identity = identity.removesuffix("@inbound.demo.invalid")
    try:
        sent = parsedate_to_datetime(str(mail["Date"]))
        if sent.tzinfo is None:
            raise ValueError
        sent = sent.astimezone(UTC)
    except (ValueError, TypeError) as exc:
        raise SourceError("Invalid EML date") from exc
    plain, html, attachments = [], [], []
    for part in mail.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if filename or part.get_content_disposition() == "attachment":
            name = filename or "attachment.bin"
            safe_attachment_path(root, name)
            payload = part.get_payload(decode=True) or b""
            if len(payload) > 10 * 1024 * 1024:
                if not keep_oversized:
                    raise SourceError("Attachment exceeds 10 MB")
                attachments.append(Attachment(name, part.get_content_type(),
                                              parse_status="unsupported"))
                continue
            attachments.append(
                Attachment(
                    name,
                    part.get_content_type(),
                    bytes_available=bool(payload),
                    parse_status="unsupported" if payload else "missing",
                    content_base64=base64.b64encode(payload).decode("ascii") if payload else None,
                )
            )
        elif part.get_content_type() == "text/plain":
            plain.append(decoded(part))
        elif part.get_content_type() == "text/html":
            parser = TextHTML()
            parser.feed(decoded(part))
            html.append("".join(parser.parts))
    complete = str(mail.get("X-Inbound-Body-Complete", "true")).lower()
    if complete not in {"true", "false"}:
        raise SourceError("Invalid EML completeness flag")
    return Message(
        provider_id=identity,
        thread_id=thread_id or str(mail.get("X-Inbound-Thread-ID", identity)),
        sent_at=sent,
        received_at=iso_timestamp(str(mail["X-Inbound-Received-At"]))
        if mail.get("X-Inbound-Received-At")
        else sent,
        sender=str(mail["From"]),
        to=str(mail.get("To", "")),
        cc=str(mail.get("Cc", "")),
        bcc=str(mail.get("Bcc", "")),
        subject=str(mail.get("Subject", "")),
        body_text="\n".join(plain or html).replace("\r\n", "\n").rstrip("\n"),
        labels=labels if labels is not None else str(mail.get("X-Inbound-Labels", "")),
        body_complete=complete == "true",
        attachments=tuple(attachments),
        source=provenance(source),
    )


def load(root, source):
    provenance(source)
    root = Path(root)
    if not root.is_dir():
        raise SourceError("Import root is not a directory")
    for path in sorted(root.glob("*.eml")):
        yield parse(path, root, source)
