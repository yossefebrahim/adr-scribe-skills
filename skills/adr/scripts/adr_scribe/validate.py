"""Schema and safety validation for a written ADR.

This is the machine backstop described in the plan (E3). It runs inside
``apply-record`` *before* and *after* every write, and in CI over the whole
`docs/adr/` tree. Its job is to make a class of model mistakes impossible to
land -- not to prove the record is true.

What it can enforce:
  * the record parses, and its frontmatter matches the v1 schema exactly
  * ``content-digest`` actually matches the bytes it covers
  * the body H1 and Y-statement mirror the canonical ``title`` and ``summary``
  * no unfinished-draft markers reached disk, and no forbidden provenance class
  * any Confirmation command is non-destructive, repo-local and network-free
  * the ``applies-to`` glob dialect is syntactically valid
  * length targets (<= 800 words; warn above 1,200)

What it cannot enforce: whether a rationale is *true*. A fluent, confident,
entirely invented reason passes every check here. That is why provenance is a
workflow property backed by the claim ledger, and why this module is described
as lint rather than protection against confabulation.

Stdlib only, Python 3.9 floor.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import digest as _digest
from . import _frontmatter as _fm
from .ids import is_valid_ulid

SCHEMA_VERSION = "adr-scribe/v1"

#: Only these three may be persisted. `[UNCONFIRMED]` is an internal state that
#: R3 forbids on disk, so it is deliberately absent from the enum.
PROVENANCE_CLASSES = ("developer-stated", "developer-confirmed", "code-observed")

PROVENANCE_FIELDS = (
    "context", "decision", "drivers", "alternatives", "consequences", "rules",
)

V1_STATUSES = ("proposed",)

REQUIRED_KEYS = (
    "status", "date", "decision-makers", "consulted", "informed",
    "schema", "id", "title", "summary", "decision-date", "applies-to",
    "supersedes", "roadmap-ref", "content-digest", "acceptance",
    "provenance", "evidence", "record-confirmation",
)

WORD_TARGET = 800
WORD_LIMIT = 1200

_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^ADR-([0-7][0-9A-HJKMNP-TV-Z]{25})$")

#: Unfinished-draft markers. Cheap to check, and they catch truncated drafts --
#: which is a real failure mode, just not the dangerous one.
FORBIDDEN_MARKERS = ("[UNCONFIRMED]", "TODO", "FIXME", "XXX")

#: A placeholder is flagged only when the angle-bracketed text contains a space,
#: e.g. `<short, decision-first title>`. This deliberately misses single-word
#: placeholders such as `<option>`, which are indistinguishable from HTML tags.
_PLACEHOLDER_RE = re.compile(r"<[a-z][^>\n]*\s[^>\n]*>")

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)

#: First token of a Confirmation command must be one of these.
_SAFE_COMMANDS = frozenset({
    "rg", "grep", "ls", "cat", "head", "tail", "find", "wc", "diff", "test",
    "python", "python3", "pytest", "make", "git", "node", "npm", "go", "cargo",
})
#: git subcommands that only read.
_SAFE_GIT = frozenset({
    "log", "diff", "status", "show", "rev-parse", "ls-files", "grep", "blame",
})
#: Shell constructs that make a command non-trivially unsafe to even suggest.
_SHELL_METACHARS = ("|", ">", "<", ";", "&", "$(", "`", "\n", "&&", "||")
_NETWORK_OR_DESTRUCTIVE = (
    "rm ", "rmdir", "mv ", "chmod", "chown", "sudo", "curl", "wget", "nc ",
    "ssh", "scp", "dd ", "mkfs", "kill", "eval", "exec", "pip install",
    "npm install", "git push", "git fetch", "git pull", "git clone",
)


class Finding(object):
    """One validation result. ``level`` is ``error`` or ``warning``."""

    __slots__ = ("level", "code", "message")

    def __init__(self, level: str, code: str, message: str) -> None:
        self.level = level
        self.code = code
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Finding(%r, %r, %r)" % (self.level, self.code, self.message)

    def as_dict(self) -> Dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message}


def _err(out: List[Finding], code: str, message: str) -> None:
    out.append(Finding("error", code, message))


def _warn(out: List[Finding], code: str, message: str) -> None:
    out.append(Finding("warning", code, message))


# --------------------------------------------------------------------------
# glob dialect
# --------------------------------------------------------------------------

def validate_glob(pattern: str) -> Optional[str]:
    """Return an error message if ``pattern`` is not a valid applies-to glob.

    Dialect: ``/`` separators; ``*`` matches within one segment; ``**`` matches
    zero or more segments. Absolute paths, ``..``, ``~``, negation and
    backslashes are invalid. Metadata only in v1 -- nothing resolves it.
    """
    if not isinstance(pattern, str):
        return "glob must be a string"
    if pattern == "":
        return "glob must not be empty"
    if pattern.startswith("/"):
        return "glob must be repo-relative, not absolute"
    if pattern.startswith("~"):
        return "glob must not start with '~'"
    if pattern.startswith("!"):
        return "negation is not supported"
    if "\\" in pattern:
        return "glob must use '/' separators, not backslashes"
    segments = pattern.split("/")
    for seg in segments:
        if seg == "":
            return "glob must not contain an empty segment"
        if seg == "..":
            return "glob must not contain a '..' segment"
        if seg == ".":
            return "glob must not contain a '.' segment"
        if "**" in seg and seg != "**":
            return "'**' must occupy a whole segment"
    return None


# --------------------------------------------------------------------------
# body helpers
# --------------------------------------------------------------------------

def _strip_code_and_comments(body_text: str) -> str:
    """Remove fenced code blocks and HTML comments before prose checks."""
    without_comments = _COMMENT_RE.sub(" ", body_text)
    out, in_fence = [], False
    for line in without_comments.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def count_words(body_text: str) -> int:
    prose = _strip_code_and_comments(body_text)
    prose = re.sub(r"^\s{0,3}#{1,6}\s+", " ", prose, flags=re.M)
    return len([w for w in re.split(r"\s+", prose) if w])


def extract_confirmation_commands(body_text: str) -> List[str]:
    """Return inline-code spans found under a `### Confirmation` heading."""
    lines = body_text.split("\n")
    commands: List[str] = []
    in_section = False
    for line in lines:
        heading = re.match(r"^(#{2,6})\s+(.*)$", line)
        if heading:
            in_section = heading.group(2).strip().lower() == "confirmation"
            continue
        if in_section:
            commands.extend(re.findall(r"`([^`\n]+)`", line))
    return [c.strip() for c in commands if c.strip()]


def check_command_safety(command: str) -> Optional[str]:
    """Return an error message if the command is not safe to *suggest*.

    v1 never executes these. The check exists so a record cannot ship a
    destructive or network-touching command that a human might paste.
    """
    lowered = command.lower()
    for bad in _NETWORK_OR_DESTRUCTIVE:
        if bad in lowered:
            return "command contains a destructive or network operation: %r" % bad.strip()
    for meta in _SHELL_METACHARS:
        if meta in command:
            return "command contains the shell metacharacter %r" % meta
    tokens = command.split()
    if not tokens:
        return "empty command"
    head = tokens[0]
    if head not in _SAFE_COMMANDS:
        return "command %r is not in the read-only allow-list" % head
    if head == "git":
        if len(tokens) < 2 or tokens[1] not in _SAFE_GIT:
            return "only read-only git subcommands are allowed"
    return None


# --------------------------------------------------------------------------
# frontmatter schema
# --------------------------------------------------------------------------

def _check_str_list(out: List[Finding], value: Any, field: str, allow_empty: bool = True) -> None:
    if not isinstance(value, list):
        _err(out, "type", "%s must be a list" % field)
        return
    if not allow_empty and not value:
        _err(out, "empty", "%s must not be empty" % field)
    for item in value:
        if not isinstance(item, str):
            _err(out, "type", "%s items must be strings" % field)
            return


def _walk_strings(value: Any, path: str = "") -> List[Tuple[str, str]]:
    """Yield every (dotted-path, string) pair inside a frontmatter value."""
    found: List[Tuple[str, str]] = []
    if isinstance(value, str):
        found.append((path, value))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            found.extend(_walk_strings(item, "%s.%s" % (path, key) if path else str(key)))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            found.extend(_walk_strings(item, "%s[%d]" % (path, i)))
    return found


def check_frontmatter_markers(fm: Mapping[str, Any]) -> List[Finding]:
    """Reject unfinished-draft text in frontmatter, not just in the body.

    The body check alone leaves a hole: `decision-makers`, `confirmed-by`,
    `title` and friends are never rendered into the body, so a record naming
    "TODO" as its decision-maker, or carrying an unfilled `<decision-maker>`
    placeholder, would land looking complete.
    """
    out: List[Finding] = []
    for path, text in _walk_strings(fm):
        if path == "content-digest":
            continue
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                _err(out, "marker",
                     "frontmatter %s contains the unfinished-draft marker %r"
                     % (path, marker))
        placeholder = _PLACEHOLDER_RE.search(text)
        if placeholder:
            _err(out, "placeholder",
                 "frontmatter %s contains an unfilled placeholder: %r"
                 % (path, placeholder.group(0)))
        elif text.startswith("<") and text.endswith(">") and len(text) > 2:
            # Single-word placeholders such as `<decision-maker>` carry no
            # space, so the prose regex misses them. In a frontmatter value --
            # a name, a title, an approver -- a whole string wrapped in angle
            # brackets is never legitimate content.
            _err(out, "placeholder",
                 "frontmatter %s is an unfilled placeholder: %r" % (path, text))
    return out


def validate_frontmatter(fm: Mapping[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    out.extend(check_frontmatter_markers(fm))

    missing = [k for k in REQUIRED_KEYS if k not in fm]
    if missing:
        _err(out, "missing-key", "missing required key(s): %s" % ", ".join(missing))
    unknown = [k for k in fm if k not in REQUIRED_KEYS]
    if unknown:
        _err(out, "unknown-key", "unknown key(s): %s" % ", ".join(sorted(unknown)))

    if fm.get("schema") != SCHEMA_VERSION:
        _err(out, "schema", "schema must be %r" % SCHEMA_VERSION)

    status = fm.get("status")
    if status not in V1_STATUSES:
        _err(out, "status", "v1 may only write status %s, got %r" % (V1_STATUSES, status))

    rid = fm.get("id")
    if not isinstance(rid, str) or not _ID_RE.match(rid):
        _err(out, "id", "id must be ADR-<ULID>, got %r" % (rid,))
    elif not is_valid_ulid(rid[4:]):
        _err(out, "id", "id contains an invalid ULID")

    for field in ("date", "decision-date"):
        value = fm.get(field)
        if not isinstance(value, str) or not _DATE_RE.match(value):
            _err(out, "date", "%s must be YYYY-MM-DD, got %r" % (field, value))

    for field in ("title", "summary"):
        value = fm.get(field)
        if not isinstance(value, str) or not value.strip():
            _err(out, "type", "%s must be a non-empty string" % field)

    _check_str_list(out, fm.get("decision-makers"), "decision-makers")
    _check_str_list(out, fm.get("consulted"), "consulted")
    _check_str_list(out, fm.get("informed"), "informed")

    applies = fm.get("applies-to")
    _check_str_list(out, applies, "applies-to", allow_empty=False)
    if isinstance(applies, list):
        for pattern in applies:
            if isinstance(pattern, str):
                problem = validate_glob(pattern)
                if problem:
                    _err(out, "glob", "applies-to %r: %s" % (pattern, problem))

    if fm.get("supersedes") != []:
        _err(out, "supersedes", "supersedes must be empty in v1 (supersession is v1.1)")
    if fm.get("acceptance") is not None:
        _err(out, "acceptance", "acceptance must be null in v1")

    roadmap = fm.get("roadmap-ref")
    if roadmap is not None and not isinstance(roadmap, str):
        _err(out, "type", "roadmap-ref must be a string or null")

    cdigest = fm.get("content-digest")
    if not isinstance(cdigest, str) or not _DIGEST_RE.match(cdigest):
        _err(out, "digest", "content-digest must be sha256:<64 lowercase hex>")

    prov = fm.get("provenance")
    if not isinstance(prov, Mapping):
        _err(out, "type", "provenance must be a mapping")
    else:
        for field in PROVENANCE_FIELDS:
            if field not in prov:
                _err(out, "provenance", "provenance.%s is missing" % field)
                continue
            value = prov[field]
            if value not in PROVENANCE_CLASSES:
                _err(
                    out, "provenance",
                    "provenance.%s must be one of %s, got %r"
                    % (field, PROVENANCE_CLASSES, value),
                )
        for extra in prov:
            if extra not in PROVENANCE_FIELDS:
                _err(out, "provenance", "unknown provenance field %r" % extra)

    evidence = fm.get("evidence")
    if not isinstance(evidence, Mapping):
        _err(out, "type", "evidence must be a mapping")
    else:
        _check_str_list(out, evidence.get("commits"), "evidence.commits")
        _check_str_list(out, evidence.get("working-tree-files"), "evidence.working-tree-files")

    rc = fm.get("record-confirmation")
    if not isinstance(rc, Mapping):
        _err(out, "type", "record-confirmation must be a mapping")
    else:
        _check_str_list(out, rc.get("confirmed-by"), "record-confirmation.confirmed-by",
                        allow_empty=False)

    return out


# --------------------------------------------------------------------------
# body
# --------------------------------------------------------------------------

def validate_body(body: bytes, fm: Mapping[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        _err(out, "encoding", "body is not valid UTF-8 (%s)" % exc.reason)
        return out

    if "\r" in text:
        _err(out, "whitespace", "body must use LF line endings, found CR")
    for i, line in enumerate(text.split("\n"), 1):
        if line != line.rstrip(" \t"):
            _err(out, "whitespace", "line %d has trailing whitespace" % i)
            break
    if text and not text.endswith("\n"):
        _err(out, "whitespace", "body must end with exactly one newline")
    elif text.endswith("\n\n"):
        _err(out, "whitespace", "body must end with exactly one newline")

    for marker in FORBIDDEN_MARKERS:
        if marker in text:
            _err(out, "marker", "body contains the unfinished-draft marker %r" % marker)

    prose = _strip_code_and_comments(text)
    placeholder = _PLACEHOLDER_RE.search(prose)
    if placeholder:
        _err(out, "placeholder",
             "body contains an unfilled template placeholder: %r" % placeholder.group(0))

    rid, title = fm.get("id"), fm.get("title")
    if isinstance(rid, str) and isinstance(title, str):
        expected_h1 = "# %s — %s" % (rid, title)
        first_heading = None
        for line in text.split("\n"):
            if line.startswith("# "):
                first_heading = line.rstrip()
                break
        if first_heading is None:
            _err(out, "h1", "body has no H1")
        elif first_heading != expected_h1:
            _err(out, "h1", "H1 must mirror id and title exactly; expected %r, got %r"
                 % (expected_h1, first_heading))

    summary = fm.get("summary")
    if isinstance(summary, str):
        expected_q = "> %s" % summary
        if expected_q not in text:
            _err(out, "summary-mirror",
                 "body must contain the Y-statement blockquote %r" % expected_q)

    for command in extract_confirmation_commands(text):
        problem = check_command_safety(command)
        if problem:
            _err(out, "confirmation-command", "unsafe Confirmation command %r: %s"
                 % (command, problem))

    words = count_words(text)
    if words > WORD_LIMIT:
        _warn(out, "length", "body is %d words, above the %d-word limit" % (words, WORD_LIMIT))
    elif words > WORD_TARGET:
        _warn(out, "length", "body is %d words, above the %d-word target" % (words, WORD_TARGET))

    return out


# --------------------------------------------------------------------------
# document
# --------------------------------------------------------------------------

def validate_document(raw: bytes) -> List[Finding]:
    """Validate a complete ADR file. Returns findings; empty means valid."""
    out: List[Finding] = []
    try:
        fm_text, body = _fm.split_document(raw)
    except _fm.FrontmatterError as exc:
        _err(out, "frontmatter", str(exc))
        return out
    try:
        fm = _fm.parse(fm_text)
    except _fm.FrontmatterError as exc:
        _err(out, "frontmatter", str(exc))
        return out

    out.extend(validate_frontmatter(fm))
    out.extend(validate_body(body, fm))

    declared = fm.get("content-digest")
    if isinstance(declared, str) and _DIGEST_RE.match(declared):
        try:
            actual = _digest.content_digest(fm, body)
        except _digest.DigestError as exc:
            _err(out, "digest", "content-digest could not be computed: %s" % exc)
        else:
            if actual != declared:
                _err(out, "digest",
                     "content-digest does not match the record: declared %s, actual %s"
                     % (declared, actual))
    return out


def errors(findings: Sequence[Finding]) -> List[Finding]:
    return [f for f in findings if f.level == "error"]


def summarize(findings: Sequence[Finding]) -> Tuple[int, int]:
    """Return ``(error_count, warning_count)``."""
    e = sum(1 for f in findings if f.level == "error")
    w = sum(1 for f in findings if f.level == "warning")
    return e, w
