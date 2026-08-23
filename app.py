"""Hosted entry point: a read-only replay of the fictional demo desk (Vercel).

The hosted copy never reads mail, never connects Gmail and refuses every change. It
serves the synthetic desk built by `scripts/build_public_demo.py` from a writable copy
in the host's temporary folder.
"""

import os
import shutil
import tempfile
from pathlib import Path

from inbound.api import create_app
from inbound.settings import Settings

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "public_demo"
COPY = Path(os.environ.get("INBOUND_DEMO_COPY", Path(tempfile.gettempdir()) / "inbound-demo"))

if not (COPY / "demo.sqlite").exists():
    shutil.copytree(SOURCE, COPY, dirs_exist_ok=True)

app = create_app({
    "APP_MODE": "replay",
    "SETTINGS": Settings(root=HERE, data_root=COPY, hosted_replay=True),
    "WEB_DIST": HERE / "public",
    "DEMO": True,
    "ASYNC_WORK": False,
    # Only the demo's own addresses (the production alias and its deployment URLs).
    "HOSTED_HOSTS": r"inbound-scout(?:-[a-z0-9]+-uzair-ba1c)?\.vercel\.app|127\.0\.0\.1(?::[0-9]{1,5})?",
})
