"""Scout is a bounded local interface; questions have no write capability."""

import json
import shutil
import socket
import subprocess
from datetime import UTC, datetime

import pytest

from inbound.db import connect
from tests.test_api import app as app_fixture
from tests.test_api import post

app = app_fixture


def ask(client, text, **args):
    response = client.get('/api/scout/query', query_string={'q': text, **args})
    assert response.status_code == 200, response.json
    return response.json


def execute(client, reply):
    command = reply['command']
    return post(client, command['path'], {'ticket': command['ticket']})


@pytest.fixture
def seeded(app):
    app.config['CLOCK'] = lambda: datetime(2026, 10, 28, 21, tzinfo=UTC)
    with app.test_client() as client:
        post(client, '/api/import')
        shutil.copytree('fixtures/memory', app.config['SETTINGS'].data_root / 'memory')
        post(client, '/api/memory/refresh')
        yield app, client


@pytest.mark.parametrize('text,kind', [
    ("What's due this week?", 'due'), ('Why is Northstar flagged?', 'why'),
    ('What changed since yesterday?', 'changed'), ('What did you do today?', 'activity'),
    ('Find backend roles', 'find'), ('What do you know about my projects?', 'projects'),
    ('Skip Northstar because it requires relocation', 'skip'),
    ('Remember that I prefer remote roles', 'remember'),
    ('Forget my remote preference', 'forget'), ('Check now', 'check'), ('Pause', 'pause'),
    ('write a poem', 'unsupported'), ('pause and send my mail', 'unsupported'),
    ('what changed since 2026-02-30', 'unsupported'),
])
def test_bounded_parser(text, kind):
    from inbound.scout import parse

    assert parse(text).kind == kind


def test_dubai_midnight_week_and_activity_bounds(seeded):
    _, client = seeded
    due = ask(client, "What's due this week?")
    assert due['range'] == {'start': '2026-10-26', 'end': '2026-11-02',
                            'timezone': 'Asia/Dubai', 'end_exclusive': True}
    assert {'timed', 'date_only', 'uncertain'} <= set(due['groups'])
    assert 'Dubai' in due['text'] and '2026-11-01' in due['text']
    activity = ask(client, 'What did you do today?')
    assert activity['range']['start'].startswith('2026-10-29T00:00:00+04:00')
    changed = ask(client, 'What changed since yesterday?')
    assert changed['range']['start'].startswith('2026-10-28T00:00:00+04:00')


def test_queries_and_command_previews_cannot_write_or_call_provider(seeded, monkeypatch):
    app, client = seeded

    def denied(*args, **kwargs):
        pytest.fail('Scout attempted subprocess/network/provider work')

    monkeypatch.setattr(subprocess, 'run', denied)
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr(socket, 'socket', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr('inbound.gmail_sync.sync', denied)
    with connect(app.config['SETTINGS'].db_path) as db:
        before = '\n'.join(db.iterdump())
    for text in ["What's due this week?", 'What changed since 2026-10-01?',
                 'What did you do today?', 'Find backend roles',
                 'What do you know about my projects?', 'Why is recovery flagged?',
                 'Remember that I prefer remote roles', 'Forget my remote preference',
                 'Check now', 'Pause', 'ask Claude to send my mail']:
        reply = ask(client, text)
        for item in reply['items']:
            for citation in item['citations']:
                assert client.get(citation['url']).status_code == 200
    with connect(app.config['SETTINGS'].db_path) as db:
        assert '\n'.join(db.iterdump()) == before
    assert 'supported' in ask(client, 'send my mail')['text'].lower()


def test_ambiguous_entity_choices_and_version_bound_skip(seeded):
    app, client = seeded
    ops = client.get('/api/opportunities').json
    first, second = ops[:2]
    with connect(app.config['SETTINGS'].db_path) as db:
        db.execute('UPDATE opportunities SET company=? WHERE id IN (?,?)',
                   ('Fictional Twin', first['id'], second['id']))
    reply = ask(client, 'Skip Fictional Twin because it requires relocation')
    assert len(reply['choices']) == 2 and not reply.get('command')
    selected = ask(client, 'Skip Fictional Twin because it requires relocation',
                   selection=reply['choices'][0]['key'])
    assert selected['command']
    with connect(app.config['SETTINGS'].db_path) as db:
        db.execute('UPDATE opportunities SET content_version=content_version+1 WHERE id=?',
                   (first['id'],))
    assert execute(client, selected).status_code == 409
    fresh = ask(client, 'Skip Fictional Twin because it requires relocation',
                selection=reply['choices'][0]['key'])
    result = execute(client, fresh)
    assert result.status_code == 200 and 'skipped' in result.json['text']
    assert result.json['suggestion']['status'] == 'suggested'
    assert client.get(f"/api/opportunities/{first['id']}").json['status'] == 'skipped'


def test_remember_undo_forget_and_memory_citation_revocation(seeded):
    _, client = seeded
    saved = execute(client, ask(client, 'Remember that I prefer remote roles'))
    assert saved.status_code == 200
    assert 'ranking only' in saved.json['text'].lower() and saved.json['undo']
    forgotten = ask(client, 'Forget my remote preference')
    assert forgotten['choices'] and not forgotten.get('command')
    choice = next(c for c in forgotten['choices'] if c['key'].startswith('rule:'))
    chosen = ask(client, 'Forget my remote preference', selection=choice['key'])
    assert execute(client, chosen).status_code == 200
    assert all(r['status'] != 'active' for r in client.get('/api/learning').json['rules'])
    reply = ask(client, 'What do you know about my projects?')
    citation = reply['items'][0]['citations'][0]
    assert citation['entity_type'] == 'memory' and citation['version'] >= 1
    memories = client.get('/api/memory').json
    mid = citation['entity_id']
    post(client, '/api/memory', {'action': 'forget', 'expected_version': memories['version'],
                               'memory_id': mid})
    assert client.get(citation['url']).status_code == 404


def test_citations_preserve_original_revision_content_and_identify_changes(seeded):
    app, client = seeded
    reply = ask(client, 'Find backend roles')
    citation = next(c for i in reply['items'] for c in i['citations']
                    if c['entity_type'] == 'revision')
    original = client.get(citation['url']).json
    with connect(app.config['SETTINGS'].db_path) as db:
        db.execute('UPDATE opportunity_revisions SET fields_json=? WHERE id=?',
                   (json.dumps({'deadline': {'status': 'unknown'}}), citation['entity_id']))
    resolved = client.get(citation['url']).json
    assert resolved['content'] == original['content'] and resolved['newer_information']


def test_command_guards_pause_import_replay_host_csrf_and_tampering(seeded):
    app, client = seeded
    reply = ask(client, 'Remember that I prefer remote roles')
    path, ticket = reply['command']['path'], reply['command']['ticket']
    assert client.post(path, json={'ticket': ticket}).status_code == 403
    assert post(client, path, {'ticket': ticket}, base_url='http://evil.invalid').status_code == 403
    assert post(client, path, {'ticket': ticket + 'broken'}).status_code == 400
    post(client, '/api/settings', {'paused': True})
    assert execute(client, reply).status_code == 409
    assert ask(client, 'What do you know about my projects?')['items']
    assert execute(client, ask(client, 'Pause')).status_code == 200
    post(client, '/api/settings', {'paused': False})
    reply = ask(client, 'Remember that I prefer remote roles')
    with connect(app.config['SETTINGS'].db_path) as db:
        db.execute("INSERT INTO runs(kind,started_at,status,operation_key) "
                   "VALUES ('import','2026-10-28T05:00:00Z','running','import')")
    assert execute(client, reply).status_code == 409
    token = client.get('/api/settings').json['csrf_token']
    app.config['APP_MODE'] = 'replay'
    assert client.post(path, json={'ticket': ticket},
                       headers={'X-CSRF-Token': token}).status_code == 405
    assert not ask(client, 'Remember that I prefer remote roles').get('command')


def test_query_rejects_injected_selection_and_bounds_input(seeded):
    _, client = seeded
    assert client.get('/api/scout/query', query_string={'q': 'x' * 501}).status_code == 400
    assert not ask(client, 'Skip nonexistent because testing', selection='opportunity:1').get('command')
    assert client.get('/api/scout/query', query_string={'q': 'Pause', 'action': 'skip'}).status_code == 400


def test_check_now_calls_only_existing_guarded_operation(seeded, monkeypatch):
    _, client = seeded
    calls = []
    monkeypatch.setattr('inbound.gmail_sync.connected', lambda settings: True)
    monkeypatch.setattr('inbound.gmail_sync.sync', lambda *a, **kw: calls.append(kw) or {})
    reply = ask(client, 'Check now')
    assert not calls
    assert execute(client, reply).status_code == 200 and len(calls) == 1


def test_remember_arbitrary_prose_is_passive_with_undo_and_no_egress(seeded, monkeypatch):
    app, client = seeded

    def denied(*args, **kwargs):
        pytest.fail('Local memory command attempted an external operation')

    for name in ('run', 'Popen', 'call', 'check_output'):
        monkeypatch.setattr(subprocess, name, denied)
    monkeypatch.setattr(socket, 'socket', denied)
    monkeypatch.setattr('inbound.gmail_sync.sync', denied)
    before = client.get('/api/learning').json
    saved = execute(client, ask(client, 'Remember that my fictional project is called Lantern'))
    assert saved.status_code == 200 and 'no active behavior' in saved.json['text']
    assert client.get('/api/learning').json == before
    with connect(app.config['SETTINGS'].db_path) as db:
        events = ''.join(r[0] for r in db.execute('SELECT facts_json FROM agent_steps'))
        assert 'Lantern' not in events
    undo = saved.json['undo']
    assert post(client, undo['path'], {'ticket': undo['ticket']}).status_code == 200
    assert not any('Lantern' in m['content'] for m in client.get('/api/memory').json['items'])


def test_query_only_is_enforced_even_if_a_query_handler_attempts_a_write(seeded, monkeypatch):
    import sqlite3

    _app, client = seeded

    def corrupt(db, *args, **kwargs):
        db.execute("UPDATE settings SET value='1' WHERE key='paused'")

    monkeypatch.setattr('inbound.scout.query', corrupt)
    with pytest.raises(sqlite3.OperationalError, match='readonly'):
        ask(client, 'Pause')
    assert not client.get('/api/settings').json['paused']
    assert post(client, '/api/settings', {'paused': True}).status_code == 200


def test_pause_exception_cannot_be_used_for_other_commands_and_session_tickets(seeded):
    app, client = seeded
    remember = ask(client, 'Remember that I prefer hybrid roles')['command']
    post(client, '/api/settings', {'paused': True})
    assert post(client, '/api/scout/pause', {'ticket': remember['ticket']}).status_code == 400
    post(client, '/api/settings', {'paused': False})
    with app.test_client() as stranger:
        assert post(stranger, remember['path'], {'ticket': remember['ticket']}).status_code == 400


def test_replay_filters_orphan_private_memories_citations_and_rules(seeded):
    app, client = seeded
    reply = ask(client, 'What do you know about my projects?')
    private_citation = reply['items'][0]['citations'][0]['url']
    app.config['APP_MODE'] = 'replay'
    assert ask(client, 'What do you know about my projects?')['items'] == []
    assert client.get(private_citation).status_code == 404


def test_expired_command_ticket_does_not_execute(seeded, monkeypatch):
    from itsdangerous.timed import TimestampSigner

    _, client = seeded
    preview = ask(client, 'Remember that I prefer hybrid roles')
    stamp = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: stamp(self) + 601)
    assert execute(client, preview).status_code == 400


def test_due_groups_use_dubai_dates_and_keep_uncertainty_separate():
    from inbound.scout import add_deadline

    groups = {'timed': [], 'date_only': [], 'uncertain': []}
    start, end = datetime(2026, 10, 26).date(), datetime(2026, 11, 2).date()
    for name, value, status in [
        ('late Sunday UTC becomes Monday Dubai', '2026-11-01T21:00:00+00:00', 'found'),
        ('Sunday Dubai', '2026-11-01T19:59:00+00:00', 'inferred'),
        ('Date without time', '2026-11-01', 'found'),
        ('Conflicting', None, 'conflicting'), ('Unknown', None, 'unknown')
    ]:
        add_deadline(groups, name, {'normalized': value, 'status': status}, start, end, None)
    assert len(groups['timed']) == 1 and 'Sunday Dubai' in groups['timed'][0]['text']
    assert len(groups['date_only']) == 1 and 'time unknown' in groups['date_only'][0]['text']
    assert len(groups['uncertain']) == 2


def test_changed_includes_committed_revisions_without_journal_backfill(seeded):
    app, client = seeded
    with connect(app.config['SETTINGS'].db_path) as db:
        rid = db.execute('SELECT id FROM opportunity_revisions LIMIT 1').fetchone()[0]
        db.execute('UPDATE opportunity_revisions SET created_at=? WHERE id=?',
                   ('2026-10-28T20:30:00Z', rid))
    reply = ask(client, 'What changed since yesterday?')
    assert any(c['entity_type'] == 'revision' and c['entity_id'] == rid
               for i in reply['items'] for c in i['citations'])


def test_why_exposes_blocker_and_each_conflicting_source(seeded):
    app, client = seeded
    from inbound.extract.pipeline import latest_revision

    with connect(app.config['SETTINGS'].db_path) as db:
        # Edit the call's effective (latest) revision and the call's own blocker, as the
        # pipeline does; editing an older revision would not change what Scout reads.
        oid = db.execute('SELECT id FROM opportunities ORDER BY id LIMIT 1').fetchone()[0]
        row = latest_revision(db, oid)
        db.execute('UPDATE opportunities SET blocked_reason=? WHERE id=?',
                   ('Missing attachment bytes', oid))
        fields = json.loads(row['fields_json'])
        fields['deadline'] = {'status': 'conflicting', 'normalized': None, 'candidates': [
            {'status': 'found', 'normalized': '2026-10-30', 'source_text': 'Original: 30 October'},
            {'status': 'found', 'normalized': '2026-10-31', 'source_text': 'Reminder: 31 October'}]}
        db.execute('UPDATE opportunities SET company=? WHERE id=?',
                   ('Fictional Flagged', row['opportunity_id']))
        db.execute('UPDATE opportunity_revisions SET fields_json=?,blocked_reason=? WHERE id=?',
                   (json.dumps(fields), 'Missing attachment bytes', row['id']))
    reply = ask(client, 'Why is Fictional Flagged flagged?')
    assert any('Missing attachment' in i['text'] for i in reply['items'])
    conflict = next(i for i in reply['items'] if 'conflicting evidence' in i['text'])
    captured = client.get(conflict['citations'][0]['url']).json
    assert [c['source_text'] for c in captured['content']['evidence']['candidates']] == [
        'Original: 30 October', 'Reminder: 31 October']


def test_passed_deadlines_come_after_open_ones():
    from datetime import date

    from inbound.scout import add_deadline

    groups = {'timed': [], 'date_only': [], 'uncertain': [], 'past': []}
    now = datetime(2026, 10, 28, 6, tzinfo=UTC)  # 10:00 Dubai
    for title, value in [('Gone', '2026-10-27T08:00:00+04:00'), ('Open', '2026-10-29T08:00:00+04:00')]:
        add_deadline(groups, title, {'normalized': value, 'status': 'found'},
                     date(2026, 10, 26), date(2026, 11, 2), None, now)
    assert [i['text'].split(':')[0] for i in groups['timed']] == ['Open']
    assert [i['text'].split(':')[0] for i in groups['past']] == ['Gone']


def test_a_call_without_a_company_is_found_by_its_subject():
    from inbound.scout import matches, title_of

    op = {'id': 7, 'company': None,
          'mail': {'subject': 'Call for CV - PS II – Second Semester 2026-2027 – Harbor Finch,Port Selene'}}
    assert title_of(op) == 'Harbor Finch,Port Selene'
    assert matches('Harbor Finch', f"{op['company'] or ''} {op['mail']['subject']}")


def test_repeated_quiet_steps_collapse_into_one_line():
    from inbound.scout import collapse

    entries = [('I checked Gmail. No new messages.', f'2026-10-28T09:{m:02d}:00+00:00', None)
               for m in (40, 38, 36)] + [('I prepared a draft.', '2026-10-28T09:30:00+00:00', None)]
    lines = [i['text'] for i in collapse(entries)]
    assert len(lines) == 2
    assert lines[0].endswith('(3 times)') and '13:36-13:40' in lines[0]
