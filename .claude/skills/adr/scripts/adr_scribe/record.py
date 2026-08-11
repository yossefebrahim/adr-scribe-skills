"""Assemble a complete ADR document from a structured record.

The agent supplies *structure*, not Markdown. This module renders the body, so
the H1 and Y-statement mirrors, section order, and MADR hierarchy cannot drift
from the frontmatter -- the validator's mirror checks then become tautologies
rather than things a model must remember to get right.

It also computes ``content-digest`` **here**, at preview-build time, so the
bytes shown for approval are byte-identical to the bytes later written. If the
digest were injected during apply, the approved preview and the written file
would differ, which would void the entire approval contract (plan E2).

Stdlib only, Python 3.9 floor.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import _frontmatter as fm
from . import digest as _digest
from .ids import adr_filename, new_ulid, slugify
from .validate import PROVENANCE_CLASSES, PROVENANCE_FIELDS

SCHEMA = "adr-scribe/v1"


class RecordError(ValueError):
    """Raised when the structured record is incomplete or inconsistent."""


def _require(record: Mapping[str, Any], key: str, kind: type) -> Any:
    if key not in record:
        raise RecordError("record is missing required field %r" % key)
    value = record[key]
    if not isinstance(value, kind):
        raise RecordError("record field %r must be %s" % (key, kind.__name__))
    return value


def _require_str_list(record: Mapping[str, Any], key: str,
                      allow_empty: bool = True) -> List[str]:
    value = _require(record, key, list)
    for item in value:
        if not isinstance(item, str):
            raise RecordError("record field %r must contain only strings" % key)
    if not allow_empty and not value:
        raise RecordError("record field %r must not be empty" % key)
    return list(value)


def _clean(text: str, field: str) -> str:
    """Reject content that would break the canonical byte contract."""
    if "\r" in text:
        raise RecordError("%s must not contain a carriage return" % field)
    if text != text.strip():
        text = text.strip()
    if not text:
        raise RecordError("%s must not be empty" % field)
    return text


# --------------------------------------------------------------------------
# body rendering
# --------------------------------------------------------------------------

def render_body(record: Mapping[str, Any], record_id: str) -> str:
    """Render the MADR 4.0 body. Section order is fixed by the template."""
    title = _clean(_require(record, "title", str), "title")
    summary = _clean(_require(record, "summary", str), "summary")

    out: List[str] = []
    out.append("# %s — %s" % (record_id, title))
    out.append("")
    out.append("<!-- adr-scribe extension: Y-statement summary -->")
    out.append("> %s" % summary)
    out.append("")

    rules = [r for r in record.get("rules", []) if isinstance(r, str) and r.strip()]
    if rules:
        out.append("## Rules")
        out.append("<!-- Only rules supported by the confirmed decision. -->")
        for rule in rules:
            out.append("- %s" % _clean(rule, "rule"))
        out.append("")

    out.append("## Context and Problem Statement")
    out.append("")
    out.append(_clean(_require(record, "context", str), "context"))
    out.append("")

    drivers = _require_str_list(record, "drivers")
    out.append("## Decision Drivers")
    out.append("")
    if drivers:
        for driver in drivers:
            out.append("- %s" % _clean(driver, "driver"))
    else:
        out.append("- None recorded beyond the context above.")
    out.append("")

    options = _require(record, "considered-options", list)
    if not options:
        raise RecordError("considered-options must not be empty")
    chosen = [o for o in options if isinstance(o, Mapping) and o.get("chosen")]
    if len(chosen) != 1:
        raise RecordError("exactly one considered option must be marked chosen")
    chosen_name = _clean(str(chosen[0].get("name", "")), "chosen option name")

    out.append("## Considered Options")
    out.append("")
    for i, option in enumerate(options, 1):
        if not isinstance(option, Mapping):
            raise RecordError("each considered option must be a mapping")
        name = _clean(str(option.get("name", "")), "option name")
        out.append("%d. %s" % (i, name))
    out.append("")

    out.append("## Decision Outcome")
    out.append("")
    outcome = _clean(_require(record, "decision-outcome", str), "decision-outcome")
    out.append("Chosen option: **%s**, because %s" % (chosen_name, outcome))
    out.append("")

    consequences = _require(record, "consequences", dict)
    good = [c for c in consequences.get("good", []) if isinstance(c, str)]
    bad = [c for c in consequences.get("bad", []) if isinstance(c, str)]
    out.append("### Consequences")
    out.append("")
    for item in good:
        out.append("- Good, because %s" % _clean(item, "consequence"))
    for item in bad:
        out.append("- Bad, because %s" % _clean(item, "consequence"))
    if not good and not bad:
        out.append("- No consequences were stated or confirmed.")
    out.append("")

    confirmation = record.get("confirmation") or {}
    manual = [m for m in confirmation.get("manual", []) if isinstance(m, str)]
    commands = [c for c in confirmation.get("commands", []) if isinstance(c, str)]
    out.append("### Confirmation")
    out.append("")
    if manual:
        for step in manual:
            out.append("- Manual: %s" % _clean(step, "confirmation step"))
    else:
        out.append("- Manual: review the implementation against this record.")
    for command in commands:
        out.append("- Optional read-only check: `%s`" % _clean(command, "confirmation command"))
    out.append("")

    out.append("## Pros and Cons of the Options")
    out.append("")
    for option in options:
        name = _clean(str(option.get("name", "")), "option name")
        out.append("### %s" % name)
        out.append("")
        pros = [p for p in option.get("pros", []) if isinstance(p, str)]
        cons = [c for c in option.get("cons", []) if isinstance(c, str)]
        for pro in pros:
            out.append("- Good, because %s" % _clean(pro, "pro"))
        for con in cons:
            out.append("- Bad, because %s" % _clean(con, "con"))
        reason = option.get("rejection-reason")
        if not option.get("chosen") and isinstance(reason, str) and reason.strip():
            out.append("- Rejected, because %s" % _clean(reason, "rejection reason"))
        if not pros and not cons and not (isinstance(reason, str) and reason.strip()):
            out.append("- No arguments were stated or confirmed for this option.")
        out.append("")

    out.append("## More Information")
    out.append("")
    more = record.get("more-information")
    if isinstance(more, str) and more.strip():
        out.append(_clean(more, "more-information"))
    else:
        out.append("No further links or evidence limitations were recorded.")
    out.append("")

    text = "\n".join(out)
    while text.endswith("\n\n"):
        text = text[:-1]
    if not text.endswith("\n"):
        text += "\n"
    return text


# --------------------------------------------------------------------------
# frontmatter assembly
# --------------------------------------------------------------------------

def build_frontmatter(record: Mapping[str, Any], record_id: str,
                      today: str) -> Dict[str, Any]:
    provenance = _require(record, "provenance", dict)
    for field in PROVENANCE_FIELDS:
        value = provenance.get(field)
        if value not in PROVENANCE_CLASSES:
            raise RecordError(
                "provenance.%s must be one of %s (a claim that cannot be "
                "attributed must be dropped, not written)" % (field, PROVENANCE_CLASSES)
            )

    evidence = _require(record, "evidence", dict)
    commits = [c for c in evidence.get("commits", []) if isinstance(c, str)]
    files = [f for f in evidence.get("working-tree-files", []) if isinstance(f, str)]

    decision_date = record.get("decision-date") or today
    if not isinstance(decision_date, str):
        raise RecordError("decision-date must be a string")

    return {
        "status": "proposed",
        "date": today,
        "decision-makers": _require_str_list(record, "decision-makers"),
        "consulted": [c for c in record.get("consulted", []) if isinstance(c, str)],
        "informed": [i for i in record.get("informed", []) if isinstance(i, str)],
        "schema": SCHEMA,
        "id": record_id,
        "title": _clean(_require(record, "title", str), "title"),
        "summary": _clean(_require(record, "summary", str), "summary"),
        "decision-date": decision_date,
        "applies-to": _require_str_list(record, "applies-to", allow_empty=False),
        "supersedes": [],
        "roadmap-ref": record.get("roadmap-ref"),
        "content-digest": "sha256:" + "0" * 64,  # placeholder, replaced below
        "acceptance": None,
        "provenance": {f: provenance[f] for f in PROVENANCE_FIELDS},
        "evidence": {"commits": commits, "working-tree-files": files},
        "record-confirmation": {
            "confirmed-by": _require_str_list(record, "confirmed-by", allow_empty=False),
        },
    }


class BuiltRecord(object):
    """A rendered ADR: its id, filename, final bytes, and row for the index."""

    __slots__ = ("ulid", "record_id", "filename", "content", "frontmatter")

    def __init__(self, ulid, record_id, filename, content, frontmatter):
        self.ulid = ulid
        self.record_id = record_id
        self.filename = filename
        self.content = content
        self.frontmatter = frontmatter

    def index_row(self) -> Dict[str, str]:
        return {k: self.frontmatter[k]
                for k in ("id", "title", "status", "date", "summary")}


def build(record: Mapping[str, Any], today: str,
          ulid: Optional[str] = None) -> BuiltRecord:
    """Render a complete ADR document, digest included.

    ``ulid`` may be supplied for deterministic tests; otherwise one is minted.
    """
    if not isinstance(record, Mapping):
        raise RecordError("record must be a mapping")
    ulid = ulid or new_ulid()
    record_id = "ADR-" + ulid

    body_text = render_body(record, record_id)
    body = body_text.encode("utf-8")

    front = build_frontmatter(record, record_id, today)
    front["content-digest"] = _digest.content_digest(front, body)

    content = ("---\n" + fm.emit(front) + "---\n").encode("utf-8") + body
    filename = adr_filename(ulid, slugify(front["title"]))
    return BuiltRecord(ulid, record_id, filename, content, front)
