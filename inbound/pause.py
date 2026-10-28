class PausedError(RuntimeError):
    pass


def set_paused(db, paused):
    db.execute(
        "INSERT INTO settings(key,value) VALUES ('paused',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(int(paused)),),
    )
    db.commit()


def check(db):
    row = db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
    if row and row[0] == "1":
        raise PausedError("Inbound is paused")


def is_paused(db):
    row = db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
    return bool(row and row[0] == "1")
