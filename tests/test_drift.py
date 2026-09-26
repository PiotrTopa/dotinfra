import json
import shutil
import subprocess
import unittest
from datetime import date
from unittest import mock

from support import IsolatedTestCase, component, run_cli
from dotinfra import DotinfraError
from dotinfra.drift import PROBE_SCRIPT, compare, parse_probe, ssh_command
from dotinfra.frontmatter import parse
from dotinfra.model import by_id, load_cmdb

PROBE_OUTPUT = """\
hostname=web1
kernel=Linux 6.1.0-25-amd64
arch=x86_64
os=Debian GNU/Linux 12 (bookworm)
cpus=4
mem_kb=16318412
ips=10.0.0.5 172.17.0.1
"""


class DriftTestCase(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb(use_git=False)
        self.write(self.root, "servers/hub.md", component("""\
            status: active
            address: 10.99.0.1
            ssh:
              user: alice
              host: 203.0.113.10
              port: 2222
            """))
        self.write(self.root, "servers/gw.md", component("""\
            status: active
            address: 10.10.0.1
            ssh:
              user: root
              jump: hub
            """))
        self.write(self.root, "servers/web1.md", component("""\
            status: active     # lifecycle
            address: 10.0.0.5
            os: Debian 12
            ssh:
              user: deploy
              jump: gw
              key: ~/.ssh/id_web
            updated: 2026-01-01
            """, "# web1\n"))
        self.write(self.root, "servers/planned.md", component(
            "status: planned\naddress: 10.0.0.9\nssh:\n  user: x"))

    def components(self):
        return by_id(load_cmdb(self.root))


class ProbeTest(DriftTestCase):
    def test_ssh_command_follows_jump_chain(self):
        cmd = ssh_command(self.components()["web1"], self.components())
        self.assertEqual(cmd, ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                               "-i", "~/.ssh/id_web", "-J", "alice@203.0.113.10:2222,root@10.10.0.1",
                               "deploy@10.0.0.5", "sh", "-s"])
        hub = ssh_command(self.components()["hub"], self.components())
        self.assertIn("-p", hub)
        self.assertNotIn("-J", hub)

    def test_jump_loop_detected(self):
        self.write(self.root, "servers/l1.md", component("status: active\naddress: a\n"
                                                         "ssh:\n  jump: l2"))
        self.write(self.root, "servers/l2.md", component("status: active\naddress: b\n"
                                                         "ssh:\n  jump: l1"))
        with self.assertRaisesRegex(DotinfraError, "loop"):
            ssh_command(self.components()["l1"], self.components())

    def test_parse_probe(self):
        facts = parse_probe(PROBE_OUTPUT, today=date(2026, 9, 26))
        self.assertEqual(facts, {"hostname": "web1", "kernel": "Linux 6.1.0-25-amd64",
                                 "arch": "x86_64", "os": "Debian GNU/Linux 12 (bookworm)",
                                 "cpus": 4, "mem_gb": 15.6, "ips": ["10.0.0.5", "172.17.0.1"],
                                 "probed": "2026-09-26"})

    @unittest.skipUnless(shutil.which("sh"), "no POSIX sh")
    def test_probe_script_runs_locally(self):
        result = subprocess.run(["sh", "-s"], input=PROBE_SCRIPT, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        facts = parse_probe(result.stdout)
        self.assertTrue(facts["hostname"])
        self.assertTrue(facts["kernel"])
        self.assertIsInstance(facts["cpus"], int)

    def test_compare(self):
        web1 = self.components()["web1"]
        facts = parse_probe(PROBE_OUTPUT)
        self.assertEqual(compare(web1, facts), [])
        facts |= {"os": "Debian GNU/Linux 13 (trixie)", "ips": ["10.0.0.7"]}
        self.assertEqual([d.field for d in compare(web1, facts)], ["os", "address"])

    def test_os_point_release_is_not_drift(self):
        web1 = self.components()["web1"]
        web1.meta["os"] = "Ubuntu 24.04 LTS"
        facts = parse_probe(PROBE_OUTPUT) | {"os": "Ubuntu 24.04.1 LTS"}
        self.assertEqual(compare(web1, facts), [])
        facts["os"] = "Ubuntu 24.10"
        self.assertEqual([d.field for d in compare(web1, facts)], ["os"])

    def test_unsafe_ssh_values_are_refused(self):
        self.write(self.root, "servers/dash.md", component(
            "status: active\naddress: 10.0.0.8\nssh:\n  user: -oProxyCommand=evil"))
        with self.assertRaisesRegex(DotinfraError, "unsafe"):
            ssh_command(self.components()["dash"], self.components())


class DriftCliTest(DriftTestCase):
    def run_drift(self, *argv, output=PROBE_OUTPUT, error=None):
        def fake(cmd):
            if error:
                raise DotinfraError(error)
            return output
        with mock.patch("dotinfra.drift.run_probe", side_effect=fake) as probe:
            result = run_cli("--root", self.root, "drift", *argv)
        return result, probe

    def test_clean(self):
        (code, out, _), probe = self.run_drift("web1")
        self.assertEqual(code, 0)
        self.assertIn("web1: OK (web1, Debian GNU/Linux 12 (bookworm), 4 cpu, 15.6 GB)", out)
        self.assertEqual(probe.call_args[0][0][-3:], ["deploy@10.0.0.5", "sh", "-s"])
        cache = json.loads((self.root / ".dotinfra/state/facts/web1.json").read_text())
        self.assertEqual(cache["facts"]["hostname"], "web1")

    def test_default_targets_skip_planned(self):
        (code, out, _), probe = self.run_drift()
        self.assertEqual(probe.call_count, 3)
        self.assertNotIn("planned", out)

    def test_update_writes_facts_and_keeps_comments(self):
        drifted = PROBE_OUTPUT.replace("12 (bookworm)", "13 (trixie)")
        (code, out, _), _ = self.run_drift("web1", "--update", output=drifted)
        self.assertEqual(code, 1)
        self.assertIn("os: recorded 'Debian 12', observed 'Debian GNU/Linux 13 (trixie)'", out)
        text = (self.root / "servers/web1.md").read_text()
        self.assertIn("status: active     # lifecycle", text)
        meta, _ = parse(text)
        self.assertEqual(meta["os"], "Debian GNU/Linux 13 (trixie)")
        self.assertEqual(meta["updated"], date.today().isoformat())
        self.assertEqual(meta["facts"]["cpus"], 4)
        self.assertEqual(meta["facts"]["ips"], ["10.0.0.5", "172.17.0.1"])
        # recorded facts are now compared on the next run
        (code, out, _), _ = self.run_drift("web1", output=drifted.replace("cpus=4", "cpus=8"))
        self.assertEqual(code, 1)
        self.assertIn("facts.cpus: recorded 4, observed 8", out)

    def test_unreachable_and_json(self):
        (code, out, _), _ = self.run_drift("web1", "--json", error="Connection timed out")
        self.assertEqual(code, 1)
        report = json.loads(out)[0]
        self.assertEqual((report["id"], report["ok"], report["error"]),
                         ("web1", False, "Connection timed out"))

    def test_unknown_id(self):
        (code, _, err), _ = self.run_drift("nope")
        self.assertEqual(code, 1)
        self.assertIn("no component with id 'nope'", err)


if __name__ == "__main__":
    unittest.main()
