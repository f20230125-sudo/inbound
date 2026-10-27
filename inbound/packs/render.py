"""Render only approved registry IDs and hash-checked fixed CV parts."""

import hashlib
import re
from pathlib import Path

import yaml

from inbound.evidence.skills import approved_skills
from inbound.packs.rank import select_profile
from inbound.settings import REPO

CATEGORY_LABELS = {"ai": "AI and ML", "data": "Data and SQL", "frontend": "Front end"}


class RenderBlocked(ValueError):
    pass


def escape_tex(text):
    mapping = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "\\": r"\textbackslash{}",
    }
    return "".join(mapping.get(c, c) for c in str(text))


def safe_url(url, demo=False):
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?:[/?#][^\s{}\\]*)?", url):
        raise ValueError("Unsafe evidence URL")
    host = url.split("/")[2].casefold()
    if demo and not host.endswith(".invalid"):
        raise ValueError("Demo links must be fictional")
    return escape_tex(url)


def filename_for(company, demo=False, applicant=None, naming_rule=None, fixed=None):
    template = applicant["default_filename"] if demo else fixed["default_filename"]
    if naming_rule:
        template = naming_rule
    name = template.replace("<Company>", company).replace("{company}", company)
    # Treat a call's naming rule as a filename only, never a filesystem path or TeX.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name).strip(" .")
    if not name or name.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL"}:
        raise ValueError("Invalid PDF filename")
    if not name.casefold().endswith(".pdf"):
        name += ".pdf"
    if len(name) > 200:
        raise ValueError("PDF filename too long")
    return name


def validated_selection(registry, selection):
    projects = {p["id"]: p for p in registry["projects"]}
    skills = {s["id"]: s for s in approved_skills(registry["skills"])}
    selected = []
    if len({s["id"] for s in selection["projects"]}) != len(selection["projects"]):
        raise ValueError("Duplicate project ID")
    for s in selection["projects"]:
        if s["id"] not in projects:
            raise ValueError("Unknown project ID")
        p = projects[s["id"]]
        bullets = {b["id"]: b for b in p["bullets"]}
        if not s["bullets"] or any(b not in bullets for b in s["bullets"]):
            raise ValueError("Unknown or cross-project bullet ID")
        selected.append((p, [bullets[b] for b in s["bullets"]]))
    if any(s not in skills for s in selection["skills"]):
        raise ValueError("Skill is not approved")
    return selected, [skills[s] for s in selection["skills"]]


def render(
    directory,
    registry,
    selection,
    *,
    company,
    role,
    demo=False,
    provisional=False,
    naming_rule=None,
    fixed=None,
):
    selected, skills = validated_selection(registry, selection)
    application = escape_tex(role + " | " + company)
    if (registry["scope"] == "demo") != demo:
        raise ValueError("Registry approval scope does not match pack")
    if fixed is None:
        fixed = yaml.safe_load((REPO / "evidence/approved_fixed.yaml").read_text("utf8"))
    parts, applicant = {}, registry.get("applicant")
    if demo:
        if not applicant:
            raise ValueError("Fictional identity is required")
        parts["preamble"] = (REPO / "inbound/packs/templates/demo_preamble.tex").read_bytes()
        metadata = (
            r"\hypersetup{pdfauthor={"
            + escape_tex(applicant["name"])
            + r"},pdftitle={Synthetic Demo CV},pdfsubject={Synthetic applicant preview},"
            r"pdfkeywords={synthetic,fictional,demo}}" + "\n"
        )
        parts["head"] = (
            metadata
            + r"\begin{document}"
            + "\n"
            + r"{\LARGE\textbf{"
            + escape_tex(applicant["name"])
            + "}}"
            + r"\\"
            + "\n"
            + escape_tex(applicant["student_id"] + " | " + applicant["location"])
            + r"\\"
            + "\n"
            + escape_tex(applicant["email"])
            + r"\quad "
            + r"\href{"
            + safe_url(applicant["portfolio"], True)
            + r"}{Portfolio}"
            + "\n"
            + r"\par\small{"
            + application
            + r"}\par"
            + "\n"
            + r"\section{Education}"
            + "\n"
            + escape_tex(applicant["education"])
            + r"\\"
            + "\n"
            + escape_tex(applicant["education_status"])
            + "\n"
        ).encode("utf8")
        parts["tail"] = b""
        profile = escape_tex(applicant["profile"])
        identity = applicant["name"]
    else:
        # Check every part before creating any copy. Fixed bytes are never rewritten.
        for name, approval in fixed["files"].items():
            path = Path(fixed["source_root"]) / approval["file"]
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != approval["sha256"]:
                raise RenderBlocked("Fixed-file hash mismatch: " + name)
            parts[name] = raw
        profile = select_profile(selection.get("requirements", []))["text"]
        identity = fixed["identity_line_check"]
    label = "Provisional preview - blocker acknowledgement required" if provisional else ""
    parts["profile"] = (
        (r"\par\textbf{" + escape_tex(label) + "}\n" if label else "")
        + r"\section{Profile}"
        + "\n"
        + r"\small{"
        + profile
        + "}\n"
    ).encode("utf8")
    lines = [r"\section{Projects}", r"\resumeSubHeadingListStart"]
    links, bullet_ids = [], []
    for p, bullets in selected:
        # Avoid fixed-width tabular headings: long reviewed titles/stacks can wrap naturally.
        title = escape_tex(p["title"])
        lines.append(r"\item \textbf{" + title + "}")
        project_links = []
        for key, text in (("live_url", "Demo"), ("code_url", "Code")):
            if p.get(key):
                url = safe_url(p[key], demo)
                links.append(p[key])
                project_links.append(r"\href{" + url + "}{" + text + "}")
        lines.append(r"\hfill " + r" $|$ ".join(project_links))
        lines.append(r"\resumeItemListStart")
        for bullet in bullets:
            # Registry LaTeX is trusted only within its approval scope. No JD text enters here.
            lines.append(r"\resumeItem{" + bullet["text_tex"] + "}")
            bullet_ids.append(bullet["id"])
        lines.append(r"\resumeItemListEnd")
    lines.append(r"\resumeSubHeadingListEnd")
    project_map = {p["id"]: p for p in registry["projects"]}
    others = []
    for identity_id in selection.get("also_built", [])[:5]:
        p = project_map[identity_id]
        title = escape_tex(p["title"])
        url = p.get("code_url") or p.get("live_url")
        if url:
            title = r"\href{" + safe_url(url, demo) + "}{" + title + "}"
            links.append(url)
        others.append(title)
    if others:
        lines.append(r"\small{\textbf{Also built:} " + "; ".join(others) + "}")
    parts["projects"] = ("\n".join(lines) + "\n").encode("utf8")
    groups = {}
    for s in skills:
        groups.setdefault(s.get("category", "engineering"), []).append(s["name"])
    skill_lines = [
        r"\section{Technical Skills" + ("" if demo else r" \& Certification") + "}",
        r"\begin{itemize}[leftmargin=0.15in, label={}]",
        r"\small{\item{\strut",
    ]
    for category, names in groups.items():
        skill_lines.append(
            r"\textbf{"
            + escape_tex(CATEGORY_LABELS.get(category, category.title()))
            + "}: "
            + escape_tex(", ".join(names))
            + r" \\"
        )
    if not demo:
        skill_lines.append(r"\textbf{Certification}: " + escape_tex(fixed["certification"]))
    skill_lines.extend(["}}", r"\end{itemize}", r"\end{document}"])
    parts["skills"] = ("\n".join(skill_lines) + "\n").encode("utf8")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, raw in parts.items():
        (directory / (name + ".tex")).write_bytes(raw)
    (directory / "body.tex").write_text(
        "\n".join(r"\input{" + name + ".tex}" for name in fixed["order"]) + "\n", encoding="utf8"
    )
    if demo:
        links.append(applicant["portfolio"])
    else:
        # List fixed hyperlinks too, resolving the preamble's URL macros without a network check.
        from inbound.evidence.import_cv import macros_from

        macros = macros_from(parts["preamble"].decode("utf8"))
        for raw in (parts["head"], parts["tail"]):
            for url in re.findall(r"\\(?:href|link)\{([^}]+)\}", raw.decode("utf8")):
                resolved = macros.get(url.lstrip("\\"), url)
                if resolved.startswith(("https://", "mailto:")):
                    links.append(resolved)
    return {
        "identity": identity,
        "demo": demo,
        "label": label,
        "provisional": provisional,
        "filename": filename_for(company, demo, applicant, naming_rule, fixed),
        "links": sorted(set(links)),
        "bullet_ids": bullet_ids,
        "skill_ids": [s["id"] for s in skills],
        "profile": select_profile(selection.get("requirements", []))
        if not demo
        else {"family": "demo", "needs_uzair_review": False, "not_tailored": False},
    }
