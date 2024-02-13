"""Length-capped, plain answers sourced only from registry facts."""

from inbound.evidence.import_cv import heading_pitch_from_cv, plain_text


def answers(registry, selection, limit=500):
    if limit < 1:
        raise ValueError("Answer length must be positive")
    projects = {p["id"]: p for p in registry["projects"]}
    result = []
    for selected in selection["projects"]:
        p = projects[selected["id"]]
        purpose = p.get("tagline") or p.get("pitch") or p.get("heading_pitch")
        if not purpose and registry.get("scope") == "public":
            purpose = heading_pitch_from_cv(p)
        purpose = purpose or "Uzair: what is this project for?"
        decisions = p.get("decisions") or []
        challenge = (
            " ".join(decisions) if decisions else "Uzair: what broke, and how did you fix it?"
        )
        result.append(
            {
                "id": p["id"],
                "purpose": plain_text(purpose)[:limit],
                "technologies": ", ".join(p["stack"])[:limit],
                "challenge_fix": plain_text(challenge)[:limit],
            }
        )
    return result
