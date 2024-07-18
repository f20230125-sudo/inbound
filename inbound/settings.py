"""Offline settings; no environment variable constructs a network provider."""

import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class OfflineLLM:
    def complete(self, prompt):
        raise LookupError("Offline replay cache miss")


@dataclass
class Settings:
    root: Path = REPO
    data_root: Path | None = None
    database: Path | None = None
    offline: bool = True
    # The public demo runs a read-only replay of fictional data on a host without a D:
    # drive. Only app.py sets this; Settings.from_env() never does.
    hosted_replay: bool = False
    personal_contacts: tuple[str, ...] = (
        "noor@contacts.demo.invalid",
        "ishan@contacts.demo.invalid",
        "leena@contacts.demo.invalid",
    )

    def __post_init__(self):
        self.root = self.root.resolve()
        if self.root.drive.upper() != "D:" and not self.hosted_replay:
            raise ValueError("Repository must be on D:")
        if self.data_root is not None:
            self.data_root = self.data_root.resolve()
            if self.data_root.drive.upper() != "D:" and not self.hosted_replay:
                raise ValueError("Configured data root must be on D:")
        else:
            self.data_root = self.root / ".local"
        self.database = (self.database or self.data_root / "demo.sqlite").resolve()
        if not self.database.is_relative_to(self.data_root):
            raise ValueError("Database must remain under the writable data root")
        if not self.offline:
            raise ValueError("Only offline mode exists in M1")

    @property
    def db_path(self):
        return self.database

    @property
    def report_dir(self):
        return self.data_root / "reports"

    @classmethod
    def from_env(cls):
        configured = os.environ.get("INBOUND_DATA_ROOT")
        options = {"data_root": Path(configured) if configured else None}
        if "INBOUND_PERSONAL_CONTACTS" in os.environ:
            options["personal_contacts"] = tuple(
                value.strip().casefold()
                for value in os.environ["INBOUND_PERSONAL_CONTACTS"].split(",")
                if value.strip()
            )
        return cls(**options)

    def build_llm(self):
        return OfflineLLM()
