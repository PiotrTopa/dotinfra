import argparse
import importlib
import json
import subprocess
import sys
import unittest
from unittest import mock

from support import SRC, IsolatedTestCase, component, run_cli
from dotinfra import __version__
from dotinfra.cli import build_parser


def subcommands(parser: argparse.ArgumentParser, prefix=()):
    """Yield every (sub)command path, e.g. ('vault', 'set')."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield prefix + (name,)
                yield from subcommands(sub, prefix + (name,))


class HelpTest(IsolatedTestCase):
    def test_every_command_has_help(self):
        paths = list(subcommands(build_parser()))
        self.assertGreater(len(paths), 25)
        for path in paths:
            with self.subTest(command=" ".join(path)):
                code, out, _ = run_cli(*path, "--help")
                self.assertEqual(code, 0)
                self.assertIn("usage: dotinfra", out)

    def test_version_and_module_entry_point(self):
        code, out, _ = run_cli("--version")
        self.assertEqual((code, out.strip()), (0, f"dotinfra {__version__}"))
        result = subprocess.run([sys.executable, "-m", "dotinfra", "--version"],
                                capture_output=True, text=True, cwd=SRC)
        self.assertEqual(result.stdout.strip(), f"dotinfra {__version__}")


class BrowseTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb(use_git=False)
        self.write(self.root, "servers/web1.md", component(
            "status: active\naddress: 10.0.0.5\ntags: [fleet]\nrole: web", "# Web one\n"))
        self.write(self.root, "services/app.md", component("status: planned\nruns_on: web1"))

    def test_ls(self):
        code, out, _ = run_cli("--root", self.root, "ls")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0].split(), ["ID", "KIND", "STATUS", "ADDRESS", "TITLE"])
        self.assertEqual(lines[1].split(), ["web1", "server", "active", "10.0.0.5", "Web", "one"])
        _, out, _ = run_cli("--root", self.root, "ls", "--kind", "services", "--json")
        self.assertEqual([c["id"] for c in json.loads(out)], ["app"])
        _, out, _ = run_cli("--root", self.root, "ls", "--tag", "fleet", "--status", "active")
        self.assertIn("web1", out)
        self.assertNotIn("app", out)

    def test_show(self):
        code, out, _ = run_cli("--root", self.root, "show", "web1")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# servers/web1.md\n---\n"))
        data = json.loads(run_cli("--root", self.root, "show", "web1", "--json")[1])
        self.assertEqual(data["meta"]["role"], "web")
        self.assertEqual(run_cli("--root", self.root, "show", "zzz")[0], 1)

    def test_root_discovery(self):
        import os
        os.environ["DOTINFRA_ROOT"] = str(self.root)
        self.assertIn("web1", run_cli("ls")[1])

    def test_missing_cmdb_is_friendly(self):
        code, _, err = run_cli("--root", self.tmp / "nothing", "ls")
        self.assertEqual(code, 1)
        self.assertIn("run `dotinfra init`", err)

    def test_unparseable_files_are_reported_not_hidden(self):
        self.write(self.root, "servers/broken.md", "---\na: |\n  x\n---\n")
        code, out, err = run_cli("--root", self.root, "ls")
        self.assertEqual(code, 0)
        self.assertIn("web1", out)
        self.assertIn("servers/broken.md:2", err)
        self.assertIn("dotinfra lint", err)

    def test_os_errors_are_friendly(self):
        blocker = self.write(self.tmp, "blocker", "not a directory\n")
        code, _, err = run_cli("init", blocker / "cmdb")
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("dotinfra: error: "), err)
        self.assertNotIn("Traceback", err)


class DoctorTest(IsolatedTestCase):
    def test_doctor_on_fresh_cmdb(self):
        root = self.make_cmdb()
        code, out, _ = run_cli("--root", root, "doctor")
        self.assertEqual(code, 0, out)
        for name in ("python", "git", "cmdb", "merge driver", "vault", "lint"):
            self.assertRegex(out, rf"(?m)^OK +{name} ")

    def test_doctor_reports_problems(self):
        code, out, _ = run_cli("--root", self.tmp / "missing", "doctor")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"(?m)^FAIL +cmdb ")


class OptionalModulesTest(IsolatedTestCase):
    def test_broken_optional_module_does_not_break_cli(self):
        real_import = importlib.import_module

        def fake_import(name, *args):
            if name == "dotinfra.events":
                raise ImportError("simulated breakage")
            return real_import(name, *args)

        with mock.patch("dotinfra.cli.importlib.import_module", side_effect=fake_import):
            code, _, err = run_cli("event", "list")
            self.assertEqual(code, 1)
            self.assertIn("the 'event' command is unavailable", err)
            self.assertIn("simulated breakage", err)
            code, out, err = run_cli("--version")
            self.assertEqual((code, err), (0, ""))


class MergeDriverCommandTest(IsolatedTestCase):
    def test_merge_driver_entry_point(self):
        base = self.write(self.tmp, "O", "# t\n\n## A\n\nx\n\n## B\n\ny\n")
        ours = self.write(self.tmp, "A", "# t\n\n## A\n\nx2\n\n## B\n\ny\n")
        theirs = self.write(self.tmp, "B", "# t\n\n## A\n\nx\n\n## B\n\ny2\n")
        code, _, _ = run_cli("merge-driver", base, ours, theirs, "doc.md")
        self.assertEqual(code, 0)
        self.assertEqual(ours.read_text(), "# t\n\n## A\n\nx2\n\n## B\n\ny2\n")


if __name__ == "__main__":
    unittest.main()
