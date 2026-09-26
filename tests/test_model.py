import unittest

from support import IsolatedTestCase, component
from dotinfra.frontmatter import FrontmatterError
from dotinfra.model import as_list, by_id, load_cmdb, parse_metric


class LoadCmdbTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "cmdb"
        self.write(self.root, "servers/Web1.md", component(
            "status: active\nmetrics: [node:9100, bad, dcgm:9400]\ntags: gpu",
            "Intro\n\n# Web one\n"))
        self.write(self.root, "servers/alpha.md", component("status: active", "no heading\n"))
        self.write(self.root, "networks/lan.md", component("id: lan\ntitle: Home LAN\nkind: network"))
        self.write(self.root, "servers/notes.local.md", component("status: active"))
        self.write(self.root, "README.md", "# not a component\n")
        self.write(self.root, "misc/other.md", component("status: active"))

    def test_defaults_and_order(self):
        components = load_cmdb(self.root)
        self.assertEqual([(c.kind, c.id) for c in components],
                         [("network", "lan"), ("server", "alpha"), ("server", "web1")])
        web = by_id(components)["web1"]
        self.assertEqual(web.meta["id"], "web1")
        self.assertEqual(web.meta["kind"], "server")
        self.assertEqual(web.title, "Web one")
        self.assertEqual(by_id(components)["alpha"].title, "alpha")
        self.assertEqual(by_id(components)["lan"].title, "Home LAN")
        self.assertEqual(web.rel(), "servers/Web1.md")
        self.assertTrue(web.path.is_absolute())

    def test_properties(self):
        web = by_id(load_cmdb(self.root))["web1"]
        self.assertEqual(web.metrics, [("node", 9100), ("dcgm", 9400)])
        self.assertEqual(web.tags, ["gpu"])
        self.assertEqual(web.status, "active")
        self.assertIsNone(web.address)
        self.assertEqual(web.ssh, {})
        self.assertEqual(web.line_of("status"), 2)

    def test_parse_errors_recorded_or_raised(self):
        self.write(self.root, "devices/broken.md", "---\na: |\n  x\n---\n")
        components = load_cmdb(self.root)
        self.assertEqual(len(components), 3)
        self.assertEqual(len(load_cmdb.errors), 1)
        self.assertIn("devices/broken.md:2", load_cmdb.errors[0])
        with self.assertRaises(FrontmatterError):
            load_cmdb(self.root, strict=True)

    def test_empty_root(self):
        self.assertEqual(load_cmdb(self.tmp / "missing"), [])


class HelpersTest(unittest.TestCase):
    def test_parse_metric(self):
        self.assertEqual(parse_metric("node:9100"), ("node", 9100))
        for bad in ("node", ":9100", "node:x", "node:0", "node:70000", 9100):
            self.assertIsNone(parse_metric(bad), bad)

    def test_as_list(self):
        self.assertEqual(as_list(None), [])
        self.assertEqual(as_list("a"), ["a"])
        self.assertEqual(as_list(["a", "b"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
