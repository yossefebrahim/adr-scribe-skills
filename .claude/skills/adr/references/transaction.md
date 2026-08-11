# The write transaction — and what to do when it fails

Load at S7 when `apply-record` exits non-zero. This is the operator runbook.

## What runs between "yes" and the file existing

```
 1  verify root      git rev-parse --show-toplevel → open(O_DIRECTORY|O_NOFOLLOW)
 2  resolve targets  component-by-component openat(O_NOFOLLOW); any symlink ⇒ refuse
 3  acquire lock     mkdir(".adr-scribe.lock") — atomic; exists ⇒ staleness check
 4  record owner     pid + process start token + timestamp → fsync
 5  journal          phase="prepared" + expected sha256 of EVERY output → fsync
 6  re-check         preconditions under the lock; changed ⇒ stop, nothing written
 7  stage            render outputs inside the lock dir (same filesystem) → fsync
 7a bootstrap        create docs/, docs/adr/ if missing; journalled before creating
 8  create ADRs      linkat(tmp→dest) — atomic, and fails if the target exists
 9  replace index    re-read + hash-match → save preimage → renameat → fsync
10  verify           re-read bytes, validate schema, check index membership
11  complete         journal → rename lock to .adr-scribe-completed-<ts> → remove
```

Creating one file and replacing another cannot be atomic *together* on a portable
filesystem. Rather than pretend otherwise, every intermediate state is recoverable.

**The phase label always lags the operation.** There is a window where a file exists
but the journal still says `prepared`. That is why step 5 records every expected hash
*before* writing: recovery identifies state by **hash**, never by phase. A file whose
bytes match the expected hash can only be ours, so it is safe to adopt.

## Exit codes

The 2-vs-4 boundary is **"has anything been written yet"**, not how bad the problem
sounds.

| Code | Meaning | Action |
|---|---|---|
| 0 | written and verified | report success |
| 2 | preconditions changed **before** any write | nothing was written. Re-run `prepare-record` and get fresh approval — the old digest is void |
| 3 | a live process holds the lock | wait. Do not `--force-reclaim`; another writer is working |
| 4 | failed **after** a write, or verification failed | run `--recover`. **Never re-apply** |
| 5 | unsupported environment | report; nothing was attempted |
| 6 | lock owner unreadable | a human must confirm no `apply-record` is running, then `--force-reclaim` |
| 7 | refused for safety | symlink, unsafe path, or payload/digest mismatch. Report verbatim; do not work around it |

## Recovery

```bash
apply-record --repo "$REPO" --recover              # resume forward (default)
apply-record --repo "$REPO" --recover --rollback   # undo only what is provably ours
```

Recovery is **idempotent** — running it twice is safe, and on a clean repository it
reports `nothing-to-recover`.

**Resume forward** is the default because a half-written transaction still has its
staged payloads inside the lock directory. Recovery re-links any missing ADR, finishes
the index replacement if it never happened, re-verifies everything, then releases.

**It stops rather than guessing** when reality diverges from the journal:

- a written file's bytes changed → `changed outside this transaction`, exit 4,
  nothing touched
- the index changed to something unrecognised → exit 4, the preimage is preserved
  inside the lock directory

In both cases the correct move is a human looking at the diff, not another automated
attempt.

**Rollback** removes only files whose current hash still equals the journal's expected
value, restores the index preimage only if the index still holds the bytes we wrote,
and removes a directory it created **only while that directory is still empty** —
otherwise it leaves it and says so.

## The lock

`.adr-scribe.lock/` at the repository root. A directory, because `mkdir` is atomic
everywhere.

Reclaimed automatically only when **all** of: no valid journal inside, the recorded
PID is not live *or* its start token differs, and the lock is older than the stale
threshold (900s default). A PID alone is not enough — PIDs get recycled, and stealing
a lock from an unrelated process would be a data-loss bug.

If the owner record is missing or corrupt, the tool exits 6 and asks a human. Do not
pass `--force-reclaim` on the developer's behalf.

`.adr-scribe-completed-*` left behind means a crash during final cleanup. It is
harmless; `--recover` removes it.

## The limit worth stating

`apply-record` proves its input matches the digest **it was given**. It cannot prove
a human saw those bytes — the same agent renders the preview and passes the digest.
So "never writes unapproved bytes" is a procedural guarantee under an honest agent,
not a mechanically enforced one. Tell the developer to `git diff` before committing.
