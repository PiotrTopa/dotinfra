"""`dotinfra lint`: schema, references and leaked-secret checks."""

from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from . import DotinfraError
from .config import Config
from .context import get_context
from .model import (ID_RE, KNOWN_KEYS, SSH_KEYS, STATUSES, Component, as_list, parse_metric,
                    scan_cmdb)

STALE_AFTER = timedelta(days=180)
ALLOW_MARKER = "dotinfra:allow-secret"
MAX_SCAN_BYTES = 1_000_000
SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("password", re.compile(r"password\s*[:=]\s*\S+", re.IGNORECASE)),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("API secret key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("Slack token", re.compile(r"xox[baprs]-")),
]
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_H1_RE = re.compile(r"^# \S", re.MULTILINE)


@dataclass
class Issue:
    level: str  # "error" | "warning"
    path: str
    line: int
    message: str
    rule: str


def format_issue(issue: Issue) -> str:
    return f"{issue.path}:{issue.line}: {issue.level}: {issue.message} [{issue.rule}]"


# --------------------------------------------------------------------------- component rules


def _check_component(c: Component, ids: set[str], today: date, strict: bool) -> list[Issue]:
    issues: list[Issue] = []

    def add(level: str, key: str, message: str, rule: str) -> None:
        issues.append(Issue(level, c.rel(), c.line_of(key), message, rule))

    if c.status is None:
        add("error", "status", f"missing status (one of: {', '.join(STATUSES)})", "status")
    elif c.status not in STATUSES:
        add("error", "status", f"invalid status {c.status!r} (one of: {', '.join(STATUSES)})",
            "status")
    if not ID_RE.match(c.id):
        add("error", "id", f"invalid id {c.id!r} (lowercase letters, digits, '.', '_', '-')",
            "id")
    if c.meta.get("kind") != c.kind:
        add("error", "kind", f"kind {c.meta.get('kind')!r} does not match folder "
                             f"({c.kind!r})", "kind")
    _check_references(c, ids, add)
    for entry in as_list(c.meta.get("metrics")):
        if parse_metric(entry) is None:
            add("error", "metrics", f"malformed metrics entry {entry!r} (expected job:port)",
                "metrics")
    if not c.meta.get("role"):
        add("warning", "role", "missing role (one line describing its purpose)", "role")
    _check_updated(c, today, add)
    if not _H1_RE.search(c.body):
        add("warning", "", "no '# Title' heading in the body", "h1")
    if strict:
        for key in c.meta:
            if key not in KNOWN_KEYS:
                add("warning", key, f"unknown key {key!r}", "unknown-key")
        for key in c.ssh:
            if key not in SSH_KEYS:
                add("warning", "ssh", f"unknown ssh key {key!r}", "unknown-key")
    return issues


def _check_references(c: Component, ids: set[str], add) -> None:
    ssh = c.meta.get("ssh")
    if ssh is not None and not isinstance(ssh, dict):
        add("error", "ssh", "ssh must be a map (user, host, port, jump, key)", "ssh")
    jump = c.ssh.get("jump")
    if jump and jump not in ids:
        add("error", "ssh", f"ssh.jump references unknown id {jump!r}", "reference")
    for dep in as_list(c.meta.get("depends_on")):
        if str(dep) not in ids:
            add("error", "depends_on", f"depends_on references unknown id {dep!r}", "reference")
    runs_on = c.meta.get("runs_on")
    if runs_on and str(runs_on) not in ids:
        add("error", "runs_on", f"runs_on references unknown id {runs_on!r}", "reference")


def _check_updated(c: Component, today: date, add) -> None:
    updated = c.meta.get("updated")
    if not updated:
        add("warning", "updated", "missing updated (YYYY-MM-DD of the last check)", "updated")
    elif not _DATE_RE.match(str(updated)):
        add("warning", "updated", f"updated {updated!r} is not YYYY-MM-DD", "updated")
    else:
        try:
            age = today - date.fromisoformat(str(updated))
        except ValueError:
            add("warning", "updated", f"updated {updated!r} is not a valid date", "updated")
        else:
            if age > STALE_AFTER:
                add("warning", "updated", f"stale: last updated {age.days} days ago", "stale")


def _duplicate_ids(components: list[Component]) -> list[Issue]:
    groups: dict[str, list[Component]] = defaultdict(list)
    for c in components:
        groups[c.id].append(c)
    issues = []
    for component_id, group in groups.items():
        for c in group[1:]:
            issues.append(Issue("error", c.rel(), c.line_of("id"),
                                f"duplicate id {component_id!r} (also {group[0].rel()})", "id"))
    return issues


def _vault_keys(config: Config) -> set[str] | None:
    from .vault import open_vault

    try:
        return set(open_vault(config).keys())
    except DotinfraError:
        return None


def _missing_secrets(components: list[Component], keys: set[str]) -> list[Issue]:
    return [Issue("warning", c.rel(), c.line_of("secrets"),
                  f"secret {key!r} is not in the vault (`dotinfra vault set {key}`)", "vault")
            for c in components for key in map(str, as_list(c.meta.get("secrets")))
            if key not in keys]


# --------------------------------------------------------------------------- secret scan


def scanned_files(root: Path) -> list[Path]:
    """Files that are (or would be) committed: git's view when available."""
    if (root / ".git").exists():
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached",
                                 "--others", "--exclude-standard"], capture_output=True)
        if result.returncode == 0:
            names = sorted(set(filter(None, result.stdout.decode().split("\0"))))
            return [root / name for name in names]
    return sorted(p for p in root.rglob("*") if p.is_file()
                  and not {".git", ".dotinfra"} & set(p.relative_to(root).parts))


def _looks_referenced(line: str, match: re.Match) -> bool:
    """A password line is fine when it points at the vault or is a placeholder."""
    rest = line[match.start():].lower()
    value = re.split(r"[:=]", match.group(0), maxsplit=1)[1].strip().strip("`'\"")
    return "vault" in rest or value.startswith(("<", "***", "{{"))


def scan_secrets(root: Path) -> list[Issue]:
    issues = []
    for path in scanned_files(root):
        if not path.is_file() or path.stat().st_size > MAX_SCAN_BYTES:
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue  # binary, e.g. vault.age
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if ALLOW_MARKER in line:
                continue
            for label, pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if match and not (label == "password" and _looks_referenced(line, match)):
                    issues.append(Issue("error", rel, number,
                                        f"possible {label} in plain text; move it to the vault "
                                        f"(or mark the line `{ALLOW_MARKER}`)", "secret"))
    return issues


# --------------------------------------------------------------------------- entry points


def run_lint(root: Path, config: Config, strict: bool = False,
             today: date | None = None) -> list[Issue]:
    today = today or date.today()
    components, errors = scan_cmdb(root)
    issues = [Issue("error", e.source or "?", e.line or 1, e.message, "parse") for e in errors]
    ids = {c.id for c in components}
    for c in components:
        issues += _check_component(c, ids, today, strict)
    issues += _duplicate_ids(components)
    keys = _vault_keys(config)
    if keys is not None:
        issues += _missing_secrets(components, keys)
    issues += scan_secrets(root)
    issues.sort(key=lambda i: (i.path, i.line, i.level != "error", i.rule))
    return issues


def summary(issues: list[Issue], count: int) -> str:
    errors = sum(i.level == "error" for i in issues)
    return f"{errors} error(s), {len(issues) - errors} warning(s) in {count} component(s)"


def cmd_lint(args) -> int:
    ctx = get_context(args)
    issues = run_lint(ctx.root, ctx.config, strict=args.strict)
    if args.json:
        print(json.dumps([asdict(i) for i in issues], indent=2))
    else:
        for issue in issues:
            print(format_issue(issue))
        print(summary(issues, len(ctx.components())))
    return 1 if any(i.level == "error" for i in issues) else 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "lint", help="check schema, references and leaked secrets",
        description="Check every component: frontmatter syntax, required fields, ids, "
                    "references (ssh.jump, depends_on, runs_on), metrics, staleness, vault keys, "
                    "and secret-looking text in any tracked file. Exits 1 on errors.")
    parser.add_argument("--strict", action="store_true", help="also warn about unknown keys")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.set_defaults(func=cmd_lint)
