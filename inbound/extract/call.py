"""Rules for current-message facts, with quoted history excluded from fact extraction."""

import re
from email.utils import parseaddr

from inbound.extract.deadline import DATE, parse_deadline
from inbound.extract.links import extract_links
from inbound.extract.records import conflict, field, stamp
from inbound.extract.roles import parse_roles
from inbound.extract.stipend import parse_stipend
from inbound.extract.subject import body_identity, split_subject
from inbound.triage.normalize import current_body, normalize
from inbound.triage.rules import classify

ATTACK = re.compile(
    r"\b(?:ignore\b.*\b(?:deadline|instructions)|system\s*:|assistant\s*:|"
    r"set\s+status|mark\s+submitted|hide\s+this\s+call|classify\s+as|"
    r"upload\s+(?:registry|private)|add\s+\w+\s+to\s+the\s+applicant)",
    re.IGNORECASE,
)


def safe_lines(text):
    return "\n".join(line for line in text.splitlines() if not ATTACK.search(line))


def deadline_fields(text, message, source="message", attachment_name=None, admin=False):
    candidates = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        # Plain-text exports may wrap after "at". Keep the newline in the evidence
        # rather than accepting the incomplete first line as a date-only deadline.
        if (
            re.search(r"\bat\s*\**\s*$", line, re.IGNORECASE)
            and index < len(lines)
            and re.fullmatch(
                r"\s*\**\s*(?:\d{1,2}:\d{2}\s*(?:AM|PM)?|\d{4}\s*hrs|\d{1,2}\s*(?:AM|PM))"
                r"\s*(?:UTC|GMT)?\s*\**\s*",
                lines[index],
                re.IGNORECASE,
            )
        ):
            line += "\n" + lines[index]
            index += 1
        if admin:
            phrases = [
                m.group().rstrip(" .")
                for m in re.finditer(
                    r"\b(?:on or before|by)\b.*?(?=\s*(?:/|;|\band by\b|\bby\b)|$)",
                    line,
                    re.IGNORECASE | re.DOTALL,
                )
            ]
        elif re.search(
            r"\b(?:deadline|closing time|final extension|CVs due)\b", line, re.IGNORECASE
        ):
            label = re.match(
                r"\s*\**CV Submission Deadline\**\s*:\s*(.*)",
                line,
                re.IGNORECASE | re.DOTALL,
            )
            phrases = [label[1] if label else line.strip()]
        else:
            phrases = []
        for phrase in phrases:
            parsed = parse_deadline(phrase, message.sent_at, message.received_at)
            if parsed["status"] != "unknown":
                stamp(
                    parsed,
                    message.provider_id,
                    source,
                    **({"name": attachment_name} if attachment_name else {}),
                )
                candidates.append(parsed)
    return candidates


def combine_deadlines(candidates, name="deadline"):
    if not candidates:
        return field(name)
    values = {c["normalized"] for c in candidates}
    result = candidates[0] if len(values) == 1 else conflict(name, candidates)
    result["name"] = name
    return result


def identity_field(name, observations):
    if not observations:
        return field(name)
    candidates = [
        field(name, o["source_text"], o["value"])
        for o in observations
    ]
    values = {o["value"].casefold() for o in observations}
    result = candidates[0]
    if len(values) > 1:
        if name == "city" and values == {"dso", "dubai"}:
            result = field(
                name,
                "; ".join(o["source_text"] for o in observations),
                list(dict.fromkeys(o["value"] for o in observations)),
            )
        else:
            result = conflict(
                name,
                [
                    stamp(c, o["message_id"], o["source"])
                    for c, o in zip(candidates, observations, strict=True)
                ],
            )
    elif observations[0]["source"] == "body":
        stamp(result, observations[0]["message_id"], "body")
    if len(observations) > 1:
        result["observations"] = observations
    return result


def extract_call(message, attachments=(), *, category=None):
    category = category or classify(message.sender, message.subject, message.body_text).category
    all_text = message.body_text + "\n" + "\n".join(a["text"] for a in attachments)
    quotes = [line for line in all_text.splitlines() if ATTACK.search(line)]
    mailbox = parseaddr(message.sender)[1].casefold()
    if mailbox == "ps@dubai-bits-pilani.ac.in":
        quotes.append(message.sender)
    body = safe_lines(current_body(message.body_text))
    result = {
        "fields": {},
        "kind": None,
        "creates_opportunity": category == "ps_call",
        "attack_suspected": bool(quotes),
        "attack_quotes": quotes,
        "amendment": False,
        "blocked_reason": None,
    }
    if category == "ps_admin":
        result["fields"]["admin_deadline"] = combine_deadlines(
            deadline_fields(body, message, admin=True), "admin_deadline"
        )
    if category == "application_update":
        reference = re.search(r"Application reference:\s*([^\s.]+)", body, re.IGNORECASE)
        result["fields"]["application_reference"] = field(
            "application_reference",
            reference[1] if reference else "",
            reference[1] if reference else None,
        )
        disposition = None
        for pattern, value in (
            (r"not shortlisted", "not_shortlisted"),
            (r"shortlisted", "shortlisted"),
            (r"your application was sent to", "sent"),
            (r"under review", "under_review"),
        ):
            if re.search(pattern, body, re.IGNORECASE):
                disposition = value
                break
        result["fields"]["disposition"] = field("disposition", body, disposition)
    if category != "ps_call":
        for f in result["fields"].values():
            stamp(f, message.provider_id)
        return result
    fields = result["fields"]
    for name in (
        "company",
        "city",
        "form_link",
        "apply_link",
        "company_website",
        "stipend",
        "mode",
        "deadline",
        "jd_location",
        "cv_naming_rule",
        "internship_dates",
        "roles",
        "role_count",
        "kind",
    ):
        fields[name] = field(name)
    subject_parts = split_subject(message.subject)
    body_parts = body_identity(body)
    for name in ("company", "city"):
        observed = []
        for source, parts in (("subject", subject_parts), ("body", body_parts)):
            if parts.get(name):
                observed.append(
                    {
                        "value": normalize(parts[name]),
                        "source": source,
                        "source_text": parts[name] if source == "subject" else parts["raw"],
                        "message_id": message.provider_id,
                    }
                )
        if name == "city":
            body_city = re.search(r"(?:Location|City)\s*:\s*([^\n;]+)", body, re.IGNORECASE)
            if body_city:
                raw = body_city[1].strip()
                observed.append(
                    {
                        "value": normalize(raw),
                        "source": "body",
                        "source_text": raw,
                        "message_id": message.provider_id,
                    }
                )
        fields[name] = identity_field(name, observed)
    extract_links(body, fields)
    result["kind"] = "direct_apply" if fields["apply_link"]["status"] == "found" else "ps_call"
    kind_quote = (
        fields["apply_link"]["raw"] if result["kind"] == "direct_apply" else message.subject
    )
    fields["kind"] = field("kind", kind_quote, result["kind"], status="inferred")
    stipend_lines = [
        line
        for line in body.splitlines()
        if re.search(r"\b(?:AED|INR|USD|EUR|GBP)\s*[\d,]|as per company norms", line, re.IGNORECASE)
    ]
    fields["stipend"] = parse_stipend("\n".join(stipend_lines))
    modes = re.findall(r"\b(In[ -]person|Hybrid|Remote)\b", body, re.IGNORECASE)
    if modes:
        candidates = [field("mode", m, re.sub(r"[ -]", "_", m.lower())) for m in modes]
        fields["mode"] = (
            candidates[0]
            if len({c["normalized"] for c in candidates}) == 1
            else conflict("mode", candidates)
        )
    deadline_candidates = deadline_fields(body, message)
    attached_line = next(
        (
            line
            for line in body.splitlines()
            if re.fullmatch(r"\s*[·•*-]?\s*Attached\s*\**\s*", line, re.IGNORECASE)
        ),
        "",
    )
    inline_marker = re.search(
        r"Job Title & (?:Expected Skills|JD)|Job Title|\bJD\b|\bPositions available\s*:", body
    )
    role_text = body
    role_origin = "message"
    role_attachment = None
    if attached_line or message.attachments:
        fields["jd_location"] = field("jd_location", attached_line, "attached")
        relevant = [a for a in attachments if not re.search(r"brochure", a["name"], re.IGNORECASE)]
        blockers = [
            f"{a['name']}: {a['parse_status']} ({a['reason']})"
            for a in relevant
            if a["parse_status"] != "parsed"
        ]
        if not relevant:
            blockers.append("Declared JD has not been parsed")
        result["blocked_reason"] = "; ".join(blockers) or None
        role_text = "\n".join(
            safe_lines(a["text"]) for a in relevant if a["parse_status"] == "parsed"
        )
        role_origin = "attachment" if role_text else "message"
        role_attachment = next((a["name"] for a in relevant if a["parse_status"] == "parsed"), None)
        for a in relevant:
            if a["parse_status"] == "parsed":
                deadline_candidates.extend(
                    deadline_fields(safe_lines(a["text"]), message, "attachment", a["name"])
                )
    elif inline_marker:
        fields["jd_location"] = field("jd_location", inline_marker.group(), "inline")
    elif message.body_complete:
        fields["jd_location"] = field("jd_location", "", "absent")
        role_text = ""
    else:
        fields["jd_location"] = field("jd_location", missing_reason="Incomplete source")
        role_text = ""
    fields["deadline"] = combine_deadlines(deadline_candidates)
    result["amendment"] = any(
        re.search(r"\b(?:extended|extension|revised|amended|corrected)\b", c["raw"], re.IGNORECASE)
        for c in deadline_candidates
    )
    if fields["deadline"]["status"] == "conflicting":
        result["attack_suspected"] = True
        result["attack_quotes"].extend(c["source_text"] for c in deadline_candidates)
    fields["roles"] = parse_roles(role_text, message.subject, message.provider_id)
    if fields["roles"].pop("subject_only", False):
        role_origin = "subject"
    roles = fields["roles"]["normalized"]
    fields["role_count"] = field(
        "role_count", fields["roles"]["raw"], len(roles) if roles else None
    )
    for name in ("roles", "role_count"):
        stamp(
            fields[name],
            message.provider_id,
            role_origin
            if name == "roles"
            else ("message" if role_origin == "subject" else role_origin),
            **({"name": role_attachment} if role_attachment else {}),
        )
    naming = re.search(r"CV is named as\s*-\s*([^\n]+)", body, re.IGNORECASE)
    if naming:
        fields["cv_naming_rule"] = field("cv_naming_rule", naming[1], naming[1])
    dates_line = next(
        (
            line
            for line in body.splitlines()
            if re.search(r"\b(?:Internship from|commence on)\b", line, re.IGNORECASE)
        ),
        "",
    )
    components = {name: field(name) for name in ("start", "end")}
    if dates_line:
        matches = list(re.finditer(DATE, dates_line, re.IGNORECASE))
        for name, date_match in zip(("start", "end"), matches):
            parsed = parse_deadline(date_match.group(), message.sent_at, message.received_at)
            components[name] = field(name, date_match.group(), parsed["normalized"])
        fields["internship_dates"] = field(
            "internship_dates", dates_line, {n: f["normalized"] for n, f in components.items()}
        )
    fields["internship_dates"]["components"] = components
    for f in fields.values():
        if "provenance" not in f:
            stamp(f, message.provider_id)
    return result
