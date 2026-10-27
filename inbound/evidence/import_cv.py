"""Brace-aware reader of manifest-approved CV project sections. No TeX execution."""

import hashlib
import re
from pathlib import Path

import yaml

from inbound.settings import REPO


def uncomment(text):
    # Keep offsets/newlines intact for provenance. An escaped percent is content.
    return re.sub(r"(?<!\\)%[^\n]*", lambda m: " " * len(m[0]), text)


def group(text, pos):
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text) or text[pos] != "{":
        raise ValueError("Expected TeX group")
    start, depth = pos + 1, 1
    pos += 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
            continue
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return text[start:pos], pos + 1
        pos += 1
    raise ValueError("Unclosed TeX group")


def commands(text, names):
    pattern = r"\\(" + "|".join(names) + r")\b"
    for match in re.finditer(pattern, text):
        value, end = group(text, match.end())
        yield match[1], value, match.start(), end


def plain_text(tex):
    """Strip formatting recursively; links retain labels, escaped symbols retain text."""

    def read(text):
        out, pos = [], 0
        while pos < len(text):
            char = text[pos]
            if char == "{":
                value, pos = group(text, pos)
                out.append(read(value))
            elif char == "\\":
                match = re.match(r"\\([a-zA-Z]+|.)", text[pos:], re.DOTALL)
                name = match[1]
                pos += len(match[0])
                if len(name) == 1 and not name.isalpha():
                    out.append(" " if name in ("\\", ",", ";", "!") else name)
                    continue
                while pos < len(text) and text[pos].isspace():
                    pos += 1
                if name in ("href", "link"):
                    _, pos = group(text, pos)
                    label, pos = group(text, pos)
                    out.append(read(label))
                elif name in ("textbf", "emph", "textit", "underline", "textrm", "mbox", "small"):
                    value, pos = group(text, pos)
                    out.append(read(value))
                elif name in ("textendash", "textemdash"):
                    out.append("-")
                elif name == "LaTeX":
                    out.append("LaTeX")
                elif name in ("cdot", "bullet"):
                    out.append(" ")
                elif name == "textasciitilde":
                    out.append("~")
                elif name == "textasciicircum":
                    out.append("^")
                elif name == "textbackslash":
                    out.append("\\")
                else:
                    raise ValueError("Unsupported plain-text TeX macro: " + name)
            else:
                out.append(" " if char in ("~", "$") else char)
                pos += 1
        return "".join(out)

    return " ".join(read(tex).split())


def macros_from(text):
    macros = {}
    for _, value, _, end in commands(uncomment(text), ["newcommand"]):
        # Only zero-argument, literal URL macros; list macros are deliberately ignored.
        try:
            target, _ = group(text, end)
        except ValueError:
            continue
        if re.fullmatch(r"\\[a-zA-Z]+", value) and target.startswith("https://"):
            macros[value[1:]] = target
    return macros


def parse_cv(text, filename, manifest, macros=None):
    digest = hashlib.sha256(text.encode("utf8")).hexdigest()
    active, projects = None, {}
    clean = uncomment(text)
    for name, value, pos, end in commands(clean, ["resumeProjectHeading", "resumeItem"]):
        if name == "resumeProjectHeading":
            active = None
            bold = next(commands(value, ["textbf"]), None)
            if not bold:
                continue
            heading, _, heading_pitch = plain_text(bold[1]).partition(":")
            heading = heading.strip()
            identity = manifest["heading_map"].get(heading)
            approval = manifest["projects"].get(identity)
            if not approval or heading.casefold() == "also built":
                continue
            if filename not in [approval["preferred"], *approval.get("also", [])]:
                continue
            stack = next(commands(value, ["emph"]), None)
            links, _ = group(clean, end)
            urls = {}
            for _, url, _, link_end in commands(links, ["link", "href"]):
                label, _ = group(links, link_end)
                resolved = (macros or {}).get(url.lstrip("\\"), url)
                if resolved.startswith("https://"):
                    urls[plain_text(label).casefold()] = resolved
            active = projects.setdefault(
                identity,
                {
                    "id": identity,
                    "title": heading,
                    "stack": [s.strip() for s in plain_text(stack[1]).split(",")] if stack else [],
                    "live_url": urls.get("live", ""),
                    "code_url": urls.get("code", ""),
                    "source_file": filename,
                    "source_hash": digest,
                    "as_of": "2026-10-28",
                    "tagline": "",
                    "pitch": heading_pitch.strip(),
                    "heading_pitch": heading_pitch.strip(),
                    "decisions": [],
                    "bullets": [],
                },
            )
        elif active is not None:
            if any(b["text_tex"] == value for b in active["bullets"]):
                continue
            identity = active["id"] + "-" + hashlib.sha256(value.encode()).hexdigest()[:16]
            active["bullets"].append(
                {
                    "id": identity,
                    "text_tex": value,
                    "text_plain": plain_text(value),
                    "source_file": filename,
                    "source_line": text.count("\n", 0, pos) + 1,
                    "source_hash": digest,
                    "preferred": filename == manifest["projects"][active["id"]]["preferred"],
                }
            )
    return list(projects.values())


def heading_pitch_from_cv(project, manifest=None):
    """Backfill older registry entries from their hash-checked, approved public source."""
    if manifest is None:
        manifest = yaml.safe_load((REPO / "evidence/approved_sources.yaml").read_text("utf8"))
    approval = manifest["projects"].get(project["id"])
    filename = project.get("source_file", "")
    if not approval or not filename or Path(filename).name != filename:
        return ""
    if filename not in [approval["preferred"], *approval.get("also", [])]:
        return ""
    try:
        raw = (Path(manifest["source_root"]) / filename).read_bytes()
    except OSError:
        return ""
    if hashlib.sha256(raw).hexdigest() != project.get("source_hash"):
        return ""
    projects = parse_cv(raw.decode("utf8"), filename, manifest)
    return next((p["heading_pitch"] for p in projects if p["id"] == project["id"]), "")


def import_cv(manifest=None):
    if manifest is None:
        manifest = yaml.safe_load((REPO / "evidence/approved_sources.yaml").read_text("utf8"))
    root = Path(manifest["source_root"])
    macros = macros_from((root / manifest["fixed"]["preamble"]).read_text("utf8"))
    cache, projects = {}, []
    for identity, approval in manifest["projects"].items():
        merged = None
        for filename in dict.fromkeys([approval["preferred"], *approval.get("also", [])]):
            if Path(filename).name != filename:
                raise ValueError("CV source must be a filename")
            if filename not in cache:
                raw = (root / filename).read_bytes()
                parsed = parse_cv(raw.decode("utf8"), filename, manifest, macros)
                # Hash source bytes, including original line endings.
                for p in parsed:
                    p["source_hash"] = hashlib.sha256(raw).hexdigest()
                    for b in p["bullets"]:
                        b["source_hash"] = p["source_hash"]
                cache[filename] = {p["id"]: p for p in parsed}
            current = cache[filename].get(identity)
            if not current:
                continue
            if merged is None:
                from copy import deepcopy

                merged = deepcopy(current)
            else:
                if not merged.get("heading_pitch") and current.get("heading_pitch"):
                    merged["heading_pitch"] = current["heading_pitch"]
                known = {b["text_tex"] for b in merged["bullets"]}
                merged["bullets"].extend(
                    b for b in current["bullets"] if b["text_tex"] not in known
                )
        if merged and merged["bullets"]:
            projects.append(merged)
    return {"scope": "public", "projects": projects, "skills": []}
