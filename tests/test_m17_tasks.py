"""Fictional college work and saved local briefings, with no external capability."""

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from inbound.db import connect, import_messages
from inbound.extract.pipeline import extract_messages
from inbound.models import Message
from inbound.triage.rules import triage_messages
from tests.test_api import app as app_fixture
from tests.test_api import post

app = app_fixture
NOW = datetime.fromisoformat('2026-10-28T10:00:00+04:00')


def mails():
    return [Message(provider_id=r['id'], provider='export', thread_id=r['thread'],
                    sender=r['sender'], subject=r['subject'], body_text=r['body'],
                    sent_at=datetime.fromisoformat(r['sent']),
                    received_at=datetime.fromisoformat(r['sent']), source='synthetic')
            for r in json.loads(Path('fixtures/college.json').read_text(encoding='utf-8'))]


def seed(db, messages=None):
    import_messages(db, messages or mails())
    triage_messages(db)
    extract_messages(db, clock=lambda: NOW)


def test_extraction_revision_precision_unknown_and_no_seating(tmp_path):
    from inbound.tasks import list_tasks

    with connect(tmp_path / 'tasks.sqlite') as db:
        seed(db)
        tasks = list_tasks(db, NOW)
        assert len(tasks) == 4
        quiz = next(t for t in tasks if t['course'] == 'CS F211')
        assert quiz['deadline']['normalized'] == '2026-10-29T09:00:00+04:00'
        assert len(quiz['history']) == 2
        case = next(t for t in tasks if t['title'] == 'Case study 3')
        assert case['deadline']['normalized'] == '2026-10-29'
        assert case['deadline']['precision'] == 'date'
        assert next(t for t in tasks if t['course'] == 'CS F213')['deadline']['status'] == 'unknown'
        assert all(t['source_quote'] and t['state'] == 'open' for t in tasks)
        before = db.execute('SELECT COUNT(*) FROM agent_steps').fetchone()[0]
        extract_messages(db, clock=lambda: NOW)
        assert db.execute('SELECT COUNT(*) FROM agent_steps').fetchone()[0] == before


def test_conflict_relative_and_late_arrival(tmp_path):
    from inbound.tasks import list_tasks

    base = mails()[1]
    other = replace(base, provider_id='other', sent_at=NOW,
                    body_text='Course: CS F211\nQuiz: Quiz 1\nQuiz on 30 October 2026 at 10 AM.')
    with connect(tmp_path / 'tasks.sqlite') as db:
        seed(db, [other])
        seed(db, [base])
        task = list_tasks(db, NOW)[0]
        assert task['deadline']['status'] == 'conflicting'
        assert len(task['deadline']['candidates']) == 2
    with connect(tmp_path / 'relative.sqlite') as db:
        seed(db, [replace(base, body_text='Course: CS F211\nQuiz: Quiz 1\nQuiz tomorrow at 8 AM.')])
        assert list_tasks(db, NOW)[0]['deadline']['status'] == 'inferred'


def test_campus_date_requires_task_evidence_and_quoted_history_is_ignored(tmp_path):
    from inbound.tasks import list_tasks

    campus = replace(mails()[2], body_text='Course: Fictional History\nExam on 30 October 2026.')
    with connect(tmp_path / 'tasks.sqlite') as db:
        seed(db, [campus])
        assert len(list_tasks(db, NOW)) == 1
    with connect(tmp_path / 'none.sqlite') as db:
        seed(db, [replace(campus, subject='Campus notice', body_text='Assignment information follows.\n'
                         'On Tuesday, someone wrote:\n> Exam on 30 October 2026.')])
        assert list_tasks(db, NOW) == []


def test_actions_undo_and_stale_version(app):
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db)
    client = app.test_client()
    tasks = client.get('/api/tasks').json['items']
    task = tasks[0]
    path = f"/api/tasks/{task['id']}/action"
    for action in ('done', 'snooze', 'not_mine'):
        payload = {'action': action, 'expected_version': task['version']}
        if action == 'snooze':
            payload['until'] = '2026-10-30T10:00:00+04:00'
        result = post(client, path, payload)
        assert result.status_code == 200, result.json
        assert post(client, path, payload).status_code == 409
        changed = result.json
        result = post(client, path, {'action': 'undo', 'expected_version': changed['version']})
        assert result.status_code == 200, result.json
        task = result.json
        assert task['state'] == 'open'
    with connect(app.config['SETTINGS'].db_path) as db:
        events = db.execute("SELECT * FROM agent_steps WHERE kind LIKE 'action.task_%'").fetchall()
        assert len(events) == 6 and all(e['actor'] == 'uzair' for e in events)
        assert all(json.loads(e['facts_json']) == {} for e in events)


@pytest.mark.parametrize('guard,status', [('csrf', 403), ('pause', 409), ('replay', 405),
                                          ('import', 409), ('host', 403)])
def test_task_guards(app, guard, status):
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db)
        if guard == 'pause':
            db.execute("UPDATE settings SET value='1' WHERE key='paused'")
        if guard == 'import':
            db.execute("INSERT INTO runs(kind,started_at,status,operation_key) "
                       "VALUES ('import',?,'running','import')", (NOW.isoformat(),))
    if guard == 'replay':
        app.config['APP_MODE'] = 'replay'
    client = app.test_client()
    task = client.get('/api/tasks').json['items'][0]
    payload = {'action': 'done', 'expected_version': task['version']}
    path = f"/api/tasks/{task['id']}/action"
    if guard in {'csrf', 'replay'}:
        response = client.post(path, json=payload)
    elif guard == 'host':
        response = client.post(path, json=payload, headers={'Host': 'evil.example'})
    else:
        response = post(client, path, payload)
    assert response.status_code == status


def test_briefing_saved_once_per_dubai_day_and_cited_activity(app):
    app.config['CLOCK'] = lambda: NOW
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db)
    client = app.test_client()
    first = post(client, '/api/briefing', {}).json
    assert first['day'] == '2026-10-28'
    assert any(i['kind'] == 'task' for i in first['items'])
    assert all(i['href'] and i['source_refs'] for i in first['items'])
    assert post(client, '/api/briefing', {}).json == first
    with connect(app.config['SETTINGS'].db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM briefings').fetchone()[0] == 1
    app.config['CLOCK'] = lambda: NOW + timedelta(days=1)
    assert post(client, '/api/briefing', {}).json['id'] != first['id']
    activity = client.get('/api/scout/query', query_string={'q': 'What did you do today?'}).json
    assert any('briefing' in i['text'] for i in activity['items'])
    assert client.get(f"/api/briefing/{first['id']}").json == first


def test_scout_task_query_preview_confirm_and_undo(app):
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db)
    client = app.test_client()
    client.get('/api/settings')
    query = client.get('/api/scout/query', query_string={'q': 'what assignments are due'}).json
    assert len(query['items']) == 4
    citation = query['items'][0]['citations'][0]
    assert client.get(citation['url']).status_code == 200
    preview = client.get('/api/scout/query', query_string={'q': 'mark Assignment 2 done'}).json
    assert preview['command']
    command = preview['command']
    result = post(client, command['path'], {'ticket': command['ticket']})
    assert result.status_code == 200, result.json
    undo = result.json['undo']
    assert post(client, undo['path'], {'ticket': undo['ticket']}).status_code == 200


def test_decisions_and_briefing_keep_earlier_ps_deadline_first(app):
    from inbound.briefing import generate
    from inbound.digest import today

    ps = replace(mails()[0], provider_id='ps', thread_id='ps',
                 sender='ps@dubai.bits-pilani.ac.in',
                 subject='Call for CV - Aster Fictional,Dubai - Intern',
                 body_text='CV Submission Deadline: 28 October 2026 at 11 AM')
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db, [*mails(), ps])
        assert today(db, NOW)['decision_queue'][0]['kind'] == 'call'
        dispatch = generate(db, NOW)
        assert dispatch['items'][0]['kind'] == 'call'
        assert 'today' in dispatch['items'][0]['text']


def test_revision_preserves_manual_done_and_citation_identifies_newer_info(app):
    app.config['CLOCK'] = lambda: NOW
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db, [mails()[1]])
    client = app.test_client()
    client.get('/api/settings')
    result = client.get('/api/scout/query', query_string={'q': 'what assignments are due'}).json
    citation = result['items'][0]['citations'][0]['url']
    task = client.get('/api/tasks').json['items'][0]
    post(client, f"/api/tasks/{task['id']}/action",
         {'action': 'done', 'expected_version': task['version']})
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db, [mails()[3]])
    task = client.get('/api/tasks').json['items'][0]
    assert task['state'] == 'done'
    assert task['deadline']['normalized'] == '2026-10-29T09:00:00+04:00'
    original = client.get(citation).json
    assert original['newer_information']
    assert original['content']['deadline']['normalized'] == '2026-10-28T18:00:00+04:00'


def test_snooze_expiry_refreshes_briefing_without_mutating_task(app):
    from inbound.briefing import generate
    from inbound.tasks import list_tasks, mutate

    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db)
        task = list_tasks(db, NOW)[0]
        mutate(db, task['id'], 'snooze', task['version'], NOW,
               until=(NOW + timedelta(hours=1)).isoformat())
        first = generate(db, NOW)
        assert not any(i['href'] == task['href'] for i in first['items'])
        later = generate(db, NOW + timedelta(hours=2))
        assert any(i['href'] == task['href'] for i in later['items'])
        assert later['id'] != first['id']
        assert list_tasks(db, NOW + timedelta(hours=2))[0]['state'] == 'snoozed'


def test_read_endpoints_and_queries_do_not_write_and_replay_hides_private(app):
    from inbound.briefing import generate

    app.config['CLOCK'] = lambda: NOW
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db)
        generate(db, NOW)
    client = app.test_client()
    client.get('/api/settings')
    with connect(app.config['SETTINGS'].db_path) as db:
        before = '\n'.join(db.iterdump())
    for path in ('/api/tasks', '/api/briefing', '/api/briefing/1',
                 '/api/scout/query?q=what+assignments+are+due',
                 '/api/scout/query?q=mark+Assignment+2+done'):
        assert client.get(path).status_code == 200
    with connect(app.config['SETTINGS'].db_path) as db:
        assert '\n'.join(db.iterdump()) == before
        db.execute("INSERT INTO briefings(day,generation,projection_key,created_at,source,payload_json) "
                   "VALUES ('2026-10-28',0,'private',?,'private','{}')", (NOW.isoformat(),))
        private_id = db.execute('SELECT MAX(id) FROM briefings').fetchone()[0]
    app.config['APP_MODE'] = 'replay'
    assert client.get(f'/api/briefing/{private_id}').status_code == 404
    assert client.post('/api/briefing', json={}).status_code == 405


def test_failed_staged_import_publishes_no_task_or_result(app, monkeypatch):
    from inbound import work

    # Stage the fictional inputs through the real importer before a later stage fails.
    monkeypatch.setattr('inbound.sources.export_txt.load', lambda *a: iter(mails()))

    def fail(*args):
        raise ValueError('fictional failure after college extraction')

    monkeypatch.setattr(work, 'index_locations', fail)
    response = post(app.test_client(), '/api/import')
    assert response.status_code == 202
    with connect(app.config['SETTINGS'].db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM agent_steps WHERE kind='task.found'").fetchone()[0] == 0


def test_cli_briefing_saved_history(app, monkeypatch, capsys):
    from inbound.__main__ import main

    root = app.config['SETTINGS'].data_root
    monkeypatch.setenv('INBOUND_DATA_ROOT', str(root))
    with connect(root / 'demo.sqlite') as db:
        seed(db)
        db.execute("INSERT INTO settings(key,value) VALUES ('demo_clock',?)", (NOW.isoformat(),))
    assert main(['briefing']) == 0
    assert 'Good morning.' in capsys.readouterr().out
    assert main(['briefing']) == 0
    with connect(root / 'demo.sqlite') as db:
        assert db.execute('SELECT COUNT(*) FROM briefings').fetchone()[0] == 1


def test_append_only_sources_and_generation_rollback(tmp_path):
    from inbound.tasks import extract_tasks, list_tasks, mutate

    with connect(tmp_path / 'tasks.sqlite') as db:
        import_messages(db, mails())
        triage_messages(db)
        before = db.execute('SELECT generation FROM domain_generation').fetchone()[0]
        db.execute('BEGIN')
        extract_tasks(db)
        db.rollback()
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
        assert db.execute('SELECT generation FROM domain_generation').fetchone()[0] == before
        seed(db)
        task = list_tasks(db, NOW)[0]
        mutate(db, task['id'], 'done', task['version'], NOW)
        for table in ('task_revisions', 'task_actions'):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(f"UPDATE {table} SET id=id")
            db.rollback()


def test_past_deadline_today_still_appears_in_briefing(tmp_path):
    from inbound.briefing import generate

    with connect(tmp_path / 'tasks.sqlite') as db:
        seed(db, [mails()[1]])
        dispatch = generate(db, NOW.replace(hour=19))
        assert any('passed' in i['text'] and i['kind'] == 'task' for i in dispatch['items'])


@pytest.mark.parametrize('body', [
    'Course: CS F212\nAssignment: Assignment 2\nPublished on 28 October 2026.\nDue date pending.',
    'Course: CS F212\nAssignment: Assignment 2\nMeeting on 28 October 2026 at 10 AM.',
    'Course: CS F212\nAssignment: Assignment 2\nDue date will be announced on 28 October 2026.',
    'Course: CS F212\nAssignment: Assignment 2\nDue: 28 October 2026 at 5 PM IST.',
])
def test_unrelated_dates_and_unsupported_timezone_remain_unknown(tmp_path, body):
    from inbound.tasks import list_tasks

    with connect(tmp_path / 'tasks.sqlite') as db:
        seed(db, [replace(mails()[0], body_text=body)])
        assert list_tasks(db, NOW)[0]['deadline']['status'] == 'unknown'


def test_unknown_course_is_not_invented_and_subject_dates_are_supported(tmp_path):
    from inbound.tasks import list_tasks

    with connect(tmp_path / 'tasks.sqlite') as db:
        seed(db, [replace(mails()[1], subject='Quiz 4 on 29 October 2026 at 10 AM',
                          body_text='Bring a pencil.')])
        task = list_tasks(db, NOW)[0]
        assert task['course'] is None and task['course_status'] == 'unknown'
        assert task['deadline']['normalized'] == '2026-10-29T10:00:00+04:00'


def test_same_course_and_title_merge_across_threads_when_subject_has_due_clause(tmp_path):
    from inbound.tasks import list_tasks

    first = replace(mails()[0], subject='CS F212 Assignment 3 due on 29 October 2026',
                    body_text='Course: CS F212')
    second = replace(first, provider_id='second', thread_id='new-thread', sent_at=NOW,
                     subject='CS F212 Assignment 3 due on 30 October 2026')
    with connect(tmp_path / 'tasks.sqlite') as db:
        seed(db, [first, second])
        tasks = list_tasks(db, NOW)
        assert len(tasks) == 1
        assert tasks[0]['title'] == 'Assignment 3'
        assert tasks[0]['deadline']['status'] == 'conflicting'


def test_malformed_task_action_fails_closed(app):
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db)
    client = app.test_client()
    task = client.get('/api/tasks').json['items'][0]
    assert post(client, f"/api/tasks/{task['id']}/action",
                {'action': ['done'], 'expected_version': task['version']}).status_code == 400


def test_replay_rejects_private_task_projection(app):
    with connect(app.config['SETTINGS'].db_path) as db:
        seed(db)
        db.execute("INSERT INTO tasks(course,title,source) VALUES ('Private','Private','private')")
    app.config['APP_MODE'] = 'replay'
    client = app.test_client()
    for path in ('/api/today', '/api/tasks', '/api/briefing', '/api/agent/steps'):
        assert client.get(path).status_code == 403
