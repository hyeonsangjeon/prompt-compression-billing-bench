from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.screening_inventory import canonical_json, digest
from src.screening_scheduler import ScreeningState, make_screening_manifest, verify_screening_manifest


def inventory():
    tasks = [{"task_id": f"task-{index:03d}", "exclusion": None,
              "image": {"pinned_reference": "owner/image@sha256:" + f"{index:064x}"}}
             for index in range(89)]
    payload = {"tasks": tasks}
    return {**payload, "inventory_sha256": digest(canonical_json(payload))}


class ScreeningSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.inventory = inventory()
        self.manifest = make_screening_manifest(self.inventory, "a" * 40, "screening-test")
        self.temporary = tempfile.TemporaryDirectory()
        self.state = ScreeningState(Path(self.temporary.name) / "state.sqlite3")
        self.state.initialize(self.manifest)

    def tearDown(self):
        self.state.close()
        self.temporary.cleanup()

    def test_manifest_has_1780_unique_trials_and_is_reproducible(self):
        self.assertEqual(len(self.manifest["trials"]), 1780)
        self.assertEqual(len({trial["trial_id"] for trial in self.manifest["trials"]}), 1780)
        self.assertEqual(self.manifest, make_screening_manifest(self.inventory, "a" * 40, "screening-test"))
        self.assertIs(verify_screening_manifest(self.manifest, self.inventory), self.manifest)

        compressed = make_screening_manifest(
            self.inventory, "a" * 40, "screening-compressed", condition="squeez"
        )
        self.assertEqual(compressed["condition"], "squeez")
        self.assertTrue(all(trial["condition"] == "squeez" for trial in compressed["trials"]))
        self.assertTrue(
            set(trial["trial_id"] for trial in compressed["trials"]).isdisjoint(
                trial["trial_id"] for trial in self.manifest["trials"]
            )
        )

    def test_claim_never_runs_two_trials_for_one_task(self):
        first = self.state.claim(8)
        second = self.state.claim(8)
        tasks = [trial["task_id"] for trial in first + second]
        self.assertEqual(len(tasks), len(set(tasks)))

    def test_single_claim_deduplicates_task_when_only_one_task_is_available(self):
        selected = self.manifest["trials"][0]["task_id"]
        self.state.connection.execute(
            "UPDATE tasks SET state='ineligible' WHERE task_id != ?", (selected,)
        )
        claimed = self.state.claim(8)
        self.assertEqual([trial["task_id"] for trial in claimed], [selected])

    def test_diagnostic_claim_selects_only_the_requested_task(self):
        selected = self.manifest["trials"][17]["task_id"]
        claimed = self.state.claim(1, task_id=selected)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["task_id"], selected)
        self.assertEqual(claimed[0]["repetition"], 1)

    def test_third_quality_failure_cancels_only_unstarted_trials(self):
        target = None
        for _ in range(3):
            claimed = self.state.claim(89)
            current = next(trial for trial in claimed if target is None or trial["task_id"] == target)
            target = current["task_id"]
            for trial in claimed:
                self.state.mark_attempt_runtime(
                    trial["attempt_id"], process_id=100 + trial["repetition"],
                    artifact_manifest_hash="a" * 64,
                    container_instance_id=trial["attempt_id"] + "-container",
                    workspace_instance_id=trial["attempt_id"] + "-workspace",
                )
                result = "wrong_answer" if trial["task_id"] == target else "pass"
                self.state.complete_attempt(trial["attempt_id"], result, provider_dispatched=True,
                                            evidence_sha256="e" * 64, cost_usd=0.1)
        row = self.state.connection.execute("SELECT * FROM tasks WHERE task_id=?", (target,)).fetchone()
        self.assertEqual((row["state"], row["quality_failures"]), ("ineligible", 3))
        self.assertEqual(self.state.connection.execute(
            "SELECT COUNT(*) FROM trials WHERE task_id=? AND state='cancelled_by_futility'", (target,)
        ).fetchone()[0], 17)

    def test_preparation_error_retries_once_with_same_trial_and_new_attempt(self):
        trial = self.state.claim(1)[0]
        self.state.mark_attempt_runtime(
            trial["attempt_id"], process_id=None, artifact_manifest_hash="a" * 64,
            container_instance_id="container-1", workspace_instance_id="workspace-1",
        )
        self.state.mark_attempt_runtime(
            trial["attempt_id"], process_id=101, artifact_manifest_hash="a" * 64,
            container_instance_id="container-1", workspace_instance_id="workspace-1",
        )
        self.state.complete_attempt(trial["attempt_id"], "setup_error", provider_dispatched=False,
                                    evidence_sha256="e" * 64, cost_usd=0)
        retried = self.state.claim(1)[0]
        self.assertEqual(retried["trial_id"], trial["trial_id"])
        self.assertEqual(retried["attempt_number"], 2)
        self.assertNotEqual(retried["attempt_id"], trial["attempt_id"])
        self.state.mark_attempt_runtime(
            retried["attempt_id"], process_id=102, artifact_manifest_hash="a" * 64,
            container_instance_id="container-2", workspace_instance_id="workspace-2",
        )
        self.state.complete_attempt(retried["attempt_id"], "setup_error", provider_dispatched=False,
                                    evidence_sha256="f" * 64, cost_usd=0)
        task = self.state.connection.execute("SELECT state,reason FROM tasks WHERE task_id=?", (trial["task_id"],)).fetchone()
        self.assertEqual(tuple(task), ("ineligible", "setup_error"))

    def test_safety_stops_are_technical_and_do_not_increment_quality_counters(self):
        for result in ("budget_stopped", "censored"):
            trial = self.state.claim(1)[0]
            self.state.mark_attempt_runtime(
                trial["attempt_id"], process_id=101,
                artifact_manifest_hash="a" * 64,
                container_instance_id=trial["attempt_id"] + "-container",
                workspace_instance_id=trial["attempt_id"] + "-workspace",
            )
            self.state.complete_attempt(
                trial["attempt_id"], result, provider_dispatched=True,
                evidence_sha256="e" * 64, cost_usd=0.25,
            )
            task = self.state.connection.execute(
                "SELECT state,reason,valid_results,passes,quality_failures "
                "FROM tasks WHERE task_id=?",
                (trial["task_id"],),
            ).fetchone()
            self.assertEqual(tuple(task), ("ineligible", result, 0, 0, 0))
            attempt = self.state.connection.execute(
                "SELECT error_category,cost_usd FROM attempts WHERE attempt_id=?",
                (trial["attempt_id"],),
            ).fetchone()
            self.assertEqual(tuple(attempt), (result, 0.25))

    def test_vm_deallocation_preserves_first_attempt_and_schedules_one_fresh_attempt(self):
        trial = self.state.claim(1)[0]
        self.state.mark_attempt_runtime(
            trial["attempt_id"], process_id=101, artifact_manifest_hash="a" * 64,
            container_instance_id="container-1", workspace_instance_id="workspace-1",
        )
        self.state.pause_interrupted()
        self.state.retry_paused_after_infrastructure_interruption(
            trial["attempt_id"], provider_dispatched=True, evidence_sha256="e" * 64,
            cost_usd=0.25, reason="vm_deallocated",
        )
        first = self.state.connection.execute(
            "SELECT state,error_category,cost_usd FROM attempts WHERE attempt_id=?",
            (trial["attempt_id"],),
        ).fetchone()
        self.assertEqual(tuple(first), ("completed", "infrastructure_interruption", 0.25))
        task = self.state.connection.execute(
            "SELECT state,valid_results,passes,quality_failures FROM tasks WHERE task_id=?",
            (trial["task_id"],),
        ).fetchone()
        self.assertEqual(tuple(task), ("eligible_for_screening", 0, 0, 0))
        retried = self.state.claim(1)[0]
        self.assertEqual((retried["trial_id"], retried["attempt_number"]), (trial["trial_id"], 2))
        self.state.mark_attempt_runtime(
            retried["attempt_id"], process_id=102, artifact_manifest_hash="a" * 64,
            container_instance_id="container-2", workspace_instance_id="workspace-2",
        )
        with self.assertRaisesRegex(ValueError, "paused first attempt"):
            self.state.retry_paused_after_infrastructure_interruption(
                trial["attempt_id"], provider_dispatched=True, evidence_sha256="f" * 64,
                cost_usd=0.25, reason="vm_deallocated",
            )

    def test_provider_request_and_attempt_ids_are_unique(self):
        trial = self.state.claim(1)[0]
        self.state.mark_provider_dispatch(trial["attempt_id"], "provider-request-1", 0.25,
                                          logical_request=1, http_attempt=1,
                                          input_cost_estimate_usd=0.3)
        self.assertEqual(self.state.provider_cost_state(), {
            "requests": 1, "known_cost_usd": 0.25, "unknown_requests": 0,
            "unconfirmed_input_cost_estimate_usd": 0,
            "unknown_requests_without_input_estimate": 0,
        })
        with self.assertRaises(Exception):
            self.state.mark_provider_dispatch(trial["attempt_id"], "provider-request-1", 0.25,
                                              logical_request=1, http_attempt=2,
                                              input_cost_estimate_usd=0.3)

    def test_unknown_provider_cost_remains_distinct_from_zero(self):
        trial = self.state.claim(1)[0]
        self.state.mark_provider_dispatch(
            trial["attempt_id"], None, None, True,
            logical_request=1, http_attempt=1,
            input_cost_estimate_usd=0.4,
        )
        self.assertEqual(self.state.provider_cost_state(), {
            "requests": 1, "known_cost_usd": 0, "unknown_requests": 1,
            "unconfirmed_input_cost_estimate_usd": 0.4,
            "unknown_requests_without_input_estimate": 0,
        })

    def test_read_only_continuation_counts_trials_and_costs_once_without_budget_blocking(self):
        by_task = {
            trial["task_id"]: trial
            for trial in self.manifest["trials"]
            if trial["repetition"] == 1
        }
        passed_task, rejected_task = sorted(by_task)[:2]
        lineage = {
            "prior_run_id": "screening-prior",
            "prior_source_commit": "b" * 40,
            "prior_ledger_sha256": "c" * 64,
            "prior_inventory_sha256": self.inventory["inventory_sha256"],
            "prior_manifest_sha256": "d" * 64,
            "source_diff_sha256": "e" * 64,
            "prior_active_vm_cost_usd": 0.3,
            "prior_blob_network_cost_usd": 0.002,
            "prior_provider_known_cost_usd": 1.2,
            "prior_provider_unknown_requests": 1,
            "prior_provider_unconfirmed_estimate_usd": 0.4,
            "prior_provider_unknown_without_estimate": 0,
        }
        records = [
            {
                "prior_trial_id": "1" * 64,
                "prior_attempt_id": "2" * 64,
                "task_id": passed_task,
                "repetition": 1,
                "plan_index": by_task[passed_task]["plan_index"],
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
            },
            {
                "prior_trial_id": "4" * 64,
                "prior_attempt_id": "5" * 64,
                "task_id": rejected_task,
                "repetition": 1,
                "plan_index": by_task[rejected_task]["plan_index"],
                "result": "provider_error",
                "evidence_disposition": "technical_exclusion_complete",
                "evidence_sha256": "6" * 64,
                "provider_request_count": 1,
                "provider_known_cost_usd": 0,
                "provider_unknown_requests": 1,
                "provider_unconfirmed_estimate_usd": 0.4,
                "active_vm_cost_usd": 0.2,
                "blob_network_cost_usd": 0.001,
                "direct_cost_usd": None,
                "verifier_test_ids": [],
                "finished_at": "2026-09-15T00:00:01+00:00",
            },
        ]

        self.state.link_continuation(lineage, records)

        summary = self.state.summary()
        self.assertEqual(summary["completed_attempts"], 2)
        self.assertEqual(summary["linked_completed_attempts"], 2)
        self.assertEqual(self.state.local_provider_cost_state(), {
            "requests": 0,
            "known_cost_usd": 0,
            "unknown_requests": 0,
            "unconfirmed_input_cost_estimate_usd": 0,
            "unknown_requests_without_input_estimate": 0,
        })
        provider = self.state.provider_cost_state()
        self.assertEqual({key: provider[key] for key in (
            "requests", "known_cost_usd", "unknown_requests",
            "unconfirmed_input_cost_estimate_usd", "unknown_requests_without_input_estimate",
        )}, {
            "requests": 3,
            "known_cost_usd": 0.2,
            "unknown_requests": 1,
            "unconfirmed_input_cost_estimate_usd": 0.4,
            "unknown_requests_without_input_estimate": 0,
        })
        all_cost = self.state.all_provider_cost_state()
        self.assertIsNone(all_cost["requests"])
        self.assertEqual(all_cost["request_count_scope"], "unavailable_for_linked_legacy_runs")
        self.assertEqual(all_cost["prior_known_cost_usd"], 1.2)
        self.assertEqual(all_cost["prior_unknown_requests"], 1)
        self.assertEqual(all_cost["known_cost_usd"], 1.2)
        self.assertEqual(all_cost["unconfirmed_input_cost_estimate_usd"], 0.4)
        passed = self.state.connection.execute(
            "SELECT valid_results,passes,quality_failures FROM tasks WHERE task_id=?",
            (passed_task,),
        ).fetchone()
        rejected = self.state.connection.execute(
            "SELECT state,reason FROM tasks WHERE task_id=?", (rejected_task,)
        ).fetchone()
        self.assertEqual(tuple(passed), (1, 1, 0))
        self.assertEqual(tuple(rejected), ("ineligible", "provider_error"))

        claimed = self.state.claim(89)
        claimed_by_task = {trial["task_id"]: trial for trial in claimed}
        self.assertEqual(claimed_by_task[passed_task]["repetition"], 2)
        self.assertNotIn(rejected_task, claimed_by_task)
        self.assertFalse({trial["trial_id"] for trial in claimed} & {
            by_task[passed_task]["trial_id"], by_task[rejected_task]["trial_id"],
        })
        current = claimed_by_task[passed_task]
        self.state.mark_provider_dispatch(
            current["attempt_id"], "provider-request-current", 0.1,
            logical_request=1, http_attempt=1, input_cost_estimate_usd=0.2,
        )
        self.assertEqual(self.state.local_provider_cost_state()["known_cost_usd"], 0.1)
        self.assertAlmostEqual(self.state.provider_cost_state()["known_cost_usd"], 0.3)
        self.assertAlmostEqual(self.state.all_provider_cost_state()["known_cost_usd"], 1.3)
        with self.assertRaisesRegex(ValueError, "already linked"):
            self.state.link_continuation(lineage, records)

    def test_resume_pauses_unknown_running_attempt_without_duplicate(self):
        trial = self.state.claim(1)[0]
        self.state.mark_attempt_runtime(
            trial["attempt_id"], process_id=101, artifact_manifest_hash="a" * 64,
            container_instance_id="container-1", workspace_instance_id="workspace-1",
        )
        self.assertEqual(self.state.pause_interrupted(), 1)
        resumed = self.state.claim(89)
        self.assertNotIn(trial["task_id"], {item["task_id"] for item in resumed})
        row = self.state.connection.execute("SELECT state FROM trials WHERE trial_id=?", (trial["trial_id"],)).fetchone()
        self.assertEqual(row[0], "paused")
        self.assertEqual(self.state.paused_attempts()[0]["attempt_id"], trial["attempt_id"])
        self.state.resolve_paused_attempt(
            trial["attempt_id"], "evidence_missing", provider_dispatched=False,
            evidence_sha256="e" * 64, cost_usd=0,
        )
        self.assertEqual(self.state.paused_attempts(), [])

    def test_retry_rejects_reused_runtime_or_changed_artifact(self):
        trial = self.state.claim(1)[0]
        self.state.mark_attempt_runtime(
            trial["attempt_id"], process_id=101, artifact_manifest_hash="a" * 64,
            container_instance_id="container-1", workspace_instance_id="workspace-1",
        )
        self.state.complete_attempt(trial["attempt_id"], "image_error", provider_dispatched=False,
                                    evidence_sha256="e" * 64, cost_usd=0)
        retried = self.state.claim(1)[0]
        for artifact, container, workspace in (
            ("b" * 64, "container-2", "workspace-2"),
            ("a" * 64, "container-1", "workspace-2"),
            ("a" * 64, "container-2", "workspace-1"),
        ):
            with self.subTest(artifact=artifact, container=container, workspace=workspace), self.assertRaises(ValueError):
                self.state.mark_attempt_runtime(
                    retried["attempt_id"], process_id=102, artifact_manifest_hash=artifact,
                    container_instance_id=container, workspace_instance_id=workspace,
                )


if __name__ == "__main__":
    unittest.main()
