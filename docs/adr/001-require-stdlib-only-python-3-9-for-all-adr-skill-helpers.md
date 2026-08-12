---
status: "proposed"
date: "2026-08-13"
decision-makers:
  - "yossefebrahim"
consulted: []
informed: []
schema: "adr-scribe/v1"
id: "ADR-01KZVWEF64Y8AFXTPA37GHD2BS"
title: "Require stdlib-only Python 3.9+ for all adr skill helpers"
summary: "In the context of shipping the adr skill's helper scripts to every machine that runs Claude Code, facing the impossibility of guaranteeing that third-party packages are installed there, we decided for a stdlib-only Python implementation with a 3.9 floor to achieve zero-install portability, accepting that parsing and transaction machinery must be hand-written and maintained in this repository."
decision-date: "2026-08-12"
applies-to:
  - "skills/adr/scripts/**"
supersedes: []
roadmap-ref: null
content-digest: "sha256:3d4a83eb6936d01bc3d2a9e48105846238e2e559bbc9c6199abf6429094a7388"
acceptance: null
provenance:
  context: "code-observed"
  decision: "developer-confirmed"
  drivers: "developer-confirmed"
  alternatives: "developer-confirmed"
  consequences: "code-observed"
  rules: "developer-confirmed"
evidence:
  commits:
    - "64e9b04324f6316d959f263ed7ce91066d9e095a"
  working-tree-files: []
record-confirmation:
  confirmed-by:
    - "yossefebrahim"
---
# ADR-01KZVWEF64Y8AFXTPA37GHD2BS — Require stdlib-only Python 3.9+ for all adr skill helpers

<!-- adr-scribe extension: Y-statement summary -->
> In the context of shipping the adr skill's helper scripts to every machine that runs Claude Code, facing the impossibility of guaranteeing that third-party packages are installed there, we decided for a stdlib-only Python implementation with a 3.9 floor to achieve zero-install portability, accepting that parsing and transaction machinery must be hand-written and maintained in this repository.

## Rules
<!-- Only rules supported by the confirmed decision. -->
- MUST: helper scripts under skills/adr/scripts import only the Python standard library
- MUST: helper scripts remain compatible with Python 3.9

## Context and Problem Statement

The skill's helper scripts (prepare-record, apply-record, validate-adr, render-index) run on whatever Python interpreter is present on the machine where the skill is installed. Skills are distributed as plain files with no install hook, so nothing guarantees pip, a virtualenv, or any third-party package is available. A runtime had to be chosen that works on an unprepared machine.

## Decision Drivers

- The helpers must run anywhere Claude Code runs, with zero install step
- Python 3.9 matches the oldest system Python still common on target machines

## Considered Options

1. Stdlib-only Python with a 3.9 floor
2. Third-party dependencies (for example PyYAML) with an install step

## Decision Outcome

Chosen option: **Stdlib-only Python with a 3.9 floor**, because the helper scripts must work on whatever Python ships with the machine, with no dependency installation, and 3.9 is the oldest interpreter still commonly found there

### Consequences

- Good, because Any machine that can run Claude Code can run the helpers without setup
- Bad, because The canonical frontmatter parser and transaction code are maintained in this repository instead of being delegated to established libraries

### Confirmation

- Manual: Review that no module under skills/adr/scripts imports a package outside the Python standard library, and that CI still runs the suite on Python 3.9

## Pros and Cons of the Options

### Stdlib-only Python with a 3.9 floor

- Good, because Runs on an unprepared machine with no dependency installation
- Bad, because Frontmatter parsing, digest canonicalization, and transaction machinery are hand-written instead of using mature libraries

### Third-party dependencies (for example PyYAML) with an install step

- Good, because Mature, widely reviewed parsing libraries
- Bad, because Requires an install step that skill distribution cannot guarantee
- Rejected, because skill distribution drops files onto a machine and cannot guarantee any package installation

## More Information

Rationale originally proposed in docs/adr-skill-development-plan.md (decision E1) and confirmed by the developer in-session on 2026-08-13. Alternatives beyond a dependency-based approach were not discussed.
