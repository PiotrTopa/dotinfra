"""`dotinfra init` and `dotinfra new`: create a CMDB and components from templates."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

from . import DotinfraError
from .config import CONFIG_NAME, DEFAULT_ROOT, STATE_DIR, Config, load_config, set_toml_value
from .context import get_context
from .frontmatter import FENCE, dump_scalar
from .index import write_index
from .managed import style_for, wrap
from .model import FOLDERS, ID_RE, KINDS, load_cmdb
from .versioning import minor_floor

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = PACKAGE_DIR / "templates"
EXAMPLES = PACKAGE_DIR / "examples"
LEGACY = TEMPLATES / "legacy"   # renders of earlier releases, for `migrate` to recognise
SCHEMA = 1                       # current CMDB schema (see migrate.MIGRATIONS)
MANAGED_FILES = {  # file name in the CMDB -> template name; content lives in managed blocks
    "README.md": "README.md",
    "AGENTS.md": "AGENTS.md",
    "CLAUDE.md": "CLAUDE.md",
    ".gitignore": "gitignore",
    ".gitattributes": "gitattributes",
}
REPO_URL = "https://github.com/PiotrTopa/dotinfra"
NO_URL = "<URL of this repository>"


def fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


# --------------------------------------------------------------------------- managed files


def public_url(url: str | None) -> str:
    """A clone URL safe to write into the README: credentials in http(s) URLs are dropped."""
    url = (url or "").strip()
    return re.sub(r"^(https?://)[^/@]+@", r"\1", url)


def legacy_renders(template: str) -> list[str]:
    """Every earlier release's version of a scaffold template (``{{name}}`` unfilled)."""
    return [p.read_text(encoding="utf-8") for p in sorted(LEGACY.glob(f"*/{template}"))]


def _monitoring_note(root: Path, config: Config) -> str:
    service = str(config.get("monitoring", "service", "monitoring") or "monitoring")
    try:
        components = {c.id: c for c in load_cmdb(root)}
    except Exception:  # a broken component file must not break README rendering
        components = {}
    component = components.get(service)
    if component is None:
        return ("not set up yet. Pick one always-on machine, describe the stack as "
                f"`services/{service}.md` with `runs_on: <server id>`, and run "
                "`dotinfra monitoring setup-server` on that machine. Every other device is "
                "a client; `dotinfra monitoring where` shows where things run.")
    host = component.meta.get("runs_on")
    if not host:
        return (f"described in `services/{service}.md`, which has no `runs_on:` host yet; "
                "set it so every device knows where Prometheus and Grafana live.")
    return (f"Prometheus and Grafana run on **{host}** only (the `{service}` service, "
            f"`{component.rel()}`); every other device is a client. "
            "`dotinfra monitoring where` prints the URLs; on "
            f"{host} itself run `dotinfra monitoring setup-server` once.")


def template_values(root: Path, config: Config) -> dict[str, str]:
    from .skills import TARGETS, project_targets

    url = public_url(config.get("sync", "remote_url", ""))
    backend = str(config.get("vault", "backend", "file"))
    project = project_targets(config)
    dirs = sorted({d for name in project for d in TARGETS[name].project})
    return {
        "name": str(config.get("cmdb", "name", "home")),
        "min_version": str(config.get("cmdb", "min_version") or minor_floor()),
        "clone_url": url or NO_URL,
        "clone_note": "" if url else (
            "\n" + textwrap.fill(
                "The URL is on this repository's web page (GitHub: the green **Code** "
                "button). Once the CMDB has a hub remote, `dotinfra migrate` writes the real "
                "URL here.", width=79, initial_indent="   ", subsequent_indent="   ") + "\n"),
        "age_note": ", plus `age` (the vault is age-encrypted)" if backend == "age" else "",
        "vault_backend": backend,
        "project_skills": "" if not dirs else "\n" + textwrap.fill(
            "This repository already carries the skills for agents started inside it ("
            + ", ".join(f"`{d}`" for d in dirs) + "), so step 4 only adds them for work "
            "in other folders.", width=79, initial_indent="   ", subsequent_indent="   "),
        "monitoring": textwrap.fill("7. **Monitoring** — " + _monitoring_note(root, config),
                                    width=79, subsequent_indent="   "),
    }


def managed_contents(root: Path, config: Config) -> dict[str, str]:
    """The current content of every managed block, rendered for this CMDB."""
    values = template_values(root, config)
    return {target: fill((TEMPLATES / template).read_text(encoding="utf-8"), values)
            for target, template in MANAGED_FILES.items()}


def render_config(name: str, remote_url: str = "") -> str:
    return fill((TEMPLATES / "dotinfra.toml").read_text(encoding="utf-8"), {
        "name": name, "schema": str(SCHEMA), "min_version": minor_floor(),
        "remote_url": json.dumps(public_url(remote_url))[1:-1]})


# --------------------------------------------------------------------------- init


def init_cmdb(root: Path, name: str, *, use_git: bool = True, example: str | None = None,
              remote_url: str | None = None, skills: list[str] | None = None) -> list[str]:
    """Create (or complete) a CMDB at ``root``; existing files are never overwritten.

    ``remote_url`` adds the hub remote and records it for the README;
    ``skills`` (target names) installs project-scope Agent Skills into the repository.
    Returns human-readable lines describing what happened.
    """
    report: list[str] = []
    root.mkdir(parents=True, exist_ok=True)
    (root / STATE_DIR).mkdir(parents=True, exist_ok=True)
    config_path = root / CONFIG_NAME
    if config_path.exists():
        report.append(f"kept    {CONFIG_NAME}")
        if remote_url and not load_config(root).get("sync", "remote_url"):
            set_toml_value(config_path, "sync", "remote_url", public_url(remote_url))
    else:
        config_path.write_text(render_config(name, remote_url or ""), encoding="utf-8")
        report.append(f"created {CONFIG_NAME}")
    for folder in KINDS:
        (root / folder).mkdir(exist_ok=True)
        (root / folder / ".gitkeep").touch()
    if example:
        report += copy_example(root, example)
    if skills:
        from .skills import PROJECT, install_skills

        install_skills(skills, scope=PROJECT, root=root)
        report.append(f"skills  project scope for {', '.join(skills)}")
    config = load_config(root)
    for target, content in managed_contents(root, config).items():
        path = root / target
        if path.exists():
            report.append(f"kept    {target}")
            continue
        path.write_text(wrap(content, style_for(target)), encoding="utf-8")
        report.append(f"created {target}")
    write_index(root, config.get("cmdb", "name", name))
    report.append("wrote   INDEX.md")
    if use_git:
        report += _init_git(root, remote_url, str(config.get("sync", "remote", "origin")))
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


def _init_git(root: Path, remote_url: str | None = None, remote: str = "origin") -> list[str]:
    from .sync import ensure_merge_driver, git, is_repo, remote_names

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
    if remote_url and remote:
        if remote in remote_names(root):
            report.append(f"kept existing remote {remote}")
        else:
            git(root, "remote", "add", "--", remote, remote_url)
            report.append(f"added remote {remote} -> {public_url(remote_url)}")
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


def _interactive() -> bool:
    return sys.stdin.isatty()


def _choose_skills(args) -> list[str]:
    """Targets for ``init --skills``: explicit list, else detected agents (asked on a TTY)."""
    from .skills import TARGETS, detect_targets, parse_targets

    if args.skills is not None:
        return parse_targets(args.skills)
    detected = detect_targets()
    if args.yes or not _interactive():
        return detected
    print(f"Install the dotinfra Agent Skills for: {', '.join(detected)}?\n"
          f"  (Enter = yes; or a comma list from {', '.join(TARGETS)}; 'all'; 'none')")
    answer = input("skills> ").strip()
    return detected if not answer else parse_targets(answer)


def cmd_init(args) -> int:
    root = Path(args.path or args.root or os.environ.get("DOTINFRA_ROOT") or DEFAULT_ROOT)
    root = root.expanduser().resolve()
    name = args.name or ("home" if root == DEFAULT_ROOT else root.name.lstrip(".") or "home")
    if args.remote and args.remote.startswith("-"):
        raise DotinfraError(f"invalid remote URL {args.remote!r}")
    targets = _choose_skills(args)
    scope = args.skills_scope
    project = targets if scope in ("project", "both") else None
    for line in init_cmdb(root, name, use_git=not args.no_git, example=args.example,
                          remote_url=args.remote, skills=project):
        print(line)
    if targets and scope in ("user", "both"):
        from .skills import USER, install_skills

        for line in install_skills(targets, scope=USER, link=args.link):
            print(line)
    print(f"\nCMDB ready at {root}. Next: `dotinfra new server NAME --address IP`, then "
          "`dotinfra lint`.")
    if not args.remote and not args.no_git:
        print("Add a private hub so other devices can clone it: `git remote add origin URL`, "
              "`dotinfra sync`, then `dotinfra migrate` (writes the clone URL into README.md).")
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
    p.add_argument("--remote", metavar="URL",
                   help="hub repository URL: added as the [sync] remote and shown in "
                        "README.md as the clone URL")
    p.add_argument("--skills", metavar="LIST",
                   help="Agent Skills targets: comma list of claude, agents, copilot, cline, "
                        "antigravity (agy), codex, gemini; or all / auto / none (default: auto "
                        "= detected agents, asked interactively on a terminal)")
    p.add_argument("--skills-scope", choices=("user", "project", "both"), default="both",
                   help="user: ~/.<agent>/skills; project: inside the CMDB, committed so "
                        "every clone has them (default: both)")
    p.add_argument("--link", action="store_true",
                   help="user-scope skills as symlinks into the package")
    p.add_argument("--yes", "-y", action="store_true",
                   help="do not ask; use the detected agents")
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
