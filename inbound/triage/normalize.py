import re

ZERO_WIDTH = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")
DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})


def normalize(text):
    return " ".join(text.translate(ZERO_WIDTH).translate(DASHES).split())


def normalize_subject(subject):
    return re.sub(r"^(?:(?:fwd|re):\s*)+", "", normalize(subject), flags=re.IGNORECASE)


def current_body(body):
    lines = []
    for line in body.splitlines():
        if re.match(
            r"\s*(?:On .+wrote:|-{2,}\s*(?:Original|Forwarded) message)", line, re.IGNORECASE
        ):
            break
        if not line.lstrip().startswith(">"):
            lines.append(line)
    return "\n".join(lines)
