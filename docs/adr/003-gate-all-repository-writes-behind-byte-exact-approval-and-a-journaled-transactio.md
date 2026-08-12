---
status: "proposed"
date: "2026-08-13"
decision-makers:
  - "yossefebrahim"
consulted: []
informed: []
schema: "adr-scribe/v1"
id: "ADR-01KZVX5130A57K2157ZFTD2KB1"
title: "Gate all repository writes behind byte-exact approval and a journaled transaction"
summary: "In the context of an agent skill that writes decision records into a developer's repository, facing the risk that generated content lands without the developer having reviewed exactly what will be written, we decided for a preview, byte-exact approval, and journaled single-writer transaction to achieve writes that are provably the approved bytes and recoverable after interruption, accepting a substantially heavier write path than direct file edits."
decision-date: "2026-08-12"
applies-to:
  - "skills/adr/scripts/**"
  - "docs/adr/**"
supersedes: []
roadmap-ref: null
content-digest: "sha256:89f41e22526ba59a234c736d9278fb2a8e935208ed1c1567e947b8d9de6b5a81"
acceptance: null
provenance:
  context: "developer-stated"
  decision: "developer-stated"
  drivers: "developer-stated"
  alternatives: "developer-stated"
  consequences: "code-observed"
  rules: "developer-stated"
evidence:
  commits:
    - "64e9b04324f6316d959f263ed7ce91066d9e095a"
  working-tree-files: []
record-confirmation:
  confirmed-by:
    - "yossefebrahim"
---
# ADR-01KZVX5130A57K2157ZFTD2KB1 — Gate all repository writes behind byte-exact approval and a journaled transaction

<!-- adr-scribe extension: Y-statement summary -->
> In the context of an agent skill that writes decision records into a developer's repository, facing the risk that generated content lands without the developer having reviewed exactly what will be written, we decided for a preview, byte-exact approval, and journaled single-writer transaction to achieve writes that are provably the approved bytes and recoverable after interruption, accepting a substantially heavier write path than direct file edits.

## Rules
<!-- Only rules supported by the confirmed decision. -->
- MUST: docs/adr is written only by apply-record; no agent tool edits it directly
- MUST: apply-record refuses a patch whose digest does not match the approved digest
- MUST NOT: the helpers stage, commit, push, or fetch

## Context and Problem Statement

The skill's purpose is to write into someone else's repository. The PRD (docs/adr-skill-prd.md) makes safe, unsurprising writes a top-level product goal: an unreviewed ADR with plausible-but-wrong rationale is worse than no ADR, and a write that spans two files (record plus index) can be interrupted at any point, so portable multi-file crash atomicity cannot be promised and recoverable state must be preserved instead.

## Decision Drivers

- Nothing may be written before approval; tool permission alone is not approval
- Approval must apply to the exact proposed patch, not to a description of it
- An interrupted write must leave recorded, recoverable state rather than a guess
- The helper must never stage, commit, push, or fetch

## Considered Options

1. Preview staged outside the repository, SHA-256 patch-digest approval, cooperative lock plus write-ahead journal
2. Direct file writes by the agent without a binding approval step

## Decision Outcome

Chosen option: **Preview staged outside the repository, SHA-256 patch-digest approval, cooperative lock plus write-ahead journal**, because safe and unsurprising writes are a product goal: nothing is written before approval, approval binds to the exact proposed patch, and interrupted writes must remain recoverable (PRD goal 4 and requirement R7)

### Consequences

- Good, because An interruption at any point leaves the repository recoverable without guessing
- Bad, because The transactional write path dominates the helper codebase and its test suite

### Confirmation

- Manual: Review that the transaction tests still cover every crash-injection point and both refuse paths: digest mismatch and tampered payload
- Optional read-only check: `make test`

## Pros and Cons of the Options

### Preview staged outside the repository, SHA-256 patch-digest approval, cooperative lock plus write-ahead journal

- Good, because The bytes shown for approval are provably the bytes written
- Good, because Recovery after an interruption is mechanical, keyed to hashes recorded in the journal
- Bad, because Considerably more code than writing files directly: lock, journal, staged payloads, recovery, crash-injection tests

### Direct file writes by the agent without a binding approval step

- Good, because Trivial to implement
- Bad, because The approved preview and the written file can silently differ
- Bad, because An interruption mid-write leaves no recorded state to recover from
- Rejected, because the PRD names auto-writing without approval as a primary risk: an unreviewed ADR with plausible-but-wrong rationale is worse than no ADR, and explicit approval is a workflow invariant

## More Information

Requirements are docs/adr-skill-prd.md, goal 4 and requirement R7 (last updated 2026-08-12); the developer confirmed in-session on 2026-08-13 that the PRD is their decision. The transaction design is documented in skills/adr/references/transaction.md.
