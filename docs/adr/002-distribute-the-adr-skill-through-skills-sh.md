---
status: "proposed"
date: "2026-08-13"
decision-makers:
  - "yossefebrahim"
consulted: []
informed: []
schema: "adr-scribe/v1"
id: "ADR-01KZVWRFCF67JQDJ5T2RW0Z6NB"
title: "Distribute the adr skill through skills.sh"
summary: "In the context of publishing the adr skill to developers outside this repository, facing the question of where users will find and install it, we decided for distribution through skills.sh to achieve reach on the registry where agent skills are discovered, accepting that the repository layout and skill metadata must conform to its conventions."
decision-date: "2026-08-12"
applies-to:
  - "skills/**"
supersedes: []
roadmap-ref: null
content-digest: "sha256:ff18651708e47f777c9d5e97d642e313f8b3e49d86eec4b97d01c0ea9a12040c"
acceptance: null
provenance:
  context: "code-observed"
  decision: "developer-stated"
  drivers: "developer-stated"
  alternatives: "developer-stated"
  consequences: "code-observed"
  rules: "developer-stated"
evidence:
  commits:
    - "64e9b04324f6316d959f263ed7ce91066d9e095a"
  working-tree-files:
    - "skills-lock.json"
record-confirmation:
  confirmed-by:
    - "yossefebrahim"
---
# ADR-01KZVWRFCF67JQDJ5T2RW0Z6NB — Distribute the adr skill through skills.sh

<!-- adr-scribe extension: Y-statement summary -->
> In the context of publishing the adr skill to developers outside this repository, facing the question of where users will find and install it, we decided for distribution through skills.sh to achieve reach on the registry where agent skills are discovered, accepting that the repository layout and skill metadata must conform to its conventions.

## Context and Problem Statement

The adr skill is built to be used beyond this repository, so a distribution channel had to be chosen. Skills installed from skills.sh are copied into a project's skills directory by the skills CLI; there is no separate registry submission step, and discovery is driven by installs. The developer directed during planning that the skill be ready to deploy there.

## Decision Drivers

- The skill should be discoverable where people already look for agent skills

## Considered Options

1. skills.sh (install via the skills CLI)

## Decision Outcome

Chosen option: **skills.sh (install via the skills CLI)**, because reach and discovery: being installable from the registry where agent skills are found is the point of publishing the skill

### Consequences

- Good, because The skill can be installed onto any machine with a single command
- Bad, because The skills/adr directory layout, naming, and SKILL.md frontmatter must track external spec requirements

### Confirmation

- Manual: On a clean machine or checkout, run the documented skills.sh install command and confirm the adr skill becomes invocable

## Pros and Cons of the Options

### skills.sh (install via the skills CLI)

- Good, because It is the registry where people find and install agent skills
- Good, because No publishing infrastructure to run; the GitHub repository is the source of truth
- Bad, because Repository layout and skill metadata are constrained by skills.sh and Agent Skills spec conventions

## More Information

The developer directed skills.sh deployment during planning and stated the reach-and-discovery rationale in-session on 2026-08-13. No alternative distribution channel was discussed, so none is listed. Deployment-readiness details are in docs/adr-skill-development-plan.md, section 9.
