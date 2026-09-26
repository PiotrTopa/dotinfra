import unittest
from datetime import date

from support import IsolatedTestCase, git, run_cli
from dotinfra import DotinfraError
from dotinfra.frontmatter import parse
from dotinfra.model import load_cmdb
from dotinfra.scaffold import EXAMPLES, new_component, render_component
from dotinfra.sync import merge_driver_command

KINDS = ("server", "network", "domain", "router", "service", "device")


class InitTest(IsolatedTestCase):
    def test_layout(self):
        root = self.tmp / "infra"
        code, out, err = run_cli("init", root, "--name", "lab")
        self.assertEqual(code, 0, err)
        for name in ("README.md", "AGENTS.md", "CLAUDE.md", "INDEX.md", ".gitignore",
                     ".gitattributes", ".dotinfra.toml"):
            self.assertTrue((root / name).is_file(), name)
        for folder in ("servers", "networks", "domains", "routers", "services", "devices"):
            self.assertTrue((root / folder).is_dir(), folder)
        self.assertTrue((root / ".dotinfra/state").is_dir())
        self.assertEqual((root / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        self.assertIn("*.md merge=dotinfra", (root / ".gitattributes").read_text())
        self.assertIn(".dotinfra/state/", (root / ".gitignore").read_text())
        self.assertIn('name = "lab"', (root / ".dotinfra.toml").read_text())
        self.assertIn("# lab — infrastructure index", (root / "INDEX.md").read_text())
        self.assertNotIn("{{", (root / "AGENTS.md").read_text())

    def test_git_repo_and_merge_driver(self):
        root = self.make_cmdb()
        self.assertEqual(git(root, "branch", "--show-current").strip(), "main")
        self.assertEqual(git(root, "config", "merge.dotinfra.driver").strip(),
                         merge_driver_command())
        self.assertIn("init: dotinfra CMDB", git(root, "log", "--oneline"))
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_idempotent_keeps_user_files(self):
        root = self.make_cmdb()
        (root / "AGENTS.md").write_text("custom rules\n")
        code, out, _ = run_cli("init", root)
        self.assertEqual(code, 0)
        self.assertIn("kept    AGENTS.md", out)
        self.assertEqual((root / "AGENTS.md").read_text(), "custom rules\n")

    def test_no_git(self):
        root = self.make_cmdb(use_git=False)
        self.assertFalse((root / ".git").exists())

    @unittest.skipUnless((EXAMPLES / "homelab").is_dir(), "bundled example not present")
    def test_example(self):
        root = self.make_cmdb(use_git=False, example="homelab")
        self.assertGreater(len(load_cmdb(root)), 0)
        with self.assertRaises(DotinfraError):
            self.make_cmdb("other", use_git=False, example="nope")


class NewTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb(use_git=False)

    def test_every_template_renders_valid_frontmatter(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                text = render_component(kind, "x1", title="X: one", address="10.0.0.9",
                                        today=date(2026, 1, 2))
                meta, body = parse(text)
                self.assertEqual((meta["id"], meta["kind"], meta["status"]),
                                 ("x1", kind, "planned"))
                self.assertEqual(meta["title"], "X: one")
                self.assertEqual(meta["address"], "10.0.0.9")
                self.assertEqual(meta["updated"], "2026-01-02")
                self.assertIn("# X: one\n", body)
                for section in ("Overview", "Configuration", "Access", "Secrets",
                                "Known issues", "History"):
                    self.assertIn(f"\n## {section}\n", body)
                self.assertIn("- 2026-01-02 — created", body)

    def test_cli_new(self):
        code, out, _ = run_cli("--root", self.root, "new", "servers", "web1",
                               "--address", "10.0.0.5")
        self.assertEqual(code, 0)
        self.assertIn("servers/web1.md", out)
        meta, _ = parse((self.root / "servers/web1.md").read_text())
        self.assertEqual(meta["address"], "10.0.0.5")
        self.assertEqual(meta["ssh"], {"user": None, "port": 22})

    def test_without_address(self):
        new_component(self.root, "device", "ups")
        meta, _ = parse((self.root / "devices/ups.md").read_text())
        self.assertIsNone(meta["address"])

    def test_refusals(self):
        new_component(self.root, "server", "web1")
        with self.assertRaisesRegex(DotinfraError, "already exists"):
            new_component(self.root, "server", "web1")
        cases = [("server", "web1", "already used"), ("device", "web1", "already used"),
                 ("server", "Web 1", "invalid id"), ("gizmo", "g1", "unknown kind")]
        for kind, cid, message in cases:
            with self.subTest(kind=kind, id=cid):
                code, _, err = run_cli("--root", self.root, "new", kind, cid)
                self.assertEqual(code, 1)
                self.assertIn(message, err)


if __name__ == "__main__":
    unittest.main()
