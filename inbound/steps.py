"""Typed, text-free journal facts. emit never commits its caller's transaction."""

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from inbound.ledger import timestamp
from inbound.triage.taxonomy import CATEGORIES


class Kind(StrEnum):
    TASK_FOUND = "task.found"
    TASK_REVISED = "task.revised"
    TASK_DONE = "action.task_done"
    TASK_SNOOZED = "action.task_snoozed"
    TASK_NOT_MINE = "action.task_not_mine"
    TASK_UNDONE = "action.task_undone"
    BRIEFING = "briefing.prepared"
    RULE_SUGGESTED = "learning.suggested"
    RULE_ACTIVATED = "action.rule_activated"
    RULE_UNDONE = "action.rule_undone"
    RULE_MATCHED = "learning.matched"
    MEMORY_PUBLISHED = "memory.published"
    MEMORY_CHANGED = "action.memory_changed"
    GMAIL_STARTED = "gmail.started"
    GMAIL_FETCHED = "gmail.fetched"
    GMAIL_FAILED = "gmail.failed"
    GMAIL_FINISHED = "gmail.finished"
    IMPORT_STARTED = "import.started"
    IMPORT_STAGE = "import.stage"
    PUBLISHED = "snapshot.published"
    IMPORT_FAILED = "import.failed"
    INTERRUPTED = "work.interrupted"
    CLASSIFIED = "triage.classified"
    CORRECTED = "triage.corrected"
    CREATED = "opportunity.created"
    REVISED = "opportunity.revised"
    CONFLICT = "field.conflict"
    PACK_QUEUED = "pack.queued"
    PACK_STARTED = "pack.started"
    VERIFIED = "pack.verified"
    READY = "pack.ready"
    PACK_FAILED = "pack.failed"
    APPLIED = "action.applied_outside"
    SKIPPED = "action.skipped"
    RESTORED = "action.undo_skip"
    RECOVERED = "action.attachment_recovered"
    REVIEWED = "action.reviewed"
    SUBMITTED = "action.submitted_by_me"
    ACKNOWLEDGED = "action.blocker_acknowledged"
    ALERT_ELIGIBLE = "alert.eligible"
    ALERT_REQUESTED = "alert.requested"
    ALERT_SUPPRESSED = "alert.suppressed"


@dataclass(frozen=True)
class Empty:
    pass


@dataclass(frozen=True)
class Classification:
    category: str


@dataclass(frozen=True)
class Stage:
    stage: str


@dataclass(frozen=True)
class Snapshot:
    count: int
    review_count: int


@dataclass(frozen=True)
class Fetch:
    listed: int
    fetched: int
    too_large: int


@dataclass(frozen=True)
class Verification:
    passed: bool
    provisional: bool


@dataclass(frozen=True)
class Alert:
    alert_type: str
    reason: str


@dataclass(frozen=True)
class Reference:
    entity_type: str
    entity_id: int | str
    version: int | None = None


@dataclass(frozen=True)
class MemoryPublication:
    count: int


_CONTEXT = ContextVar("agent_step_context", default=None)
STAGES = {"queued", "import", "triage", "extraction", "provenance", "snapshot", "pack"}
ENTITIES = {"message", "opportunity", "pack", "run", "snapshot", "memory", "memory_snapshot", "rule",
            "task", "briefing"}
FACT_TYPES = {k: Empty for k in Kind}
FACT_TYPES.update(
    {
        Kind.CLASSIFIED: Classification,
        Kind.CORRECTED: Classification,
        Kind.IMPORT_STAGE: Stage,
        Kind.PUBLISHED: Snapshot,
        Kind.GMAIL_FETCHED: Fetch,
        Kind.VERIFIED: Verification,
        Kind.READY: Verification,
        Kind.ALERT_ELIGIBLE: Alert,
        Kind.ALERT_REQUESTED: Alert,
        Kind.ALERT_SUPPRESSED: Alert,
        Kind.MEMORY_PUBLISHED: MemoryPublication,
        Kind.MEMORY_CHANGED: MemoryPublication,
    }
)
PROGRESS = {
    Kind.GMAIL_STARTED,
    Kind.IMPORT_STARTED,
    Kind.IMPORT_STAGE,
    Kind.PACK_QUEUED,
    Kind.PACK_STARTED,
}
FAILURES = {Kind.GMAIL_FAILED, Kind.IMPORT_FAILED, Kind.PACK_FAILED}


@contextmanager
def scope(**values):
    token = _CONTEXT.set((_CONTEXT.get() or {}) | values)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def identifier(value):
    return (type(value) is int and value > 0) or (
        isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value) is not None
    )


def provenance(db, entity_type, entity_id):
    if entity_type in {"task", "briefing"}:
        table = 'tasks' if entity_type == 'task' else 'briefings'
        rows = db.execute(f'SELECT source FROM {table} WHERE id=?', (entity_id,)).fetchall()
    elif entity_type == "rule":
        rows = db.execute("SELECT source FROM learned_rules WHERE id=?", (entity_id,)).fetchall()
    elif entity_type == "memory":
        rows = db.execute("SELECT source FROM memories WHERE id=?", (entity_id,)).fetchall()
    elif entity_type == "memory_snapshot":
        rows = db.execute("SELECT source FROM memories WHERE version<=?", (entity_id,)).fetchall()
    elif entity_type == "message":
        rows = db.execute("SELECT source FROM messages WHERE id=?", (entity_id,)).fetchall()
    elif entity_type in {"opportunity", "pack"}:
        oid = entity_id
        if entity_type == "pack":
            row = db.execute("SELECT opportunity_id FROM packs WHERE id=?", (entity_id,)).fetchone()
            oid = row[0] if row else None
        rows = db.execute(
            "SELECT m.source FROM messages m JOIN opportunity_revisions r ON r.message_id=m.id "
            "WHERE r.opportunity_id=?",
            (oid,),
        ).fetchall()
    elif entity_type == "run":
        row = db.execute(
            "SELECT source FROM agent_steps WHERE run_id=? ORDER BY id LIMIT 1", (entity_id,)
        ).fetchone()
        return row[0] if row else None
    else:
        return None
    return "synthetic" if rows and all(r[0] == "synthetic" for r in rows) else "private"


def emit(
    db,
    kind: Kind,
    facts: Empty | Classification | Stage | Snapshot | Fetch | Verification | Alert,
    *,
    entity_type=None,
    entity_id=None,
    revision_id=None,
    snapshot_version=None,
    run_id=None,
    correlation_id=None,
    source=None,
    dedupe_key=None,
    references: tuple[Reference, ...] = (),
    occurred_at=None,
):
    if not isinstance(kind, Kind) or type(facts) is not FACT_TYPES[kind]:
        raise ValueError("Typed event facts required")
    if isinstance(facts, Classification) and facts.category not in CATEGORIES:
        raise ValueError("Unknown category")
    if isinstance(facts, Stage) and facts.stage not in STAGES:
        raise ValueError("Unknown stage")
    if isinstance(facts, (Snapshot, Fetch, MemoryPublication)) and any(
        type(v) is not int or not 0 <= v <= 10000000 for v in asdict(facts).values()
    ):
        raise ValueError("Nonnegative bounded counts required")
    if isinstance(facts, Verification) and any(type(v) is not bool for v in asdict(facts).values()):
        raise ValueError("Boolean verification facts required")
    if kind == Kind.READY and not facts.passed:
        raise ValueError("A ready draft requires passed checks")
    if isinstance(facts, Alert) and (
        facts.alert_type not in {"new_call", "deadline", "task_deadline"}
        or facts.reason
        not in {"eligible", "requested", "opening", "disabled", "unavailable", "failed"}
    ):
        raise ValueError("Unknown alert facts")
    if (entity_type is None) != (entity_id is None) or (
        entity_type is not None and (entity_type not in ENTITIES or not identifier(entity_id))
    ):
        raise ValueError("Typed entity reference required")
    for ref in references:
        if (
            type(ref) is not Reference
            or ref.entity_type not in ENTITIES
            or not identifier(ref.entity_id)
            or (ref.entity_type == "memory" and (type(ref.version) is not int or ref.version < 1))
            or (ref.entity_type != "memory" and ref.version is not None)
        ):
            raise ValueError("Typed source reference required")
    context = _CONTEXT.get() or {}
    run_id = run_id or context.get("run_id")
    correlation_id = correlation_id or context.get("correlation_id")
    for value in (run_id, revision_id, snapshot_version):
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError("Positive journal version required")
    if correlation_id is not None and not identifier(correlation_id):
        raise ValueError("Opaque correlation ID required")
    inferred_source = provenance(db, entity_type, entity_id)
    reference_sources = [provenance(db, ref.entity_type, ref.entity_id) for ref in references]
    source = (
        "private"
        if "private" in [inferred_source, *reference_sources]
        else (source or inferred_source or context.get("source", "private"))
    )
    if source not in {"private", "synthetic"}:
        raise ValueError("Unknown provenance")
    dedupe_key = dedupe_key or uuid4().hex
    if not isinstance(dedupe_key, str) or not re.fullmatch(r"[a-z0-9:._-]{1,160}", dedupe_key):
        raise ValueError("Opaque dedupe key required")
    actor = (
        "uzair"
        if kind.value.startswith("action.") or kind == Kind.CORRECTED
        else ("system" if kind == Kind.INTERRUPTED else "scout")
    )
    phase = "progress" if kind in PROGRESS else "committed_result"
    outcome = (
        "started"
        if kind in PROGRESS
        else "failed"
        if kind in FAILURES
        else (
            "cancelled"
            if kind == Kind.INTERRUPTED
            else "blocked"
            if isinstance(facts, Verification) and not facts.passed
            else "succeeded"
        )
    )
    refs = list(references)
    if entity_type:
        if entity_type == "memory":
            row = db.execute("SELECT version FROM memories WHERE id=?", (entity_id,)).fetchone()
            if row is None:
                raise ValueError("Known memory required")
            refs.insert(0, Reference(entity_type, entity_id, row[0]))
        else:
            refs.insert(0, Reference(entity_type, entity_id))
    now = timestamp()
    if occurred_at is not None and (
        not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None
    ):
        raise ValueError('Timezone-aware event clock required')
    db.execute(
        "INSERT INTO agent_steps(occurred_at,recorded_at,actor,kind,run_id,correlation_id,"
        "entity_type,entity_id,revision_id,snapshot_version,phase,outcome,facts_json,"
        "source_refs_json,dedupe_key,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(dedupe_key) DO NOTHING",
        (
            occurred_at.isoformat() if occurred_at else now,
            now,
            actor,
            kind.value,
            run_id,
            correlation_id,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            revision_id,
            snapshot_version,
            phase,
            outcome,
            json.dumps(asdict(facts)),
            json.dumps([{k: v for k, v in asdict(r).items() if v is not None} for r in refs]),
            dedupe_key,
            source,
        ),
    )
    return db.execute("SELECT id FROM agent_steps WHERE dedupe_key=?", (dedupe_key,)).fetchone()[0]


TEMPLATES = {
    Kind.TASK_FOUND: "I found a college task in the saved messages.",
    Kind.TASK_REVISED: "I recorded a college task revision. Its source history is available.",
    Kind.TASK_DONE: "You marked this college task done.",
    Kind.TASK_SNOOZED: "You snoozed this college task.",
    Kind.TASK_NOT_MINE: "You marked this college task as not yours.",
    Kind.TASK_UNDONE: "You undid your college task action.",
    Kind.BRIEFING: "I prepared your daily briefing from stored work.",
    Kind.RULE_SUGGESTED: "I suggested a scoped rule for your review.",
    Kind.RULE_ACTIVATED: "You activated a rule. Its scope and Undo are in Memory.",
    Kind.RULE_UNDONE: "You undid a rule. Its future influence is disabled.",
    Kind.RULE_MATCHED: "I used your scoped rule on matching stored work.",
    Kind.MEMORY_PUBLISHED: "I refreshed the saved memory snapshot.",
    Kind.MEMORY_CHANGED: "You changed a saved memory.",
    Kind.GMAIL_STARTED: "I started a Gmail check.",
    Kind.GMAIL_FAILED: "My Gmail check failed. Your saved information is available.",
    Kind.GMAIL_FINISHED: "I finished this Gmail check.",
    Kind.IMPORT_STARTED: "I queued an import of saved messages.",
    Kind.IMPORT_FAILED: "My import did not publish. Your previous snapshot is unchanged.",
    Kind.INTERRUPTED: "This work was interrupted. It has not resumed automatically.",
    Kind.CREATED: "I found an opportunity in the saved messages.",
    Kind.REVISED: "I recorded a new opportunity revision.",
    Kind.CONFLICT: "I found conflicting fields. I need clarification.",
    Kind.PACK_QUEUED: "I queued a draft build.",
    Kind.PACK_STARTED: "I started preparing a draft.",
    Kind.PACK_FAILED: "My draft build failed. Review the run for details.",
    Kind.APPLIED: "You recorded an application made outside Inbound.",
    Kind.SKIPPED: "You skipped this opportunity.",
    Kind.RESTORED: "You restored this opportunity after skipping it.",
    Kind.RECOVERED: "You supplied a replacement attachment.",
    Kind.REVIEWED: "You reviewed this draft.",
    Kind.SUBMITTED: "You declared that you submitted this application yourself.",
    Kind.ACKNOWLEDGED: "You acknowledged the draft's blocker.",
    Kind.ALERT_ELIGIBLE: "I found work eligible for a local browser alert.",
    Kind.ALERT_REQUESTED: "I requested a browser notification. Delivery and reading are unknown.",
    Kind.ALERT_SUPPRESSED: "I suppressed a local browser alert.",
}
STAGE_TEXT = {
    "import": "I'm importing saved messages.",
    "triage": "I'm classifying messages.",
    "extraction": "I'm extracting requirements.",
    "provenance": "I'm indexing evidence.",
    "snapshot": "I'm publishing the snapshot.",
    "pack": "I'm preparing a draft.",
    "queued": "I queued local work.",
}


def project(row):
    result = dict(row)
    facts = json.loads(result.pop("facts_json"))
    refs = json.loads(result.pop("source_refs_json"))
    kind = Kind(result["kind"])
    text = TEMPLATES.get(kind, "")
    if kind == Kind.IMPORT_STAGE:
        text = STAGE_TEXT[facts["stage"]]
    elif kind in {Kind.CLASSIFIED, Kind.CORRECTED}:
        text = (
            (
                "You corrected this message's category to "
                if kind == Kind.CORRECTED
                else "I classified this message as "
            )
            + facts["category"].replace("_", " ")
            + "."
        )
    elif kind == Kind.PUBLISHED:
        text = (
            f"I classified {facts['count']} messages. {facts['review_count']} still need your help."
        )
    elif kind == Kind.GMAIL_FETCHED:
        text = (
            "I checked Gmail. No new messages."
            if not facts["fetched"]
            else (f"I fetched {facts['fetched']} new messages from Gmail.")
        )
        if facts["too_large"]:
            count = facts["too_large"]
            text = (
                f"I fetched {facts['fetched']} new messages from Gmail. "
                f"{count} message{'s' if count != 1 else ''} exceeded the size limit."
            )
    elif kind in {Kind.VERIFIED, Kind.READY}:
        text = (
            (
                "I completed the required draft checks. "
                + ("They passed." if facts["passed"] else "They did not pass.")
            )
            if (kind == Kind.VERIFIED)
            else "I prepared a draft. The required checks passed."
        )
        if facts["provisional"]:
            text += " The draft is provisional; its blocker still needs your review."
    entity, identity = result["entity_type"], result["entity_id"]
    href = (
        f"/opportunity/{identity}"
        if entity == "opportunity"
        else (
            f"/work#message-{identity}"
            if entity == "message"
            else f"/settings?run={result['run_id']}#runs"
            if result["run_id"]
            else "/settings#runs"
        )
    )
    if entity == "pack":
        # Pack source refs also carry the opportunity for a stable workspace link.
        op = next((r for r in refs if r["entity_type"] == "opportunity"), None)
        if op:
            href = f"/opportunity/{op['entity_id']}#pack"
    if entity in {"memory", "memory_snapshot", "rule"}:
        href = f"/memory#memory-{identity}" if entity == "memory" else "/memory"
    if entity == "rule":
        href = f"/memory#rule-{identity}"
    if entity == 'task':
        href = f'/work#task-{identity}'
    if entity == 'briefing':
        href = f'/?briefing={identity}'
    return result | {"facts": facts, "source_refs": refs, "text": text, "href": href}


def page(db, after=0, *, replay=False, recorded=False, recording_id=None, through=None, tail=False):
    where, args = ["id> ?"], [after]
    if replay:
        where.append("source='synthetic'")
    label = None
    if recorded:
        privacy = " AND source='synthetic'" if replay else ""
        if through is None:
            through = db.execute(
                "SELECT COALESCE(MAX(id),0) FROM agent_steps WHERE 1" + privacy
            ).fetchone()[0]
        where.append("id<=?")
        args.append(through)
        last = db.execute(
            "SELECT * FROM agent_steps WHERE kind IN ('gmail.started','import.started')"
            + privacy
            + " AND id<=?"
            + (" AND id=?" if recording_id is not None else "")
            + " ORDER BY id DESC LIMIT 1",
            (through, recording_id) if recording_id is not None else (through,),
        ).fetchone()
        if last:
            recording_id = last["id"]
            if last["correlation_id"]:
                where.append("correlation_id=?")
                args.append(last["correlation_id"])
            elif last["run_id"]:
                where.append("run_id=?")
                args.append(last["run_id"])
            else:
                where.append("id=?")
                args.append(last["id"])
            from inbound.agent import display_time

            label = "Recorded check - " + display_time(last["occurred_at"])
        else:
            where.append("0")
    rows = db.execute(
        "SELECT * FROM agent_steps WHERE "
        + " AND ".join(where)
        + (" ORDER BY id DESC LIMIT 100" if tail else " ORDER BY id LIMIT 101"),
        args,
    ).fetchall()
    if tail:
        rows.reverse()
    return {
        "steps": [project(r) for r in rows[:100]],
        "has_more": len(rows) > 100,
        "after": rows[min(len(rows), 100) - 1]["id"] if rows else after,
        "label": label,
        "recording_id": recording_id,
        "through": through,
    }
