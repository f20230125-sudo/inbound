"""A recursive literal parser for the portfolio's small TypeScript data grammar."""

import re


class Literals:
    def __init__(self, text, constants=None):
        self.text, self.pos, self.constants = text, 0, constants or {}

    def space(self):
        while self.pos < len(self.text):
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text.startswith("//", self.pos):
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end < 0 else end + 1
            elif self.text.startswith("/*", self.pos):
                end = self.text.find("*/", self.pos + 2)
                if end < 0:
                    raise ValueError("Unclosed comment")
                self.pos = end + 2
            else:
                break

    def take(self, char):
        self.space()
        if self.text[self.pos : self.pos + 1] != char:
            raise ValueError("Expected literal delimiter")
        self.pos += 1

    def string(self):
        quote = self.text[self.pos]
        self.pos += 1
        out = []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == quote:
                result = "".join(out)
                if quote == "`":

                    def replace(m):
                        if m[1] not in self.constants:
                            raise ValueError("Only file-defined GH substitution is supported")
                        return self.constants[m[1]]

                    result = re.sub(r"\$\{([^}]*)\}", replace, result)
                    if "${" in result:
                        raise ValueError("Unclosed interpolation")
                return result
            if char == "\\":
                if self.pos >= len(self.text):
                    break
                escape = self.text[self.pos]
                self.pos += 1
                if escape in ("n", "r", "t", "\\", '"', "'", "`", "/"):
                    out.append({"n": "\n", "r": "\r", "t": "\t"}.get(escape, escape))
                elif escape == "u":
                    digits = self.text[self.pos : self.pos + 4]
                    if not re.fullmatch("[0-9a-fA-F]{4}", digits):
                        raise ValueError("Invalid Unicode escape")
                    out.append(chr(int(digits, 16)))
                    self.pos += 4
                else:
                    raise ValueError("Unsupported string escape")
            else:
                out.append(char)
        raise ValueError("Unclosed string")

    def value(self, depth=0):
        if depth > 30:
            raise ValueError("Literal nesting limit")
        self.space()
        char = self.text[self.pos : self.pos + 1]
        if char and char in ('"', "'", "`"):
            return self.string()
        if char in ("[", "{"):
            mapping = char == "{"
            end = "}" if mapping else "]"
            self.pos += 1
            values = {} if mapping else []
            self.space()
            while self.text[self.pos : self.pos + 1] != end:
                if mapping:
                    self.space()
                    if self.text[self.pos : self.pos + 1] in ('"', "'"):
                        key = self.string()
                    else:
                        m = re.match(r"[A-Za-z_]\w*", self.text[self.pos :])
                        if not m:
                            raise ValueError("Expected object key")
                        key = m[0]
                        self.pos += len(key)
                    if key in values or key in {"__proto__", "constructor", "prototype"}:
                        raise ValueError("Unsafe or duplicate key")
                    self.take(":")
                    values[key] = self.value(depth + 1)
                else:
                    values.append(self.value(depth + 1))
                self.space()
                if self.text[self.pos : self.pos + 1] == end:
                    break
                self.take(",")
                self.space()
            self.take(end)
            return values
        m = re.match(r"(true|false|null)\b|-?\d+(?:\.\d+)?\b", self.text[self.pos :])
        if not m:
            raise ValueError("Only literal data is permitted")
        self.pos += len(m[0])
        return {"true": True, "false": False, "null": None}.get(m[0], m[0])


def parse_projects(text):
    gh = re.search(r"\bconst\s+GH\s*=\s*", text)
    constants = {}
    if gh:
        parser = Literals(text[gh.end() :])
        value = parser.value()
        parser.take(";")
        if not isinstance(value, str) or "${" in value:
            raise ValueError("GH must be a constant string")
        constants["GH"] = value
    start = re.search(r"export\s+const\s+projects\s*(?::[^=]+)?=\s*", text)
    if not start:
        raise ValueError("Missing project array")
    parser = Literals(text[start.end() :], constants)
    result = parser.value()
    parser.take(";")
    if not isinstance(result, list) or any(not isinstance(p, dict) for p in result):
        raise ValueError("Projects must be object literals")
    return result


def merge_projects(registry, projects):
    by_id = {p["id"]: p for p in projects}
    for project in registry["projects"]:
        data = by_id.get(project["id"])
        if data is None:
            continue
        for name in ("tagline", "pitch", "stack", "decisions"):
            if name in data and (data[name] or name not in ("pitch", "tagline")):
                project[name] = data[name]
        for name, url in (
            ("code_url", data.get("code")),
            ("live_url", (data.get("live") or {}).get("url")),
        ):
            if url:
                if not url.startswith("https://") or any(c in url for c in "\n\r{}\\"):
                    raise ValueError("Unsafe portfolio link")
                project[name] = url
        project["as_of"] = data.get("asOf", project.get("as_of"))
    return registry
