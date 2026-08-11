# Repository states

Load at S0 if something looks unusual, or at S7 to interpret a failure. Most "weird"
states are explicitly supported — do not treat them as errors.

## Supported without comment

| State | Why it works |
|---|---|
| **No commits (unborn HEAD)** | The first ADR in a brand-new repo is a first-class case. Preconditions record `head: "unborn"`. |
| **No remote** | Nothing ever contacts a network. `git fetch` is never run. |
| **Detached HEAD** | HEAD is recorded as a SHA; nothing requires a branch. |
| **No `docs/adr/`** | The approved patch bootstraps `docs/` and `docs/adr/` and creates the index. |
| **Dirty working tree** | Uncommitted changes elsewhere are irrelevant. |
| **Shallow clone / worktree / submodule** | Only the repository root matters. |

## Refused, with a reason

**Not a git repository.** Stop at S0. adr-scribe records decisions *into* a
repository; there is nothing to record into. Do not offer to `git init` — creating a
repository is a decision the developer should make deliberately.

**`python3` missing or < 3.9.** The helpers need directory-relative, no-follow path
operations; that is why the runtime requirement exists. Report it and stop.

**Uncommitted changes to a target file.** If `docs/adr/README.md` or the ADR path has
uncommitted edits, `prepare-record` refuses. Overwriting someone's unsaved work to
write a decision record would be a poor trade. Ask them to commit or stash.

**A symlink anywhere in a destination path.** Refused even when it currently resolves
inside the repository — "currently" is exactly the problem, since it can change
between the check and the write. Exit 7.

**Windows.** The internal alpha is macOS and Linux. The required `*at()` primitives
are not available; the helper says so rather than degrading silently.

## Index states

**Missing** → bootstrapped by the approved patch.

**Present and consistent** → the generated block is replaced; everything outside the
markers is preserved byte for byte.

**Markers missing from an existing `README.md`** → hard error. The file was written by
something else and adr-scribe will not guess where its block belongs. The developer
should add the marker pair, or move the file aside.

**Hand-edited inside the generated block** → `render-index --check` reports drift and
`prepare-record` refuses. Fix the ADR frontmatter, not the table; the table is output.

**Merge conflict inside the generated block** → resolve by regenerating from the ADR
files after the merge. Never hand-resolve the table. The records are the source of
truth; the index is derived.

## Multiple writers

The lock (`.adr-scribe.lock/` at the repository root) serialises adr-scribe writers.
A second writer exits 3 and waits. This is cooperative: it protects against another
adr-scribe process, not against a person editing the index in their editor at the
same moment. That residual risk is why the index hash is re-checked immediately
before replacement and verified immediately after.

## Reading untracked files

Only when relevant to the decision, not ignored by `.gitignore`, ≤ 128 KiB, textual,
not a symlink, and at most 20 per invocation. Anything skipped is named in the
record's evidence limitations rather than silently dropped.
