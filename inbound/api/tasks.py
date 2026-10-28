"""Guarded local college actions and saved briefing retrieval."""

from flask import abort, request

from inbound import briefing, tasks


def register(app, db, output, clock):
    @app.get('/api/tasks')
    def college_tasks():
        return output({'items': tasks.list_tasks(db(), clock(),
                                                replay=app.config['APP_MODE'] == 'replay')})

    @app.post('/api/tasks/<int:tid>/action')
    def task_action(tid):
        value = request.get_json()
        if set(value) - {'action', 'expected_version', 'until'}:
            abort(400)
        return output(tasks.mutate(db(), tid, value.get('action'), value.get('expected_version'),
                                   clock(), until=value.get('until')))

    @app.get('/api/briefing')
    def current_briefing():
        replay = app.config['APP_MODE'] == 'replay'
        return output(briefing.current(db(), clock(), replay=replay))

    @app.get('/api/briefing/<int:identity>')
    def recorded_briefing(identity):
        value = briefing.saved(db(), identity, replay=app.config['APP_MODE'] == 'replay')
        if value is None:
            abort(404)
        return output(value)

    @app.post('/api/briefing')
    def prepare_briefing():
        if request.get_json():
            abort(400)
        return output(briefing.generate(db(), clock()))
