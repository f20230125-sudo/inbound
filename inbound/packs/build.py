"""The only subprocess boundary: cached, untrusted Tectonic compilation."""

import json
import os
import subprocess
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

from inbound.evidence.registry import import_evidence, load_registry
from inbound.extract.pipeline import latest_revision, opportunity_state
from inbound.ledger import run, timestamp
from inbound.packs.answers import answers
from inbound.packs.rank import rank
from inbound.packs.render import render
from inbound.packs.verify import verify
from inbound.pause import check
from inbound.settings import REPO, Settings

TECTONIC = Path("D:/codex/tools/tectonic/tectonic.exe")
CACHE = REPO / ".local/tectonic-cache/cache"
STATUSES = {"new", "preparing", "needs_review", "reviewed", "submitted_by_me", "blocked", "skipped"}


def compile_tex(directory):
    directory = Path(directory).resolve()
    temporary = REPO / ".local/tectonic-tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "TECTONIC_CACHE_DIR": str(CACHE),
        "TMP": str(temporary),
        "TEMP": str(temporary),
    }
    command = [
        str(TECTONIC),
        "-X",
        "compile",
        "--only-cached",
        "--untrusted",
        "--outdir",
        str(directory),
        "body.tex",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=directory,
            env=env,
            timeout=120,
            capture_output=True,
            text=True,
            encoding="utf8",
            errors="replace",
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        (directory / "build.log").write_text("Build timeout\n", encoding="utf8")
        raise RuntimeError("Tectonic timeout") from None
    (directory / "build.log").write_text(result.stdout + result.stderr, encoding="utf8")
    if result.returncode or not (directory / "body.pdf").is_file():
        raise RuntimeError("Tectonic build failed")
    return directory / "body.pdf"


def create_pack(db, opportunity_id, *, demo=False, pack_root=None, settings=None, run_counts=None):
    with (run(db, "pack") if run_counts is None else nullcontext(run_counts)) as counts:
        check(db)
        state = opportunity_state(db, opportunity_id)
        if demo:
            source = db.execute(
                "SELECT m.source FROM messages m JOIN opportunity_revisions r "
                "ON r.message_id=m.id WHERE r.opportunity_id=?",
                (opportunity_id,),
            ).fetchall()
            if any(row[0] != "synthetic" for row in source):
                raise ValueError("Demo packs require synthetic opportunities")
            import_evidence(db, demo=True)
        registry = load_registry(db, "demo" if demo else "public")
        revision = latest_revision(db, opportunity_id)
        roles = db.execute(
            "SELECT * FROM roles WHERE revision_id=? ORDER BY id", (revision["id"],)
        ).fetchall()
        ranked_roles = [
            (row, rank(registry, json.loads(row["requirements_json"]))) for row in roles
        ]
        role, selection = (
            max(
                ranked_roles,
                key=lambda pair: (
                    pair[1]["coverage"]["ratio"] if pair[1]["coverage"]["ratio"] is not None else -1
                ),
            )
            if ranked_roles
            else (None, rank(registry, []))
        )
        if role:
            cov = selection["coverage"]
            selection["recommended_role"] = {
                "id": role["id"],
                "title": role["title"],
                "reason": f"Best evidence coverage: {cov['supported']} of {cov['total']} "
                "requirements supported; ties use SPEC/source role order.",
            }
        selection["other_roles"] = [
            {
                "id": row["id"],
                "title": row["title"],
                "coverage": ranked,
            }
            for row, ranked in ranked_roles
            if row is not role
        ]
        check(db)
        pack_id = uuid4().hex
        settings = settings or Settings.from_env()
        allowed = (settings.data_root / "packs").resolve()
        directory = Path(pack_root or allowed).resolve() / pack_id
        if not directory.is_relative_to(allowed):
            raise ValueError("Pack output must remain under a configured local data root")
        provisional = bool(state.get("blocked_reason"))
        with db:
            db.execute(
                "INSERT INTO packs(id,opportunity_id,role_id,revision_id,status,created_at,"
                "provisional,demo,content_version) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    pack_id,
                    opportunity_id,
                    role["id"] if role else None,
                    revision["id"],
                    "preparing",
                    timestamp(),
                    int(provisional),
                    int(demo),
                    state["content_version"],
                ),
            )
            if not provisional:
                db.execute(
                    "UPDATE opportunities SET status='preparing',updated_at=? WHERE id=?",
                    (timestamp(), opportunity_id),
                )
        try:
            check(db)
            rendered = render(
                directory,
                registry,
                selection,
                company=state["company"] or "Unknown",
                role=role["title"] if role else "Opportunity",
                demo=demo,
                provisional=provisional,
                naming_rule=state["fields"]["cv_naming_rule"]["normalized"],
            )
            check(db)
            pdf = compile_tex(directory)
            check(db)
            destination = directory / rendered["filename"]
            pdf.replace(destination)
            checks = verify(destination, directory / "build.log", registry, selection, rendered)
            files = {
                "pdf": str(destination),
                "tex": str(directory / "body.tex"),
                "log": str(directory / "build.log"),
                "answers": str(directory / "answers.txt"),
            }
            check(db)
            rows = answers(registry, selection)
            (directory / "answers.txt").write_text(
                "\n\n".join(
                    "\n".join(f"{key}: {value}" for key, value in row.items()) for row in rows
                ),
                encoding="utf8",
            )
            (directory / "verification.json").write_text(
                json.dumps(checks, indent=2), encoding="utf8"
            )
            (directory / "selection.json").write_text(
                json.dumps(selection, indent=2), encoding="utf8"
            )
            with db:
                db.execute(
                    "UPDATE packs SET status=?,selection_json=?,files_json=?,checks_json=? "
                    "WHERE id=?",
                    (
                        "needs_review" if checks["passed"] else "blocked",
                        json.dumps(selection),
                        json.dumps(files),
                        json.dumps(checks),
                        pack_id,
                    ),
                )
                if checks["passed"] and not provisional:
                    db.execute(
                        "UPDATE opportunities SET status='needs_review',updated_at=? WHERE id=?",
                        (timestamp(), opportunity_id),
                    )
            if not checks["passed"]:
                raise RuntimeError("Pack verification failed")
            counts["built"] = 1
            return {
                "id": pack_id,
                "status": "needs_review",
                "selection": selection,
                "files": files,
                "checks": checks,
                "rendered": rendered,
            }
        except Exception:
            with db:
                db.execute("UPDATE packs SET status='blocked' WHERE id=?", (pack_id,))
                db.execute(
                    "UPDATE opportunities SET status='blocked',updated_at=? WHERE id=?",
                    (timestamp(), opportunity_id),
                )
            raise


def set_status(db, pack_id, status, *, acknowledge_blocker=False):
    check(db)
    if status not in STATUSES:
        raise ValueError("Unknown pack status")
    pack = db.execute("SELECT * FROM packs WHERE id=?", (pack_id,)).fetchone()
    if pack is None:
        raise ValueError("Unknown pack")
    if status in {"reviewed", "submitted_by_me"}:
        revision = latest_revision(db, pack["opportunity_id"])
        version = db.execute("SELECT content_version FROM opportunities WHERE id=?",
                             (pack["opportunity_id"],)).fetchone()[0]
        if revision["id"] != pack["revision_id"] or version != pack["content_version"]:
            raise ValueError("Pack revision is stale; rebuild before review")
        if not json.loads(pack["checks_json"]).get("passed"):
            raise ValueError("Pack verification must pass before review")
        if pack["provisional"] and not (acknowledge_blocker or pack["blocker_acknowledged"]):
            raise ValueError("Must acknowledge the provisional blocker before review")
        if status == "submitted_by_me" and pack["status"] != "reviewed":
            raise ValueError("Review is required before recording submission")
    with db:
        db.execute(
            "UPDATE packs SET status=?,blocker_acknowledged=MAX(blocker_acknowledged,?) WHERE id=?",
            (status, int(acknowledge_blocker), pack_id),
        )
        db.execute(
            "UPDATE opportunities SET status=?,updated_at=? WHERE id=?",
            (status, timestamp(), pack["opportunity_id"]),
        )
