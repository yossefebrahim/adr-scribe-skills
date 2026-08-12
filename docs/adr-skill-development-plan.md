# Development Plan — `adr` Skill (adr-scribe)

**Companion to:** [`docs/adr-skill-prd.md`](adr-skill-prd.md) (PRD v0.2)
**Status:** Draft v1.1 — implementation plan for Phase 0 → v1.2 public release
**Created:** 2026-08-12 · **Revised:** 2026-08-12 after adversarial review (see §13)
**Target repo:** `github.com/yossefebrahim/adr-scribe-skills` (currently empty: unborn HEAD, one doc, `origin` configured)

This plan turns the PRD into buildable work. It fixes the engineering decisions the PRD deliberately left open (notably **Q2**, the bundled runtime), specifies every artifact, and sequences the work into milestones with hard exit gates. Requirement IDs (`R1`–`R20`, `D1`–`D9`, `Q1`–`Q6`) refer to the PRD.

---

## 1. Executive summary

| | |
|---|---|
| **What we build** | A Claude Code skill (`/adr`) that captures an architecture decision from the live conversation, classifies every claim by provenance, interviews for gaps, previews an exact patch, and — only after approval — writes a MADR-4.0 ADR plus a regenerated index through a journaled, crash-safe, symlink-hostile transaction. |
| **Hardest parts** | (a) the provenance state machine `R3` — a prompt-engineering problem verified by evals; (b) `apply-record` `R7`/`R8` — a small distributed-systems problem verified by crash injection. They are independent and can be built in parallel. |
| **Runtime decision (Q2)** | **Python 3.9+, stdlib only.** Verified on this machine: `os.supports_dir_fd` covers `open/mkdir/rename/link/unlink/stat` and `O_NOFOLLOW` exists — the exact primitives `R8` demands ("no-follow directory-relative operations"). Node has no `openat`/`dir_fd` equivalent, so it cannot satisfy `R8` without native code. See §3.1. |
| **Time to alpha** | **32–50 engineer-days** of build (M0–M3) if PRD `R7`/`R8` stand as written, then a 30-day / 10-ADR alpha run. Drops to roughly 20–30 if the owner accepts the derived-index amendment (§13, kill-list 1). |
| **Known limit of the safety story** | The approval↔bytes binding is **procedural, not mechanical** (§10 I10). Must be disclosed in the PRD before alpha. |
| **Ship target** | skills.sh-installable public package at v1.2: `npx skills add yossefebrahim/adr-scribe-skills --skill adr -a claude-code`. Readiness work is folded in from M1 rather than bolted on (§9). |

---

## 2. Environment baseline (verified 2026-08-12)

| Fact | Value | Consequence |
|---|---|---|
| Repo state | Unborn HEAD, no commits, `origin` set | The **first** commit of this repo is a live `R8` "unborn HEAD" fixture — dogfood it. |
| Python | 3.14.2 | Build target is **3.9+** so CI can prove the floor; never assume 3.14 features. |
| Node | 22.23.1 | Used only for `npx skills` install tests. Not a runtime dependency of the skill. |
| Git | 2.50.1 (Apple) | All git usage is read-only plumbing (`rev-parse`, `status --porcelain=v1 -z`, `diff`, `log`). |
| `rg`, `jq` | present | Must **not** be required (`D7`, `compatibility` promises "ripgrep not required"). CI runs one job with both removed from `PATH`. |
| Platform | macOS (darwin 25.6), bash 3.2 | Any shell glue must be bash-3.2-safe (no associative arrays). Prefer Python over shell. |

---

## 3. Engineering decisions to lock before coding

These are decisions the PRD leaves to Engineering. Each needs a yes/no from Joe before M1 starts; each is written as an ADR in this repo once the skill can write them (dogfood), and as a plain markdown note before then.

### 3.1 E1 — Helper runtime = Python 3.9+, stdlib only *(resolves Q2 for the internal matrix)*

**Rationale:** `R8` requires directory-relative, no-follow path operations and `R7` requires `fsync` on files *and directories*, atomic exclusive creation, and atomic replace. Python's `os` module exposes `dir_fd=` on `open/mkdir/rename/link/unlink/stat`, `O_NOFOLLOW`, `os.fsync` on a directory fd, and `os.replace`. Node exposes none of the `*at()` family. Bash cannot do any of it safely.

Python is a **required external runtime**, not something we bundle — the scripts ship as source, the interpreter does not. That distinction matters for **Q6**: this decision resolves Q2 for the internal support matrix only, and re-opens for public portability.

**Risks & mitigation:**
- *macOS `python3` may be a Command Line Tools stub.* Mitigation: the skill's preflight runs `python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)'` and, on failure, stops with a one-line install instruction (`R8` unsupported-environment style). `compatibility` frontmatter states the requirement (≤500 chars, per spec).
- *No third-party YAML.* We ship `_frontmatter.py`, a **strict subset** parser/emitter (§5.1). It rejects anchors, aliases, flow maps, multi-line scalars and tags, which also removes a YAML-injection surface from `R10`. This is only safe under the canonical-only policy in **E8** — an under-specified "strict subset" is a footgun, not a feature.

### 3.2 E2 — The `content-digest` is computed at **preview** time, not at write time

Non-obvious but load-bearing. `R7` says approval binds to the exact previewed bytes, and §6 puts `content-digest` inside the file. If the digest were injected during apply, the written bytes would differ from the approved bytes. **Therefore:** `prepare-record` produces final bytes (digest included, `record-confirmation.confirmed-by` already filled from `git config user.name`), the preview shows those exact bytes, and `apply-record` writes them verbatim and re-verifies the digest. The same applies to the index: the preview shows the **rendered final index**, not a description of it.

### 3.3 E3 — Marker rejection is **lint**; the claim ledger is the real check

`validate-adr` (run inside `apply-record` *before* and *after* writing) rejects the literal markers `[UNCONFIRMED]`, `TODO`, `<...>` placeholder angle-brackets, and any persisted `provenance:` value outside the **three** on-disk classes (§5.1). Keep it — it catches truncated and half-finished drafts cheaply.

**Do not overclaim it.** The actual failure mode is *fluent* confabulation: "We rejected Bloc because its event model increased operational complexity," labelled `developer-stated`, contains no marker and passes every string check.

What can partially detect that is an **ephemeral claim ledger**, produced at S3 and consumed at S6, never written to the repo:

```jsonc
{ "claim-id": "c3", "text": "<exact material claim>", "class": "developer-stated",
  "locator": "<role-tagged conversation reference, or the exact confirming words>",
  "targets": ["decision-outcome", "considered-options[2]"] }
```

`prepare-record` then mechanically checks **coverage** (every material span of the draft maps to ≥1 claim), **consistency** (no `code-observed` claim feeds a rationale field — `R3`'s "implementation is not rationale"), and **no blanket labels** (a section whose claims have mixed classes takes the *weakest* class; it does not inherit the strongest). It still cannot verify that a locator is genuine unless Claude Code exposes trusted, role-tagged message references to a helper process. Until then, provenance truth is a workflow property, not a machine-enforced one — say so in the README rather than implying otherwise.

### 3.4 E4 — Evals live at repo root, **not** inside the skill *(deviation from PRD §7)*

The `skills` CLI copies the whole skill directory into every user's project. Shipping `evals/` (transcript fixtures, temp-repo builders) bloats every install — they are development and release assets, not runtime dependencies. **Recommendation:** move to root `evals/`, keep `skills/adr/` shippable-clean, and **amend PRD §7** rather than carrying a permanent plan exception.

Two caveats the bloat argument hides:
- Moving evals out of the skill does **not** make transcripts safe — root `evals/` is still in the public repo. Public fixtures must be **synthetic or irreversibly sanitized**; any corpus derived from real internal sessions lives in a separate private store (`R10`, D8).
- An installed skill is then no longer self-testing. Ship a *tiny* deterministic conformance corpus beside `scripts/` (digest golden vectors, index-render goldens) so a user can prove their install works; keep all stochastic/session evals at root.

### 3.5 E5 — `allowed-tools` is **not** used to pre-approve the writer in v1

Tempting to add `allowed-tools: Bash(git:*) Bash(python3:*)`. But `R7`/Non-Goals state tool permission is not approval, and the field is flagged experimental in the spec. v1 ships without it; the human approval gate stays the only path to a write. Revisit at v1.2 with a narrow read-only scope (`Bash(git rev-parse:*)` etc.).

### 3.6 E6 — Untracked-file inspection bounds *(makes `R2` "bounded" concrete)*

Read untracked files only when (a) path matches the hinted/candidate decision scope, (b) not ignored by `.gitignore`, (c) size ≤ 128 KiB, (d) content sniffs as text (no NUL in first 8 KiB), (e) ≤ 20 files per invocation, (f) **opened with `O_NOFOLLOW`** — a symlinked untracked file is skipped, not followed, or `R2`'s read bound leaks outside the repo entirely. Anything skipped is named in the preview's evidence-limitations line.

### 3.7 E7 — Recovery defaults to **resume-forward**, never blind rollback

`R7` allows resume *or* rollback. Default: if every journal hash still matches reality, resume forward to completion; if anything diverged, **stop and report** — do not attempt repair. Rollback is opt-in (`--rollback`) and only unlinks files whose current hash still equals the journal's expected hash.

### 3.8 E8 — Frontmatter policy: **canonical-only**

Decide before M1, because "strict subset" as written is not a specification. Two coherent options:

| Option | Contract | Cost |
|---|---|---|
| **Canonical-only** *(recommended)* | Accept **exactly** the emitter's grammar. Valid YAML that another parser would accept but ours did not emit is a hard error with a "run `render-index --fix`"-style message. | Humans hand-editing frontmatter hit errors; that is the intended trade for immutable, digest-covered records. |
| General YAML | Vendor and pin a mature pure-Python parser. | Added code, license, and security surface; contradicts stdlib-only. |

Under canonical-only, §5.1 must additionally define: quoted-string escape semantics, Unicode policy (**no normalization** — normalization would silently change the digest), and the rejection of YAML-looking scalars (`null`, `true`, `1.0`) where a string is expected. Minimum test corpus: every allowed field shape; quoted strings containing `:`/`#`/quotes/backslashes/control escapes/combining characters; duplicate keys at every depth; indentation mutations, tabs, BOM, CRLF, truncation, invalid UTF-8; anchors, aliases, merge keys, tags, directives, multi-document, flow collections, block scalars, trailing comments; parse→emit→parse property tests over generated schema objects; fuzz/mutation tests; golden byte vectors on 3.9 **and** the newest supported version; and a dev-only differential check that a mature YAML parser reads every emitted document equivalently.

### 3.9 E9 — Git is run **hardened**, not merely read-only

Read-only-looking git commands can execute repository-controlled programs: `diff.external`, `textconv`/`.gitattributes` filters, and `core.fsmonitor` all invoke commands from config. That is a live hole in `R10`'s "repository content is evidence, not instructions" boundary — a cloned repo could execute code during evidence gathering.

Every git invocation therefore goes through one wrapper that sets `GIT_CONFIG_NOSYSTEM=1`, `GIT_OPTIONAL_LOCKS=0`, `GIT_TERMINAL_PROMPT=0`, and passes `-c core.fsmonitor=false -c diff.external= -c core.hooksPath=/dev/null`, with `--no-textconv --no-ext-diff` on diff commands. A CI test asserts no git call bypasses the wrapper.

### 3.10 E10 — State the trust boundary honestly

See §10 I10. The helper cannot prove the human saw the bytes it is applying. This is disclosed in the README and needs a PRD amendment; it is not something the implementation can close.

---

## 4. Repository layout (what we are building)

```
adr-scribe-skills/
├── skills/
│   └── adr/                          # ← the only thing users install
│       ├── SKILL.md                  # < 500 lines, < ~5k tokens (spec guidance)
│       ├── LICENSE                   # bundled; referenced by `license:` frontmatter
│       ├── references/
│       │   ├── significance.md       # R4 rubric + worked positive/negative examples
│       │   ├── provenance.md         # R3 classes, fail-closed rules, interview policy
│       │   ├── madr-format.md        # R6/§6 body + frontmatter contract, glob dialect
│       │   ├── repository-states.md  # R8 states: unborn, detached, no remote, dirty…
│       │   └── transaction.md        # R7 apply/verify/recover + operator runbook
│       ├── assets/
│       │   ├── adr-template.md       # PRD §6 verbatim, neutral placeholders (D8)
│       │   └── index-template.md     # docs/adr/README.md scaffold w/ marker block
│       └── scripts/                  # python3, stdlib only, executable
│           ├── adr_scribe/           # importable package (shared code)
│           │   ├── __init__.py
│           │   ├── _frontmatter.py   # strict YAML-subset parse/emit
│           │   ├── ids.py            # ULID gen + validate, slug rules
│           │   ├── digest.py         # canonicalization + sha256
│           │   ├── paths.py          # dir_fd/O_NOFOLLOW safe path ops
│           │   ├── index.py          # deterministic generated-block renderer
│           │   ├── journal.py        # journal + lock ownership
│           │   └── validate.py       # schema, markers, index membership
│           ├── generate-id
│           ├── render-index
│           ├── prepare-record
│           ├── apply-record
│           └── validate-adr
├── evals/                            # E4: NOT shipped
│   ├── significance/                 # ≥8 positive, ≥8 negative, ≥8 ambiguous
│   ├── provenance/                   # transcript + expected classification fixtures
│   ├── repository-states/            # temp-repo builders + expectations
│   └── run.py                        # harness (headless `claude -p`), variance N≥3
├── tests/                            # pytest: unit + transaction matrix
├── docs/
│   ├── adr-skill-prd.md
│   ├── adr-skill-development-plan.md   # this file
│   ├── phase0-baseline.md              # Q5 audit output
│   └── adr/                            # dogfood: our own ADRs (written by the skill)
├── .github/workflows/ci.yml
├── README.md                         # install + usage; the skills.sh shop window
├── LICENSE
└── Makefile                          # make test | evals | lint | install-local
```

---

## 5. Component specifications

### 5.1 Data contracts (build first — everything else depends on them)

**Frontmatter subset (`_frontmatter.py`).** Accepts exactly: `key: scalar`, `key: "quoted"`, `key: null`, `key: []`, block sequences of scalars, and one level of nested mapping (`provenance:`, `evidence:`, `record-confirmation:`). Rejects: anchors/aliases (`&`,`*`), tags (`!`), flow mappings, multi-line scalars (`|`,`>`), duplicate keys, tabs, CRLF, BOM, comments after values. Emitter is canonical: fixed key order per §6, double-quoted strings, LF, one trailing newline.

**JSON Schema** (`assets/` not required to ship; used by `validate-adr` as a Python literal) covering every §6 field: `schema` pinned to `adr-scribe/v1`; `status ∈ {proposed}` for v1 writes; `id` matches `^ADR-[0-7][0-9A-HJKMNP-TV-Z]{25}$`; dates `YYYY-MM-DD`; `applies-to` non-empty, each entry validated against the glob dialect; `supersedes: []` in v1; **`provenance.*` ∈ exactly three values — `developer-stated`, `developer-confirmed`, `code-observed`** (`[UNCONFIRMED]` is an internal state that `R3` forbids on disk, so it is not in the persisted enum); `acceptance: null` in v1.

**`validate-adr` also enforces the `R6`/`R8` checks that are easy to forget:** body H1 mirrors the canonical `title`; the Y-statement blockquote mirrors `summary` byte-for-byte; body ≤ 800 words, warn > 1,200; any Confirmation command is non-destructive, repo-local, network-free (allow-list of verbs, no redirection, no pipes, no `sudo`/`rm`/`curl`) **and is never executed**; `applies-to` glob syntax; exactly-once index membership.

**ULID** (`ids.py`): 48-bit ms timestamp + 80-bit `secrets.token_bytes(10)`, Crockford base32 (`0123456789ABCDEFGHJKMNPQRSTVWXYZ`), 26 chars, first char `0–7`. Monotonic within a process. No network, no git history (`R8`, `D5`).

**Slug**: lowercase ASCII `[a-z0-9]` + single hyphens, ≤80 chars, no leading/trailing hyphen, no `..`, no separators. Derived from the decision-first title; rejected (not silently fixed) if the model supplies something else.

**Filename**: `docs/adr/<NNN>-<slug>.md` — a zero-padded display sequence number
allocated as max+1 from records on disk (revised 2026-08-13; the ULID stays in
frontmatter as the stable identity, so a merge-time renumber is a pure rename).

**`content-digest` canonicalization** (`digest.py`) — must be byte-exact because v1.1 acceptance proves content didn't change:
1. Copy frontmatter mapping; delete `status`, `date`, `acceptance`, `content-digest`.
2. Serialize to canonical JSON: keys sorted by Unicode codepoint, `separators=(',', ':')`, `ensure_ascii=False`, arrays order-preserving, UTF-8.
3. `body` = file bytes after the frontmatter's closing `---\n`, **verbatim** (no normalization — instead the validator *requires* LF-only, no trailing spaces, exactly one trailing newline).
4. `digest = "sha256:" + sha256(b"adr-scribe/v1\x00" + canonical_json + b"\x00" + body).hexdigest()` (domain-separated; JSON cannot contain a raw NUL, so the delimiter is unambiguous).
5. **No Unicode normalization** at any step — normalizing would silently change the digest of an immutable record. Golden vectors are pinned on Python 3.9 and the newest supported version.

**`patch-digest` canonicalization** — this is what `R7` actually binds approval to, so it needs the same rigor as `content-digest` and did not have it. Canonical JSON (same rules as above) of:

```jsonc
{ "patch-version": 1,
  "repo-relative-ops": [                       // sorted by path, byte order
    {"op": "create-file", "path": "docs/adr/adr-….md", "len": 4211, "sha256": "…"},
    {"op": "replace-file", "path": "docs/adr/README.md", "len": 908, "sha256": "…",
     "expect-sha256": "…"},                    // null when the file must be absent
    {"op": "create-dir",  "path": "docs/adr"}
  ],
  "preconditions": {"head": "…|unborn", "dirty-overlap": []} }
```

`patch-digest = "sha256:" + sha256(b"adr-scribe/patch/v1\x00" + canonical_json).hexdigest()`. Payload **bytes** are covered indirectly via per-op `sha256` + `len`; `apply-record` verifies both before writing. Op order is normative — two patches differing only in op order are different patches.

**Glob dialect** (`R6`): `/` separators; `*` within one segment; `**` zero-or-more segments; `**/*` = every repo-relative file including dotfiles. Reject absolute paths, `..`, `~`, negation, backslashes, empty segments. Metadata only in v1 — the validator checks syntax, nothing resolves it.

**Index block**: content between `<!-- adr-scribe:index:start -->` / `<!-- adr-scribe:index:end -->` is generated; everything outside is preserved byte-for-byte. Rows sorted by ULID ascending. Columns: ID | Title | Status | Last updated | Summary.

Escaping, **in this order** — the order is the spec, not an implementation detail: (1) `\` → `\\`, (2) `|` → `\|`, (3) CR/LF → single space, (4) collapse runs of spaces. Doing (2) before (1) double-escapes the backslash that (2) just introduced and leaves the pipe live, breaking the table — a golden-vector test covers a title containing `a\|b`.

Missing markers on an existing file = hard error with instructions, never a guess. `prepare-record` runs `render-index --check` and refuses to build a patch when the existing generated block cannot be reproduced from ADR frontmatter (`R8`), rather than silently overwriting a hand-edited block.

### 5.2 Script CLI contracts

| Script | Invocation | Output | Notes |
|---|---|---|---|
| `generate-id` | `generate-id [--check ULID]` | ULID on stdout | exit 1 on invalid `--check` |
| `validate-adr` | `validate-adr FILE...` or `--repo ROOT --all` | JSON report | schema, digest, markers, whitespace, glob syntax, duplicate IDs |
| `render-index` | `render-index --repo ROOT [--stdout | --check]` | final index bytes | `--check` exits 3 on drift; regenerates from ADR frontmatter only (`R8` merge-conflict rule) |
| `prepare-record` | `prepare-record --repo ROOT --input record.json --out STAGE` | `patch.json` + final file bytes | computes ULID, digest, index; collects preconditions; **does not touch the repo** |
| `apply-record` | `apply-record --repo ROOT --patch STAGE/patch.json --approved-digest sha256:…` | JSON result | the transaction (§5.3) |
| `apply-record` | `apply-record --repo ROOT --recover [--rollback] [--force-reclaim]` | JSON state report | idempotent (`R7`) |

**Exit codes** (uniform, so `SKILL.md` can branch deterministically):
`0` success · `2` precondition mismatch detected **before any destination write** → new preview required, nothing written · `3` lock held by a live owner · `4` failed **after** a destination write, or verification failed → state reported, recovery required, success never claimed · `5` unsupported environment (not a git repo, python too old) · `6` needs explicit human confirmation (corrupt/missing lock owner record) · `7` refused for safety (symlink in destination path, path escapes root, dirty overlap).

The 2-vs-4 boundary is "has anything been written yet," not "what kind of problem is it." An index-hash mismatch is exit **2** at step 6 and exit **4** at step 9, because by step 9 the ADR files exist. (v1.0 of this plan returned 2 in both places, which contradicted RS-15's "nothing written" expectation.)

Global invariants for every script: stdlib only; no network; **no writes to the repository outside the approved patch** (`prepare-record` stages to a caller-supplied directory *outside* the repo; `apply-record` stages only inside its own lock directory); never `git add/commit/push/fetch`; all git calls go through the E9 hardened wrapper; never execute content read from the repo (`R10`).

### 5.3 The transaction (`apply-record`) — detailed protocol

Preconditions captured at prepare time and re-checked under the lock: `HEAD` sha or `"unborn"`; each ADR target `absent`; index `absent` **or** `sha256:…`; no dirty (`git status --porcelain=v1 -z`) entry overlapping any target; `patch-digest`.

```
1  verify root:      git rev-parse --show-toplevel  → open O_RDONLY|O_DIRECTORY|O_NOFOLLOW
2  resolve targets:  component-by-component openat(O_NOFOLLOW) → any symlink ⇒ exit 7 (R7/R10)
                     missing components are NOT an error here — they are bootstrap work (step 7a)
3  acquire:          mkdir(".adr-scribe.lock", dir_fd=root)  ← atomic; EEXIST ⇒ staleness check
                     fsync(root)                             ← lock entry must be durable
4  own:              write owner.json {pid, start-token, host, iso-ts} → fsync file + lockdir
5  journal:          write journal.json {phase:"prepared", …} → fsync file + lockdir      ← R7
                     journal carries expected sha256 of EVERY output BEFORE anything is written
6  re-check:         all preconditions under the lock → mismatch ⇒ release, exit 2 (nothing written)
7  stage:            render every output into lock/tmp/ (same filesystem) → fsync each
7a bootstrap dirs:   for each missing component of docs/, docs/adr/: mkdirat(dir_fd) → fsync parent
                     append to journal.created-dirs BEFORE creating          ← R8 first-run
8  create ADRs:      linkat(tmp→dest, O_NOFOLLOW) — atomic + EEXIST-exclusive; fsync destdir
                     journal.phase = "adrs-written"; fsync
9  index:            re-read index bytes → hash must equal precondition, else exit 4 (ADRs exist)
                     save preimage into lock/preimage/ + fsync → renameat(tmp→index) → fsync destdir
                     journal.phase = "index-replaced"; fsync
10 verify:           re-read all written bytes; hash match; validate-adr; index membership
                     exactly once per ADR; no [UNCONFIRMED]  → failure ⇒ exit 4        ← R7
11 complete:         journal.phase = "complete"; fsync
                     renameat(".adr-scribe.lock" → ".adr-scribe-completed-<ULID>") → fsync(root)  ← R7
                     rmtree the completed dir → fsync(root)
```

**The phase label always lags the operation** — steps 8, 9 and 11 each have a window where the filesystem has advanced but the journal has not. Recovery must therefore *identify state by hash, never by phase alone*. This is why step 5 records every expected output hash up front: a file whose bytes hash to the journal's expected value can only be ours, so recovery can safely claim it. A recovery routine that trusts the phase label is not idempotent and does not satisfy `R7`.

**Stale-lock rules** (`R7`): a lock with **no** journal is pre-write — reclaimable once `ADR_SCRIBE_LOCK_STALE_SECONDS` (default 900) has elapsed **and** the recorded PID is not live or its start token differs. Missing/corrupt `owner.json` ⇒ exit 6, requiring `--force-reclaim` after the human confirms no `apply-record` is running. Start token: `ps -o lstart= -p PID` (portable across macOS/Linux; falls back to `/proc/PID/stat` field 22 on Linux).

**Recovery matrix** (`--recover`):

Recovery reads the journal for *expectations* and the filesystem for *facts*, and reconciles by hash:

| Journal phase | Reality check | Action |
|---|---|---|
| *(no journal)* | nothing written | release lock, report `pre-write` |
| `prepared` | all targets absent | release lock, report `no-op` |
| `prepared` | target exists, **hash == expected output** | crashed inside step 8 → it *is* ours; adopt it and resume from step 8 for the remaining files |
| `prepared` | target exists, hash ≠ expected | exit 4, touch nothing, report the divergence |
| `adrs-written` | all written hashes match, index still == old hash | crashed before step 9 → resume from step 9 |
| `adrs-written` | index == **expected new** hash | crashed inside step 9 (renamed, unjournalled) → adopt and resume from step 10 |
| `adrs-written` | any hash differs from both expected-old and expected-new | exit 4, preserve everything, report exact divergence |
| `index-replaced` | index hash == expected new | resume from step 10 |
| `index-replaced` | index hash differs (concurrent editor) | exit 4, report; preimage stays in the lock dir |
| `complete` | — | finish cleanup (rename + rmtree), idempotent, report success |
| *(no lock, `.adr-scribe-completed-*` present)* | — | crashed during step 11 cleanup → rmtree, report success |

`--rollback` unlinks only files whose current hash still equals the journal's expected output hash, restores the index preimage only if the index still hashes to the expected *new* value, and removes a `created-dirs` entry only when it is still empty.

Directory cleanup: a transaction-created parent (`docs/`, `docs/adr/`) is removed on rollback **only if still empty**; otherwise left and reported (`R7`).

**Test hook:** `ADR_SCRIBE_CRASH_AT=<point>` triggers `os._exit(70)` at a named point. Documented, inert unless set. The named points must include the **operation-to-journal windows**, not just the phase boundaries — crashing only after a phase fsync exercises the easy half of the protocol and would have hidden every defect listed above:

`lock-created` · `owner-written` · `journal-prepared` · `dir-created` · `first-link` · **`links-done-prejournal`** · `phase-adrs-written` · `preimage-saved` · **`index-renamed-prejournal`** · `phase-index-replaced` · `verified` · `phase-complete` · **`completed-renamed-preremove`**.

### 5.4 `SKILL.md` workflow (the prompt-side deliverable)

Inline in the main conversation — **no `context: fork`** (`R1`). Progressive disclosure: each reference file is read only at the stage that needs it.

| Stage | Does | Loads | Exits |
|---|---|---|---|
| **S0 Preflight** | `git rev-parse --show-toplevel`; python version check; read `$ARGUMENTS` as literal-only evidence | `repository-states.md` if anything is unusual | not a repo ⇒ stop (`R8`) |
| **S1 Evidence** | visible conversation → working tree (`status`, `diff`, bounded untracked per E6) → existing ADRs (**full body** of duplicate/conflict candidates) | — | never `git fetch` (`R2`) |
| **S2 Significance** | apply `R4` rubric per candidate; state limitations of visible context | `significance.md` | "No ADR needed — <one line>" is a **valid end** |
| **S3 Provenance** | classify every material claim: `developer-stated` / `developer-confirmed` / `code-observed` / `[UNCONFIRMED]` | `provenance.md` | unresolved discussion ⇒ open question, no record |
| **S4 Gap interview** | ≤3 pointed questions total, only for material gaps | — | still unsupported ⇒ omit claim or cancel that record (`R5`) |
| **S5 Sensitive check** | scan proposed bytes for secrets/customer data; redact; **separate** specific confirmation if any remains | — | `R10` |
| **S6 Preview** | build `record.json` → `prepare-record` → show **exact** final bytes of every file + index → ask *"Approve this exact patch for writing?"* | `madr-format.md` | any requested change ⇒ new preview, not approval (`R7`) |
| **S7 Apply** | `apply-record` with the approved digest; branch on exit code | `transaction.md` on non-zero | never claim success on failure |
| **S8 Report** | per-candidate outcome: `written` / `not significant` / `cancelled—insufficient evidence` / `declined` / `failed`; invocation: `completed` / `partial` / `no ADR needed` / `declined` / `failed` | — | feeds §8 metrics |

Frontmatter (spec-valid; `name` must equal the directory name):

```yaml
---
name: adr
description: >-
  Capture a significant architecture decision from the current conversation as a
  provenance-checked ADR. Use when the developer invokes /adr or asks to record an
  ADR, architecture decision, or decision record from work just discussed.
license: MIT
compatibility: >-
  Claude Code with Git and python3 3.9+. macOS and Linux. No network access and no
  ripgrep required. Writes only inside the repository, never runs git mutations.
metadata:
  version: "1.0"
  schema: "adr-scribe/v1"
---
```

---

## 6. Test strategy

Three independent layers. Layers 1 and 3 are deterministic and gate CI; layer 2 is statistical and gates release.

**Layer 1 — unit (pytest, fast, deterministic).** ULID charset/monotonicity/collision (10⁶ generations); slug rejection table; frontmatter parser accept/reject corpus incl. YAML-injection attempts; digest stability + exclusion set (mutating `status`/`date`/`acceptance` must not change the digest; mutating one body byte must); index render determinism (byte-identical across 100 runs, shuffled input order), escaping, marker preservation, missing-marker error; glob syntax table.

**Layer 2 — behavioral evals (`evals/run.py`).** Fixtures are JSON: `{id, label, transcript[], repo_state?, expected}`. The harness composes `SKILL.md` + the stage's reference file + the fixture transcript, runs headless (`claude -p --output-format json`) asking for a structured verdict, and runs **N≥3 per fixture** to report variance.

**The PRD's percentage gates are not measurable at the PRD's fixture count, and the plan should say so.** With 8 positives and 8 negatives, "precision ≥ 90%" collapses to "zero false positives" (8 TP + 1 FP = 88.9%), and "recall ≥ 80%" to "at least 7 of 8." Even a perfect run proves little: the 95% Wilson interval for 8/8 is ≈ 67.6%–100%, and for 7/8 ≈ 52.9%–97.8%. N≥3 reruns measure *stochastic instability on the same examples* — they are not 48 independent fixtures and must never be pooled as such.

So, split the claim in two:

- **Now (alpha gate).** Keep the 8/8/8 corpus but call it a **regression suite**, not statistical validation. Gate on: zero unsafe outcomes across all runs, zero unsupported-provenance outcomes, full confusion matrix reported, and every per-fixture disagreement across the N runs triaged (rubric wording / reference-file gap / genuinely ambiguous → relabel with written justification).
- **Later (release gate, before public beta).** Predeclare a held-out, stratified corpus of ≥50 positive, ≥50 negative and ~25 ambiguous cases, with near-duplicate sessions prevented from crossing the tuning/held-out split; gate on a one-sided 95% confidence *lower bound*, not the point estimate; treat repeated runs hierarchically by fixture. For reference, a one-sided 95% Clopper-Pearson lower bound above 90% needs **n ≥ 29** predicted positives even with a flawless record (`0.05^(1/n) > 0.90`). That labeling cost is not justified before internal alpha — which is exactly why the alpha gate should stop claiming statistical significance it cannot have.

This needs a PRD §8 amendment; it does not weaken any safety property, since the 100%-safe gates (ambiguous escalation, provenance accuracy, fail-closed) are unchanged and are the ones that actually protect the product.

**Layer 3 — repository-state matrix.** Each fixture builds a throwaway repo in a temp dir and asserts final on-disk state. The full PRD §8 list, as test IDs:

| ID | State | Expected |
|---|---|---|
| RS-01 | fresh repo, no `docs/adr/` | bootstrap ADR + index created |
| RS-02 | no commits (unborn HEAD) | success; precondition records `unborn` |
| RS-03 | no remote | success; no fetch attempted (asserted via `GIT_*` proxy trap) |
| RS-04 | detached HEAD | success |
| RS-05 | dirty index, unrelated files | success |
| RS-06 | dirty index **overlapping** a target | exit 7, nothing written |
| RS-07 | decline at preview | zero filesystem writes (asserted by tree hash) |
| RS-08 | multiple decisions | separate records; `partial` outcome reporting |
| RS-09 | ADR target already exists | exit 2, new preview required (never regenerate silently) |
| RS-10 | symlinked `docs/adr` or destination component | exit 7 even when it resolves inside the repo |
| RS-11 | stale pre-journal lock (dead PID) | reclaimed after threshold |
| RS-11b | live lock | exit 3 |
| RS-11c | lock, corrupt `owner.json` | exit 6 until `--force-reclaim` |
| RS-12 | crash after ADR creation (`phase-adrs-written`) | `--recover` resumes to complete |
| RS-12b | crash **between** `linkat` and the phase update (`links-done-prejournal`) | recovery adopts the file by hash and resumes — the window v1.0 of this plan could not recover |
| RS-13 | crash after index replacement, before completion | `--recover` completes; index correct exactly once |
| RS-13b | crash **between** index rename and the phase update (`index-renamed-prejournal`) | recovery adopts by hash and resumes to verify |
| RS-14 | interrupted completed-lock cleanup (`completed-renamed-preremove`) | `--recover` finishes rename/rmtree idempotently |
| RS-15 | concurrent index mismatch detected at step 6 (pre-write) | exit 2, nothing written |
| RS-15b | concurrent index mismatch detected at step 9 (ADRs already created) | exit **4**, ADRs left in place, recovery required, reported |
| RS-16 | concurrent post-write index mismatch | exit 4, preimage preserved, mismatch reported |
| RS-17 | journaled rollback | only hash-matching files unlinked; non-empty created dir left + reported |
| RS-18 | two `apply-record` processes racing | exactly one writes; other exits 3 |
| RS-19 | outside a git repo | exit 5, clear unsupported-environment message |
| RS-20 | `[UNCONFIRMED]` present in staged bytes | refused before any write (E3) |
| RS-21 | hostile repo config (`diff.external`, `textconv`, `core.fsmonitor` set to a marker command) | marker command never executes (E9) |
| RS-22 | symlinked untracked file inside the evidence scope | skipped and reported, never followed (E6) |
| RS-23 | existing index with a hand-edited generated block | `prepare-record` refuses; no patch is offered (`R8`) |

**CI** (`.github/workflows/ci.yml`): matrix `{ubuntu-latest, macos-latest} × python{3.9, 3.12, 3.14}`; one job with `rg` and `jq` removed from `PATH`; one job with network disabled; `skills-ref validate ./skills/adr`; `render-index --check` + `validate-adr --all` against this repo's own dogfood ADRs.

---

## 7. Milestones

### M0 — Phase 0: discovery, spike, contracts · ~6–9 days

Gated by PRD §8 Phase-0 exit gates; **the audit can kill the project** and runs first.

| # | Task | Out |
|---|---|---|
| M0.1 | Audit ≥10 recent agent-assisted sessions/PRs for missing rationale & re-litigation (**Q5**) | `docs/phase0-baseline.md` |
| M0.2 | **Go/No-Go.** Threshold: ≥2 significant decisions without durable rationale, or ≥1 material re-litigation/violation/reconstruction incident | written decision |
| M0.3 | Build fixture corpus: ≥8 positive, ≥8 negative, ≥8 ambiguous significance; provenance + compaction-ambiguity fixtures | `evals/` |
| M0.4 | Runtime spike: prove `dir_fd`+`O_NOFOLLOW`+`linkat`+dir-`fsync` on macOS **and** Linux CI | spike script + notes |
| M0.5 | Freeze data contracts (§5.1) + JSON schema + `validate-adr` v0 | `adr_scribe/` skeleton |
| M0.6 | Confirm inline conversation access; write the honest "we cannot detect compaction" language | `references/provenance.md` draft |

**Exit:** all Phase-0 gates pass; **Q2** (→ E1) and **Q5** resolved; E4/E5 signed off.

### M1 — Writer core · **~15–25 days** *(the risk milestone)*

*Revised up from 8–12. That estimate covered a happy-path writer with tests; it did not cover a reviewed cross-platform recovery protocol with adversarial path handling and systematic fault injection at the operation-to-journal windows. Assume the lower end only if the implementer is already fluent in `*at()` semantics and crash consistency.*

| # | Task |
|---|---|
| M1.1 | `_frontmatter.py`, `ids.py`, `digest.py` + unit tests |
| M1.2 | `paths.py`: symlink-hostile, root-confined, dir-fd path ops |
| M1.3 | `index.py` + `render-index` (deterministic, marker-preserving, conflict-regenerating) |
| M1.4 | `prepare-record` (final bytes + preconditions + patch digest — E2) |
| M1.5 | `apply-record` happy path: lock, journal, stage, create, replace, verify, complete |
| M1.6 | `--recover` + `--rollback` + stale-lock ownership + `ADR_SCRIBE_CRASH_AFTER` |
| M1.7 | RS-01…RS-20 green on both OSes, all Python versions |

**Exit:** repository-state coverage 100% (a PRD alpha gate) with zero silent overwrites and zero unreported partial writes.

### M2 — Skill surface · ~4–5 days

| # | Task |
|---|---|
| M2.1 | `SKILL.md` (<500 lines) implementing S0–S8 |
| M2.2 | `references/significance.md` — rubric + worked examples straight from the M0.3 fixtures |
| M2.3 | `references/provenance.md` — four classes, interview policy (≤3 questions), fail-closed script |
| M2.4 | `references/madr-format.md` + `references/repository-states.md` + `references/transaction.md` (incl. operator runbook for exit 4/6) |
| M2.5 | `assets/adr-template.md` + `assets/index-template.md`, neutral placeholders only (**D8**) |
| M2.6 | Local install (`make install-local` → symlink into `.claude/skills/adr`), walking-skeleton run end-to-end in a scratch repo |

**Exit:** a real `/adr` produces a proposed ADR + index in a fresh repo; `/adr` on a trivial change says "No ADR needed."

### M3 — Evals & hardening · ~4–5 days

| # | Task |
|---|---|
| M3.1 | `evals/run.py` harness, N≥3 variance reporting |
| M3.2 | Run significance/provenance gates; iterate on rubric wording until §8 targets hold |
| M3.3 | Prompt-injection fixtures: hostile existing ADR / code comment / filename attempting to override the workflow (`R10`) |
| M3.4 | Sensitive-data fixtures: keys and customer data in diffs and transcripts |
| M3.5 | CI matrix green; `skills-ref validate` clean |

**Exit:** every PRD §8 Phase-0 gate reproducibly passes from a clean checkout.

### M4 — Internal alpha · 30 days or 10 ADRs

Install for Joe + one developer. Joe audits 100% of claims in the first 10 records. **Pause immediately** if unsupported rationale reaches disk or any unrelated file is touched.

**Outcome logging lives outside the repository** — `~/.adr-scribe/alpha-log.jsonl`, not a gitignored file in the working tree. A gitignored log still writes into the repo on a *declined* invocation, contradicting `R7`'s "on decline, write nothing." Contents: outcome, timing, exit code, invocation id. No transcript content (`R10`). If the team would rather have zero automatic writes at all, record outcomes manually in a shared doc — the metric matters, the mechanism does not.

Also produce: `docs/adr/` dogfood records for E1–E7 above, written by the skill itself.

### M5 — v1.1 internal beta · ~8–10 days build + 30 days run

`R11` natural-language activation (measured fresh-session precision/recall) · `R12` acceptance + immutable supersession (acceptance patch touches only `status`/`date`/`acceptance` + index, and must verify the stored `content-digest`; reject missing refs, scope mismatch, self-links, cycles, competing replacements) · `R13` commit/PR text suggestions with **no** git execution · `R14` `roadmap-ref` · **Q1** acceptance policy adopted.

### M6 — v1.2 public release · ~4–6 days

See §9.

---

## 8. Task dependency map

```
M0.1 → M0.2 ─┬→ M0.3 ─────────────┬→ M3.1 → M3.2 ─┐
             ├→ M0.4 → M0.5 ─┬→ M1.1 → M1.2 → M1.3 → M1.4 → M1.5 → M1.6 → M1.7 ─┤
             └→ M0.6 ────────┴→ M2.1…M2.5 ────────→ M2.6 ───────────────────────┴→ M3.5 → M4
```
The two long poles — **M1 (writer)** and **M2/M3 (prompt + evals)** — share only the data contracts (M0.5), so with two developers they run in parallel after M0.

---

## 9. skills.sh deployment readiness

**How skills.sh actually works** (verified against the CLI docs and the Agent Skills spec): there is **no registry submission**. You publish by putting a valid skill in a public git repo; the skills.sh directory is populated through the CLI's install telemetry as people install it. So "ready to deploy" means: *the repo is structurally discoverable, the skill validates, and a stranger's first install works.* PRD §8 already says installs are an awareness metric, not proof of use — that stays true.

**Structural requirements we already satisfy by design:**

| Requirement | Status in this plan |
|---|---|
| Skill at `skills/<name>/SKILL.md` (CLI walks `skills/`, root, `.claude/skills/`, depth ≤3) | §4 layout: `skills/adr/SKILL.md` ✅ |
| `name` ≤64 chars, lowercase/digits/hyphens, no leading/trailing/consecutive hyphens, **equal to the directory name** | `name: adr`, dir `adr` ✅ |
| `description` 1–1024 chars, says *what* and *when* | §5.4 frontmatter ✅ |
| `compatibility` ≤500 chars, only if there are real environment requirements | we have them (git, python3 ≥3.9) ✅ |
| `metadata` = string→string map only | `version`, `schema` as **strings** ✅ |
| `SKILL.md` <500 lines / ~5k tokens, deep material in `references/` | §5.4 ✅ |
| Relative file references, one level deep | ✅ |
| Public repo, no private paths/names (**D8**) | enforced by M6.2 |

**M6 checklist:**

| # | Task | Gate |
|---|---|---|
| M6.1 | `skills-ref validate ./skills/adr` in CI (`github.com/agentskills/agentskills`) | must pass on every PR |
| M6.2 | Portability sweep: grep the shipped tree for internal names, absolute paths, team conventions, `rg`/`jq`/network assumptions | zero hits (**D8**, PRD §8) |
| M6.3 | **Resolved:** keep the `adr` skill name and use the **MIT License**. `adr` is not globally unique and **can collide with a local `/adr`**; the CLI installs by directory name, so document the rename path before public release. Keep the root and bundled `LICENSE` files aligned with `license: MIT` frontmatter. | decided 2026-08-13 |
| M6.4 | Resolve **Q6**: support matrix. Recommend macOS 13+ / Linux, git ≥2.30, python ≥3.9; state it in `compatibility` and README. | documented |
| M6.5 | Fresh-install test in **≥3 unrelated repos**: `npx skills add yossefebrahim/adr-scribe-skills --skill adr -a claude-code`, plus `--list` and the non-interactive `--skill '*' -a claude-code -y` form | 3/3 first-run success |
| M6.6 | README as the shop window: one-paragraph value prop (session-based capture with provenance discipline — the differentiator per PRD Risk 11), install command, a real before/after example, explicit **non-goals**, safety statement ("never stages, commits, pushes, or fetches; writes only after you approve exact bytes"), uninstall/disable, recovery runbook, issue-reporting path | reviewed |
| M6.7 | Security & privacy review: no automatic command execution, no secret persistence, no writes outside the repo, no telemetry of our own | signed off |
| M6.8 | Tag `v1.2.0`; keep `metadata.version` in sync; publish; optionally list on skills.sh by installing it once ourselves from the public URL | tagged |

**Deliberately excluded:** `.claude-plugin/marketplace.json` (that's the Claude Code plugin path, a different distribution channel) and `allowed-tools` (E5). Both can be added later without breaking installs.

---

## 10. Implementation risk register

*(Distinct from the PRD's product risks — these are ways the build itself goes wrong.)*

| # | Risk | Mitigation |
|---|---|---|
| I1 | Preview/write byte drift (digest or index computed after approval) | E2: `prepare-record` emits final bytes; `apply-record` re-verifies the patch digest and refuses on mismatch |
| I2 | Hand-rolled YAML parser accepts something ugly and corrupts frontmatter | Strict allow-list subset + accept/reject corpus in unit tests + `validate-adr` on read *and* write |
| I3 | Model regresses and emits unsupported rationale | E3 machine enforcement: markers/placeholders/illegal provenance values are a hard write failure |
| I4 | `fsync`/rename semantics differ on macOS vs Linux vs network FS | CI on both OSes; PRD already declines to promise portable multi-file crash atomicity; temp files forced onto the same filesystem via the root-level lock dir |
| I5 | Eval harness needs the Claude Code CLI and is slow/flaky | N≥3 with variance reporting; evals gate releases, not every PR; layers 1 and 3 keep CI fast and deterministic |
| I6 | `apply-record` scope creep into a general-purpose transactional FS library | Hard scope: exactly the paths in one `patch.json`; no generic API; no config file |
| I7 | Alpha telemetry accidentally persists session content | Local gitignored JSONL, outcome/timing/exit-code fields only, schema-checked in tests |
| I8 | 3-minute median (PRD §8) blown by preview length | Preview shows full ADR bytes but a *diff* for the index; ≤3 questions asked in a single message, not serially |
| I9 | `python3` unavailable/stubbed on a user's mac | Preflight check with a one-line remedy; documented in `compatibility` and README; measured during M6.5 |
| **I10** | **No trusted binding between the human's approval and the bytes handed to `apply-record`.** The same model renders the preview *and* invokes the helper with `--approved-digest`. It could display bytes A and apply bytes B; the helper proves only that its input matches a digest **the model supplied**, not that a human ever saw it. | Not closable in-process. Reduce: `apply-record` echoes the digest and the full destination list to stdout (visible in the transcript); the post-write report tells the developer to `git diff` before committing; `prepare-record` output is the only accepted input format. **Disclose it** — `R7`'s "never write unapproved bytes" is a procedural guarantee under an honest model, not a mechanically enforced one. Closing it needs a host-issued approval receipt bound to the helper's digest, or a helper-owned confirmation channel the model cannot answer on the user's behalf; neither exists in Claude Code today. |
| I11 | Repository-controlled git config executes commands during "read-only" evidence gathering | E9 hardened wrapper + RS-21 |
| I12 | `confirmed-by` is taken from `git config user.name`, which is unauthenticated repo configuration, not developer identity | Acceptable for an internal alpha — the field records *who the preview named*, and `R3`'s confirmation is the human's explicit yes, not a cryptographic claim. Document the limitation; do not let it imply authentication. |

---

## 11. Open items this plan cannot close

| Ref | Item | Owner | Needed by |
|---|---|---|---|
| Q1 | What action moves `proposed → accepted` | Team | M5 |
| Q3 | Public repo name, final skill name, license | Joe | M6.3 |
| Q4 | Agent formats beyond Claude Code for rule projection | Joe + Eng | v2 |
| Q5 | Phase-0 audit baseline | Joe | M0.2 — **blocks everything** |
| Q6 | Public OS/git support matrix | Eng | M6.4 |
| E4 | Move `evals/` out of the shipped skill (amend PRD §7) | Joe | M0 exit |
| E5 | Confirm `allowed-tools` stays unset in v1 | Joe | M2 |
| E8 | Canonical-only frontmatter vs vendored YAML | Eng | **before M1** |
| **A1** | **Amend `R7`/`R8` for the derived-index option?** Accepting it removes the lock, journal, preimage, phase machine and most of the recovery matrix, cutting M1 roughly in half. Rejecting it keeps §5.3 as specified. This is the single highest-leverage decision in the plan. | Joe | **before M1** |
| A2 | Amend PRD §8 to reframe the 8/8/8 gates as a regression suite (§6 layer 2) | Joe | M0 exit |
| A3 | Disclose the I10 trust boundary in the PRD and README | Joe | before alpha |

---

## 12. Definition of done — v1 alpha

1. `npx skills`-installable layout; `skills-ref validate ./skills/adr` clean; CI green on macOS + Linux, Python 3.9/3.12/3.14, including no-`rg`/no-network jobs.
2. RS-01…RS-20 pass with zero silent overwrites and zero unreported partial writes.
3. Significance precision ≥90%, recall ≥80%, ambiguous 100% safe, provenance accuracy 100%, fail-closed 100% — reproducible from a clean checkout.
4. `/adr` in a fresh repo with no commits and no remote produces, after one approval, a schema-valid `status: proposed` ADR plus a valid index, and nothing else changes on disk.
5. Decline writes zero bytes; every failure path reports the journal and observed state and never claims success.
6. No `git add`/`commit`/`push`/`fetch` is reachable from any code path (asserted by a CI grep **and** a PATH-shim test that fails the suite if git is invoked with a mutating verb).
7. Every invocation reports exactly one outcome from the §8 taxonomy.
8. The I10 trust boundary is stated plainly in the README — the product does not claim a guarantee it cannot enforce.

---

## 12a. Build status — 2026-08-12

The **v1 capture pipeline is implemented and tested**: 247 tests pass on Python 3.9
and 3.14, the skill installs through the real `npx skills` CLI, and a fresh repo with
unborn HEAD produces a schema-valid `proposed` record plus a consistent index.

| Milestone | State |
|---|---|
| M0.5 data contracts | done — `_frontmatter`, `digest`, `ids`, `index` |
| M1 writer core | done — `paths`, `journal`, `transaction`, `prepare-record`, `apply-record` |
| M1.7 repository-state matrix | done — 28 cases incl. both operation-to-journal crash windows |
| M2 skill surface | done — `SKILL.md` (201 lines) + 5 references + assets |
| M3.5 CI + spec validation | done — matrix workflow, `check_skill.py`, no-`rg`/no-`jq` job |
| M0.1/M0.2 audit + kill gate | **outstanding — owner only** |
| M3.1–M3.4 behavioural evals | **outstanding — needs labelled fixtures from real sessions** |
| M4 alpha run | ready to start once the gate passes |

**Decision A1 was resolved conservatively:** built as the PRD specifies, with the
index inside the approved patch, because the PRD is authoritative until amended. The
index-inclusion point is one seam in `prepare-record`; switching to a derived index
remains a small change.

Defects found during the build, all fixed with regression tests: a `re.match(...$)`
anchor that allowed a newline inside a generated filename; a contract that could not
express nested list fields; recovery that abandoned a transaction whose staged
payloads were still present; and a symlink refusal that misreported the cause.

---


## 13. Revision log — adversarial review (2026-08-12)

Plan v1.0 was reviewed by a second agent (Codex, read-only, high effort) briefed to attack eight contested decisions. Verdicts: C1 runtime, C3 transaction-machinery-given-the-PRD, C4 preview-time digest and C7 eval packaging upheld; C5 eval validity, C6 provenance enforcement and C8 sizing overturned; C2 frontmatter ruled under-specified.

**Accepted — defects fixed in this revision:**

| Fix | Where | Was |
|---|---|---|
| Index escaping order (`\` before `\|`) | §5.1 | Escaped `\|` first, which double-escaped its own backslash and left the pipe live — a broken table on any title containing `\|` |
| Recovery identifies state **by hash**, not phase | §5.3 | Crash between `linkat` and the phase update was unrecoverable ("never assume it's ours") though the journal already held the expected hash |
| Crash hooks at operation-to-journal windows | §5.3, RS-12b/13b | Hook fired only after phase fsync — the fault injection tested only the safe half of the protocol |
| First-run directory bootstrap (step 7a) | §5.3 | Protocol never created `docs/adr/`, so RS-01 and `R8` could not pass |
| Exit 2 vs 4 split on "has anything been written" | §5.2, RS-15/15b | Step-9 mismatch returned exit 2 after ADRs existed, contradicting RS-15 |
| `patch-digest` canonical encoding defined | §5.1 | Named but never specified — the digest `R7` binds approval to |
| Persisted provenance enum = 3 values | §5.1 | Allowed all four, including the one `R3` forbids on disk |
| Hardened git wrapper (E9) + RS-21 | §3.9 | Missed entirely: `diff.external`/`textconv`/`core.fsmonitor` execute repo-controlled commands during "read-only" reads |
| `O_NOFOLLOW` on untracked evidence reads | §3.6 | Bounds ignored symlinks, letting reads escape the repo |
| `validate-adr` H1/summary mirrors, word limits, Confirmation-command safety | §5.1 | `R6`/`R8` checks omitted from the validator spec |
| Claim ledger; marker check demoted to lint | §3.3 | Overclaimed that string matching stops confabulation |
| Eval gates reframed; held-out protocol for release | §6 | Presented an n=8 corpus as validating a 90% precision target |
| Alpha logging moved outside the repo | M4 | Gitignored in-repo log wrote on declined runs, against `R7` |
| Sizing: M1 15–25 d, alpha 32–50 d | §1, M1 | 8–12 d covered a happy-path writer, not the recovery protocol |
| E8 frontmatter policy + test corpus | §3.8 | "Strict subset" was not a specification |
| I10 trust boundary | §10 | Neither document acknowledged that approval↔bytes binding is procedural |

**Rejected, with reasons:**

- *"`prepare-record --out STAGE` writes before approval, violating `R7`."* `R7` governs **repository** writes; staging to a temp dir outside the repo is not one. The real defect was §5.2's sloppy "no writes outside the repo root" invariant, now reworded. Design unchanged.
- *"Drop `content-digest` from v1."* ~20 lines of code, and without it the v1.1 acceptance flow cannot prove immutability for records the alpha produced — creating a migration problem for exactly the records that matter most.
- *"Marker matching is security theater."* It reliably catches truncated and half-finished drafts at near-zero cost. The overclaim was in the framing, which is fixed; the check stays.

**Deferred to the PRD owner** (A1–A3 in §11): the derived-index amendment, the §8 gate reframing, and the I10 disclosure. All three change the PRD, so none is the plan's call to make.
