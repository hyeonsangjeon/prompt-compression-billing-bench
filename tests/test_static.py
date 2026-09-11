import copy
from contextlib import chdir, redirect_stderr
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import run as entrypoint

from src import provenance, static_run
from src.compressors import CompressorError, NoOpCompressor, SqueezCompressor, make_compressor, report
from src.contracts import load_ledger, safe_child, validate
from src.measurement import billed_unavailable, load_encoder, pattern_observation
from src.pipeline import ObservationPipeline
from src.protection import digest


ROOT = Path(__file__).resolve().parents[1]


class StaticContractTests(unittest.TestCase):
    def setUp(self):
        self.ledger = load_ledger(ROOT / "ledgers/demo.toml")
        self.encoder = load_encoder(self.ledger["measurement"])
        self.manifest, _content, self.sources = static_run.read_inputs(self.ledger, self.encoder, ROOT / "examples/static")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def measure(self, compressor, ledger):
        request = self.manifest["requests"][0]
        source = self.sources[0]
        transformed, checked, originals, compressed = ObservationPipeline(compressor).transform(source, request["sha256"], request["segments"])
        lineage = {
            "run_id": "synthetic-unit-fixture", "source_commit": "a" * 40,
            "source_sha256": "b" * 64, "ledger_sha256": "c" * 64,
            "manifest_sha256": ledger["inputs"]["manifest_sha256"],
            "compressor": {**compressor.metadata, "target": "identified_log_spans"},
        }
        record = static_run.request_record(request, source, originals, compressed, transformed, checked, ledger, self.manifest, self.encoder, lineage)
        validate(record, "static-result.schema.json")
        return record

    def test_none_is_exact_and_deletion_is_only_a_calculation(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            compressor = make_compressor(self.ledger["compressor"], self.directory / "none")
            record = self.measure(compressor, self.ledger)
        self.assertEqual(record["measured_local"]["before"], record["measured_local"]["after"])
        self.assertTrue(all(value == 0 for value in record["reductions"]["saved"].values()))
        self.assertEqual(record["deletion_reference"]["kind"], "calculated")
        self.assertEqual(record["measured_billed"], billed_unavailable())
        self.assertEqual(record["input_kind"], "synthetic_fixture")
        self.assertIsNone(record["judge"]["score"])

    def test_billing_zero_quality_scores_and_unknown_metrics_are_rejected(self):
        record = self.measure(NoOpCompressor({"options": {}}, None), self.ledger)
        mutations = [
            lambda changed: changed["measured_billed"].update(input_tokens=0),
            lambda changed: changed["measured_billed"].update(cost_usd=0),
            lambda changed: changed["judge"].update(score=1),
            lambda changed: changed["measured_local"].update(provider_tokens=100),
            lambda changed: changed.update(source_commit=None),
            lambda changed: changed.update(source_commit="HEAD"),
            lambda changed: changed.update(raw_prompt="do not publish"),
        ]
        for mutation in mutations:
            changed = copy.deepcopy(record)
            mutation(changed)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate(changed, "static-result.schema.json")

    def test_unknown_compressors_paid_limits_and_options_are_rejected(self):
        mutations = [
            lambda changed: changed["compressor"].update(name="headroom"),
            lambda changed: changed["compressor"].update(target="all_user_messages"),
            lambda changed: changed["compressor"]["tools"]["squeez"]["options"].update(invocation="run_original_command"),
            lambda changed: changed["limits"].update(model_calls=1),
            lambda changed: changed["limits"].update(api_cost_usd=1),
        ]
        for mutation in mutations:
            changed = copy.deepcopy(self.ledger)
            mutation(changed)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate(changed, "static-ledger.schema.json")

    def test_frozen_expectations_block_drift_in_both_directions(self):
        for difference in (-1, 1):
            for field in self.ledger["expect"]:
                changed = copy.deepcopy(self.ledger)
                changed["expect"][field] += difference
                with self.subTest(field=field, difference=difference), self.assertRaisesRegex(ValueError, "either direction"):
                    static_run.read_inputs(changed, self.encoder, ROOT / "examples/static")

    def test_tool_display_has_different_explicit_units(self):
        observed = report(["# squeez [cat] 219→96 tokens (-57%) 1ms"], "squeez")
        self.assertEqual([metric["value"] for metric in observed["metrics"]], [219, 96, -57])
        self.assertNotEqual(observed["metrics"][0]["unit"], observed["metrics"][1]["unit"])
        self.assertTrue(observed["not_provider_usage"])
        self.assertEqual(report([], "squeez")["status"], "not_reported")
        grouped = report(["# squeez [cat] 2,000→1,000 (-50%) 1ms"], "squeez")
        self.assertEqual(grouped["metrics"][0]["value"], 2000)
        compact = report(["# squeez [cat] 2.0K→1.0K (-50%) 1ms"], "squeez")
        self.assertEqual(compact["metrics"], [])
        self.assertEqual(compact["status"], "reported")

    def test_static_entrypoint_never_enters_native_preflight(self):
        with patch("sys.argv", ["run.py", "static", "--check", "--source-commit", "not-a-sha"]), patch.object(entrypoint, "preflight") as native, redirect_stderr(io.StringIO()):
            self.assertEqual(entrypoint.main(), 2)
            native.assert_not_called()

    def test_missing_tokenizer_never_downloads_implicitly(self):
        with patch.dict(os.environ, {"TIKTOKEN_CACHE_DIR": str(self.directory)}), patch("urllib.request.urlopen") as network:
            with self.assertRaisesRegex(ValueError, "Tokenizer table missing"):
                load_encoder(self.ledger["measurement"])
            network.assert_not_called()

    def test_artifact_paths_cannot_escape_or_use_symlinks(self):
        (self.directory / "outside").symlink_to(ROOT)
        for name in ("../secret", "/etc/passwd", "./noncanonical", "outside/run.py"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_child(self.directory, name)

    def test_pattern_diagnostics_do_not_claim_semantic_safety(self):
        result = pattern_observation("[2026-01-01T00:00:01Z] INFO OK\n", "INFO OK\n")
        self.assertEqual(result["before"]["iso_timestamp_prefix"], 1)
        self.assertEqual(result["after"]["iso_timestamp_prefix"], 0)
        self.assertEqual(result["kind"], "classification")
        self.assertIn("do not establish", result["does_not_prove"])

    def stub(self, body: str) -> dict:
        executable = self.directory / "synthetic-squeez"
        executable.write_text(
            "#!/usr/bin/python3\nimport os, pathlib, sys, time\n"
            "if sys.argv[1:] == ['--version']:\n    print('squeez 1.48.4')\n    sys.exit(0)\n" + body
        )
        executable.chmod(0o700)
        specification = copy.deepcopy(self.ledger["compressor"]["tools"]["squeez"])
        specification["sha256"] = digest(executable.read_bytes())
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"SQUEEZ_BINARY": str(executable), "PRIVATE_TEST_CREDENTIAL": "not-forwarded"}).start()
        return specification

    def test_binary_adapter_uses_fixed_command_fresh_state_and_full_stdout(self):
        specification = self.stub(
            "assert sys.argv[1:] == ['wrap', 'cat input.txt']\n"
            "assert 'PRIVATE_TEST_CREDENTIAL' not in os.environ\n"
            "home = pathlib.Path(os.environ['HOME'])\n"
            "assert not (home / 'seen').exists()\n(home / 'seen').write_text('seen')\n"
            "sys.stdout.write('# squeez [cat] 10→12 (+20%) 1ms\\n' + pathlib.Path('input.txt').read_text())\n"
        )
        compressor = SqueezCompressor(specification, self.directory / "artifacts")
        first = compressor.compress("short input")
        second = compressor.compress("short input")
        self.assertEqual(first.text, second.text)
        self.assertTrue(first.text.endswith("short input"))
        self.assertGreater(len(first.text), len("short input"))
        self.assertTrue((self.directory / "artifacts/span-00001/home/seen").exists())
        self.assertTrue((self.directory / "artifacts/span-00002/home/seen").exists())
        self.assertEqual(compressor.calls, 2)

    def test_binary_change_exit_failure_and_invalid_utf8_stop(self):
        for body in ("sys.exit(7)\n", "sys.stdout.buffer.write(b'\\xff')\n"):
            specification = self.stub(body)
            with tempfile.TemporaryDirectory(dir=self.directory) as temporary:
                compressor = SqueezCompressor(specification, Path(temporary) / "artifacts")
                with self.assertRaises(CompressorError):
                    compressor.compress("input")
        Path(os.environ["SQUEEZ_BINARY"]).write_text("changed")
        with self.assertRaisesRegex(CompressorError, "changed during"):
            compressor.compress("input")

    def test_timeout_kills_compressor_and_restores_alarm(self):
        specification = self.stub("time.sleep(2)\n")
        specification["options"]["timeout_seconds"] = 0.1
        compressor = SqueezCompressor(specification, self.directory / "artifacts")
        with self.assertRaisesRegex(CompressorError, "timed out"):
            compressor.compress("input")
        previous = signal.getsignal(signal.SIGALRM)
        with self.assertRaises(TimeoutError), static_run.time_limit(0.02):
            time.sleep(0.1)
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    @unittest.skipUnless(os.environ.get("TEST_SQUEEZ_BINARY"), "real pinned squeez not supplied; this is an optional offline integration test")
    def test_real_squeez_and_none_swap_only_name(self):
        baseline = self.measure(make_compressor(self.ledger["compressor"], self.directory / "none"), self.ledger)
        changed = copy.deepcopy(self.ledger)
        changed["compressor"]["name"] = "squeez"
        self.assertEqual(self.ledger | {"compressor": changed["compressor"]}, changed)
        with patch.dict(os.environ, {"SQUEEZ_BINARY": os.environ["TEST_SQUEEZ_BINARY"]}):
            compressed = self.measure(make_compressor(changed["compressor"], self.directory / "squeez"), changed)
        self.assertEqual(set(baseline), set(compressed))
        for field in ("sample", "protection", "deletion_reference", "judge", "measured_billed"):
            self.assertEqual(baseline[field], compressed[field])
        self.assertEqual(baseline["measured_local"]["before"], compressed["measured_local"]["before"])
        self.assertNotEqual(compressed["measured_local"]["before"], compressed["measured_local"]["after"])
        restored = copy.deepcopy(changed)
        restored["compressor"]["name"] = "none"
        self.assertEqual(restored, self.ledger)


class StaticSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        names = [*provenance.source_files(ROOT), ".gitignore", "ledgers/demo.toml", "examples/static/manifest.json", "examples/static/requests/0000.json"]
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.git("init", "-q")
        self.git("add", ".")
        self.commit()
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.ledger = self.root / "ledgers/demo.toml"
        self.enter = chdir(self.root)
        self.enter.__enter__()
        self.addCleanup(self.enter.__exit__, None, None, None)
        self.environment = patch.dict(os.environ, {"FROZEN_INPUT_ROOT": str(self.root / "examples/static")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.capture_patch = patch.object(static_run, "capture", side_effect=lambda path, sha: provenance.capture(path, sha, self.root))
        self.capture_patch.start()
        self.addCleanup(self.capture_patch.stop)
        self.verify_patch = patch.object(static_run, "verify_snapshot", side_effect=lambda directory: provenance.verify_snapshot(directory, self.root))
        self.verify_patch.start()
        self.addCleanup(self.verify_patch.stop)

    def git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.root), *arguments], stderr=subprocess.PIPE).decode()

    def commit(self):
        self.git("-c", "user.name=Synthetic Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "Synthetic source fixture")

    def test_execution_and_verification_record_real_fixture_commit(self):
        directory = static_run.execute(self.ledger, self.sha)
        result = static_run.verify(directory)
        self.assertEqual(result["source_commit"], self.sha)
        self.assertEqual(result["input_kind"], "synthetic_fixture")
        self.assertEqual(result["sample"]["requests"], 1)
        self.assertIsNone(result["measured_billed"]["input_tokens"])

    def test_external_ledger_snapshot_is_explicit_not_falsely_committed(self):
        external = self.root / "_work/external.toml"
        external.parent.mkdir()
        external.write_bytes(self.ledger.read_bytes())
        directory = static_run.execute(external, self.sha)
        recorded = json.loads((directory / "provenance.json").read_bytes())
        self.assertEqual(recorded["ledger_origin"], "external_snapshot")
        self.assertIsNone(recorded["ledger_source_path"])
        static_run.verify(directory)

    def test_missing_wrong_and_dirty_commit_fail_before_adapter(self):
        with patch.object(static_run, "make_compressor") as compressor:
            for commit in (None, "HEAD", self.sha[:7], "b" * 40):
                with self.subTest(commit=commit), self.assertRaises(ValueError):
                    static_run.execute(self.ledger, commit)
            (self.root / "unclassified.txt").write_text("synthetic")
            with self.assertRaisesRegex(ValueError, "dirty"):
                static_run.execute(self.ledger, self.sha)
            compressor.assert_not_called()

    def test_verification_uses_recorded_commit_not_later_head(self):
        directory = static_run.execute(self.ledger, self.sha)
        (self.root / "src/later.py").write_text('"""Later synthetic source."""\n')
        self.git("add", "src/later.py")
        self.commit()
        self.assertNotEqual(self.git("rev-parse", "HEAD").strip(), self.sha)
        self.assertEqual(static_run.verify(directory)["source_commit"], self.sha)

    def test_snapshot_record_and_billed_tampering_fail(self):
        directory = static_run.execute(self.ledger, self.sha)
        summary_path = directory / "summary.json"
        original = summary_path.read_bytes()
        for difference in (-1, 1):
            changed = json.loads(original)
            changed["measured_local"]["after"]["message_content_tokens"] += difference
            summary_path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "aggregate differs"):
                static_run.verify(directory)
        summary_path.write_bytes(original)
        (directory / "source/run.py").write_text("tampered snapshot")
        with self.assertRaisesRegex(ValueError, "recorded commit"):
            static_run.verify(directory)

    def test_failed_or_incomplete_run_cannot_verify(self):
        with patch.object(static_run, "make_compressor", side_effect=CompressorError("synthetic failure")):
            with self.assertRaises(CompressorError):
                static_run.execute(self.ledger, self.sha)
        directory = next((self.root / "runs").iterdir())
        failure = json.loads((directory / "failure.json").read_bytes())
        self.assertEqual(failure["source_commit"], self.sha)
        self.assertIsNone(failure["measured_billed"]["input_tokens"])
        with self.assertRaisesRegex(ValueError, "failed or is incomplete"):
            static_run.verify(directory)


if __name__ == "__main__":
    unittest.main()
