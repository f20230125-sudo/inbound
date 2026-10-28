"""Deterministic daily dispatches. Stored snapshots never rewrite yesterday's claims."""

import hashlib
import json
from datetime import datetime, timedelta

from inbound.agent import agent_state
from inbound.digest import DUBAI, today
from inbound.memory import guard
from inbound.steps import Empty, Kind, Reference, emit
from inbound.tasks import extract_tasks


def compose(db, now):
    day = now.astimezone(DUBAI).date()
    summary = today(db, now)
    state = agent_state(db, now)
    items = []

    def add(kind, text, href, refs, due='9999', evidence=None):
        items.append({'kind': kind, 'text': text, 'href': href, 'source_refs': refs, 'due': due,
                      'evidence': evidence})

    for entry in summary['decision_queue'] + [e for e in summary['past_deadlines']
                                              if e['deadline'].get('normalized', '')[:10] == str(day)]:
        kind, identity = entry['kind'], entry['id']
        ref = {'entity_type': 'opportunity' if kind == 'call' else
               'task' if kind == 'task' else 'message', 'entity_id': identity}
        href = (f'/opportunity/{identity}' if kind == 'call' else
                f'/work#task-{identity}' if kind == 'task' else f'/work#message-{identity}')
        record = entry['deadline'] or {}
        value = record.get('normalized') if record.get('status') in {'found', 'inferred'} else None
        due_day = datetime.fromisoformat(value).date() if value else None
        text = f"I need your decision on {entry['display_title']}. {entry['attention_reason']}."
        if due_day in {day, day + timedelta(days=1)}:
            text = (f"I found {entry['display_title']} due "
                    f"{'today' if due_day == day else 'tomorrow'}: {value}"
                    + (' · time not stated' if len(value) == 10 else ' · Dubai')
                    + f" ({record['status']}).")
            if entry['deadline_group'] == 'overdue':
                text = (f"I found a passed deadline today for {entry['display_title']}: "
                        f"{value} · Dubai ({record['status']}).")
        add(kind, text, href, [ref], value or '9999',
            {'title': entry['display_title'], 'deadline': record})
    for entry in summary['outside_applications']:
        activity = entry['outside_application']
        if activity['follow_up'] and activity['follow_up'] <= day.isoformat():
            add('follow_up', f"I found your follow-up due for {entry['display_title']}: "
                f"{activity['follow_up']}.", f"/opportunity/{entry['id']}",
                [{'entity_type': 'opportunity', 'entity_id': entry['id']}], activity['follow_up'])
    # Current verified drafts only, including drafts outside the first three decisions.
    for row in db.execute(
        "SELECT p.id,p.opportunity_id,p.checks_json FROM packs p JOIN opportunities o "
        "ON o.id=p.opportunity_id WHERE p.status='needs_review' AND "
        "o.status NOT IN ('skipped','submitted_by_me') AND p.content_version=o.content_version "
        "AND NOT EXISTS(SELECT 1 FROM review_events e WHERE e.opportunity_id=o.id "
        "AND e.action='applied_outside') "
        "AND p.id=(SELECT p2.id FROM packs p2 WHERE p2.opportunity_id=o.id "
        "ORDER BY julianday(p2.created_at) DESC,p2.id DESC LIMIT 1) "
        "AND p.revision_id=(SELECT r.id FROM opportunity_revisions r JOIN messages m "
        "ON m.id=r.message_id WHERE r.opportunity_id=o.id "
        "ORDER BY julianday(m.sent_at) DESC,m.id DESC LIMIT 1)"
    ):
        if json.loads(row['checks_json']).get('passed') is True:
            add('draft', 'I prepared a draft that is waiting for your review.',
                f"/opportunity/{row['opportunity_id']}#pack",
                [{'entity_type': 'pack', 'entity_id': row['id']}])
    since = datetime.combine(day - timedelta(days=1), datetime.min.time(), DUBAI)
    for row in db.execute(
        'SELECT r.id,r.opportunity_id,r.message_id FROM opportunity_revisions r '
        'WHERE julianday(r.created_at)>=julianday(?) AND julianday(r.created_at)<=julianday(?) '
        'AND EXISTS(SELECT 1 FROM opportunity_revisions old WHERE '
        'old.opportunity_id=r.opportunity_id AND old.id<>r.id)', (since.isoformat(), now.isoformat())
    ):
        add('changed', 'I recorded a changed call since yesterday; its revision is available.',
            f"/opportunity/{row['opportunity_id']}#facts",
            [{'entity_type': 'opportunity', 'entity_id': row['opportunity_id']},
             {'entity_type': 'message', 'entity_id': row['message_id']}])
    if state['decision_counts']['emails_to_sort']:
        refs = [{'entity_type': 'message', 'entity_id': r[0]} for r in db.execute(
            "SELECT message_id FROM triage WHERE COALESCE(corrected_category,category)='needs_review'"
        )]
        add('sorting', f"I found {len(refs)} emails that still need sorting.",
            '/work?category=needs_review', refs)
    items.sort(key=lambda i: (i['due'], i['kind']))
    return {'day': day.isoformat(), 'created_at': now.isoformat(), 'timezone': 'Asia/Dubai',
            'greeting': 'Good morning.' if now.astimezone(DUBAI).hour < 12 else 'Hello.',
            'freshness': 'I am using stored work. New mail may be missing.' if
            summary['snapshot']['stale'] else 'I am using the latest stored snapshot.',
            'items': items, 'empty': 'I found no actionable work in this stored snapshot.'
            if not items else ''}


def saved(db, identity, *, replay=False):
    row = db.execute('SELECT * FROM briefings WHERE id=?', (identity,)).fetchone()
    if row is None or replay and row['source'] != 'synthetic':
        return None
    return json.loads(row['payload_json']) | {'id': row['id']}


def projection_key(payload, generation):
    return hashlib.sha256(json.dumps(
        {k: v for k, v in payload.items() if k != 'created_at'} | {'generation': generation},
        sort_keys=True).encode()).hexdigest()


def current(db, now, *, replay=False):
    """Reading the opening view never writes; a guarded POST saves a missing projection."""
    generation = db.execute('SELECT generation FROM domain_generation WHERE id=1').fetchone()[0]
    payload = compose(db, now)
    key = projection_key(payload, generation)
    row = db.execute('SELECT id FROM briefings WHERE day=? AND projection_key=?' +
                     (" AND source='synthetic'" if replay else ''), (payload['day'], key)).fetchone()
    if row:
        return saved(db, row[0], replay=replay) | {'needs_refresh': False}
    writable = not replay and db.execute(
        "SELECT value FROM settings WHERE key='paused'").fetchone()[0] != '1' and not db.execute(
        "SELECT 1 FROM runs WHERE status='running' AND operation_key='import'").fetchone()
    return payload | {'id': None, 'needs_refresh': bool(writable)}


def generate(db, now):
    db.execute('BEGIN IMMEDIATE')
    with db:
        guard(db)
        extract_tasks(db)
        generation = db.execute('SELECT generation FROM domain_generation WHERE id=1').fetchone()[0]
        day = now.astimezone(DUBAI).date().isoformat()
        payload = compose(db, now)
        key = projection_key(payload, generation)
        old = db.execute('SELECT id FROM briefings WHERE day=? AND projection_key=?',
                         (day, key)).fetchone()
        if old:
            return saved(db, old[0])
        source = 'private' if db.execute(
            "SELECT 1 FROM messages WHERE source<>'synthetic'"
        ).fetchone() else 'synthetic'
        identity = db.execute(
            'INSERT INTO briefings(day,generation,projection_key,created_at,source,payload_json) '
            'VALUES (?,?,?,?,?,?)',
            (day, generation, key, now.isoformat(), source,
             json.dumps(payload, ensure_ascii=False))
        ).lastrowid
        emit(db, Kind.BRIEFING, Empty(), entity_type='briefing', entity_id=identity,
             occurred_at=now,
             references=tuple(Reference(r['entity_type'], r['entity_id'])
                              for item in payload['items'] for r in item['source_refs']))
    return saved(db, identity)


def plain_text(value):
    lines = [f"{value['greeting']} Dubai briefing · {value['day']}", value['freshness']]
    lines.extend(f"{i['text']} [{i['href']}]" for i in value['items'])
    if value['empty']:
        lines.append(value['empty'])
    return '\n'.join(lines) + '\n'
