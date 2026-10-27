from datetime import datetime
from pathlib import Path

from inbound.sources.export_txt import load

CLOCK = datetime.fromisoformat("2026-10-28T02:30:00+04:00")


def message(identity):
    return next(
        m for m in load(Path("fixtures/export_sample"), "synthetic") if m.provider_id == identity
    )
