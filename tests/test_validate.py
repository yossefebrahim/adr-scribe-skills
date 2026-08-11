"""Tests for the validation backstop.

The positive case matters as much as the rejections: if a correctly built
record cannot pass, the validator would block every legitimate write.
"""

import unittest

from adr_scribe import _frontmatter as fm
from adr_scribe import digest, validate as V

ULID = "01J000000000000000000000AA"
RID = "ADR-" + ULID
TITLE = "Use ULIDs for record identity"
SUMMARY = ("In the context of concurrent authors, facing coordination cost, we decided for "
           "ULIDs to achieve local generation, accepting longer identifiers.")


def base_frontmatter(**overrides):
    fmap = {
        "status": "proposed",
        "date": "2026-08-12",
        "decision-makers": ["Joe"],
        "consulted": [],
        "informed": [],
        "schema": "adr-scribe/v1",
        "id": RID,
        "title": TITLE,
        "summary": SUMMARY,
        "decision-date": "2026-08-12",
        "applies-to": ["skills/adr/**"],
        "supersedes": [],
        "roadmap-ref": None,
        "content-digest": "sha256:" + "0" * 64,
        "acceptance": None,
        "provenance": {
            "context": "code-observed",
            "decision": "developer-stated",
            "drivers": "developer-confirmed",
            "alternatives": "developer-stated",
            "consequences": "developer-confirmed",
            "rules": "developer-confirmed",
        },
        "evidence": {"commits": [], "working-tree-files": ["skills/adr/scripts/adr_scribe/ids.py"]},
        "record-confirmation": {"confirmed-by": ["Joe"]},
    }
    fmap.update(overrides)
    return fmap


def body_for(fmap, extra=""):
    return (
        "# %s — %s\n\n> %s\n\n## Context and Problem Statement\n\n"
        "Records need identifiers that several authors can mint at once.\n\n"
        "### Confirmation\n\n- Manual: review the index.\n- Optional: `git log --oneline`\n%s"
        % (fmap["id"], fmap["title"], fmap["summary"], extra)
    ).encode("utf-8")


def build_document(fmap=None, extra=""):
    """Build a complete, digest-correct ADR document."""
    fmap = dict(fmap or base_frontmatter())
    body = body_for(fmap, extra)
    fmap["content-digest"] = digest.content_digest(fmap, body)
    return ("---\n" + fm.emit(fmap) + "---\n").encode("utf-8") + body, fmap


class TestValidDocument(unittest.TestCase):
    def test_a_correctly_built_record_passes(self):
        raw, _ = build_document()
        findings = V.validate_document(raw)
        self.assertEqual([f.as_dict() for f in V.errors(findings)], [])

    def test_digest_is_self_consistent(self):
        raw, fmap = build_document()
        front, body = fm.split_document(raw)
        self.assertEqual(digest.content_digest(fm.parse(front), body), fmap["content-digest"])


class TestFrontmatterRules(unittest.TestCase):
    def codes(self, **overrides):
        fmap = base_frontmatter(**overrides)
        return {f.code for f in V.errors(V.validate_frontmatter(fmap))}

    def test_wrong_schema(self):
        self.assertIn("schema", self.codes(schema="adr-scribe/v2"))

    def test_status_must_be_proposed_in_v1(self):
        self.assertIn("status", self.codes(status="accepted"))

    def test_bad_id(self):
        self.assertIn("id", self.codes(id="ADR-nope"))
        self.assertIn("id", self.codes(id=RID.lower()))

    def test_bad_dates(self):
        self.assertIn("date", self.codes(date="12-08-2026"))
        self.assertIn("date", self.codes(date="2026-13-01"))
        self.assertIn("date", self.codes(**{"decision-date": "2026-02-30x"}))

    def test_unconfirmed_provenance_cannot_be_persisted(self):
        prov = dict(base_frontmatter()["provenance"])
        prov["decision"] = "[UNCONFIRMED]"
        self.assertIn("provenance", self.codes(provenance=prov))

    def test_unknown_provenance_value_rejected(self):
        prov = dict(base_frontmatter()["provenance"])
        prov["decision"] = "vibes"
        self.assertIn("provenance", self.codes(provenance=prov))

    def test_supersedes_and_acceptance_must_be_empty_in_v1(self):
        self.assertIn("supersedes", self.codes(supersedes=["ADR-" + ULID]))
        self.assertIn("acceptance", self.codes(acceptance={"by": "Joe"}))

    def test_applies_to_must_not_be_empty(self):
        self.assertIn("empty", self.codes(**{"applies-to": []}))

    def test_confirmed_by_must_not_be_empty(self):
        self.assertIn("empty", self.codes(**{"record-confirmation": {"confirmed-by": []}}))

    def test_bad_digest_format(self):
        self.assertIn("digest", self.codes(**{"content-digest": "sha256:XYZ"}))


class TestGlobDialect(unittest.TestCase):
    def test_accepts_valid_patterns(self):
        for pattern in ("**/*", "a/**", "a/*.py", "src/**/test_*.py", "a"):
            self.assertIsNone(V.validate_glob(pattern), pattern)

    def test_rejects_invalid_patterns(self):
        for pattern in ("/abs/path", "../escape", "~/home", "!negated",
                        "back\\slash", "a//b", "a/./b", "a/**b/c", ""):
            self.assertIsNotNone(V.validate_glob(pattern), pattern)


class TestBodyRules(unittest.TestCase):
    def codes_for(self, raw):
        return {f.code for f in V.errors(V.validate_document(raw))}

    def test_unconfirmed_marker_blocks_the_write(self):
        raw, _ = build_document(extra="\nSome [UNCONFIRMED] rationale.\n")
        self.assertIn("marker", self.codes_for(raw))

    def test_todo_marker_blocks_the_write(self):
        raw, _ = build_document(extra="\nTODO: ask about this.\n")
        self.assertIn("marker", self.codes_for(raw))

    def test_template_placeholder_blocks_the_write(self):
        raw, _ = build_document(extra="\nChosen option: <short, decision-first title>\n")
        self.assertIn("placeholder", self.codes_for(raw))

    def test_h1_must_mirror_title(self):
        fmap = base_frontmatter()
        body = body_for(fmap).replace(b"# " + RID.encode(), b"# Wrong heading")
        fmap["content-digest"] = digest.content_digest(fmap, body)
        raw = ("---\n" + fm.emit(fmap) + "---\n").encode() + body
        self.assertIn("h1", self.codes_for(raw))

    def test_summary_blockquote_must_be_present(self):
        fmap = base_frontmatter()
        body = body_for(fmap).replace(("> " + SUMMARY).encode(), b"> something else")
        fmap["content-digest"] = digest.content_digest(fmap, body)
        raw = ("---\n" + fm.emit(fmap) + "---\n").encode() + body
        self.assertIn("summary-mirror", self.codes_for(raw))

    def test_tampering_with_the_body_breaks_the_digest(self):
        raw, _ = build_document()
        tampered = raw.replace(b"Records need identifiers", b"Records need identifierz")
        self.assertIn("digest", self.codes_for(tampered))

    def test_marker_inside_a_code_fence_still_blocks(self):
        # Markers are checked on the raw text: a record shipping [UNCONFIRMED]
        # anywhere is unfinished, code fence or not.
        raw, _ = build_document(extra="\n```\n[UNCONFIRMED]\n```\n")
        self.assertIn("marker", self.codes_for(raw))


class TestConfirmationCommandSafety(unittest.TestCase):
    def test_read_only_commands_allowed(self):
        for command in ("git log --oneline", "rg 'foo' src", "ls docs/adr",
                        "python3 -m unittest discover", "grep -rn x ."):
            self.assertIsNone(V.check_command_safety(command), command)

    def test_destructive_and_network_commands_rejected(self):
        for command in ("rm -rf docs", "curl https://example.com", "sudo make install",
                        "git push origin main", "npm install left-pad",
                        "chmod 777 .", "ssh host 'ls'"):
            self.assertIsNotNone(V.check_command_safety(command), command)

    def test_shell_metacharacters_rejected(self):
        for command in ("ls | wc -l", "cat a > b", "ls; rm x", "echo $(whoami)",
                        "ls && rm -rf /"):
            self.assertIsNotNone(V.check_command_safety(command), command)

    def test_write_capable_git_subcommand_rejected(self):
        self.assertIsNotNone(V.check_command_safety("git commit -m x"))
        self.assertIsNotNone(V.check_command_safety("git checkout main"))

    def test_unsafe_command_in_a_record_is_an_error(self):
        raw, _ = build_document()
        bad = raw.replace(b"`git log --oneline`", b"`rm -rf docs/adr`")
        codes = {f.code for f in V.errors(V.validate_document(bad))}
        # digest also breaks, which is fine -- the command check must fire too
        self.assertIn("confirmation-command", codes)


class TestLength(unittest.TestCase):
    def test_warns_above_the_target(self):
        raw, _ = build_document(extra="\n" + ("word " * 900) + "\n")
        findings = V.validate_document(raw)
        self.assertTrue(any(f.code == "length" and f.level == "warning" for f in findings))

    def test_code_fences_do_not_count_toward_length(self):
        fenced = "\n```\n" + ("word " * 2000) + "\n```\n"
        raw, _ = build_document(extra=fenced)
        self.assertFalse(any(f.code == "length" for f in V.validate_document(raw)))


if __name__ == "__main__":
    unittest.main()
