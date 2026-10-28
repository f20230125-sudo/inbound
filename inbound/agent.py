"""Deterministic Scout projection. Reads only; all counts describe the saved snapshot."""

import json
from datetime import datetime, timedelta

from inbound.digest import DUBAI, today


def mood(*, connected=True, paused=False, working=False, failed=False, decisions=0, drafts=0):
    """Health, ongoing work and outstanding choices remain separate in the response."""
    if not connected:
        return "disconnected"
    if paused:
        return "paused"
    if working:
        return "working"
    if failed:
        return "failed"
    if decisions:
        return "needs_decision"
    return "draft_ready" if drafts else "idle"


def display_time(value):
    return datetime.fromisoformat(value).astimezone(DUBAI).strftime("%d %b %Y, %H:%M Dubai")


def agent_state(db, now, *, gmail=None, syncing=False):
    summary = today(db, now)
    gmail = gmail or {}
    paused = summary["paused"]
    active = db.execute(
        "SELECT id,kind,stage FROM runs WHERE status='running' ORDER BY id DESC"
    ).fetchall()
    latest = db.execute("SELECT id,status FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    gmail_failed = bool(gmail.get("last_error")) or (gmail.get("last_result") or {}).get(
        "status", "success"
    ) not in {"success", "completed"}
    failed = gmail_failed or bool(latest and latest["status"] in {"failed", "blocked"})
    success_at = (
        gmail.get("last_sync_at")
        if not gmail_failed and gmail.get("last_result") is not None
        else None
    )
    next_at = gmail.get("next_check_at")
    if paused or not next_at or datetime.fromisoformat(next_at) <= now:
        next_at = None
    snapshot = summary["snapshot"]
    fresh = (
        (
            now - datetime.fromisoformat(success_at) <= timedelta(hours=12)
            and datetime.fromisoformat(success_at).astimezone(DUBAI).date()
            == now.astimezone(DUBAI).date()
        )
        if success_at
        else not snapshot["stale"]
    )
    decisions = []
    drafts = 0
    for entry in summary["decision_queue"]:
        draft = None
        if entry["kind"] == "call":
            # Only the latest current-version pack can be ready. Superseded or failed
            # attempts must not revive an earlier successful draft.
            pack = db.execute(
                "SELECT p.* FROM packs p JOIN opportunities o ON o.id=p.opportunity_id "
                "WHERE p.opportunity_id=? AND p.content_version=o.content_version "
                "AND p.revision_id=(SELECT r.id FROM opportunity_revisions r "
                "JOIN messages m ON m.id=r.message_id WHERE r.opportunity_id=o.id "
                "ORDER BY julianday(m.sent_at) DESC,m.id DESC LIMIT 1) "
                "ORDER BY julianday(p.created_at) DESC,p.id DESC LIMIT 1",
                (entry["id"],),
            ).fetchone()
            if (
                pack
                and pack["status"] == "needs_review"
                and json.loads(pack["checks_json"]).get("passed") is True
            ):
                draft = pack["id"]
        drafts += draft is not None
        decisions.append(
            {
                "id": f"{entry['kind']}-{entry['id']}",
                "title": entry["display_title"],
                "reason": entry["attention_reason"],
                "deadline": entry["deadline"],
                "action": "Review draft"
                if draft
                else "Resolve blocker"
                if entry["blocked_reason"]
                else "Review deadline"
                if entry["deadline_group"] == "uncertain"
                else "Review opportunity"
                if entry["kind"] == "call"
                else "Review notice",
                "href": f"/opportunity/{entry['id']}" + ("#pack" if draft else "")
                if entry["kind"] == "call"
                else f"/work#message-{entry['id']}",
            }
        )
    # Category corrections and due follow-ups are decisions, not fictional Scout activity.
    review_count = db.execute(
        "SELECT COUNT(*) FROM messages m JOIN triage t ON t.message_id=m.id "
        "WHERE COALESCE(t.corrected_category,t.category)='needs_review' "
    ).fetchone()[0]
    call_count = sum(e['kind'] == 'call' for e in summary['decision_queue'])
    notice_count = len(summary['decision_queue']) - call_count
    follow_up_count = 0
    for entry in summary["outside_applications"]:
        follow_up = entry["outside_application"]["follow_up"]
        if follow_up and follow_up <= now.astimezone(DUBAI).date().isoformat():
            follow_up_count += 1
            decisions.append(
                {
                    "id": f"follow-up-{entry['id']}",
                    "title": entry["display_title"],
                    "reason": f"Your local follow-up date: {follow_up}.",
                    "action": "Review follow-up",
                    "href": f"/opportunity/{entry['id']}",
                }
            )
    if review_count:
        decisions.append({
            "id": "sorting-backlog", "title": f"{review_count} emails need sorting",
            "reason": "Review the grouped sorting backlog in Work.",
            "action": "Sort emails", "href": "/work?category=needs_review",
        })
    total = len(decisions)
    clauses = []

    def say(text, href):
        clauses.append({"text": text, "href": href})

    if gmail_failed:
        say(
            "My latest Gmail check failed. "
            + (
                "Your previous snapshot is still available."
                if snapshot["imported_at"]
                else "No successful snapshot is recorded."
            ),
            "/settings#gmail",
        )
    elif not fresh:
        say("I don't have a recent successful check. New mail may be missing.", "/settings#runs")
    if latest and latest["status"] in {"failed", "blocked"}:
        say(
            "My latest local run failed. "
            + (
                "Your previous snapshot is still available."
                if snapshot["imported_at"]
                else "No successful snapshot is recorded."
            ),
            f"/settings?run={latest['id']}#runs",
        )
    if call_count:
        say(f"{call_count} call{'s need' if call_count != 1 else ' needs'} you.", "/work")
    if notice_count:
        say(f"{notice_count} notice{'s need' if notice_count != 1 else ' needs'} you.", "/work")
    if follow_up_count:
        say(f"{follow_up_count} local follow-up{'s need' if follow_up_count != 1 else ' needs'} you.",
            "/work")
    if review_count:
        say(f"{review_count} email{'s need' if review_count != 1 else ' needs'} sorting.",
            "/work?category=needs_review")
    if drafts:
        say(
            f"{drafts} draft{'s are' if drafts != 1 else ' is'} ready for review.",
            "/work?status=needs_review",
        )
    if not total:
        say("There is no actionable work in this snapshot.", "/work")
    if success_at:
        say(f"My last successful Gmail check was {display_time(success_at)}.", "/settings#gmail")
    elif snapshot["imported_at"]:
        say(
            f"My last published snapshot is from {display_time(snapshot['imported_at'])}.",
            "/settings#runs",
        )
    if next_at:
        say(f"Next scheduled Gmail check: {display_time(next_at)}.", "/settings#gmail")
    state = mood(
        paused=paused,
        working=bool(active) or syncing,
        failed=failed,
        decisions=total - drafts,
        drafts=drafts,
    )
    status = {
        "idle": "I'm ready to review your stored work.",
        "working": "I'm checking Gmail."
        if syncing and not active
        else {
            "import": "I'm importing saved messages.",
            "triage": "I'm classifying saved messages.",
            "extraction": "I'm extracting call requirements.",
            "provenance": "I'm indexing source evidence.",
            "snapshot": "I'm publishing the local snapshot.",
            "pack": "I'm preparing a draft.",
        }.get(active[0]["stage"] if active else None, "I'm working on a local run."),
        "needs_decision": "I need your decision on the saved work below.",
        "draft_ready": "The draft is ready for your review.",
        "failed": "My latest work failed. Your saved information is available.",
        "paused": "I'm paused. Your saved information is available.",
    }[state]
    return {
        "mood": state,
        "as_of": now.isoformat(),
        "snapshot_version": snapshot["version"],
        "status": status,
        "paused": paused,
        "working": bool(active) or syncing,
        "gmail_connected": bool(gmail.get("connected")),
        "failed": failed,
        "counts": {"decisions": total, "drafts": drafts},
        "decision_counts": {"calls": call_count, "notices": notice_count,
                            "follow_ups": follow_up_count, "emails_to_sort": review_count},
        "decisions": decisions[:3],
        "briefing": clauses,
        "freshness": {
            "uncertain": not fresh or gmail_failed,
            "gmail_success_at": success_at,
            "snapshot_at": snapshot["imported_at"],
            "next_check_at": next_at,
        },
        "sources": {
            "queue": "/api/today",
            "categories": "/api/messages?category=needs_review",
            "drafts": "/api/opportunities",
            "runs": "/api/runs",
            "gmail": "/api/gmail",
        },
    }
