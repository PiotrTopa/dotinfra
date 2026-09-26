"""Two simulated devices (clones) exchanging edits through a local bare hub repository."""

import os
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from support import IsolatedTestCase, git, run_cli
from dotinfra import DotinfraError
from dotinfra.config import load_config
from dotinfra.frontmatter import parse
from dotinfra.scaffold import new_component
from dotinfra.sync import (commit_message, cron_line, parse_interval, sync_lock,
                           systemd_units)


def init_bare(path: Path) -> None:
    if subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(path)]).returncode:
        subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
        git(path, "symbolic-ref", "HEAD", "refs/heads/main")


class TwoDeviceTestCase(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.hub = self.tmp / "hub.git"
        init_bare(self.hub)
        self.a = self.make_cmdb("a")
        git(self.a, "remote", "add", "origin", str(self.hub))
        new_component(self.a, "server", "web1", address="10.0.0.5")
        self.assertSync(self.a)
        self.b = self.tmp / "b"
        git(self.tmp, "clone", "-q", str(self.hub), str(self.b))

    def sync(self, root: Path, *extra: str) -> tuple[int, str, str]:
        return run_cli("--root", root, "sync", *extra)

    def assertSync(self, root: Path, expected: int = 0, *extra: str) -> str:
        code, out, err = self.sync(root, *extra)
        self.assertEqual(code, expected, f"stdout:\n{out}\nstderr:\n{err}")
        return out + err

    @staticmethod
    def edit(root: Path, rel: str, *pairs: tuple[str, str]) -> None:
        path = root / rel
        text = path.read_text()
        for old, new in pairs:
            assert old in text, f"{old!r} not in {rel}"
            text = text.replace(old, new, 1)
        path.write_text(text)

    def web1(self, root: Path) -> str:
        return (root / "servers/web1.md").read_text()


class SyncMergeTest(TwoDeviceTestCase):
    def test_initial_sync_committed_and_pushed(self):
        log = git(self.a, "log", "--format=%s")
        self.assertIn("sync(", log)
        self.assertIn("index: regenerate", log)
        self.assertIn("web1", (self.b / "INDEX.md").read_text())
        self.assertEqual(git(self.hub, "rev-parse", "main"), git(self.a, "rev-parse", "HEAD"))

    def test_concurrent_edits_to_different_sections_auto_merge(self):
        # Each device edits a different section of the same file, bumps `updated`
        # and adds a History line: a plain line merge would conflict three times.
        self.edit(self.a, "servers/web1.md",
                  ("- Hardware:", "- Hardware: Intel NUC 12"),
                  ("updated: ", "updated: 2099-01-02 #"),
                  ("## History\n\n", "## History\n\n- 2099-01-02 — installed nginx (a)\n"))
        self.edit(self.b, "servers/web1.md",
                  ("## Known issues\n", "## Known issues\n\n- fan is noisy\n"),
                  ("updated: ", "updated: 2099-01-03 #"),
                  ("tags: [fleet]", "tags: [fleet, web]"),
                  ("## History\n\n", "## History\n\n- 2099-01-03 — replaced fan (b)\n"))
        self.assertSync(self.a)
        out = self.assertSync(self.b)
        self.assertIn("merged origin/main", out)
        self.assertIn("pushed to origin", out)
        self.assertSync(self.a)

        merged = self.web1(self.b)
        self.assertEqual(merged, self.web1(self.a))
        self.assertNotIn("<<<<<<<", merged)
        self.assertIn("- Hardware: Intel NUC 12", merged)
        self.assertIn("- fan is noisy", merged)
        meta, body = parse(merged)
        self.assertEqual(meta["updated"], "2099-01-03")
        self.assertEqual(meta["tags"], ["fleet", "web"])
        history = body.split("## History\n\n")[1]
        self.assertTrue(history.startswith("- 2099-01-03 — replaced fan (b)\n"
                                           "- 2099-01-02 — installed nginx (a)\n"))
        self.assertIn("merge origin/main", git(self.b, "log", "--merges", "--format=%s"))
        self.assertIn("merge-driver", git(self.b, "config", "merge.dotinfra.driver"))

    def test_history_union(self):
        self.edit(self.a, "servers/web1.md",
                  ("## History\n\n", "## History\n\n- 2099-05-01 — a did x\n"))
        self.edit(self.b, "servers/web1.md",
                  ("## History\n\n", "## History\n\n- 2099-04-01 — b did y\n"
                                     "- 2099-06-01 — b did z\n"))
        self.assertSync(self.a)
        self.assertSync(self.b)
        history = self.web1(self.b).split("## History\n\n")[1].splitlines()
        self.assertEqual(history[:3], ["- 2099-06-01 — b did z", "- 2099-05-01 — a did x",
                                       "- 2099-04-01 — b did y"])

    def test_both_devices_add_components_index_regenerated(self):
        new_component(self.a, "server", "alpha")
        new_component(self.b, "server", "beta")
        self.assertSync(self.a)
        self.assertSync(self.b)
        self.assertSync(self.a)
        index = (self.a / "INDEX.md").read_text()
        for cid in ("alpha", "beta", "web1"):
            self.assertIn(f"[{cid}]", index)
        self.assertEqual(index, (self.b / "INDEX.md").read_text())
        self.assertEqual(run_cli("--root", self.a, "index", "--check")[0], 0)


class ConflictTest(TwoDeviceTestCase):
    def make_conflict(self) -> str:
        self.edit(self.a, "servers/web1.md", ("- Storage:", "- Storage: 1 TB NVMe"))
        self.edit(self.b, "servers/web1.md", ("- Storage:", "- Storage: 2 TB SATA"),
                  ("## Overview\n", "## Overview\n\nMerged fine.\n"))
        self.assertSync(self.a)
        return self.assertSync(self.b, 2)

    def test_true_conflict_exits_2_and_writes_report(self):
        out = self.make_conflict()
        self.assertIn("CONFLICT", out)
        report = self.b / ".dotinfra/state/RECONCILE.md"
        text = report.read_text()
        self.assertIn("## servers/web1.md", text)
        self.assertIn("- Storage: 2 TB SATA", text)
        self.assertIn("- Storage: 1 TB NVMe", text)
        self.assertIn("dotinfra reconcile --continue", text)
        content = self.web1(self.b)
        self.assertIn("Merged fine.", content)  # the rest of the file merged cleanly
        self.assertEqual(content.count("<<<<<<<"), 1)

        self.assertIn("merge is in progress", self.assertSync(self.b, 2))
        code, out, _ = run_cli("--root", self.b, "reconcile")
        self.assertEqual(code, 2)
        self.assertIn("servers/web1.md  (conflict markers)", out)
        code, _, err = run_cli("--root", self.b, "reconcile", "--continue")
        self.assertEqual(code, 2)
        self.assertIn("conflict markers remain", err)

        fixed = content.replace(content[content.index("<<<<<<<"):
                                        content.index(">>>>>>> theirs\n") + 15],
                                "- Storage: 1 TB NVMe + 2 TB SATA\n")
        (self.b / "servers/web1.md").write_text(fixed)
        code, out, err = run_cli("--root", self.b, "reconcile", "--continue")
        self.assertEqual(code, 0, err)
        self.assertFalse(report.exists())
        self.assertIn("reconcile(", git(self.b, "log", "-2", "--format=%s"))
        self.assertSync(self.a)
        self.assertIn("- Storage: 1 TB NVMe + 2 TB SATA", self.web1(self.a))

    def test_frontmatter_conflict(self):
        self.edit(self.a, "servers/web1.md", ("status: planned", "status: active"))
        self.edit(self.b, "servers/web1.md", ("status: planned", "status: retired"))
        self.assertSync(self.a)
        self.assertSync(self.b, 2)
        self.assertIn("<<<<<<< ours\nstatus: retired", self.web1(self.b))

    def test_abort(self):
        self.make_conflict()
        code, _, _ = run_cli("--root", self.b, "reconcile", "--abort")
        self.assertEqual(code, 0)
        self.assertNotIn("<<<<<<<", self.web1(self.b))
        self.assertIn("2 TB SATA", self.web1(self.b))
        self.assertFalse((self.b / ".dotinfra/state/RECONCILE.md").exists())


class SyncBehaviourTest(TwoDeviceTestCase):
    def test_dry_run_changes_nothing(self):
        self.edit(self.a, "servers/web1.md", ("- Storage:", "- Storage: x"))
        head = git(self.a, "rev-parse", "HEAD")
        out = self.assertSync(self.a, 0, "--dry-run")
        self.assertIn("would commit 1 file(s)", out)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), head)

    def test_no_push_and_message(self):
        self.edit(self.a, "servers/web1.md", ("- Storage:", "- Storage: x"))
        self.assertSync(self.a, 0, "--no-push", "--message", "storage facts")
        self.assertEqual(git(self.a, "log", "-1", "--format=%s").strip(), "storage facts")
        self.assertNotEqual(git(self.hub, "rev-parse", "main"), git(self.a, "rev-parse", "HEAD"))

    def test_up_to_date(self):
        self.assertIn("up to date", self.assertSync(self.a))

    def test_lock(self):
        state = load_config(self.a).state_dir
        with sync_lock(state):
            code, _, err = self.sync(self.a)
            self.assertEqual(code, 1)
            self.assertIn("another sync is running", err)
        lock = state / "sync.lock"
        lock.write_text("stale")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        self.assertSync(self.a)
        self.assertFalse(lock.exists())

    def test_unrelated_histories_explained(self):
        other = self.make_cmdb("other")
        git(other, "remote", "add", "origin", str(self.hub))
        code, _, err = self.sync(other)
        self.assertEqual(code, 1)
        self.assertIn("git clone", err)

    def test_missing_and_unreachable_remotes(self):
        config = self.a / ".dotinfra.toml"
        config.write_text(config.read_text().replace("peers = []", 'peers = ["ghost", "gone"]'))
        git(self.a, "remote", "add", "gone", str(self.tmp / "nowhere"))
        code, _, err = self.sync(self.a)
        self.assertEqual(code, 1)
        self.assertIn("remote 'ghost' is configured but does not exist", err)
        self.assertIn("fetch from gone failed", err)

    def test_status(self):
        self.edit(self.a, "servers/web1.md", ("- Storage:", "- Storage: x"))
        code, out, _ = run_cli("--root", self.a, "status")
        self.assertEqual(code, 0)
        self.assertIn("uncommitted: 1 file(s)\n  servers/web1.md", out)
        self.assertIn("origin: 0 ahead, 0 behind", out)
        self.assertIn("last sync:", out)

    def test_peers(self):
        code, out, _ = run_cli("--root", self.b, "peer", "add", "laptop", str(self.a))
        self.assertEqual(code, 0)
        self.assertEqual(load_config(self.b).get("sync", "peers"), ["laptop"])
        self.assertIn("laptop", run_cli("--root", self.b, "peer", "ls")[1])
        # a commits locally without pushing; b picks it up straight from the peer
        self.edit(self.a, "servers/web1.md", ("- Storage:", "- Storage: from peer"))
        self.assertSync(self.a, 0, "--no-push")
        out = self.assertSync(self.b)
        self.assertIn("merged laptop/main", out)
        self.assertIn("from peer", self.web1(self.b))
        self.assertEqual(run_cli("--root", self.b, "peer", "rm", "laptop")[0], 0)
        self.assertEqual(load_config(self.b).get("sync", "peers"), [])
        self.assertNotIn("laptop", git(self.b, "remote"))


class HelpersTest(IsolatedTestCase):
    def test_commit_message(self):
        self.assertEqual(commit_message("laptop", ["servers/a.md"]), "sync(laptop): 1 file(s): servers/a.md")
        long = commit_message("laptop", [f"servers/host{i}.md" for i in range(20)])
        self.assertLessEqual(len(long), 72)
        self.assertTrue(long.endswith("…"))

    def test_interval(self):
        self.assertEqual(parse_interval("15m"), 900)
        self.assertEqual(parse_interval("2h"), 7200)
        self.assertEqual(parse_interval("5"), 300)
        for bad in ("0m", "30s", "soon"):
            with self.assertRaises(DotinfraError):
                parse_interval(bad)

    def test_timer_units_and_cron(self):
        root = Path("/srv/my infra")
        units = systemd_units(root, 900)
        self.assertIn('"/srv/my infra" sync', units["dotinfra-sync.service"])
        self.assertIn("OnUnitActiveSec=900s", units["dotinfra-sync.timer"])
        self.assertTrue(cron_line(root, 900).startswith("*/15 * * * * "))
        self.assertTrue(cron_line(root, 7200).startswith("0 */2 * * * "))

    def test_timer_without_systemd_prints_cron(self):
        root = self.make_cmdb(use_git=False)
        with mock.patch("dotinfra.sync.shutil.which", return_value=None):
            code, out, _ = run_cli("--root", root, "timer", "install", "--interval", "30m")
        self.assertEqual(code, 0)
        self.assertIn("*/30 * * * *", out)
        self.assertFalse((self.home / ".config/systemd").exists())


if __name__ == "__main__":
    unittest.main()
