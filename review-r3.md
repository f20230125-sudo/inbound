**The spec needs a small contract patch before M1.** The main blockers are the export format, revision semantics, evidence boundaries, and offline prerequisites. I read the permitted sources; I did not access or enumerate `inbound\private`. No files changed.

**1. Ambiguities and exact proposed resolutions**

| Issue | Resolution to freeze |
|---|---|
| PLAN says `json_export`; SPEC requires `export_txt`. | SPEC wins: overnight supports `inbound-export-v1` and EML only. Claude supplies the actual exporter. |
| Export `date` does not distinguish sent/received time; “tomorrow” requires sent time. Attachments have metadata but no byte location. | Add `sent_at`, `received_at`, and attachment IDs with relative paths under the configured import root. Reject traversal. Missing sent time → relative deadline `unknown`; missing bytes → `missing`. Define `body_exported` as a Boolean completeness flag. |
| “A forwarded reminder … never a second opportunity” lacks a matching rule. Same company can issue distinct calls. | Match explicit references/provider thread plus intake; otherwise propose a merge for review. Never merge on company alone. Process chronologically by message time, not import order. |
| Revision precedence and conflicting deadlines are undefined. | Extract the current message separately from quoted history. A newer explicit amendment supersedes the deadline; unexplained competing values remain `conflicting`. Store each candidate’s quote and source. Revision changes invalidate pack review. |
| Company/city lack field provenance; roles lack revision ownership; admin tasks have no clear storage. | Add company/city to provenance-bearing fields, bind roles and packs to a revision, and store admin deadlines against their source message. Keep `DSO` and `Dubai` as distinct observed values without declaring them contradictory. |
| Every POST checks Pause, including the POST needed to resume. | Exempt only authenticated pause/resume control. Pause blocks new pipeline work through both CLI and API, persists across restart, and is checked between stages and before every retry. |
| HTTP capability prohibition conflicts with the required Gemini adapter; Telegram environment flags contradict chat approval. | Overnight: **no external networking or notifier implementation**. Later provider transport gets an explicit exception behind policy. Environment variables alone never authorize Telegram. Unit tests deny networking; browser tests permit only their exact loopback origins. |
| Triage urgency and precedence are ambiguous. | First matching rule wins; application-update exceptions precede job alerts. Exact sender mailbox/domain comparisons only. `high` means a future deadline within 48 hours; later deadlines are normal. Date-only deadlines stay unresolved rather than inventing a time. |
| An unreadable JD is “blocked” but a pack remains possible. | Allow an explicitly labelled provisional preview; prohibit marking it reviewed until the blocker is acknowledged. Missing deadline never means “not expired.” |
| Frozen SPEC versus PLAN disagreements. | SPEC governs implementation; amend PLAN’s adapter and private-pack gate accordingly. Claude alone runs private cases and reports aggregate gate results. |

**2. Scope to simplify, in order**

The existing cut list mostly removes work already deferred. These cuts affect tonight’s actual workload:

1. **Defer the entire model comparison implementation.** Keep an interface and explicit “not run” result; FakeLLM is contract testing, not evaluation evidence.
2. **Replace seven desk pages and drag-and-drop board with three views:** inbox/today, opportunity/pack, settings/runs. Status changes can be selects.
3. **Start with four to six approved projects and one approved profile.** Keep registry import extensible; defer broad coverage, “Also built,” and generalized CV parsing.
4. **Answers use approved tagline, stack, and decisions only.** Missing challenge/fix becomes a question. No README discovery tonight.
5. **One recommended-role pack.** Other roles get requirement coverage and gaps; defer polished explanations.
6. **Support only supplied attachment fixtures:** text PDFs and DOCX paragraphs/tables. No OCR, images, nested archives, or general document repair.

Move policy, persisted Pause, import ledger, and the baseline reporter into M1. Leaving all safety and evaluation integration until M4 creates a late architectural rewrite.

**3. Backroom and CV reuse: copy narrowly**

- **LLM:** adapt `llm/store.py`’s completion/cache primitives, `budget.py`, and router contracts later. Rewrite `settings.py`: `build_llm()` currently defaults to online, and even its offline branch constructs a Gemini HTTP client. Offline must instantiate no live provider; cache misses must fail closed.
- **Cache/budget:** replace Backroom’s committed `cache/llm.sqlite` default with explicit isolated paths. Do not copy cache contents. SQLite connections need request/thread ownership; budget check-and-reserve is not atomic across workers. Use one worker tonight.
- **Policy placement:** run policy before cache lookup, logging, provider calls, and retries. Backroom’s router has no such boundary. Provider error bodies can contain sensitive content; do not log them verbatim.
- **Web:** copy `src/components/ui/`, `src/lib/utils.ts`, theme CSS, local Geist dependency, and relevant build configuration. Rewrite app routes, API client, domain types, pages, and fixtures.
- **Security:** reuse header-setting ideas from `api/security.py`; add actual CSRF protection and loopback Host validation. Its current origin checks are not the specified CSRF token.
- **Harness:** adapt `playwright.config.ts` and `web/tests/e2e*`; remove arbitrary `BASE_URL`, Backroom pipeline imports, domain assertions, and shared mutable fixture state.
- **Do not copy:** `.env`, databases, caches, public snapshots, results, deployment configuration, PostgreSQL plumbing, or Backroom business logic.

Actual CV traps:

- `head.tex` opens the document; `tail.tex` contains experience/research claims; the skills files close the document. Generated assembly must preserve that structure.
- Those fixed claims, education, certification, and profile text need approved provenance too—not just project bullets.
- `projects.ts` contains template strings such as `${GH}`, nested objects, and older facts. Use a constrained parser or reviewed snapshot, never `eval` or a loose object regex.
- Backroom, Order Desk, and LoopDesk/ScopeDesk/FollowDesk are absent from this `projects.ts`. Missing portfolio data must not erase their CV evidence.
- Define “preferred version” with a reviewed manifest, not filesystem modification times. Parse nested LaTeX braces and exclude “Also built” pseudo-project headings.

**4. Safety and evaluation gaps**

Add these gates:

- **Runtime egress denial**, beyond grep: sockets, DNS, browser subresources, subprocesses, and Tectonic. Disable TeX downloads/shell execution; test with a warmed local bundle.
- **Trusted provenance:** import configuration assigns `private`/`synthetic`; message contents cannot self-declare public. Unknown or mixed provenance fails closed.
- **Artifact isolation:** synthetic canaries must never appear in replay APIs, public bundles, logs, caches, PDF metadata, screenshots, or traces. Test private-like data in a temporary test directory; never inspect the real private tree.
- **Input boundaries:** reject attachment path traversal, Windows reserved filenames, unsafe URL schemes, oversized files, and DOCX decompression bombs. Invalid required filenames block rather than silently changing the naming rule.
- **State enforcement:** replay rejects all mutations; stale revisions invalidate reviews; failed builds cannot leave a successful pack record; Pause during work survives restart and prevents subsequent stages.
- **Fictional packs:** replace identity, education, experience, research, contact links, and PDF metadata. Swapping the name alone leaks or falsely attributes real claims.

Evaluation needs these amendments:

- Freeze exact counts, split membership, clock, seed, fixture hashes, and scoring rules **before tuning**. “~120” is not a gate.
- Hold out wording/layout variants and entire reminder threads—not just different company names.
- Keep gold labels outside parser logic; Claude independently audits them. Developer-authored synthetic results are not an independent real-world validation.
- Define field accuracy over applicable fields, with unknown/conflicting correctness explicit. Report populated-field accuracy separately so absent fields do not inflate results.
- Define “silently wrong deadline” as an incorrect effective deadline shown without an uncertainty/blocking flag.
- Add ranking quality: human-labelled requirement support, unsupported matches, and coverage versus the fixed CV. Provenance alone does not prove relevance.
- Separate attacks that append instructions from attacks that alter source facts. The latter cannot always be recovered; conflict/abstention is an acceptable outcome.
- Freeze the eight pack cases before running; include failures in the denominator. Report cold/warm timings separately. Never present replay latency as a fresh model run.

**5. Exact proposed M1 deliverables and gate**

All paths below are relative to `D:\claude-workspace\inbound`.

| Area | Files |
|---|---|
| Setup | `.gitignore`, `.env.example`, `README.md`, `pyproject.toml`, `requirements-lock.txt` |
| Core | `inbound/__init__.py`, `inbound/__main__.py`, `inbound/settings.py`, `inbound/models.py`, `inbound/db.py`, `inbound/policy.py`, `inbound/pause.py`, `inbound/ledger.py`, `inbound/migrations/001_ingest.sql` |
| Sources | `inbound/sources/__init__.py`, `inbound/sources/base.py`, `inbound/sources/export_txt.py`, `inbound/sources/eml_dir.py` |
| Triage | `inbound/triage/__init__.py`, `inbound/triage/taxonomy.py`, `inbound/triage/normalize.py`, `inbound/triage/rules.py` |
| Synthetic data | `synth/__init__.py`, `synth/generate.py`, `synth/families.py`, `synth/cases.json`, `fixtures/manifest.json`, `fixtures/ground_truth.jsonl` |
| Export fixtures | `fixtures/export_sample/dev-001.txt` through `dev-064.txt`; `held-001.txt` through `held-116.txt`; `attack-001.txt` through `attack-010.txt` |
| EML fixtures | `fixtures/eml_sample/plain.eml`, `html-only.eml`, `multipart.eml`, `encoded.eml`, `malformed.eml` |
| Baseline | `eval/__init__.py`, `eval/triage_baseline.py` |
| Tests | `tests/conftest.py` plus the test files below |

Proposed exact dataset: **24 dev + 36 held-out PS-related; 120 others split 40/80; 10 adversarial = 190**. Claude freezes the case manifest/gold. M1 materializes attachment metadata; binary PDF/DOCX fixtures arrive in M2.

| Test file | Required assertions |
|---|---|
| `test_settings.py` | Offline default; inherited API keys cannot enable networking; all writable paths under the configured D: root. |
| `test_sources.py` | Export grammar, timestamps, incomplete body, malformed files, MIME decoding, HTML-only text, attachment metadata and traversal rejection. |
| `test_import.py` | Repeat import adds zero records; provider-scoped IDs; changed same-ID content reported without overwriting history; transactional failure. |
| `test_triage.py` | Every category, ordered-rule collisions, exact sender matching, look-alikes, subject normalization, quoted-text false positives, source quote preservation. |
| `test_synth.py` | Exactly 190 IDs, deterministic regeneration, complete gold, disjoint groups/splits, manifest hashes. |
| `test_policy.py` | Private/unknown/mixed provenance rejected; input cannot override source classification. |
| `test_pause.py` | Persistence, CLI blocking, resume control, checks between pipeline stages. |
| `test_ledger.py` | Import counts/errors recorded without message bodies or credentials. |
| `test_egress.py` | Import/triage under denied networking, no provider construction or subprocess calls. |
| `test_baseline.py` | Hand-computed confusion matrix/F1, zero-support handling, dev-only selection, correction versus original prediction separation. |

Generated, ignored outputs: `.venv/`, `.local/demo.sqlite`, `.local/reports/m1.json`, `.local/reports/m1.md`, and test caches.

**Claude’s gate:** ruff and pytest pass; offline CLI imports 190 then zero on repeat; dev baseline includes confusion matrix and denominators; no held-out tuning; git index contains no private/local artifacts. Urgency remains explicitly pending M2 deadline extraction.

**6. What Claude must supply before M1**

- The amended contract and synthetic export samples—**no real excerpts**.
- A frozen synthetic case manifest/gold and responsibility for independently checking labels.
- Offline dependency readiness: Python 3.14 wheels, `tzdata`, DOCX/PDF libraries, Node packages, Chromium/axe, and a warmed Tectonic bundle. No overnight install can depend on downloads.
- Approved CV source order, fixed-claim/profile entries, initial approved skills, and fictional demo templates. Otherwise M3 correctly produces no releasable skills.
- Confirmation that the build session can write the target repo; this review session is read-only.
- Ownership of the private split and private M3 run, returning only sanitized counts/pass/fail—not mail, screenshots, logs, or pack text.

Also record the date explicitly: **M1–M4 are 28 October 2026, 02:30–09:00 Dubai.**