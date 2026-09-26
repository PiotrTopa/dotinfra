"""Version guard (min_version), incoming-commit guard in sync, and .dotinfra.local.toml."""

import unittest
from unittest import mock

from support import IsolatedTestCase, git, run_cli
from test_sync import TwoDeviceTestCase
from dotinfra.config import load_config, set_toml_value
from dotinfra.scaffold import new_component
from dotinfra.versioning import is_newer, minor_floor, parse_version


class VersionParsingTest(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(parse_version("v0.10.2"), (0, 10, 2))
        self.assertEqual(parse_version("1.2"), (1, 2, 0))
        self.assertEqual(parse_version("0.3.0rc1"), (0, 3, 0))
        self.assertTrue(is_newer("0.10.0", "0.9.9"))
        self.assertFalse(is_newer("0.2.0", "0.2.0"))
        self.assertFalse(is_newer(None, "0.1.0"))
        self.assertEqual(minor_floor("0.2.7"), "0.2.0")


class CommandGuardTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb()
        set_toml_value(self.root / ".dotinfra.toml", "cmdb", "min_version", "9.0.0")

    def test_writing_commands_exit_3(self):
        for argv in (["lint"], ["index"], ["new", "server", "x1"], ["migrate", "--yes"],
                     ["sync"]):
            with self.subTest(argv=argv):
                code, out, err = run_cli("--root", self.root, *argv)
                self.assertEqual(code, 3, out + err)
                self.assertIn("this CMDB needs dotinfra ≥ 9.0.0", err)
                self.assertIn("run `dotinfra upgrade`", err)

    def test_read_only_commands_warn(self):
        new_component(self.root, "server", "web1")
        code, out, err = run_cli("--root", self.root, "ls")
        self.assertEqual(code, 0)
        self.assertIn("web1", out)
        self.assertIn("warning: this CMDB needs dotinfra ≥ 9.0.0", err)
        code, out, err = run_cli("--root", self.root, "show", "web1")
        self.assertEqual(code, 0)
        code, out, _ = run_cli("--root", self.root, "doctor")
        self.assertIn("FAIL  version", out)
        self.assertEqual(code, 1)

    def test_newer_install_passes(self):
        with mock.patch("dotinfra.__version__", "9.0.1"):
            code, _, err = run_cli("--root", self.root, "lint")
        self.assertNotEqual(code, 3, err)


class SyncGuardTest(TwoDeviceTestCase):
    """A migrates with a newer dotinfra; B's older dotinfra must not merge that."""

    def test_incoming_newer_min_version_is_not_merged(self):
        with mock.patch("dotinfra.__version__", "0.9.0"):
            code, out, err = run_cli("--root", self.a, "migrate", "--yes")
            self.assertEqual(code, 0, out + err)
            self.assertEqual(load_config(self.a).get("cmdb", "min_version"), "0.9.0")
            self.assertSync(self.a)
        hub_head = git(self.hub, "rev-parse", "main").strip()

        self.edit(self.b, "servers/web1.md", ("status: planned", "status: active"))
        before = git(self.b, "rev-parse", "HEAD").strip()
        out = self.assertSync(self.b, 3)
        self.assertIn("origin/main needs dotinfra ≥ 0.9.0", out)
        self.assertIn("nothing was merged", out)
        # the local edit was committed and kept, nothing from A was merged, nothing pushed
        self.assertNotEqual(git(self.b, "rev-parse", "HEAD").strip(), before)
        self.assertIn("sync(", git(self.b, "log", "-1", "--format=%s"))
        self.assertNotEqual(git(self.b, "merge-base", "HEAD", "origin/main").strip(), hub_head)
        self.assertEqual(git(self.hub, "rev-parse", "main").strip(), hub_head)
        self.assertNotIn("min_version = \"0.9.0\"", (self.b / ".dotinfra.toml").read_text())
        self.assertIn("refused", (self.b / ".dotinfra/state/sync.log").read_text())

        # after the upgrade B merges normally
        with mock.patch("dotinfra.__version__", "0.9.0"):
            self.assertSync(self.b)
        self.assertIn('min_version = "0.9.0"', (self.b / ".dotinfra.toml").read_text())
        self.assertIn("status: active", git(self.hub, "show", "main:servers/web1.md"))

    def test_same_version_merges(self):
        code, out, err = run_cli("--root", self.a, "migrate", "--yes")
        self.assertEqual(code, 0, out + err)
        self.assertSync(self.a)
        self.assertSync(self.b)


class LocalConfigTest(IsolatedTestCase):
    def test_local_overrides_are_deep_merged(self):
        root = self.make_cmdb()
        self.write(root, ".dotinfra.local.toml",
                   '[cmdb]\ndevice = "laptop"\n\n[monitoring]\nrole = "server"\n'
                   'grafana_url = "http://10.99.0.2:3000"\n\n[vault]\n'
                   'path = "~/secure/vault.json"\n')
        config = load_config(root)
        self.assertEqual(config.device, "laptop")
        self.assertEqual(config.get("monitoring", "role"), "server")
        self.assertEqual(config.get("monitoring", "grafana_url"), "http://10.99.0.2:3000")
        # untouched shared keys survive the merge
        self.assertEqual(config.get("monitoring", "grafana_user"), "admin")
        self.assertEqual(config.get("cmdb", "name"), "cmdb")
        self.assertEqual(config.path("vault", "path"), self.home / "secure" / "vault.json")
        self.assertEqual(load_config(root, local=False).get("monitoring", "role"), "client")

    def test_local_config_is_ignored_by_git(self):
        root = self.make_cmdb()
        self.write(root, ".dotinfra.local.toml", '[cmdb]\ndevice = "x"\n')
        self.assertEqual(git(root, "check-ignore", ".dotinfra.local.toml").strip(),
                         ".dotinfra.local.toml")
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_invalid_local_config_is_an_error(self):
        root = self.make_cmdb()
        self.write(root, ".dotinfra.local.toml", "[cmdb\n")
        code, _, err = run_cli("--root", root, "ls")
        self.assertEqual(code, 1)
        self.assertIn(".dotinfra.local.toml: invalid TOML", err)


if __name__ == "__main__":
    unittest.main()
