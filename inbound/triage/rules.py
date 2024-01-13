import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr

from inbound.pause import check
from inbound.triage.normalize import current_body, normalize_subject

OFFICE = {"ps@dubai.bits-pilani.ac.in", "psd@dubai.bits-pilani.ac.in"}
CONTACTS = {
    "noor@contacts.demo.invalid",
    "ishan@contacts.demo.invalid",
    "leena@contacts.demo.invalid",
}


@dataclass(frozen=True)
class Prediction:
    category: str
    rule_id: str
    reason: str
    source_quote: str
    urgency: str = "normal"
    confidence: float = 1.0


def classify(sender, subject, body, personal_contacts=None):
    mailbox = parseaddr(sender)[1].casefold()
    domain = mailbox.rpartition("@")[2]
    title = normalize_subject(subject)
    snippet = current_body(body)[:300]
    update = re.search(
        r"your application was sent to|\b(?:not\s+)?shortlisted\b", snippet, re.IGNORECASE
    )

    def result(category, rule, quote):
        return Prediction(category, rule, f"{rule}: {category}; source quote: {quote}", quote)

    if mailbox == "ps@dubai.bits-pilani.ac.in" and re.match(
        r"^Call for CV\b", title, re.IGNORECASE
    ):
        return result("ps_call", "T01", subject)
    if re.match(r"^Update on Your Application\b", title, re.IGNORECASE):
        return result("application_update", "T02-subject", subject)
    if re.search(r"your application was sent to", title, re.IGNORECASE):
        return result("application_update", "T02-sent", subject)
    if update:
        return result("application_update", "T02-body", update.group())
    if mailbox in OFFICE:
        return result("ps_admin", "T03", sender)
    if mailbox in {"jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com"}:
        return result("job_alert", "T04", sender)
    if mailbox in {"bitserp@bits-pilani.ac.in", "no-reply@teams.mail.microsoft"} or re.match(
        r"^f20\d{6}@", mailbox
    ):
        return result("academic", "T05-sender", sender)
    if re.search(r"\b(exam|quiz|assignment|case study|mid[ -]sem|seating)\b", title, re.IGNORECASE):
        return result("academic", "T05-subject", subject)
    if domain in {"dubai.bits-pilani.ac.in", "bits-pilani.ac.in"}:
        return result("campus_notice", "T06", sender)
    if domain == "easychair.org" or re.search(r"\[IEEE\b", title, re.IGNORECASE):
        return result("research", "T07", sender if domain == "easychair.org" else subject)
    if mailbox in {"notifications@github.com", "notifications@vercel.com"}:
        return result("dev_ops", "T08", sender)
    if re.search(r"\b(receipt|invoice|subscription confirmation)\b", title, re.IGNORECASE):
        return result("account_billing", "T09", subject)
    if re.search(
        r"\b(changelog|newsletters?|promotions?|marketing|product updates)\b", title, re.IGNORECASE
    ):
        return result("newsletter_promo", "T10", subject)
    if mailbox.partition("@")[0] in {
        "newsletter",
        "newsletters",
        "updates",
        "marketing",
        "offers",
        "promotions",
        "changelog",
    }:
        return result("newsletter_promo", "T10-sender", sender)
    contacts = CONTACTS if personal_contacts is None else set(personal_contacts)
    if mailbox in {c.casefold() for c in contacts}:
        return result("personal", "T11", sender)
    return result("needs_review", "T12", sender)


def urgency(deadline, now):
    if not deadline or len(deadline) == 10:
        return "normal"
    due = datetime.fromisoformat(deadline)
    if due.tzinfo is None:
        return "normal"
    return "high" if timedelta(0) < due - now <= timedelta(hours=48) else "normal"


def triage_messages(db, ids=None, personal_contacts=None):
    check(db)
    rows = db.execute("SELECT id,sender,subject,body_text FROM messages ORDER BY sent_at,id")
    count = 0
    with db:
        for row in rows.fetchall():
            if ids is not None and row["id"] not in ids:
                continue
            check(db)
            prediction = classify(
                row["sender"], row["subject"], row["body_text"], personal_contacts
            )
            db.execute(
                "INSERT INTO triage(message_id,category,urgency,reason,rule_id,source_quote,"
                "confidence) VALUES (?,?,?,?,?,?,?) ON CONFLICT(message_id) DO UPDATE SET "
                "category=excluded.category,urgency=excluded.urgency,reason=excluded.reason,"
                "rule_id=excluded.rule_id,source_quote=excluded.source_quote,"
                "confidence=excluded.confidence",
                (
                    row["id"],
                    prediction.category,
                    prediction.urgency,
                    prediction.reason,
                    prediction.rule_id,
                    prediction.source_quote,
                    prediction.confidence,
                ),
            )
            count += 1
    return count
