"""`dotinfra init` and `dotinfra new`: create a CMDB and components from templates."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

from . import DotinfraError
from .config import CONFIG_NAME, DEFAULT_ROOT, STATE_DIR, load_config
from .context import get_context
from .frontmatter import FENCE, dump_scalar
from .index import write_index
from .model import FOLDERS, ID_RE, KINDS

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = PACKAGE_DIR / "templates"
EXAMPLES = PACKAGE_DIR / "examples"
SCAFFOLD_FILES = {  # template name -> file name in the CMDB
    "README.md": "README.md",
    "AGENTS.md": "AGENTS.md",
    "CLAUDE.md": "CLAUDE.md",
    "gitignore": ".gitignore",
    "gitattributes": ".gitattributes",
    "dotinfra.toml": CONFIG_NAME,
}


def fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


# --------------------------------------------------------------------------- init


def init_cmdb(root: Path, name: str, *, use_git: bool = True,
              example: str | None = None) -> list[str]:
    """Create (or complete) a CMDB at ``root``; existing files are never overwritten.

    Returns human-readable lines describing what happened.
    """
    report: list[str] = []
    root.mkdir(parents=True, exist_ok=True)
    (root / STATE_DIR).mkdir(parents=True, exist_ok=True)
    for template, target in SCAFFOLD_FILES.items():
        path = root / target
        if path.exists():
            report.append(f"kept    {target}")
            continue
        path.write_text(fill((TEMPLATES / template).read_text(encoding="utf-8"), {"name": name}),
                        encoding="utf-8")
        report.append(f"created {target}")
    for folder in KINDS:
        (root / folder).mkdir(exist_ok=True)
        (root / folder / ".gitkeep").touch()
    if example:
        report += copy_example(root, example)
    write_index(root, load_config(root).get("cmdb", "name", name))
    report.append("wrote   INDEX.md")
    if use_git:
        report += _init_git(root)
    return report


def copy_example(root: Path, example: str) -> list[str]:
    source = EXAMPLES / example
    if not source.is_dir():
        available = sorted(p.name for p in EXAMPLES.glob("*") if p.is_dir())
        raise DotinfraError(f"no bundled example {example!r} "
                            f"(available: {', '.join(available) or 'none'})")
    copied = []
    for folder in KINDS:
        for path in sorted((source / folder).glob("*.md")):
            target = root / folder / path.name
            if not target.exists():
                shutil.copyfile(path, target)
                copied.append(f"example {folder}/{path.name}")
    return copied


def _init_git(root: Path) -> list[str]:
    from .sync import ensure_merge_driver, git, is_repo

    if not shutil.which("git"):
        return ["git not found: skipped repository setup (install git, then run `git init`)"]
    report = []
    fresh = not is_repo(root)
    if fresh:
        if git(root, "init", "-q", "-b", "main", check=False).returncode != 0:
            git(root, "init", "-q")  # git < 2.28 has no -b
            git(root, "symbolic-ref", "HEAD", "refs/heads/main")
        report.append("created git repository (branch main)")
    ensure_merge_driver(root)
    report.append("configured the dotinfra merge driver")
    if fresh:
        if subprocess.run(["git", "-C", str(root), "var", "GIT_COMMITTER_IDENT"],
                          capture_output=True).returncode != 0:
            report.append("git has no user.name/user.email: skipped the initial commit "
                          "(set them, then run `dotinfra sync`)")
        else:
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "init: dotinfra CMDB")
            report.append("committed the initial layout")
    return report


def cmd_init(args) -> int:
    root = Path(args.path or args.root or os.environ.get("DOTINFRA_ROOT") or DEFAULT_ROOT)
    root = root.expanduser().resolve()
    name = args.name or ("home" if root == DEFAULT_ROOT else root.name.lstrip(".") or "home")
    for line in init_cmdb(root, name, use_git=not args.no_git, example=args.example):
        print(line)
    if args.skills != "none":
        from .skills import install_skills

        for line in install_skills(args.skills):
            print(line)
    print(f"\nCMDB ready at {root}. Next: `dotinfra new server NAME --address IP`, then "
          "`dotinfra lint`.")
    if root != DEFAULT_ROOT and not os.environ.get("DOTINFRA_ROOT"):
        print(f"Outside {root}, point commands at it with --root {root} or "
              f"DOTINFRA_ROOT={root}.")
    return 0


# --------------------------------------------------------------------------- new


def normalise_kind(kind: str) -> str:
    kind = kind.lower()
    if kind in FOLDERS:
        return kind
    if kind in KINDS:
        return KINDS[kind]
    raise DotinfraError(f"unknown kind {kind!r} (one of: {', '.join(FOLDERS)})")


def render_component(kind: str, component_id: str, title: str | None = None,
                     address: str | None = None, today: date | None = None) -> str:
    """A new component document from ``templates/<kind>.md``."""
    template = (TEMPLATES / f"{kind}.md").read_text(encoding="utf-8")
    head, sep, body = template.partition(f"\n{FENCE}\n")
    title = title or component_id
    stamp = (today or date.today()).isoformat()
    head = fill(head, {"id": component_id, "title": dump_scalar(title),
                       "address": dump_scalar(address) if address else "", "date": stamp})
    body = fill(body, {"id": component_id, "title": title, "address": address or "",
                       "date": stamp})
    return head + sep + body


def new_component(root: Path, kind: str, component_id: str, *, title: str | None = None,
                  address: str | None = None) -> Path:
    kind = normalise_kind(kind)
    if not ID_RE.match(component_id):
        raise DotinfraError(f"invalid id {component_id!r}: use lowercase letters, digits, "
                            "'.', '_' and '-', starting with a letter or digit")
    path = root / FOLDERS[kind] / f"{component_id}.md"
    if path.exists():
        raise DotinfraError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_component(kind, component_id, title, address), encoding="utf-8")
    return path


def cmd_new(args) -> int:
    ctx = get_context(args)
    existing = {c.id: c for c in ctx.components()}
    if args.id in existing:
        raise DotinfraError(f"id {args.id!r} is already used by {existing[args.id].rel()}")
    path = new_component(ctx.root, args.kind, args.id, title=args.title, address=args.address)
    print(f"created {ctx.rel(path)} (status: planned; fill in role, ssh, and the sections)")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "init", help="create a CMDB (default ~/.infra)",
        description="Create the CMDB layout, agent rules (AGENTS.md, CLAUDE.md), config, "
                    "git repository and merge driver. Existing files are kept.")
    p.add_argument("path", nargs="?", help="where to create it (default: --root, "
                                           "$DOTINFRA_ROOT or ~/.infra)")
    p.add_argument("--name", "-n", help="CMDB name shown in INDEX.md and dashboards")
    p.add_argument("--no-git", action="store_true", help="do not create a git repository")
    p.add_argument("--skills", choices=("none", "claude", "agents", "both"), default="none",
                   help="also install the bundled Agent Skills for Claude Code (~/.claude) "
                        "and/or other agents (~/.agents) (default: none)")
    p.add_argument("--example", nargs="?", const="homelab", metavar="NAME",
                   help="copy the components of a bundled example CMDB (default: homelab)")
    p.set_defaults(func=cmd_init)

    p = subparsers.add_parser(
        "new", help="create a component from a template",
        description="Create KIND/ID.md from the kind's template (status: planned).")
    p.add_argument("kind", metavar="KIND", help=f"one of: {', '.join(FOLDERS)}")
    p.add_argument("id", metavar="ID", help="unique id, e.g. nas or web1")
    p.add_argument("--title", help="display name (default: ID)")
    p.add_argument("--address", help="primary IP or hostname")
    p.set_defaults(func=cmd_new)
