"""Learning endpoints retain the desk's Host, CSRF, mode, Pause and import guards."""

from flask import abort, request

from inbound import learning


def register(app, db, output):
    @app.errorhandler(learning.LearningConflict)
    def learning_conflict(exc):
        return output({"error": "conflict", "message": str(exc)}, 409)

    @app.get("/api/learning")
    def learned_rules():
        return output(learning.view(db(), replay=app.config["APP_MODE"] == "replay"))

    @app.get("/api/learning/review")
    def sender_review():
        return output(learning.review(db(), replay=app.config["APP_MODE"] == "replay"))

    @app.post("/api/learning/sender")
    def suggest_sender():
        value = request.get_json()
        if set(value) != {"message_id", "category", "subject"}:
            abort(400)
        connection = db()
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            result = learning.suggest_sender(connection, **value)
        return output(result)

    @app.post("/api/learning/preference")
    def structured_preference():
        value = request.get_json()
        if set(value) != {"effect"}:
            abort(400)
        return output(learning.suggest_preference(db(), value["effect"]))

    @app.post("/api/learning/instruction")
    def learning_instruction():
        value = request.get_json()
        if set(value) != {"instruction"}:
            abort(400)
        return output(learning.instruction(db(), value["instruction"]))

    @app.post("/api/learning/<rid>")
    def change_rule(rid):
        value = request.get_json()
        if set(value) != {"action", "expected_version"}:
            abort(400)
        return output(learning.change(db(), rid, **value))

    @app.get("/api/learning/<rid>/preview")
    def preview_rule(rid):
        if app.config["APP_MODE"] == "replay" and learning.get(db(), rid)["source"] != "synthetic":
            abort(404)
        return output(learning.preview(db(), rid, replay=app.config["APP_MODE"] == "replay"))

    @app.post("/api/learning/<rid>/reprocess")
    def reprocess_rule(rid):
        value = request.get_json()
        if set(value) != {"expected_version", "expected_token"}:
            abort(400)
        return output(learning.reprocess(db(), rid, **value))
