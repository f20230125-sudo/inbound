# Inbound

Inbound is a personal inbox desk. M1 imports local mail exports, classifies messages with
evidence-backed rules, and reports a synthetic dev baseline. It runs offline and makes no
outward actions. Later milestones add extraction, application packs, and the desk UI.

Use the supplied Python 3.14 venv from this repository in PowerShell:

```powershell
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$env:PYTHONPYCACHEPREFIX = "$PWD\.local\pycache"
python -m synth.generate
python -m inbound import --source export --path fixtures/export_sample --provenance synthetic
python -m inbound import --source export --path fixtures/export_sample --provenance synthetic
python -m inbound import --source eml --path fixtures/eml_sample --provenance synthetic
python -m inbound triage
python -m inbound baseline
python -m inbound pause
python -m inbound resume
ruff check .
pytest
```

The first export import adds 190 messages; repeats and the five EML alternates add zero.
Each message identity is scoped by provider (`mail` for both file formats). Changed content
is counted as `changed` and appended to history; the original message remains intact.
M1 triage uses that original snapshot. Transport encoding, newline endings, byte availability,
attachment file locations, and export notes are excluded from content identity.

All runtime data, reports, and test caches default to `.local/`. The baseline writes
`.local/reports/m1.json` and `m1.md`, scoring only the 64 dev cases. Held-out and attacks are
not scored in this baseline. Urgency and admin deadline recall await M2 extraction;
M1 predictions use normal urgency. Model comparison is explicitly not run.

`synth/cases.json` is the gold authority transcribed from the frozen manifest and audit
(`r4-20261028-01`, including the P-H25 unknown stipend). It contains source definitions,
independently authored gold fields and future attachment plans. Regeneration is byte stable;
`fixtures/manifest.json` records membership, seed, clock and SHA-256 hashes. M1 includes only
attachment declarations; even the EML attachments have no PDF/DOCX payload. M2 will provide
the planned documents. Missing bytes remain `missing` in the imported M1 records.

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
