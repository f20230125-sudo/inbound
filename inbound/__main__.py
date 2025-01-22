import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from inbound.db import connect, import_messages
from inbound.ledger import run
from inbound.pause import check, set_paused
from inbound.settings import Settings
from inbound.sources import eml_dir, export_txt
from inbound.triage.rules import triage_messages


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m inbound")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("import")
    ingest.add_argument("--source", choices=("export", "eml"), required=True)
    ingest.add_argument("--path", type=Path, required=True)
    ingest.add_argument("--provenance", choices=("synthetic", "private"), required=True)
    for name in ("triage", "extract", "pause", "resume", "baseline"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        with closing(connect(settings.db_path)) as db:
            if args.command in {"pause", "resume"}:
                set_paused(db, args.command == "pause")
                print(json.dumps({"paused": args.command == "pause"}))
                return 0
            with run(db, args.command) as counts:
                check(db)
                if args.command == "import":
                    loader = export_txt.load if args.source == "export" else eml_dir.load
                    counts.update(import_messages(db, loader(args.path, args.provenance)))
                    print(json.dumps(counts, sort_keys=True))
                elif args.command == "triage":
                    counts["triaged"] = triage_messages(
                        db, personal_contacts=settings.personal_contacts
                    )
                    print(json.dumps(counts, sort_keys=True))
                elif args.command == "extract":
                    from inbound.extract.pipeline import extract_messages

                    counts.update(extract_messages(db))
                    print(json.dumps(counts, sort_keys=True))
                else:
                    from eval.triage_baseline import baseline

                    report = baseline(db, settings.report_dir)
                    counts["evaluated"] = report["denominator"]
                    print(
                        json.dumps(
                            {
                                k: report[k]
                                for k in (
                                    "split",
                                    "denominator",
                                    "macro_f1",
                                    "ps_call_recall",
                                    "ps_admin_recall",
                                )
                            },
                            sort_keys=True,
                        )
                    )
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        # Parser/provider exception text may contain bodies, paths or credentials.
        print(json.dumps({"error": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
