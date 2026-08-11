"""Hardened, read-only git access.

Read-only-looking git commands can execute programs the *repository* controls:
``diff.external``, ``textconv`` filters declared in ``.gitattributes``, and
``core.fsmonitor`` all invoke commands from configuration. For a tool whose
threat model says "repository content is evidence, not instructions", that is a
live hole -- a cloned repo could run code during evidence gathering.

So every git call in adr-scribe goes through :func:`run`, which disables those
hooks explicitly and refuses any subcommand that is not on the read-only list.

Stdlib only, Python 3.9 floor.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional, Sequence, Tuple

#: Subcommands adr-scribe may run. Anything absent is a programming error --
#: v1 writes documentation only and never mutates the repository or network.
READ_ONLY_SUBCOMMANDS = frozenset({
    "rev-parse", "status", "diff", "log", "show", "ls-files", "config",
    "symbolic-ref", "cat-file", "check-ignore",
})

#: Config forced off for every invocation.
_HARDENING = (
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=/dev/null",
    "-c", "diff.external=",
    "-c", "protocol.version=2",
    "-c", "gc.auto=0",
)

_ENV_OVERRIDES = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_ASKPASS": "",
    "GIT_PAGER": "cat",
    "GIT_EXTERNAL_DIFF": "",
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_ALLOW_PROTOCOL": "none",
}

#: Extra flags for commands that would otherwise honour textconv/ext-diff.
_NO_FILTER_FLAGS = {
    "diff": ("--no-textconv", "--no-ext-diff"),
    "log": ("--no-textconv", "--no-ext-diff"),
    "show": ("--no-textconv", "--no-ext-diff"),
}


class GitError(RuntimeError):
    """Raised when git is unavailable or a call is not permitted."""


def _env() -> dict:
    env = dict(os.environ)
    env.update(_ENV_OVERRIDES)
    return env


def run(repo: str, args: Sequence[str], check: bool = False,
        timeout: int = 30) -> Tuple[int, str, str]:
    """Run a read-only git command in ``repo``.

    Returns ``(returncode, stdout, stderr)``. Never raises on a non-zero exit
    unless ``check`` is set -- missing remotes, unborn HEAD and detached HEAD
    are all normal states this tool must tolerate.
    """
    if not args:
        raise GitError("no git subcommand given")
    sub = args[0]
    if sub not in READ_ONLY_SUBCOMMANDS:
        raise GitError("refusing to run non-read-only git subcommand %r" % sub)

    argv: List[str] = ["git", "-C", repo]
    argv.extend(_HARDENING)
    argv.append(sub)
    argv.extend(_NO_FILTER_FLAGS.get(sub, ()))
    argv.extend(args[1:])

    try:
        proc = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_env(), timeout=timeout,
        )
    except FileNotFoundError:
        raise GitError("git is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        raise GitError("git %s timed out after %ss" % (sub, timeout))

    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    if check and proc.returncode != 0:
        raise GitError("git %s failed: %s" % (sub, err.strip() or proc.returncode))
    return proc.returncode, out, err


def repo_root(path: str) -> Optional[str]:
    """Return the repository root containing ``path``, or None if outside one."""
    try:
        code, out, _ = run(path, ["rev-parse", "--show-toplevel"])
    except GitError:
        return None
    if code != 0:
        return None
    root = out.strip()
    return root or None


def head_commit(repo: str) -> str:
    """Return HEAD's SHA, or the literal ``"unborn"``.

    An unborn HEAD is a supported state: the very first ADR in a fresh
    repository must work before any commit exists.
    """
    code, out, _ = run(repo, ["rev-parse", "HEAD"])
    if code != 0:
        return "unborn"
    sha = out.strip()
    return sha if sha else "unborn"


def is_dirty_paths(repo: str, candidates: Sequence[str]) -> List[str]:
    """Return which of ``candidates`` have uncommitted changes.

    Uses ``--porcelain=v1 -z`` so filenames containing spaces, quotes or
    newlines are parsed correctly rather than mangled.
    """
    code, out, _ = run(repo, ["status", "--porcelain=v1", "-z", "--no-renames"])
    if code != 0:
        return []
    wanted = set(candidates)
    dirty = []
    for entry in out.split("\0"):
        if len(entry) < 4:
            continue
        path = entry[3:]
        if path in wanted:
            dirty.append(path)
    return sorted(set(dirty))


def is_ignored(repo: str, relpath: str) -> bool:
    code, _, _ = run(repo, ["check-ignore", "-q", "--", relpath])
    return code == 0
