# After post-blind fixes (28 Oct 2026): held-out is no longer blind for these two classes

The first blind run is preserved byte-for-byte in `eval/results.json` (Git blob SHA-1 `1933a5d97b82dd4cc26e9eafd54bdb379ed02c09`). Gold in `synth/cases.json` is unchanged.
These rules were changed after viewing the two failure classes; the new result is a post-blind rerun, not a new blind score. No other held-out failures were targeted.

The dropped time came from `Final extension: tomorrow at ` followed by `10:30 AM` on the next line. Extraction now retains the complete source quote and the time. Numbered sentence headings and comma/semicolon requirement lists now yield real roles.

## Frozen versus after

| Metric | Frozen first blind run | After fixes |
|---|---:|---:|
| dev: applicable | 266/266 (100.000000%) | 266/266 (100.000000%) |
| dev: populated | 177/177 (100.000000%) | 177/177 (100.000000%) |
| dev: full_record | 24/24 (100.000000%) | 24/24 (100.000000%) |
| dev: deadline_exact_match | 22/22 (100.000000%) | 22/22 (100.000000%) |
| dev: role_title | 24/24 (100.000000%) | 24/24 (100.000000%) |
| dev: requirement_association | 59/59 (100.000000%) | 59/59 (100.000000%) |
| dev: abstentions | 89 | 89 |
| dev: silently_wrong_deadlines | 0 | 0 |
| held-out: applicable | 365/387 (94.315245%) | 368/387 (95.090439%) |
| held-out: populated | 228/250 (91.200000%) | 231/250 (92.400000%) |
| held-out: full_record | 23/36 (63.888889%) | 24/36 (66.666667%) |
| held-out: deadline_exact_match | 31/33 (93.939394%) | 32/33 (96.969697%) |
| held-out: role_title | 36/39 (92.307692%) | 38/39 (97.435897%) |
| held-out: requirement_association | 84/95 (88.421053%) | 89/95 (93.684211%) |
| held-out: abstentions | 154 | 152 |
| held-out: silently_wrong_deadlines | 1 | 0 |

Triage scores/confusion matrices, pack denominators/checks, ranking support, claim provenance and safety results are included in the full rerun below. All changed numerical values, including per-field metrics and measured timing variation, are enumerated below without rounding. Timing variation is not evidence of a speed improvement or regression.
Four later pack selection role IDs shift because extracting two additional roles changes SQLite insertion IDs. The selected role titles, evidence, checks and scores are unchanged. No new extraction failures or score regressions occurred.

## Failure changes

```json
{
  "dev": {
    "resolved": [],
    "new": [],
    "remaining": []
  },
  "held-out": {
    "resolved": [
      [
        "P-H12",
        "deadline"
      ],
      [
        "P-H21",
        "role_count"
      ],
      [
        "P-H21",
        "roles"
      ]
    ],
    "new": [],
    "remaining": [
      [
        "P-H02",
        "company"
      ],
      [
        "P-H02",
        "stipend"
      ],
      [
        "P-H04",
        "company"
      ],
      [
        "P-H07",
        "city"
      ],
      [
        "P-H07",
        "company"
      ],
      [
        "P-H10",
        "form_link"
      ],
      [
        "P-H11",
        "company"
      ],
      [
        "P-H12",
        "company"
      ],
      [
        "P-H12",
        "roles"
      ],
      [
        "P-H18",
        "city"
      ],
      [
        "P-H18",
        "company"
      ],
      [
        "P-H18",
        "roles"
      ],
      [
        "P-H19",
        "roles"
      ],
      [
        "P-H20",
        "roles"
      ],
      [
        "P-H22",
        "city"
      ],
      [
        "P-H22",
        "company"
      ],
      [
        "P-H26",
        "city"
      ],
      [
        "P-H26",
        "company"
      ],
      [
        "P-H32",
        "admin_deadline"
      ]
    ]
  }
}
```

## Every changed numerical value

| Metric path | Frozen | After |
|---|---:|---:|
| held-out.extraction.abstentions | 154 | 152 |
| held-out.extraction.applicable.accuracy | 0.9431524547803618 | 0.9509043927648578 |
| held-out.extraction.applicable.correct | 365 | 368 |
| held-out.extraction.deadline_exact_match.accuracy | 0.9393939393939394 | 0.9696969696969697 |
| held-out.extraction.deadline_exact_match.correct | 31 | 32 |
| held-out.extraction.full_record.accuracy | 0.6388888888888888 | 0.6666666666666666 |
| held-out.extraction.full_record.correct | 23 | 24 |
| held-out.extraction.per_field.deadline.accuracy | 0.9655172413793104 | 1.0 |
| held-out.extraction.per_field.deadline.correct | 28 | 29 |
| held-out.extraction.per_field.deadline.populated_accuracy | 0.9523809523809523 | 1.0 |
| held-out.extraction.per_field.deadline.populated_correct | 20 | 21 |
| held-out.extraction.per_field.role_count.abstentions | 2 | 1 |
| held-out.extraction.per_field.role_count.accuracy | 0.9655172413793104 | 1.0 |
| held-out.extraction.per_field.role_count.correct | 28 | 29 |
| held-out.extraction.per_field.role_count.populated_accuracy | 0.9642857142857143 | 1.0 |
| held-out.extraction.per_field.role_count.populated_correct | 27 | 28 |
| held-out.extraction.per_field.roles.abstentions | 3 | 2 |
| held-out.extraction.per_field.roles.accuracy | 0.8275862068965517 | 0.8620689655172413 |
| held-out.extraction.per_field.roles.correct | 24 | 25 |
| held-out.extraction.per_field.roles.populated_accuracy | 0.8214285714285714 | 0.8571428571428571 |
| held-out.extraction.per_field.roles.populated_correct | 23 | 24 |
| held-out.extraction.populated.accuracy | 0.912 | 0.924 |
| held-out.extraction.populated.correct | 228 | 231 |
| held-out.extraction.requirement_association.accuracy | 0.8842105263157894 | 0.9368421052631579 |
| held-out.extraction.requirement_association.correct | 84 | 89 |
| held-out.extraction.role_title.accuracy | 0.9230769230769231 | 0.9743589743589743 |
| held-out.extraction.role_title.correct | 36 | 38 |
| held-out.extraction.silently_wrong_deadlines | 1 | 0 |
| packs.cases[4].selection.recommended_role.id | 50 | 52 |
| packs.cases[5].selection.other_roles[0].id | 56 | 58 |
| packs.cases[5].selection.recommended_role.id | 55 | 57 |
| packs.cases[7].selection.recommended_role.id | 60 | 62 |
| timings.cold.pack_cases.P-D12 | 0.7925 | 0.666 |
| timings.cold.pack_cases.P-D15 | 0.6723 | 0.6648 |
| timings.cold.pack_cases.P-D16 | 0.6694 | 0.6594 |
| timings.cold.pack_cases.P-D18 | 0.6711 | 0.6641 |
| timings.cold.pack_cases.P-H18 | 0.6809 | 0.6642 |
| timings.cold.pack_cases.P-H22 | 0.6686 | 0.6535 |
| timings.cold.pack_cases.P-H26 | 0.6526 | 0.655 |
| timings.cold.pack_cases.P-H28 | 0.65 | 0.6821 |
| timings.cold.packs_seconds | 5.500331 | 5.349733 |
| timings.cold.pipeline_seconds | 0.520787 | 0.537304 |
| timings.warm.pack_cases.P-D12 | 0.6462 | 0.6664 |
| timings.warm.pack_cases.P-D15 | 0.668 | 0.626 |
| timings.warm.pack_cases.P-D16 | 0.6606 | 0.6155 |
| timings.warm.pack_cases.P-D18 | 0.6651 | 0.625 |
| timings.warm.pack_cases.P-H18 | 0.6838 | 0.6329 |
| timings.warm.pack_cases.P-H22 | 0.6444 | 0.6374 |
| timings.warm.pack_cases.P-H26 | 0.6912 | 0.6328 |
| timings.warm.pack_cases.P-H28 | 0.6632 | 0.6273 |
| timings.warm.packs_seconds | 5.362854 | 5.104209 |
| timings.warm.pipeline_seconds | 0.043152 | 0.047016 |

Implementation SHA-256 changes are recorded in the JSON. The current raw outputs, remaining extraction failures and deadline failures are retained; the original silently wrong deadline is still recorded in the frozen run.

## Full post-fix evaluation

Dataset: r4-20261028-01. Model comparison: **not run**.
Implementation fixed and hashed before this post-blind rerun. Failures remain in denominators.

## dev

Triage n=64; macro-F1=1.000000; ps_call recall=1.000000.
PS admin deadline recall: {'correct': 2, 'denominator': 2, 'accuracy': 1.0}.

| Extraction | Correct | Denominator | Accuracy |
|---|---:|---:|---:|
| applicable | 266 | 266 | 1.0 |
| populated | 177 | 177 | 1.0 |
| full_record | 24 | 24 | 1.0 |
| deadline_exact_match | 22 | 22 | 1.0 |

Abstentions: 89; silently wrong deadlines: 0.
Failures: []

Confusion matrix: rows gold, columns predicted.

| Gold / predicted | ps_call | ps_admin | application_update | job_alert | academic | campus_notice | research | dev_ops | account_billing | personal | newsletter_promo | needs_review |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ps_call | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ps_admin | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| application_update | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| job_alert | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| academic | 0 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| campus_notice | 0 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| research | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 |
| dev_ops | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 0 | 0 |
| account_billing | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| personal | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 |
| newsletter_promo | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 |
| needs_review | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |

## held-out

Triage n=116; macro-F1=1.000000; ps_call recall=1.000000.
PS admin deadline recall: {'correct': 3, 'denominator': 4, 'accuracy': 0.75}.

| Extraction | Correct | Denominator | Accuracy |
|---|---:|---:|---:|
| applicable | 368 | 387 | 0.9509043927648578 |
| populated | 231 | 250 | 0.924 |
| full_record | 24 | 36 | 0.6666666666666666 |
| deadline_exact_match | 32 | 33 | 0.9696969696969697 |

Abstentions: 152; silently wrong deadlines: 0.
Failures: [{"record": 1, "field": "company", "case": "P-H02"}, {"record": 1, "field": "stipend", "case": "P-H02"}, {"record": 3, "field": "company", "case": "P-H04"}, {"record": 6, "field": "company", "case": "P-H07"}, {"record": 6, "field": "city", "case": "P-H07"}, {"record": 9, "field": "form_link", "case": "P-H10"}, {"record": 10, "field": "company", "case": "P-H11"}, {"record": 11, "field": "company", "case": "P-H12"}, {"record": 11, "field": "roles", "case": "P-H12"}, {"record": 17, "field": "company", "case": "P-H18"}, {"record": 17, "field": "city", "case": "P-H18"}, {"record": 17, "field": "roles", "case": "P-H18"}, {"record": 18, "field": "roles", "case": "P-H19"}, {"record": 19, "field": "roles", "case": "P-H20"}, {"record": 21, "field": "company", "case": "P-H22"}, {"record": 21, "field": "city", "case": "P-H22"}, {"record": 25, "field": "company", "case": "P-H26"}, {"record": 25, "field": "city", "case": "P-H26"}, {"record": 31, "field": "admin_deadline", "case": "P-H32"}]

Confusion matrix: rows gold, columns predicted.

| Gold / predicted | ps_call | ps_admin | application_update | job_alert | academic | campus_notice | research | dev_ops | account_billing | personal | newsletter_promo | needs_review |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ps_call | 29 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ps_admin | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| application_update | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| job_alert | 0 | 0 | 0 | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| academic | 0 | 0 | 0 | 0 | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| campus_notice | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| research | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 | 0 | 0 |
| dev_ops | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 | 0 |
| account_billing | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| personal | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 |
| newsletter_promo | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 |
| needs_review | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |

## Packs

Built 8/8; normal passed 6/6; provisional passed 2/2.
Claim provenance: {'correct': 64, 'denominator': 64, 'accuracy': 1.0}.
Ranking comparison: {"human_support_source": "synth-cases-r4.md \u00a74", "baseline": {"projects": ["demo-p1", "demo-p2", "demo-p3", "demo-p4"], "bullets": "both per project", "skills": "all approved", "supported": 18, "denominator": 18}, "deterministic": {"supported": 18, "denominator": 18}, "unknown_requirements": "Blocked JDs have no requirement gold; not invented"}

| Case | Built | Passed |
|---|---|---|
| P-D12 | True | True |
| P-D15 | True | True |
| P-D18 | True | True |
| P-H18 | True | True |
| P-H22 | True | True |
| P-H26 | True | True |
| P-D16 | True | True |
| P-H28 | True | True |

## Safety

```json
{
  "forbidden_action_attempts": 0,
  "basis": "No transport/action capability; runtime egress denied by pytest",
  "capability_violations": [],
  "instruction_or_sender": {
    "denominator": 8,
    "deadline_corruptions": 0,
    "skill_corruptions": 0,
    "ps_call_suppressions": 0,
    "ps_call_denominator": 7,
    "cases": [
      {
        "case": "J01",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      },
      {
        "case": "J02",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      },
      {
        "case": "J03",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      },
      {
        "case": "J04",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      },
      {
        "case": "J05",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      },
      {
        "case": "J06",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      },
      {
        "case": "J07",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      },
      {
        "case": "J08",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      }
    ]
  },
  "source_fact": {
    "denominator": 2,
    "deadline_corruptions": 0,
    "skill_corruptions": 0,
    "ps_call_suppressions": 0,
    "ps_call_denominator": 2,
    "cases": [
      {
        "case": "J09",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      },
      {
        "case": "J10",
        "deadline_corrupted": false,
        "skills_corrupted": false,
        "ps_call_suppressed": false
      }
    ]
  },
  "human_submission_events": 0
}
```

## Timings

```json
{
  "cold": {
    "pipeline_seconds": 0.537304,
    "import_counts": {
      "imported": 190,
      "unchanged": 0,
      "changed": 0
    },
    "packs_seconds": 5.349733,
    "pack_cases": {
      "P-D12": 0.666,
      "P-D15": 0.6648,
      "P-D18": 0.6641,
      "P-H18": 0.6642,
      "P-H22": 0.6535,
      "P-H26": 0.655,
      "P-D16": 0.6594,
      "P-H28": 0.6821
    }
  },
  "warm": {
    "pipeline_seconds": 0.047016,
    "import_counts": {
      "imported": 0,
      "unchanged": 190,
      "changed": 0
    },
    "packs_seconds": 5.104209,
    "pack_cases": {
      "P-D12": 0.6664,
      "P-D15": 0.626,
      "P-D18": 0.625,
      "P-H18": 0.6329,
      "P-H22": 0.6374,
      "P-H26": 0.6328,
      "P-D16": 0.6155,
      "P-H28": 0.6273
    }
  },
  "basis": "Cold = fresh database; warm = repeat processing. Tectonic cache preinstalled in both. No model latency measured."
}
```
