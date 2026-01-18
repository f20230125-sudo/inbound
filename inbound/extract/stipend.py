import re

from inbound.extract.records import conflict, field


def parse_stipend(raw):
    pattern = r"\b(AED|INR|USD|EUR|GBP)\s*([\d,]+)(?:\s*(?:to|[-–])\s*([\d,]+))?"
    found = []
    for match in re.finditer(pattern, raw, re.IGNORECASE):
        low = int(match[2].replace(",", ""))
        high = int((match[3] or match[2]).replace(",", ""))
        unit = re.search(r"(?:per\s+|/)(month|day|week|year)\b", raw[match.end() :], re.IGNORECASE)
        if not unit:
            continue
        found.append(
            field(
                "stipend",
                raw,
                {"currency": match[1].upper(), "min": low, "max": high, "period": unit[1].lower()},
            )
        )
    if len(found) > 1:
        return conflict("stipend", found)
    return found[0] if found else field("stipend", raw)
