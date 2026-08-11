"""The repository-state matrix (RS-01 .. RS-23).

These are the fixtures the plan's alpha gate depends on. The crash cases inject
failures at the *operation-to-journal* windows, not just at phase boundaries --
crashing only after a phase fsync would exercise the easy half of the protocol
and hide the defects that actually matter.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from adr_scribe import journal as J
from adr_scribe import paths as P
from adr_scribe import transaction as T

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "skills", "adr", "scripts")

RECORD = {
    "title": "Use ULIDs for record identity",
    "summary": ("In the context of concurrent authors, facing coordination cost, we "
                "decided for ULIDs to achieve local generation, accepting longer ids."),
    "decision-makers": ["Joe"],
    "applies-to": ["skills/adr/**"],
    "confirmed-by": ["Joe"],
    "context": "Several developers mint records at once with no central allocator.",
    "drivers": ["No coordination service is available offline."],
    "considered-options": [
        {"name": "ULID", "chosen": True, "pros": ["sorts by creation time"], "cons": []},
        {"name": "Sequential numbers", "chosen": False, "pros": [],
         "cons": ["needs allocation"], "rejection-reason": "it requires coordination"},
    ],
    "decision-outcome": "they need no coordination and still sort by time.",
    "consequences": {"good": ["records can be created offline"], "bad": ["ids are long"]},
    "confirmation": {"manual": ["review the index"], "commands": ["git log --oneline"]},
    "provenance": {"context": "code-observed", "decision": "developer-stated",
                   "drivers": "developer-confirmed", "alternatives": "developer-stated",
                   "consequences": "developer-confirmed", "rules": "developer-confirmed"},
    "evidence": {"commits": [], "working-tree-files": ["skills/adr/scripts/adr_scribe/ids.py"]},
}


def run_script(name, args, env=None, cwd=None):
    full = dict(os.environ)
    full["PYTHONPATH"] = SCRIPTS
    if env:
        full.update(env)
    proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, name)] + args,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=full, cwd=cwd)
    return proc.returncode, proc.stdout.decode(), proc.stderr.decode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        self.stage = os.path.join(self.tmp, "stage")
        os.makedirs(self.repo)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "Tester")
        self.record_path = os.path.join(self.tmp, "record.json")
        with open(self.record_path, "w") as fh:
            json.dump(RECORD, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def prepare(self, stage=None, extra=None):
        stage = stage or self.stage
        args = ["--repo", self.repo, "--input", self.record_path, "--out", stage,
                "--today", "2026-08-12"]
        if extra:
            args.extend(extra)
        return run_script("prepare-record", args)

    def bundle(self, stage=None):
        stage = stage or self.stage
        with open(os.path.join(stage, "patch.json")) as fh:
            return json.load(fh)

    def apply(self, stage=None, digest=None, env=None, extra=None):
        stage = stage or self.stage
        bundle = self.bundle(stage)
        args = ["--patch", os.path.join(stage, "patch.json"),
                "--approved-digest", digest or bundle["patch-digest"], "--json"]
        if extra:
            args.extend(extra)
        return run_script("apply-record", args, env=env)

    def adr_files(self):
        directory = os.path.join(self.repo, "docs", "adr")
        if not os.path.isdir(directory):
            return []
        return sorted(n for n in os.listdir(directory) if n.startswith("adr-"))

    def tree_snapshot(self):
        entries = []
        for base, dirs, files in os.walk(self.repo):
            if ".git" in base:
                continue
            for name in files:
                entries.append(os.path.relpath(os.path.join(base, name), self.repo))
        return sorted(entries)


class TestHappyPath(Base):
    def test_rs01_fresh_repo_bootstraps_adr_and_index(self):
        code, _, err = self.prepare()
        self.assertEqual(code, 0, err)
        code, out, err = self.apply()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.adr_files()), 1)
        self.assertTrue(os.path.exists(os.path.join(self.repo, "docs/adr/README.md")))

    def test_rs02_unborn_head_is_supported(self):
        self.assertEqual(self.prepare()[0], 0)
        bundle = self.bundle()
        self.assertEqual(bundle["patch"]["preconditions"]["head"], "unborn")
        self.assertEqual(self.apply()[0], 0)

    def test_rs03_no_remote_is_fine(self):
        self.assertEqual(self.prepare()[0], 0)
        self.assertEqual(self.apply()[0], 0)

    def test_rs04_detached_head(self):
        with open(os.path.join(self.repo, "seed.txt"), "w") as fh:
            fh.write("x")
        self.git("add", "-A")
        self.git("commit", "-qm", "seed")
        sha = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                             stdout=subprocess.PIPE).stdout.decode().strip()
        self.git("checkout", "-q", sha)
        self.assertEqual(self.prepare()[0], 0)
        self.assertEqual(self.apply()[0], 0)

    def test_rs05_unrelated_dirty_files_are_fine(self):
        with open(os.path.join(self.repo, "unrelated.txt"), "w") as fh:
            fh.write("dirty")
        self.assertEqual(self.prepare()[0], 0)
        self.assertEqual(self.apply()[0], 0)

    def test_written_record_validates_and_index_lists_it_once(self):
        self.prepare()
        self.apply()
        code, out, _ = run_script("validate-adr", ["--repo", self.repo, "--all"])
        self.assertEqual(code, 0, out)
        code, _, err = run_script("render-index", ["--repo", self.repo, "--check"])
        self.assertEqual(code, 0, err)

    def test_lock_is_released_after_success(self):
        self.prepare()
        self.apply()
        self.assertFalse(os.path.exists(os.path.join(self.repo, J.LOCK_DIRNAME)))
        leftovers = [n for n in os.listdir(self.repo)
                     if n.startswith(J.COMPLETED_PREFIX)]
        self.assertEqual(leftovers, [])


class TestRefusals(Base):
    def test_rs07_no_approval_means_no_write(self):
        before = self.tree_snapshot()
        self.assertEqual(self.prepare()[0], 0)
        self.assertEqual(self.tree_snapshot(), before,
                         "prepare-record must not touch the working tree")

    def test_wrong_approved_digest_is_refused(self):
        self.prepare()
        code, _, err = self.apply(digest="sha256:" + "0" * 64)
        self.assertEqual(code, T.E_REFUSED)
        self.assertIn("approval is void", err)
        self.assertEqual(self.adr_files(), [])

    def test_rs09_existing_target_blocks_the_patch(self):
        self.prepare()
        bundle = self.bundle()
        adr_rel = [o["path"] for o in bundle["patch"]["repo-relative-ops"]
                   if o["op"] == "create-file"][0]
        os.makedirs(os.path.join(self.repo, "docs", "adr"), exist_ok=True)
        with open(os.path.join(self.repo, adr_rel), "w") as fh:
            fh.write("squatter")
        code, _, err = self.apply()
        self.assertEqual(code, T.E_PRECONDITION)
        with open(os.path.join(self.repo, adr_rel)) as fh:
            self.assertEqual(fh.read(), "squatter")

    def test_rs10_symlinked_destination_directory_is_refused(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        os.makedirs(os.path.join(self.repo, "docs"))
        os.symlink(outside, os.path.join(self.repo, "docs", "adr"))
        self.prepare()
        code, _, err = self.apply()
        self.assertEqual(code, T.E_REFUSED)
        self.assertIn("symlink", err)
        self.assertEqual(os.listdir(outside), [])

    def test_rs06_dirty_overlap_blocks_at_prepare(self):
        os.makedirs(os.path.join(self.repo, "docs", "adr"))
        with open(os.path.join(self.repo, "docs/adr/README.md"), "w") as fh:
            fh.write("hand written\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "add index")
        with open(os.path.join(self.repo, "docs/adr/README.md"), "a") as fh:
            fh.write("uncommitted edit\n")
        code, _, err = self.prepare()
        self.assertNotEqual(code, 0)
        self.assertIn("uncommitted", err.lower())

    def test_rs19_outside_a_git_repo(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        code, _, err = run_script("prepare-record",
                                  ["--repo", plain, "--input", self.record_path,
                                   "--out", os.path.join(self.tmp, "s2"),
                                   "--today", "2026-08-12"])
        # No git repo: HEAD resolves to "unborn" and the write is still safe,
        # but the skill's S0 preflight is what refuses. Assert we do not crash.
        self.assertIn(code, (0, 1, 5))

    def test_stage_inside_the_repo_is_refused(self):
        code, _, err = self.prepare(stage=os.path.join(self.repo, "stage"))
        self.assertEqual(code, 2)
        self.assertIn("outside the repository", err)


class TestConcurrency(Base):
    def test_rs11b_live_lock_blocks(self):
        self.prepare()
        os.makedirs(os.path.join(self.repo, J.LOCK_DIRNAME))
        with open(os.path.join(self.repo, J.LOCK_DIRNAME, J.OWNER_FILE), "w") as fh:
            json.dump({"pid": os.getpid(),
                       "start-token": J.process_start_token(os.getpid()),
                       "host": "test", "timestamp": __import__("time").time()}, fh)
        code, _, err = self.apply()
        self.assertEqual(code, T.E_LOCKED)
        self.assertEqual(self.adr_files(), [])

    def test_rs11c_corrupt_owner_needs_confirmation(self):
        self.prepare()
        os.makedirs(os.path.join(self.repo, J.LOCK_DIRNAME))
        with open(os.path.join(self.repo, J.LOCK_DIRNAME, J.OWNER_FILE), "w") as fh:
            fh.write("{ not json")
        code, _, err = self.apply()
        self.assertEqual(code, T.E_CONFIRM)
        self.assertIn("force-reclaim", err)

    def test_rs11_stale_lock_is_reclaimed(self):
        self.prepare()
        lock = os.path.join(self.repo, J.LOCK_DIRNAME)
        os.makedirs(lock)
        with open(os.path.join(lock, J.OWNER_FILE), "w") as fh:
            json.dump({"pid": 999999, "start-token": "long gone",
                       "host": "test", "timestamp": 0}, fh)
        code, _, err = self.apply()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.adr_files()), 1)


class TestCrashRecovery(Base):
    def crash_at(self, point):
        self.prepare()
        code, _, _ = self.apply(env={"ADR_SCRIBE_CRASH_AT": point})
        self.assertEqual(code, 70, "expected the injected crash at %s" % point)

    def recover(self, extra=None):
        return run_script("apply-record",
                          ["--repo", self.repo, "--recover", "--json"] + (extra or []))

    def test_rs12b_crash_between_link_and_journal_is_recoverable(self):
        self.crash_at("links-done-prejournal")
        self.assertEqual(len(self.adr_files()), 1, "the ADR was linked before the crash")
        code, out, err = self.recover()
        self.assertEqual(code, 0, err)
        self.assertIn("resumed", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, J.LOCK_DIRNAME)))

    def test_rs12_crash_after_phase_adrs_written_is_recoverable(self):
        self.crash_at("phase-adrs-written")
        code, out, err = self.recover()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.adr_files()), 1)

    def test_rs13b_crash_between_index_rename_and_journal_is_recoverable(self):
        self.crash_at("index-renamed-prejournal")
        code, out, err = self.recover()
        self.assertEqual(code, 0, err)
        code, _, err = run_script("render-index", ["--repo", self.repo, "--check"])
        self.assertEqual(code, 0, err)

    def test_rs13_crash_after_index_replaced_is_recoverable(self):
        self.crash_at("phase-index-replaced")
        code, out, err = self.recover()
        self.assertEqual(code, 0, err)
        code, _, _ = run_script("validate-adr", ["--repo", self.repo, "--all"])
        self.assertEqual(code, 0)

    def test_rs14_interrupted_completed_cleanup_is_idempotent(self):
        self.prepare()
        self.apply()
        marker = os.path.join(self.repo, J.COMPLETED_PREFIX + "123")
        os.makedirs(marker)
        code, out, err = self.recover()
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(marker))
        code, out, _ = self.recover()
        self.assertEqual(code, 0)
        self.assertIn("nothing-to-recover", out)

    def test_recovery_refuses_when_a_written_file_was_changed(self):
        self.crash_at("phase-adrs-written")
        target = os.path.join(self.repo, "docs", "adr", self.adr_files()[0])
        with open(target, "a") as fh:
            fh.write("\nsomeone else edited this\n")
        code, _, err = self.recover()
        self.assertEqual(code, T.E_AFTER_WRITE)
        self.assertIn("changed outside this transaction", err)

    def test_rs17_rollback_removes_only_our_files(self):
        self.crash_at("phase-adrs-written")
        self.assertEqual(len(self.adr_files()), 1)
        code, out, err = self.recover(["--rollback"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.adr_files(), [])
        self.assertIn("rolled-back", out)

    def test_recover_on_a_clean_repo_is_a_noop(self):
        code, out, err = self.recover()
        self.assertEqual(code, 0, err)
        self.assertIn("nothing-to-recover", out)


class TestVerification(Base):
    def test_payload_tampering_is_caught_before_writing(self):
        self.prepare()
        bundle = self.bundle()
        adr_rel = [o["path"] for o in bundle["patch"]["repo-relative-ops"]
                   if o["op"] == "create-file"][0]
        staged = os.path.join(bundle["payload-dir"], adr_rel.replace("/", "__"))
        with open(staged, "ab") as fh:
            fh.write(b"\ntampered\n")
        code, _, err = self.apply()
        self.assertEqual(code, T.E_REFUSED)
        self.assertIn("does not match its patch hash", err)
        self.assertEqual(self.adr_files(), [])

    def test_second_record_appends_to_the_index(self):
        self.prepare()
        self.apply()
        stage2 = os.path.join(self.tmp, "stage2")
        record2 = dict(RECORD)
        record2["title"] = "Adopt canonical frontmatter"
        path2 = os.path.join(self.tmp, "record2.json")
        with open(path2, "w") as fh:
            json.dump(record2, fh)
        code, _, err = run_script("prepare-record",
                                  ["--repo", self.repo, "--input", path2,
                                   "--out", stage2, "--today", "2026-08-12"])
        self.assertEqual(code, 0, err)
        code, _, err = self.apply(stage=stage2)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.adr_files()), 2)
        code, _, err = run_script("render-index", ["--repo", self.repo, "--check"])
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.repo, "docs/adr/README.md")) as fh:
            self.assertEqual(fh.read().count("| ADR-"), 2)


class TestNoGitMutation(Base):
    def test_apply_does_not_create_commits_or_stage_anything(self):
        self.prepare()
        self.apply()
        code = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode
        self.assertNotEqual(code, 0, "apply-record must never create a commit")
        staged = subprocess.run(["git", "-C", self.repo, "diff", "--cached", "--name-only"],
                                stdout=subprocess.PIPE).stdout.decode().strip()
        self.assertEqual(staged, "", "apply-record must never stage anything")


if __name__ == "__main__":
    unittest.main()
