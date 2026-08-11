"""Cross-module integration tests.

Each module was built in isolation by a different implementer against
CONTRACT.md. These tests exercise the seam between them -- which is where the
first real defect appeared: the contract described nested frontmatter maps as
scalars-only, but a real record needs list values in `evidence` and
`record-confirmation`. No single-module suite could have caught that.
"""

import unicodedata
import unittest

from adr_scribe import _frontmatter as fm
from adr_scribe import digest, index
from adr_scribe.ids import adr_filename, new_ulid, slugify


def make_record():
    ulid = new_ulid(now_ms=1_760_000_000_000)
    return ulid, {
        "status": "proposed",
        "date": "2026-08-12",
        "decision-makers": ["Joe"],
        "consulted": [],
        "informed": [],
        "schema": "adr-scribe/v1",
        "id": "ADR-" + ulid,
        "title": "Use ULIDs for record identity",
        "summary": "In the context of concurrent authors, we chose ULIDs to avoid coordination.",
        "decision-date": "2026-08-12",
        "applies-to": ["skills/adr/**"],
        "supersedes": [],
        "roadmap-ref": None,
        "content-digest": "sha256:" + "0" * 64,
        "acceptance": None,
        "provenance": {
            "context": "code-observed",
            "decision": "developer-stated",
            "drivers": "developer-confirmed",
            "alternatives": "developer-stated",
            "consequences": "developer-confirmed",
            "rules": "developer-confirmed",
        },
        "evidence": {
            "commits": [],
            "working-tree-files": ["skills/adr/scripts/adr_scribe/ids.py"],
        },
        "record-confirmation": {"confirmed-by": ["Joe"]},
    }


BODY = b"# ADR\n\n> summary\n\n## Context and Problem Statement\n\nText.\n"


class TestRealRecordRoundTrip(unittest.TestCase):
    def test_full_record_emits_and_parses(self):
        _, rec = make_record()
        text = fm.emit(rec)
        self.assertEqual(dict(fm.parse(text)), rec)
        self.assertEqual(fm.emit(fm.parse(text)), text)

    def test_document_split_preserves_body_verbatim(self):
        _, rec = make_record()
        doc = ("---\n" + fm.emit(rec) + "---\n").encode("utf-8") + BODY
        ftext, body = fm.split_document(doc)
        self.assertEqual(body, BODY)
        self.assertEqual(dict(fm.parse(ftext)), rec)

    def test_digest_survives_the_full_round_trip(self):
        _, rec = make_record()
        doc = ("---\n" + fm.emit(rec) + "---\n").encode("utf-8") + BODY
        ftext, body = fm.split_document(doc)
        self.assertEqual(
            digest.content_digest(fm.parse(ftext), body),
            digest.content_digest(rec, BODY),
        )


class TestImmutabilityContract(unittest.TestCase):
    """The property the v1.1 acceptance flow depends on."""

    def test_lifecycle_fields_do_not_affect_content_digest(self):
        _, rec = make_record()
        before = digest.content_digest(rec, BODY)
        accepted = dict(rec)
        accepted["status"] = "accepted"
        accepted["date"] = "2030-01-01"
        accepted["acceptance"] = None
        accepted["content-digest"] = "sha256:" + "f" * 64
        self.assertEqual(digest.content_digest(accepted, BODY), before)

    def test_decision_content_does_affect_content_digest(self):
        _, rec = make_record()
        before = digest.content_digest(rec, BODY)
        for key, value in (
            ("title", "Something else"),
            ("summary", "A different summary."),
            ("applies-to", ["other/**"]),
        ):
            mutated = dict(rec)
            mutated[key] = value
            self.assertNotEqual(digest.content_digest(mutated, BODY), before, key)

    def test_body_change_changes_content_digest(self):
        _, rec = make_record()
        self.assertNotEqual(
            digest.content_digest(rec, BODY + b"\n"),
            digest.content_digest(rec, BODY),
        )

    def test_no_unicode_normalization_across_modules(self):
        _, rec = make_record()
        nfc, nfd = dict(rec), dict(rec)
        nfc["title"] = unicodedata.normalize("NFC", "Café strategy")
        nfd["title"] = unicodedata.normalize("NFD", "Café strategy")
        self.assertNotEqual(nfc["title"], nfd["title"])
        self.assertNotEqual(
            digest.content_digest(nfc, BODY), digest.content_digest(nfd, BODY)
        )
        # and the parser preserves each form byte for byte
        self.assertEqual(dict(fm.parse(fm.emit(nfd)))["title"], nfd["title"])


class TestIdsToIndex(unittest.TestCase):
    def test_generated_filename_is_safe(self):
        ulid, rec = make_record()
        name = adr_filename(ulid, slugify(rec["title"]))
        self.assertTrue(name.startswith("adr-" + ulid.lower() + "-"))
        self.assertTrue(name.endswith(".md"))
        self.assertFalse(any(ord(c) < 0x20 for c in name))
        self.assertNotIn("/", name)
        self.assertNotIn("..", name)

    def test_parsed_record_renders_into_the_index(self):
        _, rec = make_record()
        parsed = fm.parse(fm.emit(rec))
        row = {k: parsed[k] for k in ("id", "title", "status", "date", "summary")}
        out = index.render_index(None, [row])
        self.assertIn(rec["title"], out)
        self.assertIn(rec["id"], out)

    def test_index_stays_one_row_per_record_when_title_contains_delimiters(self):
        _, rec = make_record()
        rec["title"] = "Pipes | and \\ backslashes"
        parsed = fm.parse(fm.emit(rec))
        row = {k: parsed[k] for k in ("id", "title", "status", "date", "summary")}
        body = index.render_table([row]).splitlines()[-1]
        unescaped = sum(
            1 for i, ch in enumerate(body) if ch == "|" and (i == 0 or body[i - 1] != "\\")
        )
        self.assertEqual(unescaped, 6, body)


if __name__ == "__main__":
    unittest.main()
