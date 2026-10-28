"""Bounded local grammar and read-only answers. No command execution is imported here."""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from inbound import memory
from inbound import scout_citations as citations
from inbound.application_activity import latest
from inbound.evidence.registry import load_registry
from inbound.extract.deadline import DUBAI
from inbound.extract.pipeline import latest_revision, opportunity_state
from inbound.learning_preferences import EFFECTS, preference_fit, relocation_evidence
from inbound.packs.matching import contains, skill_matches
from inbound.steps import project
from inbound.triage.normalize import ZERO_WIDTH

COMMANDS = {'skip', 'remember', 'forget', 'check', 'pause', 'task_done'}
EXAMPLES = ["What's due this week?", 'What changed since yesterday?',
            'What assignments are due?', 'Mark <task> done',
            'What did you do today?', 'Find backend roles',
            'What do you know about my projects?', 'Check now', 'Pause']


@dataclass(frozen=True)
class Intent:
    kind: str
    entity: str = ''
    value: str = ''


def parse(text):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
        raise ValueError('Use a request of 1 to 500 characters')
    text = re.sub(r'\s+', ' ', text.strip()).replace('’', "'").rstrip('?.')
    normal = text.casefold()
    exact = {"what's due this week": 'due', 'what is due this week': 'due',
             'due this week': 'due', 'what did you do today': 'activity',
             'what do you know about my projects': 'projects',
             'check now': 'check', 'pause': 'pause'}
    exact['what assignments are due'] = 'tasks'
    if normal in exact:
        return Intent(exact[normal])
    for pattern, kind in [(r'why is (.{1,120}) flagged', 'why'),
                          (r'find (.{1,80}) roles', 'find'),
                          (r'forget (.{1,120})', 'forget'),
                          (r'remember that (.{1,300})', 'remember')]:
        match = re.fullmatch(pattern, text, re.IGNORECASE)
        if match:
            return Intent(kind, match[1])
    match = re.fullmatch(r'skip (.{1,120}?) because (.{1,300})', text, re.IGNORECASE)
    if match:
        return Intent('skip', match[1], match[2])
    match = re.fullmatch(r'mark (.{1,120}) done', text, re.IGNORECASE)
    if match:
        return Intent('task_done', match[1])
    match = re.fullmatch(r'what changed since (yesterday|today|\d{4}-\d{2}-\d{2})', normal)
    if match:
        try:
            if match[1] not in {'today', 'yesterday'}:
                date.fromisoformat(match[1])
            return Intent('changed', value=match[1])
        except ValueError:
            pass
    return Intent('unsupported')


def reply(text, **extra):
    return {'text': text, 'items': [], 'choices': [], 'suggestions': [], **extra}


def item(text, *refs):
    return {'text': text, 'citations': [r for r in refs if r is not None]}


def opportunities(db, now, replay):
    result = []
    for row in db.execute('SELECT * FROM opportunities ORDER BY id'):
        rev = latest_revision(db, row['id'])
        mail = db.execute('SELECT * FROM messages WHERE id=?', (rev['message_id'],)).fetchone()
        if replay and mail['source'] != 'synthetic':
            continue
        state = opportunity_state(db, row['id'], clock=lambda: now)
        state['mail'] = dict(mail)
        result.append(state)
    return result


def title_of(op):
    """A readable call name even when the company is unknown or conflicting."""
    if op.get('company'):
        return op['company'].translate(ZERO_WIDTH)
    subject = re.sub(r'^(?:(?:fwd|re):\s*)*call for cv\s*[-–]\s*(?:ps ii\s*[-–]\s*'
                     r'second semester\s*\d{4}\s*-\s*\d{4}\s*[-–]\s*)?', '',
                     (op['mail']['subject'] or '').translate(ZERO_WIDTH), flags=re.IGNORECASE)
    return subject.strip() or f"Call {op['id']}"


def matches(text, title):
    words = re.findall(r'\w+', re.sub(r'^(?:my|the)\s+', '', text.casefold()))
    haystack = re.findall(r'\w+', (title or '').casefold())
    return bool(words) and all(word in haystack for word in words)


def choose(candidates, selection, *, always=False):
    options = [{'key': key, 'label': label} for key, label, _ in candidates[:20]]
    if selection:
        return next((value for key, _, value in candidates if key == selection), None), []
    if len(candidates) == 1 and not always:
        return candidates[0][2], []
    return None, options


def query(db, text, now, *, replay=False, selection=None, demo=False):
    intent = parse(text)
    if intent.kind in COMMANDS:
        return prepare(db, intent, now, replay=replay, selection=selection)
    if selection and intent.kind != 'why':
        raise ValueError('This question does not take an entity selection')
    if intent.kind == 'due':
        return due(db, now, replay)
    if intent.kind == 'tasks':
        from inbound.tasks import list_tasks

        records = list_tasks(db, now, replay=replay, active=True)
        return reply(f'I found {len(records)} open college tasks in stored mail. '
                     'Supported dates are ordered first; unknown and conflicting dates need review.',
                     items=[item(f"{t['course'] or 'Course unknown'} · {t['title']}: "
                                 f"{t['deadline'].get('normalized') or 'Date unknown'} "
                                 f"({t['deadline']['status']})" +
                                 (' · time not stated' if t['deadline'].get('precision') == 'date'
                                  else ' · Dubai'), citations.task(db, t)) for t in records])
    if intent.kind in {'changed', 'activity'}:
        return activity(db, intent, now, replay)
    if intent.kind == 'projects':
        records = [m for m in memory.retrieve(db, replay=replay) if m['type'] == 'project']
        return reply(f'I found {len(records)} active project memories. These are remembered facts; '
                     'CV claims still require approved evidence. Showing up to 20.',
                     items=[item(f"{m['display_title']}: {m['content']}", citations.remembered(m))
                            for m in records[:20]])
    if intent.kind == 'find':
        return find(db, intent.entity, now, replay, demo)
    if intent.kind == 'why':
        candidates = [(f"opportunity:{o['id']}", f"{title_of(o)} · call {o['id']}", o)
                      for o in opportunities(db, now, replay)
                      if matches(intent.entity, f"{o['company'] or ''} {o['mail']['subject']}")]
        op, choices = choose(candidates, selection)
        if op is None:
            return reply('Choose the call you mean.' if choices else 'No matching stored call found.',
                         choices=choices)
        return why(db, op)
    return reply('I cannot answer that with the supported local intents. '
                 'Supported commands and questions are below.',
                 suggestions=EXAMPLES)


def due(db, now, replay):
    day = now.astimezone(DUBAI).date()
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=7)
    groups = {'timed': [], 'date_only': [], 'uncertain': [], 'past': []}
    from inbound.tasks import list_tasks

    for task in list_tasks(db, now, replay=replay, active=True):
        add_deadline(groups, f"{task['course'] or 'Course unknown'} · {task['title']}",
                     task['deadline'], start, end, citations.task(db, task), now)
    for op in opportunities(db, now, replay):
        if op['status'] in {'skipped', 'submitted_by_me'} or latest(db, op['id']):
            continue
        add_deadline(groups, title_of(op), op['fields']['deadline'], start, end,
                     citations.revision(db, op['revision_id']), now)
    for row in db.execute(
        "SELECT m.*,e.fields_json FROM messages m JOIN message_extractions e ON e.message_id=m.id "
        "JOIN triage t ON t.message_id=m.id WHERE COALESCE(t.corrected_category,t.category)='ps_admin'"
    ):
        if replay and row['source'] != 'synthetic':
            continue
        deadline = json.loads(row['fields_json']).get('deadline')
        if deadline:
            # A message citation carries the captured extraction, not a mutable current lookup.
            ref = citations.make('message', row['id'], row['content_hash'],
                                 'Message · administrative deadline',
                                 {'subject': row['subject'], 'deadline': deadline},
                                 f"/work#message-{row['id']}", row['sent_at'], row['source'])
            add_deadline(groups, row['subject'], deadline, start, end, ref, now)
    for name in ('timed', 'date_only', 'past'):
        groups[name].sort(key=lambda entry: entry['_due_order'])
        for entry in groups[name]:
            del entry['_due_order']
    counts = ', '.join(f'{len(v)} {k.replace("_", " ")}' for k, v in groups.items())
    return reply(f'Dubai week: {start} through {end - timedelta(days=1)} (inclusive). '
                 f'{counts}. Uncertain dates cannot be placed in this range. Showing up to 20 per group.',
                 range={'start': str(start), 'end': str(end), 'timezone': 'Asia/Dubai',
                        'end_exclusive': True},
                 groups={k: v[:20] for k, v in groups.items()},
                 items=[i for values in groups.values() for i in values[:20]])


def add_deadline(groups, title, deadline, start, end, ref, now=None):
    value = deadline.get('normalized')
    status = deadline['status']
    if status not in {'found', 'inferred'} or not isinstance(value, str):
        groups['uncertain'].append(item(f'{title}: {status} deadline; not assigned to a week.', ref))
        return
    try:
        day = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(
            value).astimezone(DUBAI).date()
    except ValueError:
        groups['uncertain'].append(item(f'{title}: unsupported deadline.', ref))
        return
    if start <= day < end:
        group = 'date_only' if len(value) == 10 else 'timed'
        if now is not None and (day < now.astimezone(DUBAI).date() if group == 'date_only'
                                else datetime.fromisoformat(value) <= now):
            # Already passed: kept visible, but after everything still open.
            groups.setdefault('past', []).append(
                item(f'{title}: {when(value)} · passed', ref) | {'_due_order': deadline_order(value)})
            return
        groups[group].append(item(f'{title}: {when(value)} · {status}', ref)
                             | {'_due_order': deadline_order(value)})


def deadline_order(value):
    return value if len(value) == 10 else datetime.fromisoformat(value).astimezone(DUBAI).isoformat()


def when(value):
    """A deadline as Uzair reads it: Dubai date and time, or date only."""
    if len(value) == 10:
        return f'{date.fromisoformat(value):%a %d %b} · time unknown'
    return f'{datetime.fromisoformat(value).astimezone(DUBAI):%a %d %b, %H:%M} Dubai'


def stamp(value):
    """A stored UTC timestamp as a short Dubai time."""
    return f'{datetime.fromisoformat(value).astimezone(DUBAI):%d %b %H:%M}'


def collapse(entries):
    """Fold repeated identical steps (e.g. a quiet Gmail check every 2 minutes) into one line."""
    seen, out = {}, []
    for text, at, ref in entries:
        if text in seen:
            first = seen[text]
            first['count'] += 1
            first['earliest'] = at
            continue
        record = {'text': text, 'latest': at, 'earliest': at, 'count': 1, 'ref': ref}
        seen[text] = record
        out.append(record)
    return [item(f"{stamp(r['latest'])} · {r['text']}" if r['count'] == 1 else
                 f"{stamp(r['earliest'])}-{stamp(r['latest'])[-5:]} · {r['text']} "
                 f"({r['count']} times)", r['ref']) for r in out]


def activity(db, intent, now, replay):
    local = now.astimezone(DUBAI)
    value = intent.value or 'today'
    start_day = (local.date() - timedelta(days=value == 'yesterday')) if value in {
        'today', 'yesterday'} else date.fromisoformat(value)
    start = datetime.combine(start_day, datetime.min.time(), DUBAI)
    finish = min(now, start + timedelta(days=1)) if intent.kind == 'activity' else now
    rows = db.execute(
        "SELECT * FROM agent_steps WHERE phase='committed_result' AND julianday(occurred_at)>=? "
        'AND julianday(occurred_at)<=? ' + ("AND source='synthetic' " if replay else '')
        + 'ORDER BY id DESC LIMIT 101',
        (start.timestamp() / 86400 + 2440587.5, finish.timestamp() / 86400 + 2440587.5)
    ).fetchall()
    items = collapse([(project(r)['text'], r['occurred_at'], citations.step(r)) for r in rows[:100]])
    if intent.kind == 'changed':
        # Committed call revisions count as changes even when no journal step describes them
        # (revisions imported before the journal existed are never backfilled as steps).
        revisions = db.execute(
            'SELECT r.id,r.created_at,o.company,m.source FROM opportunity_revisions r '
            'JOIN opportunities o ON o.id=r.opportunity_id JOIN messages m ON m.id=r.message_id '
            'WHERE julianday(r.created_at)>=? AND julianday(r.created_at)<=? '
            + ("AND m.source='synthetic' " if replay else '')
            + 'ORDER BY julianday(r.created_at) DESC,r.id DESC LIMIT 50',
            (start.timestamp() / 86400 + 2440587.5, finish.timestamp() / 86400 + 2440587.5),
        ).fetchall()
        items = [item(f"{stamp(r['created_at'])} · {r['company'] or 'A call'}: a revision was recorded.",
                      citations.revision(db, r['id'])) for r in revisions] + items
    return reply(f'Committed recorded work from {start.isoformat()} through '
                 f'{finish.astimezone(DUBAI).isoformat()} · Dubai. '
                 'Scout work uses “I”; your actions use “You”; system events keep their attribution. '
                 + ('Showing the latest 100 events; more exist.' if len(rows) > 100
                    else f'{len(rows)} recorded events.'),
                 range={'start': start.isoformat(), 'end': finish.astimezone(DUBAI).isoformat(),
                        'timezone': 'Asia/Dubai'}, items=items)


def why(db, op):
    items = []
    if op.get('blocked_reason'):
        items.append(item(op['blocked_reason'], citations.revision(db, op['revision_id'], 'jd_location')))
    for name, field in op['fields'].items():
        if field['status'] == 'conflicting':
            items.append(item(f'{name}: conflicting evidence. Review every source candidate.',
                              citations.revision(db, op['revision_id'], name)))
    if op['fields']['deadline']['status'] == 'unknown':
        items.append(item('Deadline unknown.', citations.revision(db, op['revision_id'])))
    triage = db.execute('SELECT * FROM triage WHERE message_id=?', (op['mail']['id'],)).fetchone()
    if triage:
        refs = [citations.revision(db, op['revision_id'], 'roles')]
        if triage['rule_id'].startswith('learned:'):
            refs.append(citations.rule(db, triage['rule_id'].split(':')[1]))
        items.append(item(f"Classification: {triage['reason']} (rule {triage['rule_id']}).", *refs))
    return reply(f"{title_of(op)}: current stored blockers, rule matches and conflicts.", items=items)


def find(db, term, now, replay, demo):
    try:
        registry = load_registry(db, 'demo' if replay or demo else 'public')
    except ValueError:
        registry = {'skills': []}
    results = []
    for op in opportunities(db, now, replay):
        for role in db.execute('SELECT * FROM roles WHERE revision_id=?', (op['revision_id'],)):
            requirements = json.loads(role['requirements_json']) or []
            text = ' '.join([role['title'], *(r['text'] for r in requirements)])
            if not contains(text, term):
                continue
            refs = [citations.revision(db, op['revision_id'], 'roles')]
            approved = [s for s in registry['skills'] if s.get('approved') is True
                        and skill_matches(s, text) and citations.skill(db, s['id'])]
            refs.extend(citations.skill(db, s['id']) for s in approved[:3])
            mode = op['fields']['mode']
            fit = preference_fit(db, {'mode': mode['normalized'] if mode['status'] in {
                'found', 'inferred'} else None, **relocation_evidence(op['mail']['body_text'])})
            refs.extend(citations.rule(db, r['rule_id']) for r in fit['preference_reasons'])
            if fit['preference_reasons']:
                refs.append(citations.revision(db, op['revision_id'], 'mode'))
            explanation = '; '.join(r['text'] + ': ' + r['evidence']
                                    for r in fit['preference_reasons']) or 'No preference adjustment'
            results.append((fit['preference_score'], item(
                f"{op['company']} · {role['title']} · {op['status']}. "
                f"Approved skill matches: {', '.join(s['name'] for s in approved) or 'none'}. "
                f'{explanation}. Preferences rank matches; they do not establish eligibility.', *refs)))
    results.sort(key=lambda r: -r[0])
    return reply(f'{len(results)} stored role matches for “{term}”. Showing up to 20. '
                 'Search includes stored titles and requirements; approved skills are separate evidence.',
                 items=[r[1] for r in results[:20]])


def prepare(db, intent, now, *, replay, selection):
    if replay:
        return reply('Commands are unavailable in read-only replay. You can ask local questions.',
                     suggestions=EXAMPLES[:5])
    action = {'kind': intent.kind, 'entity': intent.entity, 'value': intent.value}
    if intent.kind == 'task_done':
        from inbound.tasks import list_tasks

        candidates = [(f"task:{t['id']}", f"{t['course'] or 'Course unknown'} · {t['title']}", t)
                      for t in list_tasks(db, now, active=True)
                      if matches(intent.entity, f"{t['course'] or ''} {t['title']}")]
        task, choices = choose(candidates, selection)
        if task is None:
            return reply('Choose the task you mean.' if choices else
                         'No matching open college task found.', choices=choices)
        action.update(id=task['id'], version=task['version'])
        return reply(f"Mark {task['title']} done? This records your decision locally.",
                     action=action, items=[item('Current task evidence.', citations.task(db, task))])
    if intent.kind == 'skip':
        candidates = [(f"opportunity:{o['id']}", f"{title_of(o)} · call {o['id']}", o)
                      for o in opportunities(db, now, replay)
                      if matches(intent.entity, f"{o['company'] or ''} {o['mail']['subject']}")]
        op, choices = choose(candidates, selection)
        if op is None:
            return reply('Choose the call you mean.' if choices else 'No matching stored call found.',
                         choices=choices)
        action.update(id=op['id'], revision=op['revision_id'], content_version=op['content_version'])
        return reply(f"Skip {op['company']} because {intent.value}? Only this call will be skipped.",
                     action=action, items=[item('Current call evidence.',
                                               citations.revision(db, op['revision_id']))])
    if intent.kind == 'forget':
        candidates = [(f"memory:{m['id']}", f"Memory · {m['display_title']}",
                       {'type': 'memory', 'id': m['id']}) for m in memory.retrieve(db)
                      if matches(intent.entity.replace(' preference', ''),
                                 m['display_title'] + ' ' + m['name'] + ' ' + m['content'])]
        for r in db.execute("SELECT * FROM learned_rules WHERE kind='preference' AND status='active'"):
            title = EFFECTS[json.loads(r['definition_json'])['effect']]
            if matches(intent.entity.replace(' preference', ''), title):
                candidates.append((f"rule:{r['id']}", f'Preference · {title}',
                                   {'type': 'rule', 'id': r['id'], 'version': r['version']}))
        chosen, choices = choose(candidates, selection, always=True)
        if chosen is None:
            return reply('Choose the memory or preference to remove from active use.' if choices
                         else 'No matching active memory or preference found.', choices=choices)
        action.update(chosen)
    return reply({'remember': 'Save this explicit instruction locally? Supported mode/relocation '
                  'preferences affect ranking only. Other prose is remembered without active influence.',
                  'forget': 'Remove the selected memory or preference from active use? '
                  'Historical conversation text and artifacts can remain. Clear conversation to remove it here.',
                  'check': 'Run the existing guarded Gmail check now?',
                  'pause': 'Pause new work? Saved questions remain available.'}[intent.kind], action=action)
