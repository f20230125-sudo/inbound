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
| GET `/api/messages?category=ps_call` | Summary array without bodies; effective and original categories, original rule/reason/quote, append-only correction history, fields and opportunity link |
| GET `/api/messages/<id>` | Source body on demand; subject, sender, sent time, completeness and provenance; read-only while paused, same replay sanitization and database exclusion |
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
| GET `/api/agent/state` | Source-linked briefing, separate call/sorting counts, three prioritized decisions and factual Scout state |
| GET `/api/agent/steps` | Most recent 100 journal steps; `?after=<id>` instead returns ascending catch-up with `after` and `has_more` |
| GET `/api/agent/stream` | Same-origin SSE; journal IDs, `Last-Event-ID` resume (or initial `?after=<id>`), unstored 15-second heartbeats |
| GET `/api/agent/steps?replay=last` | Read-only recorded check, `label`, `recording_id` and `through`; subsequent pages use `?replay=<recording_id>&through=<through>&after=<id>` |
| GET `/api/version` | Fallback change token including domain generation and visible journal cursor |
| POST `/api/agent/alerts` | Typed local browser-alert receipt: `opportunity_id`, `kind` (`eligible`, `requested`, `suppressed`), `alert_type` (`new_call`, `deadline`), allowlisted `reason`; normal POST guards apply |

M12 journal facts never contain mail text, exception messages, notes or skip reasons.
Successful staged results publish with the snapshot; progress and failures survive a
failed import. Content generation triggers detect concurrent authoritative changes;
run/journal telemetry does not invalidate imports. Pause is checked separately.
Replay mode filters private journal events even when no private message remains.
Recorded playback performs reads only and suspends browser notifications in that view.

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

M7 adds `POST /api/opportunities/<id>/applied` for an application the human made
outside Inbound. Its JSON body requires `applied_at` (ISO time with timezone),
`human_submission: true`, `expected_revision_id`, and `expected_activity_id`
(null for the first record); `note` (up to 1000 characters) and `follow_up`
(`YYYY-MM-DD`, a local task only) are optional. Read the expected IDs from the
opportunity detail, including `outside_application.id`. Stale writes return 409;
an exact retry returns the existing record. Corrections append `applied_outside`
events to `review_history`, including both applied and recorded times and the
preceding activity ID. No pack is required or marked reviewed, and the pipeline
status and JD/deadline warnings remain intact. Today shows the latest declarations
in `outside_applications`, ordered by follow-up date, instead of active call groups.
These timeline rows live in the existing `review_events` table, so no schema
migration or staged-import table publication change is required.

The equivalent CLI is `python -m inbound applied <id> --at <ISO>
[--note ...] [--follow-up YYYY-MM-DD] --i-applied-myself`. It checks local mode,
Pause, active imports and the revision/activity versions before appending.

The desk anchors to the server clock, advances by browser elapsed wall time, and
reloads Today every minute and on visible tab return. Demo/replay clocks remain
frozen. The browser fixture alone enables `TEST_CLOCK=True`; with `DEMO=True`,
`POST /api/test/clock` accepts `{ "now": "<ISO time with timezone>" }` to replace
the frozen clock. It has the normal POST guards and returns 404 unless both
configuration flags are enabled. There is no environment switch for this hook.

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

M4b presentation contract fixes:

- Settings includes `source_format` (`export` or `eml`) from trusted configuration.
  Import still accepts `{}` and cannot be pointed at another folder from the browser.
- Today entries include `display_title`, effective `city`, and `attention_reason`.
  Calls use effective company/role/city; unknown company falls back to the normalized
  subject. Original subject remains available as source evidence. The CLI uses the
  same title and explicit blocker/expiry/conflict reason.
- GET `/api/packs/<id>/preview` returns an actual PNG of the PDF's first page. It uses
  exactly the download artifact confinement guard, renders locally with the installed
  PDFium dependency, and serializes rasterization. It adds no subprocess or transport.
  This supports mobile and headless browsers without relying on a native PDF plugin;
  the restrictive page CSP stays intact. The HTML evidence remains available.

Learning is local and explicit:

- `GET /api/learning` returns visible rules with versions, scopes, examples and
  recent uses. `GET /api/learning/review` returns grouped unfamiliar senders and
  the unresolved/stored totals. Neither endpoint writes.
- Category corrections return `learning_rule`: a suggested exact-mailbox rule
  with an exact normalized subject. Skip responses return a suggested preference
  for supported reasons; the reason itself remains in opportunity history.
- `POST /api/learning/sender` accepts `message_id`, `category`, `subject` (literal
  normalized equality, or null). Multiple stored subjects require a condition.
- `POST /api/learning/preference` accepts a supported `effect` and suggests it.
  `POST /api/learning/instruction` accepts a supported explicit `instruction` and
  activates it. Supported effects: `prefer_remote`, `prefer_hybrid`,
  `prefer_in_person`, `avoid_relocation`. Prose memories are not executable rules.
- `POST /api/learning/<id>` accepts `action: activate|undo`, `expected_version`.
  Activation applies to future mail; Undo leaves original actions and past packs.
- `GET /api/learning/<id>/preview` returns counts, examples and a token. Separate
  `POST /api/learning/<id>/reprocess` requires `expected_version`, `expected_token`.
  A content change invalidates the preview. Reprocessing changes categories only,
  preserves manual corrections and never rebuilds opportunities or packs.

All mutation guards apply, including a second Pause/import check inside the write
transaction. Replay excludes private rules, examples and uses. Learned categories
cannot authorize a sender to create PS opportunities. Decision urgency precedes
preference fit; current source facts precede memory. Imported memory supports an
optional scalar `title`; display falls back to the description's first clause,
then the humanised slug, without changing stable IDs.
