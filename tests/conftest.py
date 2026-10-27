import os
import socket
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def deny_egress(monkeypatch):
    real_run, real_popen = subprocess.run, subprocess.Popen

    def denied(*args, **kwargs):
        raise AssertionError("Networking and subprocesses other than cached Tectonic are forbidden")

    def tectonic_only(command, options):
        from inbound.packs.build import CACHE, TECTONIC
        from inbound.settings import REPO

        assert isinstance(command, list) and len(command) == 8
        assert command[:6] == [
            str(TECTONIC),
            "-X",
            "compile",
            "--only-cached",
            "--untrusted",
            "--outdir",
        ]
        assert command[7] == "body.tex"
        output = Path(command[6]).resolve()
        assert output.is_relative_to(REPO / ".local")
        assert Path(options["cwd"]).resolve() == output
        assert options.get("shell") is False
        assert options["env"]["TECTONIC_CACHE_DIR"] == str(CACHE)

    def allowed_run(command, *args, **kwargs):
        tectonic_only(command, kwargs)
        assert kwargs.get("timeout") == 120
        assert kwargs.get("capture_output") is True
        return real_run(command, *args, **kwargs)

    def allowed_popen(command, *args, **kwargs):
        tectonic_only(command, kwargs)
        return real_popen(command, *args, **kwargs)

    for name in (
        "socket",
        "create_connection",
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
        "getnameinfo",
        "getfqdn",
        "socketpair",
        "fromfd",
        "fromshare",
    ):
        if not hasattr(socket, name):
            continue
        monkeypatch.setattr(socket, name, denied)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, denied)
    monkeypatch.setattr(subprocess, "run", allowed_run)
    monkeypatch.setattr(subprocess, "Popen", allowed_popen)
    for name in (
        "system",
        "popen",
        "startfile",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "posix_spawn",
        "posix_spawnp",
    ):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, denied)


@pytest.fixture
def database(tmp_path):
    from inbound.db import connect

    connection = connect(tmp_path / "test.sqlite")
    yield connection
    connection.close()
