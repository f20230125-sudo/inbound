"""Explicit, bounded recovery against one fictional call; no filename auto-linking."""

import io
import json
import zipfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from inbound.__main__ import main
from inbound.api import create_app
from inbound.db import connect, import_messages
from inbound.evidence.registry import import_evidence
from inbound.extract.attachments import DOCX
from inbound.extract.pipeline import extract_messages
from inbound.models import Attachment
from inbound.packs.build import create_pack, set_status
from inbound.pause import set_paused
from inbound.settings import Settings
from inbound.triage.rules import triage_messages
from inbound.work import execute, start_run
from tests.test_m6_polish import NOW, fictional_call, prepare

FILES = Path("fixtures/export_sample/attachments")


@pytest.fixture
def desk(tmp_path):
    settings = Settings(data_root=tmp_path)
    message = replace(fictional_call(), subject=fictional_call().subject + " - Backend Intern",
                      body_text="Job Title & JD\nAttached\n",
                      attachments=(Attachment("JD.pdf", "application/pdf"),))
    with connect(settings.db_path) as db:
        oid = prepare(db, message)
        import_evidence(db, demo=True)
    app = create_app({"TESTING": True, "SETTINGS": settings, "ASYNC_WORK": False, "DEMO": True})
    with app.test_client() as client:
        token = client.get("/api/settings").json["csrf_token"]
        yield app, client, oid, {"X-CSRF-Token": token}, message


def detail(desk):
    return desk[1].get(f"/api/opportunities/{desk[2]}").json


def upload(desk, *, action="preview", preview=None, data=None, filename="supplied.pdf",
           mime="application/pdf", **changes):
    _, client, oid, headers, _ = desk
    fields = {"attachment_id": str(detail(desk)["attachments"][0]["id"])}
    if preview:
        fields.update({k: str(preview[k]) for k in (
            "content_hash", "expected_revision_id", "expected_content_version", "preview_token")})
    fields.update(changes)
    fields["file"] = (io.BytesIO(data if data is not None else
                                (FILES / "jd-P-D15.pdf").read_bytes()), filename, mime)
    return client.post(f"/api/opportunities/{oid}/attachments/{action}",
                       data=fields, headers=headers)


@pytest.mark.parametrize("filename,mime,fixture,location", [
    ("supplied.pdf", "application/pdf", "jd-P-D15.pdf", "pdf_page"),
    ("supplied.docx", DOCX, "jd-P-D19.docx", "docx_paragraph"),
])
def test_preview_no_writes_confirm_recovers_traced_one_page_pack(desk, filename, mime,
                                                               fixture, location):
    app, _, oid, _, _ = desk
    before = detail(desk)
    data = (FILES / fixture).read_bytes()
    response = upload(desk, filename=filename, mime=mime, data=data)
    assert response.status_code == 200
    preview = response.json
    assert preview["text"] and preview["roles"] and preview["roles"][0]["requirements"]
    assert detail(desk) == before
    assert not (app.config["SETTINGS"].data_root / "recovered").exists()
    confirmed = upload(desk, action="confirm", preview=preview, filename=filename,
                       mime=mime, data=data)
    assert confirmed.status_code == 200
    op = detail(desk)
    assert not op["blocked_reason"] and op["content_version"] == 1
    assert op["revision_id"] == before["revision_id"]
    assert op["roles"][0]["requirements"] and op["roles"][0]["coverage"]
    assert any(item["kind"] == location for item in op["attachments"][0]["locations"])
    recovery = op["attachment_recoveries"][0]
    assert recovery["supplier"] == "uzair" and recovery["recorded_at"]
    assert recovery["sha256"] == preview["content_hash"]
    assert recovery["original_filename"] == filename
    with connect(app.config["SETTINGS"].db_path) as db:
        history = db.execute("SELECT * FROM attachment_recoveries").fetchone()
        assert json.loads(history["previous_state_json"])["extraction"]["fields_json"]
        stored = (app.config["SETTINGS"].data_root / history["stored_path"]).resolve()
        assert stored.read_bytes() == data
        pack = create_pack(db, oid, demo=True, settings=app.config["SETTINGS"])
        assert pack["checks"]["passed"] and pack["checks"]["pages"] == 1
        assert pack["checks"]["traced_bullets"] == pack["checks"]["bullet_count"] > 0
        assert all(pack["checks"]["bullet_trace"].values())
        assert pack["checks"]["approved_skills"]
    again = upload(desk, action="confirm", preview=preview, filename=filename, mime=mime, data=data)
    assert again.status_code == 200 and again.json == confirmed.json
    assert len(detail(desk)["attachment_recoveries"]) == 1


def test_unreadable_confirm_retains_blocker_and_reason(desk):
    preview = upload(desk, data=b"%PDF-1.7\nnot a document").json
    assert preview["parse_status"] == "unreadable"
    result = upload(desk, action="confirm", preview=preview, data=b"%PDF-1.7\nnot a document")
    assert result.status_code == 200 and result.json["parse_status"] == "unreadable"
    assert "Document could not be parsed" in detail(desk)["blocked_reason"]
    assert detail(desk)["attachments"][0]["parse_status"] == "unreadable"


@pytest.mark.parametrize("change", ["hash", "revision", "version", "bytes", "receipt"])
def test_stale_confirm_rejected(desk, change):
    preview = upload(desk).json
    kwargs = {}
    if change == "hash":
        preview["content_hash"] = "0" * 64
    elif change == "bytes":
        kwargs["data"] = (FILES / "jd-P-H22.pdf").read_bytes()
    elif change == "receipt":
        preview["preview_token"] += "changed"
    elif change == "revision":
        message = replace(desk[4], provider_id="reminder", sent_at=NOW + timedelta(hours=1))
        with connect(desk[0].config["SETTINGS"].db_path) as db:
            import_messages(db, [message])
            triage_messages(db)
            extract_messages(db)
    else:
        with connect(desk[0].config["SETTINGS"].db_path) as db:
            db.execute("UPDATE opportunities SET content_version=content_version+1")
    assert upload(desk, action="confirm", preview=preview, **kwargs).status_code == 409
    assert detail(desk)["blocked_reason"]


@pytest.mark.parametrize("filename,mime,data,status", [
    ("a.pdf", "application/pdf", b"x" * (10 * 1024 * 1024 + 1), 413),
    ("a.pdf", "application/pdf", b"PK\x03\x04fake", 400),
    ("a.pdf", DOCX, b"%PDF-1.7\n", 400),
    ("a.exe", "application/pdf", b"%PDF-1.7\n", 400),
    ("../a.pdf", "application/pdf", b"%PDF-1.7\n", 400),
])
def test_upload_bounds_mime_and_magic(desk, filename, mime, data, status):
    assert upload(desk, filename=filename, mime=mime, data=data).status_code == status
    assert detail(desk)["blocked_reason"]


@pytest.mark.parametrize("kind", ["size", "entries"])
def test_docx_zip_caps(desk, kind):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if kind == "size":
            archive.writestr("word/document.xml", b"x" * (50 * 1024 * 1024 + 1))
        else:
            for i in range(2001):
                archive.writestr(f"word/{i}.xml", "x")
    response = upload(desk, data=stream.getvalue(), filename="bomb.docx", mime=DOCX)
    assert response.status_code == 200
    assert response.json["parse_status"] == "unreadable"
    assert response.json["reason"] == "DOCX zip cap exceeded"


def test_path_confined_and_cli_preview_then_confirm(desk, tmp_path, monkeypatch, capsys):
    app, client, oid, headers, _ = desk
    settings = app.config["SETTINGS"]
    aid = detail(desk)["attachments"][0]["id"]
    outside = tmp_path.parent / "outside.pdf"
    # Reject before reading: an outside path need not exist.
    url = f"/api/opportunities/{oid}/attachments/preview"
    assert client.post(url, headers=headers,
                       json={"attachment_id": aid, "path": str(outside)}).status_code == 400
    path = tmp_path / "local.pdf"
    path.write_bytes((FILES / "jd-P-D15.pdf").read_bytes())
    assert client.post(url, headers=headers,
                       json={"attachment_id": aid, "path": str(path)}).status_code == 200
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings))
    args = ["attach", str(oid), "--attachment", "JD.pdf", "--file", str(path)]
    assert main([*args, "--preview"]) == 0
    assert json.loads(capsys.readouterr().out)["text"]
    assert detail(desk)["blocked_reason"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["parse_status"] == "parsed"
    assert not detail(desk)["blocked_reason"]


@pytest.mark.parametrize("guard", ["csrf", "host", "pause", "replay", "import", "pack"])
def test_guards_apply_to_both_steps(desk, guard):
    app, client, oid, headers, _ = desk
    preview = upload(desk).json
    expected = 409
    if guard == "csrf":
        headers.clear()
        expected = 403
    elif guard == "host":
        headers["Host"] = "evil.invalid"
        expected = 403
    elif guard == "replay":
        app.config["APP_MODE"] = "replay"
        expected = 405
    else:
        with connect(app.config["SETTINGS"].db_path) as db:
            if guard == "pause":
                set_paused(db, True)
            else:
                start_run(db, guard, opportunity_id=oid)
    # Avoid detail() after changing Host/replay: upload helper uses a GET for the row id.
    for action in ("preview", "confirm"):
        form = {"attachment_id": "1", "file": (io.BytesIO((FILES / "jd-P-D15.pdf").read_bytes()),
                                                 "a.pdf", "application/pdf")}
        if action == "confirm":
            form.update({k: str(preview[k]) for k in (
                "content_hash", "expected_revision_id", "expected_content_version", "preview_token")})
        assert client.post(f"/api/opportunities/{oid}/attachments/{action}",
                           data=form, headers=headers).status_code == expected


def test_explicit_association_and_exact_message_only(desk):
    app, _, oid, _, message = desk
    with connect(app.config["SETTINGS"].db_path) as db:
        second = replace(message, provider_id="second", thread_id="second",
                         subject="Call for CV - Another Fictional,DSO - Backend Intern")
        import_messages(db, [second])
        triage_messages(db)
        extract_messages(db)
        other = db.execute("SELECT * FROM message_extractions WHERE message_id=2").fetchone()
        canonical = db.execute("SELECT content_hash FROM messages WHERE id=1").fetchone()[0]
    preview = upload(desk).json
    assert upload(desk, action="confirm", preview=preview).status_code == 200
    with connect(app.config["SETTINGS"].db_path) as db:
        assert dict(db.execute("SELECT * FROM message_extractions WHERE message_id=2").fetchone()
                    ) == dict(other)
        assert db.execute("SELECT content_hash FROM messages WHERE id=1").fetchone()[0] == canonical
        assert db.execute("SELECT blocked_reason FROM opportunities WHERE id<>?", (oid,)
                          ).fetchone()[0]
    # The identical file needs its own preview and explicit confirmation on the other call.
    other_id = desk[1].get("/api/opportunities").json[-1]["id"]
    assert other_id != oid
    other_desk = (app, desk[1], other_id, desk[3], second)
    second_preview = upload(other_desk).json
    assert upload(other_desk, action="confirm", preview=preview).status_code == 409
    assert upload(other_desk, action="confirm", preview=second_preview).status_code == 200
    assert not detail(other_desk)["blocked_reason"]


def test_symlink_resolution_rejects_outside_data_root(desk, tmp_path):
    import _winapi

    root = desk[0].config["SETTINGS"].data_root
    outside = tmp_path.parent / f"outside-{tmp_path.name}"
    outside.mkdir()
    (outside / "jd.pdf").write_bytes((FILES / "jd-P-D15.pdf").read_bytes())
    # Directory junctions resolve like symlinks, and do not need Windows symlink privileges.
    _winapi.CreateJunction(str(outside), str(root / "linked"))
    result = desk[1].post(f"/api/opportunities/{desk[2]}/attachments/preview", headers=desk[3],
                          json={"attachment_id": 1, "path": str(root / "linked/jd.pdf")})
    assert result.status_code == 400


def test_later_revision_inherits_recovered_requirements_and_retains_deadline(desk):
    app, _, _oid, _, message = desk
    with connect(app.config["SETTINGS"].db_path) as db:
        reminder = replace(message, provider_id="later", sent_at=NOW + timedelta(hours=1),
                           body_text="Deadline extended to 29 October 2026, 08:00AM",
                           attachments=())
        import_messages(db, [reminder])
        triage_messages(db)
        extract_messages(db)
    before = detail(desk)
    preview = upload(desk).json
    assert upload(desk, action="confirm", preview=preview).status_code == 200
    after = detail(desk)
    assert after["revision_id"] == before["revision_id"]
    assert after["fields"]["deadline"] == before["fields"]["deadline"]
    assert after["roles"][0]["requirements"]
    assert after["roles"][0]["requirements"][0]["provenance"]["message_id"] == message.provider_id


def test_success_after_unreadable_attempt_and_stale_outside_application(desk):
    data = b"%PDF-1.7\nunreadable"
    preview = upload(desk, data=data).json
    assert upload(desk, action="confirm", preview=preview, data=data).status_code == 200
    preview = upload(desk).json
    assert upload(desk, action="confirm", preview=preview).status_code == 200
    after = detail(desk)
    assert after["content_version"] == 2 and not after["blocked_reason"]
    assert len(after["attachment_recoveries"]) == 2
    body = {"applied_at": NOW.isoformat(), "human_submission": True,
            "expected_revision_id": after["revision_id"], "expected_activity_id": None}
    url = f"/api/opportunities/{desk[2]}/applied"
    assert desk[1].post(url, headers=desk[3], json=body).status_code == 409
    assert desk[1].post(url, headers=desk[3],
                        json=body | {"expected_content_version": 2}).status_code == 200


@pytest.mark.parametrize("status", ["reviewed", "submitted_by_me", "skipped"])
def test_pack_review_invalidated_and_human_history_survives_reimport(desk, status):
    app, client, oid, headers, _ = desk
    settings = app.config["SETTINGS"]
    with connect(settings.db_path) as db:
        pack = create_pack(db, oid, demo=True, settings=settings)
        set_status(db, pack["id"], "reviewed", acknowledge_blocker=True)
        if status != "reviewed":
            set_status(db, pack["id"], status)
    op = detail(desk)
    assert client.post(f"/api/opportunities/{oid}/applied", headers=headers, json={
        "applied_at": NOW.isoformat(), "human_submission": True,
        "expected_revision_id": op["revision_id"], "expected_activity_id": None,
    }).status_code == 200
    with connect(settings.db_path) as db:
        db.execute("INSERT INTO review_events(opportunity_id,revision_id,pack_id,action,"
                   "created_at,details_json) VALUES (?,?,?,?,?,?)",
                   (oid, op["revision_id"], pack["id"], status, NOW.isoformat(), '{}'))
    before_history = detail(desk)["review_history"]
    preview = upload(desk).json
    assert upload(desk, action="confirm", preview=preview).status_code == 200
    after = detail(desk)
    assert after["review_history"][:len(before_history)] == before_history
    assert after["outside_application"] == detail(desk)["outside_application"]
    if status == "reviewed":
        assert after["packs"][0]["status"] == "needs_review"
        assert after["status"] == "needs_review"
    else:
        assert after["status"] == status
    assert client.post(f"/api/packs/{pack['id']}/status", headers=headers, json={
        "status": "reviewed", "expected_pack_id": pack["id"],
        "expected_revision_id": after["revision_id"], "expected_content_version": 1,
        "acknowledge_blocker": True,
    }).status_code == 409
    with connect(settings.db_path) as db:
        with pytest.raises(ValueError, match="stale"):
            set_status(db, pack["id"], "reviewed", acknowledge_blocker=True)
        rid = start_run(db, "import")
        execute(settings, rid, "import", root=Path("fixtures/export_sample"), provenance="synthetic")
        assert db.execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()[0] == "success"
    final = detail(desk)
    assert final["review_history"] == after["review_history"]
    assert final["attachment_recoveries"] == after["attachment_recoveries"]
    assert final["content_version"] == after["content_version"]
