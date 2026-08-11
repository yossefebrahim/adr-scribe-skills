import unittest
import random
import time

from adr_scribe.ids import (
    IdError,
    new_ulid,
    is_valid_ulid,
    ulid_timestamp_ms,
    slugify,
    is_valid_slug,
    adr_filename,
)

class TestIds(unittest.TestCase):
    def test_format(self):
        ulid = new_ulid()
        self.assertEqual(len(ulid), 26)
        self.assertTrue(ulid.isupper())
        self.assertIn(ulid[0], "01234567")
        for char in ulid:
            self.assertIn(char, "0123456789ABCDEFGHJKMNPQRSTVWXYZ")
            self.assertNotIn(char, "ILOU")

    def test_round_trip_timestamp(self):
        test_times = [
            0,
            1,
            1234567890123,
            0xFFFFFFFFFFFF, # Ceiling 48-bit value
        ]
        for t in test_times:
            with self.subTest(t=t):
                ulid = new_ulid(now_ms=t)
                self.assertEqual(ulid_timestamp_ms(ulid), t)
                
    def test_timestamp_ceiling(self):
        with self.assertRaises(IdError):
            new_ulid(now_ms=0x1000000000000)
        with self.assertRaises(IdError):
            new_ulid(now_ms=-1)

    def test_monotonicity_within_millisecond(self):
        pinned_ms = 1629817200000
        ulids = []
        for _ in range(10000):
            ulids.append(new_ulid(now_ms=pinned_ms))
            
        # Assert strictly increasing and all unique
        for i in range(1, len(ulids)):
            self.assertGreater(ulids[i], ulids[i-1])
            
        self.assertEqual(len(set(ulids)), 10000)
        
        # Assert sorting a shuffled copy restores generation order
        shuffled = ulids.copy()
        random.shuffle(shuffled)
        shuffled.sort()
        self.assertEqual(shuffled, ulids)

    def test_uniqueness_at_volume(self):
        # We need to generate 200,000 ULIDs. Do not store list twice.
        start_time = time.time()
        ulids_set = set()
        for _ in range(200000):
            ulids_set.add(new_ulid())
            
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 15.0, "uniqueness test is too slow for CI")
        self.assertEqual(len(ulids_set), 200000)

    def test_validation_is_valid_ulid(self):
        valid = new_ulid()
        self.assertTrue(is_valid_ulid(valid))
        
        self.assertFalse(is_valid_ulid(valid.lower()))
        self.assertFalse(is_valid_ulid(valid[:25]))
        self.assertFalse(is_valid_ulid(valid + "0"))
        
        # Test I/L/O/U
        self.assertFalse(is_valid_ulid(valid[:-1] + "I"))
        self.assertFalse(is_valid_ulid(valid[:-1] + "L"))
        self.assertFalse(is_valid_ulid(valid[:-1] + "O"))
        self.assertFalse(is_valid_ulid(valid[:-1] + "U"))
        
        # Leading char 8-Z
        self.assertFalse(is_valid_ulid("8" + valid[1:]))
        self.assertFalse(is_valid_ulid("Z" + valid[1:]))
        
        self.assertFalse(is_valid_ulid(""))
        self.assertFalse(is_valid_ulid(123)) # type: ignore
        self.assertFalse(is_valid_ulid(None)) # type: ignore
        self.assertFalse(is_valid_ulid(" " + valid[:-1]))
        self.assertFalse(is_valid_ulid(valid[:-1] + " "))

    def test_slugify(self):
        cases = [
            ("Use Riverpod for state management", "use-riverpod-for-state-management"),
            (" leading and trailing punctuation! ", "leading-and-trailing-punctuation"),
            ("runs...of---separators", "runs-of-separators"),
            ("C++ / Rust?", "c-rust"),
            ("A" * 90, "a" * 80),
            # Title whose 80-char truncation lands on a hyphen (must not end in -)
            # 79 'a's, 1 space, 1 'b'. Total 81 chars.
            ("a" * 79 + " b", "a" * 79),
            ("Café menu", "caf-menu"),
        ]
        
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(slugify(title), expected)
                
        error_cases = [
            "!!!",
            "",
            "日本語",
        ]
        
        for title in error_cases:
            with self.subTest(title=title):
                with self.assertRaises(IdError):
                    slugify(title)
                    
    def test_is_valid_slug(self):
        self.assertTrue(is_valid_slug("valid-slug-123"))
        self.assertTrue(is_valid_slug("a"))
        
        self.assertFalse(is_valid_slug("UPPERCASE"))
        self.assertFalse(is_valid_slug(".."))
        self.assertFalse(is_valid_slug("/"))
        self.assertFalse(is_valid_slug("\\\\"))
        self.assertFalse(is_valid_slug("-leading"))
        self.assertFalse(is_valid_slug("trailing-"))
        self.assertFalse(is_valid_slug("consecutive--hyphens"))
        self.assertFalse(is_valid_slug(""))
        self.assertFalse(is_valid_slug("a" * 81))
        self.assertFalse(is_valid_slug(123)) # type: ignore
        self.assertFalse(is_valid_slug(None)) # type: ignore

    def test_adr_filename(self):
        ulid = new_ulid()
        slug = "valid-slug"
        expected = f"adr-{ulid.lower()}-{slug}.md"
        
        self.assertEqual(adr_filename(ulid, slug), expected)
        
        with self.assertRaises(IdError):
            adr_filename("invalid_ulid", slug)
            
        with self.assertRaises(IdError):
            adr_filename(ulid, "invalid_slug/")


class TestTrailingNewlineRegression(unittest.TestCase):
    """Regression: `re.match(r'...$')` also accepts a trailing newline.

    Left unfixed, `adr_filename` would happily build a path containing a
    newline character -- a path-validation bypass in the module whose job is
    safe path construction.
    """

    VALID = "01J000000000000000000000AA"

    def test_ulid_rejects_trailing_newline(self):
        self.assertTrue(is_valid_ulid(self.VALID))
        self.assertFalse(is_valid_ulid(self.VALID + "\n"))

    def test_ulid_rejects_all_whitespace_padding(self):
        for pad in ("\n", "\r", "\t", " ", "\r\n", "\x0b", "\x0c"):
            self.assertFalse(is_valid_ulid(self.VALID + pad), repr(pad))
            self.assertFalse(is_valid_ulid(pad + self.VALID), repr(pad))

    def test_slug_rejects_trailing_newline(self):
        self.assertTrue(is_valid_slug("abc"))
        self.assertFalse(is_valid_slug("abc\n"))

    def test_slug_rejects_all_whitespace_padding(self):
        for pad in ("\n", "\r", "\t", " ", "\r\n"):
            self.assertFalse(is_valid_slug("abc" + pad), repr(pad))
            self.assertFalse(is_valid_slug(pad + "abc"), repr(pad))

    def test_adr_filename_never_contains_a_newline(self):
        with self.assertRaises(IdError):
            adr_filename(self.VALID, "abc\n")
        with self.assertRaises(IdError):
            adr_filename(self.VALID + "\n", "abc")

    def test_no_generated_filename_contains_control_characters(self):
        name = adr_filename(new_ulid(now_ms=1), slugify("Use ULIDs for record ids"))
        self.assertFalse(any(ord(ch) < 0x20 for ch in name), repr(name))
