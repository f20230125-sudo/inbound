import hashlib

import yaml

from inbound.settings import REPO


def load_skills(path=None):
    data = yaml.safe_load((path or REPO / "evidence/skills.yaml").read_text("utf8"))
    return [
        {**s, "id": "skill-" + hashlib.sha256(s["name"].encode()).hexdigest()[:16]}
        for s in data["skills"]
    ]


def approved_skills(skills):
    return [s for s in skills if s.get("approved") is True]
