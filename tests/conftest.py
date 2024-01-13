import os
import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def deny_egress(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Networking and subprocesses are forbidden in M1 tests")

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
