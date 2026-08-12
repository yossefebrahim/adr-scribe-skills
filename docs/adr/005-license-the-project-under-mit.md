---
status: "proposed"
date: "2026-08-13"
decision-makers:
  - "yossefebrahim"
consulted: []
informed: []
schema: "adr-scribe/v1"
id: "ADR-01KZW001709Y84ZKM96D41V4W0"
title: "License the project under MIT"
summary: "In the context of publishing the adr skill as open source, facing a choice between MIT and the development plan's Apache-2.0 recommendation, we decided for the MIT License to achieve simplicity and the broadest adoption with the least friction, accepting the loss of Apache-2.0's explicit patent grant."
decision-date: "2026-08-13"
applies-to:
  - "**/*"
supersedes: []
roadmap-ref: null
content-digest: "sha256:18cab553a70bccdff5ade736efe1a1d8a5d8755d3daace2bcb5933f79563bd95"
acceptance: null
provenance:
  context: "code-observed"
  decision: "developer-stated"
  drivers: "developer-stated"
  alternatives: "developer-confirmed"
  consequences: "code-observed"
  rules: "developer-stated"
evidence:
  commits:
    - "b42e011086379ddaf81aeb0d594ea6ec17e41a69"
  working-tree-files: []
record-confirmation:
  confirmed-by:
    - "yossefebrahim"
---
# ADR-01KZW001709Y84ZKM96D41V4W0 — License the project under MIT

<!-- adr-scribe extension: Y-statement summary -->
> In the context of publishing the adr skill as open source, facing a choice between MIT and the development plan's Apache-2.0 recommendation, we decided for the MIT License to achieve simplicity and the broadest adoption with the least friction, accepting the loss of Apache-2.0's explicit patent grant.

## Rules
<!-- Only rules supported by the confirmed decision. -->
- MUST: the root LICENSE, the bundled skills/adr/LICENSE, and the SKILL.md license field stay aligned on MIT

## Context and Problem Statement

The development plan left the license open as question Q3 and recommended Apache-2.0, citing its explicit patent grant. The developer resolved Q3 by adding MIT LICENSE files at the repository root and inside the skill bundle, setting the SKILL.md license field to MIT, and marking the plan's M6.3 row resolved.

## Decision Drivers

- The shortest, most widely understood permissive license minimizes friction for users of a small tool

## Considered Options

1. MIT License
2. Apache-2.0 (the plan's recommendation)

## Decision Outcome

Chosen option: **MIT License**, because simplicity and adoption win for a small tool: the shortest, most widely understood permissive license carries the least friction for its users

### Consequences

- Good, because A single, universally recognized license with no notice overhead
- Bad, because Users and contributors receive no explicit patent grant, which Apache-2.0 would have provided

### Confirmation

- Manual: Review that the root LICENSE, skills/adr/LICENSE, and the SKILL.md license field all say MIT

## Pros and Cons of the Options

### MIT License

- Good, because Simple, short, and universally recognized
- Bad, because No explicit patent grant

### Apache-2.0 (the plan's recommendation)

- Good, because Explicit patent grant
- Bad, because Longer and heavier-weight for a small tool

## More Information

Resolves the plan's open question Q3. The developer adopted MIT in commit b42e011 on 2026-08-13 and stated the rationale in-session the same day. The plan had recommended Apache-2.0 for its patent grant; no rejection reason for Apache-2.0 beyond the stated simplicity-and-adoption driver was given, so none is recorded.
