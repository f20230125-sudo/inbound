"""Bounded, nonrecursive Markdown snapshots; no executable metadata or link traversal."""

import hashlib
import json
import os
import stat
from contextlib import contextmanager

import yaml

MAX_FILES = 128
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
TYPES = {"user", "feedback", "project", "reference"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def is_link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


@contextmanager
def windows_handle(path, *, directory=False):
    """Pin the object against rename/replacement and validate BEFORE reading any bytes.

    OPEN_REPARSE_POINT opens the link itself rather than following the final component.
    Final-handle path verification also rejects a swapped ancestor junction.
    """
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    flags = 0x00200000 | (0x02000000 if directory else 0)  # OPEN_REPARSE / BACKUP_SEMANTICS
    handle = kernel.CreateFileW(
        str(path), 0x80 if directory else 0x80000000, 3 if directory else 1, None, 3, flags, None
    )
    if handle == wintypes.HANDLE(-1).value:
        raise OSError("Memory object unavailable")
    try:
        attributes = (wintypes.DWORD * 2)()
        if not kernel.GetFileInformationByHandleEx(
            handle, 9, attributes, ctypes.sizeof(attributes)
        ):
            raise OSError("Memory attributes unavailable")
        if attributes[0] & 0x400 or bool(attributes[0] & 0x10) != directory:
            raise ValueError("Memory links and nonregular files are not supported")
        final = ctypes.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, final, len(final), 0)
        if not 0 < length < len(final):
            raise ValueError("Memory path unavailable")
        actual = final.value.removeprefix("\\\\?\\")
        if os.path.normcase(actual) != os.path.normcase(str(path.absolute())):
            raise ValueError("Memory path escaped its configured root")
        yield handle
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def pinned_directory(path, *, create=False):
    if create and not path.exists():
        path.mkdir()  # parent is the configured data root, never recursively invented
    if is_link(path) or not path.is_dir():
        raise ValueError("Memory directory must be a real directory")
    if os.name == "nt":
        with windows_handle(path, directory=True):
            yield
    else:
        yield


def read_file(path, root):
    if path.parent != root or is_link(path) or not path.is_file():
        raise ValueError("Memory files must remain inside their root")
    before = path.stat()
    if before.st_size > MAX_FILE_BYTES:
        raise ValueError("Memory file exceeds size cap")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        with windows_handle(path) as handle:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.ReadFile.argtypes = [
                wintypes.HANDLE,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.LPVOID,
            ]
            payload = ctypes.create_string_buffer(MAX_FILE_BYTES + 1)
            size = wintypes.DWORD()
            if not kernel.ReadFile(handle, payload, len(payload), ctypes.byref(size), None):
                raise OSError("Memory read failed")
            data = payload.raw[: size.value]
    else:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Nonregular memory file")
            data = stream.read(MAX_FILE_BYTES + 1)
    after = path.stat()
    if len(data) > MAX_FILE_BYTES or signature(before) != signature(after):
        raise ValueError("Memory changed during read")
    return data


def signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def validate(value):
    if not isinstance(value, dict) or set(value) != {"name", "description", "type", "content"}:
        raise ValueError("Memory name, description, type and content required")
    for key, limit in (("name", 200), ("description", 2000), ("content", MAX_FILE_BYTES)):
        text = value[key]
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > limit:
            raise ValueError("Invalid memory text")
        if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
            raise ValueError("Control characters in memory")
    if not isinstance(value["type"], str) or value["type"] not in TYPES:
        raise ValueError("Unsupported memory type")
    return value


def parse(data):
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("Complete front matter required")
    end = lines.index("---", 1)
    front = "\n".join(lines[1:end])
    # A flat scalar map only. No tags, aliases, anchors, nested collections or duplicate keys.
    maps = 0
    for count, token in enumerate(yaml.scan(front)):
        if isinstance(token, yaml.tokens.BlockMappingStartToken):
            maps += 1
        if (
            count > 32
            or maps > 1
            or isinstance(
                token,
                (
                    yaml.tokens.AliasToken,
                    yaml.tokens.AnchorToken,
                    yaml.tokens.TagToken,
                    yaml.tokens.BlockSequenceStartToken,
                    yaml.tokens.FlowSequenceStartToken,
                    yaml.tokens.FlowMappingStartToken,
                ),
            )
        ):
            raise ValueError("Only a bounded scalar metadata map is supported")
    node = yaml.compose(front, Loader=yaml.BaseLoader)
    if not isinstance(node, yaml.MappingNode) or not 3 <= len(node.value) <= 4:
        raise ValueError("Memory metadata required")
    metadata = {}
    for key, value in node.value:
        if not isinstance(key, yaml.ScalarNode) or not isinstance(value, yaml.ScalarNode):
            # This is malformed external data, rather than a Python caller type error.
            raise ValueError("Memory metadata must contain scalar values")  # noqa: TRY004
        if key.value in metadata or key.value not in {"name", "description", "type", "source"}:
            raise ValueError("Duplicate or unsupported metadata")
        metadata[key.value] = value.value
    source = metadata.pop("source", None)
    if source is not None and (not source.strip() or len(source.encode()) > 512):
        raise ValueError("Invalid source identity")
    value = validate(metadata | {"content": "\n".join(lines[end + 1 :]).strip()})
    return value, source


def encode(document, source):
    validate(document)
    metadata = {k: document[k] for k in ("name", "description", "type")}
    if source is not None:
        metadata["source"] = source
    data = (
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n"
        + document["content"]
        + "\n"
    ).encode()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Memory file exceeds size cap")
    return data


def scan(settings, previous_roots=()):
    documents, present, total = [], [], 0
    manifests = {}
    for folder in ("memory", "memory-local"):
        root = settings.data_root / folder
        if not root.exists() and not root.is_symlink():
            if folder in previous_roots:
                raise ValueError("Previously published directory missing")
            continue
        present.append(folder)
        with pinned_directory(root):
            paths = []
            for path in root.iterdir():
                # Bound all directory entries, including unsupported files. Never recurse.
                paths.append(path)
                if len(paths) > MAX_FILES:
                    raise ValueError("Memory file count exceeds cap")
            before = {p.name: signature(p.lstat()) for p in paths}
            manifests[root] = (signature(root.stat()), before)
            for path in sorted(paths):
                if is_link(path):
                    raise ValueError("Memory links are not supported")
                if path.suffix.casefold() != ".md":
                    continue
                if len(documents) >= MAX_FILES:
                    raise ValueError("Memory file count exceeds cap")
                data = read_file(path, root)
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("Memory snapshot exceeds size cap")
                value, source = parse(data)
                identity = digest([folder, "source", source] if source else [folder, path.name])
                documents.append(
                    {
                        "identity": identity,
                        "file": f"{folder}/{path.name}",
                        "document": value,
                        "hash": digest(value),
                        "source_id": source,
                        "origin": "imported" if folder == "memory" else "local",
                    }
                )
            after = {}
            for path in root.iterdir():
                if len(after) >= MAX_FILES:
                    raise ValueError("Memory directory changed during scan")
                after[path.name] = signature(path.lstat())
            if before != after:
                raise ValueError("Memory directory changed during scan")
    # Recheck both roots after the complete read, so an edit to curated files while
    # reading local additions cannot publish a mixture of two filesystem snapshots.
    for folder in ("memory", "memory-local"):
        root = settings.data_root / folder
        if root not in manifests:
            if root.exists() or root.is_symlink():
                raise ValueError("Memory directory appeared during scan")
            continue
        with pinned_directory(root):
            after = {}
            for path in root.iterdir():
                if len(after) >= MAX_FILES:
                    raise ValueError("Memory directory changed during scan")
                after[path.name] = signature(path.lstat())
            if manifests[root] != (signature(root.stat()), after):
                raise ValueError("Memory snapshot changed during scan")
    identities = [d["identity"] for d in documents]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate source identity")
    return documents, present
