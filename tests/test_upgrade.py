"""`dotinfra upgrade`: install detection, commands, --check (network and subprocess mocked)."""

import io
import json
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from support import IsolatedTestCase, run_cli
from dotinfra import DotinfraError, upgrade


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def serve(routes: dict):
    """urlopen stand-in answering JSON by URL suffix; unknown URLs raise URLError."""
    seen = []

    def urlopen(request, timeout=None):
        seen.append((request.full_url, timeout))
        for suffix, payload in routes.items():
            if suffix in request.full_url:
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(json.dumps(payload).encode())
        raise urllib.error.URLError("offline")

    return urlopen, seen


class LatestReleaseTest(unittest.TestCase):
    def test_latest_stable_release(self):
        urlopen, seen = serve({"/releases": [
            {"tag_name": "v0.3.0rc1", "prerelease": True},
            {"tag_name": "v0.2.1"}, {"tag_name": "v0.10.0", "draft": True},
            {"tag_name": "v0.2.0"}]})
        with mock.patch("urllib.request.urlopen", urlopen):
            self.assertEqual(upgrade.latest_release(), "v0.2.1")
            self.assertEqual(upgrade.latest_release(pre=True), "v0.3.0rc1")
        self.assertEqual(seen[0][1], 5)

    def test_falls_back_to_tags(self):
        urlopen, _ = serve({"/releases": [], "/tags": [{"name": "v0.1.0"}, {"name": "v0.2.0"},
                                                       {"name": "nightly"}]})
        with mock.patch("urllib.request.urlopen", urlopen):
            self.assertEqual(upgrade.latest_release(), "v0.2.0")

    def test_offline_is_none(self):
        urlopen, _ = serve({})
        with mock.patch("urllib.request.urlopen", urlopen):
            self.assertIsNone(upgrade.latest_release())


class InstallMethodTest(unittest.TestCase):
    def test_commands(self):
        with mock.patch("shutil.which", return_value="/usr/bin/pipx"):
            self.assertEqual(upgrade.upgrade_command("pipx", "x"),
                             ["/usr/bin/pipx", "upgrade", "dotinfra"])
            self.assertEqual(upgrade.upgrade_command("pipx", "x", pre=True),
                             ["/usr/bin/pipx", "upgrade", "--pip-args=--pre", "dotinfra"])
        self.assertEqual(upgrade.upgrade_command("user", "x"),
                         [sys.executable, "-m", "pip", "install", "--user", "-U",
                          "git+https://github.com/PiotrTopa/dotinfra"])
        self.assertEqual(upgrade.upgrade_command("venv", "x")[:5],
                         [sys.executable, "-m", "pip", "install", "-U"])
        for kind in ("editable", "source", "system"):
            with self.subTest(kind=kind), self.assertRaises(DotinfraError):
                upgrade.upgrade_command(kind, "/somewhere")
        with mock.patch("shutil.which", return_value=None), self.assertRaises(DotinfraError):
            upgrade.upgrade_command("pipx", "x")

    def test_detects_the_dev_checkout(self):
        # the test suite runs from src/ via PYTHONPATH or an editable install
        self.assertIn(upgrade.install_method()[0], ("editable", "source"))

    def test_detects_pipx(self):
        package = Path(upgrade.dotinfra.__file__).resolve().parent
        dist = mock.Mock()
        dist.read_text.return_value = None
        dist.locate_file.return_value = package / "__init__.py"
        prefix = "/home/alice/.local/share/pipx/venvs/dotinfra"
        with mock.patch("importlib.metadata.distribution", return_value=dist), \
                mock.patch("sys.prefix", prefix):
            self.assertEqual(upgrade.install_method(), ("pipx", str(Path(prefix).resolve())))

    def test_detects_editable(self):
        dist = mock.Mock()
        dist.read_text.return_value = json.dumps({"url": "file:///src/dotinfra",
                                                  "dir_info": {"editable": True}})
        with mock.patch("importlib.metadata.distribution", return_value=dist):
            self.assertEqual(upgrade.install_method(), ("editable", "file:///src/dotinfra"))


class UpgradeCommandTest(IsolatedTestCase):
    def test_check_reports_newer(self):
        urlopen, _ = serve({"/releases": [{"tag_name": "v9.0.0"}]})
        with mock.patch("urllib.request.urlopen", urlopen):
            code, out, _ = run_cli("upgrade", "--check")
        self.assertEqual(code, 0)
        self.assertIn("dotinfra 9.0.0 is available", out)

    def test_check_offline_is_not_an_error(self):
        urlopen, _ = serve({})
        with mock.patch("urllib.request.urlopen", urlopen):
            code, out, _ = run_cli("upgrade", "--check")
        self.assertEqual(code, 0)
        self.assertIn("could not reach GitHub", out)

    def test_upgrade_then_migrate_inside_a_cmdb(self):
        root = self.make_cmdb()
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with mock.patch.object(upgrade, "install_method", return_value=("user", "/site")), \
                mock.patch("subprocess.run", run):
            code, out, err = run_cli("--root", root, "upgrade")
        self.assertEqual(code, 0, err)
        self.assertEqual(calls[0][-2:], ["-U", upgrade.GIT_URL])
        self.assertEqual(calls[1], [sys.executable, "-m", "dotinfra", "--root", str(root),
                                    "migrate", "--yes"])
        self.assertIn("next step is `dotinfra migrate`", out)

    def test_upgrade_outside_a_cmdb_does_not_migrate(self):
        calls = []
        with mock.patch.object(upgrade, "install_method", return_value=("user", "/site")), \
                mock.patch("subprocess.run",
                           lambda cmd, **kw: calls.append(cmd) or
                           subprocess.CompletedProcess(cmd, 0)):
            code, out, _ = run_cli("--root", self.tmp / "nothing", "upgrade")
        self.assertEqual((code, len(calls)), (0, 1))
        self.assertIn("run `dotinfra migrate` next", out)

    def test_failed_upgrade(self):
        with mock.patch.object(upgrade, "install_method", return_value=("user", "/site")), \
                mock.patch("subprocess.run",
                           lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1)):
            code, _, err = run_cli("upgrade")
        self.assertEqual(code, 1)
        self.assertIn("upgrade command failed", err)

    def test_dev_checkout_is_refused(self):
        with mock.patch.object(upgrade, "install_method", return_value=("editable", "/src")):
            code, _, err = run_cli("upgrade")
        self.assertEqual(code, 1)
        self.assertIn("git pull", err)

    def test_doctor_check_updates(self):
        root = self.make_cmdb()
        urlopen, _ = serve({"/releases": [{"tag_name": "v9.0.0"}]})
        with mock.patch("urllib.request.urlopen", urlopen):
            _, out, _ = run_cli("--root", root, "doctor", "--check-updates")
        self.assertIn("v9.0.0 is available", out)
        _, out, _ = run_cli("--root", root, "doctor")
        self.assertNotIn("updates", out)


if __name__ == "__main__":
    unittest.main()
