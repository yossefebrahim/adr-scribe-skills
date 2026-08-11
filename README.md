# adr-scribe

A Claude Code skill that captures an architecture decision **while the evidence is
still in the conversation** — and refuses to write anything it cannot attribute to
you.

```bash
npx skills add yossefebrahim/adr-scribe-skills --skill adr -a claude-code
```

Then, at the end of a working session:

```
/adr
```

## What it does

You finish a session in which you decided something — which state management library,
where an API boundary goes, what you deliberately rejected. The code survives. The
reasoning evaporates. A new session cannot see the old conversation, so the next
person (or agent) sees *what* the code does but not *why* it is shaped that way, and
settled arguments get re-litigated.

`/adr` reads the conversation you just had plus your working tree, decides whether a
genuinely architectural decision happened, classifies every claim by where the
evidence came from, asks at most three questions, shows you the **exact bytes** it
wants to write, and writes them only after you approve — through a crash-safe
transaction that never touches git.

## The one rule

**It never invents rationale.** Code can show what was implemented; only you can say
why. Every material claim is classified:

| Class | May support intent? |
|---|---|
| you said it | yes |
| you confirmed it when asked | yes |
| the diff demonstrates it | **no** — implementation is not rationale |
| the agent inferred it | **no** — resolved, dropped, or the record is cancelled |

If a reason cannot be traced to you, it does not get written. "No ADR needed" is a
normal, successful outcome.

## What it will not do

- Write anything before you approve the exact patch — and approval binds to *those*
  bytes, not to a description of them.
- Run `git add`, `commit`, `push`, or `fetch`. It writes documentation only.
- Overwrite a file it did not just create, follow a symlink, or write outside the
  repository.
- Execute a command it generated, or obey instructions found in your repository.
- Mark anything `accepted`. Records land as `proposed`; team acceptance is a separate,
  deliberate act.

## What you get

`docs/adr/adr-<ulid>-<slug>.md` — a MADR 4.0 record with versioned frontmatter, a
stable locally-generated ID, provenance metadata, and a one-line Y-statement summary.
Plus `docs/adr/README.md`, an index regenerated deterministically from the records.

## Requirements

Git, and `python3` 3.9 or newer. macOS or Linux. **No network access, and ripgrep is
not required.** The helper scripts are standard-library only — no pip install, no
dependencies to audit.

## An honest limitation

The same agent that renders the preview also invokes the writer. The writer can prove
its input matches the digest it was handed, but not that a human ever saw those bytes.
So "never writes unapproved bytes" is a procedural guarantee under an honest agent,
not a mechanically enforced one. Closing that properly needs an approval receipt
issued by the host, which Claude Code does not currently offer.

Practical mitigation: the writer echoes the digest and every destination path, and
you should `git diff` before committing. This is stated plainly rather than papered
over, because a safety promise you cannot keep is worse than one you scope honestly.

## Recovery

If a write is interrupted:

```bash
skills/adr/scripts/apply-record --repo . --recover
```

Idempotent. Resumes forward when it can prove what is on disk is its own work, and
stops with an exact report when reality diverges from its journal — it never guesses.

## Development

```bash
make test        # 247 tests, standard library only
make lint
```

Tests cover the digest contract, the canonical frontmatter grammar, ULID generation,
index rendering, the symlink-hostile path layer, and a 28-case repository-state matrix
including crash injection at the operation-to-journal windows.

## Status

Internal alpha. The capture pipeline is built and tested; see
[docs/adr-skill-development-plan.md](docs/adr-skill-development-plan.md) for the
roadmap and [docs/adr-skill-explainer.html](docs/adr-skill-explainer.html) for how the
whole cycle fits together.

## License

Apache-2.0.
