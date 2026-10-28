"""Build the public demo: a fictional desk for the hosted read-only replay.

Everything here is synthetic: the frozen test mail, the fictional college mail, the
fictional applicant's memories and her CV packs. No private file is read.

    python scripts/build_public_demo.py      # writes public_demo/
"""

import json
import shutil
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from inbound import briefing, memory
from inbound.db import connect
from inbound.demo import build_demo
from inbound.packs.build import create_pack
from inbound.settings import Settings
from inbound.work import execute, start_run

OUT = REPO / "public_demo"
EXTRA_PACKS = ("P-D15", "P-D18")  # PDF and DOCX job descriptions


def college_mail(folder):
    """Write the fictional college fixtures in the export format."""
    folder.mkdir(parents=True, exist_ok=True)
    for mail in json.loads((REPO / "fixtures/college.json").read_text("utf8")):
        (folder / f"college-{mail['id']}.txt").write_text(
            f"id: college-{mail['id']}\nthread_id: college-{mail['thread']}\n"
            f"date: {mail['sent']}\nfrom: {mail['sender']}\nto: sara@fiction.demo.invalid\n"
            "cc:\nbcc:\nlabels:\nattachments:\nbody_exported: fictional college fixture\n"
            f"subject: {mail['subject']}\nbody_complete: true\n---\n{mail['body']}\n",
            encoding="utf-8",
        )


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    settings = Settings(data_root=OUT)
    result = build_demo(settings)
    clock = datetime.fromisoformat(result["clock"])
    college_mail(OUT / "college-mail")
    with closing(connect(settings.db_path)) as db:
        run_id = start_run(db, "import", source_type="export")
    execute(settings, run_id, "import", root=OUT / "college-mail", source="export",
            provenance="synthetic", clock=lambda: clock)
    shutil.copytree(REPO / "fixtures/memory", OUT / "memory")
    with closing(connect(settings.db_path)) as db:
        memory.refresh(db, settings, source="synthetic")
        for case in EXTRA_PACKS:
            oid = db.execute(
                "SELECT r.opportunity_id FROM opportunity_revisions r JOIN messages m "
                "ON m.id=r.message_id WHERE m.provider_id=?", (case,)).fetchone()[0]
            create_pack(db, oid, demo=True, settings=settings)
        briefing.generate(db, clock)
        assert not db.execute("SELECT 1 FROM messages WHERE source<>'synthetic'").fetchone()
        assert not db.execute("SELECT 1 FROM packs WHERE demo<>1").fetchone()
        counts = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("messages", "opportunities", "packs", "tasks", "memories",
                                "agent_steps", "briefings")}
    shutil.rmtree(OUT / "college-mail")
    for leftover in ("reports", "pycache"):
        shutil.rmtree(OUT / leftover, ignore_errors=True)
    scrub_paths()
    print(json.dumps(counts))


def local_forms(path):
    text = str(path)
    return [text, text.replace("\\", "\\\\"), text.replace("\\", "/")]


def scrub(text):
    """Remove this machine's folder layout from anything the public demo ships."""
    for local in local_forms(OUT):
        text = text.replace(local, "<demo>")
    for local in local_forms(REPO):
        text = text.replace(local, "<repo>")
    return text


def scrub_paths():
    with closing(connect(OUT / "demo.sqlite")) as db, db:
        for row in db.execute("SELECT id,files_json FROM packs").fetchall():
            files = {name: Path(value).relative_to(OUT).as_posix()
                     for name, value in json.loads(row["files_json"]).items()}
            db.execute("UPDATE packs SET files_json=? WHERE id=?", (json.dumps(files), row["id"]))
        for table, column in (("messages", "attachments_json"), ("attachments", "import_root"),
                              ("packs", "selection_json"), ("packs", "checks_json")):
            for key, value in db.execute(f"SELECT rowid,{column} FROM {table}").fetchall():
                if isinstance(value, str) and value != scrub(value):
                    db.execute(f"UPDATE {table} SET {column}=? WHERE rowid=?", (scrub(value), key))
    with closing(connect(OUT / "demo.sqlite")) as db:
        db.execute("VACUUM")  # replaced values otherwise survive in free pages of the file
    for path in OUT.rglob("*"):
        if path.suffix in {".log", ".json", ".txt", ".tex"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if scrub(text) != text:
                path.write_text(scrub(text), encoding="utf-8")


if __name__ == "__main__":
    main()
