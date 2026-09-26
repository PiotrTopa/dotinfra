"""The infrastructure event log: outages, maintenance, changes, incidents, observations.

Component docs describe what *is*; what *happened* goes here. Two backends,
chosen by ``[events] backend`` in ``.dotinfra.toml``:

* ``grafana`` — each event is an organisation-wide annotation tagged ``dotinfra``,
  ``host:<component id>`` and ``type:<type>``; the fleet dashboard shows them on
  every time series, coloured by type.
* ``file`` — one line per event in ``events/<YYYY>.md`` inside the CMDB
  (:mod:`dotinfra.eventlog`), synced with it and union-merged.
* ``auto`` (default) — ``grafana`` when a monitoring service component or a
  Grafana URL is configured, else ``file``.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone

from . import DotinfraError
from . import eventlog
from .grafana import EVENT_TAG, EVENT_TYPES, client_from_context

VALID_TYPES = tuple(EVENT_TYPES)
BACKENDS = ("auto", "grafana", "file")

_RELATIVE = re.compile(r"^-?(\d+)\s*([smhdw])(?:\s*ago)?$", re.IGNORECASE)
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def parse_time(value: str, now: datetime | None = None) -> int:
    """Parse ``now``, a relative offset (``-2h``, ``30m ago``) or ISO 8601 into epoch ms.

    Naive timestamps are taken as local time; a trailing ``Z`` means UTC.
    Raises ValueError on anything else.
    """
    now = now or datetime.now(timezone.utc)
    s = value.strip()
    if s.lower() == "now":
        return int(now.timestamp() * 1000)
    m = _RELATIVE.match(s)
    if m:
        delta = timedelta(**{_UNITS[m.group(2).lower()]: int(m.group(1))})
        return int((now - delta).timestamp() * 1000)
    iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    for fmt in _FORMATS:
        try:
            dt = datetime.strptime(iso, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.astimezone()  # local time
        return int(dt.timestamp() * 1000)
    raise ValueError(
        f"cannot parse time {value!r}; use 'now', '-2h', '30m ago' or ISO 8601 like 2026-09-26T14:05Z")


def event_tags(host: str, etype: str) -> list[str]:
    return [EVENT_TAG, f"host:{host}", f"type:{etype}"]


def build_event(host: str, etype: str, text: str, time_ms: int, end_ms: int | None = None) -> dict:
    """Payload for ``POST /api/annotations``."""
    if etype not in EVENT_TYPES:
        raise ValueError(f"unknown event type {etype!r}; expected one of {', '.join(VALID_TYPES)}")
    if not text.strip():
        raise ValueError("event text is empty")
    payload = {"time": time_ms, "tags": event_tags(host, etype), "text": text.strip()}
    if end_ms is not None:
        if end_ms < time_ms:
            raise ValueError("--end is before --time")
        payload["timeEnd"] = end_ms
    return payload


def list_params(host: str | None = None, etype: str | None = None, limit: int = 50,
                since_ms: int | None = None) -> dict:
    """Query parameters for ``GET /api/annotations`` (tags are AND-ed by Grafana)."""
    tags = [EVENT_TAG]
    if host:
        tags.append(f"host:{host}")
    if etype:
        tags.append(f"type:{etype}")
    params = {"tags": tags, "limit": str(limit), "type": "annotation"}
    if since_ms is not None:
        params["from"] = str(since_ms)
    return params


def _split_tags(tags) -> tuple[str, str]:
    host = etype = ""
    for t in tags or []:
        if t.startswith("host:"):
            host = t[5:]
        elif t.startswith("type:"):
            etype = t[5:]
    return host, etype


def format_events(annotations: list[dict]) -> str:
    """Human-readable table, newest first."""
    if not annotations:
        return "no events"
    rows = sorted(annotations, key=lambda a: a.get("time", 0), reverse=True)
    lines = [f"{'ID':>7}  {'TIME (UTC)':<17}  {'HOST':<14}  {'TYPE':<12}  TEXT"]
    for a in rows:
        ts = datetime.fromtimestamp(a.get("time", 0) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        end = a.get("timeEnd")
        if end and end != a.get("time"):
            mins = int((end - a["time"]) / 60000)
            ts_note = f" ({mins} min)"
        else:
            ts_note = ""
        host, etype = _split_tags(a.get("tags"))
        text = (a.get("text") or "").replace("\n", " ")
        if len(text) > 90:
            text = text[:87] + "..."
        lines.append(f"{a.get('id', ''):>7}  {ts:<17}  {host:<14}  {etype:<12}  {text}{ts_note}")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def backend_of(ctx) -> str:
    """``"grafana"`` or ``"file"`` for this CMDB (resolving ``auto``)."""
    backend = str(ctx.config.get("events", "backend", "auto") or "auto").lower()
    if backend not in BACKENDS:
        raise DotinfraError(f"[events] backend must be one of {', '.join(BACKENDS)}, "
                            f"not {backend!r}")
    if backend != "auto":
        return backend
    if ctx.config.get("monitoring", "grafana_url"):
        return "grafana"
    service = str(ctx.config.get("monitoring", "service", "monitoring") or "")
    if service and any(c.id == service for c in ctx.components()):
        return "grafana"
    return "file"


def _cmd_add(args) -> int:
    from .context import get_context

    ctx = get_context(args)
    text = " ".join(args.text).strip() if args.text else ""
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    try:
        time_ms = parse_time(args.time)
        end_ms = parse_time(args.end) if args.end else None
        payload = build_event(args.host, args.type, text, time_ms, end_ms)
    except ValueError as e:
        raise DotinfraError(str(e)) from None
    known = {c.id for c in ctx.components()}
    if known and args.host not in known:
        print(f"warning: '{args.host}' is not a component id in {ctx.root}", file=sys.stderr)
    if backend_of(ctx) == "file":
        if any(sep in args.host for sep in ("·", " ")):
            raise DotinfraError(f"invalid host {args.host!r} for the file event log")
        event = eventlog.add_event(ctx.root, eventlog.Event(
            payload["time"], args.host, args.type, payload["text"], payload.get("timeEnd")))
        rel = eventlog.year_path(ctx.root, event.time_ms).relative_to(ctx.root).as_posix()
        print(f"event {event.id} added: {args.host} {args.type} ({rel}; "
              "`dotinfra sync` shares it)")
        return 0
    result = client_from_context(ctx).request("POST", "/api/annotations", payload)
    print(f"event {result.get('id', '?')} added: {args.host} {args.type}")
    return 0


def _cmd_list(args) -> int:
    from .context import get_context

    ctx = get_context(args)
    try:
        since = parse_time(args.since) if args.since else None
    except ValueError as e:
        raise DotinfraError(str(e)) from None
    if backend_of(ctx) == "file":
        chosen = eventlog.select(eventlog.load_events(ctx.root), host=args.host,
                                 etype=args.type, since_ms=since, limit=args.limit)
        data = [e.as_annotation() for e in chosen]
    else:
        data = client_from_context(ctx).request(
            "GET", "/api/annotations", params=list_params(args.host, args.type, args.limit, since))
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_events(data or []))
    return 0


def _cmd_rm(args) -> int:
    from .context import get_context

    ctx = get_context(args)
    if backend_of(ctx) == "file":
        try:
            event = eventlog.remove_event(ctx.root, str(args.id))
        except KeyError:
            raise DotinfraError(f"no event {args.id!r} in {eventlog.EVENTS_DIR}/ "
                                "(ids look like 2026.3; see `dotinfra event list`)") from None
        print(f"event {args.id} deleted: {event.line()[2:]}")
        return 0
    if not str(args.id).isdigit():
        raise DotinfraError(f"Grafana event ids are numbers, not {args.id!r}")
    client_from_context(ctx).request("DELETE", f"/api/annotations/{args.id}")
    print(f"event {args.id} deleted")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "event", help="infra event log (Grafana annotations or events/<YYYY>.md)",
        description="Record and list infrastructure events (types: "
                    f"{', '.join(VALID_TYPES)}). [events] backend in .dotinfra.toml picks "
                    "Grafana annotations or the file log events/<YYYY>.md in the CMDB; "
                    "auto = grafana when monitoring is configured, else file.")
    sub = p.add_subparsers(dest="event_cmd", metavar="COMMAND", required=True)

    a = sub.add_parser("add", help="record an event")
    a.add_argument("--host", required=True, metavar="ID", help="component id the event is about")
    a.add_argument("--type", required=True, choices=VALID_TYPES)
    a.add_argument("--time", default="now", help="'now' (default), '-2h', '30m ago' or ISO 8601")
    a.add_argument("--end", help="end time for events with a duration (outage, maintenance)")
    a.add_argument("text", nargs="*", help="what happened (or pipe it on stdin)")
    a.set_defaults(func=_cmd_add)

    ls = sub.add_parser("list", aliases=["ls"], help="list events, newest first")
    ls.add_argument("--host", metavar="ID")
    ls.add_argument("--type", choices=VALID_TYPES)
    ls.add_argument("--since", help="only events after this time ('-7d', ISO 8601)")
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--json", action="store_true", help="annotation-shaped JSON")
    ls.set_defaults(func=_cmd_list)

    rm = sub.add_parser("rm", help="delete an event by id")
    rm.add_argument("id", help="Grafana annotation id, or YEAR.N for the file backend")
    rm.set_defaults(func=_cmd_rm)
