import json
import unittest
from datetime import date

from support import IsolatedTestCase, component, run_cli
from dotinfra.config import load_config
from dotinfra.lint import run_lint
from dotinfra.vault import open_vault

TODAY = date(2026, 9, 26)
GOOD = """\
    id: {id}
    status: active
    role: test box
    updated: 2026-09-01
"""


class LintTestCase(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb(use_git=False)

    def add(self, rel: str, meta: str, body: str = "# Title\n"):
        self.write(self.root, rel, component(meta, body))

    def issues(self, strict: bool = False):
        return run_lint(self.root, load_config(self.root), strict=strict, today=TODAY)

    def rules(self, level: str = "error", strict: bool = False):
        return sorted({(i.path, i.rule) for i in self.issues(strict) if i.level == level})


class FreshCmdbTest(LintTestCase):
    def test_fresh_cmdb_and_templates_are_clean(self):
        for kind in ("server", "network", "domain", "router", "service", "device"):
            code, _, err = run_cli("--root", self.root, "new", kind, f"x-{kind}")
            self.assertEqual(code, 0, err)
        errors = [i for i in self.issues(strict=True) if i.level == "error"]
        self.assertEqual(errors, [])
        warnings = {i.rule for i in self.issues(strict=True)}
        self.assertEqual(warnings, {"role"})  # templates leave `role:` for the author


class ErrorRulesTest(LintTestCase):
    def test_schema_errors(self):
        self.add("servers/nostatus.md", "role: r\nupdated: 2026-09-01")
        self.add("servers/badstatus.md", "status: running\nrole: r\nupdated: 2026-09-01")
        self.add("servers/Bad_Id.md", "id: Bad_Id\nstatus: active\nrole: r\nupdated: 2026-09-01")
        self.add("servers/kind.md", "kind: router\nstatus: active\nrole: r\nupdated: 2026-09-01")
        self.add("servers/metric.md", "status: active\nrole: r\nupdated: 2026-09-01\n"
                                      "metrics: [node, node:9100]")
        self.add("servers/sshstr.md", "status: active\nrole: r\nupdated: 2026-09-01\nssh: alice")
        self.add("routers/broken.md", "status: [unterminated")
        self.assertEqual(self.rules(), [
            ("routers/broken.md", "parse"),
            ("servers/Bad_Id.md", "id"),
            ("servers/badstatus.md", "status"),
            ("servers/kind.md", "kind"),
            ("servers/metric.md", "metrics"),
            ("servers/nostatus.md", "status"),
            ("servers/sshstr.md", "ssh"),
        ])

    def test_references_and_duplicates(self):
        self.add("servers/a.md", GOOD.format(id="a") + "    depends_on: [b, ghost]\n"
                                                     "    ssh:\n      jump: nowhere\n")
        self.add("servers/b.md", GOOD.format(id="b"))
        self.add("services/app.md", GOOD.format(id="app") + "    runs_on: missing\n")
        self.add("devices/b.md", GOOD.format(id="b"))
        issues = [i for i in self.issues() if i.level == "error"]
        messages = sorted(i.message for i in issues)
        self.assertEqual(len(issues), 4, messages)
        self.assertTrue(any("'ghost'" in m for m in messages))
        self.assertTrue(any("ssh.jump" in m and "'nowhere'" in m for m in messages))
        self.assertTrue(any("runs_on" in m for m in messages))
        self.assertTrue(any("duplicate id 'b'" in m for m in messages))

    def test_unsafe_ssh_and_address_values(self):
        self.add("servers/a.md", GOOD.format(id="a") + '    ssh:\n      host: "x\\ny"\n')
        self.add("servers/b.md", GOOD.format(id="b") + "    address: -oProxyCommand=x\n")
        self.add("servers/c.md", GOOD.format(id="c") + "    ssh:\n      port: 22 or 2222\n")
        self.assertEqual(self.rules(), [("servers/a.md", "unsafe"), ("servers/b.md", "unsafe"),
                                        ("servers/c.md", "unsafe")])

    def test_error_line_numbers(self):
        self.add("servers/a.md", "id: a\nrole: r\nstatus: nope\nupdated: 2026-09-01")
        issue = next(i for i in self.issues() if i.rule == "status")
        self.assertEqual(issue.line, 4)


class SecretScanTest(LintTestCase):
    def secret_lines(self):
        return sorted((i.path, i.line) for i in self.issues() if i.rule == "secret")

    def test_detects_secrets_anywhere(self):
        leaks = [
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            "root password: hunter2",
            "DB_PASSWORD=s3cret",
            "key AKIAABCDEFGHIJKLMNOP",
            "token ghp_" + "a" * 36,
            "openai sk-" + "b" * 24,
            "slack xoxb-1234",
            "project key sk-proj-" + "c" * 40,
            "fine-grained github_pat_" + "d" * 30,
            "-----BEGIN PGP PRIVATE KEY BLOCK-----",
            "AGE-SECRET-KEY-1" + "Q" * 58,
        ]
        self.add("servers/a.md", GOOD.format(id="a"), "# A\n\n" + "\n".join(leaks) + "\n")
        self.write(self.root, "notes.txt", "password = letmein\n")
        found = self.secret_lines()
        self.assertEqual(found, [("notes.txt", 1)]
                         + [("servers/a.md", n) for n in range(10, 10 + len(leaks))])

    def test_allowed_forms(self):
        body = "\n".join([
            "# A",
            "sudo password: vault key `a_sudo`",
            "password: <see vault>",
            "Password = ***",
            "example password: hunter2  dotinfra:allow-secret",
            "the password is in the vault",
        ])
        self.add("servers/a.md", GOOD.format(id="a"), body + "\n")
        self.assertEqual(self.secret_lines(), [])

    def test_git_ignored_files_are_not_scanned(self):
        root = self.make_cmdb("withgit")
        self.write(root, "servers/private.local.md", "password: hunter2\n")
        self.write(root, "servers/tracked.md", component(GOOD.format(id="tracked")))
        self.write(root, "leak.txt", "password: hunter2\n")  # untracked, not ignored: scanned
        issues = run_lint(root, load_config(root), today=TODAY)
        self.assertEqual([(i.path, i.rule) for i in issues if i.rule == "secret"],
                         [("leak.txt", "secret")])


class CredentialNotationTest(unittest.TestCase):
    """Markdown ways of writing a credential next to a quoted value (made-up values only)."""

    FLAGGED = [
        "- UID: 1000, Pass: `Wq7-plover`",
        "- `bob`: Password `m4ple!leaf`, passwordless sudo",
        "User account password set to `Qx9#tundra`.",
        'password: "Rk2 lantern"',
        "The admin password is `zephyr-81`",
        "PASSWD='c0bble5tone'",
        "Wi-Fi passphrase: `amber otter meadow`",
        "pwd = 'Lk88swift'",
        "SIM PIN: `4827`",
        "API key: `ak_live_91fz0q`",
        'api_key = "9f3c1a7b"',
        "Token: `t0k-e9x2`",
        'Secret = "orchid-72"',
        "**Password:** `Vr5-quill`",
        '{"password": "n1mbus-cloud"}',
        "db_password: 'p4ssage-home'",
        "Login: alice / pass is `h0llow-reed`",
        "`mysql -u root --password 'k3strel'`",
        "Pass = `q2w-lynx`",
        '"auth_token": "f00d-cafe-77"',
        "router PIN is '9031'",
        "password `it's-a-trap`",
    ]
    ALLOWED = [
        "- `bob`: passwordless sudo",
        "SSH password auth disabled",
        "Password in vault (`nas_sudo`)",
        "run it with keyvault exec nas_sudo -- sudo -S true",
        "`dotinfra vault exec nas_sudo -- sudo -S true`",
        "password: `<password>`",
        "Password: `***`",
        "PasswordAuthentication no",
        "Password: from `~/x/secrets.yaml`",
        "Token: `$GRAFANA_TOKEN`",
        "passphrase: `/etc/ssl/private/site.pass`",
        "Password: `./secrets/db.txt`",
        "pin `GRAFANA_IMAGE` to the running version",
        "Pass `--force` to overwrite",
        "the `password` field of the form is required",
        'grafana_password_key = "grafana_password"',
        "Secret: `{{ db_secret }}`",
        "API key: `WEATHER_API_KEY` (from the environment)",
        "token: `...`",
        "Rotate the secret quarterly.",
        "password: <see vault>",
        "Pinned `grafana/grafana` to a newer tag",
        "tokens: [`a`, `b`]",
        "sudo password: vault key `a_sudo`",
        "Password = ***",
        'GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?set it in .env}',
    ]

    def test_flagged(self):
        from dotinfra.lint import secret_labels

        for line in self.FLAGGED:
            with self.subTest(line=line):
                self.assertEqual(secret_labels(line), ["password"])

    def test_allowed(self):
        from dotinfra.lint import secret_labels

        for line in self.ALLOWED:
            with self.subTest(line=line):
                self.assertEqual(secret_labels(line), [])

    def test_reported_once_per_line(self):
        from dotinfra.lint import secret_labels

        self.assertEqual(secret_labels("password: `Vr5-quill` and PIN: `4827`"), ["password"])


class WarningRulesTest(LintTestCase):
    def test_warnings(self):
        self.add("servers/norole.md", "status: active\nupdated: 2026-09-01")
        self.add("servers/stale.md", "status: active\nrole: r\nupdated: 2025-01-01")
        self.add("servers/noupdated.md", "status: active\nrole: r")
        self.add("servers/baddate.md", "status: active\nrole: r\nupdated: last week")
        self.add("servers/noh1.md", "status: active\nrole: r\nupdated: 2026-09-01", "text\n")
        self.add("servers/extra.md", "status: active\nrole: r\nupdated: 2026-09-01\n"
                                     "colour: blue\nssh:\n  shell: zsh")
        self.assertEqual(self.rules("warning"), [
            ("servers/baddate.md", "updated"),
            ("servers/noh1.md", "h1"),
            ("servers/norole.md", "role"),
            ("servers/noupdated.md", "updated"),
            ("servers/stale.md", "stale"),
        ])
        self.assertIn(("servers/extra.md", "unknown-key"), self.rules("warning", strict=True))

    def test_missing_vault_keys_warn_only_when_vault_readable(self):
        self.add("servers/a.md", GOOD.format(id="a") + "    secrets: [a_sudo, a_token]\n")
        open_vault(load_config(self.root)).set("a_sudo", "x")
        vault_issues = [i for i in self.issues() if i.rule == "vault"]
        self.assertEqual(len(vault_issues), 1)
        self.assertIn("'a_token'", vault_issues[0].message)
        self.write(self.root, ".dotinfra.toml", '[vault]\nbackend = "nope"\n')
        self.assertEqual([i for i in self.issues() if i.rule == "vault"], [])


class ShapeRulesTest(LintTestCase):
    """`journal` and `long`: component docs are concise fact sheets (warnings only)."""

    def test_history_heading_is_journal(self):
        for heading in ("History", "Changelog", "Change log", "Log", "Event history",
                        "Historical notes"):
            with self.subTest(heading=heading):
                self.add("servers/a.md", GOOD.format(id="a"),
                         f"# a\n\n## Overview\n\nbox\n\n## {heading}\n\n- 2026-01-01 — x\n")
                found = [i for i in self.issues() if i.rule == "journal"]
                self.assertEqual(len(found), 1)
                self.assertEqual((found[0].level, found[0].line), ("warning", 14))
                self.assertIn("dotinfra event add", found[0].message)

    def test_known_issues_and_prose_dates_are_fine(self):
        body = ("# a\n\n## Constraints & known issues\n\n- TLS cert expires 2026-12-01\n"
                "- 2026-10-01: warranty ends\n\n```\n2026-01-01 a\n2026-01-02 b\n"
                "2026-01-03 c\n2026-01-04 d\n2026-01-05 e\n2026-01-06 f\n```\n")
        self.add("servers/a.md", GOOD.format(id="a"), body)
        self.assertEqual([i for i in self.issues() if i.rule in ("journal", "long")], [])

    def test_many_dated_lines_are_journal(self):
        lines = "".join(f"- 2026-0{n}-01 — did {n}\n" for n in range(1, 7))
        self.add("servers/a.md", GOOD.format(id="a"), f"# a\n\n## Notes\n\n{lines}")
        found = [i for i in self.issues() if i.rule == "journal"]
        self.assertEqual(len(found), 1)
        self.assertIn("6 lines start with a date", found[0].message)
        self.add("servers/a.md", GOOD.format(id="a"),
                 f"# a\n\n## Notes\n\n{''.join(lines.splitlines(True)[:5])}")
        self.assertEqual([i for i in self.issues() if i.rule == "journal"], [])

    def test_long_body_and_configurable_limit(self):
        body = "# a\n\n" + "".join(f"- fact {n}\n" for n in range(130))
        self.add("servers/a.md", GOOD.format(id="a"), body)
        found = [i for i in self.issues() if i.rule == "long"]
        self.assertEqual([(i.level, i.line) for i in found], [("warning", 7)])
        self.assertIn("132 lines (limit 120", found[0].message)
        from dotinfra.config import set_toml_value
        set_toml_value(self.root / ".dotinfra.toml", "lint", "max_lines", 200)
        self.assertEqual([i for i in self.issues() if i.rule == "long"], [])
        set_toml_value(self.root / ".dotinfra.toml", "lint", "max_lines", 20)
        self.assertEqual(len([i for i in self.issues() if i.rule == "long"]), 1)

    def test_warnings_do_not_fail_lint(self):
        self.add("servers/a.md", GOOD.format(id="a"), "# a\n\n## History\n\n- 2026-01-01 — x\n")
        code, out, _ = run_cli("--root", self.root, "lint")
        self.assertEqual(code, 0)
        self.assertIn("[journal]", out)


class LintCliTest(LintTestCase):
    def test_exit_codes_and_json(self):
        self.add("servers/a.md", GOOD.format(id="a"))
        code, out, _ = run_cli("--root", self.root, "lint")
        self.assertEqual(code, 0)
        self.assertIn("0 error(s)", out)
        self.add("servers/b.md", "status: bogus")
        code, out, _ = run_cli("--root", self.root, "lint", "--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertIn({"level": "error", "path": "servers/b.md", "line": 2,
                       "message": "invalid status 'bogus' (one of: active, planned, degraded, "
                                  "retired)", "rule": "status"}, data)


if __name__ == "__main__":
    unittest.main()
