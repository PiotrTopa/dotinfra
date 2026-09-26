"""A small, strict YAML-subset parser for component frontmatter (no PyYAML).

Supported (see docs/spec.md §3.1):

* ``key: scalar`` — strings, quoted strings, ``true``/``false``, integers, ``null``/``~``/empty
* ``key: [a, b, "c d"]`` — inline lists of scalars
* ``key:`` followed by ``  - item`` lines — block lists of scalars
* ``key:`` followed by ``  sub: scalar`` / ``  sub: [list]`` lines — one-level maps
* ``# comments`` on their own line and after values

Everything else is rejected with a :class:`FrontmatterError` carrying a line number,
so a typo never silently turns into wrong data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import DotinfraError

FENCE = "---"
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")
_INT_RE = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")
_NULLS = {"", "~", "null", "Null", "NULL"}
_BOOLS = {"true": True, "True": True, "TRUE": True, "false": False, "False": False, "FALSE": False}
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}


class FrontmatterError(DotinfraError):
    """A frontmatter syntax error; ``str()`` gives ``source:line: message``."""

    def __init__(self, message: str, line: int | None = None, source: str | None = None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.source = source

    def __str__(self) -> str:
        where = ":".join(str(part) for part in (self.source, self.line) if part is not None)
        return f"{where}: {self.message}" if where else self.message


@dataclass
class Entry:
    """One top-level key, with the raw lines it came from (leading comments included)."""

    key: str
    value: object
    line: int  # 1-based line number of the key within the whole document
    raw: list[str] = field(default_factory=list)


@dataclass
class Document:
    entries: list[Entry]
    trailing: list[str]  # comment/blank lines after the last key
    body: str
    has_frontmatter: bool

    @property
    def meta(self) -> dict:
        return {entry.key: entry.value for entry in self.entries}

    @property
    def lines(self) -> dict[str, int]:
        return {entry.key: entry.line for entry in self.entries}


# --------------------------------------------------------------------------- parsing


def parse(text: str, source: str | None = None) -> tuple[dict, str]:
    """Split a document into ``(meta, body)``. A document without frontmatter gives ``{}``."""
    doc = parse_document(text, source)
    return doc.meta, doc.body


def parse_document(text: str, source: str | None = None) -> Document:
    text = text.replace("\r\n", "\n").lstrip("\ufeff")
    lines = text.split("\n")
    if lines[0].rstrip() != FENCE:
        return Document([], [], text, has_frontmatter=False)
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].rstrip() in (FENCE, "..."))
    except StopIteration:
        raise FrontmatterError("unterminated frontmatter (no closing '---')", 1, source) from None
    body = "\n".join(lines[end + 1:])
    try:
        entries, trailing = _parse_block(lines[1:end], first_line=2)
    except FrontmatterError as exc:
        exc.source = source
        raise
    return Document(entries, trailing, body, has_frontmatter=True)


def _is_filler(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _parse_block(lines: list[str], first_line: int) -> tuple[list[Entry], list[str]]:
    entries: list[Entry] = []
    seen: set[str] = set()
    pending: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        lineno = first_line + i
        if _is_filler(line):
            pending.append(line)
            i += 1
            continue
        if line[0] in " \t":
            raise FrontmatterError("unexpected indentation (keys must start at column 0)", lineno)
        match = KEY_RE.match(line.rstrip())
        if not match:
            raise FrontmatterError(f"expected 'key: value', got {line.strip()!r}", lineno)
        key = match.group(1)
        if key in seen:
            raise FrontmatterError(f"duplicate key {key!r}", lineno)
        seen.add(key)
        value_text = _strip_comment(match.group(2) or "", lineno)
        j = i + 1
        if value_text:
            value = _parse_value(value_text, lineno)
        else:
            while j < len(lines) and (lines[j][:1] in (" ", "\t") or _is_filler(lines[j])):
                j += 1
            while j > i + 1 and _is_filler(lines[j - 1]):
                j -= 1  # trailing comments belong to the next key
            value = _parse_children(lines[i + 1:j], lineno + 1)
        entries.append(Entry(key, value, lineno, pending + lines[i:j]))
        pending = []
        i = j
    return entries, pending


def _parse_children(lines: list[str], first_line: int):
    content = [(first_line + n, line) for n, line in enumerate(lines) if not _is_filler(line)]
    if not content:
        return None
    for lineno, line in content:
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise FrontmatterError("tabs are not allowed for indentation", lineno)
    if content[0][1].lstrip().startswith("-"):
        return [_parse_list_item(line, lineno) for lineno, line in content]
    return _parse_map(content)


def _parse_list_item(line: str, lineno: int):
    stripped = line.strip()
    if not (stripped == "-" or stripped.startswith("- ")):
        raise FrontmatterError("mixed list items and keys under one key", lineno)
    text = _strip_comment(stripped[1:].strip(), lineno)
    if KEY_RE.match(text) and not text.startswith(("'", '"')):
        raise FrontmatterError("lists of maps are not supported (quote the item if it is text)",
                               lineno)
    if text.startswith(("[", "{", "- ")):
        raise FrontmatterError("nested collections inside a list are not supported", lineno)
    return _parse_scalar(text, lineno)


def _parse_map(content: list[tuple[int, str]]) -> dict:
    indent = len(content[0][1]) - len(content[0][1].lstrip())
    result: dict = {}
    for lineno, line in content:
        if len(line) - len(line.lstrip()) != indent:
            raise FrontmatterError("maps nested deeper than one level are not supported", lineno)
        match = KEY_RE.match(line.strip())
        if not match:
            raise FrontmatterError(f"expected 'sub: value' inside a map, got {line.strip()!r}",
                                   lineno)
        key = match.group(1)
        if key in result:
            raise FrontmatterError(f"duplicate key {key!r}", lineno)
        value = _parse_value(_strip_comment(match.group(2) or "", lineno), lineno)
        if isinstance(value, dict):
            raise FrontmatterError("maps nested deeper than one level are not supported", lineno)
        result[key] = value
    return result


def _parse_value(text: str, lineno: int):
    if not text:
        return None
    if text.startswith("["):
        return _parse_inline_list(text, lineno)
    if text == "{}":
        return {}
    if text.startswith("{"):
        raise FrontmatterError("inline maps are not supported; use an indented block", lineno)
    if text[0] in "|>":
        raise FrontmatterError("multi-line strings are not supported", lineno)
    if text[0] in "&*!":
        raise FrontmatterError("anchors, aliases and tags are not supported", lineno)
    return _parse_scalar(text, lineno)


def _parse_inline_list(text: str, lineno: int) -> list:
    if not text.endswith("]"):
        raise FrontmatterError("unterminated inline list (missing ']')", lineno)
    inner = text[1:-1].strip()
    if not inner:
        return []
    items = _split_outside_quotes(inner, ",")
    if items and not items[-1].strip():
        items.pop()  # tolerate a trailing comma
    values = []
    for item in items:
        item = item.strip()
        if not item:
            raise FrontmatterError("empty item in inline list", lineno)
        if item[0] in "[{":
            raise FrontmatterError("nested collections inside a list are not supported", lineno)
        values.append(_parse_scalar(item, lineno))
    return values


def _parse_scalar(text: str, lineno: int):
    if text[:1] in ("'", '"'):
        return _unquote(text, lineno)
    if text in _NULLS:
        return None
    if text in _BOOLS:
        return _BOOLS[text]
    if _INT_RE.match(text):
        return int(text)
    return text


def _unquote(text: str, lineno: int) -> str:
    quote = text[0]
    out: list[str] = []
    i = 1
    while i < len(text):
        ch = text[i]
        if quote == '"' and ch == "\\" and i + 1 < len(text):
            out.append(_ESCAPES.get(text[i + 1], "\\" + text[i + 1]))
            i += 2
            continue
        if ch == quote:
            if quote == "'" and text[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            if text[i + 1:].strip():
                raise FrontmatterError(f"unexpected text after quoted string: {text[i + 1:]!r}",
                                       lineno)
            return "".join(out)
        out.append(ch)
        i += 1
    raise FrontmatterError("unterminated quoted string", lineno)


def _scan(text: str):
    """Yield ``(index, char, inside_quotes)`` handling both quote styles."""
    quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if quote == '"' and ch == "\\":
                yield i, ch, True
                i += 2
                continue
            if ch == quote:
                quote = None
            yield i, ch, True
        else:
            if ch in "'\"" and (i == 0 or text[i - 1] in " \t,["):
                quote = ch
                yield i, ch, True
            else:
                yield i, ch, False
        i += 1


def _strip_comment(text: str, lineno: int) -> str:
    for i, ch, quoted in _scan(text):
        if ch == "#" and not quoted and (i == 0 or text[i - 1] in " \t"):
            return text[:i].strip()
    return text.strip()


def _split_outside_quotes(text: str, sep: str) -> list[str]:
    parts, start = [], 0
    for i, ch, quoted in _scan(text):
        if ch == sep and not quoted:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


# --------------------------------------------------------------------------- dumping


def dump(meta: dict) -> str:
    """Serialise ``meta`` in the supported subset (without ``---`` fences), keys in order."""
    return "".join(line + "\n" for key, value in meta.items() for line in dump_entry(key, value))


def render(meta: dict, body: str) -> str:
    """A whole document: frontmatter fences, the dumped ``meta``, then ``body``."""
    return f"{FENCE}\n{dump(meta)}{FENCE}\n{body}"


def dump_entry(key: str, value) -> list[str]:
    if not KEY_RE.match(f"{key}:"):
        raise ValueError(f"invalid frontmatter key: {key!r}")
    if isinstance(value, dict):
        if not value:
            return [f"{key}: {{}}"]
        lines = [f"{key}:"]
        for sub, subvalue in value.items():
            if isinstance(subvalue, dict):
                raise ValueError(f"{key}.{sub}: maps nested deeper than one level "
                                 "cannot be written")
            lines.append(f"  {sub}:" + _dump_inline(subvalue, lead=" "))
        return lines
    return [f"{key}:" + _dump_inline(value, lead=" ")]


def _dump_inline(value, lead: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return lead + "[" + ", ".join(dump_scalar(v, in_list=True) for v in value) + "]"
    if isinstance(value, dict):
        raise ValueError("maps are only allowed at the top level")
    return lead + dump_scalar(value)


def dump_scalar(value, in_list: bool = False) -> str:
    """Render one scalar so that :func:`parse` reads back the same value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if _needs_quotes(text, in_list):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return '"' + escaped.replace("\n", "\\n").replace("\t", "\\t") + '"'
    return text


def _needs_quotes(text: str, in_list: bool) -> bool:
    return (
        text in _NULLS
        or text in _BOOLS
        or bool(_INT_RE.match(text))
        or text != text.strip()
        or text[0] in "[]{}&*!|>'\"%@`#,?"
        or text.startswith("- ")
        or text == "-"
        or ": " in text
        or " #" in text
        or text.endswith(":")
        or "\n" in text
        or "\t" in text
        or (in_list and any(ch in text for ch in ",[]"))
    )


# --------------------------------------------------------------------------- editing


def replace_keys(text: str, updates: dict, remove: tuple[str, ...] | list[str] = ()) -> str:
    """Set/remove top-level keys in a document, leaving every other line untouched.

    Comments attached to untouched keys survive; a trailing ``# comment`` on a replaced
    single-line key is kept. New keys are appended after the existing ones.
    """
    doc = parse_document(text)
    out: list[str] = []
    for entry in doc.entries:
        if entry.key in remove:
            continue
        if entry.key in updates:
            out.extend(_replace_entry(entry, updates[entry.key]))
        else:
            out.extend(entry.raw)
    existing = {entry.key for entry in doc.entries}
    for key, value in updates.items():
        if key not in existing and key not in remove:
            out.extend(dump_entry(key, value))
    out.extend(doc.trailing)
    body = doc.body if doc.has_frontmatter else "\n" + doc.body.lstrip("\n")
    return f"{FENCE}\n" + "".join(line + "\n" for line in out) + f"{FENCE}\n" + body


def _replace_entry(entry: Entry, value) -> list[str]:
    key_index = next(i for i, line in enumerate(entry.raw) if KEY_RE.match(line.rstrip()))
    leading = entry.raw[:key_index]
    new = dump_entry(entry.key, value)
    original = entry.raw[key_index]
    comment = _trailing_comment(original)
    if comment and len(new) == 1:
        column = original.rindex(comment)  # keep comments aligned where they were
        new = [new[0].ljust(column) if len(new[0]) < column else f"{new[0]}  "]
        new[0] += comment
    return leading + new


def _trailing_comment(line: str) -> str:
    match = KEY_RE.match(line.rstrip())
    rest = (match.group(2) or "") if match else ""
    stripped = _strip_comment(rest, 0)
    comment = rest.strip()[len(stripped):].strip()
    return comment if comment.startswith("#") else ""
