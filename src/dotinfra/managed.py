"""Managed blocks: the parts of a CMDB's own files that dotinfra owns.

Files dotinfra writes into a CMDB (README.md, AGENTS.md, CLAUDE.md, .gitignore,
.gitattributes) wrap the tool-owned content in markers::

    <!-- dotinfra:managed:start v=0.2.0 -->
    ...
    <!-- dotinfra:managed:end -->

    # dotinfra:managed:start v=0.2.0
    ...
    # dotinfra:managed:end

``dotinfra migrate`` rewrites what is between the markers from the current
templates and never touches anything outside them, so users keep their own notes
above or below. Files written by dotinfra 0.1.x have no markers; see
:func:`refresh` for how they are adopted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .versioning import installed_version

MD, HASH = "md", "hash"
_MARKERS = {
    MD: ("<!-- dotinfra:managed:start v={v} -->", "<!-- dotinfra:managed:end -->"),
    HASH: ("# dotinfra:managed:start v={v}", "# dotinfra:managed:end"),
}
_START_RE = {
    MD: re.compile(r"^<!-- dotinfra:managed:start(?: v=(\S+))? -->[ \t]*$", re.M),
    HASH: re.compile(r"^# dotinfra:managed:start(?: v=(\S+))?[ \t]*$", re.M),
}
_END_RE = {
    MD: re.compile(r"^<!-- dotinfra:managed:end -->[ \t]*$", re.M),
    HASH: re.compile(r"^# dotinfra:managed:end[ \t]*$", re.M),
}

# Actions reported by refresh().
UNCHANGED = "unchanged"
UPDATED = "updated"          # block content refreshed
CREATED = "created"          # file did not exist
ADOPTED = "adopted"          # 0.1.x file identical to a known template render: replaced
INSERTED = "inserted"        # 0.1.x file edited by hand: block added on top, text kept


def style_for(name: str) -> str:
    return MD if name.endswith(".md") else HASH


@dataclass
class Block:
    start: int          # offset of the start marker line
    end: int            # offset just past the end marker line (and its newline)
    version: str | None
    content: str        # text between the marker lines


def find_block(text: str, style: str) -> Block | None:
    """The first managed block in ``text``; ``None`` if there is none (or it is unterminated)."""
    start = _START_RE[style].search(text)
    if not start:
        return None
    end = _END_RE[style].search(text, start.end())
    if not end:
        return None
    content_start = start.end() + 1 if text[start.end():start.end() + 1] == "\n" else start.end()
    stop = end.end() + 1 if text[end.end():end.end() + 1] == "\n" else end.end()
    return Block(start.start(), stop, start.group(1), text[content_start:end.start()])


def wrap(content: str, style: str, version: str | None = None) -> str:
    """``content`` between start/end markers (always newline-terminated)."""
    start, end = _MARKERS[style]
    body = content if content.endswith("\n") else content + "\n"
    return f"{start.format(v=version or installed_version())}\n{body}{end}\n"


def _normalise(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def matches_legacy(text: str, legacy_renders: list[str]) -> bool:
    """True when ``text`` equals one of the known 0.1.x renders (whitespace-insensitive at
    line ends). Renders may contain ``{{name}}``, which matches any single-line value."""
    current = _normalise(text)
    for render in legacy_renders:
        pattern = re.escape(_normalise(render)).replace(re.escape("{{name}}"), r"[^\n]*")
        if re.fullmatch(pattern, current):
            return True
    return False


def _dedupe_lines(user: str, owned_texts: list[str]) -> str:
    """Drop lines from ``user`` that dotinfra owns (in the new block or an old template).

    Only used for line-oriented dotfiles, where a repeated line means nothing new.
    """
    owned = {line.strip() for text in owned_texts for line in text.splitlines() if line.strip()}
    kept = [line for line in user.splitlines() if line.strip() not in owned]
    while kept and not kept[0].strip():
        kept.pop(0)
    return "\n".join(kept) + ("\n" if kept else "")


def refresh(text: str | None, content: str, style: str, *,
            legacy_renders: list[str] = ()) -> tuple[str, str]:
    """Return ``(new_text, action)`` with the managed block set to ``content``.

    - no file → a new file holding just the block (``created``);
    - a block exists → its content is replaced, text outside is kept byte for byte;
      the marker's ``v=`` only changes when the content does (``updated``/``unchanged``);
    - no block and the file equals a known 0.1.x render → replaced wholesale (``adopted``);
    - no block otherwise → the block goes on top and the user's text is kept below it
      (``inserted``); for dotfiles, lines the block now provides are dropped from below.
    """
    if text is None:
        return wrap(content, style), CREATED
    block = find_block(text, style)
    if block is not None:
        if _normalise(block.content) == _normalise(content):
            return text, UNCHANGED
        return text[:block.start] + wrap(content, style) + text[block.end:], UPDATED
    if not text.strip() or matches_legacy(text, list(legacy_renders)):
        return wrap(content, style), ADOPTED
    below = (_dedupe_lines(text, [content, *legacy_renders]) if style == HASH else text)
    separator = "\n" if below.strip() and style == MD else ""
    return wrap(content, style) + separator + below, INSERTED


def refresh_file(path: Path, content: str, *, legacy_renders: list[str] = (),
                 dry_run: bool = False) -> str:
    """:func:`refresh` applied to a file on disk; returns the action."""
    text = path.read_text(encoding="utf-8") if path.exists() else None
    new_text, action = refresh(text, content, style_for(path.name),
                               legacy_renders=legacy_renders)
    if not dry_run and new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return action
