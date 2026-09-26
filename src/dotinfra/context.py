"""Per-invocation state shared by command handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import DotinfraError
from .config import CONFIG_NAME, Config, find_root, load_config
from .model import Component, load_cmdb


@dataclass
class Context:
    root: Path
    config: Config
    _components: list[Component] | None = field(default=None, repr=False)

    def components(self) -> list[Component]:
        if self._components is None:
            self._components = load_cmdb(self.root)
        return self._components

    def component(self, component_id: str) -> Component:
        for component in self.components():
            if component.id == component_id:
                return component
        raise DotinfraError(f"no component with id {component_id!r} (see `dotinfra ls`)")

    def secret(self, key: str) -> str:
        from .vault import open_vault

        return open_vault(self.config).get(key)

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)


def get_context(args=None, *, require: bool = True) -> Context:
    """Build the context for a command, honouring the global ``--root`` option.

    With ``require`` (the default) a missing CMDB is a friendly error instead of
    a pile of empty results.
    """
    explicit = getattr(args, "root", None)
    root = Path(explicit).expanduser().resolve() if explicit else find_root()
    if require and not (root / CONFIG_NAME).is_file():
        raise DotinfraError(f"no dotinfra CMDB at {root} (missing {CONFIG_NAME}); "
                            "run `dotinfra init` or pass --root / set DOTINFRA_ROOT")
    return Context(root=root, config=load_config(root))
