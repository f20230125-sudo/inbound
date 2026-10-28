"""Readable desk labels without changing extracted values or their provenance."""

import json
import re

from inbound.triage.normalize import normalize, normalize_subject


def fallback_title(subject):
    return re.sub(
        r"^Call for CV\s*-\s*(?:PS II\s*-\s*Second Semester\s+\d{4}\s*-\s*\d{4}\s*-\s*)?",
        "",
        normalize_subject(subject),
        flags=re.IGNORECASE,
    )


def city_text(value):
    values = value if isinstance(value, list) else [value]
    values = list(dict.fromkeys(normalize(str(v)) for v in values if v))
    if not values:
        return "City unknown"
    return values[0] + (" (" + "; ".join(values[1:]) + ")" if len(values) > 1 else "")


def opportunity_labels(db, state, subject):
    fields = state["fields"]
    roles = fields["roles"]["normalized"] or []
    pack = db.execute(
        "SELECT selection_json FROM packs WHERE opportunity_id=? AND revision_id=? "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (state["id"], state["revision_id"]),
    ).fetchone()
    recommended = (json.loads(pack[0]).get("recommended_role") or {}).get("title") if pack else None
    if recommended:
        role = recommended
    elif len(roles) > 1:
        role = f"{len(roles)} roles"
    else:
        role = roles[0]["title"] if roles else "Role unknown"
    city = city_text(fields["city"]["normalized"])
    company = fields["company"]["normalized"]
    title = (
        " · ".join(normalize(str(v)) for v in (company, role, city))
        if company else fallback_title(subject)
    )
    return {"display_title": title, "city_display": city, "role_label": role}
