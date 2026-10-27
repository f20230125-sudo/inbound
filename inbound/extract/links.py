"""Recognise form/apply links and retain evidence for wrapped URL tokens."""

import re

from inbound.extract.records import conflict, field

URL = re.compile(r"https?://[^\s<>*]+")
DIRECT = re.compile(r"\b(?:apply directly|careers page)\b", re.IGNORECASE)


def url_tokens(body):
    for match in URL.finditer(body):
        end = match.end()
        url = match.group()
        # Only join URL-shaped continuations: never consume ordinary following prose.
        while continuation := re.match(r"\n[ \t]*([^\s<>*]+)[ \t]*(?=\n|$)", body[end:]):
            part = continuation[1]
            if re.match(r"https?://", part) or not re.fullmatch(r"[\w%+/?=&.#~:@!$'(),;\-]+", part):
                break
            if not re.search(r"[%+/=?&#]", part):
                break
            url += part
            end += continuation.end()
        yield url, body[match.start() : end], match.start(), end


def extract_links(body, fields):
    for url, raw, start, end in url_tokens(body):
        parsed = re.fullmatch(r"https?://([^/?#]+)([^#]*)(?:#.*)?", url, re.IGNORECASE)
        if not parsed or "@" in parsed[1] or not re.fullmatch(r"[\w.-]+", parsed[1]):
            continue
        host, path = parsed[1].casefold(), parsed[2]
        line_start = body.rfind("\n", 0, start) + 1
        line_end = body.find("\n", end)
        line = body[line_start : line_end if line_end >= 0 else len(body)]
        preceding = "\n".join(body[:line_start].splitlines()[-3:])
        if host == "forms.gle" or (host == "docs.google.com" and path.startswith("/forms/")):
            name = "form_link"
        elif re.search(r"company website", line, re.IGNORECASE):
            name = "company_website"
        elif re.search(r"(?:^|/)(?:apply|careers?|jobs?)(?:/|$)", path, re.IGNORECASE) or (
            line.strip() == raw.strip() and DIRECT.search(preceding)
        ):
            name = "apply_link"
        else:
            continue
        candidate = field(name, raw, url)
        previous = fields[name]
        if previous["status"] == "unknown":
            fields[name] = candidate
        elif previous["normalized"] != url:
            fields[name] = conflict(name, [previous, candidate])
