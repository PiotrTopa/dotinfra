"""The file event backend: ``events/<YYYY>.md`` inside the CMDB.

One Markdown bullet per event, oldest first::

    - 2026-09-26T07:34Z · nas · maintenance · replaced disk 2
    - 2026-09-26T09:00Z/2026-09-26T09:40Z · gpu1 · outage · PSU tripped

The timestamp is UTC to the minute; an event with a duration carries its end
after a ``/`` (ISO 8601 interval). The files sync with the CMDB like any other
file, but they are not components: the loader, lint's component checks and
INDEX.md never look at ``events/``, and agents read them only on request.

Two devices appending to the same year file merge by union (see
:func:`merge_event_text`), so the log never conflicts.

This module has no dependency on Grafana or the CLI, so the merge driver can use it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EVENTS_DIR = "events"
SEP = " · "
_TS_FMT = "%Y-%m-%dT%H:%MZ"
_ENTRY_RE = re.compile(
    r"^[-*+]\s+(?P<start>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z)(?:/(?P<end>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z))?"
    r" · (?P<host>[^·]*?) · (?P<type>[^·]*?) · (?P<text>.*)$")


@dataclass
class Event:
    time_ms: int
    host: str
    type: str
    text: str
    end_ms: int | None = None
    id: str = ""  # "<year>.<n>": the n-th event (1-based) in events/<year>.md

    def line(self) -> str:
        stamp = format_ts(self.time_ms)
        if self.end_ms is not None and self.end_ms != self.time_ms:
            stamp += "/" + format_ts(self.end_ms)
        text = " ".join(self.text.split())
        return f"- {stamp}{SEP}{self.host}{SEP}{self.type}{SEP}{text}"

    def as_annotation(self) -> dict:
        """The same shape as a Grafana annotation, so both backends print alike."""
        data = {"id": self.id, "time": self.time_ms,
                "tags": ["dotinfra", f"host:{self.host}", f"type:{self.type}"], "text": self.text}
        if self.end_ms is not None:
            data["timeEnd"] = self.end_ms
        return data


def format_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(_TS_FMT)


def parse_ts(text: str) -> int:
    dt = datetime.strptime(text, _TS_FMT).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def parse_line(line: str) -> Event | None:
    """An :class:`Event` for one bullet line; ``None`` for anything else."""
    m = _ENTRY_RE.match(line.rstrip("\n"))
    if not m:
        return None
    end = m.group("end")
    return Event(parse_ts(m.group("start")), m.group("host").strip(), m.group("type").strip(),
                 m.group("text").strip(), parse_ts(end) if end else None)


def year_path(root: Path, time_ms: int) -> Path:
    year = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc).year
    return root / EVENTS_DIR / f"{year}.md"


def header(year: str) -> str:
    return (f"# Events {year}\n\n"
            "<!-- Written by `dotinfra event add` (file backend), oldest first. Not read by\n"
            "     agents by default; component docs describe the current state only. -->\n\n")


def _sort_key(line: str) -> str:
    m = _ENTRY_RE.match(line)
    return m.group("start") if m else ""


def add_event(root: Path, event: Event) -> Event:
    """Insert ``event`` into its year file in timestamp order; returns it with its id."""
    path = year_path(root, event.time_ms)
    year = path.stem
    text = path.read_text(encoding="utf-8") if path.is_file() else header(year)
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    new = event.line() + "\n"
    stamp = _sort_key(new)
    # after every entry with the same or an earlier start (stable for equal stamps)
    position = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        key = _sort_key(lines[i])
        if key and key <= stamp:
            position = i + 1
            break
        if key:
            position = i
    lines.insert(position, new)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    number = sum(1 for line in lines[:position + 1] if parse_line(line))
    event.id = f"{year}.{number}"
    return event


def load_events(root: Path) -> list[Event]:
    """Every event in ``events/*.md``, oldest first, each with its ``<year>.<n>`` id."""
    found: list[Event] = []
    directory = root / EVENTS_DIR
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.md")):
        number = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            event = parse_line(line)
            if event:
                number += 1
                event.id = f"{path.stem}.{number}"
                found.append(event)
    found.sort(key=lambda e: e.time_ms)
    return found


def select(events: list[Event], *, host: str | None = None, etype: str | None = None,
           since_ms: int | None = None, limit: int = 50) -> list[Event]:
    """The newest ``limit`` events matching the filters, newest first."""
    chosen = [e for e in events
              if (not host or e.host == host) and (not etype or e.type == etype)
              and (since_ms is None or (e.end_ms or e.time_ms) >= since_ms)]
    chosen.sort(key=lambda e: e.time_ms, reverse=True)
    return chosen[:limit] if limit and limit > 0 else chosen


def remove_event(root: Path, event_id: str) -> Event:
    """Delete event ``<year>.<n>``; raises KeyError when there is no such event."""
    year, _, number = event_id.partition(".")
    path = root / EVENTS_DIR / f"{year}.md"
    if not (year.isdigit() and number.isdigit()) or not path.is_file():
        raise KeyError(event_id)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    count = 0
    for i, line in enumerate(lines):
        event = parse_line(line)
        if event:
            count += 1
            if count == int(number):
                del lines[i]
                path.write_text("".join(lines), encoding="utf-8")
                event.id = event_id
                return event
    raise KeyError(event_id)


# --------------------------------------------------------------------------- merge


def is_event_file(path: str) -> bool:
    parts = Path(path).as_posix().split("/")
    return len(parts) == 2 and parts[0] == EVENTS_DIR and parts[1].endswith(".md")


def merge_event_text(base: str, ours: str, theirs: str) -> str:
    """Union of both sides' event lines, oldest first, minus lines one side deleted.

    Everything that is not an event line (the header, comments) comes from ours.
    Never conflicts: devices only append, and an event deleted on one side stays
    deleted unless the other side added it again.
    """
    def entries(text: str) -> list[str]:
        return [line.rstrip("\n") + "\n" for line in text.splitlines() if parse_line(line)]

    base_set = set(entries(base))
    ours_e, theirs_e = entries(ours), entries(theirs)
    both = set(ours_e) & set(theirs_e)
    merged: list[str] = []
    for line in ours_e + theirs_e:
        if line in merged or (line in base_set and line not in both):
            continue
        merged.append(line)
    merged.sort(key=_sort_key)  # stable: same-minute entries keep ours-then-theirs order
    head = [line.rstrip("\n") + "\n" for line in ours.splitlines() if not parse_line(line)]
    while head and not head[-1].strip():
        head.pop()
    prefix = "".join(head) + ("\n" if head else "")
    return prefix + "".join(merged)
