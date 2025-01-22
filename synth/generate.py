"""Deterministic materialisation; no triage or extraction imports."""

import hashlib
import html
import json
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from pathlib import Path

from synth.documents import attachment_bytes
from synth.families import render

CASES = Path(__file__).with_name("cases.json")
EML_MAP = {
    "encoded.eml": "P-D01",
    "multipart.eml": "P-D03",
    "html-only.eml": "P-D15",
    "malformed.eml": "P-D18",
    "plain.eml": "O-D025",
}


def export(case):
    message = case["message"]
    entries = {
        "id": case["id"],
        "thread_id": message["thread_id"],
        "date": message["sent_at"],
        "from": message["sender"],
        "to": "sara.qamar@applicant.demo.invalid",
        "cc": "",
        "bcc": "",
        "subject": message["subject"],
        "labels": "",
        "attachments": "; ".join(
            "|".join([a["name"], a["mime"], a.get("bytes_path") or ""])
            for a in message["attachments"]
        ),
        "body_exported": "Synthetic inbound-export-v1; complete text except where flagged",
        "body_complete": str(message.get("body_complete", True)).lower(),
    }
    if message.get("received_at"):
        entries["received_at"] = message["received_at"]
    text = "\n".join(f"{k}: {v}" for k, v in entries.items()) + "\n---\n" + render(case) + "\n"
    return text.encode("utf-8")


def eml(case, filename):
    source = case["message"]
    message = EmailMessage(policy=SMTP)
    message["Message-ID"] = f"<{case['id']}@inbound.demo.invalid>"
    message["X-Inbound-Thread-ID"] = source["thread_id"]
    message["Date"] = format_datetime(datetime.fromisoformat(source["sent_at"]).astimezone(UTC))
    message["From"] = source["sender"]
    message["To"] = "sara.qamar@applicant.demo.invalid"
    message["Subject"] = source["subject"]
    body = render(case)
    if filename == "html-only.eml":
        message.set_content(
            "<html><body>" + html.escape(body).replace("\n", "<br>") + "</body></html>",
            subtype="html",
        )
    else:
        message.set_content(body, charset="utf-8")
    if filename == "multipart.eml":
        message.add_alternative(
            "<html><body>" + html.escape(body).replace("\n", "<br>") + "</body></html>",
            subtype="html",
        )
    for attachment in source["attachments"]:
        major, minor = attachment["mime"].split("/", 1)
        message.add_attachment(
            attachment_bytes(case, attachment) or b"",
            maintype=major,
            subtype=minor,
            filename=attachment["name"],
        )
    if message.is_multipart():
        message.set_boundary("INBOUND-SYNTHETIC-" + case["id"])
    data = message.as_bytes()
    if filename == "malformed.eml":
        # Missing final MIME boundary: email.parser recovers the body and encoded filename.
        boundary = message.get_boundary().encode()
        data = data.replace(b"--" + boundary + b"--\r\n", b"")
    return data


def generate(root=Path("fixtures")):
    root = Path(root)
    definitions = json.loads(CASES.read_text(encoding="utf-8"))
    cases = definitions["cases"]
    hashes, membership = {}, {"dev": [], "held-out": [], "attack": []}
    for folder in ("export_sample", "eml_sample"):
        (root / folder).mkdir(parents=True, exist_ok=True)

    def write(name, data):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()

    for case in cases:
        for attachment in case["message"]["attachments"]:
            data = attachment_bytes(case, attachment)
            if data is not None:
                write("export_sample/" + attachment["bytes_path"], data)
        split = case["split"]
        membership[split].append(case["id"])
        prefix = {"dev": "dev", "held-out": "held", "attack": "attack"}[split]
        write(f"export_sample/{prefix}-{len(membership[split]):03}.txt", export(case))
    by_id = {c["id"]: c for c in cases}
    for name, identity in EML_MAP.items():
        write("eml_sample/" + name, eml(by_id[identity], name))
    ground_truth = "".join(
        json.dumps(
            {"id": c["id"], "split": c["split"], "group": c["group"], **c["gold"]},
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for c in cases
    )
    write("ground_truth.jsonl", ground_truth.encode("utf-8"))
    manifest = {
        "dataset": definitions["dataset"],
        "seed": definitions["seed"],
        "clock": definitions["clock"],
        "counts": {k: len(v) for k, v in membership.items()},
        "split_membership": membership,
        "eml_alternates": EML_MAP,
        "sha256": hashes,
        "cases_sha256": hashlib.sha256(CASES.read_bytes()).hexdigest(),
        "attachments": "M2 deterministic PDF/DOCX bytes; missing documents stay missing",
    }
    (root / "manifest.json").write_bytes(
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    return manifest


if __name__ == "__main__":
    manifest = generate()
    print(
        json.dumps({"dataset": manifest["dataset"], "counts": manifest["counts"]}, sort_keys=True)
    )
