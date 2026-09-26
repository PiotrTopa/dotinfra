"""Components: one Markdown file per piece of infrastructure."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import FrontmatterError, parse_document

KINDS = {"servers": "server", "networks": "network", "domains": "domain",
         "routers": "router", "services": "service", "devices": "device"}
FOLDERS = {kind: folder for folder, kind in KINDS.items()}
STATUSES = ("active", "planned", "degraded", "retired")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
KNOWN_KEYS = ("id", "kind", "title", "status", "role", "tags", "address", "os", "ssh",
              "metrics", "secrets", "depends_on", "runs_on", "url", "facts", "updated")
SSH_KEYS = ("user", "host", "port", "jump", "key")
_H1_RE = re.compile(r"^# +(.+?)\s*#*\s*$", re.MULTILINE)


def as_list(value) -> list:
    """Normalise a frontmatter value that should be a list (``None`` → ``[]``, scalar → ``[x]``)."""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def parse_metric(entry) -> tuple[str, int] | None:
    """``"node:9100"`` → ``("node", 9100)``; ``None`` when malformed."""
    job, sep, port = str(entry).partition(":")
    if not (sep and job and port.isdigit() and 0 < int(port) < 65536):
        return None
    return job, int(port)


@dataclass
class Component:
    id: str
    kind: str
    path: Path
    meta: dict
    body: str
    root: Path = field(repr=False, default=Path("."))
    lines: dict[str, int] = field(repr=False, default_factory=dict)

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.id)

    @property
    def status(self) -> str | None:
        status = self.meta.get("status")
        return None if status is None else str(status)

    @property
    def tags(self) -> list[str]:
        return [str(tag) for tag in as_list(self.meta.get("tags"))]

    @property
    def address(self) -> str | None:
        address = self.meta.get("address")
        return None if address is None else str(address)

    @property
    def ssh(self) -> dict:
        ssh = self.meta.get("ssh")
        return ssh if isinstance(ssh, dict) else {}

    @property
    def metrics(self) -> list[tuple[str, int]]:
        return [m for m in map(parse_metric, as_list(self.meta.get("metrics"))) if m]

    def rel(self) -> str:
        try:
            return self.path.relative_to(self.root).as_posix()
        except ValueError:
            return self.path.as_posix()

    def line_of(self, key: str) -> int:
        """Line number of a frontmatter key (1 when unknown), for lint messages."""
        return self.lines.get(key, 1)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "path": self.rel(), "meta": self.meta}


def component_files(root: Path) -> list[Path]:
    files = []
    for folder in KINDS:
        directory = root / folder
        if directory.is_dir():
            files += [p for p in directory.rglob("*.md") if not p.name.endswith(".local.md")]
    return sorted(files)


def load_component(path: Path, root: Path) -> Component:
    """Parse one component file. Raises :class:`FrontmatterError` on bad frontmatter."""
    rel = path.relative_to(root)
    doc = parse_document(path.read_text(encoding="utf-8"), source=rel.as_posix())
    meta = dict(doc.meta)
    kind = KINDS[rel.parts[0]]
    component_id = str(meta.get("id") or path.stem.lower())
    meta.setdefault("id", component_id)
    meta.setdefault("kind", kind)
    if not meta.get("title"):
        h1 = _H1_RE.search(doc.body)
        meta["title"] = h1.group(1) if h1 else component_id
    return Component(id=component_id, kind=kind, path=path.resolve(), meta=meta, body=doc.body,
                     root=root.resolve(), lines=doc.lines)


def scan_cmdb(root: Path) -> tuple[list[Component], list[FrontmatterError]]:
    """Load every component; unparseable files are returned as errors instead of raising."""
    components, errors = [], []
    for path in component_files(root):
        try:
            components.append(load_component(path, root))
        except FrontmatterError as exc:
            errors.append(exc)
        except UnicodeDecodeError:
            errors.append(FrontmatterError("not valid UTF-8 text", 1,
                                           path.relative_to(root).as_posix()))
    components.sort(key=lambda c: (c.kind, c.id))
    return components, errors


def load_cmdb(root: Path, *, strict: bool = False) -> list[Component]:
    """All components sorted by ``(kind, id)``.

    With ``strict`` the first unparseable file raises; otherwise such files are skipped
    and their messages recorded in ``load_cmdb.errors``.
    """
    components, errors = scan_cmdb(root)
    if strict and errors:
        raise errors[0]
    load_cmdb.errors = [str(error) for error in errors]
    return components


load_cmdb.errors = []


def by_id(components) -> dict[str, Component]:
    return {component.id: component for component in components}
