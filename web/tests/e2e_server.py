"""Fresh synthetic-only browser fixture; loopback server, no external transport."""

import os
import sys
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "CODEX_BRIEF.md").is_file())
sys.path.insert(0, str(ROOT))

from inbound.api import create_app
from inbound.db import connect, import_messages
from inbound.demo import build_demo
from inbound.extract.pipeline import extract_messages
from inbound.models import Attachment, Message
from inbound.packs.build import create_pack
from inbound.settings import Settings
from inbound.triage.rules import triage_messages


def main():
    root = Path(mkdtemp(prefix="m4b-e2e-", dir=ROOT / ".local"))
    settings = Settings(data_root=root)
    build_demo(settings)
    with closing(connect(settings.db_path)) as db:
        now = datetime(2026, 10, 28, 5, tzinfo=UTC)
        missing = Message(
            provider_id="M8-desktop-light", thread_id="M8-desktop-light",
            sent_at=now, received_at=now, sender="ps@dubai.bits-pilani.ac.in",
            subject="Call for CV - Recovery Fictional,DSO - Backend Intern",
            body_text="Job Title & JD\nAttached\n", source="synthetic",
            attachments=(Attachment("JD.pdf", "application/pdf"),),
        )
        import_messages(db, [replace(missing, provider_id=f"M8-{device}-{theme}",
                                     thread_id=f"M8-{device}-{theme}",
                                     subject=f"Call for CV - Recovery {device} {theme},DSO "
                                             "- Backend Intern")
                             for device in ("desktop", "mobile") for theme in ("light", "dark")])
        triage_messages(db)
        extract_messages(db)
        oid = db.execute(
            "SELECT r.opportunity_id FROM opportunity_revisions r "
            "JOIN messages m ON m.id=r.message_id WHERE m.provider_id='P-D16'"
        ).fetchone()[0]
        create_pack(db, oid, demo=True, settings=settings)
    port = int(os.environ.get("INBOUND_E2E_PORT", "5081"))
    (ROOT / f".local/inbound-e2e-{port}.pid").write_text(str(os.getpid()), "ascii")
    app = create_app(
        {"SETTINGS": settings, "DEMO": True, "TEST_CLOCK": True,
         "WEB_DIST": Path(__file__).resolve().parents[1] / "dist"}
    )
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
