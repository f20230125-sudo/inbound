"""Group variants of one project's achievements without rewriting approved text."""

import re

from inbound.packs.matching import STOP_WORDS, content_words, tokens


def near_duplicate(first, second):
    a, b = content_words(first), content_words(second)
    overlap = a & b
    if a and b and len(overlap) / len(a | b) >= 0.5:
        return True
    # A preferred composite can contain almost all of a shorter variant's claim.
    if a and b and len(overlap) >= 5 and len(overlap) / min(len(a), len(b)) >= 0.75:
        return True
    first_words = [w for w in tokens(first) if w not in STOP_WORDS]
    second_words = [w for w in tokens(second) if w not in STOP_WORDS]
    phrases = {tuple(first_words[i : i + 6]) for i in range(len(first_words) - 5)}
    if any(tuple(second_words[i : i + 6]) in phrases for i in range(len(second_words) - 5)):
        return True
    numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", first)) & set(
        re.findall(r"\b\d+(?:\.\d+)?\b", second)
    )
    distinctive = {n for n in numbers if float(n) >= 10}
    return bool(distinctive) and (len(numbers) >= 2 or len(overlap) >= 3)


def claims(bullets):
    groups = []
    for bullet in bullets:
        matches = [
            group
            for group in groups
            if any(near_duplicate(bullet["text_plain"], b["text_plain"]) for b in group)
        ]
        merged = [bullet]
        for group in matches:
            merged.extend(group)
            groups.remove(group)
        groups.append(merged)
    return groups
