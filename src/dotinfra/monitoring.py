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
import re
import sys
import urllib.error
import urllib.request
from importlib import resources
from pathlib import Path

from . import DotinfraError

SCRAPED_STATUSES = ("active", "degraded")
TARGETS_DIRNAME = "targets"
DASHBOARD_FILENAME = "dotinfra-fleet.json"
# Files in the targets directory that dotinfra never prunes (hand-written targets).
CUSTOM_PREFIX = "custom-"


# ---------------------------------------------------------------- pure helpers

def component_address(c) -> str | None:
    """Scrape address of a component: ``address``, else ``ssh.host``."""
    addr = c.address or c.ssh.get("host")
    return str(addr) if addr else None


def host_role(c) -> str:
    """``fleet`` for components tagged ``fleet`` (dashboard rows), else ``infra``."""
    return "fleet" if "fleet" in c.tags else "infra"


LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
RESERVED_LABELS = ("job", "instance")


def extra_labels(c) -> dict[str, str]:
    """Valid entries of the component's ``labels:`` map (extra/overriding target labels).

    ``job`` and ``instance`` are derived and cannot be overridden; ``host``
    replaces the id in both ``host`` and ``instance`` (keeps existing series names).
    """
    raw = c.meta.get("labels")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()
            if LABEL_NAME.match(str(k)) and k not in RESERVED_LABELS and not str(k).startswith("__")
            and v is not None}


def build_targets(components) -> tuple[dict[str, list[dict]], list[str]]:
    """Build file_sd target groups per job.

    Returns ``(targets, warnings)`` where ``targets`` maps job name to a list of
    file_sd target groups ``{"targets": ["addr:port"], "labels": {...}}``,
    sorted by host id. Only components with status active/degraded are scraped.
    """
    jobs: dict[str, list[dict]] = {}
    warnings: list[str] = []
    for c in components:
        metrics = c.metrics
        if not metrics or c.status not in SCRAPED_STATUSES:
            continue
        addr = component_address(c)
        if not addr:
            warnings.append(f"{c.id}: has metrics but no address (or ssh.host); skipped")
            continue
        extra = extra_labels(c)
        host = extra.get("host", c.id)
        for job, port in metrics:
            labels = {"job": job, "host": host, "instance": f"{host}:{port}",
                      "role": host_role(c), "kind": c.kind}
            labels.update((k, v) for k, v in extra.items() if k != "host")
            group = {"targets": [f"{_hostport(addr, port)}"], "labels": labels}
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


# ---------------------------------------------------------------- where does it run

DEFAULT_GRAFANA = "http://localhost:3000"
DEFAULT_PROMETHEUS = "http://localhost:9090"
GRAFANA_PORT, PROMETHEUS_PORT = 3000, 9090


def _url_host(address: str) -> str:
    return f"[{address}]" if ":" in address and not address.startswith("[") else address


def monitoring_endpoints(ctx, *, warn: bool = True,
                         need: tuple[str, ...] = ("grafana", "prometheus")
                         ) -> tuple[str, str, str | None]:
    """``(grafana_url, prometheus_url, host_component_id)`` for this CMDB.

    Explicit ``[monitoring] grafana_url`` / ``prometheus_url`` (shared or in
    ``.dotinfra.local.toml``) win. Otherwise they come from the ``[monitoring] service``
    component: ``url`` → Grafana, ``prometheus_url`` → Prometheus, else
    ``http://<address>:3000`` / ``:9090``, where the address is the service's own
    ``address`` or that of its ``runs_on`` server. Without any of that: localhost
    defaults, with a warning on stderr for the endpoints in ``need``. The host is the
    service's ``runs_on``.
    """
    get = ctx.config.get
    grafana = get("monitoring", "grafana_url")
    prometheus = get("monitoring", "prometheus_url")
    service_id = str(get("monitoring", "service", "monitoring") or "")
    components = {c.id: c for c in ctx.components()}
    service = components.get(service_id)
    host_id = None
    address = None
    if service is not None:
        host_id = service.meta.get("runs_on") or None
        address = service.address
        if not address and host_id and host_id in components:
            address = components[host_id].address
    if not grafana:
        grafana = (service.meta.get("url") if service is not None else None) or (
            f"http://{_url_host(str(address))}:{GRAFANA_PORT}" if address else None)
    if not prometheus:
        prometheus = (service.meta.get("prometheus_url") if service is not None else None) or (
            f"http://{_url_host(str(address))}:{PROMETHEUS_PORT}" if address else None)
    missing = [n for n, v in (("grafana", grafana), ("prometheus", prometheus))
               if not v and n in need]
    if missing and warn:
        why = (f"no component {service_id!r}" if service is None
               else f"{service.rel()} has no url/address and no runs_on server with one")
        print(f"warning: {'/'.join(missing)} URL unknown ({why}); using localhost. Set "
              "[monitoring] service, or grafana_url/prometheus_url.", file=sys.stderr)
    return (str(grafana or DEFAULT_GRAFANA).rstrip("/"),
            str(prometheus or DEFAULT_PROMETHEUS).rstrip("/"), host_id)


def device_role(ctx) -> str:
    role = str(ctx.config.get("monitoring", "role", "client") or "client")
    if role not in ("server", "client"):
        raise DotinfraError(f"[monitoring] role must be \"server\" or \"client\", not {role!r}")
    return role


def probe(url: str, timeout: float = 3.0) -> str:
    """``"ok (HTTP 200)"`` / ``"HTTP 503"`` / ``"unreachable (...)"`` for a GET of ``url``."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={
                "User-Agent": "dotinfra"}), timeout=timeout) as response:  # noqa: S310
            return f"ok (HTTP {response.status})"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except (OSError, ValueError, urllib.error.URLError) as e:
        reason = getattr(e, "reason", e)
        return f"unreachable ({reason})"


def _client_warning(ctx, args, what: str) -> None:
    """On a client device, remind that the stack lives on the monitoring host."""
    if getattr(args, "output", None) or getattr(args, "force", False) or \
            getattr(args, "stdout", False) or device_role(ctx) == "server":
        return
    _, _, host = monitoring_endpoints(ctx, warn=False)
    if host:
        print(f"warning: the monitoring stack runs on {host!r}, and this device is a client "
              f"([monitoring] role). Writing {what} here anyway; pass --output DIR or --force "
              f"to silence this, or run `dotinfra monitoring setup-server` if this is {host}.",
              file=sys.stderr)


# ---------------------------------------------------------------- CLI

def _bundle_dir(ctx) -> Path:
    return ctx.config.path("monitoring", "bundle_dir")


def _cmdb_name(ctx) -> str:
    return ctx.config.get("cmdb", "name", "home") or "home"


def _cmd_targets(args) -> int:
    from .context import get_context

    ctx = get_context(args)
    _client_warning(ctx, args, "targets")
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
    _client_warning(ctx, args, "the bundle")
    outdir = Path(args.output).expanduser() if args.output else _bundle_dir(ctx)
    report = _render_and_print(ctx, outdir, args.force)
    if device_role(ctx) == "server":
        print("  this device is the monitoring server: `dotinfra sync` keeps the targets "
              "current")
    return 0


def _render_and_print(ctx, outdir: Path, force: bool) -> dict:
    report = render_bundle(ctx.components(), outdir, name=_cmdb_name(ctx), force=force)
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
    return report


def _cmd_where(args) -> int:
    from .context import get_context

    ctx = get_context(args)
    grafana, prometheus, host = monitoring_endpoints(ctx)
    service = str(ctx.config.get("monitoring", "service", "monitoring"))
    known = any(c.id == service for c in ctx.components())
    role = device_role(ctx)
    rows = [("service", service + ("" if known else "  (no such component)")),
            ("host", host or "(unknown: set runs_on in the service component)"),
            ("grafana", grafana),
            ("prometheus", prometheus),
            ("this device", f"{role} ({ctx.config.device})"),
            ("bundle_dir", str(_bundle_dir(ctx)) + ("" if role == "server" else
                                                    "  (used on the server only)"))]
    if args.check:
        rows += [("grafana check", probe(f"{grafana}/api/health", args.timeout)),
                 ("prometheus check", probe(f"{prometheus}/-/ready", args.timeout))]
    for name, value in rows:
        print(f"{name:<17} {value}")
    return 0


def _cmd_setup_server(args) -> int:
    from .config import set_toml_value
    from .context import get_context

    ctx = get_context(args)
    local = ctx.config.local_path
    set_toml_value(local, "monitoring", "role", "server")
    if args.bundle_dir:
        set_toml_value(local, "monitoring", "bundle_dir", args.bundle_dir)
    ctx = get_context(args)  # re-read with the new local settings
    print(f"recorded [monitoring] role = \"server\" in {local} (this device only)")
    _, _, host = monitoring_endpoints(ctx, warn=False)
    service = ctx.config.get("monitoring", "service", "monitoring")
    if not host:
        print(f"note: no `runs_on:` host is recorded for service {service!r}; create or edit "
              f"services/{service}.md (`dotinfra new service {service}`) so other devices "
              "know where monitoring runs")
    _render_and_print(ctx, _bundle_dir(ctx), args.force)
    print("  dotinfra timer install    # keeps the CMDB and the scrape targets current")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "monitoring",
        help="Prometheus targets and the monitoring bundle",
        description="Generate Prometheus file_sd targets and the Prometheus+Grafana bundle from "
                    "the CMDB. The stack runs on one machine: the runs_on host of the "
                    "[monitoring] service component (see `monitoring where`).",
    )
    sub = p.add_subparsers(dest="monitoring_cmd", metavar="COMMAND", required=True)

    t = sub.add_parser("targets", help="write Prometheus file_sd JSON, one file per job")
    t.add_argument("--output", metavar="DIR",
                   help="target directory (default: <monitoring.bundle_dir>/targets)")
    t.add_argument("--stdout", action="store_true", help="print all jobs as JSON instead of writing files")
    t.add_argument("--force", action="store_true",
                   help="write into bundle_dir even on a client device (no warning)")
    t.set_defaults(func=_cmd_targets)

    r = sub.add_parser("render", help="write the full monitoring bundle (compose, prometheus, grafana, targets, dashboard)")
    r.add_argument("--output", metavar="DIR", help="bundle directory (default: monitoring.bundle_dir)")
    r.add_argument("--force", action="store_true",
                   help="overwrite locally edited template files (and skip the client warning)")
    r.set_defaults(func=_cmd_render)

    w = sub.add_parser("where", help="where Prometheus and Grafana run, and this device's role",
                       description="Print the monitoring service component, its host "
                                   "(runs_on), the Grafana and Prometheus URLs, and whether "
                                   "this device is the monitoring server or a client.")
    w.add_argument("--check", action="store_true", help="also check both URLs respond")
    w.add_argument("--timeout", type=float, default=3.0, help="seconds per check (default 3)")
    w.set_defaults(func=_cmd_where)

    s = sub.add_parser("setup-server", help="make this device the monitoring host",
                       description="Record [monitoring] role = \"server\" in "
                                   ".dotinfra.local.toml, render the bundle into bundle_dir "
                                   "and print the remaining steps (docker compose up -d, "
                                   "dotinfra timer install). Afterwards every `dotinfra sync` "
                                   "on this device refreshes the Prometheus targets.")
    s.add_argument("--bundle-dir", metavar="DIR",
                   help="where the bundle lives on this device (recorded in the local config)")
    s.add_argument("--force", action="store_true", help="overwrite locally edited template files")
    s.set_defaults(func=_cmd_setup_server)
