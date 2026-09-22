from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from native_helpers import FixtureEncoder, ledger_fixture_document, request_fixture, response_fixture
from src.cache_reuse import (
    CACHE_THRESHOLD_TOKENS,
    SCREENING_REQUEST_ORDINALS,
    STRUCTURAL_SCREENING_TOKENS,
    eligibility_decision_sha256,
    summarize_native_bundle,
)
from src.execution_safety import safety_policy_record
from src.native_contract import TASKS
from src.native_run import (
    _cache_bundle_context,
    execute_native,
    main,
    runtime_environment,
    supervise,
    verify_cache_bundle_run,
    verify_native_run,
)
from src.protection import canonical, digest


ROOT = Path(__file__).resolve().parents[1]


def synthetic_eligibility_contract():
    rows = []
    for task_id in TASKS:
        for request_ordinal in SCREENING_REQUEST_ORDINALS:
            expected_tokens = STRUCTURAL_SCREENING_TOKENS[task_id]
            eligibility = (
                "eligible"
                if expected_tokens >= CACHE_THRESHOLD_TOKENS
                else "not_applicable"
            )
            rows.append({
                "task_id": task_id,
                "request_ordinal": request_ordinal,
                "local_screening_prefix_tokens": [
                    expected_tokens,
                    expected_tokens,
                ],
                "stable_serialized_prefix_bytes": 1,
                "capture_serialized_prefix_sha256": ["c" * 64, "c" * 64],
                "capture_request_sha256": ["d" * 64, "e" * 64],
                "cache_eligibility": eligibility,
                "execution_bundle_included": True,
                "primary_cache_estimand_included": eligibility == "eligible",
            })
    contract = {
        "schema_version": 1,
        "kind": "cache_reuse_structural_eligibility_decision",
        "decision_version": 2,
        "decided_at_utc": "2026-09-22T00:00:00Z",
        "screening_source_commit": "a" * 40,
        "screening_evidence_sha256": "b" * 64,
        "screening_launches": 2,
        "provider_cache_threshold_tokens": 1_024,
        "screening_token_unit": "local_stable_message_content_prefix_tokens_not_provider_billed_usage",
        "selection_timing": "after_zero_call_structural_screening_before_provider_inference",
        "primary_estimand": "same_task_condition_reuse_effect_structurally_eligible_tasks_only",
        "ineligible_cache_result": "not_applicable",
        "full_bundle_estimand": "descriptive_provider_usage_computed_cost_quality_all_five_tasks",
        "external_validity_limit": "eligibility_screening_favors_cache_capable_inputs_no_generalization",
        "task_denominators": {"execution": 5, "primary_eligible": 2, "not_applicable": 3},
        "raw_content_stored": False,
        "provider_model_api_calls": 0,
        "rows": rows,
        "decision_sha256": "0" * 64,
    }
    contract["decision_sha256"] = eligibility_decision_sha256(contract)
    return contract


class NativeRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ledger, self.ledger_bytes = ledger_fixture_document()
        self.ledger_path = self.root / "ledger.toml"
        self.ledger_path.write_bytes(self.ledger_bytes)
        self.sent = []
        self.supervised = []
        self.active_supervisors = 0
        self.maximum_active_supervisors = 0
        self.activity_lock = threading.Lock()

    def run_fixture(self, *, evidence_kind="synthetic_validation", broken=False, pass_counts=None, cache_bundle=False):
        """Mock all execution dependencies; temporary native-shaped records are never evidence."""
        if cache_bundle:
            self.ledger["runner"]["concurrency"] = 1
            self.ledger_bytes = self.ledger_bytes.replace(b"concurrency = 8", b"concurrency = 1")
            self.ledger_path.write_bytes(self.ledger_bytes)
        def sender(body):
            self.sent.append(body)
            return 200, response_fixture(), {}

        sender.endpoint = "https://synthetic.openai.azure.com/openai/v1"
        files = {"task.toml": b'[environment]\ndocker_image = "synthetic:unused"\n', "instruction.md": b"Synthetic fixture",
                 "tests/test.sh": b"synthetic, never executed", "tests/test_outputs.py": b"synthetic, never imported"}
        provenance = {
            "source_commit": "a" * 40,
            "ledger_sha256": digest(self.ledger_bytes),
            "source_files": {"schemas/synthetic.json": "f" * 64},
        }
        retrieval_client = SimpleNamespace(
            account_url="https://synthetic.blob.core.windows.net", container="runs", timeout_seconds=1,
        )
        setup = {"provenance": provenance, "snapshots": {"ledger.toml": self.ledger_bytes}, "encoder": FixtureEncoder(),
                 "tasks": {task: deepcopy(files) for task in TASKS}, "benchmark_root": str(self.root / "benchmark"),
                 "sender": sender, "queue_path": self.root / "shared-queue.json", "runtime_versions": {"kind": "synthetic"},
                 "queue_limits": (10_000, 1_000_000),
                 "retrieval": {"client": retrieval_client, "container": "runs", "prefix": "runs"},
                 "reporting_target": 1_789_578_340.0,
                 "harbor_limit_policy": {"agent_time_limit_seconds": None},
                 "safety_policy": safety_policy_record(self.ledger, applied=True),
                 "evidence_kind": evidence_kind}

        class SyntheticRetrieval:
            def __init__(self):
                self.items = []

            def stage_run_snapshot(self, directory, repetition, trials):
                self.items.append({
                    "kind": "native_repetition_snapshot", "item_id": f"repetition-{repetition:03d}",
                    "metadata": {"repetition": repetition}, "payload": {
                        "name": "payload.tar", "bytes": 1, "sha256": "b" * 64,
                        "blob": f"runs/synthetic/repetition-{repetition:03d}/payload.tar",
                    }, "manifest_blob": f"runs/synthetic/repetition-{repetition:03d}/manifest.json",
                    "manifest_uploaded_last": True, "upload_state": "uploaded", "attempts": 1,
                    "first_attempt_at": "synthetic", "last_attempt_at": "synthetic",
                    "last_error_category": None, "uploaded_at": "synthetic",
                    "payload_etag": "synthetic", "manifest_etag": "synthetic",
                })

            def finish(self, wait_seconds):
                return {
                    "schema_version": 1, "kind": "native_blob_retrieval",
                    "account_url_sha256": "c" * 64, "container": "runs", "prefix": "runs",
                    "run_id": next(iter((self.root if hasattr(self, "root") else [])), None),
                    "source_commit": "a" * 40, "ledger_sha256": provenance["ledger_sha256"],
                    "condition": "none", "upload_state": "uploaded" if self.items else "no_complete_repetitions",
                    "items": self.items, "nas_read_verification": "pending_external",
                    "credentials_recorded": False,
                }

        synthetic_retrieval = SyntheticRetrieval()

        def synthetic_supervisor(command, log, recorder, environment, *, trial_id=None):
            self.supervised.append(command)
            self.assertIsNotNone(trial_id)
            with self.activity_lock:
                self.active_supervisors += 1
                self.maximum_active_supervisors = max(self.maximum_active_supervisors, self.active_supervisors)
            try:
                time.sleep(0.02)
                trial_id = log.parent.name
                log.write_text("Synthetic supervisor: no Harbor process, container or model started.\n")
                if broken:
                    raise OSError("Synthetic startup failure")
                recorder.complete(trial_id, canonical(request_fixture()))
                recorder.event({"event": "response_delivered", "trial_id": trial_id})
                task = recorder.trials[trial_id]["task"]
                repetition = int(trial_id[1:3])
                passed = (pass_counts or [3] * 20)[repetition - 1]
                reward = int(TASKS.index(task) >= len(TASKS) - passed)
                native = log.parents[2] / "jobs" / trial_id / "synthetic-trial"
                (native / "verifier").mkdir(parents=True)
                (native / "agent/command-trace").mkdir(parents=True)
                (native / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": reward}}}))
                (native / "verifier/reward.txt").write_text(str(reward))
                (native / "verifier/ctrf.json").write_text(json.dumps({"results": {"summary": {"tests": 1}, "tests": [
                    {"name": "test_synthetic", "status": "passed" if reward else "failed", "trace": None if reward else "E AssertionError: synthetic"}
                ]}}))
                (native / "agent/trajectory.json").write_text(json.dumps({"steps": [{"step_id": 1, "source": "agent"}]}))
                (native / "agent/command-trace/events.jsonl").write_text("")
                return {
                    "returncode": 0,
                    "timed_out": False,
                    "stopped_by_guard": False,
                    "safety_stop": None,
                }
            finally:
                with self.activity_lock:
                    self.active_supervisors -= 1

        def make_retrieval(_settings, run_id, source_commit, ledger_sha256, condition):
            synthetic_retrieval.root = [run_id]
            synthetic_retrieval.condition = condition
            return synthetic_retrieval

        original_finish = synthetic_retrieval.finish

        def finish(wait_seconds):
            result = original_finish(wait_seconds)
            result["run_id"] = synthetic_retrieval.root[0]
            result["condition"] = synthetic_retrieval.condition
            return result

        synthetic_retrieval.finish = finish
        with patch("src.native_run.ROOT", self.root), patch("src.native_run.preflight", return_value=setup), \
             patch("src.native_run.supervise", synthetic_supervisor), \
             patch("src.native_run.apply_verifier_revision", side_effect=lambda _task, source, _specs: (deepcopy(source), {"revision": "synthetic", "modified": False})), \
             patch("src.native_run.make_blob_spool", side_effect=make_retrieval):
            keywords = {}
            if cache_bundle:
                eligibility_contract = synthetic_eligibility_contract()
                context = {
                    "cycle_id": "cycle-01", "bundle_id": "cycle-01-none-reuse-0",
                    "condition": "none", "reuse_level": 0, "eligible_predecessor_count": 0,
                    "cache_ledger_sha256": "b" * 64, "native_ledger_sha256": "a" * 64,
                    "runtime_facts_sha256": "c" * 64,
                    "isolation_evidence_sha256": "d" * 64,
                }

                def observe(**arguments):
                    task_id = arguments["task"]
                    eligibility = next(
                        row["cache_eligibility"]
                        for row in eligibility_contract["rows"]
                        if row["task_id"] == task_id and row["request_ordinal"] == 1
                    )
                    return {
                        "cycle_id": context["cycle_id"], "condition": context["condition"],
                        "reuse_level": context["reuse_level"], "eligible_predecessor_count": 0,
                        "serialized_prefix_sha256": digest(arguments["serialized"]),
                        "request_sha256": digest(arguments["serialized"]),
                        "structural_cache_eligibility": eligibility,
                        "eligibility_decision_sha256": eligibility_contract["decision_sha256"],
                    }

                keywords = {"cache_context": context, "request_observer": observe}
            directory = execute_native(self.ledger_path, self.ledger, "a" * 40, "none", **keywords)
        return directory, provenance

    def test_shared_transport_full_driver_collects_ten_five_task_repetitions(self):
        directory, _provenance = self.run_fixture()
        summary = json.loads((directory / "summary.json").read_bytes())
        self.assertEqual(summary["kind"], "synthetic_validation")
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(len(summary["trials"]), 50)
        self.assertEqual(len(self.sent), 50)
        self.assertEqual(summary["baseline_decision"]["suite_pass_counts"], [3] * 10)
        self.assertEqual(summary["concurrency"], 8)
        self.assertEqual(summary["deployment_limits"]["rpm_env"], "PROVIDER_RPM_LIMIT")
        self.assertFalse(summary["deployment_limits"]["values_recorded"])
        self.assertEqual(summary["compressor_metrics"]["trials"], 50)
        self.assertEqual(summary["compressor_metrics"]["calls"], 0)
        self.assertEqual(summary["timing_metrics"]["trials"], 50)
        self.assertEqual(summary["timing_metrics"]["provider_http_attempts"], 50)
        self.assertIsNone(summary["timing_metrics"]["model_seconds"])
        execution = json.loads((directory / "execution.json").read_bytes())
        self.assertEqual(execution["concurrency_unit"], "simultaneous_native_trial_processes")
        self.assertGreater(self.maximum_active_supervisors, 1)
        self.assertLessEqual(self.maximum_active_supervisors, 8)
        self.assertTrue(all(trial["metrics"]["measurement_complete"] for trial in summary["trials"]))
        self.assertEqual(summary["trials"][0]["native_outcome"]["primary_failure"], "wrong_answer")
        self.assertEqual(summary["interim_decision"]["decision"], "continue_to_10")
        self.assertEqual(summary["retrieval"]["upload_state"], "uploaded")
        self.assertEqual(len(summary["retrieval"]["items"]), 10)
        self.assertTrue(all(trial["metrics"]["total_model_calls"] == 1 for trial in summary["trials"]))
        with self.assertRaisesRegex(ValueError, "Synthetic"):
            verify_native_run(directory)

    def test_artifact_and_repetition_tampering_fail_verification(self):
        directory, provenance = self.run_fixture(evidence_kind="native_measurement")
        with patch("src.native_run.verify_snapshot", return_value=provenance):
            summary = verify_native_run(directory)
            path = directory / "summary.json"
            original = path.read_bytes()
            summary["repetitions"][0][TASKS[0]] = 1
            path.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "repetitions differ"):
                verify_native_run(directory)
            path.write_bytes(original)
            extra = directory / "unlisted.txt"
            extra.write_text("synthetic extra artifact")
            with self.assertRaisesRegex(ValueError, "inventory"):
                verify_native_run(directory)
            extra.unlink()
            record = directory / summary["trials"][0]["record_path"]
            record.write_text("{}")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                verify_native_run(directory)

    def test_cache_bundle_profile_is_serial_and_preserves_request_context(self):
        directory, provenance = self.run_fixture(evidence_kind="native_measurement", cache_bundle=True)
        summary = json.loads((directory / "summary.json").read_bytes())
        self.assertEqual(summary["execution_profile"], "cache_reuse_bundle")
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["concurrency"], 1)
        self.assertEqual(len(summary["trials"]), 5)
        self.assertEqual(len(self.sent), 5)
        self.assertEqual(self.maximum_active_supervisors, 1)
        with patch("src.native_run.verify_snapshot", return_value=provenance):
            checked = verify_cache_bundle_run(directory)
            bundle = summarize_native_bundle(
                directory,
                {
                    "cycle_id": "cycle-01", "bundle_id": "cycle-01-none-reuse-0",
                    "condition": "none", "reuse_level": 0,
                    "eligible_predecessor_count_required": 0,
                },
                {
                    "status": "verified",
                    "input_per_million_usd": 1,
                    "cached_input_per_million_usd": 0.1,
                    "output_per_million_usd": 2,
                    "source_reference_sha256": "f" * 64,
                    "checked_at_utc": "2026-09-20T00:00:00Z",
                },
                cache_ledger_sha256="e" * 64,
                runtime_facts_sha256="d" * 64,
                eligibility_contract=synthetic_eligibility_contract(),
                parent_run_id="parent-run",
            )
        self.assertEqual(checked["cache_reuse"]["eligible_predecessor_count"], 0)
        self.assertEqual(bundle["task_denominator"], 5)
        self.assertEqual(bundle["primary_cache_task_denominator"], 2)
        self.assertEqual(bundle["not_applicable_cache_task_denominator"], 3)
        self.assertEqual(len(bundle["observations"]), 5)
        self.assertTrue(all(row["flags"]["measured"] for row in bundle["observations"]))
        self.assertTrue(all(row["invoice"]["status"] == "not_measured" for row in bundle["observations"]))
        self.assertTrue(all(row["runtime_facts_sha256"] == "d" * 64 for row in bundle["observations"]))

    def test_cache_bundle_context_requires_every_ledger_hash(self):
        context = {
            "cycle_id": "cycle-01",
            "bundle_id": "cycle-01-none-reuse-0",
            "condition": "none",
            "reuse_level": 0,
            "eligible_predecessor_count": 0,
            "cache_ledger_sha256": "a" * 64,
            "native_ledger_sha256": "b" * 64,
            "runtime_facts_sha256": "c" * 64,
            "isolation_evidence_sha256": "d" * 64,
        }
        ledger = deepcopy(self.ledger)
        ledger["runner"]["concurrency"] = 1
        self.assertEqual(_cache_bundle_context(context, "none", ledger), context)
        changed = deepcopy(context)
        del changed["native_ledger_sha256"]
        with self.assertRaisesRegex(ValueError, "fields differ"):
            _cache_bundle_context(changed, "none", ledger)
        changed = deepcopy(context)
        changed["native_ledger_sha256"] = "not-a-hash"
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            _cache_bundle_context(changed, "none", ledger)

    def test_startup_failure_still_records_one_invalid_task_and_stops(self):
        directory, _provenance = self.run_fixture(broken=True)
        summary = json.loads((directory / "summary.json").read_bytes())
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(len(summary["trials"]), 8)
        self.assertEqual(len(self.supervised), 8)
        self.assertEqual(self.sent, [])
        self.assertTrue(all(not trial["native_outcome"]["quality_valid"] for trial in summary["trials"]))
        self.assertTrue(all(not trial["metrics"]["measurement_complete"] for trial in summary["trials"]))
        self.assertTrue(all(trial["native_outcome"]["native_reward"] is None for trial in summary["trials"]))
        self.assertEqual(summary["repetitions"], [])

    def test_large_first_five_range_stops_before_sixth_repetition(self):
        directory, _provenance = self.run_fixture(pass_counts=[1, 3, 1, 3, 1])
        summary = json.loads((directory / "summary.json").read_bytes())
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(len(summary["trials"]), 25)
        self.assertEqual(summary["interim_decision"]["range_width"], 2)
        self.assertEqual(summary["interim_decision"]["decision"], "stop_for_design_audit")
        self.assertNotIn("baseline_decision", summary)
        self.assertEqual(summary["stop_reason"]["reason"], "InterimBaselineVariability")
        self.assertEqual(len(summary["retrieval"]["items"]), 5)

    def test_compressor_close_failure_stops_and_records_the_run(self):
        def fail_close():
            raise RuntimeError("synthetic close failure")

        compressor = SimpleNamespace(metadata={"name": "synthetic"}, close=fail_close)
        with patch("src.native_run.make_compressor", return_value=compressor):
            directory, _provenance = self.run_fixture()
        summary = json.loads((directory / "summary.json").read_bytes())
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(summary["compressor_close_error"]["type"], "RuntimeError")
        self.assertEqual(summary["stop_reason"]["reason"], "CompressorCloseError")

    def test_cli_is_no_call_by_default_and_unapproved_execute_fails(self):
        with patch("src.native_run.preflight", return_value={"provenance": {"source_commit": "a" * 40}}), patch("src.native_run.execute_native") as execute, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main([str(self.ledger_path), "--source-commit", "a" * 40, "--check"]), 0)
            execute.assert_not_called()
        with patch("src.native_run.supervise") as execute, patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(main([str(self.ledger_path), "--source-commit", "a" * 40, "--execute"]), 2)
            execute.assert_not_called()
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            main([str(self.ledger_path), "--check"])

    def test_child_environment_has_no_provider_credentials(self):
        with patch.dict("os.environ", {"AZURE_API_KEY": "not-forwarded", "OPENAI_API_KEY": "not-forwarded", "FOUNDRY_ENDPOINT": "not-forwarded"}):
            environment = runtime_environment("local-proxy-only")
        self.assertEqual(environment["OPENAI_API_KEY"], "local-proxy-only")
        self.assertNotIn("AZURE_API_KEY", environment)
        self.assertNotIn("FOUNDRY_ENDPOINT", environment)

    def test_supervisor_without_trial_scope_still_honors_an_explicit_run_stop(self):
        completed = SimpleNamespace(
            stopped=threading.Event(), check=lambda: None, stop=lambda _reason: None,
        )
        result = supervise(
            [sys.executable, "-c", "import time; time.sleep(0.05)"],
            self.root / "completed.log", completed, runtime_environment("synthetic"),
        )
        self.assertEqual(result["returncode"], 0)
        self.assertFalse(result["timed_out"])
        self.assertFalse(result["stopped_by_guard"])

        stopped = threading.Event()
        guarded = SimpleNamespace(
            stopped=stopped, check=lambda: None, stop=lambda _reason: stopped.set(),
        )
        timer = threading.Timer(0.2, stopped.set)
        timer.start()
        self.addCleanup(timer.cancel)
        result = supervise(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            self.root / "guarded.log", guarded, runtime_environment("synthetic"),
        )
        self.assertIsNotNone(result["returncode"])
        self.assertTrue(result["stopped_by_guard"])
        self.assertFalse(result["timed_out"])
        self.assertLess(result["elapsed_seconds"], 5)

    def test_supervisor_reports_the_started_at_used_in_its_result(self):
        recorder = SimpleNamespace(
            stopped=threading.Event(), check=lambda: None, stop=lambda _reason: None,
        )
        timing = []
        result = supervise(
            [sys.executable, "-c", "pass"],
            self.root / "timing.log",
            recorder,
            runtime_environment("synthetic"),
            on_timing_start=timing.append,
        )
        self.assertEqual(timing, [result["started_at"]])

    def test_supervisor_stops_child_when_runtime_identity_recording_fails(self):
        stopped = threading.Event()
        recorder = SimpleNamespace(
            stopped=stopped,
            check=lambda: None,
            stop=lambda _reason: stopped.set(),
        )
        with self.assertRaisesRegex(RuntimeError, "synthetic state failure"):
            supervise(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                self.root / "callback-failure.log",
                recorder,
                runtime_environment("synthetic"),
                on_start=lambda _process_id: (_ for _ in ()).throw(RuntimeError("synthetic state failure")),
            )
        self.assertTrue(stopped.is_set())


if __name__ == "__main__":
    unittest.main()
