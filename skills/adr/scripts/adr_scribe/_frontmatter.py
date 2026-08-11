"""Canonical-only frontmatter parser/emitter (adr_scribe Module 3).

Accepts exactly what ``emit`` produces. YAML that a general-purpose parser
would happily load but that ``emit`` would never produce is an error, not
input -- see CONTRACT.md for the full rationale and grammar.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Mapping as _ABCMapping
from typing import Any, List, Mapping, Tuple


class FrontmatterError(ValueError):
    """Raised for any malformed, non-canonical, or unsupported frontmatter."""


FIELD_ORDER: Tuple[str, ...] = (
    "status", "date", "decision-makers", "consulted", "informed",
    "schema", "id", "title", "summary", "decision-date", "applies-to",
    "supersedes", "roadmap-ref",
    "content-digest", "acceptance", "provenance", "evidence",
    "record-confirmation",
)

_NESTED_SUBKEYS: Mapping[str, Tuple[str, ...]] = {
    "provenance": ("context", "decision", "drivers", "alternatives", "consequences", "rules"),
    "evidence": ("commits", "working-tree-files"),
    "record-confirmation": ("confirmed-by",),
}

_KEY_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_TOP_LINE_RE = re.compile(r"^([^:]*):(.*)$")
_UESCAPE_RE = re.compile(r"^[0-9a-fA-F]{4}$")
_INT_RE = re.compile(r"^-?(0|[1-9]\d*)$")
_BAD_LEADING_ZERO_RE = re.compile(r"^-?0\d")


def split_document(raw: bytes) -> Tuple[str, bytes]:
    """Split a raw ADR document into (frontmatter_text, body_bytes).

    Raises FrontmatterError on a missing opening or closing ``---`` fence, a
    UTF-8 byte-order mark, a carriage return anywhere in the frontmatter
    region, or bytes that are not valid UTF-8. The body is returned verbatim
    and is never validated or decoded.
    """
    if not isinstance(raw, bytes):
        raise FrontmatterError("split_document() requires bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise FrontmatterError("document begins with a UTF-8 byte-order mark (BOM)")
    if not raw.startswith(b"---\n"):
        raise FrontmatterError("frontmatter is missing the opening '---' fence")
    closing = raw.find(b"\n---\n", 3)
    if closing == -1:
        raise FrontmatterError("frontmatter is missing the closing '---' fence")
    content = raw[4:closing + 1]
    body = raw[closing + 5:]
    cr_index = content.find(b"\r")
    if cr_index != -1:
        lineno = content.count(b"\n", 0, cr_index) + 1
        raise FrontmatterError(f"line {lineno}: carriage return (CR) is not allowed in frontmatter")
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        lineno = content.count(b"\n", 0, exc.start) + 1
        raise FrontmatterError(f"line {lineno}: frontmatter is not valid UTF-8 ({exc.reason})") from exc
    return text, body


def parse(text: str) -> OrderedDict[str, Any]:
    """Parse canonical frontmatter text into an ordered mapping.

    Only the grammar documented in CONTRACT.md is accepted; every other
    construct -- including valid YAML this emitter would never produce --
    raises FrontmatterError naming the offending line number (1-indexed,
    relative to the start of ``text``).
    """
    if not isinstance(text, str):
        raise FrontmatterError("parse() requires str")
    if "﻿" in text:
        pos = text.index("﻿")
        lineno = text.count("\n", 0, pos) + 1
        raise FrontmatterError(f"line {lineno}: byte-order mark (BOM) is not allowed")
    if "\r" in text:
        pos = text.index("\r")
        lineno = text.count("\n", 0, pos) + 1
        raise FrontmatterError(f"line {lineno}: carriage return (CR) is not allowed")
    if "\t" in text:
        pos = text.index("\t")
        lineno = text.count("\n", 0, pos) + 1
        raise FrontmatterError(f"line {lineno}: tab characters are not allowed")

    lines: List[str] = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    n = len(lines)
    seen: set = set()
    result: OrderedDict[str, Any] = OrderedDict()

    def check_no_trailing_ws(line: str, lineno: int) -> None:
        if line.rstrip(" ") != line:
            raise FrontmatterError(f"line {lineno}: trailing whitespace is not allowed")

    def check_not_separator(content: str, lineno: int) -> None:
        if content == "---":
            raise FrontmatterError(
                f"line {lineno}: '---' document separators are not allowed inside the frontmatter block"
            )

    def validate_key(key: str, lineno: int) -> None:
        if key == "":
            raise FrontmatterError(f"line {lineno}: empty key")
        if not _KEY_RE.match(key):
            raise FrontmatterError(f"line {lineno}: invalid key {key!r}")
        if key in seen:
            raise FrontmatterError(f"line {lineno}: duplicate key {key!r}")
        seen.add(key)

    def parse_integer(s: str, lineno: int) -> int:
        if _INT_RE.match(s):
            return int(s)
        if s.startswith("+"):
            raise FrontmatterError(f"line {lineno}: a leading '+' is not allowed on integers")
        if "." in s:
            raise FrontmatterError(f"line {lineno}: floats are not allowed")
        if "_" in s:
            raise FrontmatterError(f"line {lineno}: underscore separators are not allowed in integers")
        if _BAD_LEADING_ZERO_RE.match(s):
            raise FrontmatterError(f"line {lineno}: leading zeros are not allowed on integers")
        raise FrontmatterError(f"line {lineno}: {s!r} is not a recognized value")

    def parse_quoted_string(s: str, lineno: int) -> str:
        out: List[str] = []
        i = 1
        m = len(s)
        closed = False
        while i < m:
            c = s[i]
            if c == '"':
                closed = True
                i += 1
                break
            if c == "\\":
                if i + 1 >= m:
                    raise FrontmatterError(f"line {lineno}: unterminated escape sequence")
                esc = s[i + 1]
                if esc == "\\":
                    out.append("\\")
                    i += 2
                elif esc == '"':
                    out.append('"')
                    i += 2
                elif esc == "n":
                    out.append("\n")
                    i += 2
                elif esc == "t":
                    out.append("\t")
                    i += 2
                elif esc == "u":
                    hexpart = s[i + 2:i + 6]
                    if len(hexpart) != 4 or not _UESCAPE_RE.match(hexpart):
                        raise FrontmatterError(f"line {lineno}: invalid \\u escape")
                    out.append(chr(int(hexpart, 16)))
                    i += 6
                else:
                    raise FrontmatterError(f"line {lineno}: unsupported escape sequence '\\{esc}'")
                continue
            out.append(c)
            i += 1
        if not closed:
            raise FrontmatterError(f"line {lineno}: unterminated string")
        trailing = s[i:]
        if trailing:
            if trailing.lstrip(" ").startswith("#"):
                raise FrontmatterError(f"line {lineno}: comments are not allowed")
            raise FrontmatterError(f"line {lineno}: unexpected characters after string value")
        return "".join(out)

    def parse_scalar(s: str, lineno: int) -> Any:
        if s == "null":
            return None
        if s == "true":
            return True
        if s == "false":
            return False
        if s == "[]":
            return []
        if s.startswith('"'):
            return parse_quoted_string(s, lineno)
        if s[:1].isdigit() or s[:1] in "+-":
            return parse_integer(s, lineno)
        if s.startswith("'"):
            raise FrontmatterError(f"line {lineno}: single-quoted strings are not allowed")
        if s.startswith("{"):
            raise FrontmatterError(f"line {lineno}: flow mappings are not allowed")
        if s.startswith("["):
            raise FrontmatterError(f"line {lineno}: non-empty flow sequences are not allowed")
        if s.startswith("|") or s.startswith(">"):
            raise FrontmatterError(f"line {lineno}: block scalars are not allowed")
        if s.startswith("&"):
            raise FrontmatterError(f"line {lineno}: anchors are not allowed")
        if s.startswith("*"):
            raise FrontmatterError(f"line {lineno}: aliases are not allowed")
        if s.startswith("!"):
            raise FrontmatterError(f"line {lineno}: tags are not allowed")
        if "#" in s:
            raise FrontmatterError(f"line {lineno}: comments are not allowed")
        raise FrontmatterError(f"line {lineno}: unquoted string scalars are not allowed")

    def parse_sequence(start: int) -> Tuple[list, int]:
        items: list = []
        i = start
        while i < n:
            line = lines[i]
            lineno = i + 1
            if line == "":
                break
            check_no_trailing_ws(line, lineno)
            spaces = len(line) - len(line.lstrip(" "))
            if spaces == 0:
                break
            if spaces != 2:
                raise FrontmatterError(f"line {lineno}: sequence items must be indented exactly two spaces")
            content = line[2:]
            check_not_separator(content, lineno)
            if not content.startswith("- "):
                raise FrontmatterError(f"line {lineno}: expected a '- ' sequence item")
            value = parse_scalar(content[2:], lineno)
            if not isinstance(value, str):
                raise FrontmatterError(f"line {lineno}: sequence items must be strings")
            items.append(value)
            i += 1
        return items, i

    def parse_nested_sequence(start: int, key_lineno: int) -> Tuple[list, int]:
        # A bare "subkey:" inside a nested map introduces a block sequence of
        # strings, indented four spaces (two for the subkey + two for the
        # item). Nested maps have no empty block form -- an empty list must
        # use inline "[]" -- so the first line after "subkey:" is required
        # to be a well-formed four-space item.
        if start >= n or lines[start] == "":
            raise FrontmatterError(
                f"line {key_lineno}: 'key:' must be followed by an indented list (or '[]' for an empty one)"
            )
        items: list = []
        i = start
        while i < n:
            line = lines[i]
            lineno = i + 1
            if line == "":
                break
            check_no_trailing_ws(line, lineno)
            spaces = len(line) - len(line.lstrip(" "))
            if i > start and spaces < 4:
                break
            if spaces != 4:
                raise FrontmatterError(f"line {lineno}: nested sequence items must be indented exactly four spaces")
            content = line[4:]
            check_not_separator(content, lineno)
            if not content.startswith("- "):
                raise FrontmatterError(f"line {lineno}: expected a '- ' sequence item")
            value = parse_scalar(content[2:], lineno)
            if not isinstance(value, str):
                raise FrontmatterError(f"line {lineno}: sequence items must be strings")
            items.append(value)
            i += 1
        return items, i

    def parse_nested_map(start: int) -> Tuple[OrderedDict[str, Any], int]:
        mapping: OrderedDict[str, Any] = OrderedDict()
        i = start
        while i < n:
            line = lines[i]
            lineno = i + 1
            if line == "":
                break
            check_no_trailing_ws(line, lineno)
            spaces = len(line) - len(line.lstrip(" "))
            if spaces == 0:
                break
            if spaces != 2:
                raise FrontmatterError(f"line {lineno}: nested mapping entries must be indented exactly two spaces")
            content = line[2:]
            check_not_separator(content, lineno)
            m = _TOP_LINE_RE.match(content)
            if not m:
                raise FrontmatterError(f"line {lineno}: not a recognized 'key: value' production")
            subkey, rest = m.group(1), m.group(2)
            validate_key(subkey, lineno)
            if rest.startswith(" "):
                mapping[subkey] = parse_scalar(rest[1:], lineno)
                i += 1
            elif rest == "":
                mapping[subkey], i = parse_nested_sequence(i + 1, lineno)
            else:
                raise FrontmatterError(f"line {lineno}: expected a single space after ':'")
        return mapping, i

    def parse_block(start: int, key_lineno: int) -> Tuple[Any, int]:
        if start >= n or lines[start] == "":
            raise FrontmatterError(f"line {key_lineno}: 'key:' must be followed by an indented block")
        first = lines[start]
        check_no_trailing_ws(first, start + 1)
        spaces = len(first) - len(first.lstrip(" "))
        if spaces != 2:
            raise FrontmatterError(f"line {start + 1}: block content must be indented exactly two spaces")
        content = first[2:]
        check_not_separator(content, start + 1)
        if content.startswith("-"):
            if not content.startswith("- "):
                raise FrontmatterError(f"line {start + 1}: expected a '- ' sequence item")
            return parse_sequence(start)
        return parse_nested_map(start)

    i = 0
    while i < n:
        line = lines[i]
        lineno = i + 1
        if line == "":
            i += 1
            continue
        check_no_trailing_ws(line, lineno)
        if line.lstrip(" ").startswith("#"):
            raise FrontmatterError(f"line {lineno}: comments are not allowed")
        if line.startswith("%"):
            raise FrontmatterError(f"line {lineno}: directives are not allowed")
        check_not_separator(line, lineno)
        if line.startswith(" "):
            raise FrontmatterError(f"line {lineno}: unexpected indentation")
        m = _TOP_LINE_RE.match(line)
        if not m:
            raise FrontmatterError(f"line {lineno}: not a recognized 'key: value' production")
        key, rest = m.group(1), m.group(2)
        validate_key(key, lineno)
        if rest == "":
            value, i = parse_block(i + 1, lineno)
            result[key] = value
        elif rest.startswith(" "):
            result[key] = parse_scalar(rest[1:], lineno)
            i += 1
        else:
            raise FrontmatterError(f"line {lineno}: expected a single space after ':'")
    return result


def _emit_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _emit_string(value)
    raise FrontmatterError(f"cannot emit value of type {type(value).__name__}")


def _emit_string(s: str) -> str:
    out = ['"']
    for ch in s:
        cp = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif cp < 0x20 or cp == 0x7F:
            out.append("\\u%04x" % cp)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _emit_sequence(key: str, value: list) -> List[str]:
    if len(value) == 0:
        return [f"{key}: []"]
    out_lines = [f"{key}:"]
    for item in value:
        if not isinstance(item, str):
            raise FrontmatterError(f"sequence values for {key!r} must be strings")
        out_lines.append(f"  - {_emit_string(item)}")
    return out_lines


def _emit_nested_map(key: str, value: Any) -> List[str]:
    if not isinstance(value, _ABCMapping):
        raise FrontmatterError(f"{key!r} must be a mapping")
    subkeys = _NESTED_SUBKEYS[key]
    unknown = [k for k in value.keys() if k not in subkeys]
    if unknown:
        raise FrontmatterError(f"unknown key(s) in {key!r}: {', '.join(sorted(map(str, unknown)))}")
    if len(value) == 0:
        raise FrontmatterError(f"{key!r} must not be empty")
    out_lines = [f"{key}:"]
    for sub in subkeys:
        if sub not in value:
            continue
        subvalue = value[sub]
        if isinstance(subvalue, _ABCMapping):
            raise FrontmatterError(f"{key}.{sub} must be a scalar or a list of strings")
        if isinstance(subvalue, list):
            # Mirrors parse_nested_sequence: an empty list is inline "[]", a
            # non-empty one is a block sequence indented four spaces (two for
            # the subkey, two for the item).
            if len(subvalue) == 0:
                out_lines.append(f"  {sub}: []")
                continue
            out_lines.append(f"  {sub}:")
            for item in subvalue:
                if not isinstance(item, str):
                    raise FrontmatterError(
                        f"sequence values for {key}.{sub} must be strings"
                    )
                out_lines.append(f"    - {_emit_string(item)}")
            continue
        out_lines.append(f"  {sub}: {_emit_scalar(subvalue)}")
    return out_lines


def emit(mapping: Mapping[str, Any]) -> str:
    """Emit a mapping as canonical frontmatter text.

    Keys are ordered by FIELD_ORDER regardless of the input mapping's
    insertion order. Raises FrontmatterError if ``mapping`` contains a key
    outside FIELD_ORDER, a nested map with an unrecognized subkey or wrong
    shape, or a value this grammar cannot represent (e.g. a float).
    """
    if not isinstance(mapping, _ABCMapping):
        raise FrontmatterError("emit() requires a mapping")
    unknown = [k for k in mapping.keys() if k not in FIELD_ORDER]
    if unknown:
        raise FrontmatterError(f"unknown key(s) not in FIELD_ORDER: {', '.join(sorted(map(str, unknown)))}")
    out_lines: List[str] = []
    for key in FIELD_ORDER:
        if key not in mapping:
            continue
        value = mapping[key]
        if key in _NESTED_SUBKEYS:
            out_lines.extend(_emit_nested_map(key, value))
        elif isinstance(value, list):
            out_lines.extend(_emit_sequence(key, value))
        else:
            out_lines.append(f"{key}: {_emit_scalar(value)}")
    return "".join(line + "\n" for line in out_lines)
