"""Live Gmail sync: fetch new mail to the private data root, then run the normal pipeline.

Fetching (network, read-only) and importing (offline, staged) are separate so every
import stays reproducible from the saved .eml files. The ledger stores counts only.
"""

import json
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta

from inbound.db import connect
from inbound.pause import check, is_paused
from inbound.sources.gmail_api import (
    GmailClient,
    GmailError,
    gmail_dir,
    read_json,
    token_path,
    write_json,
)

DEFAULT_QUERY = "newer_than:30d -in:sent -in:drafts -in:chats"
MAX_PER_SYNC = 300
MIN_MINUTES, DEFAULT_MINUTES = 1, 2
SKIP_LABELS = {"SPAM", "TRASH", "DRAFT"}


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
    """Save messages Gmail added since the last sync; return how many were saved."""
    folder = mail_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    state = read_json(state_path(settings)) or {}
    profile = client.profile()
    ids = None
    if state.get("history_id"):
        try:
            ids = client.history_ids(state["history_id"], limit)
        except FileNotFoundError:
            ids = None  # history expired: fall back to a bounded full listing
    if ids is None:
        ids = client.list_ids(query, limit)
    saved = 0
    for message_id in ids:
        if (folder / f"{message_id}.json").exists():
            continue
        try:
            data, meta = client.raw(message_id)
        except FileNotFoundError:
            continue  # deleted between listing and fetching
        labels = set(meta["labelIds"])
        # History also reports spam, trash, drafts and Uzair's own sent mail; none is inbox.
        if labels & SKIP_LABELS or ("SENT" in labels and "INBOX" not in labels):
            continue
        (folder / f"{meta['id']}.eml").write_bytes(data)
        write_json(folder / f"{meta['id']}.json", meta)  # written last: marks the pair complete
        saved += 1
    state["history_id"] = profile.get("historyId", state.get("history_id"))
    write_json(state_path(settings), state)
    return {"listed": len(ids), "fetched": saved}


def record_result(settings, result=None, error=None):
    state = read_json(state_path(settings)) or {}
    state["last_sync_at"] = datetime.now(UTC).isoformat()
    state["last_result"] = result
    state["last_error"] = error
    write_json(state_path(settings), state)


def sync(settings, *, transport=None, clock=None):
    """One sync: fetch new Gmail messages, then a staged import of the saved folder."""
    from inbound.work import execute, start_run

    token = read_json(token_path(settings))
    if not token:
        raise GmailError("Gmail is not connected")
    with closing(connect(settings.db_path)) as db:
        check(db)
    client = GmailClient(token, transport=transport,
                         on_refresh=lambda t: write_json(token_path(settings), t))
    try:
        fetched = fetch_new(settings, client)
    except (GmailError, OSError, ValueError, KeyError) as exc:
        record_result(settings, error=type(exc).__name__ + ": " + str(exc)[:120])
        raise
    finally:
        client.close()
    result = dict(fetched)
    state = read_json(state_path(settings)) or {}
    # Import when new mail arrived, or when an earlier import of saved mail did not finish.
    if fetched["fetched"] or state.get("import_pending"):
        state["import_pending"] = True
        write_json(state_path(settings), state)
        with closing(connect(settings.db_path)) as db:
            run_id = start_run(db, "import", source_type="gmail")
        execute(settings, run_id, "import", root=mail_dir(settings), source="gmail",
                provenance="private", clock=clock)
        with closing(connect(settings.db_path)) as db:
            row = db.execute("SELECT status,counts_json FROM runs WHERE id=?", (run_id,)).fetchone()
        result.update(json.loads(row["counts_json"] or "{}"))
        result["status"] = row["status"]
        state = read_json(state_path(settings)) or {}
        state["import_pending"] = row["status"] != "success"
        write_json(state_path(settings), state)
        if row["status"] == "success":
            result["auto_packs"] = auto_packs(settings)
    record_result(settings, result=result)
    return result


def auto_packs(settings, limit=5):
    """Draft packs for calls that became buildable: readable requirements, not blocked,
    no pack yet for the current revision. Drafts only (needs_review); never reviewed or sent."""
    from inbound.work import execute, start_run

    with closing(connect(settings.db_path)) as db:
        check(db)
        if not db.execute("SELECT 1 FROM evidence_snapshots WHERE scope='public'").fetchone():
            return 0  # the CV evidence registry has not been imported on this desk yet
        candidates = [row[0] for row in db.execute(
            "SELECT o.id FROM opportunities o "
            "JOIN opportunity_revisions r ON r.id=(SELECT MAX(id) FROM opportunity_revisions "
            "WHERE opportunity_id=o.id) "
            "WHERE o.blocked_reason IS NULL "
            "AND o.status NOT IN ('blocked','skipped','submitted_by_me') "
            "AND EXISTS (SELECT 1 FROM roles WHERE revision_id=r.id "
            "AND requirements_json NOT IN ('null','[]')) "
            "AND NOT EXISTS (SELECT 1 FROM packs WHERE opportunity_id=o.id AND revision_id=r.id) "
            "ORDER BY o.id DESC LIMIT ?", (limit,),
        )]
    built = 0
    for opportunity_id in candidates:
        with closing(connect(settings.db_path)) as db:
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
        if not self.due():
            return None
        try:
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
