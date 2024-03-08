from inbound.digest import plain_text, today
from tests.m2_helpers import CLOCK
from tests.m3_helpers import opportunity


def test_digest_effective_title_and_blocker_reason(database):
    for case in ("P-D12", "P-D16", "P-D06", "J09"):
        opportunity(database, case)
    summary = today(database, CLOCK)
    ledger = next(row for row in summary["new_calls"] if row["provider_id"] == "P-D12")
    assert ledger["display_title"] == "Ledgercraft · Backend Intern · Cedar Quay"
    assert ledger["city"] == "Cedar Quay"
    blocked = next(row for row in summary["attention"] if row["provider_id"] == "P-D16")
    assert blocked["attention_reason"].startswith("Blocked: ")
    expired = next(row for row in summary["attention"] if row["provider_id"] == "P-D06")
    assert expired["attention_reason"].startswith("Expired")
    conflict = next(row for row in summary["attention"] if row["provider_id"] == "J09")
    assert conflict["attention_reason"] == "Deadline conflicting — review required"
    output = plain_text(summary)
    assert ledger["display_title"] in output
    assert blocked["attention_reason"] in output
    assert "Re: Fwd:" not in output


def test_settings_exposes_configured_import_format(tmp_path):
    from inbound.api import create_app
    from inbound.settings import Settings

    for source_format in ("eml", "export"):
        app = create_app({"SETTINGS": Settings(data_root=tmp_path), "SOURCE_FORMAT": source_format})
        with app.test_client() as client:
            assert client.get("/api/settings").json["source_format"] == source_format


def test_pack_preview_is_actual_confined_first_page(tmp_path, monkeypatch):
    from pathlib import Path

    from inbound.api import create_app
    from inbound.db import connect
    from inbound.settings import Settings
    from tests.m3_helpers import opportunity

    # PDFium only needs the OS family; avoid its Windows version probe in the sandbox.
    # Socket/DNS/subprocess denial remains active for the actual rasterization.
    monkeypatch.setattr("platform.system", lambda: "Windows")
    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        oid = opportunity(db, "P-D12")
    app = create_app({"SETTINGS": settings, "ASYNC_WORK": False, "DEMO": True})
    with app.test_client() as client:
        token = client.get("/api/settings").json["csrf_token"]
        client.post(
            f"/api/opportunities/{oid}/pack", json={}, headers={"X-CSRF-Token": token}
        )
        pack_id = client.get(f"/api/opportunities/{oid}").json["packs"][0]["id"]
        preview = client.get(f"/api/packs/{pack_id}/preview")
        assert preview.status_code == 200
        assert preview.mimetype == "image/png"
        assert preview.data.startswith(b"\x89PNG\r\n\x1a\n")
        # The exact artifact guard used by PDF downloads must guard raster previews too.
        import json

        with connect(settings.db_path) as db, db:
            db.execute(
                "UPDATE packs SET files_json=? WHERE id=?",
                (json.dumps({"pdf": str(Path(__file__).resolve())}), pack_id),
            )
        assert client.get(f"/api/packs/{pack_id}/preview").status_code == 404
