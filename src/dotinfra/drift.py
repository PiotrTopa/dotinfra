"""`dotinfra drift`: probe hosts over SSH and compare what is running with what is written."""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from . import DotinfraError
from .context import Context, get_context
from .frontmatter import replace_keys
from .model import Component, by_id
from .sshconfig import ssh_hosts

SSH_TIMEOUT = 60
MAX_JUMPS = 5

# POSIX sh, tolerant of missing tools: Linux, *BSD, macOS, Termux, postmarketOS/busybox.
PROBE_SCRIPT = r"""
LC_ALL=C; export LC_ALL
echo "hostname=$(hostname 2>/dev/null || uname -n)"
echo "kernel=$(uname -sr)"
echo "arch=$(uname -m)"
os=""
if [ -r /etc/os-release ]; then
  os=$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-$NAME $VERSION_ID}")
fi
if [ -z "$os" ] && command -v sw_vers >/dev/null 2>&1; then
  os="$(sw_vers -productName) $(sw_vers -productVersion)"
fi
if [ -z "$os" ] && command -v getprop >/dev/null 2>&1; then
  os="Android $(getprop ro.build.version.release)"
fi
[ -n "$os" ] || os=$(uname -sr)
echo "os=$os"
cpus=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null)
echo "cpus=$cpus"
mem_kb=""
if [ -r /proc/meminfo ]; then
  mem_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
fi
if [ -z "$mem_kb" ]; then
  bytes=$(sysctl -n hw.physmem 2>/dev/null || sysctl -n hw.memsize 2>/dev/null)
  [ -n "$bytes" ] && mem_kb=$((bytes / 1024))
fi
echo "mem_kb=$mem_kb"
ips=""
if command -v ip >/dev/null 2>&1; then
  ips=$(ip -4 -o addr show scope global 2>/dev/null | awk '{sub(/\/.*/, "", $4); print $4}')
fi
if [ -z "$ips" ] && command -v ifconfig >/dev/null 2>&1; then
  ips=$(ifconfig 2>/dev/null |
    awk '/inet / {a=$2; sub(/^addr:/, "", a); if (a !~ /^127\./) print a}')
fi
echo "ips="$ips
"""


@dataclass
class Drift:
    field: str
    recorded: object
    observed: object


@dataclass
class DriftReport:
    id: str
    facts: dict | None = None
    drifts: list[Drift] = field(default_factory=list)
    error: str | None = None
    updated: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and not self.drifts


# --------------------------------------------------------------------------- probing


def _destination(component: Component) -> tuple[str, str | None]:
    """``(user@host, port)`` for a component's ssh settings."""
    for field, reason in component.unsafe_values():
        raise DotinfraError(f"{component.id}: {field} {reason}; unsafe for ssh, refusing")
    ssh = component.ssh
    host = str(ssh.get("host") or component.address or "")
    if not host:
        raise DotinfraError(f"{component.id}: no ssh.host or address to connect to")
    user = ssh.get("user")
    return (f"{user}@{host}" if user else host), (str(ssh["port"]) if ssh.get("port") else None)


def jump_chain(component: Component, components: dict[str, Component]) -> list[str]:
    """``-J`` hops for ``ssh.jump`` (outermost first), following jumps of jump hosts."""
    chain: list[str] = []
    current = component
    while current.ssh.get("jump"):
        jump_id = str(current.ssh["jump"])
        if jump_id not in components:
            raise DotinfraError(f"{current.id}: ssh.jump {jump_id!r} is not a known component")
        if len(chain) >= MAX_JUMPS:
            raise DotinfraError(f"{component.id}: ssh.jump chain longer than {MAX_JUMPS} "
                                "(loop?)")
        current = components[jump_id]
        dest, port = _destination(current)
        chain.insert(0, f"{dest}:{port}" if port else dest)
    return chain


def ssh_command(component: Component, components: dict[str, Component]) -> list[str]:
    dest, port = _destination(component)
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    if port:
        cmd += ["-p", port]
    if component.ssh.get("key"):
        cmd += ["-i", str(component.ssh["key"])]
    chain = jump_chain(component, components)
    if chain:
        cmd += ["-J", ",".join(chain)]
    return cmd + [dest, "sh", "-s"]


def run_probe(cmd: list[str]) -> str:
    """Run the probe script through ``cmd`` and return its stdout."""
    try:
        result = subprocess.run(cmd, input=PROBE_SCRIPT, capture_output=True, text=True,
                                timeout=SSH_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise DotinfraError(f"timed out after {SSH_TIMEOUT}s") from None
    except FileNotFoundError:
        raise DotinfraError("ssh is not installed or not on PATH") from None
    if result.returncode != 0:
        raise DotinfraError((result.stderr.strip() or f"ssh exited {result.returncode}")
                            .splitlines()[-1])
    return result.stdout


def parse_probe(output: str, today: date | None = None) -> dict:
    raw = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    facts: dict = {"hostname": raw.get("hostname", "").strip(),
                   "kernel": raw.get("kernel", "").strip(),
                   "arch": raw.get("arch", "").strip(),
                   "os": raw.get("os", "").strip()}
    cpus = raw.get("cpus", "").strip()
    facts["cpus"] = int(cpus) if cpus.isdigit() else None
    mem_kb = raw.get("mem_kb", "").strip()
    facts["mem_gb"] = round(int(mem_kb) / 1048576, 1) if mem_kb.isdigit() else None
    facts["ips"] = raw.get("ips", "").split()
    facts["probed"] = (today or date.today()).isoformat()
    return facts


# --------------------------------------------------------------------------- comparing


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", text.lower()))


def _norm(value) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(sorted(str(v) for v in value))
    return "" if value is None else str(value)


def compare(component: Component, facts: dict) -> list[Drift]:
    drifts = []
    declared_os = component.meta.get("os")
    if declared_os and facts.get("os") and not _tokens(str(declared_os)) <= _tokens(facts["os"]):
        drifts.append(Drift("os", declared_os, facts["os"]))
    address = component.address
    if address and facts.get("ips") and _is_ipv4(address) and address not in facts["ips"]:
        drifts.append(Drift("address", address, facts["ips"]))
    recorded = component.meta.get("facts")
    if isinstance(recorded, dict):
        for key, old in recorded.items():
            if key != "probed" and key in facts and _norm(old) != _norm(facts[key]):
                drifts.append(Drift(f"facts.{key}", old, facts[key]))
    return drifts


def _is_ipv4(text: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(text), ipaddress.IPv4Address)
    except ValueError:
        return False


# --------------------------------------------------------------------------- orchestration


def check(ctx: Context, component: Component, *, update: bool = False) -> DriftReport:
    report = DriftReport(component.id)
    try:
        output = run_probe(ssh_command(component, by_id(ctx.components())))
    except DotinfraError as exc:
        report.error = str(exc)
        return report
    report.facts = parse_probe(output)
    report.drifts = compare(component, report.facts)
    _cache(ctx, component.id, report.facts)
    if update:
        write_facts(component, report.facts, report.drifts)
        report.updated = True
    return report


def write_facts(component: Component, facts: dict, drifts: list[Drift]) -> None:
    """Record probed facts (and a drifted ``os``) in the component's frontmatter."""
    stored = {key: facts[key] for key in ("hostname", "kernel", "arch", "cpus", "mem_gb", "ips",
                                          "probed") if facts.get(key) not in (None, "", [])}
    updates: dict = {"facts": stored, "updated": facts["probed"]}
    if any(d.field == "os" for d in drifts):
        updates["os"] = facts["os"]
    text = component.path.read_text(encoding="utf-8")
    component.path.write_text(replace_keys(text, updates), encoding="utf-8")


def _cache(ctx: Context, component_id: str, facts: dict) -> None:
    directory = ctx.config.state_dir / "facts"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"id": component_id, "checked": datetime.now().isoformat(timespec="seconds"),
               "facts": facts}
    (directory / f"{component_id}.json").write_text(json.dumps(payload, indent=2) + "\n",
                                                    encoding="utf-8")


def _targets(ctx: Context, ids: list[str]) -> list[Component]:
    if ids:
        return [ctx.component(component_id) for component_id in ids]
    targets = [c for c in ssh_hosts(ctx.components()) if c.status != "planned"]
    if not targets:
        raise DotinfraError("no components with ssh: settings to probe")
    return targets


def _describe(report: DriftReport) -> list[str]:
    if report.error:
        return [f"{report.id}: UNREACHABLE: {report.error}"]
    facts = report.facts or {}
    summary = (f"{facts.get('hostname')}, {facts.get('os')}, {facts.get('cpus')} cpu, "
               f"{facts.get('mem_gb')} GB")
    lines = [f"{report.id}: {'OK' if report.ok else 'DRIFT'} ({summary})"]
    lines += [f"  {d.field}: recorded {d.recorded!r}, observed {d.observed!r}"
              for d in report.drifts]
    if report.updated:
        lines.append("  facts written to the component (add a History line if something "
                     "changed)")
    return lines


def cmd_drift(args) -> int:
    ctx = get_context(args)
    reports = []
    for component in _targets(ctx, args.ids):
        report = check(ctx, component, update=args.update)
        reports.append(report)
        if not args.json:
            print("\n".join(_describe(report)), flush=True)
    if args.json:
        print(json.dumps([asdict(r) | {"ok": r.ok} for r in reports], indent=2, default=str))
    failed = [r for r in reports if not r.ok]
    if failed and not args.json:
        print(f"{len(failed)} of {len(reports)} component(s) drifted or unreachable",
              file=sys.stderr)
    return 1 if failed else 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "drift", help="compare live hosts with their docs over SSH",
        description="Run one read-only SSH probe per host (via ssh.jump when set) and compare "
                    "hostname, OS, kernel, CPUs, memory and IPv4 addresses with the component's "
                    "os, address and facts. Exit 1 if anything drifted or was unreachable.")
    p.add_argument("ids", nargs="*", metavar="ID",
                   help="components to probe (default: every non-planned one with ssh:)")
    p.add_argument("--update", action="store_true",
                   help="write probed facts (and a drifted os) into the frontmatter and bump "
                        "updated")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_drift)
