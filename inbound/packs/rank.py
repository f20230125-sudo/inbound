"""Deterministic BM25 scoring and diminishing-return requirement coverage."""

import math
from collections import Counter
from typing import Protocol

import yaml

from inbound.evidence.skills import approved_skills
from inbound.packs.claims import claims
from inbound.packs.matching import contains, skill_matches, text_supports, tokens
from inbound.settings import REPO


def requirements(lines):
    return [
        {"id": f"q{i + 1}", "text": line} if isinstance(line, str) else dict(line)
        for i, line in enumerate(lines or [])
    ]


def select_profile(lines, path=None):
    config = yaml.safe_load((path or REPO / "evidence/profiles.yaml").read_text("utf8"))
    text = " ".join(q["text"] for q in requirements(lines))
    scores = {
        key: sum(contains(text, word) for word in p["keywords"])
        for key, p in config["profiles"].items()
    }
    family = max(scores, key=lambda key: scores[key]) if any(scores.values()) else config["default"]
    return {
        "family": family,
        "text": config["profiles"][family]["text"],
        "needs_uzair_review": bool(config["profiles"][family].get("needs_uzair_review")),
        "not_tailored": not any(scores.values()),
    }


def bm25(documents, query):
    counts = [Counter(tokens(doc)) for doc in documents]
    n = len(counts)
    average = sum(sum(c.values()) for c in counts) / max(n, 1) or 1
    scores = [0.0] * n
    for term in set(tokens(query)):
        frequency = sum(term in c for c in counts)
        inverse = math.log(1 + (n - frequency + 0.5) / (frequency + 0.5))
        for i, count in enumerate(counts):
            tf = count[term]
            scores[i] += (
                inverse * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * sum(count.values()) / average))
            )
    return scores


def line_cost(bullet):
    return max(1, math.ceil(len(bullet["text_plain"]) / 110))


def fit_summary(reqs, gaps):
    total, missing = len(reqs), len(gaps)
    ratio = (total - missing) / total if total else None
    return {
        "coverage": {"supported": total - missing, "total": total, "ratio": ratio},
        "fit": "unknown" if ratio is None else ("low" if ratio < 0.25 else "supported"),
        "fit_reason": (
            f"No evidence for {missing} of {total} requirements: consider skipping"
            if ratio is not None and ratio < 0.25
            else ""
        ),
    }


def compact_skills(skills, hits, selected_ids, max_lines=3):
    """Requirement matches first, then curated evidence for selected projects."""
    relevant = [s for s in skills if s["id"] in hits]
    general = [s for s in skills if selected_ids.intersection(s.get("projects", []))]
    candidates = relevant + [s for s in general if s not in relevant]
    if not candidates:
        candidates = skills
    groups, chosen = {}, []
    for skill in candidates:
        category = skill.get("category", "engineering")
        updated = {
            **groups,
            category: groups.get(category, len(category) + 2) + len(skill["name"]) + 2,
        }
        lines = sum(math.ceil(n / 105) for n in updated.values())
        if lines <= max_lines or not chosen:
            groups = updated
            chosen.append(skill["id"])
    return chosen


def rank(registry, lines, project_count=4, line_budget=24):
    if not 4 <= project_count <= 6:
        raise ValueError("Select four to six projects")
    reqs = requirements(lines)
    projects = sorted((p for p in registry["projects"] if p["bullets"]), key=lambda p: p["id"])
    skills = approved_skills(registry["skills"])
    all_bullets = [b for p in projects for b in p["bullets"]]
    scores = {b["id"]: 0.0 for b in all_bullets}
    supports = {p["id"]: set() for p in projects}
    bullet_support = {b["id"]: set() for b in all_bullets}
    skill_hits = set()
    for q in reqs:
        weights = bm25([b["text_plain"] for b in all_bullets], q["text"])
        for b, score in zip(all_bullets, weights, strict=True):
            scores[b["id"]] += score
        matching = [s for s in skills if skill_matches(s, q["text"])]
        for skill in matching:
            skill_hits.add(skill["id"])
            for p in projects:
                if p["id"] not in skill.get("projects", []):
                    continue
                supports[p["id"]].add(q["id"])
                for b in p["bullets"]:
                    if any(
                        contains(b["text_plain"], a)
                        for a in [skill["name"], *skill.get("aliases", [])]
                    ):
                        bullet_support[b["id"]].add(q["id"])
                        scores[b["id"]] += 2.0
        # Plain phrases in an approved bullet also support requirements absent from the alias map.
        for p in projects:
            for b in p["bullets"]:
                if text_supports(b["text_plain"], q["text"]):
                    supports[p["id"]].add(q["id"])
                    bullet_support[b["id"]].add(q["id"])

    selected, coverage = [], Counter()
    # One representative per connected claim; prefer the manifest unless another
    # variant covers more requirements. Relevance only breaks ties after preference.
    representatives = {}
    for p in projects:
        order = {b["id"]: i for i, b in enumerate(p["bullets"])}
        representatives[p["id"]] = [
            min(
                group,
                key=lambda b: (
                    -len(bullet_support[b["id"]]),
                    not b.get("preferred", False),
                    -scores[b["id"]],
                    order[b["id"]],
                    b["id"],
                ),
            )
            for group in claims(p["bullets"])
        ]
    target = min(project_count, len(projects))

    def utility(p):
        gain = sum(1 / (1 + coverage[q]) for q in supports[p["id"]])
        relevance = max(scores[b["id"]] for b in representatives[p["id"]])
        return -(gain * 10 + relevance * 0.1), p["id"]

    while len(selected) < target:
        candidates = [p for p in projects if p not in selected]
        chosen = min(candidates, key=utility)
        selected.append(chosen)
        coverage.update(supports[chosen["id"]])

    # Reserve one bullet per project before allocating extras, with stable preferred-order ties.
    ordered = {}
    for p in selected:
        order = {b["id"]: i for i, b in enumerate(p["bullets"])}
        ordered[p["id"]] = sorted(
            representatives[p["id"]],
            key=lambda b: (
                -len(bullet_support[b["id"]]),
                -scores[b["id"]],
                not b.get("preferred", False),
                order[b["id"]],
                b["id"],
            ),
        )
    chosen_bullets = {}
    remaining = line_budget
    for i, p in enumerate(selected):
        reserve = sum(
            min(line_cost(b) for b in ordered[later["id"]]) for later in selected[i + 1 :]
        )
        fitting = [b for b in ordered[p["id"]] if line_cost(b) <= remaining - reserve]
        if not fitting:
            raise ValueError("Insufficient line budget for selected projects")
        chosen_bullets[p["id"]] = [fitting[0]]
        remaining -= line_cost(fitting[0])
    for _ in range(2):
        for p in selected:
            extras = [
                b
                for b in ordered[p["id"]]
                if b not in chosen_bullets[p["id"]] and line_cost(b) <= remaining
            ]
            if extras:
                chosen_bullets[p["id"]].append(extras[0])
                remaining -= line_cost(extras[0])
    selected_ids = {p["id"] for p in selected}
    gaps = [q for q in reqs if not coverage[q["id"]]]
    return {
        "projects": [
            {
                "id": p["id"],
                "bullets": [b["id"] for b in chosen_bullets[p["id"]]],
                "why": sorted(supports[p["id"]]),
            }
            for p in selected
        ],
        "skills": compact_skills(
            skills, skill_hits, selected_ids, max_lines=4 if registry["scope"] == "demo" else 3
        ),
        "gaps": gaps,
        **fit_summary(reqs, gaps),
        "also_built": [
            p["id"] for p in sorted((p for p in projects if p not in selected), key=utility)
        ][:5],
        "line_costs": {b["id"]: line_cost(b) for bs in chosen_bullets.values() for b in bs},
        "requirements": reqs,
        "profile": select_profile(reqs),
    }


class ModelRanker(Protocol):
    def rank(self, registry: dict, requirements: list) -> dict: ...


def model_rank(registry, requirements):
    return {"status": "not run", "selection": None}
