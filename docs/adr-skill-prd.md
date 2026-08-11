# PRD — `adr` Skill for Claude Code

**Status:** Draft v0.2 — internal alpha definition
**Owner:** Joe (Negm)
**Primary audience:** internal team (2 developers → 4)
**Future audience:** public users installing from a public repository through the skills CLI after internal and external validation
**Last updated:** 2026-08-12

---

## 1. Problem Statement

Our team makes architectural decisions inside Claude Code sessions — which state management approach, which API boundary, which library, what we deliberately rejected. When the session ends, the code survives and the reasoning becomes unreliable or inaccessible. A new session does not contain the prior conversation; only explicitly persisted project instructions and machine-local auto memory may carry over. The next person or agent can see *what* the code does but not reliably *why* it is shaped that way, so settled debates are re-litigated and unwritten constraints are quietly violated.

Writing ADRs by hand solves this but doesn't survive contact with a shipping schedule. The cost is about to grow: we're going from 2 developers to 4, and every one of them will run agents against the same repo.

**The skill closes the gap while the evidence is still visible** — during or at the end of the working session, while the alternatives, constraints, and developer responses are still in the active conversation.

Current evidence is qualitative and comes from the team's direct experience. Before implementation, Phase 0 will audit recent agent-assisted sessions and PRs to establish a baseline: significant decisions found, durable rationale present, re-litigation observed, and time spent reconstructing intent. Until then, this PRD treats the product thesis as a hypothesis to validate internally.

---

## 2. Goals

1. **Capture the decision while its evidence is still available.** For a single-decision invocation, a developer runs `/adr` and gets an accurate draft that can be reviewed, written, and indexed with a median of less than 3 minutes of active developer attention.
2. **Never invent rationale.** Every material claim is classified by provenance. Code can support what was implemented, but only a developer statement or explicit confirmation can support intent.
3. **Fail closed.** If a material decision, driver, or rejection reason remains unsupported after the gap interview, omit it or cancel the record; never turn ambiguity into architectural law.
4. **Make writes safe and unsurprising.** Nothing is written before approval. Approval applies to the exact proposed patch. The helper serializes adr-scribe writers, refuses detected conflicts, preserves recoverable state, and never stages, commits, pushes, or fetches.
5. **Stay usable as the team grows.** Records receive stable, collision-resistant IDs generated locally, without sequential allocation or network access.
6. **Create a durable source record.** Humans get a concise MADR-based narrative; future tools get versioned, machine-readable metadata and scoped rules. Automatic agent loading is not a v1 promise.
7. **Validate internally before publishing.** Public packaging and broader portability are gated on an internal alpha, a four-developer beta, and fresh-install tests in unrelated repositories.

---

## 3. Non-Goals

| Not doing | Why |
|---|---|
| **Status / progress tracking** ("what's done, where we are now") | That's the roadmap's job. Mixing it in fills the decision log with non-decisions and destroys the signal. ADRs may *link* to roadmap items; they don't replace them. |
| **Auto-writing files without approval** | An unreviewed ADR with plausible-but-wrong rationale is worse than no ADR. Explicit approval is a workflow invariant; tool permission alone is not approval. |
| **Accepting architectural decisions** | v1 confirms the accuracy of the record and writes `status: proposed`. Team acceptance and status transitions happen through a separate review policy. |
| **Git staging, commits, pushes, or remote fetches** | v1 writes documentation only. Git mutations require a separate, explicit workflow. |
| **Automatic loading or enforcement for agents** | `docs/adr/` and `applies-to` metadata are not auto-loaded by Claude Code. Retrieval, `.claude/rules` projection, and compliance checking come later. |
| **Superseding accepted ADRs** | v1 may flag a possible conflict, but lifecycle-safe supersession is v1.1. |
| **Editing accepted ADRs** | Accepted ADR content is immutable. v1 only creates new proposed records. |
| **Retroactive backfill of the whole repo's history** | Separate one-off job. This skill records decisions going forward. |
| **Reliable detection when `/adr` was never invoked** | A standalone skill is not a session lifecycle listener. Skipped-decision nudges require optional hook or plugin support. |

---

## 4. User Stories

**Primary — the developer finishing a session**
- As a developer wrapping up a Claude Code session, I want to run `/adr` and have the agent propose a record of what we actually decided, so the reasoning lands in the repo before I lose it.
- As a developer, I want the agent to tell me plainly when nothing in the session was architecturally significant, so I'm not pressured into writing filler records.
- As a developer, I want to be asked at most a few pointed questions about the *why*, not to be interviewed for ten minutes.
- As a developer, I want approval to confirm the record without silently committing code or declaring a team-wide decision accepted.

**Decision reviewer**
- As a reviewer, I want every new ADR to arrive as `proposed`, with unsupported claims removed and evidence limitations visible, so architectural acceptance remains a deliberate team act.

**Second reader — the teammate**
- As the other developer, I want to open `docs/adr/` and understand a decision I wasn't part of, including what was rejected and why.
- As a new developer joining in month 3, I want the accepted records in the ADR index to be my onboarding path through the architecture.

**Future reader — the agent (design constraint, not a v1 deliverable)**
- As an agent starting a fresh session on a file, I want future retrieval tooling to identify the active ADRs governing that file from stable metadata, without reparsing prose or treating superseded records as active.

**Maintainer**
- As the skill's maintainer, I want the first internal `/adr` run to work in a Git repository with no `docs/adr/` directory, no remote, and no commits.
- Before public beta, I want a stranger's first run to succeed without internal names, paths, tools, or conventions.

---

## 5. Requirements

### P0 — Internal capture alpha

**R1. Explicit invocation and execution context**

The required v1 trigger is `/adr`. The directory name defines the command.

- [ ] Runs in the main conversation; the skill must not set `context: fork`
- [ ] Conversation and provenance analysis must not be delegated to a subagent that lacks the current conversation history
- [ ] Works during a session as well as at the end
- [ ] Reads `$ARGUMENTS` as an optional developer hint: `/adr we chose Riverpod over Bloc`
- [ ] Treats the hint as evidence only for what it literally states; it never invents an unstated reason

Natural-language activation is supported by Claude Code but probabilistic. It is evaluated in v1.1, not required for alpha success.

**R2. Read-only evidence gathering — three sources**

1. **Visible session context** — developer statements, agent proposals, explicit choices, constraints, and unresolved questions. This is the primary source for intent.
2. **Local working tree** — status plus relevant staged, unstaged, and bounded untracked changes. Relevant local commits may be inspected when a local baseline is identifiable.
3. **Existing ADRs** — the index and the full body of plausible duplicate or conflict candidates, not the index summary alone.

- [ ] Evidence inspection is read-only and never performs `git fetch`
- [ ] Missing remote, upstream, commits, or default-branch reference is non-fatal
- [ ] Commit SHAs are optional; uncommitted evidence is recorded as working-tree paths
- [ ] When early context or speaker attribution is missing or ambiguous, the skill states the limitation; it does not claim it can deterministically detect compaction
- [ ] The skill does not copy raw transcript content into the ADR, index, or repository by default

**R3. Provenance state machine — the highest-risk requirement**

Every material claim in the draft is classified internally as one of:

| Class | Meaning | May support intent? |
|---|---|---|
| `developer-stated` | The developer explicitly stated the decision, driver, consequence, or rejection reason | Yes |
| `developer-confirmed` | Before the final preview, the developer explicitly confirmed that exact claim in the gap interview or a dedicated confirmation | Yes |
| `code-observed` | The implementation or diff demonstrates a technical fact | No — implementation is not rationale |
| `[UNCONFIRMED]` | The agent inferred or reconstructed the claim | No — must be resolved, removed, or cancelled |

- [ ] An unacknowledged agent suggestion is not a developer decision
- [ ] If the developer selects one of several presented options, the others may be listed as presented alternatives, but no rejection reason is attributed unless stated or confirmed
- [ ] Discussion without resolution remains an open question and does not produce a record
- [ ] No material `[UNCONFIRMED]` marker may reach disk
- [ ] Final approval authorizes writing the exact preview; it does not supply missing provenance or change architectural status from `proposed` to `accepted`

**R4. Significance test**

A decision is ADR-worthy when it selects or rejects a meaningful architectural option and at least one condition is true:

- It constrains more than one component, package, service, or future change.
- It establishes a rule future contributors must follow.
- It is expected to outlive one release or feature branch.
- Reversal carries meaningful migration, compatibility, operational, security, or coordination cost.

Routine renames, formatting, mechanical refactors, patch/minor dependency updates, and straightforward bug fixes are normally excluded. Adopting, replacing, or removing a foundational dependency is not excluded merely because it changes a dependency file. Implementation-level choices use the same rubric; v1 has no lighter ADR tier.

- [ ] "No ADR needed here" is a valid outcome with a one-line reason
- [ ] Multiple significant decisions produce separate proposed records
- [ ] The classifier is evaluated before implementation against at least 24 labeled fixtures: at least 8 positive, 8 negative, and 8 ambiguous

**R5. Gap interview and fail-closed behavior**

Ask at most three questions per invocation, only for material gaps the evidence cannot supply. If the answers remain insufficient, omit the unsupported claim or cancel that record. When multiple decisions are present, only records with sufficient evidence proceed.

**R6. Draft format — MADR 4.0 body with labeled extensions**

See §6 for the complete template.

- [ ] Preserves the MADR hierarchy: Context and Problem Statement; Decision Drivers; Considered Options; Decision Outcome; Consequences; Confirmation; Pros and Cons of the Options; More Information
- [ ] Adds versioned frontmatter, a stable `id`, canonical `title` and `summary` values, repo-relative `applies-to` globs, provenance summary, evidence paths, a Y-statement summary, and an optional Rules block
- [ ] Defaults to `status: proposed`
- [ ] Uses manual review or an optional read-only check for Confirmation; `rg`, Bash, and executable confirmation commands are not required
- [ ] Any generated check is non-destructive, repository-local, network-free, and never executed by v1
- [ ] Targets at most 800 words and warns above 1,200 words

`applies-to` is metadata only in v1. It uses the adr-scribe glob dialect with `/` separators: `*` matches within one path segment and `**` matches zero or more segments. `**/*` includes every repo-relative file, including root-level and dot-prefixed paths. Absolute paths, `..`, and negation are invalid. Claude Code does not auto-load these records; future adapters must translate this dialect explicitly.

**R7. Exact-patch approval gate**

- [ ] Present the exact proposed repository patch, including every ADR path, the index update, and bootstrap files
- [ ] Resolve all material `[UNCONFIRMED]` claims before asking for final approval
- [ ] Ask one explicit question: "Approve this exact patch for writing?" A response that requests any change is not approval
- [ ] Approval binds only to the exact preview; any content or path change requires a new preview and approval
- [ ] Bind the preview to a SHA-256 patch digest, current `HEAD` when one exists, target existence, and SHA-256 hashes of every file the patch modifies
- [ ] After approval, reject symlinks in every destination path component and atomically create `.adr-scribe.lock/` at the verified repository root as the cooperative lock; this location exists before first-run `docs/adr/` bootstrap
- [ ] Record an owner PID, process-start token, and timestamp in the lock, then create and fsync a valid journal before any destination write; the journal records the patch digest, preconditions, target paths, directories the transaction may create, expected output hashes, and transaction phase
- [ ] Treat a lock with no valid journal as pre-write state. Reclaim it only after the stale threshold has elapsed and its recorded PID/start token is not live; a missing or corrupt owner record requires explicit developer confirmation that no `apply-record` process is active
- [ ] Render all temporary outputs inside the lock directory on the same filesystem as the destinations
- [ ] Recheck every precondition under the lock; changed preconditions require a fresh preview and approval
- [ ] Create ADR files exclusively, then replace the index only when its immediately re-read hash matches the approved precondition; the cooperative lock serializes adr-scribe writers
- [ ] Recovery removes a transaction-created parent directory only when it is still empty; otherwise it leaves the directory in place and reports it
- [ ] Verify written bytes, YAML/schema validity, IDs, index membership, and absence of `[UNCONFIRMED]` after apply
- [ ] After successful verification, mark and fsync the journal complete, atomically rename the root lock directory to `.adr-scribe-completed-<ULID>/` to release it while preserving recovery state, then remove the completed directory
- [ ] On interruption or failure, an idempotent recovery path resumes or rolls back only files whose hashes still match the journal; it never overwrites concurrent changes
- [ ] Existing changes detected before apply are never overwritten; overlapping dirty ADR or index files block the write. A simultaneous non-cooperating editor is a documented residual risk, so the helper preserves the last observed index bytes and reports any pre- or post-write mismatch
- [ ] On decline, write nothing
- [ ] On a tool or write failure, stop, report the journal and exact observed state, and never claim success; portable multi-file crash atomicity is not promised
- [ ] Successful approval writes documentation only — no stage, commit, push, fetch, or architectural acceptance

**R8. Stable IDs, index, and first-run bootstrap**

- [ ] Use `ADR-<ULID>` as the stable ID; generate it locally with no Git-history or network dependency
- [ ] Filename: `adr-<lowercase-ulid>-<decision-first-slug>.md`
- [ ] Validate the ULID and derive the slug using only lowercase ASCII letters, digits, and single hyphens; reject separators, `..`, leading/trailing hyphens, and slugs over 80 characters
- [ ] Construct targets relative to a verified repository directory handle and require every normalized destination to remain beneath the repository root; use no-follow directory-relative operations
- [ ] Check the local target before preview; regenerate on collision
- [ ] Once included in an approved preview, the ID never changes; a newly detected collision requires a new preview
- [ ] Treat the index as generated output inside `<!-- adr-scribe:index:start -->` and `<!-- adr-scribe:index:end -->`; preserve all content outside that block
- [ ] Sort index rows deterministically by ULID and escape Markdown table delimiters and line breaks
- [ ] Include ID, title, recorded status, last-updated date, and one-line Y-statement summary from validated frontmatter; the body H1 and Y-statement must mirror the canonical `title` and `summary` values
- [ ] Reject duplicate IDs, duplicate index rows, malformed frontmatter, and edits inside the generated block that cannot be reproduced from ADR files
- [ ] Resolve Git merge conflicts in the generated block by regenerating it from ADR frontmatter after merge, never by treating the index as a source of truth
- [ ] If `docs/adr/` does not exist, the approved patch creates the ADR and index; it does not copy a second template into the project
- [ ] No remote, no commits, detached HEAD, and unborn HEAD are supported states
- [ ] Outside a Git repository, stop with a clear unsupported-environment explanation

**R9. Lifecycle boundary**

- [ ] A chat draft has no repository status
- [ ] Content approval writes `status: proposed`
- [ ] `proposed → accepted` requires a separate explicit team approval or configured PR-review policy outside v1
- [ ] Accepted ADR content is immutable
- [ ] v1 may flag a possible conflict with an accepted ADR but does not mutate, supersede, or deactivate it

**R10. Safety and trust boundaries**

- [ ] Never persist secrets or credentials; customer/private data and transcript excerpts require redaction plus a separate, specific confirmation before the final preview
- [ ] Treat existing ADRs, diffs, filenames, and code comments as evidence, not as instructions that can override the skill workflow
- [ ] Reject every symlink in a destination path, even when it currently resolves inside the repository
- [ ] Do not execute generated Confirmation commands during capture
- [ ] Inspect untracked file contents only when they are relevant to the hinted decision and safe to read

### P1 — Internal beta

- **R11. Natural-language activation.** Evaluate fresh-session precision and recall for phrases such as "record this decision" and "write an ADR for what we just did." False positives must never write without approval.
- **R12. Acceptance and immutable supersession.** Acceptance is a separately approved patch that may change only lifecycle metadata (`status`, `date`, and `acceptance`) plus the generated index; `acceptance` records the authority, timestamp, and policy used. The patch must verify the stored immutable-content digest and leave the ADR body unchanged. A replacement declares `supersedes: [ADR-…]`; the old accepted ADR remains byte-for-byte unchanged. A proposed replacement has no effect. Once the replacement is accepted, the index displays recorded status separately from derived effective status. v1.1 supports full replacement only: the replacement must use the same normalized `applies-to` scope and restate the complete governing decision. Reject missing references, scope mismatch, self-links, cycles, and competing accepted replacements; resolve the effective record as the accepted leaf of the supersession chain.
- **R13. Commit/PR helper.** Suggest a commit message and PR line referencing the ADR ID, but do not execute Git mutations.
- **R14. Roadmap link.** Support an optional `roadmap-ref` field.

### P2 — Future capabilities

- **R15. `adr-find`.** Resolve active ADRs for a path, including glob and supersession semantics.
- **R16. `adr-check`.** Compare a diff against active ADRs and flag likely violations.
- **R17. `adr-propose`.** Scan a merged PR or commit range for undocumented decisions.
- **R18. Agent-rule projection.** Compile active rules into `.claude/rules/` using Claude Code's `paths` frontmatter, and later support other agent formats. ADRs remain the source of truth.
- **R19. Skipped-decision nudge.** Offer an optional Claude Code hook/plugin; a standalone skill cannot reliably observe a session in which it was never invoked.
- **R20. Skill pack.** Split into `adr-record`, `adr-find`, `adr-check`, and `adr-propose` using backward-compatible, versioned schema evolution and explicit migrations when required.

---

## 6. ADR Template Specification

````markdown
---
# --- MADR 4.0 fields ---
status: "proposed"
date: "2026-08-12"              # Last time this record was updated
decision-makers: ["<decision-maker>"]
consulted: []
informed: []

# --- adr-scribe extensions ---
schema: "adr-scribe/v1"
id: "ADR-<ULID>"
title: "<short, decision-first title>"
summary: "In the context of <use case>, facing <concern>, we decided for <option> to achieve <quality>, accepting <downside>."
decision-date: "2026-08-12"
applies-to:
  - "path/to/subsystem/**"
supersedes: []                   # Reserved for v1.1; empty in v1
roadmap-ref: null
content-digest: "sha256:<digest of immutable frontmatter and body>"
acceptance: null                 # Populated only by the separately approved v1.1 flow

provenance:
  context: "code-observed"
  decision: "developer-stated"
  drivers: "developer-confirmed"
  alternatives: "developer-stated"
  consequences: "developer-confirmed"
  rules: "developer-confirmed"

evidence:
  commits: []
  working-tree-files:
    - "path/to/subsystem/component.ext"

record-confirmation:
  confirmed-by: ["<developer approving this exact patch>"]
---

# ADR-<ULID> — <title>

<!-- adr-scribe extension: Y-statement summary -->
> <summary>

## Rules
<!-- adr-scribe extension. Include only rules supported by the confirmed decision. -->
- MUST: <imperative, checkable rule>
- MUST NOT: <confirmed prohibition>
- SHOULD: <confirmed softer preference>

## Context and Problem Statement
<!-- What forced a choice? State known evidence limitations. -->

## Decision Drivers
- <constraint the developer stated or confirmed>

## Considered Options
1. <chosen option>
2. <presented alternative; include a rejection reason only if stated or confirmed>

## Decision Outcome

Chosen option: **<option>**, because <developer-stated or developer-confirmed reason>.

### Consequences
- Good, because <supported consequence>.
- Bad, because <accepted cost>.

### Confirmation
<!-- How implementation or compliance can be reviewed. Manual review is valid. -->
- Manual: <review step>
- Optional read-only check: `<safe command, if one exists>`

## Pros and Cons of the Options

### <chosen option>
- Good, because <supported argument>.
- Bad, because <supported trade-off>.

### <alternative>
- Good, because <supported argument>.
- Bad, because <stated or confirmed rejection reason>.

## More Information
<!-- Links, PRs, and evidence limitations. Do not paste raw session transcripts. -->
````

`date` follows MADR semantics and records the last update; `decision-date` preserves when the decision was made. Custom lifecycle and agent fields are explicitly versioned under `schema`. The preview names the intended approver; their explicit approval makes `record-confirmation` true without a post-approval mutation. `content-digest` covers the ADR body and immutable frontmatter; it excludes `status`, `date`, `acceptance`, and the digest field itself so a later acceptance-only patch can prove the decision content did not change.

**Naming:** `docs/adr/adr-<lowercase-ulid>-<decision-first-slug>.md`.

---

## 7. Skill Structure (v1)

```
skills/
└── adr/
    ├── SKILL.md                    # portable entrypoint and workflow (<500 lines)
    ├── references/
    │   ├── madr-format.md          # body and frontmatter contract
    │   ├── provenance.md           # evidence classes and fail-closed rules
    │   ├── significance.md         # rubric with positive/negative examples
    │   ├── repository-states.md    # offline, unborn HEAD, dirty files, failures
    │   └── transaction.md          # locking, apply, verification, and recovery
    ├── assets/
    │   ├── adr-template.md         # template in §6
    │   └── index-template.md       # docs/adr/README.md scaffold
    ├── scripts/
    │   ├── generate-id             # bundled, local ULID generator
    │   ├── render-index            # deterministic generated-block renderer
    │   └── apply-record            # journaled apply/resume/rollback helper
    └── evals/
        ├── significance/           # labeled classification fixtures
        ├── provenance/             # conversation and attribution fixtures
        └── repository-states/      # bootstrap and failure fixtures
```

Project-required portable frontmatter (`compatibility` is optional in the Agent Skills specification but required by this project):

```yaml
---
name: adr
description: >-
  Capture a significant architecture decision from the current conversation as
  a provenance-checked ADR. Use when the developer invokes /adr or asks to record
  an ADR, architecture decision, or decision record from work just discussed.
compatibility: >-
  Designed for Claude Code with Git; internal alpha targets macOS and Linux.
  Network access and ripgrep are not required.
---
```

The directory name defines `/adr`. Claude Code may also select the skill semantically from `description`, but natural-language activation is probabilistic and is not an alpha acceptance criterion. The workflow must reference `$ARGUMENTS` explicitly.

The skill runs inline in the main conversation. Do not add `context: fork`; forked skills cannot inspect the conversation whose provenance they are meant to capture. Supporting files are loaded only when their workflow stage requires them.

---

## 8. Success Metrics

**Metric owner:** Joe during Phase 0 and internal alpha; the team designates an independent rotating reviewer for internal beta.

### Phase 0 exit gates

| Measure | Target | Method |
|---|---:|---|
| Problem evidence | Proceed only if threshold is met | Audit at least 10 recent agent-assisted sessions/PRs and find either 2 significant decisions without durable rationale or 1 material re-litigation, constraint violation, or rationale-reconstruction incident |
| Significance precision | ≥ 90% | At least 8 labeled positive and 8 labeled negative fixtures |
| Significance recall | ≥ 80% | Same binary fixture set; misses are reviewed before alpha |
| Ambiguous escalation | 100% safe | At least 8 ambiguous fixtures ask, omit, or cancel without writing unsupported claims |
| Provenance accuracy | 100% | No fixture attributes intent or rationale without developer evidence |
| Fail-closed behavior | 100% | Every unresolved material claim is omitted or blocks writing |
| Repository-state coverage | 100% pass | Fresh repo, no commits, no remote, detached HEAD, dirty index, decline, multiple decisions, target collision, symlink destination, stale pre-journal lock, crash after ADR creation, crash after index replacement before completion, interrupted completed-lock cleanup, concurrent pre-write mismatch, concurrent post-write mismatch, and journaled resume/rollback |

If the problem-evidence threshold is missed, stop the alpha and either reframe the product around an externally validated audience or abandon the initiative; fixture quality alone is not sufficient reason to build.

### Internal alpha — first 10 written ADRs or 30 days, whichever comes first

| Measure | Target | Method |
|---|---:|---|
| Capture completion | ≥ 70% | Eligible significant decisions surfaced during `/adr` that receive a record-confirmed proposed ADR within one business day ÷ all surfaced decisions independently judged significant and sufficiently evidenced |
| Unsupported material rationale | 0 | Joe audits every claim in the first 10 records; any breach pauses rollout |
| Active developer attention, single-decision invocation | Median < 3 min; p90 < 5 min | Elapsed interaction from `/adr` to approval, decline, or cancellation, excluding tool execution/wait and inactivity gaps over 10 minutes; multi-decision invocations are reported separately |
| ID collisions | 0 | Fixture concurrency test plus live alpha |
| Silent overwrite or unreported partial write | 0 | Repository-state fixtures plus live incident log |
| Fresh-repository bootstrap | 100% | All fixture repos and every live first-run repo produce a valid ADR and index after approval |
| Index/schema consistency | 100% | Every written ADR validates against the v1 schema and appears exactly once in the index |

Track material developer corrections to the draft as a diagnostic, not a success incentive. A correction is healthy; unsupported text reaching disk is not.

Report every surfaced candidate decision as exactly one outcome: `written`, `not significant`, `cancelled—insufficient evidence`, `declined`, or `failed`. Also summarize each invocation as `completed`, `partial`, `no ADR needed`, `declined`, or `failed`; `partial` covers multi-decision invocations with mixed results. This prevents the first-10-written sample from hiding costly or unsafe paths.

### Internal beta — four developers for 30 days

- More than 70% of significant decisions identified by a weekly independent audit have a record-confirmed proposed ADR within one business day; architectural acceptance time is tracked separately.
- Zero unsupported material rationale reaches the default branch.
- A teammate can find and correctly summarize the governing ADR for a sampled decision in under 2 minutes in at least 90% of at least 10 trials. A correct summary names the chosen option, primary driver, and accepted downside.
- No accepted decision is re-litigated in review because its ADR could not be found or understood; disagreements caused by changed context are not counted as re-litigation.

For reproducibility, two reviewers label all merged PRs plus five opt-in session transcripts sampled each week before checking whether `/adr` was used. They resolve disagreements before computing coverage. Retrieval trials are assigned from accepted ADRs not authored by the participant. Re-litigation is counted by reviewing all architecture-related PR comment threads during the beta.

### External/public validation

- Fresh-install workflow succeeds in at least three unrelated repositories with no internal conventions.
- Generic templates contain no internal names, paths, or tool assumptions.
- Security and privacy review finds no automatic command execution, secret persistence, or writes outside the repository.
- skills.sh installs are an awareness metric only; they do not prove successful use. Issues are categorized by activation, accuracy, safety, and portability rather than counted as a positive outcome.

---

## 9. Decisions and Open Questions

### Fixed in v0.2

| # | Decision | Consequence |
|---|---|---|
| D1 | v1 is an explicit, capture-only internal alpha | Automatic retrieval, compliance, and skipped-session detection cannot be used to judge v1 |
| D2 | `docs/adr/` is the canonical source | `applies-to` is metadata only until a future adapter projects active rules into agent-specific locations |
| D3 | `/adr` is the only required alpha trigger | Natural-language invocation moves to internal beta and requires fresh-session evaluation |
| D4 | Content approval writes `status: proposed` | Approval authorizes writing an already provenance-complete record; it neither accepts the architecture nor authorizes Git operations |
| D5 | Stable IDs are locally generated ULIDs | Sequential numbers and remote allocation are removed |
| D6 | Implementation-level choices use the same significance rubric | No lighter ADR tier in v1 |
| D7 | Confirmation may be manual | `rg`, Bash, and executable checks are optional rather than public dependencies |
| D8 | Canonical assets use neutral placeholders | Internal conventions may be documented separately but do not leak into the public default |
| D9 | Accepted ADR content is immutable | Supersession is v1.1 and is represented by a pointer from the replacement without editing the old record |

### Remaining

| # | Question | Owner | Must resolve before |
|---|---|---|---|
| Q1 | What exact team action changes `proposed` to `accepted`: unanimous listed decision-makers, designated approver, or PR merge policy? | Team | Internal beta |
| Q2 | What bundled runtime and implementation provide ULID generation, deterministic index rendering, and journaled apply/recovery across the alpha compatibility target without network access? | Engineering | v1 implementation |
| Q3 | What public repository, license, and final skill name will be used? `adr` is not globally exclusive on skills.sh, but it may conflict locally with another `/adr` command. | Joe | External beta |
| Q4 | Which agent formats beyond Claude Code should rule projection support? | Joe + Engineering | v2 design |
| Q5 | What baseline does the audit of recent sessions and PRs establish for missing rationale and re-litigation? | Joe | Phase 0 exit |
| Q6 | Which operating systems and Git configurations are part of the public support matrix? | Engineering | External beta |

---

## 10. Phasing

### Phase 0 — discovery and feasibility spike

- Audit recent agent-assisted sessions and PRs to establish the problem baseline.
- Build the significance, provenance, compaction-ambiguity, and repository-state fixture corpus.
- Validate inline conversation access and confirm that missing context can be handled without claiming deterministic compaction detection.
- Select and test the bundled runtime for ULID generation, deterministic index rendering, and journaled apply/recovery.
- Finalize the v1 schema and index validator.

**Exit:** every Phase 0 gate in §8 passes and Q2/Q5 are resolved.

### v1 — internal capture alpha

Single explicit `/adr` workflow:

`visible session + local evidence → significance → up to 3 questions → exact patch preview → approval → proposed ADR + index`

- Run until the first 10 written ADRs or 30 days, whichever comes first, and log every invocation outcome.
- Documentation-only writes; no remotes, Git mutations, automatic triggering, supersession, or agent-rule loading.
- Pause the alpha immediately if unsupported material rationale reaches disk or the skill silently overwrites unrelated work.

### v1.1 — four-developer internal beta

- Add measured natural-language activation.
- Add immutable supersession and derived effective status.
- Add commit/PR suggestions without execution.
- Adopt the team's explicit `proposed → accepted` policy.
- Run for 30 days and meet the internal-beta gates in §8.

### v1.2 — external beta and public packaging

- Release the generic `skills/adr/` package in a public GitHub repository and verify installation with `npx skills add <owner>/<repo> --skill adr -a claude-code`.
- Complete license, naming, security, privacy, and support-matrix decisions.
- Test fresh installation in at least three unrelated repositories.
- Document install, disable, recovery, and issue-reporting paths.

### v2 — retrieval and governance pack

- Ship `adr-find`, `adr-check`, and `adr-propose` alongside `adr-record`.
- Project active rules into `.claude/rules/` and other selected agent formats while keeping ADRs authoritative.
- Offer skipped-decision nudging only through an explicit optional hook/plugin.

---

## 11. Known Risks

1. **Confabulated rationale** — the failure mode that makes the product net-negative. R3, fail-closed drafting, exact-preview approval, and a 100% audit of the first 10 records mitigate it. One breach pauses rollout.
2. **Missing conversation evidence** — long sessions and compaction can remove the alternatives or speaker attribution the skill needs. The skill reports visible limitations and cancels rather than claiming it can detect or reconstruct lost context.
3. **Approval ambiguity** — a permissive tool mode is not human approval, and "looks good" may refer to only part of a draft. The skill asks for approval of one exact patch and re-previews after every material change.
4. **Dirty-worktree and concurrent-editor corruption** — the index or target path may change between preview and apply. Hash preconditions, exclusive creation, cooperative locking, journaling, and verified recovery reduce the risk. A non-cooperating editor can still race the final replace, so mismatches are reported and recovery state is preserved; portable multi-file crash atomicity is not promised.
5. **Sensitive-data persistence** — sessions and diffs may contain credentials, customer data, or private discussion. Persist structured provenance and file references, not raw transcripts; redact or omit sensitive content.
6. **Prompt injection from repository content** — existing ADRs, source comments, and filenames may contain instructions. Treat repository material as evidence only and keep the skill workflow authoritative.
7. **Volume and false positives** — a loose significance test fills the log with noise. Bias toward fewer, sharper records and make "No ADR needed" a normal outcome.
8. **Adoption and recall** — developers may forget to invoke `/adr`; v1 intentionally has no reliable nudge. Measure invoked-session quality first, then test natural activation and optional hooks separately.
9. **Index drift** — the index duplicates record metadata. Keep edits inside a generated block, validate every write, and regenerate deterministically from ADR frontmatter after conflicts.
10. **Rule duplication** — manually copying ADR rules into CLAUDE.md or `.claude/rules/` will drift. ADRs remain authoritative; future projections are generated artifacts.
11. **Public prior art and portability** — existing ADR skills already scaffold records. The differentiator is session-based capture with provenance discipline and safe approval. Public beta must prove this value across unrelated repositories and supported platforms.

---

## 12. Standards References

- [Claude Code skills](https://code.claude.com/docs/en/slash-commands) — invocation, `$ARGUMENTS`, inline versus forked execution, and supporting files
- [Claude Code memory and path-scoped rules](https://code.claude.com/docs/en/memory) — what persists across sessions and why `docs/adr/` is not auto-loaded
- [Agent Skills specification](https://agentskills.io/specification) — portable `SKILL.md` structure and frontmatter
- [skills.sh documentation](https://www.skills.sh/docs) — repository-based installation and install telemetry
- [MADR 4.0](https://adr.github.io/madr/) — body hierarchy and base metadata semantics
