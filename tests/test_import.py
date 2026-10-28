from dataclasses import replace
from pathlib import Path

import pytest

from inbound.db import import_messages
from inbound.sources.eml_dir import load as load_eml
from inbound.sources.export_txt import load


def test_repeat_and_alternate_import(database):
    messages = list(load(Path("fixtures/export_sample"), "synthetic"))
    assert import_messages(database, messages)["imported"] == 190
    assert import_messages(database, messages) == {"imported": 0, "unchanged": 190, "changed": 0}
    assert import_messages(database, load_eml(Path("fixtures/eml_sample"), "synthetic")) == {
        "imported": 0,
        "unchanged": 5,
        "changed": 0,
    }


def test_scoped_ids_and_content_history(database):
    message = next(load(Path("fixtures/export_sample"), "synthetic"))
    import_messages(database, [message, replace(message, provider="other")])
    changed = replace(message, body_text="changed source content")
    assert import_messages(database, [changed])["changed"] == 1
    assert import_messages(database, [changed])["unchanged"] == 1
    row = database.execute("SELECT body_text FROM messages WHERE provider=?", (message.provider,))
    assert row.fetchone()[0] == message.body_text
    assert database.execute("SELECT count(*) FROM message_history").fetchone()[0] == 3


def test_transactional_failure(database):
    message = next(load(Path("fixtures/export_sample"), "synthetic"))

    def broken():
        yield message
        raise ValueError("synthetic parser failure")

    with pytest.raises(ValueError):
        import_messages(database, broken())
    assert database.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert database.execute("SELECT count(*) FROM message_history").fetchone()[0] == 0


def test_database_failure_rolls_back_whole_batch(database):
    messages = list(load(Path("fixtures/export_sample"), "synthetic"))[:2]
    database.execute(
        "CREATE TRIGGER reject_second BEFORE INSERT ON messages "
        "WHEN (SELECT count(*) FROM messages)=1 "
        "BEGIN SELECT RAISE(ABORT, 'synthetic db failure'); END"
    )
    with pytest.raises(Exception, match="synthetic db failure"):
        import_messages(database, messages)
    for table in ("messages", "message_history", "attachments"):
        assert database.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_migrations_are_applied_once(tmp_path):
    from inbound.db import connect

    path = tmp_path / "migrations.sqlite"
    db = connect(path)
    db.close()
    db = connect(path)
    assert db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 11
    db.execute("UPDATE schema_migrations SET sha256='altered'")
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="migration was modified"):
        connect(path)


def test_import_rejects_mixed_provenance(database):
    message = next(load(Path("fixtures/export_sample"), "synthetic"))
    with pytest.raises(ValueError, match="Mixed import provenance"):
        import_messages(
            database, [message, replace(message, provider_id="private-like", source="private")]
        )
    assert database.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_unchanged_import_hydrates_m1_attachment_location(database):
    message = next(
        m for m in load(Path("fixtures/export_sample"), "synthetic") if m.provider_id == "P-D15"
    )
    old = replace(
        message,
        attachments=tuple(
            replace(a, import_root=None, bytes_available=False) for a in message.attachments
        ),
    )
    import_messages(database, [old])
    assert import_messages(database, [message])["unchanged"] == 1
    row = database.execute("SELECT import_root,bytes_available FROM attachments").fetchone()
    assert row["import_root"] == message.attachments[0].import_root and row["bytes_available"]
