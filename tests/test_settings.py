from pathlib import Path

import pytest

from inbound.settings import OfflineLLM, Settings


def test_offline_ignores_inherited_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-secret")
    monkeypatch.setenv("TELEGRAM_ENABLED", "1")
    settings = Settings.from_env()
    assert settings.offline
    assert isinstance(settings.build_llm(), OfflineLLM)
    with pytest.raises(LookupError):
        settings.build_llm().complete("no replay")


def test_write_paths_confined(tmp_path):
    settings = Settings(root=tmp_path)
    assert settings.db_path.is_relative_to(tmp_path / ".local")
    assert settings.report_dir.is_relative_to(tmp_path / ".local")
    for path in (tmp_path / "outside.sqlite", Path("C:/outside.sqlite")):
        with pytest.raises(ValueError):
            Settings(root=tmp_path, database=path)


def test_configured_root_requires_d_drive():
    with pytest.raises(ValueError):
        Settings(data_root=Path("C:/inbound-data"))
