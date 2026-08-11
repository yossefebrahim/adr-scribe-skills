"""Deterministic digests for ADR content and proposed repository patches."""

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, FrozenSet, Set


class DigestError(ValueError):
    """Raised when a value cannot be encoded by the digest contract."""


IMMUTABLE_EXCLUDED_KEYS: FrozenSet[str] = frozenset(
    {"status", "date", "acceptance", "content-digest"}
)

_HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_PATCH_KEYS = frozenset({"patch-version", "repo-relative-ops", "preconditions"})
_PRECONDITION_KEYS = frozenset({"head", "dirty-overlap"})
_OP_KEYS = {
    "create-file": frozenset({"op", "path", "len", "sha256"}),
    "replace-file": frozenset(
        {"op", "path", "len", "sha256", "expect-sha256"}
    ),
    "create-dir": frozenset({"op", "path"}),
}


def _validate_json_value(value: Any, active: Set[int]) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise DigestError("float values are not allowed in canonical JSON")
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            raise DigestError("cyclic values are not allowed in canonical JSON")
        active.add(identity)
        try:
            for item in value:
                _validate_json_value(item, active)
        finally:
            active.remove(identity)
        return
    if isinstance(value, dict):
        identity = id(value)
        if identity in active:
            raise DigestError("cyclic values are not allowed in canonical JSON")
        active.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise DigestError("canonical JSON object keys must be strings")
                _validate_json_value(item, active)
        finally:
            active.remove(identity)
        return
    raise DigestError(
        "canonical JSON values must be strings, integers, booleans, null, lists, or dicts"
    )


def canonical_json(value: Any) -> bytes:
    """Return the contract's canonical UTF-8 JSON; raise DigestError for unsupported values."""

    _validate_json_value(value, set())
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return text.encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError) as exc:
        raise DigestError("value cannot be encoded as canonical JSON") from exc


def content_digest(frontmatter: Mapping[str, Any], body: bytes) -> str:
    """Hash immutable frontmatter and verbatim body; raise DigestError on bad input."""

    if not isinstance(frontmatter, Mapping):
        raise DigestError("frontmatter must be a mapping")
    if not isinstance(body, bytes):
        raise DigestError("body must be bytes")
    try:
        reduced = dict(frontmatter)
    except (TypeError, ValueError) as exc:
        raise DigestError("frontmatter must be a valid mapping") from exc
    for key in IMMUTABLE_EXCLUDED_KEYS:
        reduced.pop(key, None)
    encoded = canonical_json(reduced)
    digest = hashlib.sha256(b"adr-scribe/v1\x00" + encoded + b"\x00" + body)
    return "sha256:" + digest.hexdigest()


def _require_exact_keys(value: dict, expected: FrozenSet[str], location: str) -> None:
    actual = frozenset(value.keys())
    if actual != expected:
        unknown = actual - expected
        missing = expected - actual
        if unknown:
            raise DigestError(
                "%s has unknown key(s): %s"
                % (location, ", ".join(sorted(repr(key) for key in unknown)))
            )
        raise DigestError(
            "%s is missing key(s): %s" % (location, ", ".join(sorted(missing)))
        )


def _validate_path(path: Any) -> bytes:
    if not isinstance(path, str):
        raise DigestError("operation path must be a string")
    if path.startswith("/"):
        raise DigestError("operation path must be repo-relative")
    if "\\" in path:
        raise DigestError("operation path must not contain a backslash")
    segments = path.split("/")
    if "" in segments:
        raise DigestError("operation path must not contain an empty segment")
    if "." in segments:
        raise DigestError("operation path must not contain a '.' segment")
    if ".." in segments:
        raise DigestError("operation path must not contain a '..' segment")
    try:
        return path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DigestError("operation path must be valid UTF-8 text") from exc


def _validate_sha256(value: Any, location: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or _HEX_64_RE.fullmatch(value) is None:
        suffix = " or null" if nullable else ""
        raise DigestError("%s must be lowercase 64-hex%s" % (location, suffix))


def _validate_preconditions(value: Any) -> None:
    if not isinstance(value, dict):
        raise DigestError("preconditions must be a dict")
    _require_exact_keys(value, _PRECONDITION_KEYS, "preconditions")
    head = value["head"]
    if not isinstance(head, str) or (
        head != "unborn" and _HEX_40_RE.fullmatch(head) is None
    ):
        raise DigestError("preconditions.head must be lowercase 40-hex or 'unborn'")
    overlaps = value["dirty-overlap"]
    if not isinstance(overlaps, list):
        raise DigestError("preconditions.dirty-overlap must be a list")
    for path in overlaps:
        _validate_path(path)


def _validate_patch(patch: Any) -> None:
    if not isinstance(patch, dict):
        raise DigestError("patch must be a dict")
    _require_exact_keys(patch, _PATCH_KEYS, "patch")
    if type(patch["patch-version"]) is not int or patch["patch-version"] != 1:
        raise DigestError("patch-version must be the integer 1")
    operations = patch["repo-relative-ops"]
    if not isinstance(operations, list):
        raise DigestError("repo-relative-ops must be a list")

    previous_path = None
    seen_paths = set()
    for index, operation in enumerate(operations):
        location = "repo-relative-ops[%d]" % index
        if not isinstance(operation, dict):
            raise DigestError("%s must be a dict" % location)
        op = operation.get("op")
        if not isinstance(op, str) or op not in _OP_KEYS:
            raise DigestError("%s has an unknown op" % location)
        _require_exact_keys(operation, _OP_KEYS[op], location)
        path_bytes = _validate_path(operation["path"])
        if path_bytes in seen_paths:
            raise DigestError("operation paths must be unique")
        if previous_path is not None and path_bytes < previous_path:
            raise DigestError("operations must be sorted by path byte order")
        seen_paths.add(path_bytes)
        previous_path = path_bytes

        if op != "create-dir":
            length = operation["len"]
            if type(length) is not int or length < 0:
                raise DigestError("%s.len must be a non-negative integer" % location)
            _validate_sha256(operation["sha256"], location + ".sha256")
        if op == "replace-file":
            _validate_sha256(
                operation["expect-sha256"],
                location + ".expect-sha256",
                nullable=True,
            )

    _validate_preconditions(patch["preconditions"])


def patch_digest(patch: Mapping[str, Any]) -> str:
    """Validate and hash a patch; raise DigestError when its closed shape is invalid."""

    _validate_patch(patch)
    encoded = canonical_json(patch)
    digest = hashlib.sha256(b"adr-scribe/patch/v1\x00" + encoded)
    return "sha256:" + digest.hexdigest()
