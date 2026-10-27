import ast
import os
import socket
import subprocess
from pathlib import Path

import pytest

from inbound.__main__ import main


def test_runtime_denial():
    with pytest.raises(AssertionError):
        socket.getaddrinfo("example.invalid", 443)
    with pytest.raises(AssertionError):
        socket.socket()
    with pytest.raises(AssertionError):
        subprocess.run(["anything"], check=True)
    with pytest.raises(AssertionError):
        os.system("anything")


def test_package_has_no_transports():
    forbidden = {"socket", "subprocess", "httpx", "requests", "smtplib", "urllib", "http"}
    for path in Path("inbound").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden


def test_import_triage_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret")
    assert (
        main(
            [
                "import",
                "--source",
                "export",
                "--path",
                "fixtures/export_sample",
                "--provenance",
                "synthetic",
            ]
        )
        == 0
    )
    assert main(["triage"]) == 0
