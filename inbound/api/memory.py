"""Memory reads never scan the filesystem; mutations share the desk's existing guards."""

from flask import abort, request

from inbound import memory


def register(app, db, output, settings):
    @app.get("/api/memory")
    def get_memory():
        if request.args:
            abort(400)
        return output(memory.view(db(), replay=app.config["APP_MODE"] == "replay"))

    @app.get("/api/memory/<mid>/versions/<int:version>")
    def get_memory_version(mid, version):
        result = memory.resolve(
            db(),
            {"entity_type": "memory", "entity_id": mid, "version": version},
            replay=app.config["APP_MODE"] == "replay",
        )
        if result is None:
            abort(404)
        return output(result)

    @app.post("/api/memory/refresh")
    def refresh_memory():
        if request.get_json() != {}:
            abort(400, "Memory directories are configured locally")
        try:
            return output(memory.refresh(db(), settings))
        except memory.MemoryConflict as exc:
            abort(409, str(exc))

    @app.post("/api/memory")
    def change_memory():
        value = request.get_json()
        if not {"action", "expected_version"} <= value.keys() or value.keys() - {
            "action",
            "expected_version",
            "memory_id",
            "document",
        }:
            abort(400)
        if not isinstance(value["action"], str):
            abort(400)
        if value["action"] == "add" and "memory_id" in value:
            abort(400)
        if value["action"] not in {"add", "edit"} and "document" in value:
            abort(400)
        try:
            return output(memory.mutate(db(), settings, **value))
        except memory.MemoryConflict as exc:
            abort(409, str(exc))
