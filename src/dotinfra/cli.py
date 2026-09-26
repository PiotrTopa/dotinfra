"""Command-line entry point: ``dotinfra [--root PATH] COMMAND ...``."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import (DotinfraError, __version__, drift, index, lint, migrate, scaffold, skills,
               sshconfig, sync, upgrade, versioning)
from . import vault as vault_module
from .config import CONFIG_NAME, load_config
from .context import get_context
from .reconcile import merge_driver

OPTIONAL_MODULES = (  # (module, command, help): features the CLI must survive without
    ("monitoring", "monitoring", "Prometheus targets and the monitoring bundle"),
    ("grafana", "grafana", "Grafana fleet dashboard"),
    ("events", "event", "infra event log (Grafana annotations)"),
)


# --------------------------------------------------------------------------- ls / show


def _matches(component, args) -> bool:
    return ((not args.kind or component.kind == scaffold.normalise_kind(args.kind))
            and (not args.tag or args.tag in component.tags)
            and (not args.status or component.status == args.status))


def cmd_ls(args) -> int:
    ctx = get_context(args)
    components = [c for c in ctx.components() if _matches(c, args)]
    if args.json:
        print(json.dumps([c.to_dict() for c in components], indent=2, default=str))
        return 0
    rows = [(c.id, c.kind, c.status or "?", c.address or "", c.title) for c in components]
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in
              enumerate(("ID", "KIND", "STATUS", "ADDRESS", "TITLE"))]
    for row in [("ID", "KIND", "STATUS", "ADDRESS", "TITLE"), *rows]:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())
    return 0


def cmd_show(args) -> int:
    ctx = get_context(args)
    component = ctx.component(args.id)
    if args.json:
        print(json.dumps(component.to_dict() | {"body": component.body}, indent=2, default=str))
    else:
        print(f"# {component.rel()}")
        sys.stdout.write(component.path.read_text(encoding="utf-8"))
    return 0


# --------------------------------------------------------------------------- merge driver


def cmd_merge_driver(args) -> int:
    return merge_driver(Path(args.base), Path(args.ours), Path(args.theirs), args.path)


# --------------------------------------------------------------------------- doctor


def _check(results: list[tuple[str, str, str]], level: str, name: str, detail: str) -> None:
    results.append((level, name, detail))


def _tool_version(cmd: list[str]) -> str | None:
    """First line of ``cmd``'s version output; ``None`` when the tool is missing."""
    if not shutil.which(cmd[0]):
        return None
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0] if result.returncode == 0 and lines else "installed"


def _doctor_tools(results) -> None:
    python = ".".join(map(str, sys.version_info[:3]))
    _check(results, "ok" if sys.version_info >= (3, 11) else "fail", "python",
           f"{python} ({sys.executable})")
    for tool, cmd, required in (("git", ["git", "--version"], True),
                                ("ssh", ["ssh", "-V"], True),
                                ("age", ["age", "--version"], False)):
        version = _tool_version(cmd)
        if version:
            _check(results, "ok", tool, version)
        else:
            _check(results, "fail" if required else "info", tool,
                   "not found" + ("" if required else " (only needed for the age vault)"))


def _doctor_version(args, results, config) -> None:
    installed = versioning.installed_version()
    required = config.get("cmdb", "min_version") if config else None
    if required and versioning.is_newer(str(required)):
        _check(results, "fail", "version", versioning.too_old_message(str(required)))
    else:
        _check(results, "ok", "version", f"dotinfra {installed}"
               + (f" (CMDB needs ≥ {required})" if required else ""))
    if getattr(args, "check_updates", False):
        latest = upgrade.latest_release()
        if latest is None:
            _check(results, "info", "updates", "could not reach GitHub (offline?)")
        elif versioning.is_newer(latest, installed):
            _check(results, "warn", "updates", f"{latest} is available; run `dotinfra upgrade`")
        else:
            _check(results, "ok", "updates", f"up to date (latest release {latest})")


def _doctor_migrate(root: Path, results) -> None:
    try:
        plan = migrate.plan_migration(root)
    except DotinfraError as exc:
        _check(results, "fail", "migrate", str(exc))
        return
    if plan.changed:
        _check(results, "warn", "migrate", f"{len(plan.lines)} pending change(s) "
                                           "(managed files, schema, skills); run "
                                           "`dotinfra migrate --dry-run` to see them")
    else:
        _check(results, "ok", "migrate", "schema, managed files and project skills current")


def _skill_rows(pairs, scope_label: str, results) -> None:
    """One row per directory; agents sharing a directory are listed together."""
    by_dir: dict[Path, list[str]] = {}
    for name, directory in pairs:
        by_dir.setdefault(directory, []).append(name)
    for directory, names in by_dir.items():
        state = skills.skills_state(directory)
        level = {"current": "ok", "missing": "info"}.get(state, "warn")
        hint = "" if state == "current" else (" — `dotinfra migrate`" if scope_label
                                              else " — `dotinfra skills install`")
        _check(results, level, "skills", f"{state}: {directory} ({', '.join(names)}"
                                         f"{scope_label}){hint}")


def _doctor_skills(config, results) -> None:
    home = Path.home()
    wanted = set(skills.detect_targets(home)) | set(skills.read_record(home).get("targets", []))
    _skill_rows([(name, d) for name in skills.TARGETS if name in wanted
                 for d in skills.target_dirs([name], skills.USER, home=home)], "", results)
    if config is not None:
        _skill_rows([(name, d) for name in skills.project_targets(config)
                     for d in skills.target_dirs([name], skills.PROJECT, root=config.root)],
                    "; project scope", results)


def _doctor_monitoring(ctx, results) -> None:
    try:
        from .monitoring import device_role, monitoring_endpoints

        grafana, _, host = monitoring_endpoints(ctx, warn=False)
        role = device_role(ctx)
    except Exception as exc:  # optional module; never break doctor
        _check(results, "warn", "monitoring", str(exc))
        return
    _check(results, "ok" if host else "info", "monitoring",
           f"this device: {role}; host: {host or 'unknown'}; grafana {grafana}")


def _doctor_cmdb(args, results) -> None:
    ctx = get_context(args, require=False)
    if not (ctx.root / CONFIG_NAME).is_file():
        _doctor_version(args, results, None)
        _doctor_skills(None, results)
        _check(results, "fail", "cmdb", f"no {CONFIG_NAME} in {ctx.root}; run `dotinfra init`")
        return
    try:
        config = load_config(ctx.root)
    except DotinfraError as exc:
        _check(results, "fail", "config", str(exc))
        return
    _doctor_version(args, results, config)
    _check(results, "ok", "cmdb", f"{ctx.root} (name {config.get('cmdb', 'name')!r})")
    _doctor_migrate(ctx.root, results)
    _doctor_skills(config, results)
    _doctor_monitoring(ctx, results)
    _doctor_git(ctx.root, results)
    try:
        keys = vault_module.open_vault(config).keys()
        _check(results, "ok", "vault", f"{config.get('vault', 'backend')} backend, "
                                       f"{len(keys)} key(s)")
    except DotinfraError as exc:
        _check(results, "fail", "vault", str(exc))
    issues = lint.run_lint(ctx.root, config)
    errors = any(i.level == "error" for i in issues)
    _check(results, "fail" if errors else "ok", "lint",
           lint.summary(issues, len(ctx.components())) + (" — run `dotinfra lint`" if issues
                                                          else ""))


def _doctor_git(root: Path, results) -> None:
    if not sync.is_repo(root):
        _check(results, "warn", "git repo", "not a git repository: sync is unavailable")
        return
    configured = sync.git(root, "config", "--local", "--get", "merge.dotinfra.driver",
                          check=False).stdout.strip()
    if configured == sync.merge_driver_command():
        _check(results, "ok", "merge driver", configured)
    else:
        _check(results, "warn", "merge driver",
               f"{'points to ' + configured if configured else 'not configured'}; "
               "the next `dotinfra sync` fixes it")
    attributes = root / ".gitattributes"
    if "merge=dotinfra" not in (attributes.read_text() if attributes.is_file() else ""):
        _check(results, "warn", "gitattributes", "missing `*.md merge=dotinfra`; section-aware "
                                                 "merges are off")
    remotes = sync.remote_names(root)
    _check(results, "ok" if remotes else "info", "remotes",
           ", ".join(remotes) or "none (add a hub: `git remote add origin URL`)")


def cmd_doctor(args) -> int:
    results: list[tuple[str, str, str]] = []
    _doctor_tools(results)
    _doctor_cmdb(args, results)
    for level, name, detail in results:
        print(f"{level.upper():<5} {name:<13} {detail}")
    return 1 if any(level == "fail" for level, _, _ in results) else 0


# --------------------------------------------------------------------------- parser


def _register_browse(sub) -> None:
    p = sub.add_parser("ls", help="list components",
                       description="List components, optionally filtered.")
    p.add_argument("--kind", help="server, network, domain, router, service or device")
    p.add_argument("--tag", help="only components with this tag")
    p.add_argument("--status", help="active, planned, degraded or retired")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_ls, version_guard="warn")

    p = sub.add_parser("show", help="print one component",
                       description="Print a component file (or its parsed data with --json).")
    p.add_argument("id", metavar="ID")
    p.add_argument("--json", action="store_true", help="parsed frontmatter and body as JSON")
    p.set_defaults(func=cmd_show, version_guard="warn")


def _register_merge_driver(sub) -> None:
    p = sub.add_parser("merge-driver", help="git merge driver (internal)",
                       description="Section-aware 3-way merge used by git through "
                                   ".gitattributes (`*.md merge=dotinfra`). Writes the result "
                                   "to OURS; exits 1 if conflicts remain.")
    for name in ("base", "ours", "theirs", "path"):
        p.add_argument(name, metavar=name.upper())
    p.set_defaults(func=cmd_merge_driver)


def _register_doctor(sub) -> None:
    p = sub.add_parser("doctor", help="check the installation and the CMDB",
                       description="Check python, git, ssh, age, the dotinfra version against "
                                   "the CMDB's min_version, pending migrations, Agent Skills "
                                   "per agent, the monitoring role, config, merge driver, "
                                   "vault and lint. Offline unless --check-updates.")
    p.add_argument("--check-updates", action="store_true",
                   help="also ask GitHub whether a newer dotinfra release exists")
    p.set_defaults(func=cmd_doctor, version_guard="off")


def _register_optional(sub, module: str, name: str, help_text: str) -> None:
    try:
        importlib.import_module(f"dotinfra.{module}").register(sub)
        return
    except Exception as exc:  # a broken optional module must not take the CLI down
        reason = f"{type(exc).__name__}: {exc}"

    def unavailable(args) -> int:
        print(f"dotinfra: the '{name}' command is unavailable ({reason})", file=sys.stderr)
        return 1

    try:
        p = sub.add_parser(name, help=f"{help_text} (unavailable)", add_help=False)
    except argparse.ArgumentError:
        return  # register() failed after adding its parser; nothing more we can do
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=unavailable)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dotinfra",
        description="A self-maintaining Markdown infrastructure CMDB for humans and AI agents.",
        epilog="Exit codes: 0 ok, 1 error, 2 sync conflict, 3 this dotinfra is older than the "
               "CMDB's min_version (run `dotinfra upgrade`). Run `dotinfra COMMAND --help` "
               "for details. Docs: https://github.com/PiotrTopa/dotinfra")
    parser.add_argument("--root", metavar="PATH",
                        help="CMDB root (default: $DOTINFRA_ROOT, the nearest folder with "
                             ".dotinfra.toml, or ~/.infra)")
    parser.add_argument("--version", action="version", version=f"dotinfra {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    for register in (scaffold.register, _register_browse, lint.register, index.register,
                     sshconfig.register, vault_module.register, sync.register,
                     _register_merge_driver, drift.register, skills.register, migrate.register,
                     upgrade.register, _register_doctor):
        register(sub)
    for module, name, help_text in OPTIONAL_MODULES:
        _register_optional(sub, module, name, help_text)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:  # e.g. `dotinfra ls | head`
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except (DotinfraError, OSError) as exc:
        print(f"dotinfra: error: {exc}", file=sys.stderr)
        return getattr(exc, "exit_code", 1)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
