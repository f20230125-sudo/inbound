"""Typed, signed-by-the-API excerpts. Captured bytes never follow a newer revision."""

import hashlib
import json

from inbound import memory
from inbound.extract.pipeline import latest_revision
from inbound.learning_preferences import relocation_evidence
from inbound.steps import project


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def revision(db, rid, field='deadline'):
    row = db.execute(
        'SELECT r.*,m.subject,m.sent_at,m.body_text,m.source,m.id AS mid,t.rule_id,t.reason '
        'FROM opportunity_revisions r JOIN messages m ON m.id=r.message_id '
        'LEFT JOIN triage t ON t.message_id=m.id WHERE r.id=?', (rid,)
    ).fetchone()
    if row is None:
        return None
    record = json.loads(row['fields_json']).get(field, {'status': 'unknown'})
    content = {'subject': row['subject'], 'sent_at': row['sent_at'], 'field': field,
               'evidence': record, 'blocker': row['blocked_reason'],
               'classification_rule': row['rule_id'], 'classification_reason': row['reason']}
    if field == 'mode':
        content['relocation'] = relocation_evidence(row['body_text'])
    return make('revision', rid, rid, f"Message · {field} excerpt", content,
                f"/opportunity/{row['opportunity_id']}#facts", row['created_at'], row['source'],
                field=field, opportunity_id=row['opportunity_id'])


def make(kind, identity, version, label, content, href, snapshot_at, source, **extra):
    return {'entity_type': kind, 'entity_id': identity, 'version': version, 'label': label,
            'content': excerpt(content), 'href': href, 'snapshot_at': snapshot_at, 'source': source,
            **extra}


def excerpt(value, depth=0):
    """Bound snapshots before signing; omitted text is explicitly labelled as an excerpt."""
    if depth > 8:
        return '[Further evidence omitted; open source workspace]'
    if isinstance(value, str):
        return value if len(value) <= 3000 else value[:3000] + '\n[Excerpt ends here]'
    if isinstance(value, list):
        result = [excerpt(v, depth + 1) for v in value[:12]]
        return result + (['[More evidence in source workspace]'] if len(value) > 12 else [])
    if isinstance(value, dict):
        return {k: excerpt(v, depth + 1) for k, v in value.items()}
    return value


def remembered(item):
    # Memory content is resolved through active retrieval, so forgetting revokes old citations.
    return make('memory', item['id'], item['version'], f"Memory · {item['display_title']}",
                None, f"/memory#memory-{item['id']}", item['changed_at'], item['source'])


def rule(db, rid, version=None):
    row = db.execute('SELECT * FROM learned_rules WHERE id=?', (rid,)).fetchone()
    if row is None:
        return None
    old = db.execute('SELECT * FROM learned_rule_versions WHERE rule_id=? AND version=?',
                     (rid, version or row['version'])).fetchone()
    if old is None:
        return None
    content = {'definition': json.loads(old['definition_json']), 'status': old['status'],
               'scope': 'Opportunity ranking only' if row['kind'] == 'preference'
               else 'Exact sender classification rule'}
    return make('rule', rid, old['version'], 'Rule · saved scope', content,
                f'/memory#rule-{rid}', old['changed_at'], row['source'])


def step(row):
    item = project(row)
    return make('step', row['id'], row['id'], 'Activity · recorded event',
                {'actor': item['actor'], 'text': item['text'], 'kind': item['kind'],
                 'source_refs': item['source_refs'], 'revision_id': item['revision_id']},
                item['href'], row['occurred_at'], row['source'])


def task(db, value):
    return make('task', value['id'], value['version'], 'College task · source excerpt',
                {'course': value['course'], 'title': value['title'],
                 'deadline': value['deadline'], 'source_quote': value['source_quote'],
                 'revision_id': value['revision_id']}, value['href'],
                value['history'][-1]['created_at'], value['source'])


def skill(db, sid):
    row = db.execute('SELECT * FROM skills WHERE id=? AND active=1 AND approved=1',
                     (sid,)).fetchone()
    if row is None:
        return None
    proofs = [dict(r) for r in db.execute(
        'SELECT s.project_id,s.note,p.title,p.source_hash FROM skill_evidence s '
        'JOIN evidence_projects p ON p.id=s.project_id WHERE s.skill_id=? AND p.active=1',
        (sid,))]
    if not proofs:
        return None
    content = {'name': row['name'], 'approved': True, 'evidence': proofs}
    return make('skill', sid, digest(content), 'Approved skill evidence · ' + row['name'],
                content, '/work', None, 'synthetic' if row['scope'] == 'demo' else 'private')


def resolve(db, captured, *, replay=False):
    if replay and captured['source'] != 'synthetic':
        return None
    kind, identity = captured['entity_type'], captured['entity_id']
    newer = False
    if kind == 'memory':
        record = memory.resolve(db, {k: captured[k] for k in ('entity_type', 'entity_id', 'version')},
                                replay=replay)
        if record is None:
            return None
        return captured | {'content': record, 'newer_information': bool(record['newer_version'])}
    if kind == 'task':
        row = db.execute('SELECT source,version FROM tasks WHERE id=?', (identity,)).fetchone()
        current = dict(row) if row else None
        newer = row is None or row['version'] != captured['version']
    elif kind == 'revision':
        current = revision(db, identity, captured['field'])
        if current:
            latest = latest_revision(db, captured['opportunity_id'])
            newer = latest['id'] != identity or current['content'] != captured['content']
    elif kind == 'rule':
        current = rule(db, identity)
        newer = current is None or current['version'] != captured['version']
    elif kind == 'skill':
        current = skill(db, identity)
        newer = current is None or current['version'] != captured['version']
    elif kind == 'step':
        row = db.execute('SELECT * FROM agent_steps WHERE id=?', (identity,)).fetchone()
        current = step(row) if row else None
    elif kind == 'message':
        row = db.execute('SELECT m.*,e.fields_json FROM messages m '
                         'JOIN message_extractions e ON e.message_id=m.id WHERE m.id=?',
                         (identity,)).fetchone()
        current = {'source': row['source']} if row else None
        newer = row is None or row['content_hash'] != captured['version'] or {
            'subject': row['subject'], 'deadline': json.loads(row['fields_json']).get('deadline')
        } != captured['content']
    else:
        raise ValueError('Unknown citation type')
    if current is None:
        newer = True
    elif replay and current['source'] != 'synthetic':
        return None
    return captured | {'newer_information': newer}
