"""Locating the CMDB root and reading `.dotinfra.toml` (+ the per-device `.dotinfra.local.toml`)."""

from __future__ import annotations

import copy
import json
import os
import re
import socket
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import DotinfraError

DEFAULT_ROOT = Path("~/.infra").expanduser()
CONFIG_NAME = ".dotinfra.toml"
LOCAL_CONFIG_NAME = ".dotinfra.local.toml"  # untracked, per-device overrides
STATE_DIR = ".dotinfra/state"

DEFAULTS: dict[str, dict] = {
    "cmdb": {"name": "home", "device": ""},
    "vault": {
        "backend": "file",
        "path": "~/.config/dotinfra/vault.json",
        "age_file": "vault.age",
        "age_identity": "~/.config/dotinfra/age.key",
        "age_recipients": [],
    },
    "sync": {"remote": "origin", "peers": [], "auto_commit": True, "branch": "main"},
    # grafana_url / prometheus_url have no default: when unset they are resolved from
    # the `service` component (see monitoring.monitoring_endpoints).
    "monitoring": {
        "service": "monitoring",
        "role": "client",
        "grafana_user": "admin",
        "grafana_password_key": "grafana_password",
        "bundle_dir": "~/dotinfra-monitoring",
    },
    # "auto": grafana when a monitoring service or URL is configured, else events/<YYYY>.md
    "events": {"backend": "auto"},
    "lint": {"max_lines": 120},
}


_SECTION_RE = re.compile(r"\s*\[[^\]]+\]\s*(#.*)?$")


class ConfigError(DotinfraError):
    pass


def find_root(start: Path | None = None) -> Path:
    """Return the CMDB root.

    Order: ``$DOTINFRA_ROOT``; the nearest directory at or above ``start`` (default: cwd)
    that contains ``.dotinfra.toml``; ``DEFAULT_ROOT``.
    """
    env = os.environ.get("DOTINFRA_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    return DEFAULT_ROOT


@dataclass
class Config:
    root: Path
    data: dict

    def get(self, section: str, key: str, default=None):
        value = self.data.get(section, {}).get(key)
        return default if value is None else value

    def path(self, section: str, key: str) -> Path:
        """A path-valued setting: ``~`` is expanded, relative paths are relative to the root."""
        path = Path(str(self.get(section, key, ""))).expanduser()
        return path if path.is_absolute() else self.root / path

    @property
    def state_dir(self) -> Path:
        return self.root / STATE_DIR

    @property
    def local_path(self) -> Path:
        """This device's untracked override file."""
        return self.root / LOCAL_CONFIG_NAME

    @property
    def device(self) -> str:
        """This device's name, used in sync commit messages."""
        return self.get("cmdb", "device") or socket.gethostname().split(".")[0]


def read_toml(path: Path) -> dict:
    """Parse a TOML file; ``{}`` when it does not exist."""
    if not path.is_file():
        return {}
    return parse_toml(path.read_text(encoding="utf-8"), str(path))


def parse_toml(text: str, where: str = CONFIG_NAME) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{where}: invalid TOML: {exc}") from None


def deep_merge(base: dict, override: dict) -> dict:
    """Merge ``override`` into ``base`` in place: tables recursively, other values replaced."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def load_config(root: Path, *, local: bool = True) -> Config:
    """Defaults, then ``.dotinfra.toml`` (shared), then ``.dotinfra.local.toml`` (this device)."""
    data = copy.deepcopy(DEFAULTS)
    deep_merge(data, read_toml(root / CONFIG_NAME))
    if local:
        deep_merge(data, read_toml(root / LOCAL_CONFIG_NAME))
    return Config(root=root, data=data)


def set_toml_value(path: Path, section: str, key: str, value) -> None:
    """Set ``section.key`` in a TOML file by editing one line, keeping comments intact.

    Only single-line values are supported (strings, booleans, numbers, flat lists),
    which covers every setting dotinfra writes itself.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(set_toml_text(text, section, key, value), encoding="utf-8")


def _section_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    header = f"[{section}]"
    start = next((i for i, line in enumerate(lines) if line.split("#")[0].strip() == header),
                 None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if _SECTION_RE.match(lines[i])),
               len(lines))
    return start, end


def set_toml_text(text: str, section: str, key: str, value) -> str:
    """:func:`set_toml_value` on a string."""
    rendered = f"{key} = {_toml_literal(value)}"
    lines = text.splitlines()
    header = f"[{section}]"
    bounds = _section_bounds(lines, section)
    if bounds is None:
        lines += ([""] if lines and lines[-1].strip() else []) + [header, rendered]
    else:
        start, end = bounds
        key_re = re.compile(rf"\s*{re.escape(key)}\s*=")
        for i in range(start + 1, end):
            if key_re.match(lines[i]):
                comment = _trailing_comment(lines[i])
                lines[i] = rendered + (f"  {comment}" if comment else "")
                break
        else:
            lines.insert(start + 1, rendered)
    return "\n".join(lines) + "\n"


def comment_out_toml_key(text: str, section: str, key: str, note: str = "") -> str:
    """Turn ``key = ...`` in ``[section]`` into a comment (``# key = ...  # note``)."""
    lines = text.splitlines()
    bounds = _section_bounds(lines, section)
    if bounds is None:
        return text
    key_re = re.compile(rf"\s*{re.escape(key)}\s*=")
    for i in range(bounds[0] + 1, bounds[1]):
        if key_re.match(lines[i]):
            code = lines[i][: len(lines[i]) - len(_trailing_comment(lines[i]))].rstrip()
            lines[i] = f"# {code}" + (f"  # {note}" if note else "")
    return "\n".join(lines) + "\n"


def _toml_literal(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_literal(v) for v in value) + "]"
    return json.dumps(str(value))


def _trailing_comment(line: str) -> str:
    in_string = None
    for i, ch in enumerate(line):
        if in_string:
            if ch == in_string:
                in_string = None
        elif ch in "\"'":
            in_string = ch
        elif ch == "#":
            return line[i:]
    return ""
