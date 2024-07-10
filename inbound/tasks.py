"""Conservative college extraction. Mail supplies evidence, only the person supplies state."""

import json
import re
import sqlite3
from datetime import datetime

from inbound.extract.call import safe_lines
from inbound.extract.deadline import DUBAI, parse_deadline
from inbound.extract.records import conflict, field, stamp
from inbound.ledger import timestamp
from inbound.memory import guard
from inbound.steps import Empty, Kind, Reference, emit
from inbound.triage.normalize import current_body, normalize_subject

TASK = r'\b(?:assignment|quiz|exam|mid\s*sem|lab|submission|case[ -]study)\b'
DUE = r'\b(?:due|submit|submission|deadline|scheduled|rescheduled)\b'


def clean_title(text):
    text = normalize_subject(text)
    return re.sub(r'\s+(?:due|rescheduled|extended|updated|reminder)\b.*$', '', text,
                  flags=re.IGNORECASE).strip(' :-')


def parse(row):
    body = safe_lines(current_body(row['body_text']))
    subject = normalize_subject(row['subject'])
    text = subject + '\n' + body
    # A publication date for room allocation is not an assessment deadline.
    if re.search(r'\bseating[ -]plan\b', subject, re.IGNORECASE):
        return None
    if not re.search(TASK, text, re.IGNORECASE):
        return None
    course = re.search(r'\b[A-Z]{2,5}\s+F\s*\d{3}\b', text)
    stated = re.search(r'^\s*Course\s*:\s*(.+)$', body, re.IGNORECASE | re.MULTILINE)
    course = re.sub(r'\s+', ' ', course[0]) if course else (stated[1].strip() if stated else None)
    title = re.search(r'^\s*(?:Assignment|Quiz|Exam|Lab|Submission|Task)\s*:\s*(.+)$',
                      body, re.IGNORECASE | re.MULTILINE)
    title = clean_title(title[1] if title else subject.replace(course or '\0', '').strip(' :-'))
    candidates = []
    for line in text.splitlines():
        if not re.search(DUE + '|' + TASK, line, re.IGNORECASE):
            continue
        if re.search(r'\b(?:published|posted|released|will be announced|to be announced)\b',
                     line, re.IGNORECASE):
            continue
        if re.search(r'\b(?:IST|PST|PDT|EST|EDT|CET|CEST|BST|Asia/(?!Dubai)\w+)\b|'
                     r'\b(?:UTC|GMT)\s*[+-]', line, re.IGNORECASE):
            continue
        record = parse_deadline(line, datetime.fromisoformat(row['sent_at']),
                                datetime.fromisoformat(row['received_at']))
        if record['status'] != 'unknown':
            stamp(record, row['provider_id'], local_message_id=row['id'])
            candidates.append(record)
    if row['category'] == 'campus_notice' and not candidates:
        return None
    unique = {c['normalized'] for c in candidates}
    deadline = conflict('deadline', candidates) if len(unique) > 1 else (
        candidates[-1] if candidates else field('deadline', source_text=text[:2000]))
    return {'course': course, 'title': title or 'Untitled college task', 'deadline': deadline,
            'quote': text[:4000],
            'amendment': bool(re.search(r'\b(?:rescheduled|extended|revised|postponed|'
                                       r'new deadline)\b', text, re.IGNORECASE))}


def extract_tasks(db):
    """Caller owns the transaction. Backfills already stored eligible mail idempotently."""
    for row in db.execute(
        "SELECT m.*,COALESCE(t.corrected_category,t.category) AS category FROM messages m "
        "JOIN triage t ON t.message_id=m.id WHERE COALESCE(t.corrected_category,t.category) "
        "IN ('academic','campus_notice') ORDER BY julianday(m.sent_at),m.id"
    ).fetchall():
        if db.execute('SELECT 1 FROM task_revisions WHERE message_id=? AND content_hash=?',
                      (row['id'], row['content_hash'])).fetchone():
            continue
        parsed = parse(row)
        if not parsed:
            continue
        matches = set()
        for old in db.execute(
            'SELECT t.*,r.course AS revision_course,r.title AS revision_title,m.provider,m.thread_id '
            'FROM tasks t JOIN task_revisions r ON r.task_id=t.id '
            'JOIN messages m ON m.id=r.message_id WHERE t.source=?', (row['source'],)
        ):
            same_name = (parsed['course'] and old['revision_course'] and
                         parsed['course'].casefold() == old['revision_course'].casefold() and
                         parsed['title'].casefold() == old['revision_title'].casefold())
            same_thread = (row['thread_id'] and old['thread_id'] == row['thread_id'] and
                           old['provider'] == row['provider'] and
                           (not old['course'] or not parsed['course'] or
                            old['course'].casefold() == parsed['course'].casefold()) and
                           (parsed['title'].casefold() == old['revision_title'].casefold() or
                            re.match(r'\s*(?:re|fwd):', row['subject'], re.IGNORECASE)))
            if same_name or same_thread:
                matches.add(old['id'])
        if len(matches) == 1:
            tid = matches.pop()
            db.execute('UPDATE tasks SET version=version+1 WHERE id=?', (tid,))
            kind = Kind.TASK_REVISED
        else:
            tid = db.execute('INSERT INTO tasks(course,title,source) VALUES (?,?,?)',
                             (parsed['course'], parsed['title'], row['source'])).lastrowid
            kind = Kind.TASK_FOUND
        rid = db.execute(
            'INSERT INTO task_revisions(task_id,message_id,content_hash,course,title,deadline_json,'
            'source_quote,amendment,sent_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (tid, row['id'], row['content_hash'], parsed['course'], parsed['title'],
             json.dumps(parsed['deadline']), parsed['quote'], int(parsed['amendment']),
             row['sent_at'], timestamp())
        ).lastrowid
        emit(db, kind, Empty(), entity_type='task', entity_id=tid, revision_id=rid,
             references=(Reference('message', row['id']),))


def list_tasks(db, now, *, replay=False, active=False):
    result = []
    for task in db.execute('SELECT * FROM tasks ORDER BY id'):
        if replay and task['source'] != 'synthetic':
            continue
        history = [dict(r) for r in db.execute(
            'SELECT * FROM task_revisions WHERE task_id=? ORDER BY julianday(sent_at),id',
            (task['id'],))]
        deadline = field('deadline')
        for revision in history:
            candidate = json.loads(revision['deadline_json'])
            if candidate['status'] == 'unknown':
                continue
            if (deadline['status'] == 'unknown' or revision['amendment'] or
                    deadline.get('normalized') == candidate.get('normalized') and
                    deadline['status'] != 'conflicting'):
                deadline = candidate
            else:
                deadline = conflict('deadline', [deadline, candidate])
        latest = history[-1]
        item = dict(task) | {'course': latest['course'] or task['course'],
                             'course_status': 'found' if latest['course'] else 'unknown',
                             'title': latest['title'], 'deadline': deadline,
                             'source_quote': latest['source_quote'], 'history': history,
                             'message_id': latest['message_id'], 'revision_id': latest['id'],
                             'href': f"/work#task-{task['id']}"}
        item['actionable'] = task['state'] not in {'done', 'not_mine'} and not (
            task['state'] == 'snoozed' and task['snoozed_until'] and
            datetime.fromisoformat(task['snoozed_until']) > now)
        if not active or item['actionable']:
            result.append(item)
    return sorted(result, key=lambda t: (t['deadline'].get('normalized') or '9999', t['id']))


def mutate(db, tid, action, version, now, *, until=None, expected_generation=None):
    if type(version) is not int or not isinstance(action, str) or action not in {
        'done', 'snooze', 'not_mine', 'undo'
    }:
        raise ValueError('Known action and integer version required')
    if action == 'snooze':
        due = datetime.fromisoformat(until) if isinstance(until, str) else None
        if due is None or due.tzinfo is None or due <= now:
            raise ValueError('A future snooze time with timezone is required')
        until = due.astimezone(DUBAI).isoformat()
    elif until is not None:
        raise ValueError('Only snooze takes a time')
    db.execute('BEGIN IMMEDIATE')
    with db:
        guard(db, expected_generation)
        task = db.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
        if task is None or task['version'] != version:
            raise sqlite3.IntegrityError('Task changed; refresh before acting')
        state, new_until, undone = action, until, None
        if action == 'undo':
            last = db.execute(
                "SELECT * FROM task_actions a WHERE task_id=? AND action<>'undo' "
                'AND NOT EXISTS(SELECT 1 FROM task_actions u WHERE u.undone_action_id=a.id) '
                'ORDER BY id DESC LIMIT 1', (tid,)).fetchone()
            if last is None:
                raise ValueError('No action to undo')
            state, new_until, undone = last['previous_state'], last['previous_until'], last['id']
        elif action == 'snooze':
            state = 'snoozed'
        db.execute('INSERT INTO task_actions(task_id,action,previous_state,previous_until,'
                   'undone_action_id,created_at) VALUES (?,?,?,?,?,?)',
                   (tid, action, task['state'], task['snoozed_until'], undone, now.isoformat()))
        db.execute('UPDATE tasks SET state=?,snoozed_until=?,version=version+1 WHERE id=?',
                   (state, new_until, tid))
        emit(db, {'done': Kind.TASK_DONE, 'snooze': Kind.TASK_SNOOZED,
                  'not_mine': Kind.TASK_NOT_MINE, 'undo': Kind.TASK_UNDONE}[action], Empty(),
             entity_type='task', entity_id=tid)
    return next(t for t in list_tasks(db, now) if t['id'] == tid)
