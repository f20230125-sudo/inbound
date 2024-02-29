# M4a frozen synthetic evaluation

Dataset: r4-20261028-01. Model comparison: **not run**.
Rules frozen and hashed before held-out scoring. Failures remain in denominators.

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
| applicable | 365 | 387 | 0.9431524547803618 |
| populated | 228 | 250 | 0.912 |
| full_record | 23 | 36 | 0.6388888888888888 |
| deadline_exact_match | 31 | 33 | 0.9393939393939394 |

Abstentions: 154; silently wrong deadlines: 1.
Failures: [{"record": 1, "field": "company", "case": "P-H02"}, {"record": 1, "field": "stipend", "case": "P-H02"}, {"record": 3, "field": "company", "case": "P-H04"}, {"record": 6, "field": "company", "case": "P-H07"}, {"record": 6, "field": "city", "case": "P-H07"}, {"record": 9, "field": "form_link", "case": "P-H10"}, {"record": 10, "field": "company", "case": "P-H11"}, {"record": 11, "field": "company", "case": "P-H12"}, {"record": 11, "field": "deadline", "case": "P-H12"}, {"record": 11, "field": "roles", "case": "P-H12"}, {"record": 17, "field": "company", "case": "P-H18"}, {"record": 17, "field": "city", "case": "P-H18"}, {"record": 17, "field": "roles", "case": "P-H18"}, {"record": 18, "field": "roles", "case": "P-H19"}, {"record": 19, "field": "roles", "case": "P-H20"}, {"record": 20, "field": "roles", "case": "P-H21"}, {"record": 20, "field": "role_count", "case": "P-H21"}, {"record": 21, "field": "company", "case": "P-H22"}, {"record": 21, "field": "city", "case": "P-H22"}, {"record": 25, "field": "company", "case": "P-H26"}, {"record": 25, "field": "city", "case": "P-H26"}, {"record": 31, "field": "admin_deadline", "case": "P-H32"}]

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
    "pipeline_seconds": 0.520787,
    "import_counts": {
      "imported": 190,
      "unchanged": 0,
      "changed": 0
    },
    "packs_seconds": 5.500331,
    "pack_cases": {
      "P-D12": 0.7925,
      "P-D15": 0.6723,
      "P-D18": 0.6711,
      "P-H18": 0.6809,
      "P-H22": 0.6686,
      "P-H26": 0.6526,
      "P-D16": 0.6694,
      "P-H28": 0.65
    }
  },
  "warm": {
    "pipeline_seconds": 0.043152,
    "import_counts": {
      "imported": 0,
      "unchanged": 190,
      "changed": 0
    },
    "packs_seconds": 5.362854,
    "pack_cases": {
      "P-D12": 0.6462,
      "P-D15": 0.668,
      "P-D18": 0.6651,
      "P-H18": 0.6838,
      "P-H22": 0.6444,
      "P-H26": 0.6912,
      "P-D16": 0.6606,
      "P-H28": 0.6632
    }
  },
  "basis": "Cold = fresh database; warm = repeat processing. Tectonic cache preinstalled in both. No model latency measured."
}
```
