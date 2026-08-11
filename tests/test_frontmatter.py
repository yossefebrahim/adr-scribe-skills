import unicodedata
import unittest
from collections import OrderedDict

from adr_scribe._frontmatter import (
    FIELD_ORDER,
    FrontmatterError,
    emit,
    parse,
    split_document,
)


# ---------------------------------------------------------------------------
# Round-trip properties
# ---------------------------------------------------------------------------

class TestRoundTripPerFieldShape(unittest.TestCase):
    """parse(emit(m)) == m for a table of valid mappings covering every field shape."""

    def _roundtrip(self, mapping):
        text = emit(mapping)
        self.assertEqual(parse(text), mapping)
        return text

    def test_string_value(self):
        self._roundtrip({"status": "proposed"})

    def test_null_value(self):
        self._roundtrip({"decision-date": None})

    def test_integer_value(self):
        self._roundtrip({"schema": 1})

    def test_negative_integer_value(self):
        self._roundtrip({"schema": -7})

    def test_zero_integer_value(self):
        self._roundtrip({"schema": 0})

    def test_true_value(self):
        self._roundtrip({"acceptance": True})

    def test_false_value(self):
        self._roundtrip({"acceptance": False})

    def test_empty_list_value(self):
        self._roundtrip({"consulted": []})

    def test_block_sequence_of_strings(self):
        self._roundtrip({"decision-makers": ["alice", "bob", "carol"]})

    def test_nested_map_provenance(self):
        self._roundtrip({
            "provenance": OrderedDict([
                ("context", "developer-stated"),
                ("decision", "developer-confirmed"),
                ("drivers", "code-observed"),
                ("alternatives", "developer-stated"),
                ("consequences", "developer-confirmed"),
                ("rules", "code-observed"),
            ])
        })

    def test_nested_map_evidence(self):
        self._roundtrip({
            "evidence": OrderedDict([
                ("commits", "abc123"),
                ("working-tree-files", "adr_scribe/_frontmatter.py"),
            ])
        })

    def test_nested_map_record_confirmation(self):
        self._roundtrip({"record-confirmation": OrderedDict([("confirmed-by", "alice")])})

    def test_partial_nested_map(self):
        # emit()/parse() must not require every declared subkey to be present.
        self._roundtrip({"provenance": OrderedDict([("context", "developer-stated")])})


class TestRoundTripCanonicalText(unittest.TestCase):
    """emit(parse(t)) == t for canonical text, constructed independently of emit()."""

    def test_simple_scalars(self):
        t = (
            'status: "proposed"\n'
            'schema: 3\n'
            'decision-date: null\n'
            'acceptance: false\n'
        )
        self.assertEqual(emit(parse(t)), t)

    def test_sequence(self):
        t = (
            "decision-makers:\n"
            '  - "alice"\n'
            '  - "bob"\n'
            "consulted: []\n"
        )
        self.assertEqual(emit(parse(t)), t)

    def test_nested_map(self):
        t = (
            "record-confirmation:\n"
            '  confirmed-by: "alice"\n'
        )
        self.assertEqual(emit(parse(t)), t)

    def test_empty_frontmatter(self):
        self.assertEqual(emit(parse("")), "")


class TestRoundTripFullDocument(unittest.TestCase):
    """A full realistic frontmatter using every key in FIELD_ORDER, both directions."""

    def _full_mapping(self):
        # Deliberately shuffled relative to FIELD_ORDER.
        return {
            "acceptance": True,
            "status": "proposed",
            "record-confirmation": {"confirmed-by": "alice"},
            "date": "2026-08-12",
            "provenance": {
                "context": "developer-stated",
                "decision": "developer-confirmed",
                "drivers": "code-observed",
                "alternatives": "developer-stated",
                "consequences": "developer-confirmed",
                "rules": "code-observed",
            },
            "decision-makers": ["alice", "bob"],
            "consulted": ["carol"],
            "informed": [],
            "schema": 1,
            "id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "evidence": {"commits": "abc123", "working-tree-files": "adr_scribe/_frontmatter.py"},
            "title": "Use canonical frontmatter",
            "summary": "A summary of the decision.",
            "decision-date": None,
            "applies-to": ["adr_scribe/_frontmatter.py"],
            "supersedes": [],
            "roadmap-ref": "RM-1",
            "content-digest": "sha256:" + "0" * 64,
        }

    def test_full_document_parse_of_emit(self):
        m = self._full_mapping()
        text = emit(m)
        self.assertEqual(parse(text), m)

    def test_full_document_emit_of_parse(self):
        m = self._full_mapping()
        text = emit(m)
        self.assertEqual(emit(parse(text)), text)

    def test_key_order_follows_field_order_regardless_of_input_order(self):
        m = self._full_mapping()
        text = emit(m)
        emitted_keys = []
        for line in text.split("\n"):
            if line and not line.startswith(" "):
                emitted_keys.append(line.split(":", 1)[0])
        expected = [k for k in FIELD_ORDER if k in m]
        self.assertEqual(emitted_keys, expected)


# ---------------------------------------------------------------------------
# String handling
# ---------------------------------------------------------------------------

class TestStringHandling(unittest.TestCase):
    def _roundtrip_string(self, value):
        m = {"title": value}
        text = emit(m)
        self.assertEqual(parse(text), m)
        return text

    def test_colon(self):
        self._roundtrip_string("a: b")

    def test_hash(self):
        self._roundtrip_string("a # b")

    def test_pipe(self):
        self._roundtrip_string("a | b")

    def test_greater_than(self):
        self._roundtrip_string("a > b")

    def test_hyphen(self):
        self._roundtrip_string("-leading and trailing-")

    def test_double_quote(self):
        self._roundtrip_string('she said "hi"')

    def test_backslash(self):
        self._roundtrip_string(r"C:\path\to\file")

    def test_literal_newline_escape(self):
        self._roundtrip_string("line one\nline two")

    def test_tab_escape(self):
        self._roundtrip_string("a\tb")

    def test_u_escape_survives_via_control_char(self):
        # A control char that only the \uXXXX escape can represent (e.g. NUL).
        self._roundtrip_string("a\x00b")

    def test_non_ascii_emitted_raw_cafe(self):
        text = self._roundtrip_string("Café")
        self.assertIn("Café", text)
        self.assertNotIn("\\u", text)

    def test_non_ascii_emitted_raw_emoji(self):
        text = self._roundtrip_string("rocket 🚀")
        self.assertIn("🚀", text)
        self.assertNotIn("\\u", text)

    def test_no_normalization_nfc_nfd_distinct(self):
        base = "Café"
        nfc = unicodedata.normalize("NFC", base)
        nfd = unicodedata.normalize("NFD", base)
        self.assertNotEqual(nfc, nfd)  # sanity: the two forms really are distinct
        text_nfc = emit({"title": nfc})
        text_nfd = emit({"title": nfd})
        self.assertNotEqual(text_nfc, text_nfd)
        self.assertEqual(parse(text_nfc)["title"], nfc)
        self.assertEqual(parse(text_nfd)["title"], nfd)
        self.assertNotEqual(parse(text_nfc)["title"], parse(text_nfd)["title"])

    def test_string_that_looks_like_null(self):
        self._roundtrip_string("null")

    def test_string_that_looks_like_true(self):
        self._roundtrip_string("true")

    def test_string_that_looks_like_integer(self):
        self._roundtrip_string("123")

    def test_string_that_looks_like_date(self):
        self._roundtrip_string("2026-08-12")

    def test_string_that_looks_like_sequence_item(self):
        self._roundtrip_string("- x")

    def test_string_that_looks_like_empty_list(self):
        self._roundtrip_string("[]")


# ---------------------------------------------------------------------------
# Rejection corpus
# ---------------------------------------------------------------------------

class TestRejectionStructural(unittest.TestCase):
    def test_missing_opening_fence(self):
        with self.assertRaises(FrontmatterError):
            split_document(b'status: "proposed"\n---\n')

    def test_missing_closing_fence(self):
        with self.assertRaises(FrontmatterError):
            split_document(b'---\nstatus: "proposed"\n')

    def test_bom(self):
        with self.assertRaises(FrontmatterError):
            split_document(b'\xef\xbb\xbf---\nstatus: "proposed"\n---\n')

    def test_cr_anywhere_in_frontmatter(self):
        with self.assertRaises(FrontmatterError):
            split_document(b'---\nstatus: "proposed"\r\n---\n')

    def test_invalid_utf8(self):
        with self.assertRaises(FrontmatterError):
            split_document(b"---\nstatus: \xff\xfe\n---\n")

    def test_separator_inside_block(self):
        with self.assertRaises(FrontmatterError):
            parse('status: "proposed"\n---\ndate: "2026-08-12"\n')


class TestRejectionLexical(unittest.TestCase):
    def test_tab_indentation(self):
        with self.assertRaises(FrontmatterError):
            parse('decision-makers:\n\t- "alice"\n')

    def test_trailing_whitespace(self):
        with self.assertRaises(FrontmatterError):
            parse('status: "proposed"  \n')

    def test_three_space_indentation(self):
        with self.assertRaises(FrontmatterError):
            parse('decision-makers:\n   - "alice"\n')

    def test_one_space_indentation(self):
        with self.assertRaises(FrontmatterError):
            parse('decision-makers:\n - "alice"\n')

    def test_empty_key(self):
        with self.assertRaises(FrontmatterError):
            parse(': "value"\n')

    def test_key_with_uppercase(self):
        with self.assertRaises(FrontmatterError):
            parse('Status: "proposed"\n')

    def test_key_with_leading_digit(self):
        with self.assertRaises(FrontmatterError):
            parse('1status: "proposed"\n')


class TestRejectionDuplicates(unittest.TestCase):
    def test_duplicate_key_top_level(self):
        with self.assertRaises(FrontmatterError):
            parse('status: "proposed"\nstatus: "accepted"\n')

    def test_duplicate_key_nested(self):
        with self.assertRaises(FrontmatterError):
            parse(
                "provenance:\n"
                '  context: "developer-stated"\n'
                '  context: "code-observed"\n'
            )

    def test_duplicate_key_nested_vs_top_level(self):
        with self.assertRaises(FrontmatterError):
            parse(
                'context: "top-level"\n'
                "provenance:\n"
                '  context: "developer-stated"\n'
            )


class TestRejectionYamlFeatures(unittest.TestCase):
    def test_anchor(self):
        with self.assertRaises(FrontmatterError):
            parse('status: &a "proposed"\n')

    def test_alias(self):
        with self.assertRaises(FrontmatterError):
            parse('status: *a\n')

    def test_merge_key(self):
        with self.assertRaises(FrontmatterError):
            parse('<<: "value"\n')

    def test_tag(self):
        with self.assertRaises(FrontmatterError):
            parse('status: !!str "proposed"\n')

    def test_directive(self):
        with self.assertRaises(FrontmatterError):
            parse('%YAML 1.2\nstatus: "proposed"\n')

    def test_flow_mapping(self):
        with self.assertRaises(FrontmatterError):
            parse('provenance: {a: 1}\n')

    def test_flow_sequence_non_empty(self):
        with self.assertRaises(FrontmatterError):
            parse('decision-makers: [a, b]\n')

    def test_block_scalar_literal(self):
        with self.assertRaises(FrontmatterError):
            parse('summary: |\n  hello\n')

    def test_block_scalar_folded(self):
        with self.assertRaises(FrontmatterError):
            parse('summary: >\n  hello\n')

    def test_comment_on_own_line(self):
        with self.assertRaises(FrontmatterError):
            parse('# a comment\nstatus: "proposed"\n')

    def test_comment_after_value(self):
        with self.assertRaises(FrontmatterError):
            parse('status: "proposed" # comment\n')

    def test_single_quoted_string(self):
        with self.assertRaises(FrontmatterError):
            parse("status: 'proposed'\n")

    def test_unquoted_string_scalar(self):
        with self.assertRaises(FrontmatterError):
            parse("status: proposed\n")


class TestRejectionShape(unittest.TestCase):
    def test_nested_map_two_levels_deep(self):
        with self.assertRaises(FrontmatterError):
            parse(
                "provenance:\n"
                "  context:\n"
                '    foo: "bar"\n'
            )

    def test_sequence_with_non_string_integer(self):
        with self.assertRaises(FrontmatterError):
            parse("decision-makers:\n  - 1\n")

    def test_sequence_with_non_string_null(self):
        with self.assertRaises(FrontmatterError):
            parse("decision-makers:\n  - null\n")

    def test_sequence_item_wrong_indentation(self):
        with self.assertRaises(FrontmatterError):
            parse('decision-makers:\n  - "alice"\n    - "bob"\n')

    def test_unknown_key_raises_on_emit(self):
        with self.assertRaises(FrontmatterError):
            emit({"not-a-real-field": "value"})

    def test_unknown_key_does_not_raise_on_parse(self):
        # parse() is syntax-only and does not know FIELD_ORDER; see report.
        result = parse('not-a-real-field: "value"\n')
        self.assertEqual(result, {"not-a-real-field": "value"})


class TestRejectionIntegers(unittest.TestCase):
    def test_leading_zero(self):
        with self.assertRaises(FrontmatterError):
            parse("schema: 01\n")

    def test_plus_sign(self):
        with self.assertRaises(FrontmatterError):
            parse("schema: +1\n")

    def test_float(self):
        with self.assertRaises(FrontmatterError):
            parse("schema: 1.0\n")

    def test_underscore_separator(self):
        with self.assertRaises(FrontmatterError):
            parse("schema: 1_000\n")


# ---------------------------------------------------------------------------
# Error quality
# ---------------------------------------------------------------------------

class TestErrorQuality(unittest.TestCase):
    def test_errors_are_frontmattererror_not_bare_builtins(self):
        cases = [
            'status: proposed\n',
            "1status: \"x\"\n",
            'decision-makers:\n  - 1\n',
            'status: "proposed"\nstatus: "x"\n',
        ]
        for text in cases:
            with self.assertRaises(FrontmatterError):
                parse(text)

    def test_mid_document_error_names_line_number(self):
        text = (
            'status: "proposed"\n'
            'date: "2026-08-12"\n'
            'schema: 01\n'
            'title: "x"\n'
        )
        with self.assertRaises(FrontmatterError) as ctx:
            parse(text)
        self.assertIn("line 3", str(ctx.exception))

    def test_error_message_names_line_for_duplicate_key(self):
        text = 'status: "proposed"\ndate: "2026-08-12"\nstatus: "accepted"\n'
        with self.assertRaises(FrontmatterError) as ctx:
            parse(text)
        self.assertIn("line 3", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
