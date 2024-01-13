import re
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

MAX_BYTES = 10 * 1024 * 1024
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)


class SourceError(ValueError):
    pass


def provenance(value):
    if value not in {"private", "synthetic"}:
        raise SourceError("Import provenance must be explicitly private or synthetic")
    return value


def safe_attachment_path(root, value):
    parts = value.replace("\\", "/").split("/")
    if (
        not value
        or PureWindowsPath(value).drive
        or Path(value).is_absolute()
        or any(
            p in {"", ".", ".."}
            or p.endswith((".", " "))
            or RESERVED.match(p)
            or any(c in p for c in ':<>"|?*')
            or any(ord(c) < 32 for c in p)
            for p in parts
        )
    ):
        raise SourceError("Unsafe attachment path")
    root = Path(root).resolve()
    candidate = root.joinpath(*parts).resolve()
    if not candidate.is_relative_to(root):
        raise SourceError("Attachment escapes import root")
    return candidate


def read_bytes(path):
    if path.stat().st_size > MAX_BYTES:
        raise SourceError("Source file exceeds 10 MB")
    return path.read_bytes()


def iso_timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, TypeError) as exc:
        raise SourceError("Invalid timezone-aware timestamp") from exc
