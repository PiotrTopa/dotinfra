"""Section-aware three-way merge of component files, used by the git merge driver.

A component file is merged as structured data rather than as lines:

* frontmatter keys are merged one by one (lists are unioned, ``updated`` takes the max);
* the body is split into a preamble plus ``## H2`` sections, merged section by section;
* History/changelog sections are unioned entry by entry, newest first;
* only when both sides changed the same section differently does a line-level
  ``git merge-file`` run, and any conflict markers stay inside that section.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .frontmatter import FENCE, FrontmatterError, dump_entry, parse_document

OURS, BASE, THEIRS = "ours", "base", "theirs"
CONFLICT_RE = re.compile(r"^(<<<<<<<|>>>>>>>)( |$)", re.MULTILINE)
HISTORY_RE = re.compile(r"^(history|changelog|log)$", re.IGNORECASE)
_DATE_RE = re.compile(r"^\s*[-*+]\s+(\d{4}-\d{2}-\d{2})")
_H2_RE = re.compile(r"^## +(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_ABSENT = object()


@dataclass
class MergeResult:
    text: str
    conflicts: int

    @property
    def clean(self) -> bool:
        return self.conflicts == 0


def has_conflict_markers(text: str) -> bool:
    return bool(CONFLICT_RE.search(text))


def _markers(ours: str, theirs: str) -> str:
    """A conflict block; each side must be empty or end with a newline."""
    return f"<<<<<<< {OURS}\n{ours}=======\n{theirs}>>>>>>> {THEIRS}\n"


# --------------------------------------------------------------------------- line merge


def merge_lines(base: str, ours: str, theirs: str) -> MergeResult:
    """Classic line-level three-way merge via ``git merge-file`` (no repository needed)."""
    with tempfile.TemporaryDirectory(prefix="dotinfra-merge-") as tmp:
        paths = []
        for name, text in ((OURS, ours), (BASE, base), (THEIRS, theirs)):
            path = Path(tmp) / name
            path.write_text(text, encoding="utf-8")
            paths.append(str(path))
        result = subprocess.run(
            ["git", "merge-file", "-p", "-L", OURS, "-L", BASE, "-L", THEIRS, *paths],
            capture_output=True, text=True)
    if result.returncode < 0 or result.returncode > 127:
        raise RuntimeError(f"git merge-file failed: {result.stderr.strip()}")
    return MergeResult(result.stdout, result.returncode)


# --------------------------------------------------------------------------- frontmatter


def _merge_value(key: str, base, ours, theirs):
    """Three-way merge of one key; returns ``(value, conflicted)``. ``_ABSENT`` = deleted."""
    if ours == theirs:
        return ours, False
    if ours == base:
        return theirs, False
    if theirs == base:
        return ours, False
    if key == "updated" and _ABSENT not in (ours, theirs):
        return max(str(ours), str(theirs)), False
    if isinstance(ours, list) and isinstance(theirs, list):
        base_items = base if isinstance(base, list) else []
        merged = [x for x in ours if not (x in base_items and x not in theirs)]
        merged += [x for x in theirs if x not in merged and x not in base_items]
        return merged, False
    return None, True


def _merge_frontmatter(base_doc, ours_doc, theirs_doc) -> tuple[list[str], int]:
    """Merged frontmatter lines (no fences) and the number of conflicting keys.

    Keys whose merged value equals ours keep ours' raw lines, so comments survive.
    """
    base, ours, theirs = base_doc.meta, ours_doc.meta, theirs_doc.meta
    ours_raw = {entry.key: entry.raw for entry in ours_doc.entries}
    theirs_raw = {entry.key: entry.raw for entry in theirs_doc.entries}
    keys = list(ours) + [k for k in theirs if k not in ours]
    lines: list[str] = []
    conflicts = 0
    for key in keys:
        o, t, b = ours.get(key, _ABSENT), theirs.get(key, _ABSENT), base.get(key, _ABSENT)
        value, conflicted = _merge_value(key, b, o, t)
        if conflicted:
            conflicts += 1
            lines += _markers(_entry_text(key, o), _entry_text(key, t)).splitlines()
        elif value is _ABSENT:
            continue
        elif key in ours_raw and value == o:
            lines += ours_raw[key]
        elif key in theirs_raw and value == t:
            lines += theirs_raw[key]
        else:
            lines += dump_entry(key, value)
    return lines + ours_doc.trailing, conflicts


def _entry_text(key: str, value) -> str:
    return "" if value is _ABSENT else "".join(line + "\n" for line in dump_entry(key, value))


# --------------------------------------------------------------------------- body sections


def split_sections(body: str) -> list[tuple[str | None, str]]:
    """Split a body into ``[(None, preamble), (key, section_text), ...]``.

    Sections start at ``## Heading`` lines outside code fences. Keys are the heading
    text; repeated headings get ``#2``, ``#3``... suffixes.
    """
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    seen: dict[str, int] = {}
    in_fence = False
    for line in body.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _H2_RE.match(line.rstrip("\n"))
        if heading:
            name = heading.group(1)
            seen[name] = seen.get(name, 0) + 1
            key = name if seen[name] == 1 else f"{name}#{seen[name]}"
            sections.append((key, []))
        sections[-1][1].append(line)
    return [(key, "".join(lines)) for key, lines in sections]


def _is_history(key: str | None) -> bool:
    return key is not None and bool(HISTORY_RE.match(key.split("#")[0].strip()))


def _parse_history(text: str) -> tuple[str, list[str], list[str]]:
    """Split a History section into ``(heading_line, intro_lines, entries)``.

    An entry is a bullet line plus any indented continuation lines.
    """
    lines = text.splitlines(keepends=True)
    heading, intro, entries = (lines[0] if lines else ""), [], []
    for line in lines[1:]:
        line = _nl(line)
        if re.match(r"^[-*+]\s", line):
            entries.append(line)
        elif entries and line.strip() and line[:1] in " \t":
            entries[-1] += line
        elif line.strip():
            intro.append(line)
    return _nl(heading), intro, entries


def merge_history(base: str, ours: str, theirs: str) -> str:
    """Union of History entries (minus those deleted on one side), newest first."""
    heading, intro, ours_entries = _parse_history(ours)
    base_entries = set(_parse_history(base)[2])
    theirs_entries = _parse_history(theirs)[2]
    both = set(ours_entries) & set(theirs_entries)
    merged: list[str] = []
    for entry in ours_entries + theirs_entries:
        deleted_on_one_side = entry in base_entries and entry not in both
        if entry not in merged and not deleted_on_one_side:
            merged.append(entry)
    # newest first; on the same day, entries new since the base go above older ones
    dated = sorted((e for e in merged if _DATE_RE.match(e)),
                   key=lambda e: (_DATE_RE.match(e).group(1), e not in base_entries),
                   reverse=True)
    undated = [e for e in merged if not _DATE_RE.match(e)]
    text = heading + "\n" + ("".join(intro) + "\n" if intro else "") + "".join(dated + undated)
    return text + ("\n" if ours.endswith("\n\n") else "")


def _merge_section(key: str | None, base: str | None, ours: str | None,
                   theirs: str | None) -> tuple[str | None, int]:
    if ours == theirs:
        return ours, 0
    if ours == base:
        return theirs, 0
    if theirs == base:
        return ours, 0
    if ours is None or theirs is None:
        # deleted on one side, modified on the other: keep it, flag it
        return _markers(_nl(ours or ""), _nl(theirs or "")), 1
    if _is_history(key):
        return merge_history(base or "", ours, theirs), 0
    result = merge_lines(base or "", _nl(ours), _nl(theirs))
    return result.text, result.conflicts


def _nl(text: str) -> str:
    return text if not text or text.endswith("\n") else text + "\n"


def _order(ours_keys: list, theirs_keys: list) -> list:
    """Ours' order, with sections that only theirs has inserted after their predecessor."""
    order = list(ours_keys)
    for index, key in enumerate(theirs_keys):
        if key in order:
            continue
        previous = next((k for k in reversed(theirs_keys[:index]) if k in order), None)
        order.insert(order.index(previous) + 1 if previous in order else 0, key)
    return order


def merge_body(base: str, ours: str, theirs: str) -> MergeResult:
    b, o, t = (dict(split_sections(x)) for x in (base, ours, theirs))
    ours_keys = [k for k, _ in split_sections(ours)]
    theirs_keys = [k for k, _ in split_sections(theirs)]
    parts: list[str] = []
    conflicts = 0
    for key in _order(ours_keys, theirs_keys):
        text, n = _merge_section(key, b.get(key), o.get(key), t.get(key))
        conflicts += n
        if text:
            if parts and not parts[-1].endswith("\n"):
                parts[-1] += "\n"
            parts.append(text)
    return MergeResult("".join(parts), conflicts)


# --------------------------------------------------------------------------- whole files


def merge_text(base: str, ours: str, theirs: str) -> MergeResult:
    """Section-aware merge of one Markdown document (frontmatter optional)."""
    try:
        docs = [parse_document(text) for text in (base, ours, theirs)]
    except FrontmatterError:
        return merge_lines(base, ours, theirs)
    base_doc, ours_doc, theirs_doc = docs
    body = merge_body(base_doc.body, ours_doc.body, theirs_doc.body)
    if not any(doc.has_frontmatter for doc in docs):
        return body
    fm_lines, fm_conflicts = _merge_frontmatter(base_doc, ours_doc, theirs_doc)
    header = f"{FENCE}\n" + "".join(line + "\n" for line in fm_lines) + f"{FENCE}\n"
    return MergeResult(header + body.text, fm_conflicts + body.conflicts)


def merge_driver(base: Path, ours: Path, theirs: Path, path: str = "") -> int:
    """git merge driver: merge into ``ours`` in place; 0 = clean, 1 = conflicts remain."""
    texts = [p.read_text(encoding="utf-8") for p in (base, ours, theirs)]
    try:
        result = merge_text(*texts)
    except (RuntimeError, OSError, UnicodeError) as exc:
        print(f"dotinfra merge-driver: {path or ours}: {exc}; falling back to line merge",
              file=sys.stderr)
        result = merge_lines(*texts)
    ours.write_text(result.text, encoding="utf-8")
    return 0 if result.clean else 1


def conflict_blocks(text: str) -> list[tuple[int, str]]:
    """``(first_line, block_text)`` for every conflict block in ``text``."""
    blocks, current, start = [], None, 0
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("<<<<<<<"):
            current, start = [line], number
        elif current is not None:
            current.append(line)
            if line.startswith(">>>>>>>"):
                blocks.append((start, "\n".join(current)))
                current = None
    return blocks
