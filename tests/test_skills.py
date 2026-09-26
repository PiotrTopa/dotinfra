"""Agent Skills targets, detection, scopes, records, and `init --skills` (detection mocked)."""

from unittest import mock

from support import IsolatedTestCase, git, run_cli
from dotinfra import DotinfraError, skills
from dotinfra.config import load_config

NO_BINARIES = mock.patch("dotinfra.skills._on_path", return_value=False)


class TargetsTest(IsolatedTestCase):
    def test_parse(self):
        self.assertEqual(skills.parse_targets("claude, agy,claude"), ["claude", "antigravity"])
        self.assertEqual(skills.parse_targets("all"), list(skills.TARGETS))
        self.assertEqual(skills.parse_targets("both"), ["claude", "agents"])
        self.assertEqual(skills.parse_targets("none"), [])
        with self.assertRaises(DotinfraError):
            skills.parse_targets("claude,emacs")

    def test_every_target_has_both_scopes_and_docs(self):
        for target in skills.TARGETS.values():
            self.assertTrue(target.user and target.project, target.name)
            self.assertTrue(target.docs.startswith("https://"), target.name)

    def test_detect(self):
        with NO_BINARIES:
            self.assertEqual(skills.detect_targets(self.home), ["agents"])
            (self.home / ".claude").mkdir()
            (self.home / ".cline").mkdir()
            self.assertEqual(skills.detect_targets(self.home), ["agents", "claude", "cline"])
        with mock.patch("dotinfra.skills._on_path", side_effect=lambda b: b == "agy"):
            self.assertIn("antigravity", skills.detect_targets(self.home))

    def test_shared_directories_are_written_once(self):
        dirs = skills.target_dirs(["agents", "copilot", "codex", "gemini"], skills.USER,
                                  home=self.home)
        self.assertEqual(dirs, [self.home / ".agents" / "skills"])
        project = skills.target_dirs(["claude", "cline"], skills.PROJECT, root=self.tmp)
        self.assertEqual(project, [self.tmp / ".claude" / "skills"])


class InstallTest(IsolatedTestCase):
    def test_user_install_records_and_detects_staleness(self):
        code, out, err = run_cli("skills", "install", "--target", "claude,agy")
        self.assertEqual(code, 0, err)
        for rel in (".claude/skills", ".gemini/antigravity-cli/skills", ".gemini/config/skills"):
            self.assertTrue((self.home / rel / "infra-cmdb" / "SKILL.md").is_file(), rel)
            self.assertEqual(skills.skills_state(self.home / rel), "current")
        record = skills.read_record()
        self.assertEqual(record["targets"], ["antigravity", "claude"])
        self.assertIn(str(self.home / ".claude" / "skills"), record["dirs"])
        (self.home / ".claude/skills/infra-sync/SKILL.md").write_text("old\n")
        self.assertEqual(skills.skills_state(self.home / ".claude/skills"), "stale")
        self.assertEqual(len(skills.refresh_user_skills()), 1)
        self.assertEqual(skills.skills_state(self.home / ".claude/skills"), "current")
        # a second install rewrites nothing
        code, out, _ = run_cli("skills", "install", "--target", "claude")
        self.assertIn("already current", out)

    def test_other_skills_are_untouched(self):
        mine = self.home / ".agents" / "skills" / "my-skill" / "SKILL.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("mine\n")
        run_cli("skills", "install", "--target", "agents")
        self.assertEqual(mine.read_text(), "mine\n")

    def test_link(self):
        run_cli("skills", "install", "--target", "claude", "--link")
        dest = self.home / ".claude" / "skills" / "infra-cmdb"
        self.assertTrue(dest.is_symlink())
        self.assertEqual(skills.skills_state(dest.parent), "current")

    def test_project_scope(self):
        root = self.make_cmdb()
        code, out, err = run_cli("--root", root, "skills", "install", "--scope", "project",
                                 "--target", "claude,copilot,cline")
        self.assertEqual(code, 0, err)
        self.assertTrue((root / ".claude/skills/infra-vault/SKILL.md").is_file())
        self.assertTrue((root / ".agents/skills/infra-vault/SKILL.md").is_file())
        self.assertFalse((self.home / ".claude").exists())
        self.assertEqual(load_config(root).get("skills", "project"),
                         ["claude", "copilot", "cline"])
        # the bundled skills pass the CMDB's own secret scan
        code, out, err = run_cli("--root", root, "lint")
        self.assertEqual(code, 0, out + err)

    def test_status_and_doctor(self):
        root = self.make_cmdb()
        with NO_BINARIES:
            (self.home / ".claude").mkdir()
            _, out, _ = run_cli("--root", root, "doctor")
            self.assertRegex(out, r"INFO\s+skills\s+missing: .*\.claude/skills \(claude\)")
            run_cli("skills", "install", "--target", "claude")
            (self.home / ".claude/skills/infra-cmdb/SKILL.md").write_text("old\n")
            _, out, _ = run_cli("--root", root, "doctor")
            self.assertRegex(out, r"WARN\s+skills\s+stale: .*\.claude/skills")
            code, out, _ = run_cli("--root", root, "skills", "status")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"claude\s+user\s+stale")


class InitSkillsTest(IsolatedTestCase):
    def test_init_installs_detected_agents_in_both_scopes(self):
        root = self.tmp / "infra"
        with NO_BINARIES:
            (self.home / ".claude").mkdir()
            code, out, err = run_cli("init", root, "--yes")
        self.assertEqual(code, 0, err)
        self.assertTrue((root / ".claude/skills/infra-cmdb/SKILL.md").is_file())
        self.assertTrue((root / ".agents/skills/infra-cmdb/SKILL.md").is_file())
        self.assertTrue((self.home / ".claude/skills/infra-cmdb/SKILL.md").is_file())
        self.assertEqual(git(root, "status", "--porcelain"), "")  # committed with the layout
        self.assertIn(".claude/skills/infra-cmdb/SKILL.md", git(root, "ls-files"))
        readme = (root / "README.md").read_text()
        self.assertIn("already carries the skills", readme)

    def test_init_explicit_targets_and_none(self):
        with NO_BINARIES:
            code, _, err = run_cli("init", self.tmp / "a", "--skills", "copilot",
                                   "--skills-scope", "project")
            self.assertEqual(code, 0, err)
            self.assertTrue((self.tmp / "a/.agents/skills/infra-cmdb").is_dir())
            self.assertFalse((self.home / ".agents").exists())
            run_cli("init", self.tmp / "b", "--skills", "none")
            self.assertFalse((self.tmp / "b/.agents").exists())

    def test_init_asks_on_a_terminal(self):
        with NO_BINARIES, mock.patch("dotinfra.scaffold._interactive", return_value=True), \
                mock.patch("builtins.input", return_value="none") as ask:
            code, out, _ = run_cli("init", self.tmp / "c")
        self.assertEqual(code, 0)
        ask.assert_called_once()
        self.assertFalse((self.tmp / "c/.agents").exists())

    def test_init_remote(self):
        with NO_BINARIES:
            code, out, err = run_cli("init", self.tmp / "d", "--skills", "none", "--remote",
                                     "git@git.example.com:alice/infra.git")
        self.assertEqual(code, 0, err)
        root = self.tmp / "d"
        self.assertEqual(git(root, "remote", "get-url", "origin").strip(),
                         "git@git.example.com:alice/infra.git")
        self.assertEqual(load_config(root).get("sync", "remote_url"),
                         "git@git.example.com:alice/infra.git")
        self.assertIn("git clone git@git.example.com:alice/infra.git ~/.infra",
                      (root / "README.md").read_text())
