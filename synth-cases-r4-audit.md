# Claude's audit of the round-4 case manifest (28 Oct 2026, ~00:30)

Verdict: **approved and frozen as dataset `r4-20261028-01`, with one change.**

Checked by hand:
- All nine reminder anchors: P-D07 (27 Oct 18:10 → 28 Oct 08:00), P-D08 (28 Oct 00:20 → 29 Oct 08:00), P-D09 (→ 28 Oct 17:00), P-H09 (→ 28 Oct 09:15), P-H10 (sent 28 Oct 00:15, received 01:45 → 29 Oct 09:00 from sent time), P-H11 (→ 28 Oct 10:00), P-H12 (→ 29 Oct 10:30), P-H13 (→ 28 Oct 11:00), P-H14 conflicting {28 Oct 11:00, 29 Oct 11:00}. All correct.
- P-H07: 26 Oct 19:00 UTC = 26 Oct 23:00 Dubai, before the default sent time 27 Oct 06:00, so past_at_receipt = true. Correct. P-D06 likewise.
- Counts: families A-F = 14+9+5+7+7+7 = 49 call messages, G = 6, H = 5, total 60; 49 - 9 reminders = 40 opportunities; others 40 + 80; adversarial 10; total 190.
- Precedence cases: J06 look-alike sender → needs_review (the campus rule matches only the exact institutional domains); O-D002 job alert with "application deadline" stays job_alert; P-D24 LinkedIn "your application was sent to" → application_update (update rules precede job alerts). Consistent with SPEC §13.
- The applicant, companies, cities, links (`.invalid`, `SYNTHETIC-NOT-LIVE`) are fictional; nothing real leaks.

Change (keeps 190): **P-H25** stipend line becomes `· As per company norms` → stipend `unknown` with that source text (real calls sometimes give no figure; the parser must not read "norms" as a number). Everything else in P-H25 unchanged.

Notes for M2/M3 (no manifest change): the research category includes a conference "paper-status" notice (real-world lesson 28 Oct: such a notice can be wrong; Inbound only flags, it never changes CV evidence because of an email). Urgency is computed against the evaluation clock 2026-10-28T02:30+04:00.
