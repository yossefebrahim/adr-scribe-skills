# Is this decision ADR-worthy?

Load at S2. Bias toward **fewer, sharper records**. A decision log full of noise is
worse than a short one, because nobody reads it and the real constraints get buried.

## The test

A decision earns a record when it **selects or rejects a meaningful architectural
option** *and* at least one of these is true:

1. It constrains more than one component, package, service, or future change.
2. It establishes a rule future contributors must follow.
3. It is expected to outlive one release or feature branch.
4. Reversing it carries meaningful migration, compatibility, operational, security,
   or coordination cost.

Both halves matter. A choice that binds the whole codebase but had no alternative
(the language the project is already written in) is not a decision. A choice between
real alternatives that affects one function for one sprint is not architectural.

## Normally excluded

Renames · formatting · mechanical refactors · patch and minor dependency bumps ·
straightforward bug fixes · adding a test · fixing a typo · reverting your own commit
from ten minutes ago.

**Not excluded merely because it edits a dependency file:** adopting, replacing, or
removing a *foundational* dependency is exactly the kind of decision that needs a
record. The question is what it constrains, not which file changed.

Implementation-level choices use this same rubric. v1 has no lighter tier.

## Worked examples

**Yes — record it**

- "We'll use Riverpod instead of Bloc for state management." → constrains every
  feature module; reversal is a rewrite.
- "Auth stays a separate service; the monolith calls it over HTTP." → a boundary
  other work must respect.
- "We're dropping Postgres for SQLite in the desktop build." → migration cost,
  operational change, outlives the branch.
- "No ORM — hand-written SQL in a repository layer." → a rule contributors follow.
- "Errors cross the API boundary as RFC 7807 problem documents." → a contract.

**No — don't**

- "Renamed `fetchUser` to `getUser`." → mechanical.
- "Bumped lodash 4.17.20 → 4.17.21." → routine patch bump.
- "Extracted this 40-line function into two." → local refactor.
- "Fixed the off-by-one in the paginator." → a bug fix.
- "Added a test for the empty-cart case." → coverage, not architecture.
- "Used a `for` loop instead of `map` here." → style.

**Ambiguous — ask, or omit**

- "We'll probably move to a queue later." → unresolved. An open question is not a
  decision. Do **not** record it.
- "I set the timeout to 30s." → record only if the developer says *why* and it binds
  other components. A bare number with no stated reason is configuration.
- "Let's try Tailwind for this page and see." → an experiment. Ask whether it is
  meant to bind future pages. If they say "just this page", there is no ADR.
- Agent proposed three caching strategies, developer said "sounds good" and moved on
  → which one? Nothing was actually chosen. Ask, or report no decision.

## Outcomes

- Nothing qualifies → "No ADR needed" plus a one-line reason. This is success.
- Several qualify → separate records, each with its own evidence and approval.
- Something qualifies but the *why* is missing → that is S4's problem, not S2's.
  Significance and evidence are different tests; do not reject a real decision here
  because you have not asked about it yet.
