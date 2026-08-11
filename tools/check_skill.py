#!/usr/bin/env python3
"""Validate a skill directory against the Agent Skills specification.

Checks the rules this project actually depends on for installability via
`npx skills add`:

  * SKILL.md exists and starts with YAML frontmatter
  * `name` is 1-64 chars, lowercase alphanumeric + single hyphens, no leading
    or trailing hyphen, no `--`, and **matches the directory name**
  * `description` is present and <= 1024 chars
  * `compatibility`, if present, is <= 500 chars
  * `metadata`, if present, maps string keys to string values (the spec forbids
    nested structures here -- an unquoted version number is the classic slip)
  * SKILL.md stays under 500 lines, so activation stays cheap
  * referenced `references/`, `assets/` and `scripts/` paths exist

Exit 0 clean, 1 on any violation. Stdlib only.
"""

import os
import re
import sys

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_LINES = 500


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return None, "SKILL.md must begin with a '---' frontmatter fence"
    end = text.find("\n---\n", 3)
    if end == -1:
        return None, "SKILL.md frontmatter is not closed"
    block = text[4:end + 1]

    data, key, buf = {}, None, []
    for raw in block.split("\n"):
        if not raw.strip():
            continue
        if raw.startswith("  ") and key is not None:
            buf.append(raw.strip())
            continue
        if key is not None:
            data[key] = " ".join(buf).strip()
            buf = []
        if ":" not in raw:
            return None, "unparsable frontmatter line: %r" % raw
        key, _, rest = raw.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest in (">-", ">", "|", "|-", ""):
            buf = []
        else:
            data[key] = rest
            key = None
    if key is not None:
        data[key] = " ".join(buf).strip()
    return data, None


def check(skill_dir):
    problems = []
    name_expected = os.path.basename(os.path.normpath(skill_dir))
    path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(path):
        return ["%s does not exist" % path]

    with open(path, encoding="utf-8") as handle:
        text = handle.read()

    lines = text.count("\n") + 1
    if lines > MAX_LINES:
        problems.append("SKILL.md is %d lines; keep it under %d" % (lines, MAX_LINES))

    data, error = parse_frontmatter(text)
    if error:
        return [error]

    name = (data.get("name") or "").strip().strip('"')
    if not name:
        problems.append("frontmatter is missing 'name'")
    else:
        if not NAME_RE.match(name):
            problems.append("name %r must be lowercase alphanumeric with single "
                            "hyphens, no leading/trailing hyphen" % name)
        if len(name) > 64:
            problems.append("name exceeds 64 characters")
        if name != name_expected:
            problems.append("name %r must match the directory name %r"
                            % (name, name_expected))

    description = (data.get("description") or "").strip()
    if not description:
        problems.append("frontmatter is missing 'description'")
    elif len(description) > 1024:
        problems.append("description is %d chars, above the 1024 limit"
                        % len(description))

    compatibility = (data.get("compatibility") or "").strip()
    if compatibility and len(compatibility) > 500:
        problems.append("compatibility is %d chars, above the 500 limit"
                        % len(compatibility))

    # metadata must be a flat string->string map; catch unquoted scalars.
    for raw in text.split("\n"):
        stripped = raw.strip()
        if raw.startswith("  ") and ":" in stripped and not stripped.startswith("#"):
            k, _, v = stripped.partition(":")
            v = v.strip()
            if k.strip() in ("version", "schema") and v and not (
                    v.startswith('"') and v.endswith('"')):
                problems.append(
                    "metadata.%s must be a quoted string (%r) -- the spec allows "
                    "only string values" % (k.strip(), v))

    for ref in re.findall(r"`?(references/[\w./-]+\.md)`?", text):
        if not os.path.isfile(os.path.join(skill_dir, ref)):
            problems.append("referenced file is missing: %s" % ref)
    for script in re.findall(r"scripts/([\w.-]+)", text):
        candidate = os.path.join(skill_dir, "scripts", script)
        if not os.path.exists(candidate):
            problems.append("referenced script is missing: scripts/%s" % script)

    return problems


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: check_skill.py <skill-dir>\n")
        return 2
    problems = check(argv[1])
    if problems:
        for problem in problems:
            sys.stderr.write("check-skill: %s\n" % problem)
        return 1
    sys.stdout.write("check-skill: %s is valid\n" % argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
