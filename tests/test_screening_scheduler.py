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

    def test_provider_request_and_attempt_ids_are_unique(self):
        trial = self.state.claim(1)[0]
        self.state.mark_provider_dispatch(trial["attempt_id"], "provider-request-1", 0.25,
                                          logical_request=1, http_attempt=1)
        self.assertEqual(self.state.provider_cost_state(), {
            "requests": 1, "known_cost_usd": 0.25, "unknown_requests": 0,
        })
        with self.assertRaises(Exception):
            self.state.mark_provider_dispatch(trial["attempt_id"], "provider-request-1", 0.25,
                                              logical_request=1, http_attempt=2)

    def test_unknown_provider_cost_remains_distinct_from_zero(self):
        trial = self.state.claim(1)[0]
        self.state.mark_provider_dispatch(
            trial["attempt_id"], None, None, True,
            logical_request=1, http_attempt=1,
        )
        self.assertEqual(self.state.provider_cost_state(), {
            "requests": 1, "known_cost_usd": 0, "unknown_requests": 1,
        })

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
