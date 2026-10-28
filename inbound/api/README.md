# M4a desk contract

`inbound.api.create_app(config=None)` serves JSON beneath `/api` and the built SPA
from `web/dist`. M4a does not build or modify that directory. Run
`python -m inbound demo`, then `python -m inbound serve`. The CLI fixes the bind
address to `127.0.0.1:5000`, disables the debugger and reloader, and offers no host override.

The factory accepts `SETTINGS` (an `inbound.settings.Settings` instance),
`APP_MODE` (`local` or `replay`), `IMPORT_ROOT`, `SOURCE_FORMAT` (`export` or `eml`),
`SOURCE_PROVENANCE` (`synthetic` or `private`), `DEMO`, and an optional callable `CLOCK`.
The production defaults use `.local/demo.sqlite` and the synthetic export fixtures.
Environment configuration supports `APP_MODE`, `INBOUND_DATA_ROOT`,
`INBOUND_IMPORT_ROOT`, `INBOUND_SOURCE_FORMAT`, and `INBOUND_SOURCE_PROVENANCE`.
No environment value enables a network provider.

First GET `/api/settings` in the same browser session and origin used for writes.
Local responses include `csrf_token`; send it as `X-CSRF-Token` on every POST.
The session cookie is HTTP-only and SameSite Strict. Allowed Hosts are `localhost`
and `127.0.0.1`, optionally with a valid port. No CORS permission is granted.
Replay omits the token, returns synthetic relative paths, rejects every POST with
405, and refuses databases containing non-synthetic messages or non-demo packs.

All POST bodies are JSON objects. Errors are JSON with `error` and, where useful,
`message`. Missing resources return 404, invalid bodies 400, failed Host/CSRF checks
403, and paused, stale, blocked or conflicting operations 409. Exception details,
source paths and bodies are not included in background errors.

| Endpoint | Request / response |
|---|---|
| GET `/api/settings` | Mode, Pause, capabilities, zero disabled budgets, payload policy, configured paths, clock, timezone; CSRF in local mode only |
| POST `/api/settings` | `{ "paused": true }` or false; sole editable setting in the offline build |
| GET `/api/today` | `snapshot`, `attention`, `deadlines_48h`, `date_only`, `uncertain_deadlines`, `new_calls`, `admin_tasks`, Pause and clock |
| GET `/api/messages?category=ps_call` | Array; effective and original categories, original rule/reason/quote, append-only correction history, source text, fields and opportunity link |
| POST `/api/messages/<id>/category` | `{ "category": "academic" }`; records another correction, including Undo; returns effective and previous categories |
| GET `/api/opportunities` | Array of stored opportunity states with effective fields and revision IDs |
| GET `/api/opportunities/<id>` | Full fields and conflict candidates, revisions, source bodies, sent-time anchors, attachment locations, roles/coverage/evidence, packs and human-event history |
| POST `/api/opportunities/<id>/status` | `{ "status": "skipped", "reason": "optional" }` or `{ "status": "undo_skip" }`; Undo restores the preceding workflow state, or needs_review if the revision changed |
| POST `/api/opportunities/<id>/pack` | `{}`; returns 202 `{ "run_id": 123 }` |
| GET `/api/packs/<id>` | Selection, verification, approved evidence, answers with counts/provenance, filename, `pdf_url`, revision and human-event history; no raw artifact paths |
| GET `/api/packs/<id>/pdf` | PDF from this pack's directory beneath the configured data root; traversal and resolved symlink escapes return 404 |
| POST `/api/packs/<id>/status` | Review/submission body below |
| POST `/api/import` | `{}`; source folder/format/provenance come from trusted configuration; returns 202 with run ID |
| GET `/api/runs` | Array ordered newest first, with run ID, result, current/last stage, counts, duration, related IDs, execution type and sanitized error class |

Review body:

```json
{
  "status": "reviewed",
  "expected_revision_id": 12,
  "expected_pack_id": "returned-pack-id",
  "acknowledge_blocker": true
}
```

Acknowledgement is required for a provisional JD blocker, remains bound to the
pack/revision/blocker in event history, and does not remove the warning. A deadline
conflict cannot be acknowledged away. Required verification must have passed.
Only the current revision and latest pack can be reviewed; review is blocked while
another build for that opportunity is active. Previous artifacts remain readable.

Submission uses the same expected IDs, `"status": "submitted_by_me"`, and
`"human_submission": true`. It requires the current reviewed pack. This records
the human's declaration and performs no external action. Pipeline statuses cannot
be manufactured through either status endpoint.

Import runs through import, triage, extraction, provenance indexing and snapshot
publication. Work stages run in a temporary local SQLite copy; publication is one
transaction. Failure or Pause leaves the last successful data and snapshot intact.
Pause and the live ledger remain writable between stages. Import excludes other
writes until it finishes; the Pause control remains available. Concurrent local
database changes are detected before publication and require an explicit retry.
Duplicate imports and duplicate builds for an opportunity return 409.

`snapshot` includes `version`, `imported_at`, `latest_message_at`, `run_id`,
`stale`, and `latest_import_failure`. The latest-message timestamp describes that
import, not mailbox completeness. Staleness means over 12 hours old or an earlier
Dubai calendar day. Date-only deadlines are never coerced into the timed list.

Jobs run in a bounded in-process executor. Poll `/api/runs` every five seconds
while the observed run is running; its `pack_id` appears only after a successful
build. There is no automatic retry or durable process-restart resumption. Tests
can use `ASYNC_WORK=False` to execute the same worker synchronously without a listener.

Inbox filters other than category, and run filters, are client-side for this
190-message dataset. Source strings are plain text, never HTML. External form and
application URLs are browser anchors only; no endpoint fetches or submits them.
