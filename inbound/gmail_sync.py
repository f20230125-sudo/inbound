"""Live Gmail sync: fetch new mail to the private data root, then run the normal pipeline.

Fetching (network, read-only) and importing (offline, staged) are separate so every
import stays reproducible from the saved .eml files. The ledger stores counts only.
"""

import json
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from inbound.db import connect
from inbound.pause import check, is_paused
from inbound.sources.gmail_api import (
    GmailClient,
    GmailError,
    TooLarge,
    gmail_dir,
    read_json,
    token_path,
    write_json,
)

DEFAULT_QUERY = "newer_than:30d -in:sent -in:drafts -in:chats"
MAX_PER_SYNC = 300
MIN_MINUTES, DEFAULT_MINUTES = 1, 2
SKIP_LABELS = {"SPAM", "TRASH", "DRAFT"}
# One sync at a time per process: the poller and "Check Gmail now" share files and state.
_SYNC_LOCK = threading.Lock()


def is_syncing():
    """Expose actual ongoing work without starting a check."""
    return _SYNC_LOCK.locked()


def mail_dir(settings):
    return gmail_dir(settings) / "mail"


def state_path(settings):
    return gmail_dir(settings) / "state.json"


def connected(settings):
    return token_path(settings).exists()


def poll_settings(db):
    rows = dict(db.execute(
        "SELECT key,value FROM settings WHERE key IN ('gmail_poll_enabled','gmail_poll_minutes')"
    ).fetchall())
    minutes = int(rows.get("gmail_poll_minutes") or DEFAULT_MINUTES)
    return {"enabled": rows.get("gmail_poll_enabled") == "1", "minutes": max(MIN_MINUTES, minutes)}


def set_poll(db, *, enabled, minutes):
    if type(enabled) is not bool or type(minutes) is not int or minutes < MIN_MINUTES:
        raise ValueError("Polling needs a boolean and at least 1 minute")
    with db:
        for key, value in (("gmail_poll_enabled", "1" if enabled else "0"),
                           ("gmail_poll_minutes", str(minutes))):
            db.execute("INSERT INTO settings(key,value) VALUES (?,?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def status(settings, db):
    token = read_json(token_path(settings)) or {}
    state = read_json(state_path(settings)) or {}
    poll = poll_settings(db)
    last = state.get("last_sync_at")
    next_check = None
    if poll["enabled"] and token and last:
        next_check = (datetime.fromisoformat(last) + timedelta(minutes=poll["minutes"])).isoformat()
    return {
        "connected": bool(token),
        "email": token.get("email") or None,
        "read_only": True,
        "poll_enabled": poll["enabled"],
        "poll_minutes": poll["minutes"],
        "last_sync_at": last,
        "last_result": state.get("last_result"),
        "last_error": state.get("last_error"),
        "next_check_at": next_check,
    }


def fetch_new(settings, client, *, query=DEFAULT_QUERY, limit=MAX_PER_SYNC):
    """Save messages Gmail added since the last sync; return how many were saved.

    The history cursor moves only after every listed message is handled, so an error or
    Pause part-way leaves it where it was and the next sync repeats the same range (files
    already saved are skipped). Only the very first listing is bounded to `limit` newest.
    """
    folder = mail_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    state = read_json(state_path(settings)) or {}
    profile = client.profile()
    email = profile.get("emailAddress")
    if state.get("email") and email and state["email"] != email:
        # Another account's cursor and saved mail must never mix with this one.
        raise GmailError("Connected account changed; use a new data folder for it")
    ids = None
    if state.get("history_id"):
        try:
            ids = client.history_ids(state["history_id"])
        except FileNotFoundError:
            ids = None  # history expired or too long: fall back to a bounded listing
    if ids is None:
        ids = client.list_ids(query, limit)
    saved, skipped = 0, 0
    for message_id in ids:
        if (folder / f"{message_id}.json").exists() or (folder / f"{message_id}.skipped").exists():
            continue
        try:
            data, meta = client.raw(message_id)
        except FileNotFoundError:
            continue  # deleted between listing and fetching
        except TooLarge:
            # Over 25 MB: recorded (id only) and never retried, so one huge mail cannot stop sync.
            (folder / f"{message_id}.skipped").write_text("larger than 25 MB", encoding="utf-8")
            skipped += 1
            continue
        labels = set(meta["labelIds"])
        # History also reports spam, trash, drafts and Uzair's own sent mail; none is inbox.
        if labels & SKIP_LABELS or ("SENT" in labels and "INBOX" not in labels):
            continue
        (folder / f"{meta['id']}.eml").write_bytes(data)
        write_json(folder / f"{meta['id']}.json", meta)  # written last: marks the pair complete
        saved += 1
    state = read_json(state_path(settings)) or {}
    state["email"] = email or state.get("email")
    state["history_id"] = profile.get("historyId", state.get("history_id"))
    write_json(state_path(settings), state)
    return {"listed": len(ids), "fetched": saved, "too_large": skipped}


def unimported(settings):
    """Saved messages not yet in the database (e.g. a crash between download and import)."""
    folder = mail_dir(settings)
    rejected = {path.stem for path in folder.glob("*.rejected")}
    saved = {path.stem for path in folder.glob("*.json")} - rejected
    if not saved:
        return set()
    with closing(connect(settings.db_path)) as db:
        known = {row[0] for row in db.execute(
            "SELECT provider_id FROM messages WHERE provider='mail'")}
    return saved - known


def pause_guard(settings):
    def guard():
        with closing(connect(settings.db_path)) as db:
            check(db)
    return guard


def record_result(settings, result=None, error=None):
    state = read_json(state_path(settings)) or {}
    state["last_sync_at"] = datetime.now(UTC).isoformat()
    state["last_result"] = result
    state["last_error"] = error
    write_json(state_path(settings), state)


def sync(settings, *, transport=None, clock=None):
    """One sync: fetch new Gmail messages, import any saved mail not yet imported, then
    build draft packs for calls that became buildable."""
    if not _SYNC_LOCK.acquire(blocking=False):
        return {"skipped": "another Gmail check is running"}
    try:
        from inbound.steps import Empty, Kind, emit, scope

        with scope(correlation_id=uuid4().hex, source='private'):
            def record_step(kind):
                with closing(connect(settings.db_path)) as db, db:
                    emit(db, kind, Empty())

            record_step(Kind.GMAIL_STARTED)
            try:
                result = _sync(settings, transport=transport, clock=clock)
            except Exception:
                record_step(Kind.GMAIL_FAILED)
                raise
            record_step(Kind.GMAIL_FINISHED if result.get('status', 'success') == 'success'
                        else Kind.GMAIL_FAILED)
            return result
    finally:
        _SYNC_LOCK.release()


def _sync(settings, *, transport, clock):
    from inbound.work import execute, start_run

    token = read_json(token_path(settings))
    if not token:
        raise GmailError("Gmail is not connected")
    guard = pause_guard(settings)
    guard()
    client = GmailClient(token, transport=transport, before_request=guard,
                         on_refresh=lambda t: write_json(token_path(settings), t))
    try:
        fetched = fetch_new(settings, client)
    except (GmailError, OSError, ValueError, KeyError) as exc:
        record_result(settings, error=type(exc).__name__ + ": " + str(exc)[:120])
        raise
    finally:
        client.close()
    result = dict(fetched)
    from inbound.steps import Fetch, Kind, emit

    with closing(connect(settings.db_path)) as db, db:
        emit(db, Kind.GMAIL_FETCHED, Fetch(**fetched))
    # Import whenever saved mail is missing from the database, not only after new downloads.
    if unimported(settings):
        with closing(connect(settings.db_path)) as db:
            run_id = start_run(db, "import", source_type="gmail")
        execute(settings, run_id, "import", root=mail_dir(settings), source="gmail",
                provenance="private", clock=clock)
        with closing(connect(settings.db_path)) as db:
            row = db.execute("SELECT status,counts_json FROM runs WHERE id=?", (run_id,)).fetchone()
        result.update(json.loads(row["counts_json"] or "{}"))
        result["status"] = row["status"]
    if result.get("status", "success") == "success":
        # Runs on every check, so calls left over from a busy check are drained later.
        result["auto_packs"] = auto_packs(settings)
    record_result(settings, result=result)
    return result


def buildable(db, opportunity_id):
    """Eligible for an automatic draft right now: judged on the effective (sent-time)
    revision, rechecked immediately before each build so a later Skip always wins."""
    from inbound.extract.pipeline import latest_revision

    row = db.execute("SELECT status,blocked_reason FROM opportunities WHERE id=?",
                     (opportunity_id,)).fetchone()
    if row is None or row["blocked_reason"] or row["status"] in {
            "blocked", "skipped", "submitted_by_me", "reviewed"}:
        return False
    revision = latest_revision(db, opportunity_id)
    if revision is None or db.execute(
            "SELECT 1 FROM packs WHERE opportunity_id=? AND revision_id=?",
            (opportunity_id, revision["id"])).fetchone():
        return False
    return bool(db.execute(
        "SELECT 1 FROM roles WHERE revision_id=? AND requirements_json NOT IN ('null','[]')",
        (revision["id"],)).fetchone())


def auto_packs(settings, limit=5):
    """Draft packs for calls that became buildable: readable requirements, not blocked,
    no pack yet for the current revision. Drafts only (needs_review); never reviewed or sent."""
    from inbound.work import execute, start_run

    with closing(connect(settings.db_path)) as db:
        check(db)
        if not db.execute("SELECT 1 FROM evidence_snapshots WHERE scope='public'").fetchone():
            return 0  # the CV evidence registry has not been imported on this desk yet
        ids = [row[0] for row in db.execute("SELECT id FROM opportunities ORDER BY id DESC")]
        candidates = [oid for oid in ids if buildable(db, oid)][:limit]
    built = 0
    for opportunity_id in candidates:
        with closing(connect(settings.db_path)) as db:
            check(db)
            if not buildable(db, opportunity_id):
                continue  # skipped, built by hand or changed while earlier drafts built
            run_id = start_run(db, "pack", opportunity_id=opportunity_id)
        execute(settings, run_id, "pack", opportunity_id=opportunity_id)
        with closing(connect(settings.db_path)) as db:
            ok = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0]
        built += ok == "success"
    return built


class Poller:
    """Background loop used by `serve` and `watch`. Off until Uzair enables it in the desk."""

    def __init__(self, settings, *, on_result=None, sleep=time.sleep):
        self.settings, self.on_result, self.sleep = settings, on_result, sleep
        self.stop = threading.Event()
        self.thread = None

    def due(self):
        if not connected(self.settings):
            return False
        with closing(connect(self.settings.db_path)) as db:
            poll = poll_settings(db)
            paused = is_paused(db)
        if not poll["enabled"] or paused:
            return False
        last = (read_json(state_path(self.settings)) or {}).get("last_sync_at")
        if not last:
            return True
        return datetime.now(UTC) >= datetime.fromisoformat(last) + timedelta(minutes=poll["minutes"])

    def tick(self):
        try:
            if not self.due():
                return None
            result = sync(self.settings)
        except Exception as exc:  # noqa: BLE001 - the background loop must survive any failure
            result = {"error": type(exc).__name__}
        if self.on_result:
            self.on_result(result)
        return result

    def run(self):
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(20)

    def start(self):
        self.thread = threading.Thread(target=self.run, name="gmail-poller", daemon=True)
        self.thread.start()
        return self
