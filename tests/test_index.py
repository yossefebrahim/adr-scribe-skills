"""Tests for the generated index renderer.

The escape-ordering test is the reason this file exists: plan v1.0 specified
pipe-before-backslash, which silently produces a broken table.
"""

import random
import unittest

from adr_scribe.index import (
    END_MARKER,
    START_MARKER,
    IndexRenderError,
    escape_cell,
    render_block,
    render_index,
    render_table,
    splice,
)

U1 = "ADR-01J000000000000000000000AA"
U2 = "ADR-01J000000000000000000000BB"
U3 = "ADR-01J000000000000000000000CC"


def rec(ulid, title="T", status="proposed", date="2026-08-12", summary="S"):
    return {"id": ulid, "title": title, "status": status, "date": date, "summary": summary}


class TestEscapeCell(unittest.TestCase):
    def test_backslash_is_escaped_before_pipe(self):
        # Input:  a \ | b   ->  backslash doubled, THEN pipe escaped.
        # Correct: a \\ \| b  -> renders as a literal backslash and a literal pipe.
        # Wrong (pipe first): a \\\\ | b -> the delimiter survives and breaks the row.
        self.assertEqual(escape_cell("a\\|b"), "a\\\\\\|b")

    def test_wrong_order_would_leave_a_live_delimiter(self):
        # Demonstrates the bug this ordering prevents.
        naive = "a\\|b".replace("|", "\\|").replace("\\", "\\\\")
        self.assertTrue(naive.endswith("\\\\|b"), naive)
        self.assertNotEqual(naive, escape_cell("a\\|b"))

    def test_plain_pipe(self):
        self.assertEqual(escape_cell("a|b"), "a\\|b")

    def test_plain_backslash(self):
        self.assertEqual(escape_cell("a\\b"), "a\\\\b")

    def test_newlines_become_single_space(self):
        self.assertEqual(escape_cell("a\r\nb\nc\rd"), "a b c d")

    def test_space_runs_collapse_and_strip(self):
        self.assertEqual(escape_cell("  a    b  "), "a b")

    def test_non_ascii_passes_through(self):
        self.assertEqual(escape_cell("Café 日本語 🙂"), "Café 日本語 🙂")

    def test_non_string_rejected(self):
        with self.assertRaises(IndexRenderError):
            escape_cell(3)


class TestRenderTable(unittest.TestCase):
    def test_sorted_by_ulid_regardless_of_input_order(self):
        records = [rec(U3), rec(U1), rec(U2)]
        table = render_table(records)
        self.assertLess(table.index(U1), table.index(U2))
        self.assertLess(table.index(U2), table.index(U3))

    def test_deterministic_across_shuffles(self):
        records = [rec(U1), rec(U2), rec(U3)]
        expected = render_table(records)
        rng = random.Random(1234)
        for _ in range(50):
            shuffled = records[:]
            rng.shuffle(shuffled)
            self.assertEqual(render_table(shuffled), expected)

    def test_header_present_with_no_records(self):
        table = render_table([])
        self.assertIn("| ID | Title | Status | Last updated | Summary |", table)
        self.assertEqual(len(table.splitlines()), 2)

    def test_duplicate_id_rejected(self):
        with self.assertRaises(IndexRenderError):
            render_table([rec(U1), rec(U1)])

    def test_malformed_id_rejected(self):
        for bad in ("ADR-nope", "01J0000000000000000000AA", "ADR-81J0000000000000000000A", ""):
            with self.assertRaises(IndexRenderError):
                render_table([rec(bad)])

    def test_missing_field_rejected(self):
        broken = rec(U1)
        del broken["summary"]
        with self.assertRaises(IndexRenderError):
            render_table([broken])

    def test_pipe_in_title_does_not_add_a_column(self):
        table = render_table([rec(U1, title="a|b", summary="c|d")])
        row = table.splitlines()[-1]
        # Count only unescaped delimiters: 6 for a 5-column row.
        unescaped = sum(
            1
            for i, ch in enumerate(row)
            if ch == "|" and (i == 0 or row[i - 1] != "\\")
        )
        self.assertEqual(unescaped, 6, row)


class TestSplice(unittest.TestCase):
    def test_preserves_surrounding_content(self):
        existing = "# Title\n\nintro\n\n%s\nOLD\n%s\n\nfooter\n" % (START_MARKER, END_MARKER)
        out = splice(existing, render_block([rec(U1)]))
        self.assertTrue(out.startswith("# Title\n\nintro\n\n"))
        self.assertTrue(out.endswith("\n\nfooter\n"))
        self.assertNotIn("OLD", out)

    def test_missing_markers_rejected(self):
        for bad in ("no markers", START_MARKER, END_MARKER, START_MARKER + START_MARKER + END_MARKER):
            with self.assertRaises(IndexRenderError):
                splice(bad, "block")

    def test_reversed_markers_rejected(self):
        with self.assertRaises(IndexRenderError):
            splice(END_MARKER + "\n" + START_MARKER, "block")

    def test_idempotent(self):
        existing = "head\n%s\n%s\ntail\n" % (START_MARKER, END_MARKER)
        block = render_block([rec(U1), rec(U2)])
        once = splice(existing, block)
        self.assertEqual(splice(once, block), once)


class TestRenderIndex(unittest.TestCase):
    def test_bootstrap_scaffold_contains_markers_and_rows(self):
        out = render_index(None, [rec(U1, title="Use ULIDs")])
        self.assertIn(START_MARKER, out)
        self.assertIn(END_MARKER, out)
        self.assertIn("Use ULIDs", out)
        self.assertTrue(out.endswith("\n"))

    def test_bootstrap_then_splice_round_trip(self):
        first = render_index(None, [rec(U1)])
        second = render_index(first, [rec(U1), rec(U2)])
        self.assertIn(U2, second)
        self.assertTrue(second.startswith("# Architecture Decision Records"))


if __name__ == "__main__":
    unittest.main()
