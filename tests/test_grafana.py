import base64
import io
import json
import unittest
import urllib.error
from unittest import mock

from dotinfra import DotinfraError, grafana


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeUrlopen:
    """Records requests; replies with queued JSON bodies (or exceptions)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode()) if req.data else None
        self.requests.append({"method": req.get_method(), "url": req.full_url,
                              "headers": {k.lower(): v for k, v in req.header_items()},
                              "body": body})
        reply = self.replies.pop(0) if self.replies else {}
        if isinstance(reply, Exception):
            raise reply
        return FakeResponse(json.dumps(reply).encode())


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.dash = grafana.build_fleet_dashboard(name="lab")

    def test_roundtrips_as_json(self):
        text = grafana.dashboard_json(self.dash)
        self.assertEqual(json.loads(text), self.dash)

    def test_identity(self):
        self.assertEqual(self.dash["uid"], "dotinfra-fleet")
        self.assertEqual(self.dash["title"], "Fleet Overview — lab")
        self.assertIn("fleet", self.dash["tags"])

    def test_host_variable_comes_from_prometheus(self):
        variables = {v["name"]: v for v in self.dash["templating"]["list"]}
        host = variables["host"]
        self.assertEqual(host["type"], "query")
        self.assertEqual(host["definition"], 'label_values(up{role="fleet"}, host)')
        self.assertTrue(host["multi"] and host["includeAll"])
        self.assertEqual(host["options"], [])  # nothing hard-coded
        ds = variables["datasource"]
        self.assertEqual(ds["current"]["value"], grafana.DATASOURCE_UID)

    def test_repeated_row_and_layout(self):
        rows = [p for p in self.dash["panels"] if p["type"] == "row"]
        self.assertEqual(rows[0]["repeat"], "host")
        ids = [p["id"] for p in self.dash["panels"]]
        self.assertEqual(len(ids), len(set(ids)))
        for p in self.dash["panels"]:
            g = p["gridPos"]
            self.assertLessEqual(g["x"] + g["w"], 24, p["title"])
        # every per-host line fills the full width
        for _h, line in grafana.ROW_LAYOUT:
            self.assertEqual(sum(w for _n, w in line), 24)

    def test_all_queries_use_datasource_variable_and_host_filter(self):
        for p in self.dash["panels"]:
            for t in p.get("targets", []):
                self.assertEqual(t["datasource"]["uid"], "${datasource}")
        for name, (expr, *_rest) in grafana.QUERIES.items():
            self.assertIn('host=~"$host"', expr, name)

    def test_gpu_panels_degrade_gracefully(self):
        by_title = {p["title"]: p for p in self.dash["panels"]}
        for title in ("GPU", "VRAM", "GPU temp", "GPU power"):
            self.assertEqual(by_title[title]["fieldConfig"]["defaults"]["noValue"], "no GPU")
        self.assertIn("DCGM_FI_DEV_GPU_UTIL", by_title["GPU"]["targets"][0]["expr"])
        self.assertIn(" or ", by_title["GPU"]["targets"][0]["expr"])

    def test_event_annotations(self):
        names = [a["name"] for a in self.dash["annotations"]["list"]]
        for etype in grafana.EVENT_TYPES:
            self.assertIn(f"Events: {etype}", names)
        outage = next(a for a in self.dash["annotations"]["list"] if a["name"] == "Events: outage")
        self.assertEqual(outage["target"]["tags"], ["dotinfra", "type:outage"])

    def test_balanced_braces_in_queries(self):
        for name, (expr, *_rest) in grafana.QUERIES.items():
            self.assertEqual(expr.count("{"), expr.count("}"), name)
            self.assertEqual(expr.count("("), expr.count(")"), name)


class ClientTest(unittest.TestCase):
    def test_basic_auth_and_push(self):
        fake = FakeUrlopen({"status": "success", "url": "/d/dotinfra-fleet/x"})
        client = grafana.GrafanaClient("http://grafana.example.com:3000/", user="admin", password="pw")
        with mock.patch("urllib.request.urlopen", fake):
            dash = dict(grafana.build_fleet_dashboard(), id=42)
            res = client.push_dashboard(dash, folder_uid="dotinfra")
        self.assertEqual(res["status"], "success")
        req = fake.requests[0]
        self.assertEqual(req["method"], "POST")
        self.assertEqual(req["url"], "http://grafana.example.com:3000/api/dashboards/db")
        expected = "Basic " + base64.b64encode(b"admin:pw").decode()
        self.assertEqual(req["headers"]["authorization"], expected)
        self.assertTrue(req["body"]["overwrite"])
        self.assertEqual(req["body"]["folderUid"], "dotinfra")
        self.assertNotIn("id", req["body"]["dashboard"])

    def test_token_auth(self):
        fake = FakeUrlopen([])
        client = grafana.GrafanaClient("http://g.example.com", token="glsa_x")
        with mock.patch("urllib.request.urlopen", fake):
            client.request("GET", "/api/folders")
        self.assertEqual(fake.requests[0]["headers"]["authorization"], "Bearer glsa_x")

    def test_ensure_folder_existing_and_new(self):
        fake = FakeUrlopen([{"title": "Fleet", "uid": "abc"}])
        client = grafana.GrafanaClient("http://g.example.com", token="t")
        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(client.ensure_folder("Fleet"), "abc")
        fake = FakeUrlopen([], {"uid": "dotinfra"})
        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(client.ensure_folder("Fleet", "dotinfra"), "dotinfra")
        self.assertEqual(fake.requests[1]["body"], {"title": "Fleet", "uid": "dotinfra"})

    def test_http_error_becomes_grafana_error(self):
        err = urllib.error.HTTPError("http://g/api", 401, "Unauthorized", {}, io.BytesIO(b'{"message":"bad"}'))
        fake = FakeUrlopen(err)
        client = grafana.GrafanaClient("http://g.example.com", token="t")
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(grafana.GrafanaError) as cm:
                client.request("GET", "/api/folders")
        self.assertIn("401", str(cm.exception))

    def test_unreachable(self):
        fake = FakeUrlopen(urllib.error.URLError("connection refused"))
        client = grafana.GrafanaClient("http://g.example.com", token="t")
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(grafana.GrafanaError) as cm:
                client.request("GET", "/api/health")
        self.assertIn("cannot reach", str(cm.exception))


class FakeConfig:
    def __init__(self, data):
        self.data = data

    def get(self, section, key, default=None):
        v = self.data.get(section, {}).get(key)
        return default if v is None else v


class FakeCtx:
    def __init__(self, monitoring, secrets):
        self.config = FakeConfig({"monitoring": monitoring})
        self.secrets = secrets
        self.asked = []

    def components(self):
        return []

    def secret(self, key):
        self.asked.append(key)
        if key not in self.secrets:
            raise DotinfraError(f"no secret {key!r} in the vault")
        return self.secrets[key]


class ClientFromContextTest(unittest.TestCase):
    def test_password_from_vault(self):
        ctx = FakeCtx({"grafana_url": "http://g.example.com", "grafana_user": "alice",
                       "grafana_password_key": "gf_pw"}, {"gf_pw": "s3cret"})
        client = grafana.client_from_context(ctx)
        self.assertEqual(ctx.asked, ["gf_pw"])
        self.assertEqual(client.auth, "Basic " + base64.b64encode(b"alice:s3cret").decode())

    def test_token_key_preferred(self):
        ctx = FakeCtx({"grafana_token_key": "gf_token"}, {"gf_token": "glsa_1"})
        self.assertEqual(grafana.client_from_context(ctx).auth, "Bearer glsa_1")

    def test_missing_secret_is_friendly(self):
        ctx = FakeCtx({}, {})
        with self.assertRaises(grafana.GrafanaError) as cm:
            grafana.client_from_context(ctx)
        self.assertIn("dotinfra vault set grafana_password", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
