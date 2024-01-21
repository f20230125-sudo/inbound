from copy import deepcopy


def field(name, raw="", normalized=None, status=None, source_text=None, **extra):
    status = status or ("found" if normalized is not None else "unknown")
    result = dict(
        name=name,
        raw=raw,
        normalized=normalized,
        status=status,
        source_text=raw if source_text is None else source_text,
        **extra,
    )
    if status == "unknown":
        result.setdefault("missing_reason", "Not stated")
    return result


def conflict(name, candidates):
    flattened = []
    for candidate in candidates:
        flattened.extend(candidate.get("candidates", [candidate]))
    unique = []
    for candidate in flattened:
        if not any(candidate == c for c in unique):
            unique.append(deepcopy(candidate))
    return field(
        name,
        unique[0]["raw"],
        status="conflicting",
        source_text=unique[0]["source_text"],
        candidates=unique,
    )


def stamp(record, identity, source="message", **extra):
    record["provenance"] = dict(
        message_id=identity, source=source, source_text=record["source_text"], **extra
    )
    for candidate in record.get("candidates", []):
        if "provenance" not in candidate:
            stamp(candidate, identity, source, **extra)
    return record
