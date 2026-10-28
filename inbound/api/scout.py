"""Local queries and explicitly confirmed commands have separate capability boundaries."""

from uuid import uuid4

from flask import abort, request, session
from itsdangerous import BadSignature, URLSafeSerializer, URLSafeTimedSerializer

from inbound import learning, memory, scout, scout_citations
from inbound.pause import set_paused


def register(app, db, output, settings, clock, skip, check_now):
    commands = URLSafeTimedSerializer(app.secret_key, salt='scout-command-v1')
    evidence = URLSafeSerializer(app.secret_key, salt='scout-citation-v1')

    def public_reply(value):
        # Only the typed public reference is exposed alongside the signed original excerpt.
        for item in value['items']:
            item['citations'] = [
                {**{k: c[k] for k in ('entity_type', 'entity_id', 'version', 'label', 'snapshot_at')},
                 'url': '/api/scout/citation?ticket=' + evidence.dumps(c)}
                for c in item['citations']
            ]
        return value

    def generation(connection):
        return connection.execute('SELECT generation FROM domain_generation WHERE id=1').fetchone()[0]

    def ticket(action, connection):
        snapshot = memory.current_snapshot(connection)
        return commands.dumps(action | {'generation': generation(connection),
                                        'memory_version': snapshot['version'] if snapshot else 0,
                                        'csrf': session.get('csrf_token'), 'nonce': uuid4().hex})

    def command(action, connection, label='Confirm command'):
        return {'ticket': ticket(action, connection), 'label': label,
                'path': '/api/scout/pause' if action['kind'] == 'pause' else '/api/scout/command'}

    @app.get('/api/scout/query')
    def query():
        if set(request.args) - {'q', 'selection'} or any(
            len(request.args.getlist(k)) != 1 for k in request.args
        ) or len(request.args.get('selection', '')) > 100:
            abort(400)
        connection = db()
        # SQLite enforces read-only execution as well as the separate handler/module design.
        connection.execute('PRAGMA query_only=ON')
        try:
            connection.execute('BEGIN')
            value = scout.query(connection, request.args.get('q'), clock(),
                                replay=app.config['APP_MODE'] == 'replay',
                                selection=request.args.get('selection'), demo=app.config['DEMO'])
            action = value.pop('action', None)
            if action:
                value['command'] = command(action, connection)
            value['snapshot_at'] = clock().isoformat()
            value = public_reply(value)
            # Group membership is retained without embedding a second copy of each citation.
            if 'groups' in value:
                value['groups'] = {k: [i['text'] for i in v] for k, v in value['groups'].items()}
        finally:
            connection.rollback()
            connection.execute('PRAGMA query_only=OFF')
        return output(value)

    @app.get('/api/scout/citation')
    def citation():
        if set(request.args) != {'ticket'} or len(request.args['ticket']) > 64000:
            abort(400)
        try:
            captured = evidence.loads(request.args['ticket'])
        except BadSignature:
            abort(400, 'Invalid citation')
        value = scout_citations.resolve(db(), captured, replay=app.config['APP_MODE'] == 'replay')
        if value is None:
            abort(404, 'This evidence is no longer available for retrieval')
        return output(value)

    def authorized_action(pause_only):
        value = request.get_json()
        if set(value) != {'ticket'} or not isinstance(value['ticket'], str):
            abort(400)
        try:
            action = commands.loads(value['ticket'], max_age=600)
        except BadSignature:
            abort(400, 'Command preview expired or invalid; ask again')
        if action.get('csrf') != session.get('csrf_token') or (
            (action['kind'] == 'pause') != pause_only
        ):
            abort(400, 'This command preview does not match this session or operation')
        return action

    @app.post('/api/scout/pause')
    def pause():
        action = authorized_action(True)
        connection = db()
        connection.execute('BEGIN IMMEDIATE')
        with connection:
            if generation(connection) != action['generation']:
                abort(409, 'Stored information changed; ask again')
            set_paused(connection, True)
        return output(scout.reply("I'm paused. Your saved information is available."))

    @app.post('/api/scout/command')
    def execute():
        action = authorized_action(False)
        connection = db()
        expected = action['generation']
        kind = action['kind']
        undo = None
        suggestion = None
        refs = []
        if kind == 'skip':
            result, _ = skip(action['id'], {'status': 'skipped', 'reason': action['value']},
                             expected_generation=expected, expected_revision=action['revision'],
                             expected_content_version=action['content_version'])
            suggestion = result.get_json()['learning_rule']
            text = f"You skipped this call because {action['value']}."
            refs = [scout_citations.revision(connection, action['revision'])]
            if suggestion:
                text += ' Prefer roles without this requirement in future? Review the scoped suggestion in Memory.'
        elif kind == 'remember':
            # Only the exact supported preference grammar can activate behavior.
            try:
                rule = learning.instruction(connection, 'Remember that ' + action['entity'],
                                            expected_generation=expected)
            except ValueError:
                result = memory.mutate(connection, settings, 'add',
                                       expected_version=action['memory_version'],
                                       expected_generation=expected,
                                       document={'name': 'scout-' + uuid4().hex,
                                                 'title': action['entity'][:100],
                                                 'description': 'Explicit local instruction',
                                                 'type': 'user', 'content': action['entity']})
                saved = next(m for m in result['items'] if m['version'] == result['version'])
                refs = [scout_citations.remembered(saved)]
                undo = {'kind': 'forget', 'type': 'memory', 'id': saved['id']}
                text = 'Saved locally. Remembered for retrieval only; no active behavior rule.'
            else:
                undo = {'kind': 'forget', 'type': 'rule', 'id': rule['id'], 'version': rule['version']}
                refs = [scout_citations.rule(connection, rule['id'])]
                text = 'Saved locally. Scope: opportunity ranking only; never rejection or deadline changes.'
        elif kind == 'forget':
            if action['type'] == 'rule':
                learning.change(connection, action['id'], 'undo', expected_version=action['version'],
                                expected_generation=expected)
            else:
                memory.mutate(connection, settings, 'forget', memory_id=action['id'],
                              expected_version=action['memory_version'], expected_generation=expected)
            text = ('Selected memory or preference removed from active use. Historical conversation '
                    'text and artifacts may remain. For imported memories, the original curated file '
                    'remains unchanged and suppression prevents retrieval. '
                    'Clear conversation to remove its text here.')
        elif kind == 'check':
            connection.execute('BEGIN IMMEDIATE')
            with connection:
                memory.guard(connection, expected)
            # Existing Gmail owns its sync reservation, Pause rechecks and publication guards.
            check_now()
            text = 'The guarded Gmail check completed. Review the recorded check for results.'
        else:
            abort(400)
        value = scout.reply(text, items=[scout.item('Saved evidence.', *refs)] if refs else [])
        if undo:
            value['undo'] = command(undo, connection, 'Undo')
        value['suggestion'] = suggestion
        return output(public_reply(value))
