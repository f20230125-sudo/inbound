"""Bounded journal reads and same-origin SSE. Reading never starts work."""

import json
import sqlite3
import time
from contextlib import closing

from flask import Response, abort, request

from inbound.steps import page


def cursor(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        abort(400, "A nonnegative journal cursor is required")
    result = int(value)
    if result > 9223372036854775807:
        abort(400, "Journal cursor is too large")
    return result


def register(app, db, output, settings):
    @app.get("/api/agent/steps")
    def steps():
        if set(request.args) - {"after", "replay", "through"}:
            abort(400)
        recording = request.args.get("replay")
        recording_id = cursor(recording) if recording not in {None, "last"} else None
        through = cursor(request.args["through"]) if "through" in request.args else None
        return output(
            page(
                db(),
                cursor(request.args.get("after", "0")),
                replay=app.config["APP_MODE"] == "replay",
                recorded=recording is not None,
                recording_id=recording_id,
                through=through,
                tail=recording is None and "after" not in request.args,
            )
        )

    @app.get("/api/agent/stream")
    def stream():
        if request.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
            abort(403, "Same origin required")
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            abort(403, "Same origin required")
        after = cursor(request.headers.get("Last-Event-ID", request.args.get("after", "0")))
        db()  # Apply exactly the same replay/database guard before starting the response.
        replay = app.config["APP_MODE"] == "replay"
        heartbeat = app.config.get("AGENT_HEARTBEAT", 15)

        def events():
            nonlocal after
            # This connection only reads, holds no transaction between yields, and closes
            # on disconnect. It does not depend on Flask's torn-down request context.
            with closing(sqlite3.connect(settings.db_path)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                last_heartbeat = time.monotonic()
                while True:
                    result = page(connection, after, replay=replay)
                    for step in result["steps"]:
                        after = step["id"]
                        yield f"id: {after}\ndata: {json.dumps(step)}\n\n"
                    if time.monotonic() - last_heartbeat >= heartbeat:
                        yield ": heartbeat\n\n"
                        last_heartbeat = time.monotonic()
                    if not result["has_more"]:
                        time.sleep(1)

        return Response(events(), mimetype="text/event-stream", headers={"X-Accel-Buffering": "no"})
