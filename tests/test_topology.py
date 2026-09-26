"""Monitoring lives on one machine: endpoint resolution, `where`, `setup-server`, roles."""

import io
import json
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from support import IsolatedTestCase, component, git, run_cli
from test_sync import TwoDeviceTestCase
from dotinfra.context import get_context
from dotinfra.monitoring import monitoring_endpoints


def server(cid: str, address: str | None = None) -> str:
    return component(f"id: {cid}\nstatus: active" + (f"\naddress: {address}" if address else ""))


def service(cid: str = "monitoring", **meta) -> str:
    lines = [f"id: {cid}", "status: active"] + [f"{k}: {v}" for k, v in meta.items()]
    return component("\n".join(lines))


class EndpointTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb(use_git=False)
        self.write(self.root, "servers/nas.md", server("nas", "10.10.0.10"))

    def endpoints(self):
        err = io.StringIO()
        with redirect_stderr(err):
            result = monitoring_endpoints(get_context(mock.Mock(root=str(self.root))))
        return result, err.getvalue()

    def test_service_url_and_prometheus_url(self):
        self.write(self.root, "services/monitoring.md", service(
            runs_on="nas", url="https://grafana.example.com",
            prometheus_url="http://10.10.0.10:9091"))
        self.assertEqual(self.endpoints(), (("https://grafana.example.com",
                                             "http://10.10.0.10:9091", "nas"), ""))

    def test_address_falls_back_to_runs_on_server(self):
        self.write(self.root, "services/monitoring.md", service(runs_on="nas"))
        self.assertEqual(self.endpoints()[0], ("http://10.10.0.10:3000",
                                               "http://10.10.0.10:9090", "nas"))

    def test_service_address_wins_over_server(self):
        self.write(self.root, "services/monitoring.md",
                   service(runs_on="nas", address="198.51.100.7"))
        self.assertEqual(self.endpoints()[0][:2], ("http://198.51.100.7:3000",
                                                   "http://198.51.100.7:9090"))

    def test_ipv6_address_is_bracketed(self):
        self.write(self.root, "services/monitoring.md", service(address='"2001:db8::7"'))
        self.assertEqual(self.endpoints()[0][1], "http://[2001:db8::7]:9090")

    def test_explicit_config_wins(self):
        self.write(self.root, "services/monitoring.md", service(runs_on="nas"))
        self.write(self.root, ".dotinfra.local.toml",
                   '[monitoring]\ngrafana_url = "http://10.99.0.2:3000/"\n')
        self.assertEqual(self.endpoints()[0], ("http://10.99.0.2:3000",
                                               "http://10.10.0.10:9090", "nas"))

    def test_custom_service_id(self):
        self.write(self.root, "services/obs.md", service("obs", runs_on="nas"))
        self.write(self.root, ".dotinfra.local.toml", '[monitoring]\nservice = "obs"\n')
        self.assertEqual(self.endpoints()[0][2], "nas")

    def test_nothing_known_means_localhost_with_warning(self):
        (grafana, prometheus, host), err = self.endpoints()
        self.assertEqual((grafana, prometheus, host),
                         ("http://localhost:3000", "http://localhost:9090", None))
        self.assertIn("no component 'monitoring'", err)

    def test_grafana_client_uses_resolution(self):
        from dotinfra import grafana

        self.write(self.root, "services/monitoring.md", service(runs_on="nas"))
        ctx = get_context(mock.Mock(root=str(self.root)))
        with mock.patch.object(type(ctx), "secret", lambda self, key: "pw"):
            self.assertEqual(grafana.client_from_context(ctx).url, "http://10.10.0.10:3000")


class WhereAndSetupTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb()
        self.write(self.root, "servers/nas.md",
                   component("id: nas\nstatus: active\naddress: 10.10.0.10\n"
                             "metrics: [node:9100]"))
        self.write(self.root, "services/monitoring.md", service(runs_on="nas"))

    def test_where(self):
        code, out, err = run_cli("--root", self.root, "monitoring", "where")
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"host\s+nas")
        self.assertRegex(out, r"grafana\s+http://10.10.0.10:3000")
        self.assertRegex(out, r"prometheus\s+http://10.10.0.10:9090")
        self.assertRegex(out, r"this device\s+client")
        self.assertNotIn("check", out)

    def test_where_check(self):
        calls = []

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def urlopen(request, timeout=None):
            calls.append((request.full_url, timeout))
            if "9090" in request.full_url:
                raise OSError("connection refused")
            return Response()

        with mock.patch("urllib.request.urlopen", urlopen):
            code, out, _ = run_cli("--root", self.root, "monitoring", "where", "--check")
        self.assertEqual(code, 0)
        self.assertIn(("http://10.10.0.10:3000/api/health", 3.0), calls)
        self.assertRegex(out, r"grafana check\s+ok \(HTTP 200\)")
        self.assertRegex(out, r"prometheus check\s+unreachable")

    def test_setup_server(self):
        bundle = self.tmp / "bundle"
        code, out, err = run_cli("--root", self.root, "monitoring", "setup-server",
                                 "--bundle-dir", str(bundle))
        self.assertEqual(code, 0, err)
        local = (self.root / ".dotinfra.local.toml").read_text()
        self.assertIn('role = "server"', local)
        self.assertIn(str(bundle), local)
        self.assertTrue((bundle / "docker-compose.yml").is_file())
        self.assertTrue((bundle / "targets" / "node.json").is_file())
        self.assertIn("docker compose up -d", out)
        self.assertIn("dotinfra timer install", out)
        self.assertNotIn(".dotinfra.local.toml", git(self.root, "status", "--porcelain"))
        code, out, _ = run_cli("--root", self.root, "monitoring", "where")
        self.assertRegex(out, r"this device\s+server")

    def test_client_is_warned_before_rendering(self):
        self.write(self.root, ".dotinfra.local.toml",
                   f'[monitoring]\nbundle_dir = "{self.tmp / "b"}"\n')
        code, _, err = run_cli("--root", self.root, "monitoring", "targets")
        self.assertEqual(code, 0)
        self.assertIn("the monitoring stack runs on 'nas'", err)
        code, _, err = run_cli("--root", self.root, "monitoring", "render")
        self.assertIn("runs on 'nas'", err)
        code, _, err = run_cli("--root", self.root, "monitoring", "targets", "--output",
                               self.tmp / "t")
        self.assertNotIn("runs on", err)
        code, _, err = run_cli("--root", self.root, "monitoring", "targets", "--force")
        self.assertNotIn("runs on", err)

    def test_invalid_role(self):
        self.write(self.root, ".dotinfra.local.toml", '[monitoring]\nrole = "primary"\n')
        code, _, err = run_cli("--root", self.root, "monitoring", "where")
        self.assertEqual(code, 1)
        self.assertIn('role must be "server" or "client"', err)


class ServerRoleSyncTest(TwoDeviceTestCase):
    def test_server_regenerates_targets_after_merge(self):
        bundle = self.tmp / "bundle"
        self.write(self.b, ".dotinfra.local.toml",
                   f'[monitoring]\nrole = "server"\nbundle_dir = "{bundle}"\n')
        self.assertSync(self.b)
        self.write(self.a, "servers/gpu1.md",
                   component("id: gpu1\nstatus: active\naddress: 10.10.0.20\n"
                             "metrics: [node:9100, dcgm:9400]"))
        self.assertSync(self.a)
        out = self.assertSync(self.b)
        self.assertIn(f"monitoring targets refreshed in {bundle / 'targets'}", out)
        groups = json.loads((bundle / "targets" / "dcgm.json").read_text())
        self.assertEqual(groups[0]["targets"], ["10.10.0.20:9400"])
        # nothing new: no second refresh message
        self.assertNotIn("targets refreshed", self.assertSync(self.b))
        # a client never writes targets
        self.assertFalse((Path.home() / "dotinfra-monitoring").exists())
        self.assertNotIn("targets refreshed", self.assertSync(self.a))


if __name__ == "__main__":
    import unittest

    unittest.main()
