"""Symlink-hostile, root-confined filesystem primitives.

Every destination path is resolved **component by component** against an open
directory handle, with ``O_NOFOLLOW`` at each step. This is the requirement
that chose Python for the helper runtime: Node exposes no ``openat``/``dir_fd``
family, so it cannot do this without native code, and a ``realpath``-then-open
check has a time-of-check/time-of-use race a hostile repo can win.

The rule is absolute: a symlink anywhere in a destination path is refused, even
when it currently resolves inside the repository. "Currently" is the problem --
it can stop being true between the check and the write.

Stdlib only, Python 3.9 floor. POSIX only (macOS and Linux); Windows is out of
scope for the internal alpha and raises a clear error.
"""

from __future__ import annotations

import errno
import os
import stat
from typing import List, Optional, Sequence, Tuple

_REQUIRED_DIR_FD = ("open", "mkdir", "unlink", "rename", "stat", "link")


class PathError(ValueError):
    """Raised when a path is unsafe, escapes the root, or cannot be used."""


class UnsupportedPlatform(PathError):
    """Raised when the platform lacks the primitives this module requires."""


def check_platform() -> None:
    """Raise if the running platform cannot provide the required guarantees."""
    if os.name != "posix":
        raise UnsupportedPlatform(
            "adr-scribe requires POSIX directory-relative operations; "
            "this platform is %r" % os.name
        )
    if not hasattr(os, "O_NOFOLLOW"):
        raise UnsupportedPlatform("os.O_NOFOLLOW is unavailable")
    missing = [
        name for name in _REQUIRED_DIR_FD
        if getattr(os, name, None) not in os.supports_dir_fd
    ]
    if missing:
        raise UnsupportedPlatform(
            "these calls lack dir_fd support here: %s" % ", ".join(missing)
        )


# --------------------------------------------------------------------------
# relative path validation
# --------------------------------------------------------------------------

def check_relpath(rel: str) -> Optional[str]:
    """Return an error message if ``rel`` is not a safe repo-relative path."""
    if not isinstance(rel, str):
        return "path must be a string"
    if rel == "":
        return "path must not be empty"
    if rel.startswith("/"):
        return "path must be repo-relative, not absolute"
    if "\\" in rel:
        return "path must use '/' separators"
    if "\x00" in rel:
        return "path must not contain a NUL byte"
    for ch in rel:
        if ord(ch) < 0x20:
            return "path must not contain control characters"
    for segment in rel.split("/"):
        if segment == "":
            return "path must not contain an empty segment"
        if segment == ".":
            return "path must not contain a '.' segment"
        if segment == "..":
            return "path must not contain a '..' segment"
    return None


def split_relpath(rel: str) -> List[str]:
    """Validate and split a repo-relative path into components."""
    problem = check_relpath(rel)
    if problem:
        raise PathError("%s: %r" % (problem, rel))
    return rel.split("/")


# --------------------------------------------------------------------------
# directory handles
# --------------------------------------------------------------------------

def open_root(path: str) -> int:
    """Open the repository root as a directory handle.

    The root itself is opened with ``O_NOFOLLOW``: if the caller was handed a
    symlinked root, that is refused too.
    """
    check_platform()
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise PathError("repository root is a symlink: %s" % path)
        if exc.errno == errno.ENOTDIR:
            raise PathError("repository root is not a directory: %s" % path)
        raise PathError("cannot open repository root %s: %s" % (path, exc))


def _open_child_dir(parent_fd: int, name: str, context: str) -> int:
    try:
        return os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
        )
    except OSError as exc:
        if exc.errno not in (errno.ELOOP, errno.EMLINK, errno.ENOTDIR):
            raise
        # Which errno a symlink-to-directory produces under O_DIRECTORY|
        # O_NOFOLLOW is platform-specific: Linux gives ELOOP, macOS gives
        # ENOTDIR. Both refuse correctly, but reporting "not a directory" for
        # a symlink would mislead whoever is debugging the refusal, so ask the
        # filesystem what the entry actually is.
        if entry_kind(parent_fd, name) == "symlink":
            raise PathError(
                "refusing to follow the symlink %r in %s" % (name, context)
            )
        raise PathError("%r in %s is not a directory" % (name, context))


def resolve_dir(root_fd: int, components: Sequence[str], create: bool = False,
                mode: int = 0o755) -> Tuple[int, List[str]]:
    """Walk ``components`` beneath ``root_fd`` with no-follow at each step.

    Returns ``(dir_fd, created)`` where ``created`` lists the components this
    call created, innermost last -- the transaction journal needs that list so
    recovery can remove only directories it made, and only while still empty.

    Raises :class:`PathError` on any symlink, on a non-directory component, and
    (when ``create`` is false) on a missing component.
    """
    current = os.dup(root_fd)
    created: List[str] = []
    walked: List[str] = []
    try:
        for name in components:
            if name in ("", ".", ".."):
                raise PathError("unsafe path component %r" % name)
            context = "/".join(walked) or "<root>"
            try:
                nxt = _open_child_dir(current, name, context)
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise PathError("cannot open %r in %s: %s" % (name, context, exc))
                if not create:
                    raise PathError("missing directory %r in %s" % (name, context))
                try:
                    os.mkdir(name, mode, dir_fd=current)
                except FileExistsError:
                    pass  # lost a benign race; re-open below and re-check
                else:
                    created.append("/".join(walked + [name]))
                fsync_fd(current)
                nxt = _open_child_dir(current, name, context)
            os.close(current)
            current = nxt
            walked.append(name)
        return current, created
    except Exception:
        os.close(current)
        raise


def fsync_fd(fd: int) -> None:
    """fsync a directory (or file) handle, tolerating platforms that refuse."""
    try:
        os.fsync(fd)
    except OSError as exc:  # pragma: no cover - platform dependent
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EBADF):
            raise


# --------------------------------------------------------------------------
# inspection
# --------------------------------------------------------------------------

def entry_kind(dir_fd: int, name: str) -> str:
    """Return ``'absent'``, ``'symlink'``, ``'dir'``, ``'file'`` or ``'other'``."""
    try:
        st = os.lstat(name, dir_fd=dir_fd)
    except FileNotFoundError:
        return "absent"
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "other"


def assert_not_symlink(dir_fd: int, name: str) -> None:
    if entry_kind(dir_fd, name) == "symlink":
        raise PathError("refusing to write through the symlink %r" % name)


def read_file(dir_fd: int, name: str, max_bytes: Optional[int] = None) -> bytes:
    """Read a regular file with ``O_NOFOLLOW``.

    Used for evidence gathering as well as writes: a symlinked untracked file
    must never be followed, or the read bound escapes the repository.
    """
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise PathError("refusing to read through the symlink %r" % name)
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise PathError("%r is not a regular file" % name)
        if max_bytes is not None and st.st_size > max_bytes:
            raise PathError(
                "%r is %d bytes, above the %d-byte bound" % (name, st.st_size, max_bytes)
            )
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            if max_bytes is not None and sum(map(len, chunks)) > max_bytes:
                raise PathError("%r exceeded the %d-byte bound while reading"
                                % (name, max_bytes))
        return b"".join(chunks)
    finally:
        os.close(fd)


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------

def write_new_file(dir_fd: int, name: str, data: bytes, mode: int = 0o644) -> None:
    """Create ``name`` exclusively and write ``data``, then fsync file and dir.

    ``O_EXCL`` makes this atomic against a concurrent creator: if the target
    appears first, this raises rather than overwriting it.
    """
    if not isinstance(data, bytes):
        raise PathError("data must be bytes")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, mode, dir_fd=dir_fd)
    except FileExistsError:
        raise PathError("refusing to overwrite the existing file %r" % name)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise PathError("refusing to write through the symlink %r" % name)
        raise
    try:
        written = 0
        while written < len(data):
            written += os.write(fd, data[written:])
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_fd(dir_fd)


def link_into_place(src_dir_fd: int, src_name: str,
                    dst_dir_fd: int, dst_name: str) -> None:
    """Hard-link a staged file into its destination, exclusively and atomically.

    ``link`` fails with ``EEXIST`` if the destination exists, which gives
    exclusive creation and atomicity in one call -- the property step 8 of the
    write transaction depends on.
    """
    try:
        os.link(src_name, dst_name,
                src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd,
                follow_symlinks=False)
    except FileExistsError:
        raise PathError("destination %r already exists" % dst_name)
    except OSError as exc:
        if exc.errno in (errno.EXDEV, errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP):
            raise PathError(
                "cannot hard-link %r into place (%s); staging must live on the "
                "same filesystem as the destination" % (dst_name, exc.strerror)
            )
        raise
    fsync_fd(dst_dir_fd)


def atomic_replace(src_dir_fd: int, src_name: str,
                   dst_dir_fd: int, dst_name: str) -> None:
    """Atomically replace ``dst_name`` with ``src_name``.

    Used only for the index, which is the one file the transaction may replace
    rather than create. The caller must have re-read and hash-checked the
    destination immediately beforehand.
    """
    assert_not_symlink(dst_dir_fd, dst_name)
    try:
        os.rename(src_name, dst_name,
                  src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise PathError(
                "cannot rename across filesystems; staging must live on the "
                "same filesystem as %r" % dst_name
            )
        raise
    fsync_fd(dst_dir_fd)


def remove_dir_if_empty(parent_fd: int, name: str) -> bool:
    """Remove ``name`` only if empty. Returns True if it was removed.

    Recovery uses this: a directory the transaction created is removed only
    while still empty; otherwise it is left in place and reported.
    """
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except FileNotFoundError:
        return False
    except OSError as exc:
        if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
            return False
        raise
    fsync_fd(parent_fd)
    return True
