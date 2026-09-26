"""`dotinfra upgrade`: update the installed dotinfra, then migrate the CMDB.

The upgrade command depends on how dotinfra was installed:

- pipx (the package lives in a ``pipx/venvs/`` virtualenv) → ``pipx upgrade dotinfra``;
- ``pip install --user`` → ``python -m pip install --user -U git+URL``;
- another virtualenv → ``python -m pip install -U git+URL``;
- an editable install or a source checkout → refused: update the checkout with git;
- a system-wide install → refused with a hint to use pipx.

``--check`` only compares the installed version with the latest GitHub release
(5 s timeout); being offline is not an error.
"""

from __future__ import annotations

import json
import shutil
import site
import subprocess
import sys
import urllib.error
import urllib.request
from importlib import metadata
from pathlib import Path

import dotinfra

from . import DotinfraError
from .config import CONFIG_NAME, find_root
from .versioning import installed_version, is_newer, parse_version

REPO = "PiotrTopa/dotinfra"
GIT_URL = f"git+https://github.com/{REPO}"
API = f"https://api.github.com/repos/{REPO}"
TIMEOUT = 5


# --------------------------------------------------------------------------- releases


def _get_json(url: str):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "dotinfra"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def latest_release(pre: bool = False) -> str | None:
    """Newest release tag on GitHub (``--pre``: including pre-releases); ``None`` offline.

    Falls back to the highest ``vX.Y.Z`` tag when the repository has no releases.
    """
    try:
        releases = _get_json(f"{API}/releases?per_page=30")
        tags = [r.get("tag_name", "") for r in releases or []
                if not r.get("draft") and (pre or not r.get("prerelease"))]
        if not tags:
            tags = [t.get("name", "") for t in _get_json(f"{API}/tags?per_page=100") or []]
            tags = [t for t in tags if pre or t.lstrip("v").replace(".", "").isdigit()]
    except (OSError, ValueError, urllib.error.URLError):
        return None
    tags = [t for t in tags if t]
    return max(tags, key=parse_version) if tags else None


# --------------------------------------------------------------------------- install method


def install_method() -> tuple[str, str]:
    """``(kind, detail)`` with kind one of pipx, user, venv, editable, source, system."""
    package = Path(dotinfra.__file__).resolve().parent
    try:
        dist = metadata.distribution("dotinfra")
    except metadata.PackageNotFoundError:
        return "source", str(package.parent)
    direct = dist.read_text("direct_url.json")
    if direct:
        try:
            info = json.loads(direct)
        except ValueError:
            info = {}
        if info.get("dir_info", {}).get("editable"):
            return "editable", str(info.get("url", package))
    located = Path(str(dist.locate_file("dotinfra/__init__.py"))).resolve()
    if located != package / "__init__.py":
        return "source", str(package.parent)  # a checkout on PYTHONPATH shadows the install
    prefix = Path(sys.prefix).resolve()
    if "pipx" in prefix.parts and "venvs" in prefix.parts:
        return "pipx", str(prefix)
    user_site = Path(site.getusersitepackages()).resolve()
    if package.is_relative_to(user_site):
        return "user", str(user_site)
    if sys.prefix != sys.base_prefix:
        return "venv", str(prefix)
    return "system", str(prefix)


def upgrade_command(kind: str, detail: str, *, pre: bool = False) -> list[str]:
    """The command that upgrades an installation of ``kind``; DotinfraError if we should not."""
    pre_args = ["--pre"] if pre else []
    if kind == "pipx":
        pipx = shutil.which("pipx")
        if not pipx:
            raise DotinfraError(f"dotinfra is installed with pipx ({detail}) but `pipx` is not "
                                "on PATH; run `pipx upgrade dotinfra` yourself")
        return [pipx, "upgrade", *(["--pip-args=--pre"] if pre else []), "dotinfra"]
    if kind == "user":
        return [sys.executable, "-m", "pip", "install", "--user", "-U", *pre_args, GIT_URL]
    if kind == "venv":
        return [sys.executable, "-m", "pip", "install", "-U", *pre_args, GIT_URL]
    if kind in ("editable", "source"):
        raise DotinfraError(f"dotinfra runs from a source checkout ({detail}); update it with "
                            "`git pull` there (and `pip install -e .` if it is an editable "
                            "install), then run `dotinfra migrate`")
    raise DotinfraError(f"dotinfra is installed system-wide ({detail}); upgrade it with the "
                        f"tool that installed it, or switch to `pipx install {GIT_URL}`")


# --------------------------------------------------------------------------- CLI


def _cmdb_root(args) -> Path | None:
    root = Path(args.root).expanduser().resolve() if getattr(args, "root", None) else find_root()
    return root if (root / CONFIG_NAME).is_file() else None


def cmd_upgrade(args) -> int:
    current = installed_version()
    if args.check:
        latest = latest_release(args.pre)
        if latest is None:
            print(f"dotinfra {current}; could not reach GitHub to check for updates (offline?)")
        elif is_newer(latest, current):
            print(f"dotinfra {latest.lstrip('v')} is available (installed {current}); "
                  "run `dotinfra upgrade`")
        else:
            print(f"dotinfra {current} is up to date (latest release {latest})")
        return 0
    kind, detail = install_method()
    command = upgrade_command(kind, detail, pre=args.pre)
    print(f"dotinfra {current} ({kind} install); running: {' '.join(command)}", flush=True)
    result = subprocess.run(command)
    if result.returncode != 0:
        raise DotinfraError(f"the upgrade command failed (exit {result.returncode})")
    root = _cmdb_root(args)
    if root is None:
        print("upgraded; inside a CMDB, run `dotinfra migrate` next")
        return 0
    print(f"upgraded; next step is `dotinfra migrate` for {root} — running it now", flush=True)
    return subprocess.run([sys.executable, "-m", "dotinfra", "--root", str(root), "migrate",
                           "--yes"]).returncode


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "upgrade", help="upgrade dotinfra itself, then migrate the CMDB",
        description="Detect how dotinfra was installed (pipx, pip --user, a virtualenv) and "
                    "upgrade it from GitHub, then run `dotinfra migrate --yes` when inside a "
                    "CMDB. Source checkouts and editable installs are left to git. --check "
                    "only compares with the latest GitHub release.")
    p.add_argument("--check", action="store_true",
                   help="only report whether a newer release exists (no changes; offline-safe)")
    p.add_argument("--pre", action="store_true", help="include pre-releases")
    p.set_defaults(func=cmd_upgrade, version_guard="warn")
