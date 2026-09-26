import unittest

from support import IsolatedTestCase, component, run_cli
from dotinfra.model import load_cmdb
from dotinfra.sshconfig import render_ssh_config


class SshConfigTest(IsolatedTestCase):
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
            """, "# hub\n"))
        self.write(self.root, "servers/nas.md", component("""\
            status: active
            address: 10.10.0.10
            ssh:
              user: alice
              jump: hub
              key: ~/.ssh/id_nas
            """, "# nas\n"))
        self.write(self.root, "servers/old.md", component(
            "status: retired\naddress: 10.0.0.1\nssh:\n  user: root"))
        self.write(self.root, "servers/noaccess.md", component("status: active\naddress: 1.2.3.4"))
        self.write(self.root, "servers/lost.md", component(
            "status: active\naddress: 10.0.0.2\nssh:\n  jump: ghost"))

    def test_blocks(self):
        text, warnings = render_ssh_config(load_cmdb(self.root), self.root)
        self.assertIn("Host hub\n    HostName 203.0.113.10\n    User alice\n    Port 2222\n", text)
        self.assertIn("Host nas\n    HostName 10.10.0.10\n    User alice\n"
                      "    IdentityFile ~/.ssh/id_nas\n    IdentitiesOnly yes\n"
                      "    ProxyJump hub\n", text)
        self.assertNotIn("Host old", text)
        self.assertNotIn("Host noaccess", text)
        self.assertIn("Host lost\n    HostName 10.0.0.2\n", text)
        self.assertNotIn("ProxyJump ghost", text)
        self.assertEqual(len(warnings), 1)
        self.assertIn("ghost", warnings[0])

    def test_unsafe_values_are_skipped_with_a_warning(self):
        # A quoted "\n" in frontmatter would otherwise smuggle a ProxyCommand line
        # into ssh_config; a leading "-" would become an ssh option in `dotinfra drift`.
        self.write(self.root, "servers/evil.md", component(
            'status: active\naddress: 10.0.0.3\nssh:\n  host: "10.0.0.3\\nProxyCommand evil"'))
        self.write(self.root, "servers/dash.md", component(
            "status: active\naddress: -oProxyCommand=evil\nssh:\n  user: alice"))
        text, warnings = render_ssh_config(load_cmdb(self.root), self.root)
        self.assertNotIn("ProxyCommand evil", text)
        self.assertNotIn("Host evil", text)
        self.assertNotIn("Host dash", text)
        self.assertEqual(len([w for w in warnings if "unsafe" in w]), 2)

    def test_cli_output_file(self):
        target = self.home / ".ssh/config.d/dotinfra"
        code, out, err = run_cli("--root", self.root, "ssh-config", "--output", target)
        self.assertEqual(code, 0)
        self.assertIn("wrote 3 host(s)", out)
        self.assertIn("ghost", err)
        self.assertIn("Host nas", target.read_text())


if __name__ == "__main__":
    unittest.main()
