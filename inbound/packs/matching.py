"""Conservative word/phrase matching shared by ranking and claim grouping."""

import re

STOP_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "for",
    "from",
    "in",
    "on",
    "with",
    "by",
    "as",
    "at",
    "into",
    "using",
    "that",
    "which",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "this",
    "these",
    "those",
    "it",
    "its",
    "built",
    "build",
    "develop",
    "developed",
    "development",
    "implement",
    "implemented",
    "work",
    "working",
    "tool",
    "application",
    "experience",
    "ability",
    "knowledge",
    "understanding",
    "familiar",
    "familiarity",
    "strong",
    "good",
    "skill",
    "required",
    "preferred",
}
FORMS = {
    "automated": "automation",
    "automate": "automation",
    "automating": "automation",
    "apis": "api",
    "llms": "llm",
    "python3": "python",
}


def tokens(text):
    words = re.findall(r"[\w]+", text.casefold())
    return [
        FORMS.get(
            w,
            w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")) else w,
        )
        for w in words
    ]


def contains(text, phrase):
    haystack, needle = tokens(text), tokens(phrase)
    return bool(needle) and any(
        haystack[i : i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1)
    )


def content_words(text):
    return set(tokens(text)) - STOP_WORDS


def text_supports(text, requirement):
    query, document = content_words(requirement), content_words(text)
    overlap = query & document
    # BM25 supplies relevance, but generic shared words alone must never imply support.
    return bool(query) and (
        (len(query) == 1 and bool(overlap))
        or (len(overlap) >= 2 and len(overlap) / len(query) >= 0.5)
    )


def skill_matches(skill, requirement):
    aliases = [skill["name"], *skill.get("aliases", [])]
    if any(contains(requirement, alias) for alias in aliases):
        return True
    # AI/ML is a family requirement, backed only by curated AI evidence.
    return {"ai", "ml"} <= set(tokens(requirement)) and skill.get("category") == "ai"
