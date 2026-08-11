"""Tests for the symlink-hostile path layer.

The symlink cases are the point. Each one models a hostile or careless
repository that would let a write escape the root or clobber something the
transaction never approved.
"""

import os
import shutil
import tempfile
import unittest

from adr_scribe import paths as P


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "repo")
        self.outside = os.path.join(self.tmp, "outside")
        os.makedirs(os.path.join(self.root, "docs", "adr"))
        os.makedirs(self.outside)
        self.root_fd = P.open_root(self.root)

    def tearDown(self):
        try:
            os.close(self.root_fd)
        except OSError:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestRelpathValidation(unittest.TestCase):
    def test_accepts_ordinary_paths(self):
        for good in ("docs/adr/a.md", "a", "a/b/c.md", ".hidden/x"):
            self.assertIsNone(P.check_relpath(good), good)

    def test_rejects_unsafe_paths(self):
        for bad in ("", "/abs", "a//b", "a/./b", "a/../b", "..", "a\\b",
                    "a\x00b", "a\nb", "a\tb"):
            self.assertIsNotNone(P.check_relpath(bad), repr(bad))

    def test_split_raises_on_unsafe(self):
        with self.assertRaises(P.PathError):
            P.split_relpath("../escape")
        self.assertEqual(P.split_relpath("docs/adr"), ["docs", "adr"])


class TestResolveDir(Base):
    def test_walks_existing_directories(self):
        fd, created = P.resolve_dir(self.root_fd, ["docs", "adr"])
        try:
            self.assertEqual(created, [])
            self.assertEqual(P.entry_kind(fd, "."), "dir")
        finally:
            os.close(fd)

    def test_missing_component_without_create_raises(self):
        with self.assertRaises(P.PathError):
            P.resolve_dir(self.root_fd, ["nope", "deeper"])

    def test_create_reports_what_it_created(self):
        fd, created = P.resolve_dir(self.root_fd, ["build", "out"], create=True)
        try:
            self.assertEqual(created, ["build", "build/out"])
            self.assertTrue(os.path.isdir(os.path.join(self.root, "build", "out")))
        finally:
            os.close(fd)

    def test_existing_dirs_are_not_reported_as_created(self):
        fd, created = P.resolve_dir(self.root_fd, ["docs", "adr"], create=True)
        os.close(fd)
        self.assertEqual(created, [])

    def test_refuses_a_symlinked_intermediate_directory(self):
        # docs/link -> outside/  (escapes the repo entirely)
        os.symlink(self.outside, os.path.join(self.root, "docs", "link"))
        with self.assertRaises(P.PathError) as ctx:
            P.resolve_dir(self.root_fd, ["docs", "link"])
        self.assertIn("symlink", str(ctx.exception))

    def test_refuses_a_symlink_that_resolves_inside_the_repo(self):
        # The dangerous case: it points somewhere legitimate *right now*.
        os.symlink(os.path.join(self.root, "docs", "adr"),
                   os.path.join(self.root, "docs", "alias"))
        with self.assertRaises(P.PathError):
            P.resolve_dir(self.root_fd, ["docs", "alias"])

    def test_refuses_a_relative_symlink_escaping_upward(self):
        os.symlink("../../outside", os.path.join(self.root, "docs", "up"))
        with self.assertRaises(P.PathError):
            P.resolve_dir(self.root_fd, ["docs", "up"])

    def test_refuses_a_file_where_a_directory_is_expected(self):
        with open(os.path.join(self.root, "docs", "file"), "w") as fh:
            fh.write("x")
        with self.assertRaises(P.PathError):
            P.resolve_dir(self.root_fd, ["docs", "file"])

    def test_rejects_traversal_components(self):
        for bad in ("..", ".", ""):
            with self.assertRaises(P.PathError):
                P.resolve_dir(self.root_fd, ["docs", bad])


class TestOpenRoot(Base):
    def test_symlinked_root_is_refused(self):
        link = os.path.join(self.tmp, "rootlink")
        os.symlink(self.root, link)
        with self.assertRaises(P.PathError):
            P.open_root(link)

    def test_missing_root_raises_patherror(self):
        with self.assertRaises(P.PathError):
            P.open_root(os.path.join(self.tmp, "nope"))


class TestWrites(Base):
    def dir_fd(self):
        fd, _ = P.resolve_dir(self.root_fd, ["docs", "adr"])
        return fd

    def test_write_new_file_creates_and_reads_back(self):
        fd = self.dir_fd()
        try:
            P.write_new_file(fd, "a.md", b"hello\n")
            self.assertEqual(P.read_file(fd, "a.md"), b"hello\n")
        finally:
            os.close(fd)

    def test_write_new_file_refuses_to_overwrite(self):
        fd = self.dir_fd()
        try:
            P.write_new_file(fd, "a.md", b"one")
            with self.assertRaises(P.PathError):
                P.write_new_file(fd, "a.md", b"two")
            self.assertEqual(P.read_file(fd, "a.md"), b"one")
        finally:
            os.close(fd)

    def test_write_new_file_refuses_a_symlinked_target(self):
        target = os.path.join(self.outside, "victim.txt")
        with open(target, "w") as fh:
            fh.write("original")
        os.symlink(target, os.path.join(self.root, "docs", "adr", "evil.md"))
        fd = self.dir_fd()
        try:
            with self.assertRaises(P.PathError):
                P.write_new_file(fd, "evil.md", b"pwned")
        finally:
            os.close(fd)
        with open(target) as fh:
            self.assertEqual(fh.read(), "original")

    def test_read_file_refuses_a_symlink(self):
        secret = os.path.join(self.outside, "secret.txt")
        with open(secret, "w") as fh:
            fh.write("token")
        os.symlink(secret, os.path.join(self.root, "docs", "adr", "peek.md"))
        fd = self.dir_fd()
        try:
            with self.assertRaises(P.PathError):
                P.read_file(fd, "peek.md")
        finally:
            os.close(fd)

    def test_read_file_enforces_a_size_bound(self):
        fd = self.dir_fd()
        try:
            P.write_new_file(fd, "big.md", b"x" * 5000)
            with self.assertRaises(P.PathError):
                P.read_file(fd, "big.md", max_bytes=1024)
            self.assertEqual(len(P.read_file(fd, "big.md", max_bytes=10000)), 5000)
        finally:
            os.close(fd)

    def test_link_into_place_is_exclusive(self):
        stage = self.dir_fd()
        try:
            P.write_new_file(stage, "staged.tmp", b"payload")
            P.link_into_place(stage, "staged.tmp", stage, "final.md")
            self.assertEqual(P.read_file(stage, "final.md"), b"payload")
            with self.assertRaises(P.PathError):
                P.link_into_place(stage, "staged.tmp", stage, "final.md")
        finally:
            os.close(stage)

    def test_atomic_replace_swaps_content(self):
        fd = self.dir_fd()
        try:
            P.write_new_file(fd, "README.md", b"old")
            P.write_new_file(fd, "new.tmp", b"new")
            P.atomic_replace(fd, "new.tmp", fd, "README.md")
            self.assertEqual(P.read_file(fd, "README.md"), b"new")
            self.assertEqual(P.entry_kind(fd, "new.tmp"), "absent")
        finally:
            os.close(fd)

    def test_atomic_replace_refuses_a_symlinked_destination(self):
        target = os.path.join(self.outside, "victim.md")
        with open(target, "w") as fh:
            fh.write("original")
        fd = self.dir_fd()
        try:
            os.symlink(target, os.path.join(self.root, "docs", "adr", "README.md"))
            P.write_new_file(fd, "new.tmp", b"new")
            with self.assertRaises(P.PathError):
                P.atomic_replace(fd, "new.tmp", fd, "README.md")
        finally:
            os.close(fd)
        with open(target) as fh:
            self.assertEqual(fh.read(), "original")


class TestEntryKindAndCleanup(Base):
    def test_entry_kind(self):
        fd, _ = P.resolve_dir(self.root_fd, ["docs"])
        try:
            self.assertEqual(P.entry_kind(fd, "adr"), "dir")
            self.assertEqual(P.entry_kind(fd, "missing"), "absent")
            os.symlink("adr", os.path.join(self.root, "docs", "l"))
            self.assertEqual(P.entry_kind(fd, "l"), "symlink")
            P.write_new_file(fd, "f", b"x")
            self.assertEqual(P.entry_kind(fd, "f"), "file")
        finally:
            os.close(fd)

    def test_remove_dir_if_empty_only_removes_empty(self):
        fd, _ = P.resolve_dir(self.root_fd, ["docs"])
        try:
            os.mkdir("empty", dir_fd=fd)
            self.assertTrue(P.remove_dir_if_empty(fd, "empty"))
            self.assertFalse(P.remove_dir_if_empty(fd, "missing"))
        finally:
            os.close(fd)

    def test_remove_dir_if_empty_leaves_a_populated_dir(self):
        fd, _ = P.resolve_dir(self.root_fd, ["docs", "adr"])
        try:
            P.write_new_file(fd, "keep.md", b"x")
        finally:
            os.close(fd)
        parent, _ = P.resolve_dir(self.root_fd, ["docs"])
        try:
            self.assertFalse(P.remove_dir_if_empty(parent, "adr"))
            self.assertTrue(os.path.exists(os.path.join(self.root, "docs", "adr", "keep.md")))
        finally:
            os.close(parent)


class TestPlatform(unittest.TestCase):
    def test_platform_supports_required_primitives(self):
        P.check_platform()  # must not raise on a supported platform


if __name__ == "__main__":
    unittest.main()
