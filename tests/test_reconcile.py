import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from dotinfra.frontmatter import parse
from dotinfra.reconcile import (conflict_blocks, has_conflict_markers, merge_driver,
                                merge_history, merge_text, split_sections)

BASE = """\
---
id: web1
status: active      # lifecycle
tags: [fleet, web]
role: web server
updated: 2026-09-01
---

# web1

## Overview

A web server.

## Configuration

- nginx 1.24
- port 443
- certbot

## Known issues

## History

- 2026-09-01 — created
"""


def edit(text: str, *pairs: tuple[str, str]) -> str:
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new, 1)
    return text


class FrontmatterMergeTest(unittest.TestCase):
    def merged_meta(self, ours: str, theirs: str) -> dict:
        result = merge_text(BASE, ours, theirs)
        self.assertTrue(result.clean, result.text)
        return parse(result.text)[0]

    def test_one_side_and_identical_changes(self):
        ours = edit(BASE, ("role: web server", "role: reverse proxy"))
        theirs = edit(BASE, ("status: active", "status: degraded"))
        meta = self.merged_meta(ours, theirs)
        self.assertEqual((meta["role"], meta["status"]), ("reverse proxy", "degraded"))
        both = edit(BASE, ("status: active", "status: retired"))
        self.assertEqual(self.merged_meta(both, both)["status"], "retired")

    def test_lists_union_with_deletions(self):
        ours = edit(BASE, ("tags: [fleet, web]", "tags: [fleet, web, nginx]"))
        theirs = edit(BASE, ("tags: [fleet, web]", "tags: [web, tls]"))
        self.assertEqual(self.merged_meta(ours, theirs)["tags"], ["web", "nginx", "tls"])

    def test_updated_takes_max(self):
        ours = edit(BASE, ("updated: 2026-09-01", "updated: 2026-09-20"))
        theirs = edit(BASE, ("updated: 2026-09-01", "updated: 2026-09-10"))
        self.assertEqual(self.merged_meta(ours, theirs)["updated"], "2026-09-20")

    def test_added_and_deleted_keys(self):
        ours = edit(BASE, ("role: web server\n", ""))
        theirs = edit(BASE, ("updated:", "os: Debian 12\nupdated:"))
        meta = self.merged_meta(ours, theirs)
        self.assertNotIn("role", meta)
        self.assertEqual(meta["os"], "Debian 12")

    def test_comments_survive(self):
        ours = edit(BASE, ("role: web server", "role: proxy"))
        result = merge_text(BASE, ours, BASE)
        self.assertIn("status: active      # lifecycle\n", result.text)

    def test_scalar_conflict(self):
        ours = edit(BASE, ("status: active", "status: degraded"))
        theirs = edit(BASE, ("status: active", "status: retired"))
        result = merge_text(BASE, ours, theirs)
        self.assertEqual(result.conflicts, 1)
        self.assertIn("<<<<<<< ours\nstatus: degraded\n=======\nstatus: retired\n"
                      ">>>>>>> theirs\n", result.text)

    def test_updated_emptied_on_one_side_takes_the_date(self):
        ours = edit(BASE, ("updated: 2026-09-01", "updated:"))
        theirs = edit(BASE, ("updated: 2026-09-01", "updated: 2026-09-10"))
        self.assertEqual(self.merged_meta(ours, theirs)["updated"], "2026-09-10")
        self.assertEqual(self.merged_meta(theirs, ours)["updated"], "2026-09-10")
        ours = edit(BASE, ("updated: 2026-09-01", "updated: 7"))
        self.assertEqual(merge_text(BASE, ours, theirs).conflicts, 1)


class BodyMergeTest(unittest.TestCase):
    def test_different_sections_merge(self):
        ours = edit(BASE, ("A web server.", "A web server in the rack."))
        theirs = edit(BASE, ("## Known issues\n", "## Known issues\n\n- TLS renewals flaky\n"))
        result = merge_text(BASE, ours, theirs)
        self.assertTrue(result.clean)
        self.assertIn("in the rack", result.text)
        self.assertIn("TLS renewals flaky", result.text)

    def test_same_section_different_lines_merge(self):
        ours = edit(BASE, ("- nginx 1.24", "- nginx 1.26"))
        theirs = edit(BASE, ("- certbot", "- certbot (weekly timer)"))
        result = merge_text(BASE, ours, theirs)
        self.assertTrue(result.clean, result.text)
        self.assertIn("- nginx 1.26\n- port 443\n- certbot (weekly timer)\n", result.text)

    def test_same_line_conflict_stays_inside_section(self):
        ours = edit(BASE, ("- port 443", "- port 8443"), ("A web server.", "Ours overview."))
        theirs = edit(BASE, ("- port 443", "- port 9443"))
        result = merge_text(BASE, ours, theirs)
        self.assertEqual(result.conflicts, 1)
        self.assertIn("Ours overview.", result.text)
        blocks = conflict_blocks(result.text)
        self.assertEqual(len(blocks), 1)
        self.assertIn("- port 8443", blocks[0][1])
        self.assertIn("- port 9443", blocks[0][1])
        section = dict(split_sections(parse(result.text)[1]))
        self.assertTrue(has_conflict_markers(section["Configuration"]))
        self.assertFalse(has_conflict_markers(section["Overview"]))

    def test_added_section_keeps_position(self):
        theirs = edit(BASE, ("## Known issues", "## Access\n\nssh web1\n\n## Known issues"))
        ours = edit(BASE, ("## History", "## Backups\n\nnightly\n\n## History"))
        text = merge_text(BASE, ours, theirs).text
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, ["## Overview", "## Configuration", "## Access",
                                    "## Known issues", "## Backups", "## History"])

    def test_deleted_section(self):
        ours = edit(BASE, ("## Known issues\n\n", ""))
        self.assertNotIn("## Known issues", merge_text(BASE, ours, BASE).text)
        theirs = edit(BASE, ("## Known issues\n", "## Known issues\n\n- new issue\n"))
        result = merge_text(BASE, ours, theirs)
        self.assertEqual(result.conflicts, 1)  # deleted vs modified needs a human

    def test_both_sides_only_added_lines_keeps_both(self):
        # The most common concurrent edit: two devices each append a bullet to the
        # same (possibly empty) section. Line merge would call the adjacent additions
        # a conflict; dotinfra keeps both, ours first.
        ours = edit(BASE, ("## Known issues\n", "## Known issues\n\n- fan noisy\n"))
        theirs = edit(BASE, ("## Known issues\n", "## Known issues\n\n- disk 3 SMART warnings\n"))
        result = merge_text(BASE, ours, theirs)
        self.assertTrue(result.clean, result.text)
        self.assertIn("## Known issues\n\n- fan noisy\n- disk 3 SMART warnings\n\n## History\n",
                      result.text)
        ours = edit(BASE, ("- certbot\n", "- certbot\n- fail2ban\n"))
        theirs = edit(BASE, ("- certbot\n", "- certbot\n- unattended-upgrades\n"),
                      ("- nginx 1.24\n", "- nginx 1.24\n- brotli module\n"))
        result = merge_text(BASE, ours, theirs)
        self.assertTrue(result.clean, result.text)
        self.assertIn("- nginx 1.24\n- brotli module\n- port 443\n- certbot\n- fail2ban\n"
                      "- unattended-upgrades\n", result.text)

    def test_modified_plus_added_still_conflicts_when_adjacent(self):
        ours = edit(BASE, ("- certbot\n", "- acme.sh\n"))
        theirs = edit(BASE, ("- certbot\n", "- certbot\n- fail2ban\n"))
        result = merge_text(BASE, ours, theirs)
        self.assertEqual(result.conflicts, 1)

    def test_headings_inside_code_fences_are_not_sections(self):
        body = "# t\n\n## Real\n\n```md\n## not a heading\n```\n"
        self.assertEqual([k for k, _ in split_sections(body)], [None, "Real"])


class HistoryMergeTest(unittest.TestCase):
    def test_union_sorted_newest_first(self):
        ours = edit(BASE, ("- 2026-09-01 — created", "- 2026-09-05 — ours\n- 2026-09-01 — created"))
        theirs = edit(BASE, ("- 2026-09-01 — created",
                             "- 2026-09-07 — theirs\n- 2026-09-05 — ours\n- 2026-09-01 — created"))
        result = merge_text(BASE, ours, theirs)
        self.assertTrue(result.clean)
        history = result.text.split("## History\n\n")[1]
        self.assertEqual(history, "- 2026-09-07 — theirs\n- 2026-09-05 — ours\n"
                                  "- 2026-09-01 — created\n")

    def test_same_day_new_entries_above_old(self):
        base = "## History\n\n- 2026-09-01 — created\n"
        ours = "## History\n\n- 2026-09-01 — a\n- 2026-09-01 — created\n"
        theirs = "## History\n\n- 2026-09-01 — b\n- 2026-09-01 — created\n"
        self.assertEqual(merge_history(base, ours, theirs),
                         "## History\n\n- 2026-09-01 — a\n- 2026-09-01 — b\n"
                         "- 2026-09-01 — created\n")

    def test_deleted_entry_stays_deleted_and_continuations_kept(self):
        base = "## Changelog\n\n- 2026-01-01 — typo\n- 2026-01-01 — keep\n"
        ours = "## Changelog\n\n- 2026-01-01 — keep\n"
        theirs = ("## Changelog\n\n- 2026-02-01 — new\n  detail line\n- 2026-01-01 — typo\n"
                  "- 2026-01-01 — keep\n")
        self.assertEqual(merge_history(base, ours, theirs),
                         "## Changelog\n\n- 2026-02-01 — new\n  detail line\n"
                         "- 2026-01-01 — keep\n")


class DriverTest(unittest.TestCase):
    def run_driver(self, base: str, ours: str, theirs: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ("O", "A", "B")]
            for path, text in zip(paths, (base, ours, theirs)):
                path.write_text(text)
            code = merge_driver(*paths, path="servers/web1.md")
            return code, paths[1].read_text()

    def test_clean_and_conflicted_exit_codes(self):
        ours = edit(BASE, ("A web server.", "Ours."))
        theirs = edit(BASE, ("- certbot", "- acme.sh"))
        code, text = self.run_driver(BASE, ours, theirs)
        self.assertEqual(code, 0)
        self.assertIn("Ours.", text)
        self.assertIn("acme.sh", text)
        code, text = self.run_driver(BASE, edit(BASE, ("- certbot", "- lego")), theirs)
        self.assertEqual(code, 1)
        self.assertTrue(has_conflict_markers(text))

    def test_unparseable_frontmatter_falls_back_to_lines(self):
        broken = "---\na: |\n  x\n---\nline1\nline2\nline3\nline4\n"
        code, text = self.run_driver(broken, broken.replace("line1", "one"),
                                     broken.replace("line4", "four"))
        self.assertEqual(code, 0)
        self.assertTrue(text.endswith("one\nline2\nline3\nfour\n"))

    def test_plain_markdown_without_frontmatter(self):
        base = "# Rules\n\n## A\n\nx\n\n## B\n\ny\n"
        code, text = self.run_driver(base, base.replace("x", "x2"), base.replace("y", "y2"))
        self.assertEqual((code, text), (0, "# Rules\n\n## A\n\nx2\n\n## B\n\ny2\n"))

    def test_non_utf8_input_falls_back_to_git_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ("O", "A", "B")]
            paths[0].write_bytes(b"caf\xe9\nl2\nl3\nl4\nl5\n")
            paths[1].write_bytes(b"caf\xe9\nours\nl3\nl4\nl5\n")
            paths[2].write_bytes(b"caf\xe9\nl2\nl3\nl4\ntheirs\n")
            code = merge_driver(*paths, path="servers/x.md")
            self.assertEqual(code, 0)
            self.assertEqual(paths[1].read_bytes(), b"caf\xe9\nours\nl3\nl4\ntheirs\n")


if __name__ == "__main__":
    unittest.main()
