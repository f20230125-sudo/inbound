# Inbound: specification (contract for the build)

Inbound is Uzair's personal inbox desk. It triages his mail and turns each internship call into an evidence-backed application pack that he reviews and submits himself. Plan and reasoning: `D:\claude-workspace\neovara\personal-agent\PLAN.md`.

## 0. Non-negotiable rules

1. **No outward action exists in code:** no sending/drafting/archiving/deleting/labelling mail, no form access or submission, no Telegram send unless `TELEGRAM_ENABLED=1` and a token are configured by Uzair, no network call at all in tests. Gmail scope, when added later, is `gmail.readonly` only.
2. **`private/` is never read by Codex, never committed, never sent to any cloud model, never deployed.** Code reads it only at runtime on Uzair's PC. Tests use `fixtures/` (synthetic) only.
3. **Cloud model calls only on synthetic/public payloads.** Every model request goes through a `PayloadPolicy` that rejects anything whose source is `private` unless a per-field allowlist approved by Uzair is configured (empty by default). Default provider in tests and overnight: `OfflineLLM` (replay) or `FakeLLM`.
4. **Claims come only from the evidence registry.** The pack renderer writes text only from registry entries (by id) and fixed templates; model output may contain ids, orderings and short reasons, never CV text.
5. **Unknown is a value.** Every extracted field has `status ∈ {found, inferred, unknown, conflicting}` plus `source_text`. Never silently fill a missing field.
6. Everything lives on D:. Caches, temp, Tectonic output: under the repo's `.local/` (gitignored).

## 1. Stack and layout

Python 3.14 venv `.venv`; Flask app factory; SQLite (`private/inbound.sqlite` for real use, `.local/demo.sqlite` for synthetic); React 19 + Vite + TS + Tailwind 4 + shadcn/ui copied from `D:\claude-workspace\backroom\web` (same component set, neutral palette, Geist, light default with dark toggle); pytest, ruff, vitest, Playwright + axe. Reuse from Backroom (copy, then adapt): `backroom/llm/*` (cache, budget, router, Gemini structured output), `settings.py` OfflineLLM/CacheMiss pattern, Flask security headers/CSP, the Playwright/axe test harness.

```
inbound/
  inbound/            # python package
    sources/          # eml_dir.py, export_txt.py, (later) gmail_api.py
    triage/           # rules.py, model.py (synthetic path only), taxonomy.py
    extract/          # call.py (fields), deadline.py, stipend.py, roles.py, attachments.py (pdf/docx)
    evidence/         # registry.py, import_cv.py, import_projects.py, skills.py
    packs/            # rank.py, render.py, verify.py, answers.py, templates/
    ledger.py, pause.py, policy.py, digest.py, db.py, models.py, settings.py
    api/              # Flask blueprint(s)
  synth/              # generator (template families) + ground truth
  fixtures/           # generated synthetic mail (committed), evidence snapshot for tests
  eval/               # run_eval.py, metrics, results.json
  web/                # React app
  tests/
  private/            # gitignored, real data, never read by Codex
```

## 2. Data model (SQLite, forward-only SQL migrations)

- `messages(id, provider, provider_id, thread_id, received_at, sender, to, cc, bcc, subject, body_text, attachments_json, source, content_hash, imported_at)`; `source ∈ {private, synthetic}`.
- `attachments(id, message_id, filename, mime, bytes_available, text, parse_status ∈ {parsed, unsupported, unreadable, missing})`.
- `triage(message_id, category, urgency, reason, rule_id|model_version, confidence, corrected_category, corrected_at)`.
- `opportunities(id, company, city, source_thread_id, kind ∈ {ps_call, direct_apply}, status ∈ {new, preparing, needs_review, reviewed, submitted_by_me, blocked, skipped}, created_at, updated_at)`; `expired` is computed from the deadline.
- `opportunity_revisions(id, opportunity_id, message_id, fields_json, created_at)`: a forwarded reminder adds a revision, never a second opportunity.
- `fields(opportunity_id, revision_id, name, raw, normalized, status, source_text)`: name ∈ form_link, apply_link, stipend, mode, deadline, company_website, jd_location (attached|inline|absent), cv_naming_rule, internship_dates, roles.
- `roles(id, opportunity_id, title, requirements_json)`.
- `evidence_projects(id, title, stack_json, live_url, code_url, source_file, source_hash, as_of)`; `evidence_bullets(id, project_id, text_tex, text_plain, source_file, source_line, source_hash)`; `skills(id, name, aliases_json)`; `skill_evidence(skill_id, project_id, note, approved)`.
- `packs(id, opportunity_id, role_id, status, selection_json, files_json, checks_json, created_at)`.
- `runs(id, kind, started_at, finished_at, status, counts_json, model_calls, cache_hits, error)`, `settings(key, value)` (pause flag, budgets, preferences).

## 3. Triage taxonomy and rules

Categories: `ps_call`, `ps_admin`, `application_update`, `job_alert`, `academic`, `campus_notice`, `research`, `dev_ops`, `account_billing`, `personal`, `newsletter_promo`, `needs_review`.

Rules (ordered, each with an id and a reason string):
- Normalise subjects first: strip zero-width characters (U+200B-U+200D, U+FEFF), collapse whitespace, unify dashes (– — -).
- `ps_call`: sender `ps@dubai.bits-pilani.ac.in` and subject matches `^(Fwd:\s*)?Call for CV\b` (with or without "PS II – Second Semester ...").
- `application_update`: subject starts with "Update on Your Application" (any sender), LinkedIn "your application was sent to", shortlist/not shortlisted wording in the first 300 chars.
- `ps_admin`: sender `ps@` or `psd@` and not a call/update (survey, station introduction, PS to TS transfer, student information form); extract any "on or before <date>" / "by <date>" deadline.
- `job_alert`: `jobalerts-noreply@linkedin.com`, `jobs-noreply@linkedin.com` (except application updates).
- `academic`: `bitserp@bits-pilani.ac.in`, `no-reply@teams.mail.microsoft`, subjects with exam/quiz/assignment/case study/mid sem/seating, or a classmate `f20\d{6}@` sender.
- `campus_notice`: other `@dubai.bits-pilani.ac.in` / `@bits-pilani.ac.in` senders (council, hostels, director, library, facilities).
- `research`: `easychair.org`, conference subjects (`[IEEE ...]`).
- `dev_ops`: `notifications@github.com`, `notifications@vercel.com`.
- `account_billing`: receipts, invoices, subscription confirmations.
- `newsletter_promo`: changelog/updates/marketing senders; promotions.
- `personal`: senders in a configurable personal-contacts list.
- otherwise `needs_review` (private path). The synthetic path may also run a model tier for comparison only.

Urgency: `high` if a deadline is within 48 h of now or the category is ps_call/ps_admin with a future deadline; `normal`; `low` for job_alert/newsletter_promo/dev_ops successes.

## 4. Call extraction (rules first)

Real call template (structure only; quirks the parser must handle):
- Subject: `Call for CV - PS II – Second Semester 2026-2027 – <Company>,<City>[ - <Role>]`, sometimes without the "PS II ..." part (`Call for CV - <Company>,<City>`), sometimes `Fwd:`; company names may contain zero-width spaces and commas; city may be a free-zone code (`DSO`) while the body says `Dubai`.
- Body (Gmail plain-text conversion adds stray `*`): first line repeats the title; "<Company> has expressed their interest to hire Students for PS II ..."; a form link line `*https://forms.gle/XXXX <https://forms.gle/XXXX>*`; optional `*Company Website:* <url>`; `*Stipend*` then a bullet line `· AED2500 per month` / `· AED 2,000 per month` / `· AED2000/- per month` / `· between INR 10,000 to 15,000 per month.`; `*Mode of Internship:* In person|In-person|Hybrid|Remote`; `*Job Title & JD*` / `*JD*` / `*Job Title & Expected Skills*` followed by `· Attached`, or inline text (sections, numbered roles `*1. Title*` each with `Expected Skills:` bullets), or absent; optional `Note : Please ensure that the CV is named as - ...` (naming rule); `*Conditions:*` bullets, sometimes with internship dates ("from 4 January 2027 to 9 July 2027", "will commence on 11 January 2027"); `*CV Submission Deadline**: **: 08**:00AM , 28 October 2026*`; signature block.
- Variants: direct-apply calls with an external careers link, no form, no stipend, no deadline (`kind = direct_apply`); forwarded reminders whose new deadline is relative ("on or before 08:00AM tomorrow") → resolve relative to the forward's sent time in Asia/Dubai and record `status=inferred` with the raw text; attachments PDF or DOCX.

Fields: see §2. Deadline parsing: tolerate asterisks/extra colons, `08:00AM`, `8:00 AM`, `0800 hrs`, day-month-year with month names; timezone Asia/Dubai unless stated; store raw text; flag `past_at_receipt` if before the email's received time; a later revision updates the opportunity and records the change. Stipend: `{currency, min, max, period, raw}`; never convert currencies. Roles: one role from the subject/JD title, or several from numbered headings; each role keeps its requirement bullets. Attachments: PDF via pdfplumber, DOCX via python-docx (paragraphs + tables); unreadable/missing ⇒ `jd_location=attached` with `parse_status` not `parsed` ⇒ opportunity `blocked` until reviewed (pack still possible from title).

## 5. Evidence registry

- Import verified CV bullets from `D:\claude-workspace\cv-msd\fresh\*-body.tex` (`\resumeItem{...}` under each `\resumeProjectHeading`), keeping the LaTeX text, a plain-text version, file, line and sha256. Project headings give title, stack, links (resolve `\rxlive`-style macros from `preamble.tex`).
- Import project facts/stack/links from `D:\claude-workspace\portfolio-os\src\knowledge\projects.ts` (parse the object literals; read-only).
- The same project from several CV files: keep all bullet variants, dedupe exact duplicates, mark the newest file's version preferred; never merge text.
- Skills: a curated `evidence/skills.yaml` (committed) mapping skill → aliases → projects with a one-line note of where the evidence is (e.g. `SQL window functions → rx-market-pulse (sql/04, sql/08 ROW_NUMBER, LAG); property-data-warehouse (LEAD, LAG, RANK)`). Codex drafts it from the CV skills sections; Claude verifies entries; entries default `approved: false` until verified.
- Snapshot for tests: `fixtures/evidence_snapshot.json` (generated from the real files; contains only already-public CV text).

## 6. Pack builder

- **Rank (deterministic):** requirements (role bullets / JD lines) → tokens + phrase synonyms from `skills.yaml` → score bullets with BM25 + skill hits; choose 4 projects maximising requirement coverage with diminishing returns per project; 1-3 bullets per project within a line budget; an "Also built" line from remaining projects with links. Output: `selection = {projects:[{id, bullets:[ids], why:[requirement ids]}], skills:[ids], gaps:[requirements without evidence]}`.
- **Rank (model, synthetic path only):** same output schema, ids only; compared in eval.
- **Render:** copy `preamble.tex`, `head.tex`, `tail.tex` from `cv-msd/fresh` into the pack folder at build time (read-only source); write `body.tex` (profile from a small set of approved profile templates in `packs/templates/profiles.yaml` with slots filled only by role title/company and approved skill names) and `skills.tex` (skill lines grouped by category, only approved skills); escape all inserted text (`& % $ # _ { } ~ ^ \`).
- **Build:** `D:\codex\tools\tectonic\tectonic.exe -X compile` inside `packs/<pack_id>/` (cache dir under `.local/`), timeout 120 s, no shell interpolation of model text.
- **Verify:** pages = 1 (pdftotext form-feed count or pdfplumber), no `Overfull` in the log, identity line present, every rendered bullet maps to a registry id (compare extracted PDF text to the selected bullets' plain text), every listed skill approved, filename = form rule (`2023A7PS0125U-Mohammad Uzair Khan-<Company>.pdf` by default; a call-specific naming rule overrides), links listed for a later online check (no network now).
- **Answers:** for each selected project: purpose (registry tagline/pitch), technologies (stack), challenge + fix (registry `decisions`/README "what broke" text if present; else a question for Uzair). Plain text, copyable, length-capped.

## 7. Desk (Flask API + React)

Pages: **Today** (digest: deadlines next 48 h, new calls, admin tasks, stale-snapshot banner, last import time), **Inbox** (table with category chips, reason, source line, one-click correction), **Applications** (board by status, countdown, Expired badge), **Opportunity** (fields with source text and status, roles, requirement → evidence table for every role, gaps, attachment status, Open form link as a plain link), **Pack** (PDF preview, selection with reasons, verification report, answers with copy buttons, Mark reviewed / Mark submitted by me / Skip), **Runs** (ledger), **Settings** (Pause toggle, budgets, preferences, payload policy shown read-only, data paths). Read-only API for the public replay mode (`APP_MODE=replay`).

API (JSON): `GET /api/today`, `GET /api/messages?category=`, `POST /api/messages/<id>/category` (local mode only), `GET /api/opportunities`, `GET /api/opportunities/<id>`, `POST /api/opportunities/<id>/pack` (local mode; runs the pipeline), `GET /api/packs/<id>`, `GET /api/packs/<id>/pdf`, `POST /api/packs/<id>/status`, `GET /api/runs`, `GET/POST /api/settings` (local mode), `POST /api/import` (local mode: runs a source import). Every POST checks Pause and local mode; CSRF token for POSTs; bind 127.0.0.1 only.

CLI: `python -m inbound import --source export|eml --path ...`, `python -m inbound triage`, `python -m inbound extract`, `python -m inbound pack <opportunity_id>`, `python -m inbound digest`, `python -m inbound eval`.

## 8. Synthetic data (`synth/`)

Seeded; fictional applicant "Sara Ahmed" style identity for public packs (separate evidence snapshot `fixtures/demo_evidence.json` with fictional projects) **and** Uzair's real public CV evidence for local packs. Template families written independently (not one template with names swapped): A = PS-office template as in §4 with its quirks; B = forwarded reminder with relative deadline; C = direct-apply careers link; D = multi-role inline JD; E = JD as PDF; F = JD as DOCX; G = admin notices with "on or before" deadlines; H = application updates; I = other categories (alerts, academic, campus, dev, billing, promo); J = adversarial: instructions in the body to change the deadline, add a skill, mark submitted, forward data, hide the call (white text / HTML comment equivalents in plain text), look-alike sender `ps@dubai-bits-pilani.ac.in`. Counts: 24 dev + 36 held-out PS-related + 10 adversarial + ~120 other messages; ground truth JSON for every field and category.

## 9. Evaluation (`eval/run_eval.py` → `eval/results.json`, synthetic only in the repo; private run writes `private/results_private.json`)

Triage confusion matrix + macro-F1 + ps_call recall + ps_admin deadline recall; extraction per-field accuracy and full-record accuracy (missing counts wrong; abstentions reported separately); deadline exact-match and count of silently wrong deadlines (target 0); pack checks pass rate on a stated subset; claim provenance rate; safety: forbidden-action attempts (structurally 0), deadline/skill corruption under attack, ps_call suppression under attack; timings. Baselines: (1) rules + fixed general CV, (2) rules + deterministic ranking, (3) + model (synthetic only, after quota reset).

## 10. Safety and privacy tests (must exist)

No module imports an SMTP/HTTP-send capability except `sources/gmail_api.py` (read-only, disabled by default) and an opt-in Telegram notifier; a test greps the package for forbidden calls; PayloadPolicy blocks private payloads; Pause blocks pack/import POSTs and is rechecked inside the pipeline; LaTeX injection strings in a JD never reach the `.tex` unescaped; adversarial fixtures cannot change deadlines/skills; `private/` absent from git index and from the web build; server binds 127.0.0.1.

## 11. Milestone gates (Claude checks each)

- **M1** repo, venv, ruff, pytest; synth generator + ground truth; `eml_dir` and `export_txt` sources (format in §12); taxonomy + rules triage; import idempotent; tests. Gate: counts match ground truth, triage rules baseline on synthetic dev reported, `git status` shows no private files.
- **M2** extraction (fields, deadlines, stipend, roles, attachments PDF/DOCX, revisions). Gate: every §4 variant has a passing test; per-field baseline on synthetic dev.
- **M3** evidence registry import + skills.yaml draft + deterministic ranking + renderer + verify + answers. Gate: a synthetic pack builds (1 page, 0 overfull, all bullets traced); a local pack for a sample real JD (Claude runs this, not Codex) builds; `cv-msd/fresh` unchanged (hash check).
- **M4** Flask API + React desk + ledger + Pause + digest + eval harness + Playwright/axe. Gate: end-to-end on synthetic data in the browser; all tests green.

## 12. `export_txt` format (`inbound-export-v1`)

One UTF-8 `.txt` per message: header lines `key: value` for `id, thread_id, date (ISO 8601 UTC), from, to, cc, bcc, subject, labels, attachments (name|mime; name|mime), body_exported`, a line `---`, then the body. Empty values allowed. `fixtures/export_sample/` must contain synthetic files in this exact format for tests.

## 13. Amendment 1 (frozen 28 Oct 2026, 00:10 Dubai, after Codex's round-3 review)

Where this section conflicts with §0-§12, this section wins. M1-M4 run on **28 October 2026, 02:30-09:00 Dubai**, offline.

**Sources and export.** Overnight sources are `export_txt` (`inbound-export-v1`) and `eml_dir` only. Export header additions: `date` is the message's sent time (ISO 8601 UTC) and is also used as `received_at` unless a `received_at` line is present; `attachments` entries are `name|mime|bytes_path` where `bytes_path` is optional and relative to the import root (reject absolute paths, `..`, Windows reserved names; missing bytes ⇒ `parse_status=missing`); `body_exported` is a free-text note, and a separate boolean `body_complete: true|false` says whether the body is complete. Provenance (`private`/`synthetic`) is set by import configuration, never by message content; unknown or mixed provenance fails closed.

**Opportunity matching and revisions.** Process messages in sent-time order. A message joins an existing opportunity if it shares the provider thread id, or its form/apply link, or its subject equals the existing call's subject after removing `Fwd:`/`Re:` and normalising. Never merge on company name alone; a probable but unproven match becomes a merge suggestion for review. Extract the current message separately from quoted history. A newer explicit amendment (e.g. "on or before 08:00AM tomorrow", resolved from the newer message's sent time in Asia/Dubai, `status=inferred`) supersedes the effective deadline; otherwise competing values are `conflicting` with every candidate's quote kept. Company and city are provenance-bearing fields; `DSO` (subject) and `Dubai` (body) are both kept as observed values, not a conflict. Roles, packs and admin deadlines bind to a revision/message; a new revision invalidates a reviewed pack (status back to needs_review).

**Pause.** Persisted in `settings`; blocks new imports, extraction and pack work via CLI and API, is checked between stages and before every retry; the pause/resume control itself is exempt. CSRF token on all POSTs; Host must be 127.0.0.1/localhost; server binds 127.0.0.1.

**Networking.** Overnight there is **no** external networking code and no notifier implementation. Tests deny sockets/DNS (a pytest fixture) and subprocesses except the Tectonic call in M3 (with downloads disabled and `-Z`/shell escape off). The future Gemini transport and Telegram notifier will be explicit exceptions behind `PayloadPolicy` and a settings flag that only the UI (Uzair) can set; environment variables alone never enable them.

**Triage precedence.** First matching rule wins; application-update rules precede job alerts; exact sender mailbox/domain comparison (look-alikes such as `ps@dubai-bits-pilani.ac.in` never match). Urgency: `high` = a future deadline within 48 h; `normal` otherwise; date-only deadlines stay date-only (no invented time) and are shown as such.

**Blocked JDs.** A pack may be built as an explicitly labelled *provisional preview*; it cannot be marked reviewed until the blocker is acknowledged. A missing deadline never means "not expired".

**Scope cuts accepted (in this order):** model comparison deferred (interface + "not run" result only; FakeLLM is contract testing, not evidence); UI = three views: **Today/Inbox**, **Opportunity/Pack**, **Settings/Runs** (status via selects, no drag and drop); 4-6 approved projects + 1 approved profile; answers from approved tagline/stack/decisions only (missing challenge ⇒ a question); one recommended-role pack, other roles get coverage + gaps; attachments: text PDFs and DOCX paragraphs/tables only. Policy, persisted Pause, import ledger and the triage baseline move into **M1**.

**Backroom reuse.** Copy narrowly: `llm/store.py` cache/completion primitives and `budget.py` (later, not M1); rewrite settings so offline mode constructs no live provider and cache misses fail closed; never copy `.env`, databases, caches, results, deployment config, Postgres code or business logic. Web: copy `src/components/ui/`, `src/lib/utils.ts`, theme CSS, Geist dependency and build config; rewrite routes, client, types and pages. Security headers ideas from `backroom/api/security.py` plus a real CSRF token and Host check. Playwright: adapt config and the axe/console/overflow helpers; no `BASE_URL` override.

**CV assembly facts (for M3).** `head.tex` opens the document; `tail.tex` holds Experience and Research; the skills part closes the document; keep that order. Education, experience, research, certification and profile text also need approved provenance (an `approved_fixed.yaml`). `projects.ts` contains `${GH}` template strings and nested objects: parse with a constrained parser or use a reviewed JSON snapshot, never eval or a loose regex; Backroom, Order Desk and LoopDesk/ScopeDesk/FollowDesk are not in `projects.ts`, so CV evidence must not be dropped when portfolio data is missing. "Preferred version" of a bullet is defined by a reviewed manifest (`evidence/approved_sources.yaml`, written by Claude before M3), not file times. Parse nested braces; skip "Also built" headings.

**Safety additions.** Runtime egress denial (sockets, DNS, subprocess) in tests; synthetic canary strings that must never appear in replay APIs, logs, caches, PDF metadata or traces; tests that use private-like data only in a temporary directory, never the real `private/`; reject unsafe URL schemes, oversized files (>10 MB), DOCX zip bombs (max uncompressed 50 MB, max 2,000 entries); replay mode rejects every mutation; a failed build never leaves a successful pack record; fictional demo packs replace identity, education, experience, research, links and PDF metadata entirely.

**Evaluation amendments.** Dataset frozen at exactly **190 synthetic messages**: 24 dev + 36 held-out PS-related (calls, reminders, admin, updates), 120 others split 40 dev / 80 held-out, 10 adversarial. Held-out uses wording/layout variants and whole reminder threads not present in dev. Gold labels come from `synth/cases.json` (case definitions), never from parser code; Claude audits them. Field accuracy is computed over applicable fields with unknown/conflicting correctness explicit; populated-field accuracy reported separately. A *silently wrong deadline* = an incorrect effective deadline shown without an uncertainty/blocking flag. Ranking quality = human-labelled requirement support vs the fixed general CV (M3/M4). Attacks that append instructions are scored separately from attacks that alter source facts (conflict/abstention is acceptable for the latter). Freeze the 8 pack cases before running; failures stay in the denominator; cold vs warm timings separate; replay latency is never presented as a model run.

**Private runs.** Codex never reads `private/`. Claude alone runs the pipeline on the real export and reports only sanitized aggregates (counts, pass/fail) to Codex and in the repo.

**M1 deliverables and gate:** as listed in `D:\claude-workspace\neovara\personal-agent\codex-round3.md` §5 (files, 190 fixtures with 64/116/10 export files plus 5 EML edge cases, tests `test_settings/sources/import/triage/synth/policy/pause/ledger/egress/baseline`). Gate: ruff + pytest pass; offline CLI imports 190 then 0 on repeat; dev baseline with confusion matrix and denominators; no held-out tuning; git index has no private/local artifacts.

## 14. Amendment 2 (28 Oct 2026, 03:20 Dubai, after M2)

**Opportunity grouping.** Equal normalised subjects join only when the messages do not carry *different* explicit form/apply links. Same thread id or the same link always joins. Equal subject + different links ⇒ separate opportunities plus a `merge_suggestion` (reason `same_subject_different_link`) for Uzair to review. Rationale: a silent join would mix two calls' deadlines; a suggestion costs one click. This reproduces the frozen manifest groups.

**Real-format variants (from Claude's local run on Uzair's real export; described here with fictional names only).** Rules must also handle:
1. *Direct apply without a form:* subject `Call for CV - <Company>,<City>` (no "PS II" part); body says `please apply directly through the link below` (or "apply directly", "careers page") followed by a bare `https://` URL on its own line that is not `forms.gle`/`docs.google.com/forms`, possibly long with `%`-encoded query strings and possibly wrapped across lines. ⇒ `kind=direct_apply`, `apply_link` found (full URL, unwrapped), form_link/stipend/deadline unknown.
2. *Company and role with no city:* subject `... – <Company>- <Role>` (hyphen glued to the company, space before the role) and body opening `*<Company>*- *<Role>*,has expressed their interest ...`. ⇒ company found, role found from the subject, city unknown (never guessed).
3. *Company — City - Role:* subject `... – <Company> — <City> - <Role>` (em dash between company and city, hyphen before the role) and body `*<Company> — <City>, *has expressed ...`. ⇒ company, city and role all found. Dash unification must not lose which separator was which before splitting.
4. *Company from the body:* when the subject split is ambiguous, the body sentence `<X> has expressed their interest` (asterisks/commas tolerated) confirms the company; if subject and body disagree, keep both as observations, do not guess.
These go in as unit tests with fictional names (not added to the frozen 190; the dataset stays frozen). Real-mail results are reported separately and labelled "rules tuned on these messages".

## 15. Amendment 3 (28 Oct 2026, 06:20 Dubai): daily-use features after the first real morning

Agreed with Codex (planning round r6). Built in this order; each keeps Pause, CSRF, Host, replay and stale-write protections, staged-import publication, and the no-outward-action rule.

1. **Outside application record (M7).** Uzair can record "I applied outside Inbound" on any opportunity (no pack, blocked JD or expired deadline allowed): explicit human declaration, applied-at time, recorded-at time, optional note and optional follow-up date (a local task only). It never marks a pack reviewed. Corrections append history; nothing is deleted. Re-imports preserve it. This narrows DESIGN's reviewed-pack prerequisite for this one action only.
2. **Live deadline correctness (M7).** The open desk regroups Today every minute and on tab return, using elapsed wall time from a server-time anchor; the frozen synthetic clock stays frozen in demo/replay; unknown/conflicting deadlines never get countdowns.
3. **Missing-JD recovery (M8).** On a blocked opportunity Uzair selects the missing attachment and supplies a local PDF/DOCX (upload from the desk, or a path under the configured data root). Inbound previews the parsed text; he confirms; then requirements are re-extracted, coverage rebuilt and any reviewed pack invalidated. File hash and provenance are stored; history kept; a failed parse keeps the blocker. Never auto-link by filename.
4. **Application-update linking (M9).** An `application_update` message can be linked (manually, with a searchable selector) to an opportunity with a confirmed outcome (acknowledgement, shortlisted, not shortlisted, other); unlink/relink keep history; an update never establishes that Uzair submitted.
5. **Deadline calendar file (M9, if time).** Download one supported timed deadline as `.ics` (stable UID, version bumps on amendment, escaped text); unknown/conflicting deadlines cannot export.

Backlog (not now): preference fit, tailoring-vs-general-CV comparison with fresh labels, weekly review page, live model comparison.
