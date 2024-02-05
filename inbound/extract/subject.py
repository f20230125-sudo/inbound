"""Split call titles before normalising their meaningful dash separators."""

import re

from inbound.triage.normalize import ZERO_WIDTH

DASH = r"[-–—−]"


def split_subject(subject):
    tail = re.sub(r"^(?:(?:fwd|re):\s*)+", "", subject.strip(), flags=re.IGNORECASE)
    tail = re.sub(rf"^Call for CV\s*{DASH}\s*", "", tail, flags=re.IGNORECASE)
    tail = re.sub(
        rf"^PS II\s*{DASH}\s*Second Semester\s+\d{{4}}-\d{{4}}\s*{DASH}\s*",
        "",
        tail,
        flags=re.IGNORECASE,
    )
    return split_title(tail)


def split_title(tail):
    """Share company/city/role separator rules between the subject and body."""
    company = city = role = None
    if "," in tail:
        title = re.search(rf"\s+{DASH}\s+([^,]+)$", tail)
        if title:
            role, tail = title[1].strip(), tail[: title.start()]
        company, city = (part.strip() for part in tail.rsplit(",", 1))
    elif re.search(r"\s+[—–]\s+", tail):
        company, rest = re.split(r"\s+[—–]\s+", tail, maxsplit=1)
        parts = re.split(r"\s+-\s+", rest, maxsplit=1)
        city = parts[0].strip()
        role = parts[1].strip() if len(parts) == 2 else None
    else:
        title = re.fullmatch(r"(.+?)-\s+(.+)", tail)
        if title:
            company, role = title[1].strip(), title[2].strip()
    return {"company": company, "city": city, "role": role}


def body_identity(body):
    opening = re.search(
        r"^\s*(.+?)\s*has expressed their interest\b", body, re.IGNORECASE | re.MULTILINE
    )
    if not opening:
        return {}
    raw = opening[1].strip()
    clean = raw.replace("*", "").translate(ZERO_WIDTH).strip().rstrip(", ")
    parts = split_title(clean)
    # A bare company is sufficient evidence in the body sentence, unlike an ambiguous title.
    parts["company"] = parts["company"] or clean
    return {**parts, "raw": raw}
