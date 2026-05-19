import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from inbound.db import connect
from inbound.ledger import run
from inbound.pause import check, set_paused
from inbound.settings import Settings
from inbound.triage.rules import triage_messages


def main(argv=None):
    # Windows consoles default to cp1252; subjects and the digest contain en dashes and Ü.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m inbound")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("import")
    ingest.add_argument("--source", choices=("export", "eml"), required=True)
    ingest.add_argument("--path", type=Path, required=True)
    ingest.add_argument("--provenance", choices=("synthetic", "private"), required=True)
    for name in ("triage", "extract", "pause", "resume", "baseline", "demo", "digest",
                 "serve", "eval"):
        sub.add_parser(name)
    evidence = sub.add_parser('evidence')
    evidence.add_argument('action', choices=['import'])
    pack = sub.add_parser('pack')
    pack.add_argument('opportunity_id', type=int)
    pack.add_argument('--demo', action='store_true')
    applied = sub.add_parser('applied')
    applied.add_argument('opportunity_id', type=int)
    applied.add_argument('--at', required=True)
    applied.add_argument('--note', default='')
    applied.add_argument('--follow-up')
    applied.add_argument('--i-applied-myself', action='store_true')
    attach = sub.add_parser('attach')
    attach.add_argument('opportunity_id', type=int)
    attach.add_argument('--attachment', required=True)
    attach.add_argument('--file', type=Path, required=True)
    attach.add_argument('--preview', action='store_true')
    gmail = sub.add_parser('gmail')
    gmail.add_argument('action', choices=['connect', 'disconnect', 'sync', 'status', 'poll'])
    gmail.add_argument('--client-secret', type=Path)
    gmail.add_argument('--on', action='store_true')
    gmail.add_argument('--off', action='store_true')
    gmail.add_argument('--minutes', type=int, default=2)
    sub.add_parser('watch')
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == 'serve':
            from inbound.api import create_app
            from inbound.gmail_sync import Poller

            # Live Gmail checks run inside the desk once Uzair switches them on; never in
            # replay mode, which must stay read-only and synthetic.
            if os.environ.get("APP_MODE", "local") == "local":
                from inbound.work import interrupt_runs

                with closing(connect(settings.db_path)) as db:
                    interrupt_runs(db)
                Poller(settings).start()
            create_app().run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
            return 0
        if args.command == 'watch':
            from inbound.gmail_sync import Poller
            from inbound.work import interrupt_runs

            if os.environ.get('APP_MODE', 'local') != 'local':
                raise ValueError('Gmail watching is available in local mode only')
            with closing(connect(settings.db_path)) as db:
                interrupt_runs(db)

            def report(result):
                print(json.dumps(result), flush=True)

            print(json.dumps({"watching": True, "note": "Ctrl+C to stop"}), flush=True)
            try:
                Poller(settings, on_result=report).run()
            except KeyboardInterrupt:
                return 0
            return 0
        if args.command == 'gmail':
            from inbound import gmail_sync
            from inbound.sources import gmail_api

            if args.action == 'connect':
                if not args.client_secret:
                    raise ValueError("--client-secret is required")
                email = gmail_api.connect_account(settings, args.client_secret)
                print(json.dumps({"connected": True, "email": email}))
                return 0
            if args.action == 'disconnect':
                gmail_api.disconnect(settings)
                print(json.dumps({"connected": False}))
                return 0
            if args.action == 'sync':
                print(json.dumps(gmail_sync.sync(settings)))
                return 0
            with closing(connect(settings.db_path)) as db:
                if args.action == 'poll':
                    if args.on == args.off:
                        raise ValueError("Use --on or --off")
                    gmail_sync.set_poll(db, enabled=args.on, minutes=args.minutes)
                print(json.dumps(gmail_sync.status(settings, db)))
            return 0
        if args.command == 'demo':
            from inbound.demo import build_demo

            print(json.dumps(build_demo()))
            return 0
        if args.command == 'eval':
            from eval.run_eval import main as evaluate

            return evaluate()
        with closing(connect(settings.db_path)) as db:
            if args.command == 'attach':
                from inbound.attachment_recovery import confirm, preview

                matches = db.execute(
                    "SELECT a.id FROM attachments a JOIN opportunity_revisions r "
                    "ON r.message_id=a.message_id WHERE r.opportunity_id=? AND a.filename=?",
                    (args.opportunity_id, args.attachment),
                ).fetchall()
                if len(matches) != 1:
                    raise ValueError("Select one unambiguous attachment on this call")
                options = {"path": args.file, "mode": os.environ.get('APP_MODE', 'local')}
                result = preview(db, settings, args.opportunity_id, matches[0][0], **options)
                if not args.preview:
                    result = confirm(db, settings, args.opportunity_id, matches[0][0],
                                     **{k: result[k] for k in (
                                         'content_hash', 'expected_revision_id',
                                         'expected_content_version')}, **options)
                print(json.dumps(result))
                return 0
            if args.command == 'applied':
                from inbound.application_activity import latest, record
                from inbound.extract.pipeline import latest_revision

                previous = latest(db, args.opportunity_id)
                revision = latest_revision(db, args.opportunity_id)
                if revision is None:
                    raise ValueError("Opportunity not found")
                result = record(
                    db, args.opportunity_id, applied_at=args.at,
                    human_submission=args.i_applied_myself, note=args.note,
                    follow_up=args.follow_up, expected_revision_id=revision['id'],
                    expected_activity_id=previous['id'] if previous else None,
                    mode=os.environ.get('APP_MODE', 'local'),
                    expected_content_version=db.execute(
                        "SELECT content_version FROM opportunities WHERE id=?",
                        (args.opportunity_id,),
                    ).fetchone()[0],
                )
                print(json.dumps(result))
                return 0
            if args.command == 'digest':
                from inbound.digest import plain_text, today

                row = db.execute("SELECT value FROM settings WHERE key='demo_clock'").fetchone()
                from datetime import datetime

                print(plain_text(today(db, datetime.fromisoformat(row[0]) if row else None)), end='')
                return 0
            if args.command == 'pack':
                from inbound.packs.build import create_pack

                result = create_pack(db, args.opportunity_id, demo=args.demo)
                print(json.dumps({'id': result['id'], 'status': result['status'],
                                  'checks': result['checks']}))
                return 0
            if args.command in {"pause", "resume"}:
                set_paused(db, args.command == "pause")
                print(json.dumps({"paused": args.command == "pause"}))
                return 0
            if args.command == "import":
                from inbound.work import execute, start_run

                run_id = start_run(db, "import", source_type=args.source,
                                   source_provenance=args.provenance)
                execute(settings, run_id, "import", root=args.path, source=args.source,
                        provenance=args.provenance)
                result = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
                if result["status"] != "success":
                    print(json.dumps({"error": result["error"]}))
                    return 2
                print(result["counts_json"])
                return 0
            with run(db, args.command) as counts:
                check(db)
                if args.command == "triage":
                    counts["triaged"] = triage_messages(
                        db, personal_contacts=settings.personal_contacts
                    )
                    print(json.dumps(counts, sort_keys=True))
                elif args.command == "extract":
                    from inbound.extract.pipeline import extract_messages
                    from inbound.provenance import index_locations

                    counts.update(extract_messages(db))
                    index_locations(db)
                    print(json.dumps(counts, sort_keys=True))
                elif args.command == 'evidence':
                    from inbound.evidence.registry import import_evidence

                    registry = import_evidence(db)
                    counts.update(projects=len(registry['projects']), skills=len(registry['skills']))
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
