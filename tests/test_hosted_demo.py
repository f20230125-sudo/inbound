"""The public demo: a read-only replay of fictional data, safe to host anywhere."""

import importlib
import sqlite3
import sys

import pytest

from inbound.api import create_app
from inbound.settings import REPO, Settings

HOST = {"Host": "127.0.0.1:5090"}


def test_hosted_root_is_refused_outside_replay(tmp_path):
    with pytest.raises(ValueError):
        create_app({"APP_MODE": "local",
                    "SETTINGS": Settings(data_root=tmp_path, hosted_replay=True)})


def test_from_env_never_enables_hosted_replay(monkeypatch, tmp_path):
    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path))
    assert Settings.from_env().hosted_replay is False


def test_public_demo_is_synthetic_and_has_no_local_paths():
    db = sqlite3.connect(REPO / "public_demo/demo.sqlite")
    assert not db.execute("SELECT 1 FROM messages WHERE source<>'synthetic'").fetchone()
    assert not db.execute("SELECT 1 FROM packs WHERE demo<>1").fetchone()
    raw = (REPO / "public_demo/demo.sqlite").read_bytes()
    assert b"claude-workspace" not in raw and b"C:\\Users" not in raw


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOUND_DEMO_COPY", str(tmp_path / "copy"))
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    yield module
    sys.modules.pop("app", None)


def test_hosted_app_serves_the_fictional_desk_and_refuses_changes(hosted):
    client = hosted.app.test_client()
    for url in ("/api/agent/state", "/api/today", "/api/memory", "/api/tasks", "/api/briefing"):
        assert client.get(url, headers=HOST).status_code == 200, url
    pid = sqlite3.connect(hosted.COPY / "demo.sqlite").execute(
        "SELECT id FROM packs LIMIT 1").fetchone()[0]
    pdf = client.get(f"/api/packs/{pid}/pdf", headers=HOST)
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert client.post("/api/import", json={}, headers=HOST).status_code == 405
    assert client.post("/api/gmail/sync", json={}, headers=HOST).status_code == 405
    assert client.get("/api/gmail", headers=HOST).json["available"] is False


def test_passed_settings_are_used_without_building_defaults(tmp_path, monkeypatch):
    # On a host without D:, building default settings would fail before the passed ones apply.
    def refuse():
        raise AssertionError("defaults must not be built when settings are passed")

    monkeypatch.setattr(Settings, "from_env", staticmethod(refuse))
    app = create_app({"APP_MODE": "replay",
                      "SETTINGS": Settings(data_root=tmp_path, hosted_replay=True)})
    assert app.config["SETTINGS"].data_root == tmp_path.resolve()
