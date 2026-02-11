"""Regenerate committed evidence snapshots, without copying fixed real CV sections."""

import hashlib
import json
import re

from inbound.evidence.import_cv import import_cv
from inbound.evidence.skills import load_skills
from inbound.settings import REPO


def demo_snapshot():
    manifest = (REPO / "synth-cases-r4.md").read_text("utf8")
    digest = hashlib.sha256(manifest.encode()).hexdigest()
    section = manifest.split("### Five fictional evidence projects", 1)[1]
    section = section.split("### Human-labelled requirement support", 1)[0]
    projects, skills = [], {}
    categories = {
        "Python": "languages",
        "TypeScript": "languages",
        "SQL": "data",
        "React": "frontend",
        "HTML": "frontend",
        "CSS": "frontend",
        "accessibility": "frontend",
        "Flask": "backend",
    }
    for line in section.splitlines():
        if not line.startswith("| **"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        name = re.search(r"\*\*(.*?)\*\*", cells[0])[1]
        pid = re.search(r"`(demo-p\d+)`", cells[0])[1]
        number = pid.removeprefix("demo-")
        names = [s.strip() for s in cells[2].split(",")]
        purpose, decision = cells[3].split("<br>Challenge/fix: ", 1)
        bullets = []
        for i, text in enumerate(cells[1].split("<br>"), 1):
            bullets.append(
                {
                    "id": f"{number}-b{i}",
                    "text_tex": text,
                    "text_plain": text,
                    "source_file": "synth-cases-r4.md",
                    "source_line": manifest[: manifest.index(line)].count("\n") + 1,
                    "source_hash": digest,
                    "preferred": True,
                }
            )
        projects.append(
            {
                "id": pid,
                "title": name,
                "bullets": bullets,
                "stack": names,
                "tagline": purpose.removeprefix("Purpose: "),
                "pitch": "",
                "decisions": [decision],
                "source_file": "synth-cases-r4.md",
                "source_hash": digest,
                "as_of": "2026-10-28",
                "code_url": f"https://code.demo.invalid/sara-qamar/{pid}",
                "live_url": f"https://projects.demo.invalid/sara-qamar/{pid}",
            }
        )
        for skill in names:
            if skill not in skills:
                slug = re.sub(r"[^a-z0-9]+", "-", skill.casefold()).strip("-")
                aliases = (
                    ["accessible HTML/CSS", "a11y", "accessible"]
                    if skill == "accessibility"
                    else []
                )
                skills[skill] = {
                    "id": "demo-skill-" + slug,
                    "name": skill,
                    "aliases": aliases,
                    "projects": [],
                    "approved": True,
                    "category": categories.get(skill, "engineering"),
                    "note": "Fictional approval: synth-cases-r4.md §4",
                }
            skills[skill]["projects"].append(pid)
    assert len(projects) == 5
    return {
        "scope": "demo",
        "projects": projects,
        "skills": list(skills.values()),
        "applicant": {
            "name": "Sara Qamar",
            "student_id": "DEMO-2023-CS-0042",
            "email": "sara.qamar@applicant.demo.invalid",
            "location": "Lumen Bay",
            "education": "BSc Computer Science, Lumen Bay Institute of Computing, "
            "September 2023–July 2027",
            "education_status": "Expected graduation July 2027",
            "profile": "Computer science student building web applications, data tools and "
            "search systems with Python, TypeScript and SQL.",
            "portfolio": "https://portfolio.demo.invalid/sara-qamar",
            "default_filename": "DEMO-2023-CS-0042-Sara-Qamar-<Company>.pdf",
            "experience": None,
            "research": None,
            "certifications": None,
        },
    }


def main():
    public = import_cv()
    public["skills"] = load_skills()
    for filename, data in (
        ("evidence_snapshot.json", public),
        ("demo_evidence.json", demo_snapshot()),
    ):
        (REPO / "fixtures" / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
        )
    print(json.dumps({"public_projects": len(public["projects"]), "demo_projects": 5}))


if __name__ == "__main__":
    main()
