"""Fresh synthetic-only browser fixture; loopback server, no external transport."""

import os
import sys
from contextlib import closing
from pathlib import Path
from tempfile import mkdtemp

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "CODEX_BRIEF.md").is_file())
sys.path.insert(0, str(ROOT))

from inbound.api import create_app
from inbound.db import connect
from inbound.demo import build_demo
from inbound.packs.build import create_pack
from inbound.settings import Settings


def main():
    root = Path(mkdtemp(prefix="m4b-e2e-", dir=ROOT / ".local"))
    settings = Settings(data_root=root)
    build_demo(settings)
    with closing(connect(settings.db_path)) as db:
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
