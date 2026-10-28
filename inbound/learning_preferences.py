"""Source-backed preference fit, independent of CV evidence and decision urgency."""

import json
import re

EFFECTS = {
    "prefer_remote": "Prefer remote roles",
    "prefer_hybrid": "Prefer hybrid roles",
    "prefer_in_person": "Prefer in-person roles",
    "avoid_relocation": "Prefer roles without required relocation",
}


def active_preferences(db):
    return db.execute(
        "SELECT * FROM learned_rules WHERE kind='preference' AND status='active' "
        "ORDER BY changed_at DESC,rowid DESC"
    ).fetchall()


def contribution(effect, entry):
    if effect == "avoid_relocation":
        if entry.get("relocation_required") is True:
            return -1, entry.get("relocation_quote")
        if entry.get("relocation_required") is False:
            return 1, entry.get("relocation_quote")
        return 0, None
    preferred = {
        "prefer_remote": "remote",
        "prefer_hybrid": "hybrid",
        "prefer_in_person": "in person",
    }[effect]
    mode = str(entry.get("mode") or "").casefold().replace("-", " ").replace("_", " ")
    return (1, f"Source mode: {entry['mode']}") if mode == preferred else (0, None)


def preference_fit(db, entry):
    reasons = []
    active = active_preferences(db)
    # Current explicit preferences outrank curated prose, which remains retrieval-only.
    mode_rule = next(
        (r for r in active if json.loads(r["definition_json"])["effect"] != "avoid_relocation"),
        None,
    )
    for row in active:
        effect = json.loads(row["definition_json"])["effect"]
        if effect != "avoid_relocation" and row != mode_rule:
            continue
        score, evidence = contribution(effect, entry)
        if score:
            reasons.append(
                {
                    "rule_id": row["id"],
                    "version": row["version"],
                    "score": score,
                    "text": EFFECTS[effect],
                    "evidence": evidence,
                    "href": f"/memory#rule-{row['id']}",
                }
            )
    return {"preference_score": sum(r["score"] for r in reasons), "preference_reasons": reasons}


def relocation_evidence(body):
    from inbound.extract.call import safe_lines
    from inbound.triage.normalize import current_body

    # Only explicit current source lines count. In-person work does not imply relocation.
    candidates = []
    for line in safe_lines(current_body(body)).splitlines():
        text = line.strip().strip("* .")
        if re.fullmatch(
            r"(?:requires relocation|relocation(?: is|:)? required)", text, re.IGNORECASE
        ):
            candidates.append((True, line))
        elif re.fullmatch(
            r"(?:no relocation required|relocation(?: is|:)? not required)", text, re.IGNORECASE
        ):
            candidates.append((False, line))
    if len({c[0] for c in candidates}) == 1:
        return {"relocation_required": candidates[0][0], "relocation_quote": candidates[0][1]}
    return {"relocation_required": None, "relocation_quote": None}


def rank_key(entry):
    return (
        entry["decision_priority"],
        0
        if entry["deadline_group"] in {"timed", "date_only"}
        else -entry.get("preference_score", 0),
    )


def examples(db, definition, *, replay=False):
    from inbound.application_activity import latest
    from inbound.extract.pipeline import latest_revision, opportunity_state

    result = []
    for op in db.execute(
        "SELECT id FROM opportunities WHERE status NOT IN ('skipped','submitted_by_me')"
    ):
        if latest(db, op["id"]):
            continue
        state = opportunity_state(db, op["id"])
        revision = latest_revision(db, op["id"])
        mail = db.execute("SELECT * FROM messages WHERE id=?", (revision["message_id"],)).fetchone()
        if replay and mail["source"] != "synthetic":
            continue
        mode = state["fields"]["mode"]
        entry = {
            "mode": mode["normalized"] if mode["status"] in {"found", "inferred"} else None,
            **relocation_evidence(mail["body_text"]),
        }
        if contribution(definition["effect"], entry)[0]:
            result.append(dict(mail))
    return result


def conflicts(db, row):
    if row["status"] != "active" or row["kind"] != "preference":
        return []
    effect = json.loads(row["definition_json"])["effect"]
    if effect == "avoid_relocation":
        return []
    latest = next(
        (
            r
            for r in active_preferences(db)
            if json.loads(r["definition_json"])["effect"] != "avoid_relocation"
        ),
        None,
    )
    if latest and latest["id"] != row["id"]:
        return [
            "A newer explicit mode preference takes precedence. This rule is retained for review."
        ]
    return []


def record_uses(db):
    """Record prepared ranking matches on explicit activation/import, never from a GET."""
    from inbound.learning import use

    for row in active_preferences(db):
        if conflicts(db, row):
            continue
        for mail in examples(db, json.loads(row["definition_json"])):
            use(db, row, mail)
