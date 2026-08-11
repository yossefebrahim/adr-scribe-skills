"""Tests for deterministic ADR and patch digests."""

import copy
import math
import unittest
import unicodedata

from adr_scribe.digest import (
    DigestError,
    IMMUTABLE_EXCLUDED_KEYS,
    canonical_json,
    content_digest,
    patch_digest,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def valid_patch():
    return {
        "patch-version": 1,
        "repo-relative-ops": [
            {"op": "create-dir", "path": "docs/adr"},
            {
                "op": "create-file",
                "path": "docs/adr/a.md",
                "len": 4,
                "sha256": SHA_A,
            },
            {
                "op": "replace-file",
                "path": "docs/adr/index.md",
                "len": 8,
                "sha256": SHA_B,
                "expect-sha256": None,
            },
        ],
        "preconditions": {"head": "unborn", "dirty-overlap": []},
    }


class CanonicalJsonTests(unittest.TestCase):
    def test_key_order_is_unicode_code_point_order_and_insertion_independent(self):
        first = {"😀": 4, "é": 3, "z": 2, "a": 1}
        second = {"a": 1, "z": 2, "é": 3, "😀": 4}
        expected = '{"a":1,"z":2,"é":3,"😀":4}'.encode("utf-8")
        self.assertEqual(canonical_json(first), expected)
        self.assertEqual(canonical_json(second), expected)

    def test_rejects_float(self):
        with self.assertRaises(DigestError):
            canonical_json({"nested": [1.25]})

    def test_rejects_nan_and_infinity(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(DigestError):
                canonical_json(value)

    def test_rejects_non_string_key(self):
        with self.assertRaises(DigestError):
            canonical_json({1: "value"})

    def test_rejects_set(self):
        with self.assertRaises(DigestError):
            canonical_json({"value": {1, 2}})

    def test_rejects_tuple(self):
        with self.assertRaises(DigestError):
            canonical_json((1, 2))

    def test_rejects_bytes(self):
        with self.assertRaises(DigestError):
            canonical_json(b"bytes")

    def test_rejects_custom_object(self):
        class Custom:
            pass

        with self.assertRaises(DigestError):
            canonical_json(Custom())


class ContentDigestTests(unittest.TestCase):
    def test_golden_ascii_vector(self):
        frontmatter = {
            "id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "title": "Choose PostgreSQL",
            "schema": 1,
        }
        body = b"# Decision\n\nUse PostgreSQL.\n"
        self.assertEqual(
            content_digest(frontmatter, body),
            "sha256:778f44864b84af6114536622750b30b1f6e44eb2bbe1646c489e2d882d0efc62",
        )

    def test_golden_non_ascii_vector(self):
        frontmatter = {
            "id": "01BX5ZZKBKACTAV9WEVGEMMVRZ",
            "title": "Café service",
            "summary": "Région européenne",
        }
        body = "# Décision\n\nStockage durable.\n".encode("utf-8")
        self.assertEqual(
            content_digest(frontmatter, body),
            "sha256:3a779cd853d15ed03925f2966067d1cb6ac1dbccb2b27954e1a84c099e685aa9",
        )

    def test_golden_emoji_vector(self):
        frontmatter = {
            "id": "01H00000000000000000000000",
            "title": "Ship it 🚀",
            "tags": ["architecture", "📝"],
        }
        body = "# Decision 🚀\n\nProceed.\n".encode("utf-8")
        self.assertEqual(
            content_digest(frontmatter, body),
            "sha256:ed8919c81f1419112593d0fb7754c3e529c0123e48dc823fded50f5490ad8e2a",
        )

    def test_excluded_keys_do_not_change_digest(self):
        base = {
            "title": "Stable decision",
            "status": "proposed",
            "date": "2025-01-01",
            "acceptance": "pending",
            "content-digest": "sha256:" + "0" * 64,
        }
        expected = content_digest(base, b"body\n")
        self.assertEqual(
            IMMUTABLE_EXCLUDED_KEYS,
            frozenset({"status", "date", "acceptance", "content-digest"}),
        )
        for key in IMMUTABLE_EXCLUDED_KEYS:
            changed = dict(base)
            changed[key] = "completely different"
            with self.subTest(key=key):
                self.assertEqual(content_digest(changed, b"body\n"), expected)

    def test_non_excluded_key_changes_digest(self):
        original = {"title": "Stable decision", "schema": 1}
        changed = {"title": "Changed decision", "schema": 1}
        self.assertNotEqual(
            content_digest(original, b"body\n"),
            content_digest(changed, b"body\n"),
        )

    def test_one_byte_body_change_changes_digest(self):
        self.assertNotEqual(
            content_digest({"title": "A"}, b"abcdef"),
            content_digest({"title": "A"}, b"abcdeg"),
        )

    def test_trailing_newline_is_hashed_verbatim(self):
        without_newline = content_digest({"title": "A"}, b"body")
        one_newline = content_digest({"title": "A"}, b"body\n")
        two_newlines = content_digest({"title": "A"}, b"body\n\n")
        self.assertEqual(len({without_newline, one_newline, two_newlines}), 3)

    def test_body_whitespace_is_not_stripped_or_normalized(self):
        bodies = (b" body", b"body", b"body ", b"body\r\n", b"body\n")
        digests = {content_digest({"title": "A"}, body) for body in bodies}
        self.assertEqual(len(digests), len(bodies))

    def test_unicode_is_not_normalized(self):
        nfc = unicodedata.normalize("NFC", "Cafe\u0301")
        nfd = unicodedata.normalize("NFD", "Café")
        self.assertNotEqual(nfc, nfd)
        self.assertNotEqual(
            content_digest({"title": nfc}, nfc.encode("utf-8")),
            content_digest({"title": nfd}, nfd.encode("utf-8")),
        )

    def test_body_must_be_bytes(self):
        with self.assertRaises(DigestError):
            content_digest({}, "text")

    def test_frontmatter_body_boundary_is_domain_delimited(self):
        left = content_digest({"decision": "left"}, b"right\x00tail")
        moved = content_digest({"decision": "leftright"}, b"\x00tail")
        self.assertNotEqual(left, moved)


class PatchDigestTests(unittest.TestCase):
    def test_golden_patch_vector(self):
        patch = {
            "patch-version": 1,
            "repo-relative-ops": [
                {"op": "create-dir", "path": "docs/adr"},
                {
                    "op": "create-file",
                    "path": "docs/adr/a.md",
                    "len": 4,
                    "sha256": "0" * 64,
                },
            ],
            "preconditions": {"head": "unborn", "dirty-overlap": []},
        }
        self.assertEqual(
            patch_digest(patch),
            "sha256:2ca91564547316866b195b207758bce58dc310d2cc428a174bd3b01b12ebc5f8",
        )

    def test_content_and_patch_domains_differ(self):
        patch = {
            "patch-version": 1,
            "repo-relative-ops": [],
            "preconditions": {"head": "unborn", "dirty-overlap": []},
        }
        self.assertNotEqual(content_digest(patch, b""), patch_digest(patch))

    def test_rejects_bad_patch_version(self):
        patch = valid_patch()
        patch["patch-version"] = 2
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_rejects_ops_not_sorted_by_path_byte_order(self):
        patch = valid_patch()
        patch["repo-relative-ops"] = [
            {"op": "create-dir", "path": "docs/adr/a.b.md"},
            {"op": "create-dir", "path": "docs/adr/a-b.md"},
        ]
        self.assertLess(b"docs/adr/a-b.md", b"docs/adr/a.b.md")
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_accepts_raw_byte_order_for_punctuation_paths(self):
        patch = valid_patch()
        patch["repo-relative-ops"] = [
            {"op": "create-dir", "path": "docs/adr/a-b.md"},
            {"op": "create-dir", "path": "docs/adr/a.b.md"},
        ]
        patch_digest(patch)

    def test_rejects_duplicate_paths(self):
        patch = valid_patch()
        patch["repo-relative-ops"] = [
            {"op": "create-dir", "path": "docs/adr"},
            {"op": "create-dir", "path": "docs/adr"},
        ]
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def _assert_bad_path(self, path):
        patch = valid_patch()
        patch["repo-relative-ops"] = [{"op": "create-dir", "path": path}]
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_rejects_absolute_path(self):
        self._assert_bad_path("/docs/adr")

    def test_rejects_dot_dot_segment(self):
        self._assert_bad_path("docs/../adr")

    def test_rejects_dot_segment(self):
        self._assert_bad_path("docs/./adr")

    def test_rejects_empty_segment(self):
        self._assert_bad_path("docs//adr")

    def test_rejects_backslash(self):
        self._assert_bad_path("docs\\adr")

    def test_rejects_uppercase_sha256(self):
        patch = valid_patch()
        patch["repo-relative-ops"][1]["sha256"] = "A" * 64
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_rejects_short_sha256(self):
        patch = valid_patch()
        patch["repo-relative-ops"][1]["sha256"] = "a" * 63
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_rejects_non_null_non_hex_expect_sha256(self):
        patch = valid_patch()
        patch["repo-relative-ops"][2]["expect-sha256"] = "not-a-hash"
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_rejects_negative_len(self):
        patch = valid_patch()
        patch["repo-relative-ops"][1]["len"] = -1
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_rejects_unknown_op(self):
        patch = valid_patch()
        patch["repo-relative-ops"] = [
            {"op": "delete-file", "path": "docs/adr/a.md"}
        ]
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_rejects_unknown_key(self):
        patch = valid_patch()
        patch["repo-relative-ops"][0]["mode"] = "0755"
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_rejects_unknown_top_level_key(self):
        patch = valid_patch()
        patch["extra"] = True
        with self.assertRaises(DigestError):
            patch_digest(patch)

    def test_digest_is_independent_of_dict_insertion_order(self):
        first = valid_patch()
        second = {
            "preconditions": copy.deepcopy(first["preconditions"]),
            "repo-relative-ops": copy.deepcopy(first["repo-relative-ops"]),
            "patch-version": 1,
        }
        self.assertEqual(patch_digest(first), patch_digest(second))


if __name__ == "__main__":
    unittest.main()
