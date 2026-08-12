"""Deterministic renderer for the generated ADR index block.

The index is *generated output*. Everything between the start and end markers is
owned by this module and reproduced from ADR frontmatter; everything outside the
markers belongs to whoever wrote it and is preserved byte for byte.

Two properties are load-bearing:

* **Determinism.** The same records always render the same bytes, in any order
  they are supplied. The index is part of an approved patch, so a renderer that
  reorders rows between preview and apply would invalidate the approval.
* **Escape ordering.** Backslashes are escaped *before* pipes. Doing it the other
  way doubles the backslash that pipe-escaping just introduced, which leaves the
  table delimiter live and breaks the row. See ``escape_cell``.

Stdlib only, Python 3.9 floor.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Mapping, Optional, Sequence

START_MARKER = "<!-- adr-scribe:index:start -->"
END_MARKER = "<!-- adr-scribe:index:end -->"

COLUMNS = ("#", "ID", "Title", "Status", "Last updated", "Summary")

#: Row keys, in column order. ``number`` is derived from the filename by the
#: caller (it is display identity, not frontmatter); the rest are frontmatter.
_ROW_FIELDS = ("number", "id", "title", "status", "date", "summary")

_ULID_RE = re.compile(r"^ADR-([0-7][0-9A-HJKMNP-TV-Z]{25})$")
_NUMBER_RE = re.compile(r"^\d{3,}$")
_WHITESPACE_RUN = re.compile(r" {2,}")


class IndexRenderError(ValueError):
    """Raised when the index cannot be rendered or spliced deterministically."""


def escape_cell(value: str) -> str:
    """Make ``value`` safe to place inside a Markdown table cell.

    Order matters and is part of the specification:

    1. ``\\`` -> ``\\\\``
    2. ``|``  -> ``\\|``
    3. CR/LF  -> a single space
    4. runs of spaces collapse to one, then strip

    Escaping pipes first would double the backslash introduced in step 2,
    producing ``\\\\|`` -- a literal backslash followed by a *live* delimiter.
    """
    if not isinstance(value, str):
        raise IndexRenderError("cell values must be str, got %r" % type(value).__name__)
    out = value.replace("\\", "\\\\")
    out = out.replace("|", "\\|")
    out = out.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    out = _WHITESPACE_RUN.sub(" ", out)
    return out.strip()


def _ulid_of(record: Mapping[str, object]) -> str:
    raw = record.get("id")
    if not isinstance(raw, str):
        raise IndexRenderError("record is missing a string 'id'")
    match = _ULID_RE.match(raw)
    if match is None:
        raise IndexRenderError("record id is not a valid ADR-<ULID>: %r" % raw)
    return match.group(1)


def _sort_key(record: Mapping[str, object]):
    """Sort by sequence number, then ULID.

    The ULID tiebreak keeps the render deterministic even when a branch merge
    has produced duplicate numbers -- the renderer must still show that state
    so the developer can see it; refusing it is the validator's job.
    """
    raw_number = record.get("number")
    if not isinstance(raw_number, str) or not _NUMBER_RE.fullmatch(raw_number):
        raise IndexRenderError(
            "record %r has no zero-padded 'number' string" % record.get("id"))
    return (int(raw_number), _ulid_of(record))


def _row(record: Mapping[str, object]) -> str:
    cells = []
    for field in _ROW_FIELDS:
        value = record.get(field)
        if value is None:
            raise IndexRenderError("record %r is missing required field %r" % (record.get("id"), field))
        cells.append(escape_cell(value if isinstance(value, str) else str(value)))
    return "| " + " | ".join(cells) + " |"


def render_table(records: Sequence[Mapping[str, object]]) -> str:
    """Render the Markdown table body. Deterministic for any input order.

    Duplicate *ids* are an error -- two rows claiming the same record can never
    render meaningfully. Duplicate *numbers* (a branch-merge artifact) render
    in deterministic order instead, so the developer can see the collision;
    ``validate-adr`` reports it as the error.
    """
    seen = set()
    ordered = sorted(records, key=_sort_key)
    for record in ordered:
        ulid = _ulid_of(record)
        if ulid in seen:
            raise IndexRenderError("duplicate ADR id in index input: ADR-%s" % ulid)
        seen.add(ulid)

    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "| " + " | ".join("---" for _ in COLUMNS) + " |",
    ]
    lines.extend(_row(record) for record in ordered)
    return "\n".join(lines)


def render_block(records: Sequence[Mapping[str, object]]) -> str:
    """Render the full generated block, markers included."""
    return "\n".join((START_MARKER, "", render_table(records), "", END_MARKER))


def splice(existing: str, block: str) -> str:
    """Replace the generated block in ``existing``, preserving everything else.

    Content before the start marker and after the end marker is preserved byte
    for byte -- that is the whole contract of a generated block living inside a
    hand-written file.
    """
    if existing.count(START_MARKER) != 1 or existing.count(END_MARKER) != 1:
        raise IndexRenderError(
            "index must contain exactly one %s and one %s" % (START_MARKER, END_MARKER)
        )
    start = existing.index(START_MARKER)
    end = existing.index(END_MARKER)
    if end < start:
        raise IndexRenderError("index end marker appears before the start marker")
    return existing[:start] + block + existing[end + len(END_MARKER):]


def render_index(existing: Optional[str], records: Sequence[Mapping[str, object]]) -> str:
    """Return the full index file content.

    ``existing`` is ``None`` on first-run bootstrap, in which case the scaffold
    below is used. Otherwise the generated block is spliced into the existing
    file and all surrounding content is preserved.
    """
    block = render_block(records)
    if existing is None:
        return _SCAFFOLD % block
    return splice(existing, block)


_SCAFFOLD = """# Architecture Decision Records

Records in this directory are generated by the `adr` skill. The table below is
generated output -- edit the ADR files, not the table.

%s
"""
