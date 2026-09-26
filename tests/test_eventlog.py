"""The file event backend (events/<YYYY>.md): add, list, filters, rm, auto selection, merge."""

import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from support import IsolatedTestCase, git, run_cli
from test_sync import TwoDeviceTestCase
from dotinfra import eventlog
from dotinfra.lint import run_lint
from dotinfra.config import load_config, set_toml_value
from dotinfra.model import load_cmdb
from dotinfra.index import render_index
from dotinfra.reconcile import merge_file_text
from dotinfra.scaffold import new_component


def ms(text: str) -> int:
    return eventlog.parse_ts(text)


class FormatTest(unittest.TestCase):
    def test_line_roundtrip(self):
        event = eventlog.Event(ms("2026-09-26T07:34Z"), "nas", "maintenance", "replaced\ndisk 2")
        self.assertEqual(event.line(), "- 2026-09-26T07:34Z · nas · maintenance · replaced disk 2")
        back = eventlog.parse_line(event.line())
        self.assertEqual((back.time_ms, back.host, back.type, back.text, back.end_ms),
                         (event.time_ms, "nas", "maintenance", "replaced disk 2", None))

    def test_interval_and_text_with_separator(self):
        line = "- 2026-01-02T09:00Z/2026-01-02T09:40Z · gpu1 · outage · PSU · tripped"
        event = eventlog.parse_line(line)
        self.assertEqual(event.end_ms - event.time_ms, 40 * 60_000)
        self.assertEqual(event.text, "PSU · tripped")
        self.assertEqual(event.line(), line)

    def test_non_event_lines(self):
        for line in ("# Events 2026", "", "- 2026-01-02 — old style", "text"):
            self.assertIsNone(eventlog.parse_line(line))


class MergeTest(unittest.TestCase):
    HEAD = eventlog.header("2026")
    A = "- 2026-01-01T10:00Z · nas · change · a\n"
    B = "- 2026-01-02T10:00Z · gpu1 · outage · b\n"
    C = "- 2026-01-03T10:00Z · hub · change · c\n"

    def test_union_sorted(self):
        base = self.HEAD + self.A
        ours = base + self.C
        theirs = base + self.B
        result = merge_file_text("events/2026.md", base, ours, theirs)
        self.assertTrue(result.clean)
        self.assertEqual(result.text, self.HEAD + self.A + self.B + self.C)

    def test_deleted_on_one_side_stays_deleted(self):
        base = self.HEAD + self.A + self.B
        result = merge_file_text("events/2026.md", base, self.HEAD + self.B,
                                 base + self.C)
        self.assertEqual(result.text, self.HEAD + self.B + self.C)

    def test_no_base(self):
        result = merge_file_text("events/2026.md", "", self.HEAD + self.C, self.HEAD + self.A)
        self.assertEqual(result.text, self.HEAD + self.A + self.C)

    def test_other_paths_use_the_component_merge(self):
        self.assertFalse(eventlog.is_event_file("servers/events.md"))
        self.assertFalse(eventlog.is_event_file("events/sub/2026.md"))
        self.assertTrue(eventlog.is_event_file("events/2026.md"))


class FileBackendCliTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_cmdb(use_git=False)
        new_component(self.root, "server", "nas")
        new_component(self.root, "server", "gpu1")

    def cli(self, *argv, expected=0):
        code, out, err = run_cli("--root", self.root, "event", *argv)
        self.assertEqual(code, expected, f"stdout:\n{out}\nstderr:\n{err}")
        return out, err

    def test_auto_is_file_without_monitoring(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            out, _ = self.cli("add", "--host", "nas", "--type", "maintenance",
                              "--time", "2026-09-26T07:34Z", "replaced disk 2")
        self.assertIn("event 2026.1 added", out)
        text = (self.root / "events/2026.md").read_text()
        self.assertTrue(text.startswith("# Events 2026\n"))
        self.assertIn("- 2026-09-26T07:34Z · nas · maintenance · replaced disk 2\n", text)

    def test_add_list_filter_rm(self):
        self.cli("add", "--host", "nas", "--type", "change", "--time", "2026-03-01T10:00Z", "c1")
        self.cli("add", "--host", "gpu1", "--type", "outage", "--time", "2026-01-05T08:00Z",
                 "--end", "2026-01-05T08:30Z", "o1")
        self.cli("add", "--host", "nas", "--type", "outage", "--time", "2025-12-31T23:00Z", "o0")
        # kept in timestamp order within the year file, one file per year
        lines = [l for l in (self.root / "events/2026.md").read_text().splitlines()
                 if l.startswith("- ")]
        self.assertEqual([l.rsplit(" · ", 1)[1] for l in lines], ["o1", "c1"])
        self.assertTrue((self.root / "events/2025.md").is_file())

        out, _ = self.cli("list")
        rows = out.splitlines()[1:]
        self.assertEqual([r.split()[5] for r in rows], ["c1", "o1", "o0"])
        self.assertIn("(30 min)", out)
        out, _ = self.cli("list", "--host", "nas", "--json")
        self.assertEqual([e["text"] for e in json.loads(out)], ["c1", "o0"])
        out, _ = self.cli("list", "--type", "outage", "--json")
        self.assertEqual([e["text"] for e in json.loads(out)], ["o1", "o0"])
        out, _ = self.cli("list", "--since", "2026-01-01T00:00Z", "--json")
        self.assertEqual([e["text"] for e in json.loads(out)], ["c1", "o1"])
        out, _ = self.cli("list", "--limit", "1", "--json")
        data = json.loads(out)
        self.assertEqual((len(data), data[0]["id"]), (1, "2026.2"))

        out, _ = self.cli("rm", "2026.1")
        self.assertIn("o1", out)
        out, _ = self.cli("list", "--json")
        self.assertEqual([e["text"] for e in json.loads(out)], ["c1", "o0"])
        _, err = self.cli("rm", "2026.9", expected=1)
        self.assertIn("no event", err)

    def test_not_components_not_indexed_not_linted(self):
        self.cli("add", "--host", "nas", "--type", "change", "--time", "2026-03-01T10:00Z", "x")
        self.assertEqual({c.id for c in load_cmdb(self.root)}, {"nas", "gpu1"})
        self.assertNotIn("events", render_index(load_cmdb(self.root), "cmdb"))
        issues = run_lint(self.root, load_config(self.root))
        self.assertEqual([i for i in issues if i.path.startswith("events/")], [])

    def test_auto_is_grafana_with_monitoring_service(self):
        self.write(self.root, "services/monitoring.md",
                   "---\nstatus: active\nrole: m\nruns_on: nas\nurl: http://grafana.example.com\n"
                   "updated: 2026-09-26\n---\n# monitoring\n")
        requests = []

        def urlopen(req, timeout=None):
            requests.append(req.full_url)
            raise OSError("offline")

        with mock.patch("urllib.request.urlopen", urlopen), \
                mock.patch("dotinfra.context.Context.secret", return_value="pw"):
            self.cli("add", "--host", "nas", "--type", "change", "x", expected=1)
        self.assertTrue(requests and requests[0].startswith("http://grafana.example.com"))
        self.assertFalse((self.root / "events").exists())

    def test_explicit_file_backend_wins(self):
        self.write(self.root, "services/monitoring.md",
                   "---\nstatus: active\nurl: http://grafana.example.com\n---\n# monitoring\n")
        set_toml_value(self.root / ".dotinfra.toml", "events", "backend", "file")
        self.cli("add", "--host", "nas", "--type", "change", "--time", "2026-03-01T10:00Z", "x")
        self.assertTrue((self.root / "events/2026.md").is_file())

    def test_bad_backend(self):
        set_toml_value(self.root / ".dotinfra.toml", "events", "backend", "syslog")
        _, err = self.cli("list", expected=1)
        self.assertIn("[events] backend", err)


class EventMergeSyncTest(TwoDeviceTestCase):
    """Both devices append to events/2026.md; the merge driver unions them."""

    def add(self, root, time, text):
        code, out, err = run_cli("--root", root, "event", "add", "--host", "web1",
                                 "--type", "change", "--time", time, text)
        self.assertEqual(code, 0, err)

    def test_union_through_merge_driver(self):
        self.add(self.a, "2026-02-01T10:00Z", "base event")
        self.assertSync(self.a)
        self.assertSync(self.b)
        self.add(self.a, "2026-02-03T10:00Z", "from a")
        self.add(self.b, "2026-02-02T10:00Z", "from b")
        self.assertSync(self.a)
        out = self.assertSync(self.b)
        self.assertIn("merged origin/main", out)
        self.assertSync(self.a)
        text_a = (self.a / "events/2026.md").read_text()
        self.assertEqual(text_a, (self.b / "events/2026.md").read_text())
        self.assertNotIn("<<<<<<<", text_a)
        texts = [e.text for e in eventlog.load_events(self.a)]
        self.assertEqual(texts, ["base event", "from b", "from a"])
        self.assertEqual(git(self.b, "status", "--porcelain"), "")

    def test_both_devices_create_the_year_file(self):
        self.add(self.a, "2026-02-03T10:00Z", "from a")
        self.add(self.b, "2026-02-02T10:00Z", "from b")
        self.assertSync(self.a)
        self.assertSync(self.b)
        texts = [e.text for e in eventlog.load_events(self.b)]
        self.assertEqual(texts, ["from b", "from a"])
        self.assertNotIn("<<<<<<<", (self.b / "events/2026.md").read_text())


if __name__ == "__main__":
    unittest.main()
