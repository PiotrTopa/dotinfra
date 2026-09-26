import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from dotinfra.frontmatter import (FrontmatterError, dump, dump_scalar, parse, parse_document,
                                  render, replace_keys)

DOC = """\
---
# leading comment
id: gpu1
title: "gpu1 — GPU: inference"
status: active   # trailing comment
count: 42
enabled: true
empty:
nothing: null
tilde: ~
updated: 2026-09-23
url: http://example.com/#anchor
tags: [fleet, gpu, "c d", 'e, f']
aliases:
  - one
  - "two # not a comment"
  # a comment inside a block list
ssh:
  user: alice
  port: 22
  jump: hub   # jump host
  opts: [a, b]
---

# gpu1
"""


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.meta, self.body = parse(DOC)

    def test_scalars(self):
        m = self.meta
        self.assertEqual(m["id"], "gpu1")
        self.assertEqual(m["title"], "gpu1 — GPU: inference")
        self.assertEqual(m["status"], "active")
        self.assertEqual(m["count"], 42)
        self.assertIs(m["enabled"], True)
        self.assertIsNone(m["empty"])
        self.assertIsNone(m["nothing"])
        self.assertIsNone(m["tilde"])
        self.assertEqual(m["updated"], "2026-09-23")  # dates stay strings
        self.assertEqual(m["url"], "http://example.com/#anchor")

    def test_lists_and_maps(self):
        self.assertEqual(self.meta["tags"], ["fleet", "gpu", "c d", "e, f"])
        self.assertEqual(self.meta["aliases"], ["one", "two # not a comment"])
        self.assertEqual(self.meta["ssh"],
                         {"user": "alice", "port": 22, "jump": "hub", "opts": ["a", "b"]})

    def test_key_order_and_body(self):
        self.assertEqual(list(self.meta)[:3], ["id", "title", "status"])
        self.assertEqual(self.body, "\n# gpu1\n")

    def test_line_numbers(self):
        lines = parse_document(DOC).lines
        self.assertEqual(lines["id"], 3)
        self.assertEqual(lines["ssh"], 18)

    def test_no_frontmatter(self):
        self.assertEqual(parse("# just markdown\n"), ({}, "# just markdown\n"))

    def test_crlf_and_empty_lists(self):
        meta, _ = parse("---\r\nids: []\r\nx: [a,]\r\nm: {}\r\n---\r\nbody")
        self.assertEqual(meta, {"ids": [], "x": ["a"], "m": {}})

    def test_apostrophe_inside_unquoted_text(self):
        meta, _ = parse("---\nrole: Alice's NAS # comment\n---\n")
        self.assertEqual(meta["role"], "Alice's NAS")


class ParseErrorTest(unittest.TestCase):
    def assertError(self, frontmatter: str, fragment: str, line: int):
        with self.assertRaises(FrontmatterError) as ctx:
            parse(f"---\n{frontmatter}\n---\n", source="servers/x.md")
        self.assertIn(fragment, ctx.exception.message)
        self.assertEqual(ctx.exception.line, line)
        self.assertTrue(str(ctx.exception).startswith(f"servers/x.md:{line}: "))

    def test_unsupported_constructs(self):
        self.assertError("a: |\n  text", "multi-line", 2)
        self.assertError("a: &anchor x", "anchors", 2)
        self.assertError("a: {b: 1}", "inline maps", 2)
        self.assertError("a:\n  b:\n    c: 1", "nested deeper", 4)
        self.assertError("a:\n  - b: 1", "lists of maps", 3)
        self.assertError("a: [[1]]", "nested collections", 2)

    def test_syntax_errors(self):
        self.assertError("a: 1\na: 2", "duplicate key", 3)
        self.assertError("just text", "expected 'key: value'", 2)
        self.assertError("  a: 1", "unexpected indentation", 2)
        self.assertError('a: "open', "unterminated quoted", 2)
        self.assertError("a: [1, 2", "unterminated inline list", 2)
        self.assertError('a: "x" y', "unexpected text after quoted", 2)
        self.assertError("a:\n\t- x", "tabs", 3)
        self.assertError("a:\n  - x\n  b: 1", "mixed list items", 4)

    def test_unterminated_frontmatter(self):
        with self.assertRaises(FrontmatterError) as ctx:
            parse("---\na: 1\n")
        self.assertEqual(ctx.exception.line, 1)


class DumpTest(unittest.TestCase):
    def test_round_trip(self):
        meta, _ = parse(DOC)
        again, _ = parse(render(meta, "body"))
        self.assertEqual(again, meta)

    def test_deterministic_output(self):
        meta = {"id": "x", "tags": ["a", "b c"], "ssh": {"user": "u", "port": 22},
                "role": None, "m": {}, "ok": False}
        self.assertEqual(dump(meta), "id: x\ntags: [a, b c]\nssh:\n  user: u\n  port: 22\n"
                                     "role:\nm: {}\nok: false\n")

    def test_quoting_keeps_types(self):
        tricky = ["true", "123", "", "a: b", "#x", "x #y", " pad", "null", "- item", "end:",
                  "multi\nline", 'quote"d', "back\\slash"]
        for value in tricky:
            with self.subTest(value=value):
                meta, _ = parse(render({"k": value, "l": [value, "x,y", "[z]"]}, ""))
                self.assertEqual(meta["k"], value)
                self.assertEqual(meta["l"], [value, "x,y", "[z]"])

    def test_plain_strings_unquoted(self):
        self.assertEqual(dump_scalar("Debian 12"), "Debian 12")
        self.assertEqual(dump_scalar("10.10.0.1"), "10.10.0.1")
        self.assertEqual(dump_scalar("2026-09-23"), "2026-09-23")

    def test_too_deep_raises(self):
        with self.assertRaises(ValueError):
            dump({"a": {"b": {"c": 1}}})


class ReplaceKeysTest(unittest.TestCase):
    def test_updates_preserve_other_lines(self):
        text = replace_keys(DOC, {"status": "degraded", "facts": {"cpus": 8}}, remove=["count"])
        self.assertIn("# leading comment\n", text)
        self.assertIn("status: degraded # trailing comment\n", text)
        self.assertIn("  jump: hub   # jump host\n", text)
        self.assertNotIn("count:", text)
        self.assertTrue(text.endswith("facts:\n  cpus: 8\n---\n\n# gpu1\n"))
        meta, body = parse(text)
        self.assertEqual(meta["status"], "degraded")
        self.assertEqual(body, "\n# gpu1\n")

    def test_comment_alignment_kept(self):
        text = replace_keys("---\nstatus: planned        # choices\n---\n", {"status": "active"})
        self.assertIn("status: active         # choices\n", text)

    def test_adds_frontmatter_when_missing(self):
        text = replace_keys("# Title\n", {"status": "active"})
        self.assertEqual(text, "---\nstatus: active\n---\n\n# Title\n")


if __name__ == "__main__":
    unittest.main()
