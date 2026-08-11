# Provenance: where every claim came from

Load at S3. This is the part of the skill that makes it worth using. Everything else
is formatting.

## The four classes

| Class | Meaning | May support intent? |
|---|---|---|
| `developer-stated` | The developer explicitly said it | **yes** |
| `developer-confirmed` | The developer confirmed that exact claim when asked | **yes** |
| `code-observed` | The diff or implementation demonstrates a technical fact | **no** |
| `[UNCONFIRMED]` | You inferred or reconstructed it | **no** |

`code-observed` is the one people get wrong. A diff can prove *what* exists. It can
never prove *why* it was chosen — the reason lives in someone's head, and the only
way it reaches the record is if they say it.

`[UNCONFIRMED]` is an internal working state. It must never reach disk; the persisted
schema cannot even express it, and `apply-record` refuses the marker outright.

## The claim ledger

Before building the record, list every material claim internally:

```
claim: "Bloc was rejected because its boilerplate slowed feature work"
class: developer-stated
locator: developer, mid-session: "bloc's boilerplate is killing our velocity"
targets: considered-options[2].rejection-reason
```

Then check three things:

- **Coverage** — every material sentence you are about to write maps to a claim.
- **Consistency** — no `code-observed` claim feeds a rationale field.
- **No blanket labels** — a section whose claims have mixed classes takes the
  *weakest* class, not the strongest.

The frontmatter records one class per section. That is a summary of the ledger, so
the section value must be the weakest class among its claims.

## Rules that catch the common mistakes

**An unacknowledged agent suggestion is not a decision.** If you proposed something
and the developer didn't respond to it, it did not happen. Silence is not assent, and
neither is "ok" to a message that contained four separate proposals.

**Selecting an option does not explain the rejection of the others.** If you offered
A, B, C and they picked A, you may list B and C as presented alternatives. You may
**not** write "B was rejected because it's slower" unless they said so. Leave the
rejection reason empty — an empty field is honest; an invented one is the failure
this tool exists to prevent.

**Discussion without resolution is an open question.** "We should probably revisit
caching" produces no record.

**Implementation is not intent.** The diff shows a 30-second timeout. That is
`code-observed`. Why 30 and not 5 is unknown until someone says.

**Your own summary is not a source.** If you said "so we're going with X because of
Y" and the developer said "yep" — that is `developer-confirmed` for both X and Y,
because they confirmed the specific claim. If they said nothing, you have nothing.

## Missing context

Long sessions lose their beginning. When alternatives or attribution are not visible:

- Say so plainly in Context and in More Information.
- Do **not** claim you can detect compaction or reconstruct what was lost.
- Record what is supported; drop what is not.

An ADR that says "the alternatives discussed earlier in the session are not visible
in the current context" is a good ADR. One that guesses at them is a liability.

## Fail-closed, concretely

When a material claim is unsupported after S4, in order of preference:

1. **Omit** the claim; keep the record if what remains is still a coherent decision.
2. **Cancel** the record if what remains is not coherent — report
   `cancelled — insufficient evidence`.
3. Never soften an inference into vague prose to get it past the check. "Likely
   chosen for performance reasons" is a confabulation with a hedge in front of it.

Reaching S6 with an unsupported claim is a bug in your process, not something for the
developer to catch during approval.
