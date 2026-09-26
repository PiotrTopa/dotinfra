"""The secret vault: docs reference keys, values live here.

Backends:

* ``file`` — a plaintext JSON object ``{key: secret}`` (mode 0600) outside the CMDB.
* ``age``  — the same JSON encrypted with `age <https://age-encryption.org>`_ into a file
  inside the CMDB, so it syncs with it. Each device decrypts with its own identity.
"""

from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import DotinfraError
from .config import CONFIG_NAME, Config, set_toml_value
from .context import get_context

BACKENDS = ("file", "age")


class VaultError(DotinfraError):
    pass


class Vault:
    """Common key/value behaviour; subclasses implement ``load``/``save``/``describe``."""

    def load(self) -> dict[str, str]:
        raise NotImplementedError

    def save(self, data: dict[str, str]) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError

    def get(self, key: str) -> str:
        data = self.load()
        if key not in data:
            raise VaultError(f"no secret {key!r} in the vault ({self.describe()}); "
                             f"add it with `dotinfra vault set {key}`")
        return data[key]

    def set(self, key: str, value: str) -> None:
        data = self.load()
        data[key] = value
        self.save(data)

    def delete(self, key: str) -> None:
        data = self.load()
        if key not in data:
            raise VaultError(f"no secret {key!r} in the vault ({self.describe()})")
        del data[key]
        self.save(data)

    def keys(self) -> list[str]:
        return sorted(self.load())


def _validate(data, source: str) -> dict[str, str]:
    if not isinstance(data, dict):
        raise VaultError(f"{source}: expected a JSON object {{key: secret}}")
    bad = sorted(key for key, value in data.items() if not isinstance(value, str) or not key)
    if bad:
        raise VaultError(f"{source}: values must be strings; offending key(s): {', '.join(bad)}")
    return data


def _write_private(path: Path, payload: bytes) -> None:
    """Atomically write ``payload`` with mode 0600, creating a 0700 parent if needed."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class FileVault(Vault):
    def __init__(self, path: Path):
        self.path = path

    def describe(self) -> str:
        return f"file {self.path}"

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError) as exc:
            raise VaultError(f"cannot read vault {self.path}: {exc}") from None
        return _validate(data, str(self.path))

    def save(self, data: dict[str, str]) -> None:
        payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
        _write_private(self.path, payload.encode())


def age_binary(name: str = "age") -> str:
    found = shutil.which(name)
    if not found:
        raise VaultError(f"the age vault backend needs `{name}` on PATH "
                         "(install it from https://age-encryption.org)")
    return found


def _run(cmd: list[str], data: bytes | None = None) -> bytes:
    result = subprocess.run(cmd, input=data, capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise VaultError(f"`{Path(cmd[0]).name}` failed: {detail or f'exit {result.returncode}'}")
    return result.stdout


class AgeVault(Vault):
    def __init__(self, path: Path, identity: Path, recipients: list[str]):
        self.path = path
        self.identity = identity
        self.recipients = recipients

    def describe(self) -> str:
        return f"age {self.path}"

    def public_key(self) -> str:
        if not self.identity.is_file():
            raise VaultError(f"age identity {self.identity} not found; create it with "
                             f"`age-keygen -o {self.identity}` "
                             "or `dotinfra vault migrate --to age`")
        return _run([age_binary("age-keygen"), "-y", str(self.identity)]).decode().strip()

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        if not self.identity.is_file():
            raise VaultError(f"cannot decrypt {self.path}: identity {self.identity} not found")
        plain = _run([age_binary(), "--decrypt", "-i", str(self.identity), str(self.path)])
        try:
            return _validate(json.loads(plain or b"{}"), str(self.path))
        except json.JSONDecodeError as exc:
            raise VaultError(f"{self.path}: decrypted content is not JSON: {exc}") from None

    def all_recipients(self) -> list[str]:
        own = self.public_key()
        return [own] + [r for r in self.recipients if r and r != own]

    def save(self, data: dict[str, str]) -> None:
        cmd = [age_binary(), "--encrypt"]
        for recipient in self.all_recipients():
            cmd += ["-r", recipient]
        payload = json.dumps(data, indent=2, sort_keys=True).encode()
        _write_private(self.path, _run(cmd, payload))


def open_vault(config: Config, backend: str | None = None) -> Vault:
    """The vault configured in ``[vault]`` (``backend`` overrides the configured one)."""
    backend = backend or config.get("vault", "backend", "file")
    if backend == "file":
        return FileVault(config.path("vault", "path"))
    if backend == "age":
        recipients = [str(r) for r in config.get("vault", "age_recipients", [])]
        return AgeVault(config.path("vault", "age_file"), config.path("vault", "age_identity"),
                        recipients)
    raise VaultError(f"unknown vault backend {backend!r} in {CONFIG_NAME} "
                     f"(expected one of: {', '.join(BACKENDS)})")


def ensure_age_identity(path: Path) -> bool:
    """Create an age identity at ``path`` if missing; return True when one was created."""
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _run([age_binary("age-keygen"), "-o", str(path)])
    os.chmod(path, 0o600)
    return True


# --------------------------------------------------------------------------- CLI


def _read_secret(key: str) -> str:
    if sys.stdin.isatty():
        value = getpass.getpass(f"secret for {key}: ")
        if value != getpass.getpass("again: "):
            raise VaultError("the two entries differ; nothing stored")
    else:
        value = sys.stdin.readline().rstrip("\n")
    if not value:
        raise VaultError("empty secret; nothing stored")
    return value


def cmd_list(args) -> int:
    for key in open_vault(get_context(args).config).keys():
        print(key)
    return 0


def cmd_get(args) -> int:
    sys.stdout.write(open_vault(get_context(args).config).get(args.key) + "\n")
    return 0


def cmd_set(args) -> int:
    vault = open_vault(get_context(args).config)
    vault.set(args.key, _read_secret(args.key))
    print(f"stored {args.key} in {vault.describe()}", file=sys.stderr)
    return 0


def cmd_rm(args) -> int:
    vault = open_vault(get_context(args).config)
    vault.delete(args.key)
    print(f"removed {args.key}", file=sys.stderr)
    return 0


def cmd_exec(args) -> int:
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise VaultError("no command given; usage: dotinfra vault exec KEY -- CMD [ARGS...]")
    secret = open_vault(get_context(args).config).get(args.key)
    try:
        return subprocess.run(command, input=secret + "\n", text=True).returncode
    except FileNotFoundError:
        raise VaultError(f"command not found: {command[0]}") from None


def cmd_import(args) -> int:
    source = Path(args.file).expanduser()
    try:
        incoming = _validate(json.loads(source.read_text(encoding="utf-8")), str(source))
    except (OSError, json.JSONDecodeError) as exc:
        raise VaultError(f"cannot read {source}: {exc}") from None
    vault = open_vault(get_context(args).config)
    data = vault.load()
    skipped = sorted(k for k in incoming if k in data and data[k] != incoming[k]
                     and not args.overwrite)
    added = [k for k in incoming if k not in data]
    data.update({k: v for k, v in incoming.items() if k not in skipped})
    vault.save(data)
    print(f"imported {len(incoming) - len(skipped)} key(s) into {vault.describe()} "
          f"({len(added)} new)")
    if skipped:
        print(f"kept existing value for {len(skipped)} differing key(s): {', '.join(skipped)} "
              "(use --overwrite to replace)")
    return 0


def cmd_migrate(args) -> int:
    ctx = get_context(args)
    current = ctx.config.get("vault", "backend", "file")
    if args.to == current:
        raise VaultError(f"the vault already uses the {current} backend")
    source, target = open_vault(ctx.config), open_vault(ctx.config, backend=args.to)
    if target.keys() and not args.force:
        raise VaultError(f"{target.describe()} already holds secrets; use --force to overwrite")
    if isinstance(target, AgeVault) and ensure_age_identity(target.identity):
        print(f"created age identity {target.identity} (back it up; it is not synced)")
    data = source.load()
    target.save(data)
    if target.load() != data:
        raise VaultError(f"verification of {target.describe()} failed; config left unchanged")
    set_toml_value(ctx.root / CONFIG_NAME, "vault", "backend", args.to)
    print(f"migrated {len(data)} secret(s) to {target.describe()}; backend = \"{args.to}\"")
    if isinstance(target, AgeVault):
        print(f"this device's public key: {target.public_key()}\n"
              "add it to [vault] age_recipients on your other devices, then run "
              "`dotinfra vault rekey` there")
    if isinstance(source, FileVault) and source.path.exists():
        if args.remove_plaintext:
            source.path.unlink()
            print(f"removed plaintext vault {source.path}")
        else:
            print(f"plaintext vault left at {source.path}; delete it once you are satisfied "
                  "(or re-run with --remove-plaintext)")
    return 0


def cmd_rekey(args) -> int:
    vault = open_vault(get_context(args).config)
    if not isinstance(vault, AgeVault):
        raise VaultError("rekey only applies to the age backend")
    data = vault.load()
    vault.save(data)
    print(f"re-encrypted {len(data)} secret(s) to {len(vault.all_recipients())} recipient(s)")
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "vault", help="store and use secrets referenced by key",
        description="Secrets live in the vault; CMDB files only mention their keys.")
    sub = parser.add_subparsers(dest="vault_command", metavar="COMMAND", required=True)

    sub.add_parser("list", help="list secret keys (never values)").set_defaults(func=cmd_list)

    p = sub.add_parser("get", help="print a secret to stdout")
    p.add_argument("key")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("set", help="store a secret (prompted, or one line from stdin)",
                       description="Store a secret. On a terminal it is prompted twice without "
                                   "echo; otherwise the first line of stdin is used. Values are "
                                   "never accepted as arguments.")
    p.add_argument("key")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("rm", help="delete a secret")
    p.add_argument("key")
    p.set_defaults(func=cmd_rm)

    p = sub.add_parser("exec", help="run CMD with the secret on its stdin",
                       description="Run CMD with the secret plus a newline on its stdin, e.g. "
                                   "`dotinfra vault exec web1_sudo -- ssh web1 sudo -S reboot`. "
                                   "Exits with CMD's exit code.")
    p.add_argument("key")
    p.add_argument("command", nargs="...", metavar="-- CMD [ARGS...]")
    p.set_defaults(func=cmd_exec)

    p = sub.add_parser("import", help="import a flat JSON {key: secret} file",
                       description="Import secrets from a flat JSON object {key: secret}, "
                                   "e.g. a legacy flat JSON vault file.")
    p.add_argument("file")
    p.add_argument("--overwrite", action="store_true",
                   help="replace existing keys whose value differs")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("migrate", help="move all secrets to another backend",
                       description="Copy every secret to another backend, verify it, and switch "
                                   "[vault] backend in .dotinfra.toml. Migrating to age creates "
                                   "an identity if needed.")
    p.add_argument("--to", required=True, choices=BACKENDS)
    p.add_argument("--force", action="store_true", help="overwrite a non-empty target vault")
    p.add_argument("--remove-plaintext", action="store_true",
                   help="delete the plaintext file vault after a verified migration")
    p.set_defaults(func=cmd_migrate)

    sub.add_parser("rekey", help="re-encrypt the age vault to the current recipients",
                   description="Re-encrypt vault.age to this device's identity plus "
                               "[vault] age_recipients (after adding a device)."
                   ).set_defaults(func=cmd_rekey)
