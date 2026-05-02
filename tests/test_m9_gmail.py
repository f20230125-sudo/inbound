"""Live Gmail sync against a fake Gmail (httpx.MockTransport): no socket is ever opened."""

import base64
import json
from contextlib import closing
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from inbound import gmail_sync
from inbound.api import create_app
from inbound.db import connect, import_messages
from inbound.pause import PausedError, set_paused
from inbound.settings import Settings
from inbound.sources import gmail_api
from inbound.sources.gmail_api import SCOPE, GmailClient, GmailError

JD = Path("fixtures/export_sample/attachments/jd-P-D15.pdf")


def raw_call(gid, *, attach=True, sent=datetime(2026, 10, 27, 6, tzinfo=UTC)):
    mail = EmailMessage()
    mail["From"] = "ps@dubai.bits-pilani.ac.in"
    mail["To"] = "ps@dubai.bits-pilani.ac.in"
    mail["Subject"] = f"Call for CV - PS II – Second Semester 2026-2027 – Harbor Finch {gid},Port Selene"
    mail["Date"] = format_datetime(sent)
    mail["Message-ID"] = f"<{gid}@mail.demo.invalid>"
    mail.set_content(
        f"Harbor Finch {gid} has expressed their interest to hire Students for PS II.\n"
        f"*https://forms.gle/SYNTHETIC-{gid} <https://forms.gle/SYNTHETIC-{gid}>*\n"
        "*Stipend*\n· AED 2,000 per month\n*Mode of Internship:* In person\n"
        "*Job Title & JD*\n· Attached\n"
        "*CV Submission Deadline**: **: 08**:00AM , 29 October 2026*\n"
    )
    if attach:
        mail.add_attachment(JD.read_bytes(), maintype="application", subtype="pdf",
                            filename="JD.pdf")
    return mail.as_bytes()


class FakeGmail:
    def __init__(self):
        self.messages, self.history_id, self.added = {}, 100, []
        self.calls, self.token_scope, self.history_gone = [], SCOPE, False

    def add(self, gid, data):
        self.history_id += 1
        self.messages[gid] = data
        self.added.append((self.history_id, gid))

    def handler(self, request):
        self.calls.append((request.method, request.url.host, request.url.path))
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fake", "expires_in": 3600,
                                             "scope": self.token_scope})
        assert request.headers["Authorization"] == "Bearer fake"
        path = request.url.path.removeprefix("/gmail/v1/users/me/")
        if path == "profile":
            return httpx.Response(200, json={"emailAddress": "student@demo.invalid",
                                             "historyId": str(self.history_id)})
        if path == "messages":
            return httpx.Response(200, json={"messages": [{"id": g} for g in self.messages]})
        if path == "history":
            if self.history_gone:
                return httpx.Response(404, json={})
            start = int(request.url.params["startHistoryId"])
            items = [{"messagesAdded": [{"message": {"id": g}}]}
                     for h, g in self.added if h > start]
            return httpx.Response(200, json={"history": items})
        if path.startswith("messages/"):
            gid = path.split("/", 1)[1]
            raw = base64.urlsafe_b64encode(self.messages[gid]).decode().rstrip("=")
            return httpx.Response(200, json={"id": gid, "threadId": f"t-{gid}", "raw": raw,
                                             "labelIds": ["INBOX"], "historyId": "1"})
        return httpx.Response(404)

    def transport(self):
        return httpx.MockTransport(self.handler)


@pytest.fixture
def live(tmp_path):
    settings = Settings(data_root=tmp_path)
    gmail_api.write_json(gmail_api.token_path(settings), {
        "client_id": "id", "client_secret": "secret", "refresh_token": "refresh",
        "email": "student@demo.invalid",
    })
    fake = FakeGmail()
    fake.add("g1", raw_call("g1"))
    return settings, fake


def counts(settings):
    with closing(connect(settings.db_path)) as db:
        messages = db.execute(
            "SELECT provider,provider_id,source FROM messages ORDER BY provider_id"
        ).fetchall()
        attachments = db.execute("SELECT bytes_available,parse_status FROM attachments").fetchall()
        opportunities = db.execute("SELECT status,blocked_reason FROM opportunities").fetchall()
    return [tuple(m) for m in messages], [tuple(a) for a in attachments], opportunities


def test_first_sync_fetches_imports_and_unblocks_attached_jd(live):
    settings, fake = live
    result = gmail_sync.sync(settings, transport=fake.transport())
    assert result["fetched"] == 1 and result["status"] == "success"
    messages, attachments, opportunities = counts(settings)
    assert messages == [("mail", "g1", "private")]
    assert attachments == [(1, "parsed")]
    assert len(opportunities) == 1 and opportunities[0]["blocked_reason"] is None
    assert {(m, h) for m, h, _ in fake.calls} <= {
        ("POST", "oauth2.googleapis.com"), ("GET", "gmail.googleapis.com")}


def test_later_syncs_use_history_and_only_new_mail(live):
    settings, fake = live
    gmail_sync.sync(settings, transport=fake.transport())
    again = gmail_sync.sync(settings, transport=fake.transport())
    assert again["fetched"] == 0 and "status" not in again  # nothing new: no import run
    fake.add("g2", raw_call("g2", attach=False))
    newer = gmail_sync.sync(settings, transport=fake.transport())
    assert newer["fetched"] == 1
    assert [m[1] for m in counts(settings)[0]] == ["g1", "g2"]
    assert any(p.endswith("/history") for _, _, p in fake.calls)


def test_expired_history_falls_back_to_listing(live):
    settings, fake = live
    gmail_sync.sync(settings, transport=fake.transport())
    fake.history_gone = True
    fake.add("g3", raw_call("g3", attach=False))
    assert gmail_sync.sync(settings, transport=fake.transport())["fetched"] == 1


def test_pause_blocks_sync_before_any_request(live):
    settings, fake = live
    with closing(connect(settings.db_path)) as db:
        set_paused(db, True)
    with pytest.raises(PausedError):
        gmail_sync.sync(settings, transport=fake.transport())
    assert fake.calls == []


def test_export_copy_of_the_same_gmail_id_is_not_duplicated(live):
    settings, fake = live
    first = gmail_sync.sync(settings, transport=fake.transport())
    assert first["imported"] == 1
    with closing(connect(settings.db_path)) as db:
        row = db.execute("SELECT provider,provider_id FROM messages").fetchone()
        assert tuple(row) == ("mail", "g1")  # same identity space as Uzair's text export
        message = next(gmail_api.load(gmail_sync.mail_dir(settings), "private"))
        assert import_messages(db, [message])["imported"] == 0


def test_client_refuses_other_hosts_methods_and_scopes(live):
    settings, fake = live
    client = GmailClient(gmail_api.read_json(gmail_api.token_path(settings)),
                         transport=fake.transport())
    with pytest.raises(GmailError):
        client._send("GET", "https://example.invalid/x")
    with pytest.raises(GmailError):
        client._send("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
    with pytest.raises(GmailError):
        client._send("GET", "http://gmail.googleapis.com/gmail/v1/users/me/profile")
    fake.token_scope = "https://www.googleapis.com/auth/gmail.modify"
    with pytest.raises(GmailError):
        client.profile()


def test_consent_url_asks_only_for_read_only_with_pkce():
    url = gmail_api.consent_url("id", "http://127.0.0.1:5555/", "state", "v" * 64)
    query = httpx.URL(url).params
    assert query["scope"] == SCOPE
    assert query["code_challenge_method"] == "S256"
    assert query["redirect_uri"].startswith("http://127.0.0.1:")


def test_client_secret_must_live_under_the_private_data_root(tmp_path):
    settings = Settings(data_root=tmp_path / "data")
    outside = tmp_path / "client.json"
    outside.write_text(json.dumps({"installed": {"client_id": "a", "client_secret": "b"}}))
    with pytest.raises(GmailError):
        gmail_api.load_client_secret(outside, settings)


def test_poller_runs_only_when_connected_enabled_and_not_paused(live):
    settings, _ = live
    poller = gmail_sync.Poller(settings)
    assert poller.due() is False  # polling is off until Uzair turns it on
    with closing(connect(settings.db_path)) as db:
        gmail_sync.set_poll(db, enabled=True, minutes=2)
    assert poller.due() is True
    with closing(connect(settings.db_path)) as db:
        set_paused(db, True)
    assert poller.due() is False
    with pytest.raises(ValueError), closing(connect(settings.db_path)) as db:
        gmail_sync.set_poll(db, enabled=True, minutes=0)


def post(client, url, body=None):
    token = client.get("/api/settings").json["csrf_token"]
    return client.post(url, json=body or {}, headers={"X-CSRF-Token": token})


def test_api_status_sync_and_poll(live):
    settings, fake = live
    app = create_app({"TESTING": True, "ASYNC_WORK": False, "SETTINGS": settings,
                      "SOURCE_PROVENANCE": "private", "DEMO": False,
                      "GMAIL_TRANSPORT": fake.transport()})
    client = app.test_client()
    status = client.get("/api/gmail").json
    assert status["connected"] and status["read_only"] and not status["poll_enabled"]
    assert client.post("/api/gmail/poll", json={"enabled": True, "minutes": 2}).status_code == 403
    assert post(client, "/api/gmail/poll", {"enabled": True, "minutes": 2}).json["poll_enabled"]
    synced = post(client, "/api/gmail/sync")
    assert synced.status_code == 200 and synced.json["result"]["fetched"] == 1
    gmail_api.disconnect(settings)
    assert post(client, "/api/gmail/sync").status_code == 409


def test_replay_mode_exposes_no_gmail(live):
    settings, _ = live
    app = create_app({"TESTING": True, "APP_MODE": "replay", "SETTINGS": settings})
    assert app.test_client().get("/api/gmail").json == {
        "connected": False, "read_only": True, "available": False}


def test_spam_trash_drafts_and_own_sent_mail_are_not_saved(live):
    settings, fake = live
    original = fake.handler

    def labelled(request):
        response = original(request)
        path = request.url.path
        if path.endswith("/messages/g1"):
            data = response.json()
            data["labelIds"] = ["SPAM"]
            return httpx.Response(200, json=data)
        return response

    fake.handler = labelled
    result = gmail_sync.sync(settings, transport=httpx.MockTransport(labelled))
    assert result["fetched"] == 0
    assert counts(settings)[0] == []


def test_one_unparseable_message_does_not_block_later_mail(live):
    settings, fake = live
    fake.add("bad", b"Subject: no date or sender\n\nbody")
    fake.add("g2", raw_call("g2", attach=False))
    result = gmail_sync.sync(settings, transport=fake.transport())
    assert result["status"] == "success"
    assert [m[1] for m in counts(settings)[0]] == ["g1", "g2"]


def test_poller_survives_any_sync_failure(live, monkeypatch):
    settings, _ = live
    with closing(connect(settings.db_path)) as db:
        gmail_sync.set_poll(db, enabled=True, minutes=2)

    def broken(*args, **kwargs):
        raise KeyError("boom")

    monkeypatch.setattr(gmail_sync, "sync", broken)
    seen = []
    assert gmail_sync.Poller(settings, on_result=seen.append).tick() == {"error": "KeyError"}
    assert seen == [{"error": "KeyError"}]


def test_version_token_moves_only_when_something_changes(tmp_path):
    settings = Settings(data_root=tmp_path)
    app = create_app({"TESTING": True, "ASYNC_WORK": False, "SETTINGS": settings,
                      "SOURCE_PROVENANCE": "synthetic", "DEMO": True})
    client = app.test_client()
    first = client.get("/api/version").json["version"]
    assert client.get("/api/version").json["version"] == first
    assert post(client, "/api/settings", {"paused": True}).status_code == 200
    paused = client.get("/api/version").json["version"]
    assert paused != first
    assert post(client, "/api/settings", {"paused": False}).status_code == 200
    assert client.get("/api/version").json["version"] != paused
    assert post(client, "/api/import").status_code == 202
    assert client.get("/api/version").json["version"] not in {first, paused}


def test_new_buildable_call_gets_one_draft_pack_automatically(live):
    from inbound.evidence.registry import store_registry

    settings, fake = live
    first = gmail_sync.sync(settings, transport=fake.transport())
    assert first["auto_packs"] == 0  # no evidence registry on this desk yet: nothing built
    with closing(connect(settings.db_path)) as db:
        store_registry(db, json.loads(Path("fixtures/evidence_snapshot.json").read_text("utf8")))
    assert gmail_sync.auto_packs(settings) == 1
    assert gmail_sync.auto_packs(settings) == 0  # one draft per revision, not one per check
    with closing(connect(settings.db_path)) as db:
        pack = db.execute("SELECT status,demo FROM packs").fetchone()
    assert tuple(pack) == ("needs_review", 0)  # a draft for review, never marked reviewed


# Review r7 fixes (Codex review of Claude's M9/M9b, 28 Oct).

def test_history_is_read_completely_so_the_cursor_never_skips_mail(live):
    settings, fake = live
    gmail_sync.sync(settings, transport=fake.transport())
    for n in range(5):
        fake.add(f"h{n}", raw_call(f"h{n}", attach=False))
    original = fake.handler

    def paged(request):
        if request.url.path.endswith("/history") and "pageToken" not in request.url.params:
            response = original(request).json()
            items = response["history"]
            return httpx.Response(200, json={"history": items[:2], "nextPageToken": "p2"})
        if request.url.path.endswith("/history"):
            response = original(request).json()
            return httpx.Response(200, json={"history": response["history"][2:]})
        return original(request)

    result = gmail_sync.sync(settings, transport=httpx.MockTransport(paged))
    assert result["fetched"] == 5


def test_saved_but_unimported_mail_is_imported_on_the_next_check(live):
    settings, fake = live
    client = GmailClient(gmail_api.read_json(gmail_api.token_path(settings)),
                         transport=fake.transport())
    gmail_sync.fetch_new(settings, client)  # downloaded, then "crashed" before import
    assert gmail_sync.unimported(settings) == {"g1"}
    result = gmail_sync.sync(settings, transport=fake.transport())
    assert result["fetched"] == 0 and result["imported"] == 1
    assert gmail_sync.unimported(settings) == set()


def test_pause_during_a_fetch_stops_it_and_keeps_the_cursor(live):
    settings, fake = live
    for n in range(3):
        fake.add(f"p{n}", raw_call(f"p{n}", attach=False))
    original = fake.handler
    calls = {"raw": 0}

    def pausing(request):
        if "/messages/" in request.url.path:
            calls["raw"] += 1
            if calls["raw"] == 2:
                with closing(connect(settings.db_path)) as db:
                    set_paused(db, True)
        return original(request)

    with pytest.raises(PausedError):
        gmail_sync.sync(settings, transport=httpx.MockTransport(pausing))
    assert calls["raw"] == 2
    assert (gmail_api.read_json(gmail_sync.state_path(settings)) or {}).get("history_id") is None


def test_refresh_rejects_a_scope_broader_than_read_only(live):
    settings, fake = live
    fake.token_scope = f"{SCOPE} https://www.googleapis.com/auth/gmail.modify"
    client = GmailClient(gmail_api.read_json(gmail_api.token_path(settings)),
                         transport=fake.transport())
    with pytest.raises(GmailError):
        client.profile()


def test_rate_limit_403_is_retried(live, monkeypatch):
    settings, fake = live
    monkeypatch.setattr(gmail_api.time, "sleep", lambda seconds: None)
    original = fake.handler
    state = {"limited": 2}

    def throttled(request):
        if "/messages/" in request.url.path and state["limited"]:
            state["limited"] -= 1
            return httpx.Response(403, json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}})
        return original(request)

    assert gmail_sync.sync(settings, transport=httpx.MockTransport(throttled))["fetched"] == 1


def test_a_different_account_cannot_reuse_this_folder(live):
    settings, fake = live
    gmail_sync.sync(settings, transport=fake.transport())
    original = fake.handler

    def other(request):
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "someone@demo.invalid",
                                             "historyId": "999"})
        return original(request)

    with pytest.raises(GmailError):
        gmail_sync.sync(settings, transport=httpx.MockTransport(other))


def test_only_one_sync_runs_at_a_time(live):
    settings, fake = live
    assert gmail_sync._SYNC_LOCK.acquire(blocking=False)
    try:
        assert gmail_sync.sync(settings, transport=fake.transport()) == {
            "skipped": "another Gmail check is running"}
    finally:
        gmail_sync._SYNC_LOCK.release()
    assert fake.calls == []


def test_a_skip_made_before_the_build_wins(live):
    from inbound.evidence.registry import store_registry

    settings, fake = live
    gmail_sync.sync(settings, transport=fake.transport())
    with closing(connect(settings.db_path)) as db:
        store_registry(db, json.loads(Path("fixtures/evidence_snapshot.json").read_text("utf8")))
        db.execute("UPDATE opportunities SET status='skipped'")
        db.commit()
    assert gmail_sync.auto_packs(settings) == 0


def test_poller_survives_a_failure_while_scheduling(live, monkeypatch):
    settings, _ = live

    def broken(self):
        raise OSError("state unreadable")

    monkeypatch.setattr(gmail_sync.Poller, "due", broken)
    assert gmail_sync.Poller(settings).tick() == {"error": "OSError"}


def test_one_oversized_message_is_skipped_not_fatal(live, monkeypatch):
    settings, fake = live
    fake.add("big", raw_call("big", attach=False))
    monkeypatch.setattr(gmail_api, "MAX_RAW_BYTES", 2000)
    fake.messages["big"] = raw_call("big") * 2  # with the PDF: well over the patched cap
    fake.messages["g1"] = raw_call("g1", attach=False)
    result = gmail_sync.sync(settings, transport=fake.transport())
    assert result["too_large"] == 1 and result["fetched"] == 1
    assert gmail_sync.sync(settings, transport=fake.transport())["too_large"] == 0  # not retried
