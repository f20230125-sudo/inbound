# Inbound

Inbound is a personal inbox desk. M1 imports local mail exports and classifies messages.
M2 extracts evidence-bearing fields, bounded PDF/DOCX JDs and opportunity revisions.
It runs offline and makes no outward actions. Application packs and the desk UI are later work.

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
python -m inbound pause
python -m inbound resume
ruff check .
pytest --basetemp=.local/pytest-m2
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
packs through a table-presence hook; pack building is not implemented in M2.

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
sockets, DNS and subprocesses. Pause persists in SQLite and blocks work at stage boundaries;
pause/resume remain available. Run records contain counts and error types, never bodies or
exception messages.

`.env.example` documents optional `INBOUND_DATA_ROOT` and `INBOUND_PERSONAL_CONTACTS`.
Environment files are not loaded automatically. A configured writable root must be on D:.
Forward-only migrations live in `inbound/migrations/`; applied migration hashes are checked.
No real mail is included. Claude alone runs imports against real data and makes commits.
