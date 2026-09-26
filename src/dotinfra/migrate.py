"""`dotinfra migrate`: bring a CMDB up to the running dotinfra version.

1. Schema migrations: ``[cmdb] schema`` counts layout changes. ``MIGRATIONS[n]``
   turns schema ``n`` into ``n + 1`` by editing ``.dotinfra.toml`` text (comments
   survive). 0.1.x CMDBs have no ``schema`` key, which means schema 0; 0.2.x
   wrote schema 1; 0.3 is schema 2. Component files are never rewritten.
2. ``[cmdb] min_version`` is raised to this release's ``X.Y.0`` (never lowered),
   so older dotinfra installs stop writing to a CMDB they do not understand.
3. ``[sync] remote_url`` is filled from ``git remote get-url`` when empty.
4. Managed blocks in README.md, AGENTS.md, CLAUDE.md, .gitignore and
   .gitattributes are refreshed from the current templates (see :mod:`managed`).
5. Agent Skills are refreshed: project scope inside the CMDB, and every user-scope
   directory ``dotinfra skills install`` recorded on this device.
6. Everything that changed in the repository is committed as
   ``migrate: dotinfra X.Y.Z``.

Running it twice changes nothing the second time.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import DotinfraError
from .config import (CONFIG_NAME, DEFAULTS, LOCAL_CONFIG_NAME, Config, comment_out_toml_key,
                     deep_merge, parse_toml, read_toml, set_toml_text)
from .context import get_context
from .managed import ADOPTED, CREATED, INSERTED, UNCHANGED, UPDATED, refresh, style_for
from .scaffold import SCHEMA, legacy_renders, managed_contents, public_url, MANAGED_FILES
from .versioning import installed_version, is_newer, minor_floor

# 0.1.x templates wrote these literal defaults; from 0.2 the URLs are derived from the
# monitoring service component, so the literals would shadow it.
_LEGACY_URL_DEFAULTS = {"grafana_url": "http://localhost:3000",
                        "prometheus_url": "http://localhost:9090"}


def _schema_0_to_1(text: str, notes: list[str]) -> str:
    """0.1.x → 0.2: record the schema and the new minimum version; monitoring URLs
    that merely repeat the old localhost defaults become comments (resolution from the
    ``[monitoring] service`` component takes over)."""
    data = parse_toml(text)
    text = set_toml_text(text, "cmdb", "schema", 1)
    text = set_toml_text(text, "cmdb", "min_version", "0.2.0")
    monitoring = data.get("monitoring", {})
    for key, legacy in _LEGACY_URL_DEFAULTS.items():
        if monitoring.get(key) == legacy:
            text = comment_out_toml_key(text, "monitoring", key,
                                        "0.2: derived from [monitoring] service; uncomment "
                                        "to override")
            notes.append(f"{key} was the 0.1 default ({legacy}); now derived from the "
                         "monitoring service component")
    if "service" not in monitoring:
        text = set_toml_text(text, "monitoring", "service", "monitoring")
    if data.get("cmdb", {}).get("device"):
        notes.append("[cmdb] device is set in the shared .dotinfra.toml, so every device "
                     f"uses it; move it to {LOCAL_CONFIG_NAME} on the device it names")
    return text


_EVENTS_BLOCK = """
[events]
backend = "auto"                 # "auto" | "grafana" | "file" (events/<YYYY>.md in the CMDB)
"""
_LINT_BLOCK = """
[lint]
max_lines = 120                  # warn when a component body is longer (docs are fact sheets)
"""
JOURNAL_NOTE = ("0.3: component docs now state current facts only; history goes to the "
                "event log (`dotinfra event add`). Your docs were not changed: run "
                "`dotinfra lint` and fix the `journal`/`long` warnings, or ask an agent to "
                "do it with the infra-cmdb skill")


def _append_block(text: str, block: str) -> str:
    return text.rstrip("\n") + "\n" + block


def _schema_1_to_2(text: str, notes: list[str]) -> str:
    """0.2 → 0.3: the ``[events]`` backend and ``[lint] max_lines``. Component bodies
    are never rewritten; the user is pointed at the new lint warnings instead."""
    data = parse_toml(text)
    text = set_toml_text(text, "cmdb", "schema", 2)
    if "events" not in data:
        text = _append_block(text, _EVENTS_BLOCK)
    elif "backend" not in data["events"]:
        text = set_toml_text(text, "events", "backend", "auto")
    if "lint" not in data:
        text = _append_block(text, _LINT_BLOCK)
    elif "max_lines" not in data["lint"]:
        text = set_toml_text(text, "lint", "max_lines", 120)
    notes.append(JOURNAL_NOTE)
    return text


MIGRATIONS: dict[int, Callable[[str, list[str]], str]] = {
    0: _schema_0_to_1,
    1: _schema_1_to_2,
}
assert sorted(MIGRATIONS) == list(range(SCHEMA)), "one migration per schema step"


@dataclass
class Plan:
    root: Path
    files: dict[str, tuple[str | None, str]] = field(default_factory=dict)  # rel -> (old, new)
    lines: list[str] = field(default_factory=list)       # human summary
    notes: list[str] = field(default_factory=list)       # things the user should look at
    skill_dirs: list[Path] = field(default_factory=list)  # project-scope dirs to refresh

    @property
    def changed(self) -> bool:
        return bool(self.files or self.skill_dirs)


def schema_of(data: dict) -> int:
    try:
        return int(data.get("cmdb", {}).get("schema", 0) or 0)
    except (TypeError, ValueError):
        raise DotinfraError("[cmdb] schema in .dotinfra.toml is not a number") from None


def _remote_url(root: Path, remote: str) -> str:
    from .sync import git, is_repo

    if not remote or not is_repo(root):
        return ""
    result = git(root, "remote", "get-url", "--", remote, check=False)
    return public_url(result.stdout.strip()) if result.returncode == 0 else ""


def plan_migration(root: Path) -> Plan:
    """Compute every change without writing anything."""
    plan = Plan(root)
    config_path = root / CONFIG_NAME
    original = config_path.read_text(encoding="utf-8")
    text = original
    data = parse_toml(text, str(config_path))
    schema = schema_of(data)
    if schema > SCHEMA:
        raise DotinfraError(f"this CMDB has schema {schema}, newer than dotinfra "
                            f"{installed_version()} knows ({SCHEMA}); run `dotinfra upgrade`")
    for step in range(schema, SCHEMA):
        text = MIGRATIONS[step](text, plan.notes)
        plan.lines.append(f"{CONFIG_NAME}: schema {step} → {step + 1}")
    current_min = parse_toml(text).get("cmdb", {}).get("min_version")
    if is_newer(minor_floor(), current_min):
        text = set_toml_text(text, "cmdb", "min_version", minor_floor())
        plan.lines.append(f"{CONFIG_NAME}: min_version {current_min or '(none)'} → "
                          f"{minor_floor()}")
    shared = parse_toml(text)
    sync_cfg = shared.get("sync", {})
    if not sync_cfg.get("remote_url"):
        url = _remote_url(root, sync_cfg.get("remote", DEFAULTS["sync"]["remote"]))
        if url:
            text = set_toml_text(text, "sync", "remote_url", url)
            shared = parse_toml(text)
            plan.lines.append(f"{CONFIG_NAME}: remote_url → {url} (clone URL in README.md)")
    if text != original:
        plan.files[CONFIG_NAME] = (original, text)

    shared_config = Config(root=root, data=deep_merge(copy.deepcopy(DEFAULTS), shared))
    merged = deep_merge(copy.deepcopy(DEFAULTS), shared)
    deep_merge(merged, read_toml(root / LOCAL_CONFIG_NAME))
    config = Config(root=root, data=merged)

    from .skills import PROJECT, project_targets, skills_state, target_dirs

    for name in project_targets(config):
        for directory in target_dirs([name], PROJECT, root=root):
            if directory not in plan.skill_dirs and skills_state(directory) != "current":
                plan.skill_dirs.append(directory)
                plan.lines.append(f"{directory.relative_to(root).as_posix()}/: refresh "
                                  "project-scope skills")

    # managed files are committed: render them from the shared config only
    for target, content in managed_contents(root, shared_config).items():
        path = root / target
        old = path.read_text(encoding="utf-8") if path.exists() else None
        new, action = refresh(old, content, style_for(target),
                              legacy_renders=legacy_renders(MANAGED_FILES[target]))
        if action == UNCHANGED:
            continue
        plan.files[target] = (old, new)
        plan.lines.append(f"{target}: " + {
            CREATED: "created",
            UPDATED: "managed block refreshed (text outside the markers kept)",
            ADOPTED: "0.1.x template replaced by the managed version",
            INSERTED: "managed block added on top; your earlier text is kept below it",
        }[action])
        if action == INSERTED:
            plan.notes.append(f"{target} had local edits: dotinfra's block is now on top and "
                              "your text follows it; remove anything that is now duplicated")
    return plan


def apply(plan: Plan, *, commit: bool = True) -> list[str]:
    """Write the plan, refresh skills, commit. Returns report lines."""
    from .skills import install_into, refresh_user_skills
    from .sync import git, is_repo, merge_in_progress

    root = plan.root
    if is_repo(root) and merge_in_progress(root):
        raise DotinfraError("a merge is in progress; finish it (`dotinfra reconcile`) first")
    if commit and is_repo(root) and git(root, "var", "GIT_COMMITTER_IDENT",
                                        check=False).returncode != 0:
        raise DotinfraError("git has no user.name/user.email here, so the migration could not "
                            "be committed; set them (`git config user.name ...`) and re-run")
    report = []
    for rel, (_, new) in plan.files.items():
        (root / rel).write_text(new, encoding="utf-8")
    for directory in plan.skill_dirs:
        install_into(directory)
    user = refresh_user_skills()
    if user:
        report.append(f"refreshed {len(user)} user-scope skill(s) recorded on this device")
    paths = list(plan.files) + [d.relative_to(root).as_posix() for d in plan.skill_dirs]
    if commit and paths and is_repo(root):
        git(root, "add", "--", *paths)
        if git(root, "diff", "--cached", "--quiet", "--", *paths, check=False).returncode:
            message = f"migrate: dotinfra {installed_version()}"
            git(root, "commit", "-q", "-m", message, "--", *paths)
            report.append(f"committed: {message} (`dotinfra sync` shares it)")
    return report


def cmd_migrate(args) -> int:
    ctx = get_context(args)
    plan = plan_migration(ctx.root)
    if not plan.changed:
        if not args.dry_run:
            from .skills import refresh_user_skills

            refreshed = refresh_user_skills()
            if refreshed:
                print(f"refreshed {len(refreshed)} user-scope skill(s) recorded on this device")
        print(f"CMDB at {ctx.root} is up to date for dotinfra {installed_version()}")
        return 0
    print(f"{'would migrate' if args.dry_run else 'migrating'} {ctx.root} to dotinfra "
          f"{installed_version()}:")
    for line in plan.lines:
        print(f"  {line}")
    for note in plan.notes:
        print(f"  note: {note}")
    if args.dry_run:
        return 0
    if not args.yes and sys.stdin.isatty():
        if input("apply? [Y/n] ").strip().lower() not in ("", "y", "yes"):
            print("nothing changed")
            return 1
    for line in apply(plan):
        print(line)
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "migrate", help="update this CMDB to the installed dotinfra version",
        description="Run schema migrations, raise [cmdb] min_version, refresh the "
                    "dotinfra-managed blocks (README.md, AGENTS.md, CLAUDE.md, .gitignore, "
                    ".gitattributes) and the Agent Skills, and commit the result as "
                    "`migrate: dotinfra X.Y.Z`. Text outside the managed markers is kept. "
                    "Safe to run repeatedly.")
    p.add_argument("--dry-run", "-n", action="store_true", help="only show what would change")
    p.add_argument("--yes", "-y", action="store_true",
                   help="do not ask for confirmation (it is only asked on a terminal)")
    p.set_defaults(func=cmd_migrate)
