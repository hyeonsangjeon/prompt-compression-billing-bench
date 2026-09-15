from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.screening_contract import load_screening_ledger
from src.screening_run import (
    _attempt_intervals,
    _classify_attempt,
    _reported_task_id,
    _stage_checkpoint,
    _verify_completed_batch,
    main,
    screening_harbor_config,
)


ROOT = Path(__file__).resolve().parents[1]


def quality_outcome(*, reward=None, valid=False, categories=(), failures=()):
    return {
        "native_reward": reward,
        "quality_valid": valid,
        "failure_categories": list(categories),
        "failures": list(failures),
    }


class ScreeningRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.attempt_id = "a" * 64
        self.attempt_directory = self.root / "attempt"
        self.attempt_directory.mkdir()
        (self.attempt_directory / "harbor.log").write_text("synthetic local test\n")
        self.attempt = {
            "attempt_id": self.attempt_id,
            "attempt_directory": self.attempt_directory,
        }
        self.recorder = SimpleNamespace(
            lock=nullcontext(),
            trials={self.attempt_id: {"failure": None}},
        )
        self.process = {
            "returncode": 0,
            "timed_out": False,
            "stopped_by_guard": False,
            "started_at": "2026-09-15T00:00:00+00:00",
            "finished_at": "2026-09-15T00:00:01+00:00",
        }

    def classify(self, outcome, *, events=None, replay=({"manifest_sha256": "b" * 64}, None), complete=True):
        if events is None:
            events = (
                {"event": "attempt_started", "trial_id": self.attempt_id, "request": 1, "attempt": 1},
                {"event": "http", "trial_id": self.attempt_id, "request": 1, "attempt": 1,
                 "status": 200, "calculated_cost_usd": 0.01},
            )
        metrics = {"measurement_complete": complete}
        with patch("src.screening_run._transport_events", return_value=list(events)), \
             patch("src.screening_run.collect_native_outcome", return_value=outcome), \
             patch("src.screening_run.collect_trial_metrics", return_value=metrics), \
             patch("src.screening_run._attempt_replay", return_value=replay):
            return _classify_attempt(self.attempt, self.process, self.recorder, self.root / "transport")

    def test_harbor_configuration_disables_hidden_retries_and_uses_preserving_environment(self):
        ledger = load_screening_ledger(ROOT / "ledgers/screening.template.toml")
        config = screening_harbor_config(
            ledger,
            [Path("/task/one"), Path("/task/two")],
            Path("/jobs"),
            "screening-test",
            "http://127.0.0.1:1/trial/v1",
            preserve_for_replay=True,
        )
        self.assertEqual(config["n_concurrent_trials"], 2)
        self.assertEqual(config["retry"]["max_retries"], 0)
        self.assertEqual(config["agents"][0]["kwargs"]["llm_kwargs"]["num_retries"], 0)
        self.assertEqual(
            config["environment"]["import_path"],
            "src.replay_environment:PreservingDockerEnvironment",
        )
        self.assertNotIn("type", config["environment"])

    def test_install_preflight_maps_harbor_source_prefix_to_inventory_task(self):
        expected = {"alpha-task", "beta-task"}
        self.assertEqual(_reported_task_id("alpha-task", expected), "alpha-task")
        self.assertEqual(_reported_task_id("terminal-bench/beta-task", expected), "beta-task")
        with self.assertRaisesRegex(ValueError, "unambiguous inventory task"):
            _reported_task_id("terminal-bench/unknown-task", expected)
        with self.assertRaisesRegex(ValueError, "unambiguous inventory task"):
            _reported_task_id("source/nested/task", {"task", "nested/task"})

    def test_classification_keeps_quality_and_technical_failures_separate(self):
        passed = self.classify(quality_outcome(reward=1, valid=True))
        self.assertEqual(passed["result"], "pass")

        wrong_format = self.classify(
            quality_outcome(reward=0, valid=True, categories=("wrong_format",))
        )
        self.assertEqual(wrong_format["result"], "wrong_format")

        missing = self.classify(
            quality_outcome(), events=(), replay=(None, "replay_manifest_missing_or_duplicated")
        )
        self.assertEqual(missing["result"], "setup_error")

        dispatched = [{"event": "attempt_started", "trial_id": self.attempt_id, "request": 1, "attempt": 1}]
        self.recorder.trials[self.attempt_id]["failure"] = {
            "reason": "TimeoutError", "details": {"message": "synthetic"},
        }
        network = self.classify(quality_outcome(), events=dispatched)
        self.assertEqual(network["result"], "network_error")
        self.assertTrue(network["provider_dispatched"])
        self.assertEqual(network["provider_cost"]["unknown_attempts"], 1)

        self.recorder.trials[self.attempt_id]["failure"] = {
            "reason": "ClientDisconnectedAfterDispatch",
            "details": {"error_type": "OSError", "message": "synthetic"},
        }
        disconnected = self.classify(quality_outcome(), events=dispatched)
        self.assertEqual(disconnected["result"], "network_error")

    def test_verifier_pass_without_provider_dispatch_is_a_preparation_error(self):
        classified = self.classify(quality_outcome(reward=1, valid=True), events=())
        self.assertEqual(classified["result"], "setup_error")
        self.assertFalse(classified["provider_dispatched"])

    def test_replay_mismatch_blocks_an_otherwise_valid_quality_result(self):
        classified = self.classify(
            quality_outcome(reward=1, valid=True),
            replay=({"manifest_sha256": "b" * 64}, "replay_mismatch_or_incomplete"),
        )
        self.assertEqual(classified["result"], "replay_mismatch")

    def test_active_vm_intervals_require_real_ordered_timestamps(self):
        attempt = {"attempt": {"attempt_id": self.attempt_id}, "process": self.process}
        intervals = _attempt_intervals([attempt])
        self.assertEqual(intervals[0]["finished_epoch"] - intervals[0]["started_epoch"], 1)

        missing = {"attempt": attempt["attempt"], "process": {}}
        with self.assertRaisesRegex(ValueError, "cannot be replaced with zero"):
            _attempt_intervals([missing])

        reversed_time = {
            "attempt": attempt["attempt"],
            "process": {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
            },
        }
        with self.assertRaisesRegex(ValueError, "finishes before"):
            _attempt_intervals([reversed_time])

    def test_repeated_checkpoints_replace_the_mutable_run_summary_atomically(self):
        class State:
            def backup(self, target):
                target.write_bytes(b"state")

            def summary(self):
                return {"completed_attempts": 0}

        class Spool:
            def __init__(self):
                self.items = []

            def report(self):
                return {"items": list(self.items)}

            def stage_directory(self, source, item_id, *, kind, metadata):
                self.items.append({"item_id": item_id})
                return {"item_id": item_id, "metadata": metadata}

        summary = {"status": "running"}
        spool = Spool()
        _stage_checkpoint(self.root, State(), summary, spool)
        _stage_checkpoint(self.root, State(), summary, spool)
        written = json.loads((self.root / "summary.json").read_bytes())
        self.assertEqual(written["checkpoint_sequence"], 2)
        self.assertEqual([item["item_id"] for item in spool.items], [
            "run-state-000001", "run-state-000002",
        ])

    def test_batch_verification_requires_quality_replay_timings_and_remote_hashes(self):
        attempt_id = self.attempt_id
        timing = {
            "task_process_wall_seconds": 10.0,
            "state_save_wall_seconds": 1.0,
            "first_verifier_wall_seconds": 2.0,
            "state_restore_wall_seconds": 3.0,
            "repeated_verifier_wall_seconds": 2.1,
            "restore_and_repeated_verifier_wall_seconds": 5.2,
        }
        finalized = [{"record": {
            "attempt_id": attempt_id,
            "task_id": "cancel-async-tasks",
            "classification": {
                "result": "wrong_answer",
                "replay_error": None,
                "replay_checks": {
                    "capture_status": "complete",
                    "state_restored": True,
                    "same_judgement": True,
                },
                "evidence_timing": timing,
            },
        }}]

        class Spool:
            def wait_for_upload(self, item_ids, wait_seconds):
                return {"status": "uploaded", "items": [{
                    "item_id": item_id,
                    "upload_state": "uploaded",
                    "remote_verified_at": "2026-09-15T00:00:00+00:00",
                    "upload_wall_seconds": 0.5,
                } for item_id in item_ids]}

        checked = _verify_completed_batch(
            finalized, {"item_id": "run-state-000001"}, Spool(), 30, 1
        )
        self.assertTrue(checked["additional_claims_allowed"])
        self.assertEqual(checked["attempts"][0]["result"], "wrong_answer")

        finalized[0]["record"]["classification"]["evidence_timing"]["state_save_wall_seconds"] = None
        blocked = _verify_completed_batch(
            finalized, {"item_id": "run-state-000001"}, Spool(), 30, 1
        )
        self.assertFalse(blocked["additional_claims_allowed"])
        self.assertEqual(blocked["attempts"][0]["missing_timing_fields"], ["state_save_wall_seconds"])

    def test_cli_routes_resume_without_treating_it_as_a_new_run(self):
        ledger = self.root / "ledger.toml"
        ledger.write_bytes((ROOT / "ledgers/screening.template.toml").read_bytes())
        resumed = self.root / "screening-existing"
        resumed.mkdir()
        (resumed / "summary.json").write_text(json.dumps({"status": "complete"}))
        with patch("src.screening_run.execute_screening", return_value=resumed) as execute, \
             patch("sys.stdout", new_callable=io.StringIO):
            result = main([
                str(ledger), "--source-commit", "a" * 40, "--resume", str(resumed),
            ])
        self.assertEqual(result, 0)
        self.assertEqual(execute.call_args.kwargs["resume_directory"], resumed.resolve())

    def test_cli_marks_single_task_diagnostic_separately(self):
        ledger = self.root / "ledger.toml"
        ledger.write_bytes((ROOT / "ledgers/screening.template.toml").read_bytes())
        output = self.root / "screening-diagnostic"
        output.mkdir()
        (output / "summary.json").write_text(json.dumps({"status": "complete"}))
        with patch("src.screening_run.execute_screening", return_value=output) as execute, \
             patch("sys.stdout", new_callable=io.StringIO):
            result = main([
                str(ledger), "--source-commit", "a" * 40,
                "--diagnose-task", "cancel-async-tasks",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(execute.call_args.kwargs["diagnostic_task_id"], "cancel-async-tasks")


if __name__ == "__main__":
    unittest.main()
