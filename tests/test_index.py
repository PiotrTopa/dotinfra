import unittest

from support import IsolatedTestCase, component, run_cli
from dotinfra.index import is_stale, render_index, write_index
from dotinfra.model import load_cmdb


class IndexTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb(use_git=False)
        self.write(self.root, "servers/web1.md", component(
            "status: active\naddress: 10.0.0.5\nrole: web | proxy\ntags: [fleet, web]"))
        self.write(self.root, "networks/lan.md", component("status: planned"))

    def test_render(self):
        text = render_index(load_cmdb(self.root), "lab")
        self.assertTrue(text.startswith("# lab — infrastructure index\n"))
        self.assertIn("2 component(s)", text)
        self.assertLess(text.index("## Servers"), text.index("## Networks"))
        self.assertIn("| [web1](servers/web1.md) | active | 10.0.0.5 | web \\| proxy | fleet, web |",
                      text)
        self.assertNotIn("## Domains", text)
        self.assertEqual(text, render_index(load_cmdb(self.root), "lab"))  # deterministic

    def test_write_and_stale(self):
        self.assertTrue(is_stale(self.root, "cmdb"))
        self.assertTrue(write_index(self.root, "cmdb"))
        self.assertFalse(write_index(self.root, "cmdb"))
        self.assertFalse(is_stale(self.root, "cmdb"))

    def test_cli_check(self):
        code, out, _ = run_cli("--root", self.root, "index", "--check")
        self.assertEqual(code, 1)
        self.assertIn("stale", out)
        self.assertEqual(run_cli("--root", self.root, "index")[0], 0)
        self.assertEqual(run_cli("--root", self.root, "index", "--check")[0], 0)


if __name__ == "__main__":
    unittest.main()
