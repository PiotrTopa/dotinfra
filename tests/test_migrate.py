"""Managed blocks, `dotinfra migrate` (0.1.x → 0.2) and its idempotence."""

import shutil
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from support import IsolatedTestCase, git, run_cli
from dotinfra import managed
from dotinfra.managed import (ADOPTED, CREATED, HASH, INSERTED, MD, UNCHANGED, UPDATED,
                              find_block, refresh, wrap)
from dotinfra.migrate import plan_migration
from dotinfra.model import KINDS
from dotinfra.scaffold import EXAMPLES, LEGACY

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "homelab-0.1.1"
FIXTURE_FILES = {"README.md": "README.md", "AGENTS.md": "AGENTS.md", "CLAUDE.md": "CLAUDE.md",
                 "gitignore": ".gitignore", "gitattributes": ".gitattributes",
                 "dotinfra.toml": ".dotinfra.toml"}


class ManagedBlockTest(unittest.TestCase):
    def test_wrap_and_find(self):
        text = "above\n" + wrap("one\ntwo\n", MD, "0.2.0") + "below\n"
        block = find_block(text, MD)
        self.assertEqual(block.version, "0.2.0")
        self.assertEqual(block.content, "one\ntwo\n")
        self.assertEqual(text[block.end:], "below\n")
        self.assertIsNone(find_block("<!-- dotinfra:managed:start v=1 -->\nno end\n", MD))

    def test_hash_style(self):
        text = wrap("a\n", HASH, "0.2.0")
        self.assertEqual(text, "# dotinfra:managed:start v=0.2.0\na\n# dotinfra:managed:end\n")
        self.assertEqual(find_block(text, HASH).content, "a\n")

    def test_created(self):
        self.assertEqual(refresh(None, "x\n", MD), (wrap("x\n", MD), CREATED))

    def test_refresh_preserves_user_text_byte_for_byte(self):
        above = "My notes on top.\n\n  indented  \n"
        below = "\n## Local runbook\n\n- keep me\n\ttabbed\n"
        text = above + wrap("old content\n", MD, "0.1.9") + below
        new, action = refresh(text, "new content\n", MD)
        self.assertEqual(action, UPDATED)
        self.assertTrue(new.startswith(above))
        self.assertTrue(new.endswith(below))
        self.assertIn("new content\n", new)
        self.assertNotIn("old content", new)
        self.assertIn(f"v={managed.installed_version()}", new)

    def test_unchanged_keeps_marker_version(self):
        text = "x\n" + wrap("same\n", MD, "0.1.9")
        self.assertEqual(refresh(text, "same\n", MD), (text, UNCHANGED))

    def test_legacy_render_is_adopted(self):
        legacy = "# {{name}} infrastructure\n\nhello\n"
        new, action = refresh("# home infrastructure\n\nhello  \n", "fresh\n", MD,
                              legacy_renders=[legacy])
        self.assertEqual((new, action), (wrap("fresh\n", MD), ADOPTED))

    def test_edited_markdown_keeps_user_text_below(self):
        legacy = "# {{name}} infrastructure\n\nhello\n"
        edited = "# home infrastructure\n\nhello\n\n## My section\n"
        new, action = refresh(edited, "fresh\n", MD, legacy_renders=[legacy])
        self.assertEqual(action, INSERTED)
        self.assertEqual(new, wrap("fresh\n", MD) + "\n" + edited)

    def test_edited_dotfile_drops_lines_the_block_provides(self):
        legacy = "# dotinfra comment\n.dotinfra/state/\nvault.json\n"
        edited = "# dotinfra comment\n.dotinfra/state/\nvault.json\n\n# mine\n*.bak\n"
        new, action = refresh(edited, ".dotinfra/state/\nvault.json\n.dotinfra.local.toml\n",
                              HASH, legacy_renders=[legacy])
        self.assertEqual(action, INSERTED)
        block_end = new.index("# dotinfra:managed:end\n") + len("# dotinfra:managed:end\n")
        self.assertEqual(new[block_end:], "# mine\n*.bak\n")

    def test_every_managed_template_has_a_legacy_render(self):
        for name in ("README.md", "AGENTS.md", "CLAUDE.md", "gitignore", "gitattributes"):
            self.assertTrue((LEGACY / "0.1" / name).is_file(), name)


class MigrateTestCase(IsolatedTestCase):
    def make_legacy(self, name: str = "old", *, example: bool = False) -> Path:
        """A CMDB as dotinfra 0.1.x left it (plain template renders, or the old example)."""
        root = self.tmp / name
        root.mkdir()
        for folder in KINDS:
            (root / folder).mkdir()
            (root / folder / ".gitkeep").touch()
            if example:
                for path in (EXAMPLES / "homelab" / folder).glob("*.md"):
                    shutil.copyfile(path, root / folder / path.name)
        source = FIXTURE if example else LEGACY / "0.1"
        for template, target in FIXTURE_FILES.items():
            text = (source / template).read_text(encoding="utf-8")
            (root / target).write_text(text.replace("{{name}}", name), encoding="utf-8")
        if example:
            shutil.copyfile(FIXTURE / "services" / "monitoring.md",
                            root / "services" / "monitoring.md")
        git(root, "init", "-q")
        git(root, "symbolic-ref", "HEAD", "refs/heads/main")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init: dotinfra CMDB")
        return root

    def migrate(self, root: Path, *extra: str, expected: int = 0) -> str:
        code, out, err = run_cli("--root", root, "migrate", "--yes", *extra)
        self.assertEqual(code, expected, f"stdout:\n{out}\nstderr:\n{err}")
        return out + err

    @staticmethod
    def toml(root: Path) -> dict:
        return tomllib.loads((root / ".dotinfra.toml").read_text())

    @staticmethod
    def commits(root: Path) -> list[str]:
        return git(root, "log", "--format=%s").splitlines()


class MigrateLegacyTest(MigrateTestCase):
    def test_plain_01x_cmdb(self):
        root = self.make_legacy()
        out = self.migrate(root)
        self.assertIn("schema 0 → 1", out)
        data = self.toml(root)
        self.assertEqual((data["cmdb"]["schema"], data["cmdb"]["min_version"]), (1, "0.2.0"))
        self.assertEqual(data["monitoring"]["service"], "monitoring")
        # the literal 0.1 localhost defaults no longer shadow the service component
        self.assertNotIn("grafana_url", data["monitoring"])
        self.assertIn('# grafana_url = "http://localhost:3000"',
                      (root / ".dotinfra.toml").read_text())
        for name in ("README.md", "AGENTS.md", "CLAUDE.md", ".gitignore", ".gitattributes"):
            text = (root / name).read_text()
            self.assertTrue(text.startswith("<!-- dotinfra:managed:start v=0.2.0 -->")
                            or text.startswith("# dotinfra:managed:start v=0.2.0"), name)
        self.assertIn("0.1.x template replaced", out)
        readme = (root / "README.md").read_text()
        self.assertIn("## Start here — new machine", readme)
        self.assertIn("pipx install git+https://github.com/PiotrTopa/dotinfra", readme)
        self.assertIn("dotinfra ≥ 0.2.0", readme)
        self.assertIn("git clone <URL of this repository> ~/.infra", readme)
        self.assertIn(".dotinfra.local.toml", (root / ".gitignore").read_text())
        self.assertEqual(self.commits(root)[0], "migrate: dotinfra 0.2.0")
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_idempotent(self):
        root = self.make_legacy()
        self.migrate(root)
        snapshot = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()
                    and ".git" not in p.parts}
        out = self.migrate(root)
        self.assertIn("is up to date", out)
        self.assertEqual(len(self.commits(root)), 2)
        self.assertEqual(snapshot, {p: p.read_bytes() for p in root.rglob("*") if p.is_file()
                                    and ".git" not in p.parts})
        self.assertFalse(plan_migration(root).changed)

    def test_dry_run_writes_nothing(self):
        root = self.make_legacy()
        before = (root / ".dotinfra.toml").read_text()
        out = self.migrate(root, "--dry-run")
        self.assertIn("would migrate", out)
        self.assertEqual((root / ".dotinfra.toml").read_text(), before)
        self.assertEqual(len(self.commits(root)), 1)

    def test_old_example(self):
        root = self.make_legacy("homelab", example=True)
        out = self.migrate(root)
        readme = (root / "README.md").read_text()
        # the example README was not a plain template render: its text is kept below
        self.assertIn("managed block added on top", out)
        self.assertIn("note: README.md had local edits", out)
        self.assertTrue(readme.startswith("<!-- dotinfra:managed:start"))
        self.assertIn("**This is a fictional example CMDB**", readme.split("managed:end")[1])
        # AGENTS.md was the template with the name filled in: adopted
        self.assertNotIn("managed:end -->\n\n#", (root / "AGENTS.md").read_text())
        data = self.toml(root)
        # explicit, non-default URLs are the user's choice and stay
        self.assertEqual(data["monitoring"]["grafana_url"], "http://10.10.0.10:3000")
        self.assertIn("Prometheus and Grafana run on **nas**", readme.replace("\n   ", " "))
        self.assertEqual(self.migrate(root).count("up to date"), 1)

    def test_hand_edited_readme(self):
        root = self.make_legacy()
        readme = root / "README.md"
        mine = readme.read_text() + "\n## Our conventions\n\n- servers are named after birds\n"
        readme.write_text(mine)
        git(root, "commit", "-qam", "local notes")
        self.migrate(root)
        text = readme.read_text()
        block = find_block(text, MD)
        self.assertIsNotNone(block)
        self.assertEqual(text[block.end:], "\n" + mine)
        # later refreshes keep it too
        text = text.replace("## Start here — new machine", "## Start here (edited in block)")
        text = "Top note.\n\n" + text
        readme.write_text(text)
        out = self.migrate(root)
        self.assertIn("README.md: managed block refreshed", out)
        final = readme.read_text()
        self.assertTrue(final.startswith("Top note.\n\n<!-- dotinfra:managed:start"))
        self.assertTrue(final.endswith(mine))
        self.assertIn("## Start here — new machine", final)
        self.assertNotIn("edited in block", final)

    def test_remote_url_recorded_without_credentials(self):
        root = self.make_legacy()
        git(root, "remote", "add", "origin", "https://alice:hunter2@git.example.com/alice/infra.git")
        out = self.migrate(root)
        self.assertIn("remote_url → https://git.example.com/alice/infra.git", out)
        readme = (root / "README.md").read_text()
        self.assertIn("git clone https://git.example.com/alice/infra.git ~/.infra", readme)
        self.assertNotIn("hunter2", readme + (root / ".dotinfra.toml").read_text())
        self.assertNotIn("<URL of this repository>", readme)

    def test_min_version_is_only_raised(self):
        root = self.make_legacy()
        self.migrate(root)
        with mock.patch("dotinfra.__version__", "0.3.1"):
            self.migrate(root)
            self.assertEqual(self.toml(root)["cmdb"]["min_version"], "0.3.0")
        with mock.patch("dotinfra.__version__", "0.3.4"):
            self.assertIn("up to date", self.migrate(root))
            self.assertEqual(self.toml(root)["cmdb"]["min_version"], "0.3.0")

    def test_newer_schema_is_refused(self):
        root = self.make_legacy()
        self.migrate(root)
        text = (root / ".dotinfra.toml").read_text().replace("schema = 1", "schema = 99")
        (root / ".dotinfra.toml").write_text(text)
        out = self.migrate(root, expected=1)
        self.assertIn("schema 99", out)

    def test_refuses_during_merge(self):
        root = self.make_legacy()
        (root / ".git" / "MERGE_HEAD").write_text(git(root, "rev-parse", "HEAD"))
        self.assertIn("merge is in progress", self.migrate(root, expected=1))


class MigrateSkillsTest(MigrateTestCase):
    def test_refreshes_project_and_recorded_user_skills(self):
        root = self.make_cmdb("cur")
        code, out, err = run_cli("--root", root, "skills", "install", "--target", "claude",
                                 "--scope", "both")
        self.assertEqual(code, 0, err)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "skills")
        project = root / ".claude" / "skills" / "infra-cmdb" / "SKILL.md"
        user = self.home / ".claude" / "skills" / "infra-cmdb" / "SKILL.md"
        pristine = project.read_text()
        project.write_text("stale\n")
        user.write_text("stale\n")
        git(root, "commit", "-qam", "old skills")
        out = self.migrate(root)
        self.assertIn(".claude/skills/: refresh project-scope skills", out)
        self.assertIn("refreshed 1 user-scope skill", out)
        self.assertEqual(project.read_text(), pristine)
        self.assertEqual(user.read_text(), pristine)
        self.assertEqual(self.commits(root)[0], "migrate: dotinfra 0.2.0")


if __name__ == "__main__":
    unittest.main()
