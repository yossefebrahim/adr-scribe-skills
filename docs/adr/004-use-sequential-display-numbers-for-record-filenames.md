---
status: "proposed"
date: "2026-08-13"
decision-makers:
  - "yossefebrahim"
consulted: []
informed: []
schema: "adr-scribe/v1"
id: "ADR-01KZVZXFDYE0XEWQHASJM99X5G"
title: "Use sequential display numbers for record filenames"
summary: "In the context of developers browsing and citing architecture records, facing ULID filenames that humans cannot read or say aloud, we decided for sequential NNN-title filenames to achieve readable, citable record names, accepting that a branch merge can produce duplicate numbers that require a rename."
decision-date: "2026-08-13"
applies-to:
  - "skills/adr/scripts/**"
  - "docs/adr/**"
supersedes: []
roadmap-ref: null
content-digest: "sha256:73208b7fe161a06522faee7e70f3666abdf6f30e5173d2643f213fddd10d489c"
acceptance: null
provenance:
  context: "code-observed"
  decision: "developer-stated"
  drivers: "developer-stated"
  alternatives: "developer-confirmed"
  consequences: "code-observed"
  rules: "developer-confirmed"
evidence:
  commits:
    - "b42e011086379ddaf81aeb0d594ea6ec17e41a69"
  working-tree-files:
    - "skills/adr/scripts/adr_scribe/index.py"
    - "skills/adr/scripts/prepare-record"
record-confirmation:
  confirmed-by:
    - "yossefebrahim"
---
# ADR-01KZVZXFDYE0XEWQHASJM99X5G — Use sequential display numbers for record filenames

<!-- adr-scribe extension: Y-statement summary -->
> In the context of developers browsing and citing architecture records, facing ULID filenames that humans cannot read or say aloud, we decided for sequential NNN-title filenames to achieve readable, citable record names, accepting that a branch merge can produce duplicate numbers that require a rename.

## Rules
<!-- Only rules supported by the confirmed decision. -->
- MUST: record filenames are NNN-slug.md, the number allocated as max+1 from records on disk at preview time
- MUST NOT: the sequence number serves as identity; digests, supersedes, and references bind to the ULID

## Context and Problem Statement

The original design (PRD decision D5) mandated ULID-only filenames precisely to avoid sequential allocation and its merge collisions. In the skill's first live use the developer found the resulting names unreadable and asked for 001-style filenames. The revision keeps the ULID in frontmatter as the stable identity that digests, supersedes references, and the journal bind to; the sequence number is display identity only, allocated as max+1 from the records already on disk at preview time.

## Decision Drivers

- Record names should be readable and citable: humans browse the folder and refer to records by number

## Considered Options

1. Sequential display numbers in filenames, ULID retained as stable identity
2. ULID-only filenames (the original D5 design)
3. Ordinal column in the generated index only, filenames unchanged

## Decision Outcome

Chosen option: **Sequential display numbers in filenames, ULID retained as stable identity**, because record names must be readable and citable by humans, and keeping the ULID as the stable identity in frontmatter means a merge-time renumber cannot break digests or references

### Consequences

- Good, because Directory listings and the index read in decision order under human-friendly names
- Bad, because Concurrent branches can mint the same number; validate-adr reports the duplicate and one file must be renamed

### Confirmation

- Manual: Review that a new record receives the next free number and that validate-adr flags a manufactured duplicate
- Optional read-only check: `make test`

## Pros and Cons of the Options

### Sequential display numbers in filenames, ULID retained as stable identity

- Good, because Filenames and the index read in decision order with human-friendly names
- Good, because Renumbering after a merge is a pure file rename, because nothing binds to the number
- Bad, because Two branches can allocate the same number; the collision must be resolved by renaming one file at merge

### ULID-only filenames (the original D5 design)

- Good, because No coordination and no merge collisions
- Bad, because Names are unreadable and cannot be cited in conversation
- Rejected, because the developer found ULID filenames hostile to browsing and citing records in first live use

### Ordinal column in the generated index only, filenames unchanged

- Good, because No change to the collision-free filename scheme
- Bad, because The files themselves remain unreadable in directory listings

## More Information

Decision and rationale stated by the developer in-session on 2026-08-13, reversing PRD decision D5; the PRD was revised the same day. The alternatives above were presented by the agent during the session and the developer selected among them; the index-ordinal option's rejection reason was not stated, so none is recorded.
