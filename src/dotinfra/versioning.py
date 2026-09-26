"""Version numbers: comparing them and guarding a CMDB against a too-old dotinfra.

A CMDB records the oldest dotinfra release that may write to it in
``[cmdb] min_version`` (set by ``dotinfra migrate``). Commands that load a CMDB
refuse to run (exit 3) when the installed version is older; read-only commands
only warn. ``dotinfra sync`` applies the same rule to incoming commits before
merging them.
"""

from __future__ import annotations

import re
import sys

import dotinfra

from . import DotinfraError

GUARD_EXIT = 3
_PART_RE = re.compile(r"(\d+)")


class VersionTooOld(DotinfraError):
    """The CMDB (or an incoming commit) needs a newer dotinfra. Exit code 3."""

    exit_code = GUARD_EXIT


def installed_version() -> str:
    """The running dotinfra version (looked up at call time, so tests can patch it)."""
    return dotinfra.__version__


def parse_version(text: str | None) -> tuple[int, int, int]:
    """``"0.2.0"`` → ``(0, 2, 0)``; tolerant of ``v`` prefixes and suffixes (``0.3.0rc1``)."""
    parts = [int(m.group(1)) for m in (_PART_RE.match(p) for p in
                                        str(text or "0").lstrip("vV").split(".")[:3]) if m]
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def minor_floor(version: str | None = None) -> str:
    """The ``X.Y.0`` of a version: what ``migrate`` records as ``min_version``."""
    major, minor, _ = parse_version(version or installed_version())
    return f"{major}.{minor}.0"


def is_newer(required: str | None, installed: str | None = None) -> bool:
    """True when ``required`` is a later version than ``installed`` (default: running)."""
    if not required:
        return False
    return parse_version(required) > parse_version(installed or installed_version())


def too_old_message(required: str, where: str = "this CMDB") -> str:
    return (f"{where} needs dotinfra ≥ {required} (installed: {installed_version()}); "
            "run `dotinfra upgrade`")


def check_min_version(config, *, mode: str = "enforce") -> None:
    """Apply the version guard for a loaded config.

    ``mode`` is ``"enforce"`` (raise :class:`VersionTooOld`), ``"warn"`` (print a
    warning to stderr) or ``"off"``.
    """
    required = config.get("cmdb", "min_version")
    if mode == "off" or not is_newer(required):
        return
    message = too_old_message(str(required))
    if mode == "warn":
        print(f"warning: {message}", file=sys.stderr)
        return
    raise VersionTooOld(message)
