import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from dotinfra import DotinfraError, events, grafana

NOW = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


class ParseTimeTest(unittest.TestCase):
    def test_now(self):
        self.assertEqual(events.parse_time("now", NOW), NOW_MS)

    def test_relative(self):
        self.assertEqual(events.parse_time("-2h", NOW), NOW_MS - 2 * 3600_000)
        self.assertEqual(events.parse_time("30m ago", NOW), NOW_MS - 30 * 60_000)
        self.assertEqual(events.parse_time("1d", NOW), NOW_MS - 86400_000)

    def test_iso_utc(self):
        expected = int(datetime(2026, 9, 26, 1, 55, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertEqual(events.parse_time("2026-09-26T01:55:00Z"), expected)
        self.assertEqual(events.parse_time("2026-09-26T01:55Z"), expected)
        self.assertEqual(events.parse_time("2026-09-26T03:55:00+02:00"), expected)

    def test_naive_is_local(self):
        local = datetime(2026, 9, 26, 10, 0).astimezone()
        self.assertEqual(events.parse_time("2026-09-26 10:00"), int(local.timestamp() * 1000))

    def test_garbage(self):
        with self.assertRaises(ValueError):
            events.parse_time("yesterday-ish")


class PayloadTest(unittest.TestCase):
    def test_build_event(self):
        p = events.build_event("nas", "outage", "  disk died ", 1000, 5000)
        self.assertEqual(p, {"time": 1000, "timeEnd": 5000, "text": "disk died",
                             "tags": ["dotinfra", "host:nas", "type:outage"]})

    def test_validation(self):
        with self.assertRaises(ValueError):
            events.build_event("nas", "party", "x", 1)
        with self.assertRaises(ValueError):
            events.build_event("nas", "change", "   ", 1)
        with self.assertRaises(ValueError):
            events.build_event("nas", "change", "x", 10, 5)

    def test_list_params(self):
        self.assertEqual(events.list_params("nas", "change", 10),
                         {"tags": ["dotinfra", "host:nas", "type:change"], "limit": "10",
                          "type": "annotation"})
        self.assertEqual(events.list_params(since_ms=7)["from"], "7")
        self.assertEqual(events.list_params()["tags"], ["dotinfra"])

    def test_format(self):
        rows = [
            {"id": 1, "time": NOW_MS - 3600_000, "tags": ["dotinfra", "host:nas", "type:change"], "text": "older"},
            {"id": 2, "time": NOW_MS, "timeEnd": NOW_MS + 600_000,
             "tags": ["dotinfra", "host:gpu1", "type:outage"], "text": "newer\nline"},
        ]
        out = events.format_events(rows).splitlines()
        self.assertIn("gpu1", out[1])
        self.assertIn("(10 min)", out[1])
        self.assertIn("newer line", out[1])
        self.assertIn("older", out[2])
        self.assertEqual(events.format_events([]), "no events")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class CliHandlerTest(unittest.TestCase):
    """Handlers with a stubbed context and urlopen: no CMDB, no network."""

    def setUp(self):
        self.requests = []
        self.reply = {"id": 77, "message": "Annotation added"}

        def urlopen(req, timeout=None):
            self.requests.append((req.get_method(), req.full_url,
                                  json.loads(req.data) if req.data else None))
            return FakeResponse(json.dumps(self.reply).encode())

        comps = [SimpleNamespace(id="nas"), SimpleNamespace(id="gpu1")]
        ctx = SimpleNamespace(
            root="/cmdb",
            config=SimpleNamespace(get=lambda s, k, d=None: {
                "grafana_url": "http://grafana.example.com:3000"}.get(k, d)),
            components=lambda: comps,
            secret=lambda key: "pw",
        )
        self.patches = [
            mock.patch("urllib.request.urlopen", urlopen),
            mock.patch("dotinfra.context.get_context", lambda args: ctx, create=True),
        ]
        try:
            import dotinfra.context  # noqa: F401
        except ImportError:
            import sys
            import types
            sys.modules["dotinfra.context"] = types.ModuleType("dotinfra.context")
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def call(self, handler, **kw):
        """Run a handler the way cli.main does: DotinfraError -> message on stderr, exit 1."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = handler(SimpleNamespace(root=None, **kw))
            except DotinfraError as exc:
                print(f"dotinfra: error: {exc}", file=err)
                code = 1
        return code, out.getvalue(), err.getvalue()

    def test_add(self):
        code, out, err = self.call(events._cmd_add, host="nas", type="maintenance",
                                   time="2026-09-26T10:00Z", end="2026-09-26T11:00Z",
                                   text=["replaced", "disk", "2"])
        self.assertEqual(code, 0, err)
        method, url, body = self.requests[0]
        self.assertEqual((method, url), ("POST", "http://grafana.example.com:3000/api/annotations"))
        self.assertEqual(body["text"], "replaced disk 2")
        self.assertEqual(body["timeEnd"] - body["time"], 3600_000)
        self.assertIn("host:nas", body["tags"])
        self.assertIn("77", out)
        self.assertNotIn("warning:", err)

    def test_add_unknown_host_warns(self):
        code, _out, err = self.call(events._cmd_add, host="ghost", type="observation",
                                    time="now", end=None, text=["hello"])
        self.assertEqual(code, 0)
        self.assertIn("not a component id", err)

    def test_add_bad_time(self):
        code, _out, err = self.call(events._cmd_add, host="nas", type="change",
                                    time="soonish", end=None, text=["x"])
        self.assertEqual(code, 1)
        self.assertIn("cannot parse time", err)
        self.assertEqual(self.requests, [])

    def test_list(self):
        self.reply = [{"id": 5, "time": NOW_MS, "tags": ["dotinfra", "host:nas", "type:change"],
                       "text": "raised RAM"}]
        code, out, _ = self.call(events._cmd_list, host="nas", type=None, since=None,
                                 limit=20, json=False)
        self.assertEqual(code, 0)
        method, url, _ = self.requests[0]
        self.assertEqual(method, "GET")
        self.assertIn("tags=dotinfra", url)
        self.assertIn("tags=host%3Anas", url)
        self.assertIn("limit=20", url)
        self.assertIn("raised RAM", out)

    def test_rm(self):
        self.reply = {"message": "Annotation deleted"}
        code, out, _ = self.call(events._cmd_rm, id=5)
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0][:2], ("DELETE", "http://grafana.example.com:3000/api/annotations/5"))

    def test_types_match_dashboard(self):
        self.assertEqual(set(events.VALID_TYPES), set(grafana.EVENT_TYPES))
        self.assertEqual(set(events.VALID_TYPES),
                         {"outage", "maintenance", "change", "incident", "observation"})


if __name__ == "__main__":
    unittest.main()
