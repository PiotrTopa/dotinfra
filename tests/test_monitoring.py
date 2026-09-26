import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from dotinfra import monitoring


@dataclass
class FakeComponent:
    id: str
    kind: str = "server"
    meta: dict = field(default_factory=dict)

    @property
    def status(self):
        return self.meta.get("status")

    @property
    def tags(self):
        return list(self.meta.get("tags") or [])

    @property
    def address(self):
        return self.meta.get("address")

    @property
    def ssh(self):
        return self.meta.get("ssh") or {}

    @property
    def metrics(self):
        out = []
        for entry in self.meta.get("metrics") or []:
            job, port = entry.split(":")
            out.append((job, int(port)))
        return out


def comp(id, **meta):
    kind = meta.pop("kind", "server")
    meta.setdefault("status", "active")
    return FakeComponent(id=id, kind=kind, meta=meta)


FLEET = [
    comp("gpu1", tags=["fleet", "gpu"], address="10.10.0.21", metrics=["node:9100", "dcgm:9400"]),
    comp("nas", address="10.10.0.10", metrics=["node:9100"]),
    comp("old", status="retired", address="10.10.0.99", metrics=["node:9100"]),
    comp("planned", status="planned", address="10.10.0.98", metrics=["node:9100"]),
    comp("sick", status="degraded", tags=["fleet"], address="10.10.0.22", metrics=["node:9100"]),
    comp("noaddr", metrics=["node:9100"]),
    comp("viassh", ssh={"host": "vps.example.net", "user": "alice"}, metrics=["node:9100"]),
    comp("router", kind="router", address="10.10.0.1", metrics=["snmp:9116"]),
    comp("docs-only", address="10.10.0.50"),
]


class BuildTargetsTest(unittest.TestCase):
    def setUp(self):
        self.targets, self.warnings = monitoring.build_targets(FLEET)

    def test_jobs_sorted_and_grouped(self):
        self.assertEqual(list(self.targets), ["dcgm", "node", "snmp"])
        hosts = [g["labels"]["host"] for g in self.targets["node"]]
        self.assertEqual(hosts, sorted(hosts))

    def test_status_filter(self):
        hosts = {g["labels"]["host"] for g in self.targets["node"]}
        self.assertIn("sick", hosts)
        self.assertNotIn("old", hosts)
        self.assertNotIn("planned", hosts)

    def test_labels(self):
        g = next(g for g in self.targets["dcgm"] if g["labels"]["host"] == "gpu1")
        self.assertEqual(g["targets"], ["10.10.0.21:9400"])
        self.assertEqual(g["labels"], {"job": "dcgm", "host": "gpu1", "instance": "gpu1:9400",
                                       "role": "fleet", "kind": "server"})
        nas = next(g for g in self.targets["node"] if g["labels"]["host"] == "nas")
        self.assertEqual(nas["labels"]["role"], "infra")
        router = self.targets["snmp"][0]
        self.assertEqual(router["labels"]["kind"], "router")

    def test_ssh_host_fallback_and_missing_address(self):
        via = next(g for g in self.targets["node"] if g["labels"]["host"] == "viassh")
        self.assertEqual(via["targets"], ["vps.example.net:9100"])
        self.assertTrue(any("noaddr" in w for w in self.warnings))
        self.assertNotIn("noaddr", {g["labels"]["host"] for g in self.targets["node"]})

    def test_ipv6_bracketed(self):
        targets, _ = monitoring.build_targets([comp("v6", address="2001:db8::5", metrics=["node:9100"])])
        self.assertEqual(targets["node"][0]["targets"], ["[2001:db8::5]:9100"])

    def test_deterministic_json(self):
        a = monitoring.render_targets_json(self.targets["node"])
        b = monitoring.render_targets_json(monitoring.build_targets(list(reversed(FLEET)))[0]["node"])
        self.assertEqual(a, b)
        self.assertIsInstance(json.loads(a), list)


class WriteTargetsTest(unittest.TestCase):
    def test_write_and_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "stale.json").write_text("[]")
            (out / "custom-extra.json").write_text("[]")
            (out / "unrelated.json").write_text('{"not": "a file_sd file"}')  # never ours
            targets, _ = monitoring.build_targets(FLEET)
            written, removed = monitoring.write_targets(targets, out)
            self.assertEqual(sorted(p.name for p in written), ["dcgm.json", "node.json", "snmp.json"])
            self.assertEqual([p.name for p in removed], ["stale.json"])
            self.assertTrue((out / "custom-extra.json").exists())
            self.assertTrue((out / "unrelated.json").exists())
            data = json.loads((out / "node.json").read_text())
            self.assertEqual(len(data), 4)  # gpu1, nas, sick, viassh
            self.assertFalse(list(out.glob(".*.tmp")))


class RenderBundleTest(unittest.TestCase):
    def test_render_complete_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bundle"
            report = monitoring.render_bundle(FLEET, out, name="lab")
            for rel in ("docker-compose.yml", "prometheus/prometheus.yml",
                        "grafana/provisioning/datasources/dotinfra.yml",
                        "grafana/provisioning/dashboards/dotinfra.yml",
                        "targets/node.json", "targets/dcgm.json", ".env.example", "README.md"):
                self.assertTrue((out / rel).is_file(), rel)
            dash = json.loads((out / "grafana/dashboards/dotinfra-fleet.json").read_text())
            self.assertEqual(dash["title"], "Fleet Overview — lab")
            self.assertEqual(report["jobs"], {"dcgm": 1, "node": 4, "snmp": 1})

            compose = (out / "docker-compose.yml").read_text()
            self.assertIn("prometheus_data:/prometheus", compose)
            self.assertIn("--storage.tsdb.path=/prometheus", compose)
            self.assertIn("./prometheus:/etc/prometheus:ro", compose)
            self.assertIn("./targets:/etc/dotinfra/targets:ro", compose)
            prom = (out / "prometheus/prometheus.yml").read_text()
            self.assertIn("file_sd_configs", prom)
            self.assertIn("/etc/dotinfra/targets/*.json", prom)
            ds = (out / "grafana/provisioning/datasources/dotinfra.yml").read_text()
            self.assertIn("uid: dotinfra-prometheus", ds)

    def test_render_keeps_local_edits_unless_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            monitoring.render_bundle(FLEET, out)
            compose = out / "docker-compose.yml"
            compose.write_text("# my edits\n")
            report = monitoring.render_bundle(FLEET, out)
            self.assertEqual(compose.read_text(), "# my edits\n")
            self.assertIn(compose, report["kept"])
            monitoring.render_bundle(FLEET, out, force=True)
            self.assertIn("prometheus_data:/prometheus", compose.read_text())


def _core_available():
    try:
        import dotinfra.cli  # noqa: F401
        import dotinfra.context  # noqa: F401
        return True
    except ImportError:
        return False


NODE_MD = """---
id: box1
status: active
role: test box
tags: [fleet]
address: 10.10.0.31
metrics: [node:9100]
updated: 2026-09-20
---

# box1
"""


@unittest.skipUnless(_core_available(), "core CLI not available")
class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "cmdb"
        (self.root / "servers").mkdir(parents=True)
        (self.root / ".dotinfra.toml").write_text('[cmdb]\nname = "cli-test"\n')
        (self.root / "servers" / "box1.md").write_text(NODE_MD)
        self._env = {k: os.environ.get(k) for k in ("DOTINFRA_ROOT", "HOME")}
        os.environ["DOTINFRA_ROOT"] = str(self.root)
        os.environ["HOME"] = self.tmp.name

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def run_cli(self, *argv):
        from dotinfra.cli import main

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_targets_cli(self):
        outdir = Path(self.tmp.name) / "t"
        code, out, _ = self.run_cli("monitoring", "targets", "--output", str(outdir))
        self.assertEqual(code, 0)
        data = json.loads((outdir / "node.json").read_text())
        self.assertEqual(data[0]["targets"], ["10.10.0.31:9100"])
        self.assertEqual(data[0]["labels"]["role"], "fleet")

    def test_render_cli(self):
        outdir = Path(self.tmp.name) / "bundle"
        code, out, _ = self.run_cli("monitoring", "render", "--output", str(outdir))
        self.assertEqual(code, 0, out)
        self.assertTrue((outdir / "targets" / "node.json").is_file())
        dash = json.loads((outdir / "grafana/dashboards/dotinfra-fleet.json").read_text())
        self.assertEqual(dash["title"], "Fleet Overview — cli-test")


if __name__ == "__main__":
    unittest.main()
