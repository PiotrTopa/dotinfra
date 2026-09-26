"""Locating the CMDB root and reading `.dotinfra.toml`."""

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
    "monitoring": {
        "prometheus_url": "http://localhost:9090",
        "grafana_url": "http://localhost:3000",
        "grafana_user": "admin",
        "grafana_password_key": "grafana_password",
        "bundle_dir": "~/dotinfra-monitoring",
    },
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
    def device(self) -> str:
        """This device's name, used in sync commit messages."""
        return self.get("cmdb", "device") or socket.gethostname().split(".")[0]


def load_config(root: Path) -> Config:
    data = copy.deepcopy(DEFAULTS)
    path = root / CONFIG_NAME
    if path.is_file():
        try:
            user = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: invalid TOML: {exc}") from None
        for section, values in user.items():
            if isinstance(values, dict):
                data.setdefault(section, {}).update(values)
            else:
                data[section] = values
    return Config(root=root, data=data)


def set_toml_value(path: Path, section: str, key: str, value) -> None:
    """Set ``section.key`` in a TOML file by editing one line, keeping comments intact.

    Only single-line values are supported (strings, booleans, numbers, flat lists),
    which covers every setting dotinfra writes itself.
    """
    rendered = f"{key} = {_toml_literal(value)}"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    header = f"[{section}]"
    start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        lines += ([""] if lines and lines[-1].strip() else []) + [header, rendered]
    else:
        end = next((i for i in range(start + 1, len(lines)) if _SECTION_RE.match(lines[i])),
                   len(lines))
        key_re = re.compile(rf"\s*{re.escape(key)}\s*=")
        for i in range(start + 1, end):
            if key_re.match(lines[i]):
                comment = _trailing_comment(lines[i])
                lines[i] = rendered + (f"  {comment}" if comment else "")
                break
        else:
            lines.insert(start + 1, rendered)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
