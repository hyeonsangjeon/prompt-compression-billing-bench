import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run as runner
from accounting import sha256, totals
from evidence import check, export


SOURCE_COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


class SourceCommitTests(unittest.TestCase):
    """Synthetic Git responses and execution failures, never benchmark measurements."""

    def setUp(self):
        ledger_bytes = (runner.ROOT / "ledger.toml").read_bytes()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ledger_path = self.root / "ledger.toml"
        self.committed = {
            **{name: f"synthetic committed {name}\n".encode() for name in runner.SOURCE_FILES},
            "ledger.toml": ledger_bytes,
        }
        for name, content in self.committed.items():
            (self.root / name).write_bytes(content)
        self.ledger = runner.load_ledger(self.ledger_path)
        self.head = SOURCE_COMMIT
        self.dirty = b""
        self.commits = {SOURCE_COMMIT: self.committed}
        self.root_patch = patch.object(runner, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.git_patch = patch.object(runner, "source_git", side_effect=self.git_response)
        self.git = self.git_patch.start()
        self.addCleanup(self.git_patch.stop)

    def git_response(self, *arguments):
        if arguments == ("rev-parse", "--show-toplevel"):
            return str(self.root).encode() + b"\n"
        if arguments == ("rev-parse", "--verify", "HEAD"):
            return self.head.encode() + b"\n"
        if arguments == ("status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"):
            return self.dirty
        if arguments[:2] == ("cat-file", "-t") and arguments[2] in self.commits:
            return b"commit\n"
        if arguments[0] == "show":
            commit, name = arguments[1].split(":", 1)
            if commit in self.commits and name in self.commits[commit]:
                return self.commits[commit][name]
        raise ValueError("Source Git verification failed: unavailable commit or file")

    def capture(self):
        return runner.capture_source(self.ledger_path, self.ledger, SOURCE_COMMIT)

    def record(self):
        provenance, ledger_bytes, source_bytes = self.capture()
        directory = self.root / "record"
        (directory / "source").mkdir(parents=True)
        (directory / "ledger.toml").write_bytes(ledger_bytes)
        for name, content in source_bytes.items():
            (directory / "source" / name).write_bytes(content)
        summary = {
            **provenance, "run_id": "synthetic-unit-fixture", "status": "error",
            "usage_totals": totals([]), "trials": [],
        }
        runner.save(directory / "summary.json", summary)
        return directory, summary

    def test_capture_records_designated_sha_and_exact_bytes(self):
        provenance, ledger_bytes, source_bytes = self.capture()
        self.assertEqual(provenance["source_commit"], SOURCE_COMMIT)
        self.assertEqual(provenance["ledger_source_path"], "ledger.toml")
        self.assertEqual(ledger_bytes, self.committed["ledger.toml"])
        for name in runner.SOURCE_FILES:
            self.assertEqual(source_bytes[name], self.committed[name])
            self.assertEqual(provenance["source_files"][name], sha256(source_bytes[name]))

    def test_missing_or_non_full_sha_fails_before_preflight(self):
        with patch.object(runner, "preflight") as preflight:
            for commit in (None, "", "HEAD", "main", "a" * 7, "A" * 40, "g" * 40, "a" * 64, 42):
                with self.subTest(commit=commit), self.assertRaisesRegex(ValueError, "full 40-character SHA"):
                    runner.run(self.ledger_path, self.ledger, source_commit=commit)
            preflight.assert_not_called()
        self.git.assert_not_called()
        self.assertFalse((self.root / "runs").exists())

    def test_head_mismatch_fails_before_preflight(self):
        self.head = OTHER_COMMIT
        with patch.object(runner, "preflight") as preflight:
            with self.assertRaisesRegex(ValueError, "Checkout HEAD differs"):
                runner.run(self.ledger_path, self.ledger, source_commit=SOURCE_COMMIT)
            preflight.assert_not_called()

    def test_dirty_index_worktree_and_untracked_files_fail_before_preflight(self):
        with patch.object(runner, "preflight") as preflight:
            for status in (b"M  uv.lock\n", b" M run.py\n", b"?? helper.py\n"):
                self.dirty = status
                with self.subTest(status=status), self.assertRaisesRegex(ValueError, "clean committed checkout"):
                    runner.run(self.ledger_path, self.ledger, source_commit=SOURCE_COMMIT)
            preflight.assert_not_called()

    def test_git_hidden_input_changes_are_caught_by_blob_comparison(self):
        for name, content in self.committed.items():
            with self.subTest(name=name):
                (self.root / name).write_bytes(content + b"changed\n")
                with self.assertRaisesRegex(ValueError, "Execution input differs"):
                    self.capture()
                (self.root / name).write_bytes(content)

    def test_missing_source_file_is_rejected(self):
        (self.root / "uv.lock").unlink()
        with self.assertRaises(FileNotFoundError):
            self.capture()

    def test_parsed_ledger_must_match_committed_snapshot(self):
        self.ledger["repetitions"] += 1
        with self.assertRaisesRegex(ValueError, "Parsed ledger differs"):
            self.capture()

    def test_external_and_uncommitted_ledgers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "inside the source checkout"):
            runner.capture_source(self.root.parent / "outside.toml", self.ledger, SOURCE_COMMIT)
        uncommitted = self.root / "uncommitted.toml"
        uncommitted.write_bytes(self.committed["ledger.toml"])
        with self.assertRaisesRegex(ValueError, "unavailable commit or file"):
            runner.capture_source(uncommitted, self.ledger, SOURCE_COMMIT)

    def test_committed_nested_ledger_keeps_its_source_path(self):
        relative_path = "configs/repeat.toml"
        self.committed[relative_path] = self.committed["ledger.toml"]
        nested = self.root / relative_path
        nested.parent.mkdir()
        nested.write_bytes(self.committed[relative_path])
        provenance = runner.capture_source(nested, self.ledger, SOURCE_COMMIT)[0]
        self.assertEqual(provenance["ledger_source_path"], relative_path)

    def test_cli_run_and_check_require_a_pin_without_docker(self):
        with patch.object(runner, "preflight") as preflight:
            for options in ([], ["--check"]):
                with self.subTest(options=options), patch("sys.argv", ["run.py", str(self.ledger_path), *options]):
                    with patch("sys.stderr", new_callable=io.StringIO) as output:
                        self.assertEqual(runner.main(), 2)
                        self.assertIn("--source-commit", output.getvalue())
            preflight.assert_not_called()

    def test_check_reports_the_validated_commit(self):
        arguments = ["run.py", str(self.ledger_path), "--check", "--source-commit", SOURCE_COMMIT]
        with patch("sys.argv", arguments), patch.object(runner, "preflight", return_value={}) as preflight:
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(runner.main(), 0)
                self.assertEqual(json.loads(output.getvalue())["source_commit"], SOURCE_COMMIT)
            preflight.assert_called_once_with(self.ledger)

    def test_failure_summary_and_evidence_keep_the_commit(self):
        with patch.object(runner, "preflight", return_value={}), patch("run.os.umask"):
            with patch.object(runner, "materialize_task", side_effect=ValueError("synthetic setup failure")):
                with patch.object(runner, "execute") as execute, patch("sys.stdout", new_callable=io.StringIO):
                    directory = runner.run(self.ledger_path, self.ledger, source_commit=SOURCE_COMMIT)
                    execute.assert_not_called()
        summary = runner.verify(directory, SOURCE_COMMIT)
        self.assertEqual(summary["status"], "error")
        self.assertEqual(summary["source_commit"], SOURCE_COMMIT)
        target = self.root / "evidence.json"
        export(directory, target)
        published = check(target)
        self.assertEqual(published["source_commit"], SOURCE_COMMIT)
        self.assertNotIn("ledger_source_path", published)
        self.assertNotIn("source_snapshot", published)

    def test_verify_uses_recorded_commit_not_current_head_or_worktree(self):
        directory, summary = self.record()
        self.head = OTHER_COMMIT
        self.dirty = b" M run.py\n"
        (self.root / "run.py").write_bytes(b"new working source\n")
        self.git.reset_mock()
        self.assertEqual(runner.verify(directory), summary)
        self.assertTrue(all(call.args[0] in ("cat-file", "show") for call in self.git.call_args_list))

    def test_verify_can_check_an_independently_designated_commit(self):
        directory, summary = self.record()
        self.assertEqual(runner.verify(directory, SOURCE_COMMIT), summary)
        with self.assertRaisesRegex(ValueError, "Recorded source_commit differs"):
            runner.verify(directory, OTHER_COMMIT)

    def test_missing_or_null_historical_commit_is_not_backfilled(self):
        directory, summary = self.record()
        legacy_records = (
            {**summary, "source_commit": None},
            {key: value for key, value in summary.items() if key != "source_commit"},
        )
        for changed in legacy_records:
            runner.save(directory / "summary.json", changed)
            with self.assertRaisesRegex(ValueError, "source_commit"):
                runner.verify(directory)

    def test_unknown_recorded_commit_is_rejected(self):
        directory, summary = self.record()
        summary["source_commit"] = OTHER_COMMIT
        runner.save(directory / "summary.json", summary)
        with self.assertRaisesRegex(ValueError, "unavailable commit or file"):
            runner.verify(directory)

    def test_changed_commit_is_checked_against_git_blobs(self):
        directory, summary = self.record()
        self.commits[OTHER_COMMIT] = {**self.committed, "run.py": b"different committed source\n"}
        summary["source_commit"] = OTHER_COMMIT
        runner.save(directory / "summary.json", summary)
        with self.assertRaisesRegex(ValueError, "Source snapshot differs from source_commit"):
            runner.verify(directory)

    def test_source_manifest_and_snapshot_path_are_required(self):
        directory, summary = self.record()
        for field in ("source_snapshot", "source_files"):
            changed = copy.deepcopy(summary)
            del changed[field]
            runner.save(directory / "summary.json", changed)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "source snapshot manifest"):
                runner.verify(directory)
        for manifest in ({}, {**summary["source_files"], "../private": "unit"}):
            runner.save(directory / "summary.json", {**summary, "source_files": manifest})
            with self.assertRaisesRegex(ValueError, "source snapshot manifest"):
                runner.verify(directory)
        runner.save(directory / "summary.json", {**summary, "source_snapshot": str(self.root)})
        with self.assertRaisesRegex(ValueError, "source snapshot manifest"):
            runner.verify(directory)

    def test_aggregate_source_hash_is_verified(self):
        directory, summary = self.record()
        summary["source_sha256"] = "changed"
        runner.save(directory / "summary.json", summary)
        with self.assertRaisesRegex(ValueError, "Aggregate source hash mismatch"):
            runner.verify(directory)

    def test_source_tampering_fails_even_with_recomputed_hashes(self):
        directory, summary = self.record()
        changed = b"different source\n"
        (directory / "source/run.py").write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "Source snapshot hash mismatch"):
            runner.verify(directory)
        summary["source_files"]["run.py"] = sha256(changed)
        summary["source_sha256"] = sha256(json.dumps(summary["source_files"], sort_keys=True).encode())
        runner.save(directory / "summary.json", summary)
        with self.assertRaisesRegex(ValueError, "Source snapshot differs from source_commit"):
            runner.verify(directory)

    def test_ledger_tampering_fails_even_with_recomputed_hash(self):
        directory, summary = self.record()
        changed = self.committed["ledger.toml"] + b"\n"
        (directory / "ledger.toml").write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "Ledger hash mismatch"):
            runner.verify(directory)
        summary["ledger_sha256"] = sha256(changed)
        runner.save(directory / "summary.json", summary)
        with self.assertRaisesRegex(ValueError, "Ledger snapshot differs from source_commit"):
            runner.verify(directory)

    def test_ledger_source_path_is_required_and_confined_to_commit(self):
        directory, summary = self.record()
        for path in (None, "", ".", "/tmp/ledger.toml", "../ledger.toml", "./ledger.toml"):
            runner.save(directory / "summary.json", {**summary, "ledger_source_path": path})
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "ledger_source_path"):
                runner.verify(directory)


class SourceGitTests(unittest.TestCase):
    def test_git_is_read_from_source_root_without_replacements_or_lazy_fetch(self):
        with patch("run.subprocess.check_output", return_value=b"commit\n") as command:
            self.assertEqual(runner.source_git("cat-file", "-t", SOURCE_COMMIT), b"commit\n")
            command.assert_called_once_with(
                ["git", "--no-replace-objects", "-C", str(runner.ROOT), "cat-file", "-t", SOURCE_COMMIT],
                stderr=subprocess.PIPE,
                env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
            )

    def test_missing_git_and_commit_fail_instead_of_recording_none(self):
        failures = (
            (FileNotFoundError("git"), FileNotFoundError),
            (subprocess.CalledProcessError(128, ["git"], stderr=b"not a valid object"), ValueError),
        )
        for failure, expected in failures:
            with self.subTest(failure=failure), patch("run.subprocess.check_output", side_effect=failure):
                with self.assertRaises(expected):
                    runner.source_git("cat-file", "-t", SOURCE_COMMIT)

    def test_full_sha_must_identify_a_commit_not_a_tree_or_tag(self):
        for object_type in (b"tree\n", b"tag\n", b"blob\n"):
            with self.subTest(object_type=object_type), patch.object(runner, "source_git", return_value=object_type):
                with self.assertRaisesRegex(ValueError, "Git commit object"):
                    runner.committed_inputs(SOURCE_COMMIT, "ledger.toml")


if __name__ == "__main__":
    unittest.main()
