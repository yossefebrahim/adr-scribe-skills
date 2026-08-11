# Record format contract

Load at S6. You supply **structure**; `prepare-record` renders the Markdown. That is
deliberate — it makes the H1 and Y-statement mirrors impossible to get wrong, and it
guarantees the previewed bytes are the written bytes.

Do not hand-write ADR Markdown. Do not edit a record after it is written.

## Frontmatter (adr-scribe/v1)

Generated for you. Fields you influence via the record JSON:

| Field | Source | Notes |
|---|---|---|
| `status` | fixed | always `proposed` in v1 |
| `date` | today | MADR semantics: last update |
| `decision-date` | `decision-date` | when the decision was made |
| `id` | generated | `ADR-<ULID>`, minted locally, no coordination |
| `title` | `title` | short, decision-first |
| `summary` | `summary` | the Y-statement; mirrored into the body |
| `applies-to` | `applies-to` | repo-relative globs, **metadata only in v1** |
| `supersedes` | fixed | `[]` — supersession is v1.1 |
| `content-digest` | computed | covers body + immutable frontmatter |
| `acceptance` | fixed | `null` — acceptance is a separate v1.1 flow |
| `provenance` | `provenance` | one class per section, weakest wins |
| `evidence` | `evidence` | commits and/or working-tree paths |
| `record-confirmation` | `confirmed-by` | who approves this exact patch |

`content-digest` excludes `status`, `date`, `acceptance`, and itself, so a later
acceptance-only change can prove the decision content did not change.

## The `applies-to` glob dialect

`/` separators. `*` matches within one segment. `**` matches zero or more segments,
and must occupy a whole segment. `**/*` means every file in the repo.

Invalid: absolute paths, `..`, `.`, `~`, negation (`!`), backslashes, empty segments.

Nothing resolves these in v1 — they are metadata for future tooling. Claude Code does
**not** auto-load `docs/adr/`, so writing a record does not make agents follow it.

## The Y-statement

```
In the context of <use case>, facing <concern>, we decided for <option>
to achieve <quality>, accepting <downside>.
```

One sentence. It is the index row and the first thing a reader sees. If you cannot
fill `<downside>` from evidence, you probably have not finished S4 — every real
decision costs something.

## Body sections (rendered in this order)

H1 (mirrors id + title) · Y-statement blockquote · Rules (optional) · Context and
Problem Statement · Decision Drivers · Considered Options · Decision Outcome ·
Consequences · Confirmation · Pros and Cons of the Options · More Information.

**Rules** are optional and only for rules the confirmed decision actually supports.
Write them as `MUST:`, `MUST NOT:`, or `SHOULD:` and keep them checkable.

**Confirmation** may be entirely manual — that is a first-class answer. If you supply
a command it must be read-only, repo-local, and network-free. `prepare-record`
rejects anything else, and **v1 never executes them**.

Allowed command heads: `rg grep ls cat head tail find wc diff test python python3
pytest make git node npm go cargo`, with git limited to `log diff status show
rev-parse ls-files grep blame`. No pipes, redirects, `;`, `&&`, `$( )`, or backticks.

**More Information** is for links and evidence limitations. Never paste transcripts.

## Length

Target ≤ 800 words; a warning fires above 1,200. If a record is long, it is usually
several decisions — split it.

## What the validator enforces

Schema · digest matches the bytes · H1 mirrors id+title · Y-statement mirrors
`summary` · no `[UNCONFIRMED]`/`TODO`/`FIXME`/`XXX` · no unfilled `<placeholders>` ·
glob syntax · Confirmation-command safety · LF endings, no trailing whitespace, one
final newline · each record appears exactly once in the index.

These run **before and after** every write. They catch unfinished drafts. They cannot
catch a fluent invention — that is what provenance discipline is for.
