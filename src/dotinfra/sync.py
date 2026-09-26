"""Git-based sync between devices: `sync`, `status`, `peer`, `reconcile`, `timer`.

The CMDB is an ordinary git repository. Devices exchange commits through a hub remote
and/or peers, always by *merging* (never rebasing, never rsync), so the section-aware
merge driver in :mod:`dotinfra.reconcile` sees both sides of every concurrent edit.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import DotinfraError
from .config import CONFIG_NAME, set_toml_value
from .context import Context, get_context
from .index import INDEX_NAME, is_stale, write_index
from .lint import format_issue, run_lint
from .reconcile import conflict_blocks, has_conflict_markers, merge_text

LOCK_STALE_SECONDS = 600
REPORT_NAME = "RECONCILE.md"
TIMER_UNIT = "dotinfra-sync"


class GitError(DotinfraError):
    pass


# --------------------------------------------------------------------------- git helpers


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise GitError("git is not installed or not on PATH") from None
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(f"`git {' '.join(args)}` failed: {detail}")
    return result


def git_out(root: Path, *args: str) -> str:
    return git(root, *args).stdout.strip()


def is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def has_ref(root: Path, ref: str) -> bool:
    return git(root, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def remote_names(root: Path) -> list[str]:
    return git_out(root, "remote").split()


def merge_in_progress(root: Path) -> bool:
    return has_ref(root, "MERGE_HEAD")


def unmerged_files(root: Path) -> list[str]:
    return sorted(set(git_out(root, "diff", "--name-only", "--diff-filter=U").splitlines()))


def dirty_files(root: Path) -> list[str]:
    """Changed, staged and untracked paths (git's ignore rules apply)."""
    output = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    entries = output.split("\0")
    paths, skip = [], False
    for entry in entries:
        if skip:
            skip = False
            continue
        if len(entry) > 3:
            paths.append(entry[3:])
            skip = entry[0] in "RC"  # renames/copies are followed by the source path
    return paths


def ahead_behind(root: Path, local: str, upstream: str) -> tuple[int, int]:
    counts = git_out(root, "rev-list", "--left-right", "--count", f"{local}...{upstream}")
    ahead, behind = counts.split()
    return int(ahead), int(behind)


def merge_driver_command() -> str:
    """The driver command, using this interpreter so it works without `dotinfra` on PATH."""
    return f"{shlex.quote(sys.executable)} -m dotinfra merge-driver %O %A %B %P"


def ensure_merge_driver(root: Path) -> None:
    """Register the ``dotinfra`` merge driver in the repository's local git config."""
    wanted = {"merge.dotinfra.name": "dotinfra section-aware Markdown merge",
              "merge.dotinfra.driver": merge_driver_command()}
    for key, value in wanted.items():
        current = git(root, "config", "--local", "--get", key, check=False).stdout.strip()
        if current != value:
            git(root, "config", "--local", key, value)


# --------------------------------------------------------------------------- helpers


@contextmanager
def sync_lock(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = state_dir / "sync.lock"
    if lock.exists() and time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
        lock.unlink(missing_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise DotinfraError(f"another sync is running (lock {lock}; it expires after "
                            f"{LOCK_STALE_SECONDS // 60} minutes)") from None
    with os.fdopen(fd, "w") as handle:
        handle.write(f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}\n")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _warn(message: str) -> None:
    sys.stdout.flush()  # keep stdout/stderr in order when both go to one log
    print(message, file=sys.stderr)


def _log(ctx: Context, message: str) -> None:
    ctx.config.state_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    with open(ctx.config.state_dir / "sync.log", "a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def commit_message(device: str, paths: list[str], limit: int = 72) -> str:
    """``sync(<device>): <n> file(s): a, b, …`` with the path list truncated to ``limit``."""
    prefix = f"sync({device}): {len(paths)} file(s): "
    listing = ", ".join(paths)
    room = max(limit - len(prefix), 10)
    if len(listing) > room:
        listing = listing[: room - 1].rstrip(", ") + "…"
    return prefix + listing


def _sources(ctx: Context) -> list[str]:
    hub = ctx.config.get("sync", "remote", "")
    peers = [str(p) for p in ctx.config.get("sync", "peers", [])]
    return ([hub] if hub else []) + [p for p in peers if p != hub]


def _require_repo(ctx: Context) -> None:
    if not is_repo(ctx.root):
        raise GitError(f"{ctx.root} is not a git repository; run `git init` there "
                       "(or recreate it with `dotinfra init`)")


# --------------------------------------------------------------------------- conflicts


def resolve_conflicts(ctx: Context, files: list[str]) -> list[str]:
    """Try the reconciler on conflicted files; return the ones still conflicted."""
    remaining = []
    for rel in files:
        if rel == INDEX_NAME:
            write_index(ctx.root, ctx.config.get("cmdb", "name", "home"))
            git(ctx.root, "add", "--", rel)
        elif rel.endswith(".md") and _reconcile_file(ctx.root, rel):
            git(ctx.root, "add", "--", rel)
        else:
            remaining.append(rel)
    return remaining


def _reconcile_file(root: Path, rel: str) -> bool:
    stages = [git(root, "show", f":{n}:{rel}", check=False) for n in (1, 2, 3)]
    if any(stage.returncode != 0 for stage in stages):
        return False  # added/deleted on one side: needs a human decision
    result = merge_text(*(stage.stdout for stage in stages))
    (root / rel).write_text(result.text, encoding="utf-8")
    return result.clean


def write_report(ctx: Context, files: list[str], source: str) -> Path:
    lines = [
        "# Sync conflicts",
        "",
        f"`dotinfra sync` merged `{source}` on {datetime.now():%Y-%m-%d %H:%M} and could not "
        f"reconcile {len(files)} file(s) automatically. Both versions are kept between "
        "`<<<<<<< ours` / `=======` / `>>>>>>> theirs` markers, only in the parts that "
        "really conflict.",
        "",
        "## Next steps",
        "",
        "1. Edit each file below so that the facts from *both* sides survive; delete the markers.",
        "2. Run `dotinfra reconcile --continue` (checks markers, lints, commits, syncs).",
        "3. Or run `dotinfra reconcile --abort` to undo this merge.",
    ]
    for rel in files:
        path = ctx.root / rel
        lines += ["", f"## {rel}", ""]
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        blocks = conflict_blocks(text)
        if not blocks:
            lines.append("No conflict markers: the file was changed on one side and deleted "
                         "(or added differently) on the other. Keep it with `git add "
                         f"{rel}` or drop it with `git rm {rel}`.")
        for start, block in blocks:
            lines += [f"Line {start}:", "", "```text", block, "```", ""]
    report = ctx.config.state_dir / REPORT_NAME
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return report


def _merge(ctx: Context, ref: str) -> list[str]:
    """Merge ``ref`` into the current branch; return files left in conflict."""
    message = f"sync({ctx.config.device}): merge {ref}"
    result = git(ctx.root, "merge", "--no-edit", "-m", message, ref, check=False)
    if result.returncode == 0:
        return []
    conflicted = unmerged_files(ctx.root)
    if not conflicted:
        detail = (result.stderr or result.stdout).strip()
        if "unrelated histories" in detail:
            raise GitError(f"this CMDB and {ref} have unrelated histories. A second device must "
                           f"start from a clone: `git clone URL {ctx.root}`, then `dotinfra sync`.")
        raise GitError(f"merging {ref} failed: {detail}")
    remaining = resolve_conflicts(ctx, conflicted)
    if not remaining:
        git(ctx.root, "commit", "--no-edit", "-m", message)
    return remaining


# --------------------------------------------------------------------------- sync


def sync(ctx: Context, *, push: bool = True, dry_run: bool = False,
         message: str | None = None) -> int:
    """Commit, fetch, merge, reindex and push. Returns 0 ok, 1 remote failure, 2 conflict."""
    _require_repo(ctx)
    root, branch = ctx.root, ctx.config.get("sync", "branch", "main")
    if merge_in_progress(root):
        print("a merge is in progress (unresolved conflicts from an earlier sync).\n"
              "Resolve them and run `dotinfra reconcile --continue`, or `dotinfra reconcile "
              "--abort`.", file=sys.stderr)
        return 2
    current = git(root, "symbolic-ref", "--short", "HEAD", check=False).stdout.strip()
    if current != branch:
        raise GitError(f"on branch {current or '(detached HEAD)'}, "
                       f"but [sync] branch is {branch!r}; "
                       f"`git -C {root} switch {branch}` first")
    ensure_merge_driver(root)
    with sync_lock(ctx.config.state_dir):
        return _sync_locked(ctx, branch, push=push, dry_run=dry_run, message=message)


def _sync_locked(ctx: Context, branch: str, *, push: bool, dry_run: bool,
                 message: str | None) -> int:
    root, failures, summary = ctx.root, 0, []
    dirty = dirty_files(root)
    if dirty:
        subject = message or commit_message(ctx.config.device, dirty)
        if dry_run:
            print(f"would commit {len(dirty)} file(s): {subject}")
        elif not ctx.config.get("sync", "auto_commit", True):
            raise DotinfraError("uncommitted changes and [sync] auto_commit = false; "
                                "commit them first")
        else:
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", subject)
            print(f"committed: {subject}")
            summary.append(f"committed {len(dirty)}")

    available = remote_names(root)
    fetched = []
    for remote in _sources(ctx):
        if remote not in available:
            _warn(f"warning: remote {remote!r} is configured but does not exist "
                  f"(`git -C {root} remote add {remote} URL` or `dotinfra peer add`)")
            continue
        result = git(root, "fetch", "--quiet", remote, check=False)
        if result.returncode != 0:
            failures += 1
            _warn(f"warning: fetch from {remote} failed: {result.stderr.strip()}")
        else:
            fetched.append(remote)

    for remote in fetched:
        ref = f"{remote}/{branch}"
        if not has_ref(root, ref) or not has_ref(root, "HEAD"):
            continue
        ahead, behind = ahead_behind(root, "HEAD", ref)
        if dry_run:
            print(f"{ref}: {ahead} ahead, {behind} behind" + (" (would merge)" if behind else ""))
            continue
        if not behind:
            continue
        remaining = _merge(ctx, ref)
        if remaining:
            report = write_report(ctx, remaining, ref)
            _warn(f"CONFLICT merging {ref} in {len(remaining)} file(s): {', '.join(remaining)}\n"
                  f"details and next steps: {report}\n"
                  "edit the files, then run `dotinfra reconcile --continue`")
            _log(ctx, f"conflict: {ref}: {', '.join(remaining)}")
            return 2
        print(f"merged {ref} ({behind} commit(s))")
        summary.append(f"merged {ref}")

    if dry_run:
        return 1 if failures else 0

    name = ctx.config.get("cmdb", "name", "home")
    if has_ref(root, "HEAD") and is_stale(root, name):
        write_index(root, name)
        git(root, "add", "--", INDEX_NAME)
        git(root, "commit", "-q", "-m", "index: regenerate")
        summary.append("index regenerated")

    hub = ctx.config.get("sync", "remote", "")
    if push and hub in fetched and has_ref(root, "HEAD"):
        ref = f"{hub}/{branch}"
        if not has_ref(root, ref) or ahead_behind(root, "HEAD", ref)[0]:
            result = git(root, "push", "--quiet", "-u", hub, f"{branch}:{branch}", check=False)
            if result.returncode != 0:
                failures += 1
                _warn(f"error: push to {hub} failed: {result.stderr.strip()}")
            else:
                print(f"pushed to {hub}")
                summary.append(f"pushed {hub}")

    status = "ok" if not failures else f"{failures} remote failure(s)"
    _log(ctx, f"{status}: {', '.join(summary) or 'nothing to do'}")
    print("up to date" if not summary and not failures else f"sync {status}")
    return 1 if failures else 0


def cmd_sync(args) -> int:
    return sync(get_context(args), push=not args.no_push, dry_run=args.dry_run,
                message=args.message)


# --------------------------------------------------------------------------- status


def cmd_status(args) -> int:
    ctx = get_context(args)
    _require_repo(ctx)
    root, branch = ctx.root, ctx.config.get("sync", "branch", "main")
    print(f"CMDB {root} (branch {git_out(root, 'branch', '--show-current') or '?'})")
    dirty = dirty_files(root)
    print(f"uncommitted: {len(dirty)} file(s)")
    for path in dirty[:20]:
        print(f"  {path}")
    if len(dirty) > 20:
        print(f"  … and {len(dirty) - 20} more")
    if merge_in_progress(root):
        files = unmerged_files(root)
        print(f"MERGE IN PROGRESS: {len(files)} conflicted file(s): {', '.join(files) or '-'} "
              "— see `dotinfra reconcile`")
    available = remote_names(root)
    for remote in _sources(ctx):
        ref = f"{remote}/{branch}"
        if remote not in available:
            state = "not configured as a git remote"
        elif not has_ref(root, ref) or not has_ref(root, "HEAD"):
            state = "never fetched"
        else:
            ahead, behind = ahead_behind(root, "HEAD", ref)
            state = f"{ahead} ahead, {behind} behind (as of last fetch)"
        print(f"{remote}: {state}")
    log = ctx.config.state_dir / "sync.log"
    if log.is_file():
        last = log.read_text(encoding="utf-8").strip().splitlines()[-1:]
        print(f"last sync: {last[0] if last else 'never'}")
    driver = git(root, "config", "--local", "--get", "merge.dotinfra.driver", check=False)
    if driver.returncode != 0:
        print("merge driver: not configured (the next `dotinfra sync` sets it up)")
    return 2 if merge_in_progress(root) else 0


# --------------------------------------------------------------------------- peers


def cmd_peer_add(args) -> int:
    ctx = get_context(args)
    _require_repo(ctx)
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", args.name):
        raise DotinfraError(f"invalid peer name {args.name!r}")
    if args.name in remote_names(ctx.root):
        git(ctx.root, "remote", "set-url", args.name, args.url)
    else:
        git(ctx.root, "remote", "add", args.name, args.url)
    peers = [str(p) for p in ctx.config.get("sync", "peers", [])]
    if args.name not in peers:
        set_toml_value(ctx.root / CONFIG_NAME, "sync", "peers", peers + [args.name])
    print(f"peer {args.name} -> {args.url}; `dotinfra sync` will fetch and merge from it")
    return 0


def cmd_peer_ls(args) -> int:
    ctx = get_context(args)
    _require_repo(ctx)
    hub = ctx.config.get("sync", "remote", "")
    for remote in _sources(ctx):
        url = git(ctx.root, "remote", "get-url", remote, check=False).stdout.strip()
        role = "hub " if remote == hub else "peer"
        print(f"{role} {remote}\t{url or '(missing git remote)'}")
    return 0


def cmd_peer_rm(args) -> int:
    ctx = get_context(args)
    _require_repo(ctx)
    peers = [str(p) for p in ctx.config.get("sync", "peers", [])]
    if args.name not in peers and args.name not in remote_names(ctx.root):
        raise DotinfraError(f"no peer named {args.name!r}")
    if args.name in peers:
        set_toml_value(ctx.root / CONFIG_NAME, "sync", "peers",
                       [p for p in peers if p != args.name])
    if args.name in remote_names(ctx.root):
        git(ctx.root, "remote", "remove", args.name)
    print(f"removed peer {args.name}")
    return 0


# --------------------------------------------------------------------------- reconcile


def cmd_reconcile(args) -> int:
    ctx = get_context(args)
    _require_repo(ctx)
    report = ctx.config.state_dir / REPORT_NAME
    if args.abort:
        if merge_in_progress(ctx.root):
            git(ctx.root, "merge", "--abort")
        report.unlink(missing_ok=True)
        print("merge aborted; your local commits are untouched")
        return 0
    if not merge_in_progress(ctx.root):
        report.unlink(missing_ok=True)
        print("nothing to reconcile")
        return 0
    files = unmerged_files(ctx.root)
    marked = [f for f in files if (ctx.root / f).is_file()
              and has_conflict_markers((ctx.root / f).read_text(encoding="utf-8",
                                                                errors="replace"))]
    if not args.continue_:
        print(f"{len(files)} file(s) still conflicted:")
        for rel in files:
            print(f"  {rel}{'  (conflict markers)' if rel in marked else ''}")
        print(f"details: {report}\nfix them, then `dotinfra reconcile --continue`")
        return 2 if files else 0
    if marked:
        print("conflict markers remain in: " + ", ".join(marked), file=sys.stderr)
        return 2
    return _finish_merge(ctx, files, report)


def _finish_merge(ctx: Context, files: list[str], report: Path) -> int:
    for rel in files:
        if (ctx.root / rel).exists():
            git(ctx.root, "add", "--", rel)
        else:
            git(ctx.root, "rm", "--quiet", "--", rel)
    errors = [i for i in run_lint(ctx.root, ctx.config) if i.level == "error" and i.path in files]
    if errors:
        for issue in errors:
            print(format_issue(issue), file=sys.stderr)
        print(f"{len(errors)} lint error(s); fix them and re-run `dotinfra reconcile --continue`",
              file=sys.stderr)
        return 1
    name = ctx.config.get("cmdb", "name", "home")
    if write_index(ctx.root, name):
        git(ctx.root, "add", "--", INDEX_NAME)
    git(ctx.root, "commit", "-q", "-m",
        f"reconcile({ctx.config.device}): {len(files)} file(s): {', '.join(files)}"[:200])
    report.unlink(missing_ok=True)
    print("merge committed; continuing sync")
    return sync(ctx)


# --------------------------------------------------------------------------- timer

_INTERVAL_RE = re.compile(r"^(\d+)(s|m|min|h)?$")


def parse_interval(text: str) -> int:
    """``"15m"`` → 900 seconds; bare numbers are minutes."""
    match = _INTERVAL_RE.match(text.strip())
    if not match or int(match.group(1)) == 0:
        raise DotinfraError(f"invalid interval {text!r}; use e.g. 5m, 15m, 1h")
    value, unit = int(match.group(1)), match.group(2) or "m"
    seconds = value * {"s": 1, "m": 60, "min": 60, "h": 3600}[unit]
    if seconds < 60:
        raise DotinfraError("the sync interval must be at least one minute")
    return seconds


def sync_command(root: Path) -> list[str]:
    return [sys.executable, "-m", "dotinfra", "--root", str(root), "sync"]


def systemd_units(root: Path, seconds: int) -> dict[str, str]:
    exec_start = " ".join(f'"{arg}"' if " " in arg else arg for arg in sync_command(root))
    service = (f"[Unit]\nDescription=dotinfra sync of {root}\n\n"
               f"[Service]\nType=oneshot\nExecStart={exec_start}\n")
    timer = (f"[Unit]\nDescription=Run dotinfra sync every {seconds // 60} min\n\n"
             f"[Timer]\nOnBootSec=2min\nOnUnitActiveSec={seconds}s\nUnit={TIMER_UNIT}.service\n\n"
             "[Install]\nWantedBy=timers.target\n")
    return {f"{TIMER_UNIT}.service": service, f"{TIMER_UNIT}.timer": timer}


def cron_line(root: Path, seconds: int) -> str:
    minutes = max(seconds // 60, 1)
    schedule = f"*/{minutes} * * * *" if minutes < 60 else f"0 */{max(minutes // 60, 1)} * * *"
    log = root / ".dotinfra/state/cron.log"
    command = " ".join(shlex.quote(arg) for arg in sync_command(root))
    return f"{schedule} {command} >> {shlex.quote(str(log))} 2>&1"


def _unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def _systemctl(*args: str) -> bool:
    if not shutil.which("systemctl"):
        return False
    return subprocess.run(["systemctl", "--user", *args], capture_output=True).returncode == 0


def cmd_timer(args) -> int:
    ctx = get_context(args)
    seconds = parse_interval(args.interval)
    unit_dir = _unit_dir()
    if args.action == "remove":
        _systemctl("disable", "--now", f"{TIMER_UNIT}.timer")
        for name in systemd_units(ctx.root, seconds):
            (unit_dir / name).unlink(missing_ok=True)
        _systemctl("daemon-reload")
        print(f"removed {TIMER_UNIT} units (if you used cron, delete the line with `crontab -e`)")
        return 0
    if not shutil.which("systemctl"):
        print("systemd is not available here; add this line with `crontab -e`:\n")
        print(cron_line(ctx.root, seconds))
        return 0
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, text in systemd_units(ctx.root, seconds).items():
        (unit_dir / name).write_text(text, encoding="utf-8")
    if _systemctl("daemon-reload") and _systemctl("enable", "--now", f"{TIMER_UNIT}.timer"):
        print(f"installed and started {TIMER_UNIT}.timer (every {seconds // 60} min); "
              f"logs: journalctl --user -u {TIMER_UNIT}")
        print("note: unattended sync needs SSH keys usable without a prompt (agent or no "
              "passphrase) for your remotes")
        return 0
    print(f"wrote units to {unit_dir}, but `systemctl --user enable --now {TIMER_UNIT}.timer` "
          "failed; run it yourself, or use cron instead:\n")
    print(cron_line(ctx.root, seconds))
    return 1


# --------------------------------------------------------------------------- CLI


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "sync", help="commit, fetch, merge and push the CMDB",
        description="Commit local edits, fetch the hub and peers, merge them (section-aware), "
                    "regenerate INDEX.md and push to the hub. Exit codes: 0 ok, 1 a remote "
                    "failed, 2 conflicts need `dotinfra reconcile`.")
    p.add_argument("--no-push", action="store_true", help="do not push to the hub remote")
    p.add_argument("--dry-run", action="store_true",
                   help="only fetch and report what would be committed/merged")
    p.add_argument("--message", "-m", metavar="M", help="commit message for local edits")
    p.set_defaults(func=cmd_sync)

    subparsers.add_parser(
        "status", help="show uncommitted files, conflicts and ahead/behind per remote",
        description="Show sync state: uncommitted files, unresolved merges and how far this "
                    "device is ahead/behind each remote as of the last fetch."
    ).set_defaults(func=cmd_status)

    p = subparsers.add_parser("peer", help="manage peer devices to sync with",
                              description="Peers are other devices' CMDBs reached over SSH, "
                                          "e.g. ssh://laptop/~/.infra. Sync fetches from them; "
                                          "they fetch from you.")
    sub = p.add_subparsers(dest="peer_command", metavar="COMMAND", required=True)
    add = sub.add_parser("add", help="add a peer (git remote + [sync] peers)")
    add.add_argument("name")
    add.add_argument("url", metavar="SSH_URL")
    add.set_defaults(func=cmd_peer_add)
    sub.add_parser("ls", help="list hub and peers").set_defaults(func=cmd_peer_ls)
    rm = sub.add_parser("rm", help="remove a peer")
    rm.add_argument("name")
    rm.set_defaults(func=cmd_peer_rm)

    p = subparsers.add_parser(
        "reconcile", help="finish or abort a sync that stopped on conflicts",
        description="Without options, list remaining conflicts. --continue verifies no "
                    "conflict markers remain, runs lint, commits the merge and resumes sync.")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--continue", dest="continue_", action="store_true",
                       help="commit the resolved merge and sync")
    group.add_argument("--abort", action="store_true", help="undo the merge (git merge --abort)")
    p.set_defaults(func=cmd_reconcile)

    p = subparsers.add_parser(
        "timer", help="run sync periodically (systemd user timer, or cron)",
        description="Install or remove a systemd --user timer running `dotinfra sync`. "
                    "Where systemd is unavailable (macOS, BSD) a crontab line is printed.")
    p.add_argument("action", choices=("install", "remove"))
    p.add_argument("--interval", default="15m", help="e.g. 5m, 15m, 1h (default: 15m)")
    p.set_defaults(func=cmd_timer)
