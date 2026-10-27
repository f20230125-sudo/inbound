# Standing orders for Codex (Inbound build)

1. Read `SPEC.md` (including §13 Amendment 1, which wins on conflicts) before every milestone. Build only the current milestone.
2. **Never open, list, read or search anything under `private/`.** It is Uzair's real mail. If a task seems to need it, stop and say so in your report.
3. No network: no pip/npm installs, no downloads, no web requests. Dependencies are pre-installed by Claude in `.venv` and `web/node_modules`. If something is missing, stop and list it.
4. No git commits, pushes, deploys, account connections, emails, form access, or notifier code. Claude reviews and commits.
5. Everything stays inside `D:\claude-workspace\inbound`. Temporary files, caches and test output go under `.local/`.
6. Tests: pytest with `--basetemp=.local/pytest-<milestone>`; ruff clean (`line-length = 100`). Write tests first for every rule in the milestone's gate. Do not weaken a test to make it pass; report the failure instead.
7. Synthetic data only, fictional names, no real companies' internal text beyond the generic PS-office template structure described in SPEC §4. Gold labels come from case definitions, never from parser output.
8. Plain, readable code that matches the surrounding style; small modules; no speculative features beyond the milestone.
9. End each milestone with a report at `.codex-runs/mN-report.md`: what was built, exact test counts, gate checklist with pass/fail and evidence, anything skipped and why, open questions. Do not claim a pass you did not run.
