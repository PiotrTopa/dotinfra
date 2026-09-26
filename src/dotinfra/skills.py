"""`dotinfra skills install`: put the bundled Agent Skills where agents look for them."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import DotinfraError

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
TARGETS = {"claude": ".claude/skills", "agents": ".agents/skills"}


def bundled_skills() -> list[Path]:
    skills = sorted(p for p in SKILLS_DIR.glob("*") if (p / "SKILL.md").is_file())
    if not skills:
        raise DotinfraError(f"no bundled skills found in {SKILLS_DIR} (broken installation?)")
    return skills


def target_dirs(target: str, home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    names = list(TARGETS) if target == "both" else [target]
    return [home / TARGETS[name] for name in names]


def install_skills(target: str, *, link: bool = False, home: Path | None = None) -> list[str]:
    """Copy (or symlink) every bundled skill into the target skill directories."""
    report = []
    for directory in target_dirs(target, home):
        directory.mkdir(parents=True, exist_ok=True)
        for skill in bundled_skills():
            dest = directory / skill.name
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            elif dest.is_dir():
                shutil.rmtree(dest)
            if link:
                dest.symlink_to(skill, target_is_directory=True)
            else:
                shutil.copytree(skill, dest)
            report.append(f"{'linked' if link else 'installed'} {dest}")
    return report


def cmd_skills_install(args) -> int:
    for line in install_skills(args.target, link=args.link):
        print(line)
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("skills", help="install the bundled Agent Skills",
                              description="Manage the Agent Skills that teach AI agents the "
                                          "read-first / write-back workflow.")
    sub = p.add_subparsers(dest="skills_command", metavar="COMMAND", required=True)
    install = sub.add_parser(
        "install", help="install skills for Claude Code and/or other agents",
        description="Install the bundled skills into ~/.claude/skills (Claude Code) and/or "
                    "~/.agents/skills (other agents). Existing copies of these skills are "
                    "replaced; other skills are untouched.")
    install.add_argument("--target", choices=("claude", "agents", "both"), default="both",
                         help="where to install (default: both)")
    install.add_argument("--link", action="store_true",
                         help="symlink instead of copying (follows package upgrades)")
    install.set_defaults(func=cmd_skills_install)
