import re

from inbound.extract.records import field
from inbound.triage.normalize import normalize, normalize_subject

HEADING = re.compile(r"^\s*\**\s*(?:\(\d+\)|\d+\.|Role\s+\d+:)\s*(.+?)\s*\**$", re.IGNORECASE)
STOP = re.compile(
    r"^(?:CV |Deadline|Closing |Conditions|Mode |Stipend|Mira |Synthetic |Note\b)", re.IGNORECASE
)


def parse_roles(text, subject, identity):
    roles, quotes, active = [], [], None
    subject_only = False
    prepared = re.sub(r"(?<!^)(?<!\n)(?=\(\d+\)\s+\w|Role\s+\d+:)", "\n", text)
    prepared = re.sub(r"(\bIntern)\s+(?=(?:Expected Skills|Requirements):)", r"\1\n", prepared)
    lines = []
    for line in prepared.splitlines():
        if "|" in line:
            title, _, requirements = line.partition("|")
            if re.search(r"\bIntern\s*$", title):
                lines.extend([title.strip(), "Requirements: " + requirements.strip()])
                continue
        lines.append(line)
    continuation = False
    for line in lines:
        clean = line.strip().strip("*").strip()
        heading = HEADING.match(line)
        title = heading[1].strip("*").strip() if heading else None
        if not title and re.fullmatch(r"[\w /&-]+\bIntern", clean):
            title = clean
        if title:
            continuation = False
            role_id = f"{identity}-r{len(roles) + 1}"
            active = {"id": role_id, "title": normalize(title), "requirements": None}
            roles.append(active)
            quotes.append(line)
        elif active:
            if STOP.match(clean):
                active = None
                continuation = False
                continue
            bullet = re.match(r"^\s*[·•\-]\s+(.+)", clean)
            inline = re.match(r"^(?:Expected Skills|Requirements)\s*:\s*(.*)", clean, re.IGNORECASE)
            values = (
                [bullet[1]] if bullet else (inline[1].split(";") if inline and inline[1] else [])
            )
            if continuation and not bullet and not inline and clean and active["requirements"]:
                continued = clean.split(";")
                active["requirements"][-1]["text"] += " " + continued[0].strip()
                values = continued[1:]
                quotes.append(line)
            if bullet or inline:
                quotes.append(line)
            continuation = bool(inline and inline[1]) or bool(continuation and not bullet)
            for value in values:
                active["requirements"] = active["requirements"] or []
                qid = f"{active['id']}-q{len(active['requirements']) + 1}"
                active["requirements"].append({"id": qid, "text": value.strip()})
    if not roles:
        title_match = re.search(r",.+?\s-\s(.+)$", normalize_subject(subject))
        if title_match:
            title = title_match[1]
            roles.append({"id": f"{identity}-r1", "title": title, "requirements": None})
            quotes.append(title)
            subject_only = True
    for role in roles:
        if role["requirements"] is None:
            role["requirements_status"] = "unknown"
    quote = "\n".join(quotes)
    if roles and not subject_only and quote not in text:
        # Layout conversion is for parsing only; evidence remains the original document text.
        quote = text
    return field("roles", quote, roles or None, subject_only=subject_only)
