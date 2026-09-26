"""Prometheus targets and the monitoring bundle, derived from the CMDB.

``dotinfra monitoring targets`` turns every component's ``metrics: [job:port]``
into Prometheus file_sd JSON (one file per job). ``dotinfra monitoring render``
writes a complete, runnable docker-compose bundle (Prometheus + Grafana +
Pushgateway) with those targets and the fleet dashboard wired in.

The generation functions are pure (components in, data out) so they can be
tested without a CMDB on disk.
"""

from __future__ import annotations

import json
import sys
from importlib import resources
from pathlib import Path

SCRAPED_STATUSES = ("active", "degraded")
TARGETS_DIRNAME = "targets"
DASHBOARD_FILENAME = "dotinfra-fleet.json"
# Files in the targets directory that dotinfra never prunes (hand-written targets).
CUSTOM_PREFIX = "custom-"


# ---------------------------------------------------------------- pure helpers

def _meta(c) -> dict:
    return getattr(c, "meta", None) or {}


def component_address(c) -> str | None:
    """Scrape address of a component: ``address``, else ``ssh.host``."""
    addr = getattr(c, "address", None) or _meta(c).get("address")
    if addr:
        return str(addr)
    ssh = _meta(c).get("ssh")
    if isinstance(ssh, dict) and ssh.get("host"):
        return str(ssh["host"])
    return None


def _metrics(c) -> list[tuple[str, int]]:
    try:
        return list(c.metrics)
    except (ValueError, TypeError, AttributeError):
        return []


def _tags(c) -> list[str]:
    tags = getattr(c, "tags", None)
    if tags is None:
        tags = _meta(c).get("tags") or []
    return [str(t) for t in tags]


def _status(c) -> str | None:
    status = getattr(c, "status", None)
    return status if status is not None else _meta(c).get("status")


def host_role(c) -> str:
    """``fleet`` for components tagged ``fleet`` (dashboard rows), else ``infra``."""
    return "fleet" if "fleet" in _tags(c) else "infra"


def build_targets(components) -> tuple[dict[str, list[dict]], list[str]]:
    """Build file_sd target groups per job.

    Returns ``(targets, warnings)`` where ``targets`` maps job name to a list of
    file_sd target groups ``{"targets": ["addr:port"], "labels": {...}}``,
    sorted by host id. Only components with status active/degraded are scraped.
    """
    jobs: dict[str, list[dict]] = {}
    warnings: list[str] = []
    for c in components:
        metrics = _metrics(c)
        if not metrics:
            continue
        if _status(c) not in SCRAPED_STATUSES:
            continue
        addr = component_address(c)
        if not addr:
            warnings.append(f"{c.id}: has metrics but no address (or ssh.host); skipped")
            continue
        for job, port in metrics:
            group = {
                "targets": [f"{_hostport(addr, port)}"],
                "labels": {
                    "job": job,
                    "host": c.id,
                    "instance": f"{c.id}:{port}",
                    "role": host_role(c),
                    "kind": c.kind,
                },
            }
            jobs.setdefault(job, []).append(group)
    for groups in jobs.values():
        groups.sort(key=lambda g: (g["labels"]["host"], g["targets"][0]))
    return dict(sorted(jobs.items())), warnings


def _hostport(addr: str, port: int) -> str:
    if ":" in addr and not addr.startswith("["):  # bare IPv6
        return f"[{addr}]:{port}"
    return f"{addr}:{port}"


def render_targets_json(groups: list[dict]) -> str:
    """Deterministic JSON text for one file_sd file."""
    return json.dumps(groups, indent=2, sort_keys=False) + "\n"


def write_targets(targets: dict[str, list[dict]], outdir: Path) -> tuple[list[Path], list[Path]]:
    """Write ``<job>.json`` per job into *outdir*; prune stale job files.

    Only files that look like dotinfra's own output (a file_sd list of target
    groups) are pruned, and ``custom-*.json`` never is. Returns (written, removed).
    Files are replaced atomically so Prometheus never reads a half-written file.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    written, removed = [], []
    wanted = {f"{job}.json" for job in targets}
    for job, groups in targets.items():
        path = outdir / f"{job}.json"
        _atomic_write(path, render_targets_json(groups))
        written.append(path)
    for path in sorted(outdir.glob("*.json")):
        if (path.name not in wanted and not path.name.startswith(CUSTOM_PREFIX)
                and _looks_generated(path)):
            path.unlink()
            removed.append(path)
    return written, removed


def _looks_generated(path: Path) -> bool:
    """True for a file_sd file of the shape ``write_targets`` produces (or an empty list)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, list) and all(
        isinstance(group, dict) and "targets" in group and "labels" in group for group in data)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def bundle_source():
    """Traversable pointing at the packaged bundle template."""
    return resources.files("dotinfra") / "bundle"


def _copy_tree(src, dst: Path, force: bool, created: list[Path], kept: list[Path]) -> None:
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            if entry.name == "__pycache__":
                continue
            target.mkdir(parents=True, exist_ok=True)
            _copy_tree(entry, target, force, created, kept)
            continue
        data = entry.read_bytes()
        if target.exists():
            if target.read_bytes() == data:
                continue  # already current
            if not force:
                kept.append(target)
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        created.append(target)


def render_bundle(components, outdir: Path, *, name: str = "home", force: bool = False,
                  source=None) -> dict:
    """Write the full monitoring bundle into *outdir*.

    Static template files are copied only when missing (or with ``force``) so
    local edits survive; targets and the dashboard are always regenerated.
    Returns a report dict with lists of paths and warnings.
    """
    from . import grafana

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    kept: list[Path] = []
    _copy_tree(source if source is not None else bundle_source(), outdir, force, created, kept)

    targets, warnings = build_targets(components)
    written, removed = write_targets(targets, outdir / TARGETS_DIRNAME)

    dash_dir = outdir / "grafana" / "dashboards"
    dash_dir.mkdir(parents=True, exist_ok=True)
    dash_path = dash_dir / DASHBOARD_FILENAME
    _atomic_write(dash_path, grafana.dashboard_json(grafana.build_fleet_dashboard(name=name)))

    return {
        "outdir": outdir,
        "created": created,
        "kept": kept,
        "targets": written,
        "removed": removed,
        "dashboard": dash_path,
        "warnings": warnings,
        "jobs": {job: len(groups) for job, groups in targets.items()},
    }


# ---------------------------------------------------------------- CLI

def _bundle_dir(ctx) -> Path:
    return Path(ctx.config.get("monitoring", "bundle_dir", "~/dotinfra-monitoring")).expanduser()


def _cmdb_name(ctx) -> str:
    return ctx.config.get("cmdb", "name", "home") or "home"


def _cmd_targets(args) -> int:
    from .context import get_context

    ctx = get_context(args)
    targets, warnings = build_targets(ctx.components())
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.stdout:
        print(json.dumps(targets, indent=2))
        return 0
    outdir = Path(args.output).expanduser() if args.output else _bundle_dir(ctx) / TARGETS_DIRNAME
    written, removed = write_targets(targets, outdir)
    for path in written:
        print(f"wrote {path} ({len(targets[path.stem])} target(s))")
    for path in removed:
        print(f"removed stale {path}")
    if not written:
        print("no components with `metrics:` and status active/degraded; nothing to scrape")
    return 0


def _cmd_render(args) -> int:
    from .context import get_context

    ctx = get_context(args)
    outdir = Path(args.output).expanduser() if args.output else _bundle_dir(ctx)
    report = render_bundle(ctx.components(), outdir, name=_cmdb_name(ctx), force=args.force)
    for w in report["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    print(f"bundle: {report['outdir']}")
    print(f"  template files written: {len(report['created'])}, kept (local edits): {len(report['kept'])}"
          + ("  (use --force to overwrite)" if report["kept"] else ""))
    jobs = ", ".join(f"{job}={n}" for job, n in report["jobs"].items()) or "none"
    print(f"  targets: {jobs}")
    print(f"  dashboard: {report['dashboard']}")
    env = report["outdir"] / ".env"
    print("next:")
    if not env.exists():
        print(f"  cd {report['outdir']} && cp .env.example .env   # set GRAFANA_ADMIN_PASSWORD")
    print(f"  cd {report['outdir']} && docker compose up -d")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "monitoring",
        help="Prometheus targets and the monitoring bundle",
        description="Generate Prometheus file_sd targets and the Prometheus+Grafana bundle from the CMDB.",
    )
    sub = p.add_subparsers(dest="monitoring_cmd", metavar="COMMAND", required=True)

    t = sub.add_parser("targets", help="write Prometheus file_sd JSON, one file per job")
    t.add_argument("--output", metavar="DIR",
                   help="target directory (default: <monitoring.bundle_dir>/targets)")
    t.add_argument("--stdout", action="store_true", help="print all jobs as JSON instead of writing files")
    t.set_defaults(func=_cmd_targets)

    r = sub.add_parser("render", help="write the full monitoring bundle (compose, prometheus, grafana, targets, dashboard)")
    r.add_argument("--output", metavar="DIR", help="bundle directory (default: monitoring.bundle_dir)")
    r.add_argument("--force", action="store_true", help="overwrite locally edited template files")
    r.set_defaults(func=_cmd_render)
