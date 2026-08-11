"""The write transaction: apply, verify, recover.

Between the human's "yes" and the files existing, eleven steps run. They are
designed around an awkward truth the PRD states plainly: creating one file and
replacing another cannot be made atomic *together* on a portable filesystem.
So rather than pretending, every intermediate state is made **recoverable**,
and every failure reports exactly what is on disk instead of guessing.

Exit-code contract (the boundary is "has anything been written yet"):
    0 success
    2 precondition mismatch detected BEFORE any destination write
    3 lock held by a live owner
    4 failed AFTER a destination write, or verification failed
    5 unsupported environment
    6 needs explicit human confirmation
    7 refused for safety

Stdlib only, Python 3.9 floor.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from . import journal as J
from . import paths as P
from . import validate as V

OK = 0
E_PRECONDITION = 2
E_LOCKED = 3
E_AFTER_WRITE = 4
E_ENVIRONMENT = 5
E_CONFIRM = 6
E_REFUSED = 7


class TransactionError(RuntimeError):
    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_target(root_fd: int, relpath: str) -> Optional[str]:
    """Hash a repo-relative file, or None if it does not exist."""
    parts = P.split_relpath(relpath)
    if len(parts) == 1:
        dir_fd, _ = os.dup(root_fd), None
        name = parts[0]
        try:
            return _hash_in_dir(dir_fd, name)
        finally:
            os.close(dir_fd)
    try:
        dir_fd, _ = P.resolve_dir(root_fd, parts[:-1])
    except P.PathError:
        return None
    try:
        return _hash_in_dir(dir_fd, parts[-1])
    finally:
        os.close(dir_fd)


def _hash_in_dir(dir_fd: int, name: str) -> Optional[str]:
    kind = P.entry_kind(dir_fd, name)
    if kind == "absent":
        return None
    if kind == "symlink":
        raise TransactionError(
            "refusing to operate on the symlink %r" % name, E_REFUSED)
    if kind != "file":
        raise TransactionError("%r is not a regular file" % name, E_REFUSED)
    return sha256_bytes(P.read_file(dir_fd, name))


# --------------------------------------------------------------------------
# preconditions
# --------------------------------------------------------------------------

def check_preconditions(root_fd: int, patch: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable mismatches. Empty means all hold."""
    problems: List[str] = []
    for op in patch["repo-relative-ops"]:
        if op["op"] == "create-dir":
            continue
        relpath = op["path"]
        try:
            actual = _hash_target(root_fd, relpath)
        except TransactionError as exc:
            problems.append(str(exc))
            continue
        if op["op"] == "create-file":
            if actual is not None:
                problems.append("%s already exists" % relpath)
        elif op["op"] == "replace-file":
            expected = op.get("expect-sha256")
            if expected is None:
                if actual is not None:
                    problems.append("%s exists but the patch expected it absent" % relpath)
            elif actual is None:
                problems.append("%s is missing but the patch expected it" % relpath)
            elif actual != expected:
                problems.append(
                    "%s changed since the preview (expected %s, found %s)"
                    % (relpath, expected[:12], actual[:12]))
    return problems


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------

def apply(repo: str, patch: Dict[str, Any], payloads: Dict[str, bytes],
          approved_digest: str, patch_digest: str,
          stale_seconds: int = J.DEFAULT_STALE_SECONDS) -> Dict[str, Any]:
    """Execute the approved patch. Returns a result dict on success."""
    if approved_digest != patch_digest:
        raise TransactionError(
            "approved digest does not match the patch: approval is void", E_REFUSED)

    P.check_platform()
    root_fd = P.open_root(repo)
    lock_fd = None
    wrote_anything = False
    try:
        # Steps 1-2: resolve and refuse symlinks anywhere in a destination.
        for op in patch["repo-relative-ops"]:
            parts = P.split_relpath(op["path"])
            _assert_no_symlink_components(root_fd, parts)

        # Step 3-4: acquire the lock and record ownership.
        try:
            lock_fd = J.acquire(root_fd, stale_seconds=stale_seconds)
        except J.LockError as exc:
            raise TransactionError(str(exc),
                                   E_CONFIRM if exc.needs_confirmation else E_LOCKED)
        J.crash_point("lock-created")

        outputs = [
            {"path": op["path"], "sha256": op["sha256"]}
            for op in patch["repo-relative-ops"] if op["op"] == "create-file"
        ]
        index_op = next(
            (op for op in patch["repo-relative-ops"] if op["op"] == "replace-file"),
            None)
        creates_dirs = [op["path"] for op in patch["repo-relative-ops"]
                        if op["op"] == "create-dir"]

        journal = J.new_journal(patch_digest, patch["preconditions"],
                                outputs, creates_dirs, index_op)
        J.write_journal(lock_fd, journal)
        J.crash_point("journal-prepared")

        # Step 6: re-check under the lock. Nothing is written yet.
        problems = check_preconditions(root_fd, patch)
        if problems:
            raise TransactionError(
                "preconditions changed since the preview: " + "; ".join(problems),
                E_PRECONDITION)

        # Step 7: stage every output inside the lock directory.
        tmp_fd = J.ensure_subdir(lock_fd, J.TMP_DIRNAME)
        try:
            staged = {}
            for op in patch["repo-relative-ops"]:
                if op["op"] == "create-dir":
                    continue
                data = payloads[op["path"]]
                if sha256_bytes(data) != op["sha256"]:
                    raise TransactionError(
                        "payload for %s does not match its patch hash" % op["path"],
                        E_REFUSED)
                name = op["path"].replace("/", "__")
                P.write_new_file(tmp_fd, name, data)
                staged[op["path"]] = name

            # Step 7a: bootstrap directories, recording them before creating.
            created_dirs = _bootstrap_dirs(root_fd, patch, journal, lock_fd)
            J.crash_point("dir-created")

            # Step 8: create ADR files exclusively and atomically.
            for op in patch["repo-relative-ops"]:
                if op["op"] != "create-file":
                    continue
                parts = P.split_relpath(op["path"])
                dst_fd, _ = P.resolve_dir(root_fd, parts[:-1])
                try:
                    P.link_into_place(tmp_fd, staged[op["path"]], dst_fd, parts[-1])
                    wrote_anything = True
                finally:
                    os.close(dst_fd)
                J.crash_point("first-link")
            J.crash_point("links-done-prejournal")
            J.set_phase(lock_fd, journal, "adrs-written")
            J.crash_point("phase-adrs-written")

            # Step 9: replace the index, but only if it still matches.
            if index_op is not None:
                _replace_index(root_fd, lock_fd, tmp_fd, staged, index_op, journal)
                wrote_anything = True
                J.crash_point("index-renamed-prejournal")
                J.set_phase(lock_fd, journal, "index-replaced")
                J.crash_point("phase-index-replaced")
        finally:
            os.close(tmp_fd)

        # Step 10: verify what is actually on disk.
        findings = verify(root_fd, patch)
        if findings:
            raise TransactionError(
                "post-write verification failed: " + "; ".join(findings), E_AFTER_WRITE)
        J.set_phase(lock_fd, journal, "verified")
        J.crash_point("verified")

        # Step 11: complete and release.
        J.set_phase(lock_fd, journal, "complete")
        J.crash_point("phase-complete")
        J.release(root_fd, lock_fd)
        lock_fd = None

        return {
            "status": "written",
            "files": [op["path"] for op in patch["repo-relative-ops"]
                      if op["op"] != "create-dir"],
            "created-dirs": created_dirs,
            "patch-digest": patch_digest,
        }
    except TransactionError as exc:
        if lock_fd is not None:
            if not wrote_anything and exc.code in (E_PRECONDITION, E_REFUSED):
                _abort_clean(root_fd, lock_fd)
            else:
                os.close(lock_fd)
        raise
    finally:
        os.close(root_fd)


def _assert_no_symlink_components(root_fd: int, parts: List[str]) -> None:
    current = os.dup(root_fd)
    try:
        for name in parts[:-1]:
            kind = P.entry_kind(current, name)
            if kind == "symlink":
                raise TransactionError(
                    "refusing to write through the symlink %r" % name, E_REFUSED)
            if kind == "absent":
                return  # will be created by bootstrap
            nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=current)
            os.close(current)
            current = nxt
        if P.entry_kind(current, parts[-1]) == "symlink":
            raise TransactionError(
                "refusing to write through the symlink %r" % parts[-1], E_REFUSED)
    except OSError as exc:
        raise TransactionError("cannot resolve destination: %s" % exc, E_REFUSED)
    finally:
        os.close(current)


def _bootstrap_dirs(root_fd: int, patch: Dict[str, Any],
                    journal: Dict[str, Any], lock_fd: int) -> List[str]:
    """Create missing destination directories, journalling before creating."""
    needed = set()
    for op in patch["repo-relative-ops"]:
        parts = P.split_relpath(op["path"])
        prefix = parts if op["op"] == "create-dir" else parts[:-1]
        for i in range(1, len(prefix) + 1):
            needed.add("/".join(prefix[:i]))
    created: List[str] = []
    for rel in sorted(needed):
        parts = P.split_relpath(rel)
        try:
            fd, made = P.resolve_dir(root_fd, parts, create=True)
        except P.PathError as exc:
            raise TransactionError(str(exc), E_REFUSED)
        os.close(fd)
        for entry in made:
            if entry not in created:
                created.append(entry)
    if created:
        journal["created-dirs"] = created
        J.write_journal(lock_fd, journal)
    return created


def _replace_index(root_fd: int, lock_fd: int, tmp_fd: int,
                   staged: Dict[str, str], index_op: Dict[str, Any],
                   journal: Dict[str, Any]) -> None:
    parts = P.split_relpath(index_op["path"])
    dst_fd, _ = P.resolve_dir(root_fd, parts[:-1])
    try:
        name = parts[-1]
        expected = index_op.get("expect-sha256")
        actual = _hash_in_dir(dst_fd, name)
        if expected is None:
            if actual is not None:
                raise TransactionError(
                    "%s appeared since the preview" % index_op["path"], E_AFTER_WRITE)
            P.link_into_place(tmp_fd, staged[index_op["path"]], dst_fd, name)
            return
        if actual != expected:
            # ADR files already exist, so this is exit 4 (recovery required),
            # not exit 2 (nothing written).
            raise TransactionError(
                "%s changed between the preview and the write" % index_op["path"],
                E_AFTER_WRITE)
        preimage_fd = J.ensure_subdir(lock_fd, J.PREIMAGE_DIRNAME)
        try:
            P.write_new_file(preimage_fd, name, P.read_file(dst_fd, name))
        finally:
            os.close(preimage_fd)
        journal["index-preimage"] = {"path": index_op["path"], "sha256": actual}
        J.write_journal(lock_fd, journal)
        P.atomic_replace(tmp_fd, staged[index_op["path"]], dst_fd, name)
    finally:
        os.close(dst_fd)


def _abort_clean(root_fd: int, lock_fd: int) -> None:
    """Release the lock after a failure that wrote nothing."""
    try:
        J.release(root_fd, lock_fd)
    except OSError:
        try:
            os.close(lock_fd)
        except OSError:
            pass


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify(root_fd: int, patch: Dict[str, Any]) -> List[str]:
    """Check the written bytes, schema validity, and index membership."""
    findings: List[str] = []
    written_ids = []
    for op in patch["repo-relative-ops"]:
        if op["op"] == "create-dir":
            continue
        try:
            actual = _hash_target(root_fd, op["path"])
        except TransactionError as exc:
            findings.append(str(exc))
            continue
        if actual is None:
            findings.append("%s is missing after the write" % op["path"])
            continue
        if actual != op["sha256"]:
            findings.append("%s does not match the approved bytes" % op["path"])
            continue
        if op["op"] == "create-file":
            parts = P.split_relpath(op["path"])
            dir_fd, _ = P.resolve_dir(root_fd, parts[:-1])
            try:
                raw = P.read_file(dir_fd, parts[-1])
            finally:
                os.close(dir_fd)
            problems = V.errors(V.validate_document(raw))
            for problem in problems:
                findings.append("%s: [%s] %s" % (op["path"], problem.code, problem.message))
            try:
                front, _ = V._fm.split_document(raw)
                written_ids.append(V._fm.parse(front).get("id"))
            except Exception:
                pass

    index_op = next((op for op in patch["repo-relative-ops"]
                     if op["op"] == "replace-file"), None)
    if index_op is not None and written_ids:
        parts = P.split_relpath(index_op["path"])
        try:
            dir_fd, _ = P.resolve_dir(root_fd, parts[:-1])
        except P.PathError as exc:
            findings.append(str(exc))
            return findings
        try:
            text = P.read_file(dir_fd, parts[-1]).decode("utf-8", "replace")
        finally:
            os.close(dir_fd)
        for rid in written_ids:
            if not isinstance(rid, str):
                continue
            if text.count(rid) != 1:
                findings.append("%s appears %d times in the index, expected once"
                                % (rid, text.count(rid)))
    return findings


# --------------------------------------------------------------------------
# recovery
# --------------------------------------------------------------------------

def recover(repo: str, rollback: bool = False,
            force_reclaim: bool = False) -> Dict[str, Any]:
    """Resume or roll back an interrupted transaction. Idempotent.

    State is identified by **hash**, never by the journal phase alone: the
    phase label always lags the operation that precedes it.
    """
    P.check_platform()
    root_fd = P.open_root(repo)
    try:
        lock_fd = J.open_existing(root_fd)
        if lock_fd is None:
            removed = J.cleanup_completed(root_fd)
            if removed:
                return {"status": "completed-cleanup", "removed": removed}
            return {"status": "nothing-to-recover"}
        try:
            journal = J.read_journal(lock_fd)
            if journal is None:
                owner = J.read_owner(lock_fd)
                if owner is not None and J.owner_is_live(owner) and not force_reclaim:
                    raise TransactionError(
                        "the lock is held by a live process (pid %s); nothing was "
                        "written yet" % owner.get("pid"), E_LOCKED)
                os.close(lock_fd)
                lock_fd = None
                J._consider_reclaim(root_fd, 0, True)
                return {"status": "pre-write", "detail": "lock released, nothing written"}

            state = _observe(root_fd, journal)
            if rollback:
                return _rollback(root_fd, lock_fd, journal, state)
            return _resume(root_fd, lock_fd, journal, state)
        finally:
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except OSError:
                    pass
    finally:
        os.close(root_fd)


def _observe(root_fd: int, journal: Dict[str, Any]) -> Dict[str, Any]:
    """Compare reality against the journal's expectations, by hash."""
    outputs = []
    for entry in journal.get("outputs", []):
        actual = _hash_target(root_fd, entry["path"])
        if actual is None:
            state = "absent"
        elif actual == entry["sha256"]:
            state = "ours"
        else:
            state = "foreign"
        outputs.append({"path": entry["path"], "state": state, "actual": actual})

    index_state = None
    index_op = journal.get("index")
    if index_op:
        actual = _hash_target(root_fd, index_op["path"])
        expected_new = index_op["sha256"]
        expected_old = index_op.get("expect-sha256")
        if actual == expected_new:
            index_state = "new"
        elif actual == expected_old:
            index_state = "old"
        elif actual is None:
            index_state = "absent"
        else:
            index_state = "foreign"
    return {"outputs": outputs, "index": index_state}


def _staged_payload(lock_fd: int, relpath: str,
                    expected_sha: str) -> Optional[bytes]:
    """Return the staged bytes for ``relpath`` if they survived the crash.

    The staging directory lives *inside* the lock, so an interrupted
    transaction still has everything it needs to finish. That is what makes
    resume-forward possible rather than forcing a re-approval.
    """
    if P.entry_kind(lock_fd, J.TMP_DIRNAME) != "dir":
        return None
    tmp_fd = os.open(J.TMP_DIRNAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                     dir_fd=lock_fd)
    try:
        name = relpath.replace("/", "__")
        if P.entry_kind(tmp_fd, name) != "file":
            return None
        data = P.read_file(tmp_fd, name)
    finally:
        os.close(tmp_fd)
    return data if sha256_bytes(data) == expected_sha else None


def _resume(root_fd: int, lock_fd: int, journal: Dict[str, Any],
            state: Dict[str, Any]) -> Dict[str, Any]:
    foreign = [o["path"] for o in state["outputs"] if o["state"] == "foreign"]
    if foreign:
        raise TransactionError(
            "cannot resume: %s changed outside this transaction; nothing was "
            "touched" % ", ".join(foreign), E_AFTER_WRITE)
    if state["index"] == "foreign":
        raise TransactionError(
            "cannot resume: the index changed outside this transaction; the "
            "preimage is preserved in the lock directory", E_AFTER_WRITE)

    completed: List[str] = []

    # Finish any ADR that was journalled but never linked.
    expected = {entry["path"]: entry["sha256"] for entry in journal.get("outputs", [])}
    for entry in state["outputs"]:
        if entry["state"] != "absent":
            continue
        data = _staged_payload(lock_fd, entry["path"], expected[entry["path"]])
        if data is None:
            raise TransactionError(
                "cannot resume: %s is missing and its payload is no longer "
                "staged; re-run the preview and approve again" % entry["path"],
                E_AFTER_WRITE)
        parts = P.split_relpath(entry["path"])
        dir_fd, _ = P.resolve_dir(root_fd, parts[:-1], create=True)
        try:
            P.write_new_file(dir_fd, parts[-1], data)
        finally:
            os.close(dir_fd)
        completed.append(entry["path"])

    # Finish the index replacement if the crash landed before it.
    index_op = journal.get("index")
    if index_op and state["index"] in ("old", "absent"):
        data = _staged_payload(lock_fd, index_op["path"], index_op["sha256"])
        if data is None:
            raise TransactionError(
                "cannot resume: the index was never replaced and its new bytes "
                "are no longer staged; re-run the preview and approve again",
                E_AFTER_WRITE)
        parts = P.split_relpath(index_op["path"])
        dir_fd, _ = P.resolve_dir(root_fd, parts[:-1], create=True)
        try:
            if P.entry_kind(dir_fd, parts[-1]) == "absent":
                P.write_new_file(dir_fd, parts[-1], data)
            else:
                tmp_fd = J.ensure_subdir(lock_fd, J.TMP_DIRNAME)
                try:
                    resume_name = "resume-index"
                    if P.entry_kind(tmp_fd, resume_name) != "absent":
                        os.unlink(resume_name, dir_fd=tmp_fd)
                    P.write_new_file(tmp_fd, resume_name, data)
                    P.atomic_replace(tmp_fd, resume_name, dir_fd, parts[-1])
                finally:
                    os.close(tmp_fd)
        finally:
            os.close(dir_fd)
        completed.append(index_op["path"])
        J.set_phase(lock_fd, journal, "index-replaced")

    # Re-verify everything before declaring success.
    patch_like = {"repo-relative-ops": [
        {"op": "create-file", "path": e["path"], "sha256": expected[e["path"]]}
        for e in state["outputs"]
    ]}
    if index_op:
        patch_like["repo-relative-ops"].append(
            {"op": "replace-file", "path": index_op["path"],
             "sha256": index_op["sha256"]})
    findings = verify(root_fd, patch_like)
    if findings:
        raise TransactionError(
            "recovery verification failed: " + "; ".join(findings), E_AFTER_WRITE)

    J.set_phase(lock_fd, journal, "complete")
    J.release(root_fd, lock_fd)
    return {
        "status": "resumed",
        "files": [o["path"] for o in state["outputs"]],
        "completed-during-recovery": completed,
        "index": state["index"],
    }


def _rollback(root_fd: int, lock_fd: int, journal: Dict[str, Any],
              state: Dict[str, Any]) -> Dict[str, Any]:
    """Undo only what is provably ours."""
    removed, kept = [], []
    for entry in state["outputs"]:
        if entry["state"] != "ours":
            kept.append(entry["path"])
            continue
        parts = P.split_relpath(entry["path"])
        dir_fd, _ = P.resolve_dir(root_fd, parts[:-1])
        try:
            os.unlink(parts[-1], dir_fd=dir_fd)
            P.fsync_fd(dir_fd)
            removed.append(entry["path"])
        finally:
            os.close(dir_fd)

    index_restored = False
    index_op = journal.get("index")
    if index_op and state["index"] == "new" and journal.get("index-preimage"):
        parts = P.split_relpath(index_op["path"])
        preimage_fd = J.ensure_subdir(lock_fd, J.PREIMAGE_DIRNAME)
        try:
            data = P.read_file(preimage_fd, parts[-1])
        finally:
            os.close(preimage_fd)
        dir_fd, _ = P.resolve_dir(root_fd, parts[:-1])
        try:
            tmp_fd = J.ensure_subdir(lock_fd, J.TMP_DIRNAME)
            try:
                restore_name = "restore-index"
                if P.entry_kind(tmp_fd, restore_name) != "absent":
                    os.unlink(restore_name, dir_fd=tmp_fd)
                P.write_new_file(tmp_fd, restore_name, data)
                P.atomic_replace(tmp_fd, restore_name, dir_fd, parts[-1])
                index_restored = True
            finally:
                os.close(tmp_fd)
        finally:
            os.close(dir_fd)

    left_dirs = []
    for rel in reversed(journal.get("created-dirs", [])):
        parts = P.split_relpath(rel)
        parent_fd, _ = P.resolve_dir(root_fd, parts[:-1]) if len(parts) > 1 \
            else (os.dup(root_fd), [])
        try:
            if not P.remove_dir_if_empty(parent_fd, parts[-1]):
                left_dirs.append(rel)
        finally:
            os.close(parent_fd)

    J.release(root_fd, lock_fd)
    return {
        "status": "rolled-back",
        "removed": removed,
        "kept": kept,
        "index-restored": index_restored,
        "directories-left": left_dirs,
    }
