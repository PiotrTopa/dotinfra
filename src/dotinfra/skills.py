"""`dotinfra skills`: put the bundled Agent Skills where AI coding agents look for them.

Every supported agent reads the standard Agent Skills layout
(``<dir>/<skill-name>/SKILL.md``) from a user-scope directory under ``$HOME`` and
a project-scope directory inside a repository. Project scope is how the skills
travel with a CMDB: installed into ``~/.infra`` and committed, they are there on
every fresh clone.

Several agents also read the cross-agent ``.agents/skills`` directories, so the
table below points them there instead of writing a second copy of every skill
(duplicate skill names confuse some agents).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import DotinfraError
from .versioning import installed_version

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
USER, PROJECT = "user", "project"
RECORD_NAME = "skills.json"


@dataclass(frozen=True)
class Target:
    name: str
    title: str
    user: tuple[str, ...]        # directories under $HOME that dotinfra writes
    project: tuple[str, ...]     # directories relative to the CMDB root
    detect_dirs: tuple[str, ...] = ()   # under $HOME
    detect_bins: tuple[str, ...] = ()
    docs: str = ""


# Paths verified against each agent's documentation on 2026-09-26:
TARGETS: dict[str, Target] = {t.name: t for t in (
    # https://code.claude.com/docs/en/skills — ~/.claude/skills, .claude/skills
    Target("claude", "Claude Code", (".claude/skills",), (".claude/skills",),
           (".claude",), ("claude",), "https://code.claude.com/docs/en/skills"),
    # Cross-agent convention, read by Codex, Gemini CLI, GitHub Copilot and (project)
    # Antigravity — see their entries. Always installed.
    Target("agents", "~/.agents convention (Codex, Gemini CLI, Copilot, ...)",
           (".agents/skills",), (".agents/skills",),
           docs="https://learn.chatgpt.com/docs/build-skills"),
    # https://docs.github.com/en/copilot/concepts/agents/about-agent-skills —
    # personal ~/.copilot/skills or ~/.agents/skills; project .github/skills,
    # .claude/skills or .agents/skills. dotinfra uses the shared .agents dirs.
    Target("copilot", "GitHub Copilot (CLI, VS Code, cloud agent)",
           (".agents/skills",), (".agents/skills",), (".copilot",), ("copilot",),
           "https://docs.github.com/en/copilot/concepts/agents/about-agent-skills"),
    # https://docs.cline.bot/features/skills — global ~/.cline/skills; project
    # .cline/skills, .clinerules/skills or .claude/skills (dotinfra uses the last,
    # shared with Claude Code).
    Target("cline", "Cline", (".cline/skills",), (".claude/skills",), (".cline",), ("cline",),
           "https://docs.cline.bot/features/skills"),
    # https://antigravity.google/docs/skills — CLI (`agy`) ~/.gemini/antigravity-cli/skills,
    # IDE ~/.gemini/config/skills; workspace .agents/skills.
    Target("antigravity", "Google Antigravity (agy CLI and IDE)",
           (".gemini/antigravity-cli/skills", ".gemini/config/skills"), (".agents/skills",),
           (".gemini/antigravity-cli", ".gemini/antigravity"), ("agy", "antigravity"),
           "https://antigravity.google/docs/skills"),
    # https://learn.chatgpt.com/docs/build-skills (was developers.openai.com/codex/skills)
    # — user $HOME/.agents/skills, repo .agents/skills.
    Target("codex", "OpenAI Codex CLI", (".agents/skills",), (".agents/skills",),
           (".codex",), ("codex",), "https://learn.chatgpt.com/docs/build-skills"),
    # https://geminicli.com/docs/cli/skills/ — ~/.gemini/skills or the ~/.agents/skills
    # alias; workspace .gemini/skills or .agents/skills (the alias wins).
    Target("gemini", "Gemini CLI", (".agents/skills",), (".agents/skills",),
           (".gemini",), ("gemini",), "https://geminicli.com/docs/cli/skills/"),
)}
ALIASES = {"agy": "antigravity"}
ALWAYS = "agents"


# --------------------------------------------------------------------------- targets


def parse_targets(spec: str | None, home: Path | None = None) -> list[str]:
    """``"claude,agy"`` / ``"all"`` / ``"auto"`` / ``"both"`` / ``"none"`` → target names."""
    spec = (spec or "auto").strip().lower()
    if spec in ("", "none"):
        return []
    if spec == "auto":
        return detect_targets(home)
    if spec == "all":
        return list(TARGETS)
    if spec == "both":  # 0.1.x spelling
        return ["claude", "agents"]
    names = []
    for raw in spec.split(","):
        name = ALIASES.get(raw.strip(), raw.strip())
        if not name:
            continue
        if name not in TARGETS:
            raise DotinfraError(f"unknown skills target {raw.strip()!r} (one of: "
                                f"{', '.join([*TARGETS, *ALIASES])}, all, auto, none)")
        if name not in names:
            names.append(name)
    return names


def _on_path(binary: str) -> bool:
    return shutil.which(binary) is not None


def detect_targets(home: Path | None = None) -> list[str]:
    """Agents that look installed here (config dir in $HOME or binary on PATH), plus
    the cross-agent ``agents`` target."""
    home = home or Path.home()
    found = [ALWAYS]
    for target in TARGETS.values():
        if target.name == ALWAYS:
            continue
        if (any((home / d).is_dir() for d in target.detect_dirs)
                or any(_on_path(b) for b in target.detect_bins)):
            found.append(target.name)
    return found


def target_dirs(targets: list[str] | str, scope: str = USER, *, home: Path | None = None,
                root: Path | None = None) -> list[Path]:
    """Distinct directories to write for ``targets`` in ``scope`` (``user`` or ``project``)."""
    if isinstance(targets, str):
        targets = parse_targets(targets, home)
    base = (home or Path.home()) if scope == USER else root
    if base is None:
        raise DotinfraError("project-scope skills need a CMDB root")
    dirs: list[Path] = []
    for name in targets:
        target = TARGETS[name]
        for rel in (target.user if scope == USER else target.project):
            if base / rel not in dirs:
                dirs.append(base / rel)
    return dirs


def scopes(scope: str) -> list[str]:
    return [USER, PROJECT] if scope == "both" else [scope]


# --------------------------------------------------------------------------- content


def bundled_skills() -> list[Path]:
    skills = sorted(p for p in SKILLS_DIR.glob("*") if (p / "SKILL.md").is_file())
    if not skills:
        raise DotinfraError(f"no bundled skills found in {SKILLS_DIR} (broken installation?)")
    return skills


def tree_hash(directory: Path) -> str | None:
    """Content hash of a skill directory (paths + bytes); ``None`` if it is missing."""
    if not directory.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()
                       and "__pycache__" not in p.parts):
        digest.update(path.relative_to(directory).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def skills_state(directory: Path) -> str:
    """``current``, ``stale``, ``partial`` or ``missing`` for one skills directory."""
    states = []
    for skill in bundled_skills():
        dest = directory / skill.name
        if dest.is_symlink():
            states.append("current" if dest.resolve() == skill.resolve() else "stale")
        elif not dest.is_dir():
            states.append("missing")
        else:
            states.append("current" if tree_hash(dest) == tree_hash(skill) else "stale")
    if all(s == "missing" for s in states):
        return "missing"
    if "stale" in states:
        return "stale"
    return "current" if all(s == "current" for s in states) else "partial"


def install_into(directory: Path, *, link: bool = False) -> list[str]:
    """Copy (or symlink) every bundled skill into one directory; only changed ones are
    rewritten, other skills in the directory are left alone."""
    report = []
    directory.mkdir(parents=True, exist_ok=True)
    for skill in bundled_skills():
        dest = directory / skill.name
        if link:
            if dest.is_symlink() and dest.resolve() == skill.resolve():
                continue
        elif dest.is_dir() and not dest.is_symlink() and tree_hash(dest) == tree_hash(skill):
            continue
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        elif dest.is_dir():
            shutil.rmtree(dest)
        if link:
            dest.symlink_to(skill, target_is_directory=True)
        else:
            shutil.copytree(skill, dest, ignore=shutil.ignore_patterns("__pycache__"))
        report.append(f"{'linked' if link else 'installed'} {dest}")
    return report


# --------------------------------------------------------------------------- record


def record_path(home: Path | None = None) -> Path:
    if home is None and os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"]) / "dotinfra" / RECORD_NAME
    return (home or Path.home()) / ".config" / "dotinfra" / RECORD_NAME


def read_record(home: Path | None = None) -> dict:
    """What `skills install` put where in $HOME (``{"dirs": {path: {"link": bool}}}``)."""
    path = record_path(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_record(dirs: list[Path], targets: list[str], link: bool,
                  home: Path | None = None) -> None:
    record = read_record(home)
    entries = record.setdefault("dirs", {})
    for directory in dirs:
        entries[str(directory)] = {"link": link}
    record["targets"] = sorted(set(record.get("targets", [])) | set(targets))
    record["version"] = installed_version()
    path = record_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- install


def install_skills(target: str | list[str] = "auto", *, link: bool = False,
                   home: Path | None = None, scope: str = USER,
                   root: Path | None = None) -> list[str]:
    """Install for ``target`` (spec string or list of names) in ``scope``.

    User-scope installs are recorded (so ``dotinfra migrate`` can refresh them);
    project-scope installs are recorded in the CMDB's ``[skills] project``.
    """
    names = parse_targets(target, home) if isinstance(target, str) else list(target)
    if not names:
        return []
    report = []
    for scope_name in scopes(scope):
        dirs = target_dirs(names, scope_name, home=home, root=root)
        for directory in dirs:
            report += install_into(directory, link=link and scope_name == USER)
        if scope_name == USER:
            _write_record(dirs, names, link, home)
        else:
            _record_project(root, names)
    if not report:
        report.append(f"skills already current for: {', '.join(names)}")
    return report


def _record_project(root: Path, names: list[str]) -> None:
    from .config import CONFIG_NAME, read_toml, set_toml_value

    path = root / CONFIG_NAME
    if not path.is_file():
        return
    current = read_toml(path).get("skills", {}).get("project", [])
    merged = list(current) + [n for n in names if n not in current]
    if merged != current:
        set_toml_value(path, "skills", "project", merged)


def refresh_user_skills(home: Path | None = None) -> list[str]:
    """Re-install every recorded user-scope directory (after an upgrade)."""
    report = []
    for directory, info in read_record(home).get("dirs", {}).items():
        path = Path(directory)
        if path.is_dir():
            report += install_into(path, link=bool(info.get("link")))
    return report


def project_targets(config) -> list[str]:
    names = config.get("skills", "project", []) or []
    return [ALIASES.get(n, n) for n in names if ALIASES.get(n, n) in TARGETS]


# --------------------------------------------------------------------------- CLI


def _cmdb_root(args) -> Path:
    from .context import get_context

    return get_context(args).root


def cmd_skills_install(args) -> int:
    root = _cmdb_root(args) if args.scope in (PROJECT, "both") else None
    for line in install_skills(args.target, link=args.link, scope=args.scope, root=root):
        print(line)
    if root is not None:
        print(f"project-scope skills are in {root}; `dotinfra sync` shares them with every clone")
    return 0


def cmd_skills_status(args) -> int:
    for line in status_lines(args):
        print(line)
    return 0


def status_lines(args=None, home: Path | None = None) -> list[str]:
    """One line per (target, scope, directory) worth mentioning."""
    from .context import get_context

    home = home or Path.home()
    detected = set(detect_targets(home))
    recorded = set(read_record(home).get("targets", []))
    lines = []
    for name, target in TARGETS.items():
        mark = "detected" if name in detected else "-"
        for directory in target_dirs([name], USER, home=home):
            lines.append(f"{name:<12} user     {skills_state(directory):<8} {directory}  "
                         f"({mark}{', recorded' if name in recorded else ''})")
    ctx = get_context(args, require=False) if args is not None else None
    if ctx is not None and (ctx.root / ".dotinfra.toml").is_file():
        for name in project_targets(ctx.config):
            for directory in target_dirs([name], PROJECT, root=ctx.root):
                lines.append(f"{name:<12} project  {skills_state(directory):<8} {directory}")
    return lines


TARGET_HELP = ("comma-separated agents: " + ", ".join(TARGETS) + " (alias agy), or all / "
               "auto (detected agents + agents) / none; 'both' = claude,agents")


def register(subparsers) -> None:
    p = subparsers.add_parser("skills", help="install the bundled Agent Skills",
                              description="Manage the Agent Skills that teach AI agents the "
                                          "read-first / write-back workflow.")
    sub = p.add_subparsers(dest="skills_command", metavar="COMMAND", required=True)
    install = sub.add_parser(
        "install", help="install skills for Claude Code, Copilot, Cline, Antigravity, ...",
        description="Install the bundled skills where agents look for them. User scope "
                    "writes under $HOME; project scope writes into the CMDB repository so "
                    "the skills travel with every clone. Existing copies of these skills "
                    "are replaced; other skills are untouched. Targets and paths: "
                    + "; ".join(f"{t.name}: ~/{', ~/'.join(t.user)} | {', '.join(t.project)}"
                                for t in TARGETS.values()))
    install.add_argument("--target", default="auto", metavar="LIST", help=TARGET_HELP
                         + " (default: auto)")
    install.add_argument("--scope", choices=(USER, PROJECT, "both"), default=USER,
                         help="user ($HOME), project (the CMDB repo) or both (default: user)")
    install.add_argument("--link", action="store_true",
                         help="user scope: symlink instead of copying (follows package upgrades)")
    install.set_defaults(func=cmd_skills_install)
    status = sub.add_parser("status", help="which agents have the skills, and are they current",
                            description="Show, per agent and scope, whether the bundled "
                                        "skills are installed and current.")
    status.set_defaults(func=cmd_skills_status, version_guard="warn")

