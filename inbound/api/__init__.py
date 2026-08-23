"""Loopback-only desk API. Only Gmail sync reaches out, read-only, via sources/gmail_api.py."""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Lock

from flask import (
    Flask,
    Request,
    abort,
    g,
    jsonify,
    request,
    send_file,
    send_from_directory,
    session,
)
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.exceptions import HTTPException

from inbound import gmail_sync
from inbound.api import data
from inbound.application_activity import ActivityConflict, applied_time, latest, record
from inbound.attachment_recovery import RecoveryConflict, TooLarge, confirm, preview
from inbound.db import connect
from inbound.digest import today
from inbound.extract.pipeline import latest_revision
from inbound.ledger import timestamp
from inbound.pause import PausedError, check, set_paused
from inbound.settings import REPO, Settings
from inbound.sources.gmail_api import GmailError
from inbound.steps import Alert, Classification, Empty, Kind, emit
from inbound.triage.taxonomy import CATEGORIES
from inbound.work import execute, start_run

_PREVIEW_LOCK = Lock()


class MemoryUploads(Request):
    def _get_file_stream(self, *args, **kwargs):
        # Bounded recovery uploads never spool attachment bytes into an OS temp directory.
        return BytesIO()


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.request_class = MemoryUploads
    app.config.update(
        APP_MODE=os.environ.get("APP_MODE", "local"),
        # Built from the environment only when the caller passes no settings (the hosted
        # demo passes its own, which the D:-only defaults would reject).
        SETTINGS=(config or {}).get("SETTINGS") or Settings.from_env(),
        IMPORT_ROOT=Path(os.environ.get("INBOUND_IMPORT_ROOT", REPO / "fixtures/export_sample")),
        SOURCE_PROVENANCE=os.environ.get("INBOUND_SOURCE_PROVENANCE", "synthetic"),
        SOURCE_FORMAT=os.environ.get("INBOUND_SOURCE_FORMAT", "export"),
        DEMO=os.environ.get("INBOUND_SOURCE_PROVENANCE", "synthetic") == "synthetic",
        ASYNC_WORK=True,
        SECRET_KEY=secrets.token_hex(32),
        MAX_CONTENT_LENGTH=16384,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        WEB_DIST=REPO / "web/dist",
        CLOCK=None,
        TEST_CLOCK=False,
    )
    app.config.update(config or {})
    if app.config["APP_MODE"] not in {"local", "replay"}:
        raise ValueError("Unknown app mode")
    if app.config["SETTINGS"].hosted_replay and app.config["APP_MODE"] != "replay":
        raise ValueError("A hosted data root is only allowed for the read-only replay")
    settings = app.config["SETTINGS"]
    app.extensions["work_executor"] = ThreadPoolExecutor(max_workers=2)

    def db():
        if "db" not in g:
            g.db = connect(settings.db_path)
            if app.config["APP_MODE"] == "replay":
                if g.db.execute("SELECT 1 FROM messages WHERE source<>'synthetic'").fetchone():
                    abort(403, "Replay requires an exclusively synthetic database")
                if g.db.execute("SELECT 1 FROM packs WHERE demo<>1").fetchone():
                    abort(403, "Replay requires exclusively demo packs")
                if g.db.execute("SELECT 1 FROM tasks WHERE source<>'synthetic'").fetchone():
                    abort(403, "Replay requires exclusively synthetic tasks")
        return g.db

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            abort(400, "JSON object required")
        return value

    def output(value, status=200):
        if app.config["APP_MODE"] == "replay":
            value = data.clean_replay(value)
        return jsonify(value), status

    from inbound.api.agent_steps import register

    register(app, db, output, settings)

    from inbound.api.memory import register as register_memory

    register_memory(app, db, output, settings)

    from inbound.api.learning import register as register_learning

    register_learning(app, db, output)

    @app.teardown_appcontext
    def close_db(error=None):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.before_request
    def guard():
        hosted = app.config.get("HOSTED_HOSTS")
        if hosted and settings.hosted_replay and app.config["APP_MODE"] == "replay":
            # The public read-only demo answers only on its own published hosts.
            if not re.fullmatch(hosted, request.host):
                abort(403, "Unknown host")
        elif not re.fullmatch(r"(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?", request.host):
            abort(403, "Local Host required")
        if ":" in request.host and not 1 <= int(request.host.rsplit(":", 1)[1]) <= 65535:
            abort(403, "Invalid local port")
        if request.method == "POST":
            recovery = request.endpoint in {"attachment_preview", "attachment_confirm"}
            if recovery:
                request.max_content_length = 10 * 1024 * 1024 + 65536
                request.max_form_memory_size = 128 * 1024
                request.max_form_parts = 12
            if app.config["APP_MODE"] != "local":
                abort(405, "Read-only replay")
            token = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not token or not hmac.compare_digest(token.encode(), supplied.encode()):
                abort(403, "CSRF token required")
            value = {} if recovery and request.mimetype == "multipart/form-data" else body()
            if request.path == "/api/settings" and (
                set(value) != {"paused"} or type(value.get("paused")) is not bool
            ):
                abort(400, "Only the boolean Pause setting is editable")
            pause_only = (request.path == "/api/settings" and set(value) == {"paused"}) or (
                request.path == '/api/scout/pause' and set(value) == {'ticket'}
            )
            if not pause_only:
                check(db())
                if (
                    request.path != "/api/import"
                    and db()
                    .execute("SELECT 1 FROM runs WHERE status='running' AND operation_key='import'")
                    .fetchone()
                ):
                    abort(409, "Import is running; wait for its snapshot before making changes")

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.name, message=exc.description), exc.code

    @app.errorhandler(PausedError)
    def paused_error(exc):
        return jsonify(error="paused", message="Resume work to make changes"), 409

    @app.errorhandler(ValueError)
    def invalid_error(exc):
        return jsonify(error="invalid_request"), 400

    @app.errorhandler(RecoveryConflict)
    def recovery_conflict(exc):
        return jsonify(error="conflict", message=str(exc)), 409

    @app.errorhandler(TooLarge)
    def recovery_too_large(exc):
        return jsonify(error="too_large", message=str(exc)), 413

    @app.errorhandler(sqlite3.IntegrityError)
    def busy_error(exc):
        return jsonify(error="conflict"), 409

    @app.get("/api/settings")
    def get_settings():
        connection = db()
        replay = app.config["APP_MODE"] == "replay"
        result = {
            "mode": app.config["APP_MODE"],
            "offline": True,
            "source_format": app.config["SOURCE_FORMAT"],
            "paused": connection.execute(
                "SELECT value FROM settings WHERE key='paused'"
            ).fetchone()[0]
            == "1",
            "capabilities": {"mutations": not replay, "live_models": False, "network": False},
            "budgets": {
                "daily_call_limit": 0,
                "daily_spend_limit": 0,
                "currency": "USD",
                "calls_used_today": 0,
                "spend_used_today": None,
                "resets_timezone": "Asia/Dubai",
                "resets_at": None,
                "limits_editable": False,
            },
            "payload_policy": {
                "private_payloads": "Blocked",
                "allowlist": [],
                "external_network_services": "Disabled",
                "gmail": "Not connected",
                "notifications": "Not implemented",
            },
            "execution": "offline deterministic",
            "model_comparison": "not run",
            "timezone": "Asia/Dubai",
            "clock": current_time().isoformat(),
            "frozen_clock": bool(app.config["CLOCK"] or stored_clock(connection)),
            "paths": {
                "database": ".local/demo.sqlite",
                "import_folder": "fixtures/export_sample",
                "evidence_registry": "fixtures/demo_evidence.json",
                "pack_output_folder": ".local/packs",
                "cache": ".local",
                "source_provenance": "synthetic",
            },
        }
        if not replay:
            result["paths"].update(
                database=str(settings.db_path),
                import_folder=str(app.config["IMPORT_ROOT"]),
                pack_output_folder=str(settings.data_root / "packs"),
                cache=str(REPO / ".local/tectonic-cache"),
                source_provenance=app.config["SOURCE_PROVENANCE"],
                evidence_registry="demo" if app.config["DEMO"] else "public",
            )
            session.setdefault("csrf_token", secrets.token_urlsafe(32))
            result["csrf_token"] = session["csrf_token"]
        return output(result)

    @app.post("/api/settings")
    def post_settings():
        value = body()
        if set(value) != {"paused"} or type(value["paused"]) is not bool:
            abort(400, "Only the boolean Pause setting is editable in this offline build")
        set_paused(db(), value["paused"])
        return output({"paused": value["paused"]})

    def stored_clock(connection):
        row = connection.execute("SELECT value FROM settings WHERE key='demo_clock'").fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def current_time():
        clock = app.config["CLOCK"]
        return clock() if clock else stored_clock(db()) or datetime.now(UTC)

    @app.get("/api/today")
    def get_today():
        return output(today(db(), current_time()))

    @app.get("/api/agent/state")
    def get_agent_state():
        from inbound.agent import agent_state

        replay = app.config["APP_MODE"] == "replay"
        return output(agent_state(
            db(), current_time(),
            gmail=None if replay else gmail_sync.status(settings, db()),
            syncing=False if replay else gmail_sync.is_syncing(),
        ))

    @app.post("/api/test/clock")
    def set_test_clock():
        if not app.config["DEMO"] or not app.config["TEST_CLOCK"]:
            abort(404)
        value = body()
        if set(value) != {"now"}:
            abort(400)
        applied_time(value["now"])
        frozen = datetime.fromisoformat(value["now"])
        app.config["CLOCK"] = lambda: frozen
        return output({"now": frozen.isoformat()})

    @app.get("/api/messages")
    def get_messages():
        category = request.args.get("category")
        if category and category not in CATEGORIES:
            abort(400, "Unknown category")
        return output(data.messages(db(), category))

    @app.get("/api/messages/<int:mid>")
    def get_message_source(mid):
        return output(data.message_source(db(), mid))

    @app.post("/api/messages/<int:mid>/category")
    def category(mid):
        value = body()
        if set(value) != {"category"} or value["category"] not in CATEGORIES:
            abort(400, "Unknown category")
        connection = db()
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            from inbound.memory import guard as memory_guard

            memory_guard(connection)
            row = connection.execute("SELECT * FROM triage WHERE message_id=?", (mid,)).fetchone()
            if row is None:
                abort(404)
            previous = row["corrected_category"] or row["category"]
            connection.execute(
                "INSERT INTO category_history(message_id,previous_category,"
                "category,created_at) VALUES (?,?,?,?)",
                (mid, previous, value["category"], timestamp()),
            )
            connection.execute(
                "UPDATE triage SET corrected_category=?,corrected_at=? WHERE message_id=?",
                (value["category"], timestamp(), mid),
            )
            emit(connection, Kind.CORRECTED, Classification(value['category']),
                 entity_type="message", entity_id=mid)
            from inbound import learning
            from inbound.triage.normalize import normalize_subject

            mail = connection.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()
            learned = None
            if (
                learning.mailbox(mail['sender'])
                and normalize_subject(mail['subject']).strip()
                and len(mail['subject']) <= 500
            ):
                learned = learning.suggest_sender(connection, mid, value['category'],
                                                   subject=normalize_subject(mail['subject']))
        return output({"id": mid, "category": value["category"], "previous_category": previous,
                       "learning_rule": learned})

    @app.get("/api/opportunities")
    def get_opportunities():
        from inbound.extract.pipeline import opportunity_state
        from inbound.presentation import opportunity_labels

        def project(oid):
            state = opportunity_state(db(), oid, clock=current_time)
            state.update(opportunity_labels(db(), state, state["normalized_subject"]))
            state["outside_application"] = latest(db(), oid)
            return state

        return output(
            [
                project(r[0])
                for r in db().execute("SELECT id FROM opportunities ORDER BY id")
            ]
        )

    @app.get("/api/opportunities/<int:oid>")
    def get_opportunity(oid):
        return output(
            data.opportunity(
                db(),
                oid,
                clock=current_time,
                demo=app.config["DEMO"] or app.config["APP_MODE"] == "replay",
            )
        )

    @app.post("/api/opportunities/<int:oid>/applied")
    def applied(oid):
        value = body()
        required = {"applied_at", "human_submission", "expected_revision_id", "expected_activity_id"}
        if not required <= set(value) or set(value) - required - {
            "note", "follow_up", "expected_content_version"
        }:
            abort(400, "Expected revision, activity and human declaration required")
        try:
            result = record(db(), oid, **value, mode=app.config["APP_MODE"])
        except ActivityConflict as exc:
            abort(409, str(exc))
        except LookupError:
            abort(404)
        return output(result)

    def event(connection, oid, revision_id, action, *, pid=None, details=None):
        connection.execute(
            "INSERT INTO review_events(opportunity_id,revision_id,pack_id,action,"
            "created_at,details_json) VALUES (?,?,?,?,?,?)",
            (oid, revision_id, pid, action, timestamp(), json.dumps(details or {})),
        )
        kinds = {'skipped': Kind.SKIPPED, 'undo_skip': Kind.RESTORED,
                 'reviewed': Kind.REVIEWED, 'submitted_by_me': Kind.SUBMITTED,
                 'blocker_acknowledged': Kind.ACKNOWLEDGED}
        if action in kinds:
            emit(connection, kinds[action], Empty(), entity_type="opportunity", entity_id=oid,
                 revision_id=revision_id)

    def recovery_input():
        if request.mimetype == "multipart/form-data":
            value = request.form.to_dict()
            if set(request.files) != {"file"} or any(
                len(request.form.getlist(k)) != 1 for k in request.form
            ) or len(request.files.getlist("file")) != 1:
                abort(400, "Supply exactly one JD file")
            uploaded = request.files["file"]
            document = {"payload": uploaded.stream.read(10 * 1024 * 1024 + 1),
                        "filename": uploaded.filename, "mime": uploaded.mimetype}
        else:
            value = body().copy()
            if not isinstance(value.get("path"), str):
                abort(400, "Supply a path under the data root")
            document = {"path": value.pop("path")}
        for name in ("attachment_id", "expected_revision_id", "expected_content_version"):
            if name in value:
                if (type(value[name]) is not int and
                    not (isinstance(value[name], str) and value[name].isdigit())):
                    abort(400, "Preview versions must be integers")
                value[name] = int(value[name])
        return value, document

    def receipt(value, oid):
        return {k: value[k] for k in ("attachment_id", "content_hash", "original_filename", "mime",
                                     "expected_revision_id", "expected_content_version")} | {
            "opportunity_id": oid}

    @app.post("/api/opportunities/<int:oid>/attachments/preview")
    def attachment_preview(oid):
        value, document = recovery_input()
        if set(value) != {"attachment_id"}:
            abort(400, "Select one missing attachment")
        try:
            result = preview(db(), settings, oid, **value, **document, mode=app.config["APP_MODE"])
        except LookupError:
            abort(404)
        result["preview_token"] = URLSafeSerializer(
            app.secret_key, salt="attachment-preview"
        ).dumps(receipt(result, oid))
        return output(result)

    @app.post("/api/opportunities/<int:oid>/attachments/confirm")
    def attachment_confirm(oid):
        value, document = recovery_input()
        if set(value) != {"attachment_id", "content_hash", "expected_revision_id",
                          "expected_content_version", "preview_token"}:
            abort(400, "Preview hash, receipt and current call versions required")
        try:
            signed = URLSafeSerializer(app.secret_key, salt="attachment-preview").loads(
                value.pop("preview_token"))
        except (BadSignature, TypeError):
            abort(409, "Preview receipt changed; preview the file again")
        if any(signed.get(k) != v for k, v in value.items()) or signed.get("opportunity_id") != oid:
            abort(409, "Preview does not match this file and call; preview again")
        from inbound.attachment_recovery import read_document

        payload, filename, mime = read_document(settings, **document)
        if filename != signed.get("original_filename") or mime != signed.get("mime"):
            abort(409, "File differs from the preview; preview again")
        try:
            result = confirm(db(), settings, oid, **value, payload=payload, filename=filename,
                             mime=mime, mode=app.config["APP_MODE"])
        except LookupError:
            abort(404)
        return output(result)

    @app.post("/api/opportunities/<int:oid>/status")
    def opportunity_status(oid):
        return change_opportunity_status(oid, body())

    def change_opportunity_status(oid, value, *, expected_generation=None,
                                  expected_revision=None, expected_content_version=None):
        action = value.get("status")
        if action not in ("skipped", "undo_skip") or set(value) - {"status", "reason"}:
            abort(400, "Only skip and undo_skip are allowed")
        if not isinstance(value.get("reason", ""), str) or len(value.get("reason", "")) > 1000:
            abort(400)
        connection = db()
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            from inbound.memory import guard as mutation_guard

            mutation_guard(connection, expected_generation)
            row = connection.execute("SELECT * FROM opportunities WHERE id=?", (oid,)).fetchone()
            if row is None:
                abort(404)
            revision = latest_revision(connection, oid)
            if (expected_revision is not None and revision['id'] != expected_revision) or (
                expected_content_version is not None
                and row['content_version'] != expected_content_version
            ):
                abort(409, 'Call changed; ask again before skipping')
            if action == "skipped":
                if row["status"] in {"skipped", "submitted_by_me"}:
                    abort(409, "Transition unavailable")
                status = "skipped"
                details = {"previous_status": row["status"], "reason": value.get("reason", "")}
            else:
                if row["status"] != "skipped":
                    abort(409, "Opportunity is not skipped")
                previous = connection.execute(
                    "SELECT details_json,revision_id FROM review_events WHERE opportunity_id=? "
                    "AND action='skipped' ORDER BY id DESC LIMIT 1",
                    (oid,),
                ).fetchone()
                status = json.loads(previous[0])["previous_status"] if previous else "new"
                if previous and previous["revision_id"] != revision["id"]:
                    status = "needs_review"
                details = {}
            connection.execute(
                "UPDATE opportunities SET status=?,updated_at=? WHERE id=?",
                (status, timestamp(), oid),
            )
            event(connection, oid, revision["id"], action, details=details)
            from inbound.learning import skip_suggestion

            learned = skip_suggestion(connection, oid, details['reason']) if action == 'skipped' else None
        return output({"id": oid, "status": status, "learning_rule": learned})

    @app.get("/api/packs/<pid>")
    def get_pack(pid):
        return output(data.pack_detail(db(), pid, settings))

    @app.get("/api/packs/<pid>/pdf")
    def get_pdf(pid):
        path = data.artifact(data.pack_row(db(), pid), settings)
        return send_from_directory(path.parent, path.name, mimetype="application/pdf")

    @app.get("/api/packs/<pid>/preview")
    def get_preview(pid):
        import pdfplumber

        path = data.artifact(data.pack_row(db(), pid), settings)
        image = BytesIO()
        with _PREVIEW_LOCK, pdfplumber.open(path) as pdf:
            pdf.pages[0].to_image(resolution=110).original.save(image, format="PNG")
        image.seek(0)
        return send_file(image, mimetype="image/png")

    @app.post("/api/packs/<pid>/status")
    def pack_status(pid):
        value = body()
        if value.get("status") not in ("reviewed", "submitted_by_me"):
            abort(400, "Only review and human submission may be recorded")
        if set(value) - {
            "status",
            "expected_pack_id",
            "expected_revision_id",
            "expected_content_version",
            "acknowledge_blocker",
            "human_submission",
        }:
            abort(400, "Unknown review fields")
        if value.get("status") == "submitted_by_me" and value.get("human_submission") is not True:
            abort(400, "Explicit human submission declaration required")
        if "acknowledge_blocker" in value and type(value["acknowledge_blocker"]) is not bool:
            abort(400)
        connection = db()
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            check(connection)
            pack = data.pack_row(connection, pid)
            if connection.execute(
                "SELECT 1 FROM runs WHERE status='running' AND operation_key=?",
                (f"pack:{pack['opportunity_id']}",),
            ).fetchone():
                abort(409, "Pack work is still active")
            revision = latest_revision(connection, pack["opportunity_id"])
            version = connection.execute(
                "SELECT content_version FROM opportunities WHERE id=?", (pack["opportunity_id"],)
            ).fetchone()[0]
            latest_pack = connection.execute(
                "SELECT id FROM packs WHERE opportunity_id=? "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (pack["opportunity_id"],),
            ).fetchone()[0]
            if (
                value.get("expected_pack_id") != pid
                or latest_pack != pid
                or type(value.get("expected_revision_id")) is not int
                or value["expected_revision_id"] != revision["id"]
                or pack["revision_id"] != revision["id"]
                or value.get("expected_content_version", 0) != version
                or pack["content_version"] != version
            ):
                abort(
                    409,
                    "This opportunity changed while you were reviewing it. "
                    "Reload the latest revision.",
                )
            opportunity = connection.execute(
                "SELECT * FROM opportunities WHERE id=?", (pack["opportunity_id"],)
            ).fetchone()
            fields = json.loads(revision["fields_json"])
            if (
                fields["deadline"]["status"] == "conflicting"
                or not json.loads(pack["checks_json"]).get("passed")
                or pack["status"] in {"preparing", "blocked", "submitted_by_me"}
                or opportunity["status"] in {"skipped", "submitted_by_me"}
            ):
                abort(409, "Review blocked")
            acknowledge = value.get("acknowledge_blocker") is True
            if pack["provisional"] and not (pack["blocker_acknowledged"] or acknowledge):
                abort(409, "Explicit provisional blocker acknowledgement required")
            status = value["status"]
            if status == "submitted_by_me" and pack["status"] != "reviewed":
                abort(409, "Current reviewed pack required")
            if acknowledge:
                event(
                    connection,
                    pack["opportunity_id"],
                    revision["id"],
                    "blocker_acknowledged",
                    pid=pid,
                    details={"blocker": opportunity["blocked_reason"]},
                )
            connection.execute(
                "UPDATE packs SET status=?,blocker_acknowledged="
                "MAX(blocker_acknowledged,?) WHERE id=?",
                (status, int(acknowledge), pid),
            )
            connection.execute(
                "UPDATE opportunities SET status=?,updated_at=? WHERE id=?",
                (status, timestamp(), pack["opportunity_id"]),
            )
            event(
                connection,
                pack["opportunity_id"],
                revision["id"],
                status,
                pid=pid,
                details={"human_submission": status == "submitted_by_me"},
            )
        return output({"id": pid, "status": status})

    def launch(kind, oid=None):
        run_id = start_run(
            db(),
            kind,
            opportunity_id=oid,
            source_type=app.config["SOURCE_FORMAT"] if kind == "import" else None,
            source_provenance=app.config["SOURCE_PROVENANCE"] if kind == "import" else None,
        )
        frozen = current_time() if (app.config["CLOCK"] or stored_clock(db())) else None
        options = {
            "root": app.config["IMPORT_ROOT"],
            "source": app.config["SOURCE_FORMAT"],
            "provenance": app.config["SOURCE_PROVENANCE"],
            "opportunity_id": oid,
            "demo": app.config["DEMO"],
            "clock": (lambda: frozen) if frozen else None,
        }
        if app.config["ASYNC_WORK"]:
            app.extensions["work_executor"].submit(execute, settings, run_id, kind, **options)
        else:
            execute(settings, run_id, kind, **options)
        return output({"run_id": run_id}, 202)

    @app.post("/api/import")
    def import_messages():
        if body():
            abort(400, "Import source is configured locally and is read-only")
        return launch("import")

    @app.post("/api/opportunities/<int:oid>/pack")
    def build_pack(oid):
        if body():
            abort(400)
        if not db().execute("SELECT 1 FROM opportunities WHERE id=?", (oid,)).fetchone():
            abort(404)
        revision = latest_revision(db(), oid)
        if (
            not db()
            .execute("SELECT 1 FROM roles WHERE revision_id=?", (revision["id"],))
            .fetchone()
        ):
            abort(409, "Role unknown — no recommended-role pack can be built")
        return launch("pack", oid)

    @app.get("/api/runs")
    def get_runs():
        return output(data.runs(db()))

    @app.get("/api/version")
    def version():
        """A cheap token that changes whenever anything the desk shows changes."""
        connection = db()
        parts = [
            # Domain mutations include evidence and, in their future migrations, memories
            # and rules. Journal-only writes still refresh progress via the journal cursor.
            connection.execute("SELECT generation FROM domain_generation WHERE id=1").fetchone()[0],
            connection.execute("SELECT error FROM memory_scan_state WHERE id=1").fetchone()[0],
            connection.execute("SELECT COALESCE(MAX(id),0) FROM agent_steps").fetchone()[0]
            if app.config['APP_MODE'] != 'replay' else connection.execute(
                "SELECT COALESCE(MAX(id),0) FROM agent_steps WHERE source='synthetic'"
            ).fetchone()[0],
            tuple(connection.execute(
                "SELECT (SELECT COALESCE(MAX(version),0) FROM snapshots),"
                "(SELECT COUNT(*) FROM messages),"
                "(SELECT COALESCE(MAX(id),0) FROM review_events),"
                "(SELECT COUNT(*) FROM category_history),"
                "(SELECT COUNT(*)||':'||COALESCE(MAX(id),'') FROM packs),"
                "(SELECT GROUP_CONCAT(status,'') FROM packs),"
                "(SELECT COALESCE(MAX(id),0)||':'||COUNT(finished_at)||':'||"
                "COALESCE(GROUP_CONCAT(stage,''),'') FROM runs WHERE status='running'"
                " OR id=(SELECT MAX(id) FROM runs)),"
                "(SELECT GROUP_CONCAT(scope||length(metadata_json),'') FROM evidence_snapshots),"
                "(SELECT COUNT(*) FROM evidence_bullets),"
                "(SELECT COALESCE(SUM(content_version),0) FROM opportunities),"
                "(SELECT value FROM settings WHERE key='paused')"
            ).fetchone()),
        ]
        if app.config["APP_MODE"] != "replay":
            parts.append(gmail_sync.status(settings, connection).get("last_sync_at"))
        token = hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:16]
        return output({"version": token})

    @app.post('/api/agent/alerts')
    def record_alert():
        value = body()
        task_alert = 'task_id' in value
        identity_key = 'task_id' if task_alert else 'opportunity_id'
        if set(value) != {identity_key, 'kind', 'alert_type', 'reason'}:
            abort(400)
        kind = {'eligible': Kind.ALERT_ELIGIBLE, 'requested': Kind.ALERT_REQUESTED,
                'suppressed': Kind.ALERT_SUPPRESSED}.get(value['kind'])
        oid = value[identity_key]
        table = 'tasks' if task_alert else 'opportunities'
        if kind is None or type(oid) is not int or not db().execute(
            f'SELECT 1 FROM {table} WHERE id=?', (oid,)
        ).fetchone():
            abort(400)
        if task_alert != (value['alert_type'] == 'task_deadline'):
            abort(400)
        with db():
            emit(db(), kind, Alert(value['alert_type'], value['reason']),
                 entity_type='task' if task_alert else 'opportunity', entity_id=oid)
        return output({'recorded': True})

    @app.get("/api/gmail")
    def gmail_status():
        if app.config["APP_MODE"] == "replay":
            return output({"connected": False, "read_only": True, "available": False})
        return output({**gmail_sync.status(settings, db()), "available": True})

    @app.post("/api/gmail/sync")
    def gmail_sync_now():
        if body():
            abort(400)
        return run_gmail_check()

    def run_gmail_check():
        if not gmail_sync.connected(settings):
            abort(409, "Gmail is not connected")
        try:
            result = gmail_sync.sync(settings, transport=app.config.get("GMAIL_TRANSPORT"))
        except PausedError:
            abort(423, "Inbound is paused")
        except (GmailError, OSError, ValueError, KeyError) as exc:
            abort(502, f"Gmail sync failed ({type(exc).__name__})")
        return output({**gmail_sync.status(settings, db()), "result": result})

    @app.post("/api/gmail/poll")
    def gmail_poll():
        value = body()
        if set(value) != {"enabled", "minutes"}:
            abort(400, "enabled and minutes required")
        try:
            gmail_sync.set_poll(db(), enabled=value["enabled"], minutes=value["minutes"])
        except ValueError as exc:
            abort(400, str(exc))
        return output(gmail_sync.status(settings, db()))

    @app.get("/")
    @app.get("/<path:path>")
    def spa(path=""):
        if path == "api" or path.startswith("api/"):
            abort(404)
        directory = Path(app.config["WEB_DIST"]).resolve()
        target = (directory / path).resolve()
        if not target.is_relative_to(directory):
            abort(404)
        return send_from_directory(directory, path if path and target.is_file() else "index.html")

    from inbound.api.scout import register as register_scout

    register_scout(app, db, output, settings, current_time, change_opportunity_status, run_gmail_check)

    from inbound.api.tasks import register as register_tasks

    register_tasks(app, db, output, current_time)
    return app
