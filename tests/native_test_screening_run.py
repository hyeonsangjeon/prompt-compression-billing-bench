from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.screening_contract import load_screening_ledger
from src.screening_run import (
    _ActiveVmCostTracker,
    _attempt_intervals,
    _carried_continuation_records,
    _classify_attempt,
    _completed_attempt_evidence,
    _legacy_policy_transition,
    _merge_prior_retrieval,
    _no_limit_reuse_decision,
    _recovered_continuation_cost,
    _reported_task_id,
    _run_completion_driven,
    _stage_checkpoint,
    _verified_prior_blob_spool,
    _verify_completed_batch,
    main,
    screening_harbor_config,
)
from src.protection import digest
from src.screening_inventory import canonical_json
from src.screening_scheduler import ScreeningState, make_screening_manifest


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
            "elapsed_seconds": 1.0,
        }

    def classify(self, outcome, *, events=None, replay=({"manifest_sha256": "b" * 64}, None), complete=True):
        if events is None:
            events = (
                {"event": "attempt_started", "trial_id": self.attempt_id, "request": 1, "attempt": 1},
                {"event": "http", "trial_id": self.attempt_id, "request": 1, "attempt": 1,
                 "status": 200, "calculated_cost_usd": 0.01},
            )
            events[0]["input_cost_estimate_usd"] = 0.02
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

        dispatched = [{
            "event": "attempt_started", "trial_id": self.attempt_id,
            "request": 1, "attempt": 1, "input_cost_estimate_usd": 0.02,
        }]
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

        self.recorder.trials[self.attempt_id]["failure"] = {
            "reason": "ClientDisconnectedAfterDispatch",
            "details": {"error_type": "OSError", "message": "synthetic"},
        }

        timed_out = quality_outcome(
            reward=0,
            valid=True,
            categories=("timeout", "wrong_answer"),
            failures=(
                {"category": "timeout", "reason": "native_execution_timeout",
                 "exception_type": "AgentTimeoutError"},
                {"category": "wrong_answer", "reason": "native_assertion_failed"},
            ),
        )
        timeout = self.classify(timed_out, events=dispatched)
        self.assertEqual(timeout["result"], "timeout")
        self.assertEqual(timeout["request_failure"]["reason"], "ClientDisconnectedAfterDispatch")

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

    def test_explicit_provider_rejection_preserves_unexecuted_verifier_stages_as_not_applicable(self):
        events = [
            {
                "event": "attempt_started",
                "trial_id": self.attempt_id,
                "request": 1,
                "attempt": 1,
                "input_cost_estimate_usd": 0.075,
            },
            {
                "event": "http",
                "trial_id": self.attempt_id,
                "request": 1,
                "attempt": 1,
                "status": 400,
                "calculated_cost_usd": None,
            },
        ]
        self.recorder.trials[self.attempt_id]["failure"] = {
            "reason": "ValueError",
            "details": {"message": "Provider HTTP 400; no outer retry budget restart"},
        }
        replay = {
            "status": "complete",
            "capture_phase": "teardown_without_verifier",
            "capture_wall_seconds": 1.25,
            "manifest_sha256": "b" * 64,
        }
        classified = self.classify(
            quality_outcome(), events=events, replay=(replay, "replay_capture_phase_invalid"),
            complete=False,
        )

        self.assertEqual(classified["result"], "provider_error")
        self.assertEqual(
            classified["technical_exclusion_basis"]["kind"],
            "explicit_provider_rejection_before_first_verifier",
        )
        self.assertEqual(
            {
                name for name, status in classified["evidence_timing_status"].items()
                if status["status"] == "not_applicable"
            },
            {
                "first_verifier_wall_seconds",
                "state_restore_wall_seconds",
                "repeated_verifier_wall_seconds",
                "restore_and_repeated_verifier_wall_seconds",
            },
        )
        self.assertEqual(classified["provider_cost"]["known_cost_usd"], 0)
        self.assertEqual(
            classified["provider_cost"]["unconfirmed_cost_estimate_usd"], 0.075
        )

        ledger = load_screening_ledger(ROOT / "ledgers/screening.template.toml")
        finalized = [{"record": {
            "attempt_id": self.attempt_id,
            "task_id": "gpt2-codegolf",
            "classification": classified,
            "active_vm_cost": {"calculated_cost_usd": 0.02},
        }}]

        class Spool:
            def wait_for_upload(self, item_ids, wait_seconds):
                return {"status": "uploaded", "items": [{
                    "item_id": item_id,
                    "upload_state": "uploaded",
                    "remote_verified_at": "2026-09-15T00:00:00+00:00",
                    "upload_wall_seconds": 0.5,
                    "payload": {"bytes": 1000},
                    "manifest_bytes": 200,
                    "operations": {
                        "payload_write": {"started": 1, "succeeded": 1},
                        "manifest_write": {"started": 1, "succeeded": 1},
                        "payload_verify_read": {"started": 1, "succeeded": 1},
                        "manifest_verify_read": {"started": 1, "succeeded": 1},
                    },
                } for item_id in item_ids]}

        checked = _verify_completed_batch(
            finalized, {"item_id": "run-state-000001"}, Spool(), 30, 1, ledger
        )
        attempt = checked["attempts"][0]
        self.assertTrue(attempt["evidence_complete"])
        self.assertFalse(attempt["quality_result"])
        self.assertEqual(attempt["evidence_disposition"], "technical_exclusion_complete")
        self.assertTrue(checked["additional_claims_allowed"])

    def test_terminal_exit_preserves_narrow_pre_verifier_technical_exclusion(self):
        job = self.attempt_directory / "jobs" / self.attempt_id / "task"
        trace_directory = job / "agent" / "command-trace"
        trace_directory.mkdir(parents=True)
        result = {
            "exception_info": {
                "exception_type": "RuntimeError",
                "exception_message": (
                    "task__env: failed to send non-blocking keys: "
                    "command='tmux send-keys', return_code=1, "
                    "stdout='no server running on /tmp/tmux-0/default\\n'"
                ),
            },
        }
        (job / "result.json").write_text(json.dumps(result))
        trace = [
            {
                "event": "submission_started",
                "command_id": 19,
                "batch": 7,
                "keystrokes": "build; rc=$?; exit $rc\n",
                "command_sha256": digest(b"build; rc=$?; exit $rc\n"),
            },
            {
                "event": "submission_finished",
                "command_id": 19,
                "status": "accepted_by_terminal",
            },
            {
                "event": "submission_started",
                "command_id": 20,
                "batch": 7,
                "keystrokes": "echo unreachable\n",
                "command_sha256": digest(b"echo unreachable\n"),
            },
            {
                "event": "submission_finished",
                "command_id": 20,
                "status": "uncertain",
                "error_type": "RuntimeError",
            },
        ]
        (trace_directory / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in trace)
        )
        replay = {
            "status": "complete",
            "capture_phase": "teardown_without_verifier",
            "capture_wall_seconds": 1.25,
            "manifest_sha256": "b" * 64,
        }
        classified = self.classify(
            quality_outcome(),
            replay=(replay, "replay_capture_phase_invalid"),
            complete=False,
        )

        self.assertEqual(classified["result"], "replay_mismatch")
        self.assertEqual(
            classified["technical_exclusion_basis"]["kind"],
            "terminal_session_ended_before_first_verifier",
        )
        terminal_evidence = classified["technical_exclusion_basis"]["terminal_session_exit"]
        self.assertEqual(terminal_evidence["batch"], 7)
        self.assertEqual(terminal_evidence["failed_command_id"], 20)
        self.assertEqual(terminal_evidence["accepted_exit_command_ids"], [19])
        self.assertEqual(
            {
                name for name, status in classified["evidence_timing_status"].items()
                if status["status"] == "not_applicable"
            },
            {
                "first_verifier_wall_seconds",
                "state_restore_wall_seconds",
                "repeated_verifier_wall_seconds",
                "restore_and_repeated_verifier_wall_seconds",
            },
        )

        retrieval = {
            "upload_state": "uploaded",
            "remote_verified_at": "2026-09-15T00:00:00+00:00",
            "upload_wall_seconds": 0.5,
            "payload": {"bytes": 1000},
            "manifest_bytes": 200,
            "operations": {
                "payload_write": {"started": 1, "succeeded": 1},
                "manifest_write": {"started": 1, "succeeded": 1},
                "payload_verify_read": {"started": 1, "succeeded": 1},
                "manifest_verify_read": {"started": 1, "succeeded": 1},
            },
        }
        checked = _completed_attempt_evidence(
            {
                "attempt_id": self.attempt_id,
                "task_id": "make-doom-for-mips",
                "classification": classified,
                "active_vm_cost": {"calculated_cost_usd": 0.02},
            },
            retrieval,
            load_screening_ledger(ROOT / "ledgers/screening.template.toml"),
        )
        self.assertTrue(checked["terminal_session_exit_complete"])
        self.assertEqual(checked["evidence_disposition"], "technical_exclusion_complete")

        result["exception_info"]["exception_message"] = "unrelated runtime failure"
        (job / "result.json").write_text(json.dumps(result))
        unrelated = self.classify(
            quality_outcome(),
            replay=(replay, "replay_capture_phase_invalid"),
            complete=False,
        )
        self.assertIsNone(unrelated["technical_exclusion_basis"]["kind"])

    def test_carried_continuation_records_can_be_linked_once_into_the_next_run(self):
        inventory_payload = {
            "tasks": [
                {
                    "task_id": f"task-{index:03d}",
                    "exclusion": None,
                    "image": {
                        "pinned_reference": "owner/image@sha256:" + f"{index:064x}",
                    },
                }
                for index in range(89)
            ],
        }
        inventory = {
            **inventory_payload,
            "inventory_sha256": digest(canonical_json(inventory_payload)),
        }
        manifest = make_screening_manifest(inventory, "a" * 40, "screening-first")
        first_state = ScreeningState(self.root / "first.sqlite3")
        self.addCleanup(first_state.close)
        first_state.initialize(manifest)
        first_trial = next(
            trial for trial in manifest["trials"]
            if trial["task_id"] == "task-000" and trial["repetition"] == 1
        )
        record = {
            "prior_trial_id": "1" * 64,
            "prior_attempt_id": "2" * 64,
            "task_id": "task-000",
            "repetition": 1,
            "plan_index": first_trial["plan_index"],
            "result": "pass",
            "evidence_disposition": "quality_result_complete",
            "evidence_sha256": "3" * 64,
            "provider_request_count": 2,
            "provider_known_cost_usd": 0.2,
            "provider_unknown_requests": 0,
            "provider_unconfirmed_estimate_usd": 0,
            "active_vm_cost_usd": 0.1,
            "blob_network_cost_usd": 0.001,
            "direct_cost_usd": 0.301,
            "verifier_test_ids": [],
            "finished_at": "2026-09-15T00:00:00+00:00",
        }
        first_lineage = {
            "prior_run_id": "screening-prior",
            "prior_source_commit": "b" * 40,
            "prior_ledger_sha256": "c" * 64,
            "prior_inventory_sha256": inventory["inventory_sha256"],
            "prior_manifest_sha256": "d" * 64,
            "source_diff_sha256": "e" * 64,
            "prior_active_vm_cost_usd": 0.1,
            "prior_blob_network_cost_usd": 0.001,
            "prior_provider_known_cost_usd": 0.2,
            "prior_provider_unknown_requests": 0,
            "prior_provider_unconfirmed_estimate_usd": 0,
            "prior_provider_unknown_without_estimate": 0,
        }
        first_state.link_continuation(first_lineage, [record])

        carried = _carried_continuation_records(
            first_state.connection,
            {"records": [record]},
        )
        self.assertEqual(carried, [record])

        next_manifest = make_screening_manifest(inventory, "a" * 40, "screening-next")
        next_state = ScreeningState(self.root / "next.sqlite3")
        self.addCleanup(next_state.close)
        next_state.initialize(next_manifest)
        next_lineage = {**first_lineage, "prior_run_id": "screening-first"}
        next_state.link_continuation(next_lineage, carried)
        next_trial = next(
            trial for trial in next_state.claim(89) if trial["task_id"] == "task-000"
        )
        self.assertEqual(next_trial["task_id"], "task-000")
        self.assertEqual(next_trial["repetition"], 2)
        self.assertEqual(next_state.summary()["linked_completed_attempts"], 1)

    def test_read_only_blob_spool_recovers_only_hash_matched_verified_items(self):
        run_id = "screening-prior"
        source_commit = "a" * 40
        ledger_sha256 = "b" * 64
        spool = self.root / run_id
        spool.mkdir()
        client = SimpleNamespace(
            account_url="https://synthetic.blob.core.windows.net",
            container="runs",
        )
        setup = {"retrieval": {"client": client, "prefix": "screening"}}
        destination = {
            "account_url_sha256": digest(client.account_url.encode()),
            "container": "runs",
            "prefix": "screening",
        }
        item_ids = ["run-inputs", "c" * 64]
        for item_id in item_ids:
            item = spool / item_id
            item.mkdir()
            payload = item / "payload.tar"
            payload.write_bytes((item_id + "-evidence").encode())
            remote = f"screening/{source_commit}/{run_id}/none/{item_id}"
            operations = {
                name: {"started": 1, "succeeded": 1}
                for name in (
                    "payload_write", "manifest_write",
                    "payload_verify_read", "manifest_verify_read",
                )
            }
            state = {
                "kind": "terminal_bench_screening_attempt",
                "item_id": item_id,
                "metadata": {},
                "destination": destination,
                "payload": {
                    "name": "payload.tar",
                    "bytes": payload.stat().st_size,
                    "sha256": digest(payload.read_bytes()),
                    "blob": remote + "/payload.tar",
                },
                "manifest_blob": remote + "/manifest.json",
                "manifest_uploaded_last": True,
                "upload_state": "uploaded",
                "attempts": 1,
                "first_attempt_at": "2026-09-16T00:00:00+00:00",
                "last_attempt_at": "2026-09-16T00:00:00+00:00",
                "last_error_category": None,
                "uploaded_at": "2026-09-16T00:00:01+00:00",
                "payload_etag": "payload-etag",
                "manifest_etag": "manifest-etag",
                "remote_verified_at": "2026-09-16T00:00:02+00:00",
                "payload_verify_request_id": "payload-request",
                "manifest_verify_request_id": "manifest-request",
                "manifest_bytes": 100,
                "operations": operations,
                "upload_wall_seconds": 2.0,
                "run_id": run_id,
                "source_commit": source_commit,
                "ledger_sha256": ledger_sha256,
                "condition": "none",
            }
            (item / "state.json").write_text(json.dumps(state))

        report, spool_recovery = _verified_prior_blob_spool(
            spool,
            setup,
            run_id=run_id,
            source_commit=source_commit,
            ledger_sha256=ledger_sha256,
        )
        persisted = deepcopy(report)
        persisted["items"] = persisted["items"][:1]
        merged, merge_recovery = _merge_prior_retrieval(persisted, report)
        self.assertEqual(len(merged["items"]), 2)
        self.assertEqual(spool_recovery["item_count"], 2)
        self.assertEqual(merge_recovery["recovered_item_count"], 1)

        changed = deepcopy(persisted)
        changed["items"][0]["metadata"] = {"changed": True}
        with self.assertRaisesRegex(ValueError, "changed a persisted"):
            _merge_prior_retrieval(changed, report)

        state_path = spool / item_ids[1] / "state.json"
        state = json.loads(state_path.read_text())
        state["remote_verified_at"] = None
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "completed remote verification"):
            _verified_prior_blob_spool(
                spool,
                setup,
                run_id=run_id,
                source_commit=source_commit,
                ledger_sha256=ledger_sha256,
            )

    def test_recovered_continuation_cost_keeps_unknown_provider_cost_distinct(self):
        ledger = load_screening_ledger(ROOT / "ledgers/screening.template.toml")
        retrieval_item = {
            "upload_state": "uploaded",
            "remote_verified_at": "2026-09-16T00:00:00+00:00",
            "payload": {"bytes": 1000},
            "manifest_bytes": 100,
            "operations": {
                name: {"started": 1, "succeeded": 1}
                for name in (
                    "payload_write", "manifest_write",
                    "payload_verify_read", "manifest_verify_read",
                )
            },
        }
        values, record = _recovered_continuation_cost(
            {
                "requests": 2,
                "known_cost_usd": 0.5,
                "unknown_requests": 1,
                "unconfirmed_input_cost_estimate_usd": 0.3,
                "unknown_requests_without_input_estimate": 0,
            },
            {
                "runs": 1,
                "active_vm_cost_usd": 0.2,
                "blob_network_cost_usd": 0.001,
                "provider_known_cost_usd": 0.4,
                "provider_unknown_requests": 1,
                "provider_unconfirmed_estimate_usd": 0,
                "provider_unknown_without_estimate": 1,
            },
            [0.1],
            {"items": [retrieval_item]},
            ledger,
        )
        self.assertEqual(values["prior_provider_unknown_requests"], 2)
        self.assertEqual(values["prior_provider_unknown_without_estimate"], 1)
        self.assertAlmostEqual(values["prior_provider_known_cost_usd"], 0.9)
        self.assertAlmostEqual(values["prior_active_vm_cost_usd"], 0.3)
        self.assertEqual(record["local_provider_request_count"], 2)

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

    def test_incremental_vm_allocations_reconcile_after_open_slots_are_refilled(self):
        tracker = _ActiveVmCostTracker(0.36)

        def timestamp(seconds):
            return (
                datetime(2026, 9, 15, tzinfo=timezone.utc) + timedelta(seconds=seconds)
            ).isoformat()

        def finish(attempt_id, started, finished):
            tracker.mark_finished(attempt_id, {
                "started_at": timestamp(started),
                "finished_at": timestamp(finished),
            })

        tracker.mark_started("a", timestamp(0))
        tracker.mark_started("b", timestamp(0))
        finish("a", 0, 20)
        allocation_a = tracker.allocation_for("a")
        tracker.mark_started("c", timestamp(21))
        finish("b", 0, 30)
        allocation_b = tracker.allocation_for("b")
        finish("c", 21, 40)
        allocation_c = tracker.allocation_for("c")

        self.assertAlmostEqual(allocation_a["allocated_active_seconds"], 10)
        self.assertAlmostEqual(allocation_b["allocated_active_seconds"], 15.5)
        self.assertAlmostEqual(allocation_c["allocated_active_seconds"], 14.5)
        self.assertAlmostEqual(
            sum(record["calculated_cost_usd"] for record in (
                allocation_a, allocation_b, allocation_c
            )),
            0.004,
        )

    def test_completion_driven_execution_refills_a_slot_before_slow_work_finishes(self):
        items = iter(("slow", "fast", "replacement"))
        replacement_started = threading.Event()
        slow_finished = threading.Event()
        started = []

        def run_item(item):
            started.append(item)
            if item == "slow":
                replacement_started.wait(2)
                slow_finished.set()
            elif item == "replacement":
                replacement_started.set()
            return item

        accepting = _run_completion_driven(
            2,
            lambda: next(items, None),
            run_item,
            lambda _result: (True, False),
        )

        self.assertTrue(accepting)
        self.assertTrue(replacement_started.is_set())
        self.assertTrue(slow_finished.is_set())
        self.assertEqual(started[:2], ["slow", "fast"])
        self.assertEqual(started[2], "replacement")

    def test_completion_driven_execution_stops_new_claims_but_drains_active_work(self):
        items = iter(("slow", "incomplete", "must-not-start"))
        release_slow = threading.Event()
        started = []
        completed = []

        def run_item(item):
            started.append(item)
            if item == "slow":
                release_slow.wait(2)
            return item

        def complete_item(item):
            completed.append(item)
            if item == "incomplete":
                release_slow.set()
                return False, True
            return True, False

        accepting = _run_completion_driven(
            2,
            lambda: next(items, None),
            run_item,
            complete_item,
        )

        self.assertFalse(accepting)
        self.assertEqual(set(started), {"slow", "incomplete"})
        self.assertEqual(set(completed), {"slow", "incomplete"})

    def test_incomplete_evidence_holds_only_its_worker_slot(self):
        items = iter(("incomplete", "slow", "replacement"))
        release_slow = threading.Event()
        started = []

        def run_item(item):
            started.append(item)
            if item == "slow":
                release_slow.wait(2)
            return item

        def complete_item(item):
            if item == "incomplete":
                release_slow.set()
                return False, False
            return True, False

        accepting = _run_completion_driven(
            2,
            lambda: next(items, None),
            run_item,
            complete_item,
        )

        self.assertTrue(accepting)
        self.assertEqual(started[:2], ["incomplete", "slow"])
        self.assertEqual(started[2], "replacement")

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

    def test_batch_verification_requires_replay_timings_and_remote_hashes(self):
        attempt_id = self.attempt_id
        ledger = load_screening_ledger(ROOT / "ledgers/screening.template.toml")
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
                    "capture_phase": "after_tests_upload_before_verifier",
                    "state_restored": True,
                    "same_judgement": True,
                },
                "evidence_timing": timing,
                "provider_cost": {
                    "http_attempts": 1,
                    "calculated_cost_usd": 0.1,
                    "known_cost_usd": 0.1,
                    "unknown_attempts": 0,
                    "unconfirmed_cost_estimate_usd": 0,
                    "unknown_attempts_without_estimate": 0,
                    "requests": [{}],
                },
            },
            "active_vm_cost": {"calculated_cost_usd": 0.2},
        }}]

        class Spool:
            def wait_for_upload(self, item_ids, wait_seconds):
                return {"status": "uploaded", "items": [{
                    "item_id": item_id,
                    "upload_state": "uploaded",
                    "remote_verified_at": "2026-09-15T00:00:00+00:00",
                    "upload_wall_seconds": 0.5,
                    "payload": {"bytes": 1000},
                    "manifest_bytes": 200,
                    "operations": {
                        "payload_write": {"started": 1, "succeeded": 1},
                        "manifest_write": {"started": 1, "succeeded": 1},
                        "payload_verify_read": {"started": 1, "succeeded": 1},
                        "manifest_verify_read": {"started": 1, "succeeded": 1},
                    },
                } for item_id in item_ids]}

        checked = _verify_completed_batch(
            finalized, {"item_id": "run-state-000001"}, Spool(), 30, 1, ledger
        )
        self.assertTrue(checked["additional_claims_allowed"])
        self.assertEqual(checked["attempts"][0]["result"], "wrong_answer")
        self.assertTrue(checked["attempts"][0]["evidence_complete"])

        finalized[0]["record"]["classification"]["result"] = "timeout"
        complete_timeout = _verify_completed_batch(
            finalized, {"item_id": "run-state-000001"}, Spool(), 30, 1, ledger
        )
        self.assertFalse(complete_timeout["attempts"][0]["quality_result"])
        self.assertTrue(complete_timeout["attempts"][0]["evidence_complete"])
        self.assertTrue(complete_timeout["additional_claims_allowed"])

        finalized[0]["record"]["classification"]["evidence_timing"]["state_save_wall_seconds"] = None
        blocked = _verify_completed_batch(
            finalized, {"item_id": "run-state-000001"}, Spool(), 30, 1, ledger
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

    def test_legacy_limit_transition_reuses_only_results_unaffected_by_removed_limits(self):
        current = load_screening_ledger(ROOT / "ledgers/screening.template.toml")
        legacy = deepcopy(current)
        legacy["schema_version"] = 1
        legacy["model"]["max_completion_tokens"] = 2048
        legacy["runner"].update({
            "max_turns": 60,
            "agent_timeout_seconds": 900,
            "verifier_timeout_seconds": 900,
            "setup_timeout_seconds": 600,
            "trial_timeout_seconds": 2400,
        })
        legacy["limits"] = {
            "api_cost_usd": 300,
            "deadline_utc": "2026-09-17T00:00:00+00:00",
            "max_wall_seconds": 161928,
            "max_calls_per_trial": 60,
            "request_timeout_seconds": 300,
            "max_request_bytes": 8_000_000,
            "max_attempts_per_call": 3,
            "max_retry_wait_seconds": 120,
            "protocol_token_allowance": 4096,
        }
        removed = _legacy_policy_transition(legacy, current)
        self.assertEqual(removed, {"max_completion_tokens": 2048, "max_calls_per_trial": 60})

        unaffected = _no_limit_reuse_decision({
            "result": "pass",
            "provider_requests": [{"logical_request": 1, "finish_reason": "stop", "tokens": {"output_tokens": 8}}],
        }, removed)
        self.assertTrue(unaffected["reusable"])
        call_limited = _no_limit_reuse_decision({
            "result": "wrong_answer",
            "provider_requests": [{"logical_request": 60, "finish_reason": "stop", "tokens": {"output_tokens": 8}}],
        }, removed)
        self.assertFalse(call_limited["reusable"])
        output_limited = _no_limit_reuse_decision({
            "result": "wrong_answer",
            "provider_requests": [{"logical_request": 1, "finish_reason": "length", "tokens": {"output_tokens": 2048}}],
        }, removed)
        self.assertFalse(output_limited["reusable"])

    def test_cli_routes_read_only_continuation_without_a_budget_record(self):
        ledger = self.root / "ledger.toml"
        ledger.write_bytes((ROOT / "ledgers/screening.template.toml").read_bytes())
        prior = self.root / "screening-prior"
        prior.mkdir()
        prior_spool = self.root / "prior-spool"
        prior_spool.mkdir()
        output = self.root / "screening-continuation"
        output.mkdir()
        (output / "summary.json").write_text(json.dumps({"status": "complete"}))
        with patch("src.screening_run.execute_screening", return_value=output) as execute, \
             patch("sys.stdout", new_callable=io.StringIO):
            result = main([
                str(ledger), "--source-commit", "a" * 40,
                "--continue-from", str(prior),
                "--continue-blob-spool", str(prior_spool),
            ])
        self.assertEqual(result, 0)
        self.assertEqual(execute.call_args.kwargs["continuation_directory"], prior.resolve())
        self.assertEqual(
            execute.call_args.kwargs["continuation_spool_directory"], prior_spool.resolve()
        )


if __name__ == "__main__":
    unittest.main()
