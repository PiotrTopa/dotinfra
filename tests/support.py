"""Shared test helpers: isolated temp dirs, environment, CLI runner, git fixtures."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotinfra.cli import main  # noqa: E402
from dotinfra.scaffold import init_cmdb  # noqa: E402


def run_cli(*argv: str, stdin: str | None = None) -> tuple[int, str, str]:
    """Run the CLI in-process; return ``(exit_code, stdout, stderr)``."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), mock.patch("sys.stdin",
                                                                io.StringIO(stdin or "")):
        try:
            code = main([str(a) for a in argv])
        except SystemExit as exc:  # argparse --help / usage errors
            code = exc.code if isinstance(exc.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def component(meta: str, body: str = "# Title\n") -> str:
    """A component document from dedented frontmatter lines and body."""
    return f"---\n{textwrap.dedent(meta).strip()}\n---\n\n{textwrap.dedent(body)}"


class IsolatedTestCase(unittest.TestCase):
    """Each test gets a temp dir as $HOME, a fixed git identity and no global git config."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="dotinfra-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        home = self.tmp / "home"
        home.mkdir()
        env = {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "PYTHONPATH": os.pathsep.join(filter(None, [str(SRC),
                                                        os.environ.get("PYTHONPATH")])),
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("DOTINFRA_ROOT", None)
        self.home = home

    def make_cmdb(self, name: str = "cmdb", *, use_git: bool = True, **kwargs) -> Path:
        root = self.tmp / name
        init_cmdb(root, name, use_git=use_git, **kwargs)
        return root

    @staticmethod
    def write(root: Path, rel: str, text: str) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout
