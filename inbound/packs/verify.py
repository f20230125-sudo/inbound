"""Independent PDF checks, including text provenance rather than ID bookkeeping alone."""

import re
import unicodedata
from pathlib import Path

import pdfplumber

from inbound.packs.rank import fit_summary
from inbound.packs.render import validated_selection

CANARIES = ("SYNTHETIC-CANARY", "SYNTHETIC-CANARY-R4-J05-7E4B")


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    # ATS extractors vary in their ligatures, discretionary hyphens and line breaks.
    text = text.replace("\u00ad", "")
    return "".join(c for c in text if c.isalnum())


def verify(pdf_path, log_path, registry, selection, rendered, canaries=CANARIES):
    selected, skills = validated_selection(registry, selection)
    with pdfplumber.open(pdf_path) as pdf:
        pages = len(pdf.pages)
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        metadata = dict(pdf.metadata or {})
        uri_links = [
            str(annotation.get("uri", ""))
            for page in pdf.pages
            for annotation in (page.annots or [])
            if annotation.get("uri")
        ]
    normal = normalize(text)
    bullets = [b for _, bs in selected for b in bs]
    traced = {b["id"]: normalize(b["text_plain"]) in normal for b in bullets}
    # Cross-check the render manifest too; unknown or duplicate IDs never count as provenance.
    ids = [b["id"] for b in bullets]
    manifest_check = ids == rendered["bullet_ids"] and len(set(ids)) == len(ids)
    log = Path(log_path).read_text("utf8", errors="replace")
    skill_check = [s["id"] for s in skills] == rendered["skill_ids"] and all(
        normalize(s["name"]) in normal for s in skills
    )
    label_check = not rendered["provisional"] or normalize("Provisional preview") in normal
    identity_check = normalize(rendered["identity"]) in normal
    filename_check = Path(pdf_path).name == rendered["filename"]
    metadata_text = str(metadata)
    canary_check = all(
        normalize(token) not in normalize(text + metadata_text) for token in canaries
    )
    metadata_check = True
    if rendered["demo"]:
        applicant = registry["applicant"]
        metadata_check = (
            metadata.get("Author") == applicant["name"]
            and metadata.get("Title") == "Synthetic Demo CV"
            and "synthetic" in metadata.get("Subject", "").casefold()
            and "synthetic" in metadata.get("Keywords", "").casefold()
        )
        # Demo templates contain no real source parts or URLs, including annotation metadata.
        metadata_check &= not re.search(
            r"(?:[A-Za-z]:[\\/]|cv-msd|Mohammad|Amaani|IEEE)", metadata_text
        )
        metadata_check &= all(".invalid" in link for link in uri_links)
    overfull = log.count("Overfull")
    checks = {
        "pages": pages,
        "overfull": overfull,
        "bullet_count": len(bullets),
        "traced_bullets": sum(traced.values()),
        "bullet_trace": traced,
        "manifest_check": manifest_check,
        "approved_skills": skill_check,
        "identity_line_check": identity_check,
        "filename_check": filename_check,
        "provisional": rendered["provisional"],
        "provisional_label_check": label_check,
        "metadata_check": bool(metadata_check),
        "canary_check": canary_check,
        "links": sorted(set(rendered["links"] + uri_links)),
        "profile": rendered["profile"],
        **fit_summary(selection.get("requirements", []), selection.get("gaps", [])),
    }
    checks["passed"] = (
        pages == 1
        and overfull == 0
        and all(traced.values())
        and all(
            (
                manifest_check,
                skill_check,
                identity_check,
                filename_check,
                label_check,
                metadata_check,
                canary_check,
            )
        )
    )
    return checks
