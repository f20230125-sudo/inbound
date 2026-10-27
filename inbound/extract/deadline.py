"""Calendar precision and sent-time anchors are retained, including on conflicts."""

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from inbound.extract.records import field

DUBAI = ZoneInfo("Asia/Dubai")
MONTHS = {
    name.lower(): i
    for i, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        1,
    )
}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
DATE = r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b"


def parse_deadline(raw, sent_at, received_at):
    clean = raw.replace("*", "")
    relative = re.search(r"\b(today|tomorrow)\b", clean, re.IGNORECASE)
    match = re.search(DATE, clean, re.IGNORECASE)
    try:
        if relative:
            day = sent_at.astimezone(DUBAI).date() + timedelta(
                days=relative.group(1).lower() == "tomorrow"
            )
        elif match:
            day = date(int(match[3]), MONTHS[match[2].lower()], int(match[1]))
        else:
            return field("deadline", raw)
        remainder = clean if not match else clean[: match.start()] + clean[match.end() :]
        # Do not mistake a year for military time. A unit/meridiem is required otherwise.
        time = re.search(r"\b(\d{1,2}):(\d{2})\s*(AM|PM)?\b", remainder, re.IGNORECASE)
        military = re.search(r"\b(\d{2})(\d{2})\s*hrs\b", remainder, re.IGNORECASE)
        hour_only = re.search(r"\b(\d{1,2})\s*(AM|PM)\b", remainder, re.IGNORECASE)
        if time or military or hour_only:
            if time:
                hour, minute, meridiem = int(time[1]), int(time[2]), time[3]
            elif military:
                hour, minute, meridiem = int(military[1]), int(military[2]), None
            else:
                hour, minute, meridiem = int(hour_only[1]), 0, hour_only[2]
            if meridiem:
                if not 1 <= hour <= 12:
                    raise ValueError
                hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
            zone = UTC if re.search(r"\b(?:UTC|GMT)\b", remainder, re.IGNORECASE) else DUBAI
            due = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            normalized = due.astimezone(DUBAI).isoformat()
            precision = "minute"
            past = due < received_at
        else:
            normalized = day.isoformat()
            precision = "date"
            past = day < received_at.astimezone(DUBAI).date()
    except ValueError, OverflowError:
        return field("deadline", raw, missing_reason="Unparseable deadline")
    result = field(
        "deadline",
        raw,
        normalized,
        "inferred" if relative else "found",
        precision=precision,
        past_at_receipt=past,
        timezone="Asia/Dubai",
    )
    if relative:
        result["anchor"] = sent_at.isoformat()
    return result


def expired(deadline, now):
    if deadline["status"] not in {"found", "inferred"} or not deadline["normalized"]:
        return None
    value = deadline["normalized"]
    if len(value) == 10:
        return date.fromisoformat(value) < now.astimezone(DUBAI).date()
    return datetime.fromisoformat(value) < now
