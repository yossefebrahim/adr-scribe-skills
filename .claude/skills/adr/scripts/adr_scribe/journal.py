"""Cooperative lock and write-ahead journal for the apply transaction.

Two ideas carry the design:

**The lock is a directory.** ``mkdir`` is atomic on every POSIX filesystem, so
creating ``.adr-scribe.lock/`` either succeeds or proves someone else holds it.
It lives at the repository root so it exists before first-run ``docs/adr/``
bootstrap needs it.

**The journal records expected hashes before anything is written.** The phase
label always lags the operation -- there is a window where a file exists but
the journal still says ``prepared``. Recovery therefore identifies state by
*hash*, never by phase: a file whose bytes match the journal's expected value
can only be ours, so it is safe to adopt. A recovery routine that trusted the
phase label could not recover the most likely crash windows.

Stdlib only, Python 3.9 floor.
"""

from __future__ import annotations

import errno
import json
import os
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from . import paths as P

LOCK_DIRNAME = ".adr-scribe.lock"
COMPLETED_PREFIX = ".adr-scribe-completed-"
OWNER_FILE = "owner.json"
JOURNAL_FILE = "journal.json"
TMP_DIRNAME = "tmp"
PREIMAGE_DIRNAME = "preimage"

DEFAULT_STALE_SECONDS = 900

#: Ordered phases. Recovery compares against reality, not against this order
#: alone, but the order defines what "resume forward" means.
PHASES = ("prepared", "adrs-written", "index-replaced", "verified", "complete")

JOURNAL_VERSION = 1


class LockError(RuntimeError):
    """Raised when the lock cannot be acquired or safely reclaimed."""

    def __init__(self, message: str, needs_confirmation: bool = False) -> None:
        super().__init__(message)
        self.needs_confirmation = needs_confirmation


class JournalError(RuntimeError):
    """Raised when the journal is missing, corrupt, or inconsistent."""


# --------------------------------------------------------------------------
# process identity
# --------------------------------------------------------------------------

def process_start_token(pid: int) -> Optional[str]:
    """Return a stable token identifying *this instance* of ``pid``.

    A bare PID is not enough: PIDs are recycled, and reclaiming a lock owned by
    an unrelated process that happens to reuse the number would be a data-loss
    bug. ``ps -o lstart`` is portable across macOS and Linux.
    """
    try:
        proc = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    token = proc.stdout.decode("utf-8", "replace").strip()
    return token or None


def owner_is_live(owner: Dict[str, Any]) -> bool:
    """True if the recorded owner process still exists *and* is the same one."""
    pid = owner.get("pid")
    if not isinstance(pid, int):
        return False
    token = process_start_token(pid)
    if token is None:
        return False
    recorded = owner.get("start-token")
    if not isinstance(recorded, str):
        # We cannot prove identity; treat as live so we never steal a lock.
        return True
    return token == recorded


# --------------------------------------------------------------------------
# lock
# --------------------------------------------------------------------------

def _read_json(dir_fd: int, name: str) -> Optional[Dict[str, Any]]:
    try:
        raw = P.read_file(dir_fd, name)
    except (FileNotFoundError, P.PathError):
        return None
    except OSError:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json_atomic(dir_fd: int, name: str, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    tmp = name + ".tmp"
    if P.entry_kind(dir_fd, tmp) != "absent":
        os.unlink(tmp, dir_fd=dir_fd)
    P.write_new_file(dir_fd, tmp, data)
    os.rename(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    P.fsync_fd(dir_fd)


def acquire(root_fd: int, stale_seconds: int = DEFAULT_STALE_SECONDS,
            force_reclaim: bool = False) -> int:
    """Create and open the lock directory. Returns its file descriptor.

    Raises :class:`LockError` when another live process holds it, or when the
    owner record is missing/corrupt and a human must confirm no ``apply-record``
    is running (``needs_confirmation`` is set on the exception).
    """
    P.assert_not_symlink(root_fd, LOCK_DIRNAME)
    try:
        os.mkdir(LOCK_DIRNAME, 0o755, dir_fd=root_fd)
    except FileExistsError:
        _consider_reclaim(root_fd, stale_seconds, force_reclaim)
        try:
            os.mkdir(LOCK_DIRNAME, 0o755, dir_fd=root_fd)
        except FileExistsError:
            raise LockError("another adr-scribe process holds the lock")
    except OSError as exc:
        if exc.errno == errno.EACCES:
            raise LockError("cannot create the lock: permission denied")
        raise
    P.fsync_fd(root_fd)
    lock_fd = os.open(LOCK_DIRNAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                      dir_fd=root_fd)
    write_owner(lock_fd)
    return lock_fd


def _consider_reclaim(root_fd: int, stale_seconds: int, force: bool) -> None:
    """Remove a stale lock, or raise explaining why we will not."""
    try:
        lock_fd = os.open(LOCK_DIRNAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=root_fd)
    except OSError as exc:
        raise LockError("lock exists but cannot be inspected: %s" % exc)
    try:
        owner = _read_json(lock_fd, OWNER_FILE)
        journal = _read_json(lock_fd, JOURNAL_FILE)
        if journal is not None and not force:
            raise LockError(
                "the lock holds a journal from an interrupted transaction; "
                "run `apply-record --recover` instead of starting a new write"
            )
        if owner is None:
            if not force:
                raise LockError(
                    "the lock has no readable owner record. Confirm that no "
                    "apply-record process is running, then re-run with "
                    "--force-reclaim",
                    needs_confirmation=True,
                )
        else:
            if owner_is_live(owner) and not force:
                raise LockError("another adr-scribe process (pid %s) holds the lock"
                                % owner.get("pid"))
            age = time.time() - float(owner.get("timestamp") or 0)
            if age < stale_seconds and not force:
                raise LockError(
                    "the lock is %ds old, below the %ds stale threshold; "
                    "waiting is safer than stealing it" % (int(age), stale_seconds)
                )
        names = sorted(os.listdir(lock_fd))
    finally:
        os.close(lock_fd)

    _remove_lock_tree(root_fd, LOCK_DIRNAME, names)


def _remove_lock_tree(parent_fd: int, dirname: str, names: List[str]) -> None:
    lock_fd = os.open(dirname, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                      dir_fd=parent_fd)
    try:
        for name in names:
            kind = P.entry_kind(lock_fd, name)
            if kind == "dir":
                sub = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=lock_fd)
                try:
                    inner = sorted(os.listdir(sub))
                finally:
                    os.close(sub)
                _remove_lock_tree(lock_fd, name, inner)
            else:
                os.unlink(name, dir_fd=lock_fd)
    finally:
        os.close(lock_fd)
    os.rmdir(dirname, dir_fd=parent_fd)
    P.fsync_fd(parent_fd)


def write_owner(lock_fd: int) -> Dict[str, Any]:
    pid = os.getpid()
    owner = {
        "pid": pid,
        "start-token": process_start_token(pid),
        "host": socket.gethostname(),
        "timestamp": time.time(),
    }
    _write_json_atomic(lock_fd, OWNER_FILE, owner)
    return owner


def read_owner(lock_fd: int) -> Optional[Dict[str, Any]]:
    return _read_json(lock_fd, OWNER_FILE)


def open_existing(root_fd: int) -> Optional[int]:
    """Open an existing lock directory, or return None if there is none."""
    if P.entry_kind(root_fd, LOCK_DIRNAME) != "dir":
        return None
    return os.open(LOCK_DIRNAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                   dir_fd=root_fd)


def release(root_fd: int, lock_fd: int) -> None:
    """Release the lock via the completed-rename, then remove it.

    The rename makes release atomic while preserving recovery state: a crash
    between rename and removal leaves ``.adr-scribe-completed-*`` behind, which
    recovery recognises as "finished, just tidy up".
    """
    marker = COMPLETED_PREFIX + str(int(time.time() * 1000))
    os.close(lock_fd)
    try:
        os.rename(LOCK_DIRNAME, marker, src_dir_fd=root_fd, dst_dir_fd=root_fd)
    except FileNotFoundError:
        return
    P.fsync_fd(root_fd)
    cleanup_completed(root_fd)


def cleanup_completed(root_fd: int) -> List[str]:
    """Remove any ``.adr-scribe-completed-*`` directories. Idempotent."""
    removed = []
    for name in sorted(os.listdir(root_fd)):
        if not name.startswith(COMPLETED_PREFIX):
            continue
        if P.entry_kind(root_fd, name) != "dir":
            continue
        sub = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                      dir_fd=root_fd)
        try:
            inner = sorted(os.listdir(sub))
        finally:
            os.close(sub)
        _remove_lock_tree(root_fd, name, inner)
        removed.append(name)
    return removed


# --------------------------------------------------------------------------
# journal
# --------------------------------------------------------------------------

def new_journal(patch_digest: str, preconditions: Dict[str, Any],
                outputs: List[Dict[str, Any]], creates_dirs: List[str],
                index_op: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "journal-version": JOURNAL_VERSION,
        "phase": "prepared",
        "patch-digest": patch_digest,
        "preconditions": preconditions,
        "outputs": outputs,
        "creates-dirs": creates_dirs,
        "index": index_op,
        "created-dirs": [],
        "started-at": time.time(),
        "updated-at": time.time(),
    }


def write_journal(lock_fd: int, journal: Dict[str, Any]) -> None:
    journal["updated-at"] = time.time()
    _write_json_atomic(lock_fd, JOURNAL_FILE, journal)


def read_journal(lock_fd: int) -> Optional[Dict[str, Any]]:
    journal = _read_json(lock_fd, JOURNAL_FILE)
    if journal is None:
        return None
    if journal.get("journal-version") != JOURNAL_VERSION:
        raise JournalError("unsupported journal-version %r"
                           % journal.get("journal-version"))
    if journal.get("phase") not in PHASES:
        raise JournalError("journal has an unknown phase %r" % journal.get("phase"))
    return journal


def set_phase(lock_fd: int, journal: Dict[str, Any], phase: str) -> None:
    if phase not in PHASES:
        raise JournalError("unknown phase %r" % phase)
    journal["phase"] = phase
    write_journal(lock_fd, journal)


def ensure_subdir(lock_fd: int, name: str) -> int:
    if P.entry_kind(lock_fd, name) == "absent":
        os.mkdir(name, 0o755, dir_fd=lock_fd)
        P.fsync_fd(lock_fd)
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                   dir_fd=lock_fd)


def crash_point(name: str) -> None:
    """Test-only crash injection.

    Inert unless ``ADR_SCRIBE_CRASH_AT`` names this point. The named points
    deliberately include the operation-to-journal windows, not just phase
    boundaries -- crashing only after a phase fsync would exercise the easy
    half of the protocol and hide exactly the defects that matter.
    """
    if os.environ.get("ADR_SCRIBE_CRASH_AT") == name:
        os._exit(70)
