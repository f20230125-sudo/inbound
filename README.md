# Inbound

Inbound is a personal inbox desk. M1 imports local mail exports and classifies messages.
M2 extracts evidence-bearing fields, bounded PDF/DOCX JDs and opportunity revisions.
M3 imports approved public evidence and builds verified, offline application previews.
It makes no outward actions. The desk UI remains later work.

Use the supplied Python 3.14 venv from this repository in PowerShell:

```powershell
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$env:PYTHONPYCACHEPREFIX = "$PWD\.local\pycache"
python -m synth.generate
python -m inbound import --source export --path fixtures/export_sample --provenance synthetic
python -m inbound import --source export --path fixtures/export_sample --provenance synthetic
python -m inbound import --source eml --path fixtures/eml_sample --provenance synthetic
python -m inbound triage
python -m inbound extract
python -m inbound baseline
python -m eval.extract_baseline
python -m inbound evidence import
python -m inbound pack 1 --demo
python -m eval.pack_eval
python -m inbound pause
python -m inbound resume
ruff check .
pytest --basetemp=.local/pytest-m3
```

The first export import adds 190 messages; repeats and the five EML alternates add zero.
Each message identity is scoped by provider (`mail` for both file formats). Changed content
is counted as `changed` and appended to history; the original message remains intact.
M1 triage uses that original snapshot. Transport encoding, newline endings, byte availability,
attachment file locations, and export notes are excluded from content identity.

All runtime data, reports, and test caches default to `.local/`. Triage and extraction
baselines write `.local/reports/m1.json`/`m1.md` and `m2.json`/`m2.md`, scoring only the
64 dev messages. Held-out and attacks are not scored in these baselines. Extraction
sets urgency from the effective deadline using a clock; the dev baseline injects
2026-10-28T02:30+04:00. Model comparison is explicitly not run.

Each call retains message-local fields and an effective revision snapshot. Explicit
deadline amendments supersede prior values; competing statements retain quoted candidates.
Quoted relative dates retain their original sent-time anchor. Missing/unreadable JDs block
review. `inbound.extract.pipeline.opportunity_state(db, id, clock=...)` computes expiry;
an unknown/conflicting deadline yields `expired=None`. New revisions invalidate reviewed
packs through the M2 invalidation hook. M3 binds each pack to its source revision.

`synth/cases.json` is the gold authority transcribed from the frozen manifest and audit
(`r4-20261028-01`, including the P-H25 unknown stipend). It contains source definitions,
independently authored gold fields and attachment plans. Regeneration is byte stable;
`fixtures/manifest.json` records membership, seed, clock and SHA-256 hashes. M2 materializes
text PDFs and paragraph/table DOCX documents, including corrupt, image-only and missing
variants. The two attachment-bearing EML alternates contain actual MIME payloads. Import
does not parse documents; extraction does. Reimporting an unchanged M1 message hydrates
its attachment location without changing its canonical identity/history. Legacy attachments
without a stored root remain blocked until the source is reimported.

Provenance is required import configuration, never a message header. The model payload
boundary denies private, unknown and mixed sources. The offline model stub raises on a
cache miss. Inherited API keys and notifier flags cannot enable networking. Tests deny
sockets, DNS and subprocesses except the exact cached, untrusted Tectonic build.
Pause persists in SQLite and blocks work at stage boundaries;
pause/resume remain available. Run records contain counts and error types, never bodies or
exception messages.

`.env.example` documents optional `INBOUND_DATA_ROOT` and `INBOUND_PERSONAL_CONTACTS`.
Environment files are not loaded automatically. A configured writable root must be on D:.
Forward-only migrations live in `inbound/migrations/`; applied migration hashes are checked.
No real mail is included. Claude alone runs imports against real data and makes commits.

M3 keeps public evidence and fictional demo evidence in separate registry scopes. `evidence import`
reads only manifest-approved CV project files and the public portfolio data; it never edits those
sources. It imports 21 approved CV projects (51 bullet variants) and 52 curated skills. A missing
portfolio project keeps its CV evidence. Tests use committed snapshots; the sole source-file test
hashes every public CV TeX file before and after a demo build. `python -m inbound.evidence.snapshot`
regenerates snapshots from the reviewed sources and fictional manifest.

`pack <opportunity_id> --demo` uses Sara Qamar's five fictional projects and replaces every identity,
education, experience, research, link and PDF metadata record. Omit `--demo` for a local public-CV
pack after importing evidence; Claude runs that real-CV check. Fixed real parts must match
`evidence/approved_fixed.yaml` hashes. Approved profiles may require Uzair's review; verification
reports that flag and whether a tailored family was available. Requirement text never supplies
CV claims. Model ranking has an interface only and is reported as **not run**.

Pack files live under `.local/packs/<id>/`: `body.tex`, generated/copy-checked parts, the named PDF,
`build.log`, `selection.json`, `verification.json` and capped `answers.txt`. Tectonic runs with
`--only-cached --untrusted`, the pre-filled `.local/tectonic-cache/cache` cache and a 120-second
timeout. A failed compilation or verification leaves a blocked pack and a failed ledger row.
Blocked JDs produce visibly labelled provisional previews, which require blocker acknowledgement
before review. A newer opportunity revision makes the prior reviewed pack stale and requires a
rebuild. `inbound.packs.build.set_status` enforces those rules; it never submits anything.

`python -m eval.pack_eval` writes `.local/reports/m3.json` and `m3.md` for the eight frozen cases,
retaining failures in the denominator. Ranking coverage uses the manifest's human support labels
and the fixed p1–p4/two-bullet/all-approved-skills baseline. These are fictional pack results, not
real-mail evaluation. `.local/reports/m3-cv-hashes.json` contains all before/after source hashes.
