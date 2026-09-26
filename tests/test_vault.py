import json
import os
import shutil
import stat
import sys
import textwrap
import unittest

from support import IsolatedTestCase, run_cli
from dotinfra.config import load_config
from dotinfra.vault import AgeVault, FileVault, VaultError, open_vault

FAKE_AGE = """\
#!{python}
# Test double for `age`: "encrypts" by prefixing the recipient list.
import sys
args = sys.argv[1:]
if "--decrypt" in args:
    identity = open(args[args.index("-i") + 1]).read()
    public = identity.split("# public key: ")[1].split()[0]
    header, _, payload = open(args[-1], "rb").read().partition(b"\\n")
    if public.encode() not in header.split(b" ", 1)[1].split(b","):
        sys.exit("age: error: no identity matched any of the recipients")
    sys.stdout.buffer.write(payload)
elif "--encrypt" in args:
    recipients = [args[i + 1] for i, a in enumerate(args) if a == "-r"]
    sys.stdout.buffer.write(b"FAKEAGE " + ",".join(recipients).encode() + b"\\n"
                            + sys.stdin.buffer.read())
"""

FAKE_KEYGEN = """\
#!{python}
import sys, uuid
args = sys.argv[1:]
if args[0] == "-o":
    key = uuid.uuid4().hex
    open(args[1], "w").write(f"# public key: age1{{key}}\\nAGE-SECRET-KEY-{{key}}\\n")
elif args[0] == "-y":
    print(open(args[1]).read().split("# public key: ")[1].split()[0])
"""


class VaultTestCase(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb(use_git=False)
        self.vault_path = self.home / ".config/dotinfra/vault.json"

    def cli(self, *argv, stdin=None):
        return run_cli("--root", self.root, "vault", *argv, stdin=stdin)


class FileVaultTest(VaultTestCase):
    def test_roundtrip_and_permissions(self):
        vault = open_vault(load_config(self.root))
        self.assertIsInstance(vault, FileVault)
        self.assertEqual(vault.keys(), [])
        vault.set("b", "2")
        vault.set("a", "1")
        self.assertEqual(vault.keys(), ["a", "b"])
        self.assertEqual(vault.get("a"), "1")
        self.assertEqual(stat.S_IMODE(self.vault_path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(self.vault_path.read_text()), {"a": "1", "b": "2"})
        vault.delete("a")
        with self.assertRaisesRegex(VaultError, "no secret 'a'"):
            vault.get("a")

    def test_corrupt_file(self):
        self.vault_path.parent.mkdir(parents=True)
        self.vault_path.write_text("{not json")
        with self.assertRaisesRegex(VaultError, "cannot read vault"):
            FileVault(self.vault_path).keys()
        self.vault_path.write_text('{"a": 1}')
        with self.assertRaisesRegex(VaultError, "values must be strings"):
            FileVault(self.vault_path).keys()

    def test_unknown_backend(self):
        (self.root / ".dotinfra.toml").write_text('[vault]\nbackend = "cloud"\n')
        with self.assertRaisesRegex(VaultError, "unknown vault backend"):
            open_vault(load_config(self.root))


class VaultCliTest(VaultTestCase):
    def test_set_get_list_rm(self):
        self.assertEqual(self.cli("set", "web1_sudo", stdin="s3cret value\n")[0], 0)
        code, out, _ = self.cli("get", "web1_sudo")
        self.assertEqual((code, out), (0, "s3cret value\n"))
        self.assertEqual(self.cli("list")[1], "web1_sudo\n")
        self.assertEqual(self.cli("rm", "web1_sudo")[0], 0)
        code, _, err = self.cli("get", "web1_sudo")
        self.assertEqual(code, 1)
        self.assertIn("dotinfra vault set web1_sudo", err)

    def test_set_rejects_empty(self):
        code, _, err = self.cli("set", "k", stdin="\n")
        self.assertEqual(code, 1)
        self.assertIn("empty secret", err)

    def test_exec_pipes_secret_and_returns_exit_code(self):
        self.cli("set", "token", stdin="abc\n")
        sink = self.tmp / "received"
        script = f"import sys; open({str(sink)!r}, 'w').write(sys.stdin.read()); sys.exit(3)"
        code, _, _ = self.cli("exec", "token", "--", sys.executable, "-c", script)
        self.assertEqual(code, 3)
        self.assertEqual(sink.read_text(), "abc\n")
        self.assertEqual(self.cli("exec", "token")[0], 1)

    def test_import_legacy_json(self):
        self.cli("set", "b", stdin="old\n")
        legacy = self.tmp / "legacy_vault.json"
        legacy.write_text(json.dumps({"a": "1", "b": "new", "c": "3"}))
        code, out, _ = self.cli("import", legacy)
        self.assertEqual(code, 0)
        self.assertIn("imported 2 key(s)", out)
        self.assertIn("kept existing value for 1 differing key(s): b", out)
        self.assertEqual(self.cli("get", "b")[1], "old\n")
        self.cli("import", legacy, "--overwrite")
        self.assertEqual(self.cli("get", "b")[1], "new\n")
        self.assertEqual(self.cli("list")[1].split(), ["a", "b", "c"])

    def test_import_rejects_nested(self):
        legacy = self.tmp / "nested.json"
        legacy.write_text(json.dumps({"a": {"user": "x"}}))
        code, _, err = self.cli("import", legacy)
        self.assertEqual(code, 1)
        self.assertIn("values must be strings", err)

    def test_loose_permissions_warn(self):
        self.cli("set", "k", stdin="v\n")
        self.assertEqual(self.cli("list")[2], "")
        self.vault_path.chmod(0o644)
        code, out, err = self.cli("list")
        self.assertEqual((code, out), (0, "k\n"))
        self.assertIn("warning", err)
        self.assertIn("chmod 600", err)

    def test_secret_never_in_error_output(self):
        self.cli("set", "k", stdin="supersecret\n")
        self.assertNotIn("supersecret", "".join(self.cli("list")[1:]))
        self.assertNotIn("supersecret", self.cli("rm", "k")[2])


class FakeAgeTest(VaultTestCase):
    """Age plumbing (identity, recipients, migrate, rekey) against a stand-in binary."""

    def setUp(self):
        super().setUp()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, source in (("age", FAKE_AGE), ("age-keygen", FAKE_KEYGEN)):
            path = bin_dir / name
            path.write_text(source.format(python=sys.executable))
            path.chmod(0o755)
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

    def test_migrate_and_rekey(self):
        self.cli("set", "a", stdin="1\n")
        self.cli("set", "b", stdin="2\n")
        code, out, err = self.cli("migrate", "--to", "age")
        self.assertEqual(code, 0, err)
        self.assertIn("migrated 2 secret(s)", out)
        self.assertIn("plaintext vault left", out)
        self.assertIn('backend = "age"', (self.root / ".dotinfra.toml").read_text())
        vault = open_vault(load_config(self.root))
        self.assertIsInstance(vault, AgeVault)
        self.assertEqual(stat.S_IMODE(vault.identity.stat().st_mode), 0o600)
        self.assertEqual(self.cli("get", "b")[1], "2\n")
        self.assertTrue((self.root / "vault.age").read_bytes().startswith(b"FAKEAGE age1"))

        config = self.root / ".dotinfra.toml"
        own = vault.public_key()
        config.write_text(config.read_text().replace(f'age_recipients = ["{own}"]',
                                                     f'age_recipients = ["{own}", "age1laptop"]'))
        code, out, _ = self.cli("rekey")
        self.assertEqual(code, 0)
        self.assertIn("2 recipient(s)", out)
        header = (self.root / "vault.age").read_bytes().split(b"\n")[0]
        self.assertTrue(header.endswith(b",age1laptop"))

    def test_migrate_remove_plaintext_and_refuse_overwrite(self):
        self.cli("set", "a", stdin="1\n")
        code, _, err = self.cli("migrate", "--to", "age", "--remove-plaintext")
        self.assertEqual(code, 0, err)
        self.assertFalse(self.vault_path.exists())
        code, _, err = self.cli("migrate", "--to", "age")
        self.assertIn("already uses the age backend", err)

    def test_identity_is_created_once_recorded_and_printed(self):
        code, out, err = self.cli("identity")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("age1"))
        self.assertIn("created age identity", err)
        self.assertIn("age_recipients", err)
        identity = self.home / ".config/dotinfra/age.key"
        self.assertEqual(stat.S_IMODE(identity.stat().st_mode), 0o600)
        self.assertEqual(load_config(self.root).get("vault", "age_recipients"), [out.strip()])
        code, again, err = self.cli("identity")
        self.assertEqual((code, again, err), (0, out, ""))

    def test_migrate_records_own_key_so_other_devices_writes_stay_readable(self):
        self.cli("set", "a", stdin="1\n")
        self.assertEqual(self.cli("migrate", "--to", "age")[0], 0)
        own = self.cli("identity")[1].strip()
        self.assertEqual(load_config(self.root).get("vault", "age_recipients"), [own])

    def test_missing_identity_explains_the_next_step(self):
        (self.root / ".dotinfra.toml").write_text('[vault]\nbackend = "age"\n')
        (self.root / "vault.age").write_bytes(b"FAKEAGE age1other\n{}")
        code, _, err = self.cli("list")
        self.assertEqual(code, 1)
        self.assertIn("dotinfra vault identity", err)
        self.assertIn("dotinfra vault rekey", err)

    def test_rekey_requires_age(self):
        code, _, err = self.cli("rekey")
        self.assertEqual(code, 1)
        self.assertIn("only applies to the age backend", err)


@unittest.skipUnless(shutil.which("age") and shutil.which("age-keygen"), "age not installed")
class RealAgeTest(VaultTestCase):
    def test_roundtrip(self):
        identity = self.home / "age.key"
        (self.root / ".dotinfra.toml").write_text(textwrap.dedent(f"""\
            [vault]
            backend = "age"
            age_identity = "{identity}"
            """))
        from dotinfra.vault import ensure_age_identity

        self.assertTrue(ensure_age_identity(identity))
        vault = open_vault(load_config(self.root))
        vault.set("k", "v")
        self.assertNotIn(b"\"k\"", (self.root / "vault.age").read_bytes())
        self.assertEqual(open_vault(load_config(self.root)).get("k"), "v")


class VaultMissingAgeTest(VaultTestCase):
    def test_helpful_error(self):
        (self.root / ".dotinfra.toml").write_text('[vault]\nbackend = "age"\n')
        (self.root / "vault.age").write_bytes(b"x")
        identity = self.home / ".config/dotinfra/age.key"
        identity.parent.mkdir(parents=True, exist_ok=True)
        identity.write_text("# public key: age1x\n")
        os.environ["PATH"] = str(self.tmp / "empty-bin")
        code, _, err = self.cli("list")
        self.assertEqual(code, 1)
        self.assertIn("needs `age` on PATH", err)


if __name__ == "__main__":
    unittest.main()
