# Inbound: design (frozen 28 Oct 2026, 00:20)

Accepted by Claude from Codex round 5b. Its "Necessary contract additions" (skip endpoint POST /api/opportunities/<id>/status, provenance in opportunity responses, expected revision/pack ids on review writes, snapshot metadata, run ids for async work, sanitized replay settings) are part of the SPEC from M4. Stale threshold: last successful import older than 12 h or from an earlier Dubai day.

This design follows [SPEC.md, including §13](D:/claude-workspace/inbound/SPEC.md:127), and the [Round 4 synthetic cases](D:/claude-workspace/inbound/synth-cases-r4.md). No files were changed, and nothing under `inbound\private` was opened.

**Shared layout and visual language**

Reuse Backroom’s Geist typography, neutral theme tokens, bordered cards, compact tables, underlined links, collapsible evidence and visible keyboard focus. The references are [its shell](D:/claude-workspace/backroom/web/src/App.tsx), [theme](D:/claude-workspace/backroom/web/src/index.css), [Inbox](D:/claude-workspace/backroom/web/src/pages/Inbox.tsx) and [badge variants](D:/claude-workspace/backroom/web/src/components/ui/badge.tsx).

Use three navigation entries:

- **Today / Inbox**
- **Opportunity / Pack**
- **Settings / Runs**

“Opportunity / Pack” opens the last selected opportunity. Without one, it shows “Choose a call from Today / Inbox” and a link back. There is no separate Applications board.

| Element | Design |
|---|---|
| Background | White in light mode; Backroom’s charcoal in dark mode |
| Surfaces | Neutral cards with a 1 px border; no coloured page backgrounds |
| Primary action | Near-black button in light mode; light button in dark mode |
| Red | Overdue deadlines, blocked work and failed checks |
| Amber | Needs review, uncertainty requiring attention and stale snapshots |
| Green | Only a check explicitly labelled **Passed** |
| Neutral | New, preparing, reviewed, submitted by me, skipped, paused, found and not run |
| Type | 24 px page title; 16 px section title; 14 px body; 12 px provenance |
| Numbers | Tabular numerals for deadlines, counts and durations |
| Theme | Light on first visit; **Dark mode** toggle; remember the explicit choice |

Do not copy Backroom’s automatic status-to-colour mapping: “New”, “Reviewed” and “Submitted by me” must not become amber or green automatically.

At **1440 px**, use a roughly 76 px header, a 190 px left navigation rail and 28 px main-content padding. This leaves about 1194 px for content.

At **390 px**, use 16 px side padding and a 358 px content width. Navigation becomes three wrapping links beneath the header. Controls have at least 44 px touch targets. Tables become labelled cards; source text and paths wrap without horizontal page scrolling.

Every view shows the mode:

- Local: **Local · Offline**
- Replay: **Synthetic replay · Read-only**

All displayed times use **Dubai time · UTC+04:00**. A replay with a frozen clock also states that explicitly.

---

**1. Today / Inbox**

The first screen answers: “What needs my attention, and how current is this information?”

Reading order:

1. Persisted Pause state.
2. Snapshot freshness.
3. Overdue or blocked items.
4. Deadlines within 48 hours.
5. New calls and PS administration.
6. Triaged inbox.

The header contains **Inbound**, the mode, **Pause new work** or **Resume work**, and **Dark mode**.

Pause is neutral, with explicit text:

- **Work enabled**
- **Paused — imports, extraction and pack work are stopped.**
- During an active stage: **Pause saved. The current stage may finish; no next stage or retry will start.**
- If saving fails: **Pause could not be saved. Work may still be enabled.**

Do not change the displayed state optimistically before the server confirms it.

Below the page title, show:

> Last successful import: 28 Oct 2026, 02:20  
> Latest message in that import: 28 Oct 2026, 01:45

The second line is not called “Synced through”: an exported folder does not establish that the mailbox is complete.

For this design, mark a snapshot stale when the last successful import is over 12 hours old or belongs to an earlier Dubai calendar day. These are proposed UI thresholds, since the spec does not define one.

Exact stale banner:

> **Snapshot may be out of date**  
> Last successful import: {time}. New mail may be missing.  
> **Import messages**

“Import messages” links to the import section in Settings / Runs. Refreshing the page only reloads stored data. When a new PS call lands, Uzair exports it and imports it locally; this version does not poll Gmail.

A failed subsequent import adds:

> **Latest import failed. Showing the last successful snapshot.**  
> **View run**

Keep usable previous data visible.

**Desktop arrangement**

```text
Header: Inbound · Local · Offline             Pause new work   Dark mode
Navigation │ Today / Inbox
           │ Last successful import … · Latest message …
           │ [Snapshot banner, when needed]
           │ [Overdue / blocked attention rows]
           │
           │ Deadlines within 48 hours │ New calls │ PS administration
           │
           │ Inbox
           │ Filters
           │ Message table
```

The three summary panels share the available width. Each shows up to three entries and a **View all ({count})** link that expands or filters the relevant list on this page.

At 390 px, stack these sections in the same order. Show two entries per summary before **View all**. Never truncate a deadline, company name or blocker explanation.

**Summary content and ordering**

| Section | Contents and order |
|---|---|
| **Overdue / blocked** | Unresolved conflicts and blockers first, then expired open opportunities and admin notices. Blocked items sort by earliest supported candidate deadline, then newest update. Overdue items sort by most recently elapsed deadline. |
| **Deadlines within 48 hours** | Open calls and admin notices with supported timed deadlines in `(now, now + 48 h]`, earliest first. Each row identifies **Call** or **PS administration**. |
| **Date-only deadlines** | A separate group beneath timed deadlines: **Due today — time not stated** and **Due tomorrow — time not stated**. Never assign a time to fit the 48-hour calculation. |
| **New calls** | Opportunities whose status is `new`, newest received message first. Reminders update one opportunity rather than adding another card. |
| **PS administration** | Deadline-bearing notices first, using timed/date-only groups; remaining notices newest first. These remain message-bound tasks, not opportunities. |

Submitted and skipped opportunities do not appear as outstanding call work. They remain accessible through Inbox filters. A past admin deadline says **Deadline passed**, not “Task incomplete”: there is no admin-completion record in the current contract.

Each call summary row contains:

> **Ledgercraft · Backend Intern**  
> Due 28 Oct, 12:00 · **9 h 30 min left**  
> Hybrid · AED 2,200/month  
> **Open opportunity**

At the frozen synthetic clock, `P-D12` has that countdown. For `P-D06`, show **Expired · Deadline passed before receipt**.

Conflicting and unknown deadlines stay visible outside the timed list:

- **Deadline conflicting — review required**
- **Deadline unknown — expiry unknown**

Do not render either as “No deadline” or “Not expired”.

**Triaged inbox**

At 1440 px, use these columns:

| Column | Contents |
|---|---|
| **Message** | Linked subject, sender address and attachment count |
| **Received** | Dubai date and time |
| **Category** | Neutral category badge; manual-override marker when applicable |
| **Why** | Plain reason followed by a source excerpt |
| **Deadline / call** | Supported deadline and linked opportunity, or “Not applicable” |
| **Correct category** | Category select; optional explicit alternative button |

The **Why** cell should read like:

> Exact PS-office sender and “Call for CV” subject.  
> Source: subject · “Call for CV - …”  
> Rule: {rule ID}

Show the sender match where it matters. For `J06`:

> No exact PS-office sender match.  
> Source: From · `ps@dubai-bits-pilani.ac.in`

Do not imply that a call-looking subject overrides the sender rule.

On mobile, each message becomes a card in this order: subject, category and received time, sender, reason, source line, deadline/link, correction control. The reason and source excerpt remain visible.

Filter labels:

- **Category:** All categories; PS call; PS administration; Application update; Job alert; Academic; Campus notice; Research; Development / operations; Account / billing; Personal; Newsletter / promotion; Needs review.
- **Attention:** All messages; Due within 48 hours; Overdue; Needs review; Corrected.
- **Application status:** All statuses; New; Preparing; Needs review; Reviewed; Submitted by me; Blocked; Skipped.
- **Sort:** Newest first; Oldest first; Earliest deadline; Needs review first.
- **Clear filters**

Category and attention controls appear first; secondary filters wrap underneath. Preserve filters in the URL and on return from an opportunity.

Sort rules:

- Default: received time descending, then message ID.
- “Earliest deadline”: supported upcoming timed deadlines, date-only deadlines by calendar date, overdue deadlines, then unknown/conflicting/not applicable. Label each group.
- “Needs review first”: conflicts/blockers, uncategorised review items, remaining messages newest first.
- Use a stable ID tie-break throughout.

**One-click correction**

Selecting a different category saves the local override immediately; no second Save button. Where an explicit alternative is available, offer a button such as **Change to PS administration**.

After success:

> Category changed to PS administration. **Undo**

Undo records another correction; it does not erase history. Retain the original classification, reason, rule and correction timestamp under **Classification history**.

The correction affects local triage. It does not alter mail, rewrite extracted facts, build a pack or mark anything submitted. Later processing uses the override.

While paused:

> **Resume work to change categories.**

In replay:

> **Category changes are available in local mode.**

**Today / Inbox states**

| State | Exact presentation |
|---|---|
| Nothing imported | **No messages imported.** “Import an export folder or EML folder to start.” Local: **Import messages**. |
| No imminent deadlines | **No supported deadlines within the next 48 hours.** Unknown/conflicting entries remain elsewhere. |
| No new calls | **No new calls in this snapshot.** |
| No admin notices | **No PS administration notices in this snapshot.** |
| Empty filter result | **No messages match these filters.** **Clear filters** |
| First load | Neutral skeletons with **Loading Today and Inbox…**; no temporary zero counts |
| Partial failure | Keep the successful sections. Failed section: **Inbox could not be loaded.** **Retry** |
| Correction failure | Keep the original category: **Category was not changed. Retry.** |

---

**2. Opportunity / Pack**

This view combines source facts, role fit and the reviewable artifact.

At 1440 px:

- Full-width opportunity header and deadline.
- Approximately 7/12 width for facts, revisions, attachments and role coverage.
- Approximately 5/12 width for a PDF preview.
- Selected projects, verification and answers follow beneath the preview.
- Keep the main action group near the header; avoid overlapping floating controls.

At 390 px, use one column:

1. Header and deadline.
2. Blockers and actions.
3. Facts and provenance.
4. Attachments.
5. Roles and coverage.
6. PDF preview.
7. Selected projects.
8. Verification.
9. Form answers.

Provide jump links: **Facts**, **Roles**, **Pack**, **Answers**. Other roles use collapsible sections; there is one recommended-role pack.

**Header**

> **Ledgercraft**  
> Backend Intern · Recommended role  
> Cedar Quay · Hybrid · AED 2,200/month  
> PS call · Needs review  
> Revision 1 · Received 27 Oct 2026, 06:00  
> **Back to Today / Inbox**

“Recommended” explains a deterministic evidence match; it does not imply employer preference or eligibility.

The header repeats important facts for scanning. Their full provenance appears immediately below.

**Facts and provenance**

Every applicable field must be present, including company and city:

- Company
- City
- Form link
- Application link
- Stipend
- Internship mode
- Submission deadline
- Company website
- JD location
- CV naming rule
- Internship dates
- Roles

Desktop columns: **Field**, **Value**, **Status**, **Source text**.

Mobile renders the same information as labelled blocks. Status and at least a short source quote are visible without hovering.

| Status | Exact behaviour |
|---|---|
| **Found** | Show normalized value, literal supporting quote and source location. |
| **Inferred** | Show value, raw phrase and the inference anchor. Amber when it requires review. |
| **Unknown** | Show **Unknown** and a reason, such as “Not stated in the complete message” or “Exported body is incomplete”. Do not invent a source quote. |
| **Conflicting** | Show every candidate and its own quote/provenance. No single effective value. |

A provenance reference contains message ID, sent time, revision and location: subject, body, PDF page or DOCX paragraph/table cell.

Example for `P-D08`:

> **Submission deadline:** 29 Oct 2026, 08:00  
> **Inferred**  
> “Revised deadline: on or before 08:00AM tomorrow”  
> P-D08 · sent 28 Oct, 00:20 · body  
> “Tomorrow” resolved from this message’s sent time in Dubai.

Inherited facts say:

> Retained from revision 1 · P-D02

For `P-D04`, city is:

> **DSO** — subject quote  
> **Dubai** — body quote  
> **Found · Both observations retained**

That pair is not presented as conflicting.

Keep an unknown naming-rule field separate from the chosen output filename:

> **CV naming rule:** Unknown · Not stated  
> **Output filename:** {filename} · Default approved naming template

**View source** expands safe plain text within the view, highlights the quote and identifies its location. Never render email HTML or treat source instructions as controls. Public replay source text must already exclude canaries and disallowed content.

**Deadline presentation**

| Situation | Label |
|---|---|
| Supported future time | **5 h 30 min left** plus **28 Oct 2026, 08:00 · Dubai** |
| Supported past time | **Expired · 2 h 10 min overdue** |
| Before receipt | Add **Deadline passed before receipt** |
| Date-only | **Due 29 Oct 2026 · Time not stated** |
| Unknown | **Deadline unknown · Expiry unknown** |
| Conflict | **Deadline conflicting · No countdown**; list all candidates |

Update timed countdowns once per minute. Do not show seconds or announce every change to assistive technology.

A genuine newer amendment updates the effective deadline. A competing unsupported value creates a conflict.

On a new revision, show:

> **Call updated — review this revision**  
> A previous pack was reviewed against revision {n}. It is no longer current.

Keep the previous pack available as **Previous revision — out of date**. Never overwrite its provenance or remove a recorded human submission event.

A probable merge without matching authority says:

> **Possible related call — not merged**

Provide a link to inspect it. No merge button is included without an API contract for that operation.

**Roles, requirements and gaps**

Recommended role first; other roles retain source order. Each heading shows:

> **Backend Intern · Recommended**  
> 3 requirements have approved evidence · 0 gaps

Coverage counts are requirement counts, not a percentage claiming suitability.

For every role, use:

| Requirement | Approved evidence | Evidence source | Coverage |
|---|---|---|---|
| Python | Shelfmark Inventory · `p1-b1` | Demo registry entry and approved bullet | Supported |
| Flask | Shelfmark Inventory · `p1-b1` | Same entry | Supported |
| SQL | QuayPulse Reports · `p3-b2` | Approved bullet | Supported |

Each requirement also retains its JD quote and location. Expanding an evidence entry shows its exact approved text, registry ID and source record.

Coverage labels are **Supported**, **Partial evidence**, **Gap**, or **Requirements unavailable**. Do not use green here; reserve it for checks labelled Passed.

For `P-H21`, the Machine Learning role must show:

> PyTorch — **Gap: no approved evidence**  
> TensorFlow — **Gap: no approved evidence**

For unreadable or missing JDs:

> **Requirements unavailable — attached JD could not be read.**  
> Title from subject: Backend Intern.

Never turn unavailable requirements into “0 gaps”.

**Attachments and blockers**

Each attachment row shows filename, type, JD/brochure purpose, byte availability, parse status and provenance.

| Status | Label and consequence |
|---|---|
| Parsed | **Parsed**; neutral. Requirements link to the parsed locations. |
| Missing | **Missing bytes · Review blocked** |
| Unreadable | **Unreadable · Review blocked** |
| Unsupported | **Unsupported format · Review blocked** |
| Complete source, no JD | **JD not included**; distinct from a broken attachment |
| Incomplete body | **JD presence unknown — incomplete export** |

For `P-D16`:

> **JD unreadable — provisional preview only**  
> Requirements could not be checked. The preview uses the role title and approved evidence.

Offer **Build provisional preview** in local mode. Before review, require the explicit acknowledgement:

> **I understand that the JD was not read and this pack may miss requirements.**

Record the acknowledgement against this blocker, revision and pack. The missing-JD warning remains visible after acknowledgement.

An unresolved deadline conflict remains a review blocker. The UI cannot resolve it by choosing a convenient candidate; a clarifying source revision is needed.

**The pack**

Use five labelled sections:

| Section | Contents |
|---|---|
| **PDF preview** | Filename, role, revision, creation time, page count and local PDF preview |
| **Selected projects** | Exact selected bullets, registry IDs and requirement-specific selection reasons |
| **Verification** | Individual check results and supporting details |
| **Form answers** | Approved purpose, technologies and challenge/fix text |
| **Review history** | Review, acknowledgement, submission and skip events |

On mobile, show a fit-width first-page preview with **Open PDF**. Provide the same content in readable HTML; the embedded PDF is not the only way to inspect the pack.

**Download PDF** is separate from the external application link. A provisional PDF retains **Provisional preview** beside its download control.

Selected projects must explain the actual returned selection. For example:

> **Shelfmark Inventory**  
> Selected for Python, Flask and SQL requirements.  
> Bullets: `p1-b1`, `p1-b2`  
> **View approved evidence**

Do not promise a particular four-project selection before ranking runs. Do not add editable CV prose or an “Add skill” action.

Verification rows use **Passed**, **Failed**, **Not run**, or **Blocked**:

- One page.
- No overfull output.
- Correct approved identity.
- Every rendered bullet traces to an approved registry entry.
- Every listed skill is approved.
- Filename matches the call rule or approved default.
- Approved fixed sections and correct demo identity/metadata where applicable.
- Links listed — **Not checked online**.

A failed required check blocks review. An unrun online link check is explicitly informational in offline mode; it must not silently appear as Passed.

A failed build shows:

> **Pack build failed. No successful pack was created.**  
> **View run** · **Retry build**

Do not show a stale successful artifact as the result of that failed build.

Form answers show the field label, exact answer, character count and **Copy answer**. Include provenance beneath the answer. A missing challenge becomes:

> **Answer needed from you:** What broke, and how did you fix it?

There is no generated substitute and no copyable invented answer. Clipboard success says **Copied**; failure says **Could not copy. Select the answer text to copy it.**

**Action rules**

| Action | Rule |
|---|---|
| **Open form link** | Plain external anchor to a supported, validated form URL. No server fetch, preview, prefill or submission. Show the destination host and “Opens in a new tab”. Unknown/conflicting links have no active anchor. |
| **Open application link** | Equivalent action for `direct_apply`; do not substitute the company website. |
| **Build pack** | Local, unpaused, recommended role known. Creates one recommended-role pack. Missing-JD cases use **Build provisional preview**. |
| **Mark reviewed** | Current revision, completed pack, required checks passed, blockers resolved or explicitly acknowledged where permitted. Record reviewed pack/revision and time. |
| **Mark submitted by me** | Requires the current reviewed pack. Expand an inline confirmation: **I submitted this application myself**, then **Record submission**. Records the user’s statement only. |
| **Skip** | Available locally even before a pack exists. Optional **Reason for skipping**. Save immediately; offer **Undo skip**. |
| Status select | Displays workflow status and permitted user transitions. New/preparing/blocked are pipeline states; selecting them must not manufacture pipeline results. |

Opening a form link does not change review or submission status. Application-update mail does not establish that Uzair submitted anything.

An expired deadline does not prevent recording an actual human submission; keep the expiry visible.

While paused, server-changing actions are disabled with **Resume work to make changes**. Viewing, copying, downloading and manually opening a link remain available. In public replay, mutation controls explain **Available in local mode** and synthetic external links are labelled **Synthetic link — not opened in replay**.

**Opportunity / Pack states**

- **Loading opportunity…** and a separate **Loading pack…** skeleton.
- **No pack built for this revision.** Local: **Build pack**.
- **Role unknown — no recommended-role pack can be built.**
- **Opportunity could not be loaded.** **Retry**.
- **PDF preview could not be loaded.** Keep facts, verification and HTML evidence available.
- **This opportunity changed while you were reviewing it. Reload the latest revision.** Reject stale writes.

---

**3. Settings / Runs**

At 1440 px, place settings in a roughly 430 px left column and the run ledger in the remaining space. At 390 px, stack settings, import, then runs. Add a **Jump to runs** link near the title.

**Pause**

Repeat the global persisted control with the same wording. It remains usable when paused because §13 exempts pause/resume itself.

Other backend settings changes remain unavailable while paused. Dark mode is a browser preference and remains usable.

Replay shows the recorded Pause state with:

> **Read-only replay. Pause can be changed in local mode.**

**Budgets**

Show configured limits and usage separately:

- **Daily model call limit**
- **Daily model spend limit**, with an explicit currency
- **Calls used today**
- **Spend used today**
- **Budget resets at**, with timezone

Use the budget service’s actual available measurements; show **Not recorded** rather than inventing spend.

In this offline build:

> **Offline mode — live model calls are disabled.**  
> Changing a budget does not enable a provider.

Limits default to zero. Live-provider budget controls can remain disabled until that capability exists. **Model comparison: Not run** stays visible; FakeLLM and cache replay are not described as live model runs.

If editable limits are available locally, use **Save budget limits** with inline validation and a persisted success message.

**Payload policy — read-only**

Display:

| Item | Value |
|---|---|
| Private payloads to cloud models | **Blocked** |
| Approved private-field allowlist | **Empty**, or the exact approved field names |
| Synthetic/public payloads | Subject to policy; live transport disabled in this build |
| Current model execution | Offline replay / FakeLLM, as actually configured |
| External network services | Disabled in this build |
| Gmail | Not connected |
| Notifications | Not implemented in this build |

No provider key, allowlist editor or notification switch is included. Environment variables alone must not appear to enable future transport.

**Data paths**

Read-only labels:

- **Database**
- **Import folder**
- **Evidence registry**
- **Pack output folder**
- **Cache and temporary files**
- **Source provenance**

Local mode shows runtime-configured paths. The intended database locations are `private/inbound.sqlite` for real local use and `.local/demo.sqlite` for synthetic use. Displaying configuration is not permission to browse those files.

Replay shows only synthetic relative paths. It must not expose local private paths, real source filenames or credentials.

No **Browse private files**, delete, reset or shell-open actions.

**Import messages**

Local controls:

- **Source format:** Export text / EML folder.
- **Import folder:** configured path, read-only.
- **Source provenance:** explicit configured value; never inferred from message text.
- **Import messages** button.

While active:

> **Import running · {current stage}**  
> **View run**

Disable duplicate starts. If paused:

> **Import blocked while paused. Resume work to import messages.**

On completion:

> Imported {new} new messages · {duplicates} already present · {rejected} rejected

The snapshot advances only after the associated triage/extraction work completes successfully. This orchestration needs to be made explicit in the API contract; “source import finished” alone is insufficient to claim that Today is current.

In replay:

> **Imports are available in local mode.**

**Run ledger**

Default sort: started time descending, then run ID.

Filters:

- **Run type:** All types; Import; Triage; Extraction; Pack; Digest; Evaluation.
- **Result:** All results; Running; Completed; Paused; Blocked; Failed.
- **Clear filters**

Columns: **Started**, **Type**, **Result**, **Counts**, **Duration**, **Model calls**, **Replay/cache hits**, **Details**.

Completed is neutral. Failed/blocked is red. Green appears only on a specific verification result labelled Passed.

Expanded run details show:

- Run ID and mode.
- Source type and safe path display.
- Started/finished times and current/last stage.
- Count breakdown, including duplicates and rejected files.
- Related opportunity, revision and pack.
- Provider execution type.
- Sanitized error and retry history.

Paused work must not read “Completed”. A previous interrupted build must not acquire a successful pack result.

Empty: **No runs recorded.**  
Loading: **Loading runs…**  
Error: **Run ledger could not be loaded. Retry.**

Refresh the ledger every five seconds while an observed run is active; stop when it finishes or the page is hidden. Refreshing only reads state and never starts work.

---

**Components: reuse versus new**

| Reuse from Backroom | Adaptation |
|---|---|
| Theme CSS, Geist, `cn` utility | Light-first default and Inbound storage key |
| Button, Badge, Card, Alert, Separator | Explicit semantic badge mapping |
| Table, Select, Input, Label, Textarea | Responsive card alternatives and larger mobile targets |
| Tabs, Collapsible, ScrollArea, Tooltip | Labelled source and role disclosures |
| Skeleton | Separate page, section and artifact loading states |
| Source-text highlighting pattern | Message/revision/page provenance; sanitized text; reduced-motion support |
| Skip-link and focus-outline patterns | Inbound routes and focus restoration |

New Inbound components:

- `PauseControl` and `SnapshotBanner`.
- `AttentionList`, `DeadlineDisplay` and `AdminNotice`.
- `MessageRow` / `MessageCard` and `CategoryCorrection`.
- `FieldProvenance`, `ConflictCandidates` and `RevisionHistory`.
- `RoleCoverage` and `AttachmentBlocker`.
- `PackPreview`, `ProjectSelection`, `VerificationList` and `CopyAnswer`.
- `ReviewActions`, including blocker acknowledgement and submission confirmation.
- `PayloadPolicySummary`, `DataPaths`, `ImportControl` and `RunLedger`.

Reuse the primitives and interaction patterns. Rewrite pages, types and API client as §13 requires.

---

**API calls and contract details**

These are design requirements, not a claim that the endpoints already exist.

Every view first reads `GET /api/settings` for mode, Pause, capabilities and safe configuration. In local mode, it also supplies the CSRF bootstrap needed for POSTs. Allowing a sanitized read-only settings response in replay must be explicit, since §7 describes settings as local-mode.

| View | Reads | Mutations |
|---|---|---|
| Today / Inbox | `GET /api/today`; `GET /api/messages?category=…`; `GET /api/opportunities` | `POST /api/messages/<id>/category`; `POST /api/settings` for Pause |
| Opportunity / Pack | `GET /api/opportunities/<id>`; `GET /api/packs/<id>`; `GET /api/packs/<id>/pdf`; `GET /api/runs` while building | `POST /api/opportunities/<id>/pack`; `POST /api/packs/<id>/status`; Pause through settings |
| Settings / Runs | `GET /api/settings`; `GET /api/runs` | `POST /api/settings`; `POST /api/import` |

Only `category` is an existing documented message-query parameter. Other Inbox filters and sorts can operate over the returned collection for this small local dataset; do not silently assume unsupported server parameters.

Necessary contract additions or clarifications:

1. **Skip without a pack:** add `POST /api/opportunities/<id>/status`, limited to skip/undo-skip transitions. The documented pack-status endpoint cannot cover this case.
2. **Provenance responses:** opportunity detail must include revisions, every field’s status/raw/normalized/source text, all conflict candidates, sent-time anchors, role requirements and attachment locations.
3. **Review writes:** include expected revision and pack IDs, blocker acknowledgements and the explicit human-submission declaration. Reject stale state rather than silently applying it.
4. **Snapshot metadata:** return last successful import, latest imported-message time, latest import failure and a snapshot version.
5. **Asynchronous work:** import/build responses identify a run; results become available through runs and the relevant resource. Define import-to-triage/extraction orchestration explicitly.
6. **Replay settings:** return sanitized settings/capabilities without private paths or mutation credentials.

All POSTs require CSRF, local mode, allowed Host and a fresh Pause check. Only changing Pause itself is exempt from the Pause block. Recheck Pause between stages and before retries.

External application URLs are browser anchors only. No view calls an API that fetches, fills or submits a form.

---

**Keyboard and screen-reader behaviour**

- First focusable control: **Skip to content**. Use header, primary navigation and main landmarks, one page-level heading and ordered section headings.
- Route changes announce the page title and focus its heading. **Back to Today / Inbox** restores filters, scroll position and the originating message link.
- Subject links open details. Rows are not clickable containers with hidden keyboard behaviour.
- Native select behaviour: arrows navigate; Enter commits. Merely moving through options must not save a category.
- Collapsible controls announce expanded/collapsed state and identify the controlled region.
- Each status has text. Colour and icons never carry the only meaning.
- Tables have captions and scoped headers. Mobile cards repeat their field labels.
- Source highlighting also has a textual announcement, such as **Source for submission deadline, message P-D08, body**.
- Loading sections use `aria-busy`; completion, corrections and copy results use polite status announcements. Mutation failures use an alert.
- Countdown changes are not live-announced every minute. The absolute deadline remains readable.
- Reordered lists do not move focus. After a correction filters out a message, move focus to the next message and announce what happened.
- Disabled actions have a nearby persistent explanation, not a tooltip alone.
- The PDF has an accessible title and equivalent HTML evidence/verification content.
- No required single-letter shortcuts. All actions work through Tab, Shift+Tab, Enter, Space and native control keys.
- Honour reduced motion. Keep focus indicators visible in both themes and prevent sticky elements from covering focused controls.

---

**Three-minute founder demo**

Prepare a **local synthetic-only** database and demo evidence registry. Use the manifest’s frozen clock, **28 Oct 2026, 02:30 Dubai**, visibly labelled. Prebuild the normal `P-D12` pack and provisional `P-D16` preview so compilation does not consume the presentation.

Use Sara Qamar’s fictional identity throughout. Do not open synthetic external URLs. Show actual run/check results; expected fixture outcomes are not evidence that a run passed.

| Time | What to show | What to say |
|---|---|---|
| **0:00–0:20** | Today: `P-D06`, `P-D21`, `P-D22`; freshness and Pause | “This is the morning view. It puts overdue calls and upcoming deadlines first. This survey gives a date without a time, so it stays date-only. The import timestamp tells me how current the desk is.” |
| **0:20–1:00** | `P-D12`, Ledgercraft: recommended API role, one provenance quote, coverage table, PDF, verification, one copyable answer | “This call has API and QA roles. There is one recommended-role pack. Each requirement points to approved evidence. The PDF uses those exact records, and these checks show what passed. This answer comes from the same registry.” |
| **1:00–1:25** | `P-D02` with reminder `P-D08`; revision history and inferred deadline | “This is one opportunity with a reminder. ‘Tomorrow’ is anchored to the reminder’s sent time: 28 October at 00:20. The effective deadline is 29 October at 08:00. A new revision requires the pack to be reviewed again.” |
| **1:25–1:50** | `P-D16`, Ember Mosaic: unreadable attachment, provisional preview, disabled review before acknowledgement | “The attached JD could not be read. A title-based preview is still possible, but the missing requirements stay visible. Review requires an explicit acknowledgement; the warning does not disappear.” |
| **1:50–2:15** | `J09`, then `J06` in Inbox | “Here the email and PDF disagree on the deadline. Both values stay visible, with no countdown. This other message uses a look-alike sender, so it needs review and creates no automatic opportunity.” |
| **2:15–2:35** | `P-H21`, other-role coverage | “The machine-learning role asks for PyTorch and TensorFlow. Neither has approved evidence. They appear as gaps and are not added to the applicant’s CV.” |
| **2:35–3:00** | Settings / Runs; Pause; import control; model execution and ledger | “Pause is persisted and blocks new import, extraction and pack work. This run uses synthetic local data and no live model. The ledger records what happened. I review the pack, open the application myself and record submission myself.” |

For a public read-only replay, use the same sequence with recorded states. Show the disabled review and Pause controls without pretending they changed anything.