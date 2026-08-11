---
status: "proposed"
date: "2026-08-12"
decision-makers:
  - "<decision-maker>"
consulted: []
informed: []
schema: "adr-scribe/v1"
id: "ADR-01J000000000000000000000AA"
title: "<short, decision-first title>"
summary: "In the context of <use case>, facing <concern>, we decided for <option> to achieve <quality>, accepting <downside>."
decision-date: "2026-08-12"
applies-to:
  - "path/to/subsystem/**"
supersedes: []
roadmap-ref: null
content-digest: "sha256:bd7e15b19abe87a1a21163c0f5f7c1166e9a303ec88e60873ea7f889f469c4f3"
acceptance: null
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
    - "path/to/component.ext"
record-confirmation:
  confirmed-by:
    - "<approver>"
---
# ADR-01J000000000000000000000AA — <short, decision-first title>

<!-- adr-scribe extension: Y-statement summary -->
> In the context of <use case>, facing <concern>, we decided for <option> to achieve <quality>, accepting <downside>.

## Rules
<!-- Only rules supported by the confirmed decision. -->
- MUST: <imperative, checkable rule>

## Context and Problem Statement

<what forced a choice; state known evidence limitations>

## Decision Drivers

- <constraint the developer stated or confirmed>

## Considered Options

1. <chosen option>
2. <presented alternative>

## Decision Outcome

Chosen option: **<chosen option>**, because <developer-stated or developer-confirmed reason>

### Consequences

- Good, because <supported consequence>
- Bad, because <accepted cost>

### Confirmation

- Manual: <review step>

## Pros and Cons of the Options

### <chosen option>

- Good, because <supported argument>
- Bad, because <supported trade-off>

### <presented alternative>

- No arguments were stated or confirmed for this option.

## More Information

<links, PRs, evidence limitations. Never paste transcripts.>
