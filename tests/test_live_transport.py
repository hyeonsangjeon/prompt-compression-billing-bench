from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from native_helpers import FixtureEncoder, ImmediateQueue, ledger_fixture, request_fixture, response_fixture
from src.compressors import NoOpCompressor
from src.live_transport import (
    DeploymentQueue,
    FoundrySender,
    LiveRecorder,
    TrialRequestBlocked,
    provider_timing,
    start_live_proxy,
)
from src.protection import FrozenRequestGuard, ProtectionViolation, canonical
from src.task_metrics import read_events


class LiveTransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ledger = ledger_fixture()
        self.sent = []
        self.queue = ImmediateQueue()

        def sender(body):
            self.sent.append(body)
            return 200, response_fixture(), {}

        self.recorder = LiveRecorder(self.root / "transport", self.ledger, "a" * 40,
                                     NoOpCompressor({"options": {}}, self.root), FixtureEncoder(), self.queue,
                                     sender, evidence_kind="synthetic_validation")
        self.recorder.register_trial("trial-one", "synthetic-task", 1)

    def test_final_wire_bytes_are_checked_and_recorded_before_dispatch(self):
        status, _body = self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(status, 200)
        self.assertEqual(len(self.sent), 1)
        after = self.root / "transport/request-00001/after.json"
        self.assertEqual(after.read_bytes(), self.sent[0])
        events = read_events(self.root / "transport/events.jsonl")
        self.assertTrue(all(event["source_commit"] == "a" * 40 for event in events))
        response = next(event for event in events if event["event"] == "http")
        self.assertEqual(response["tokens"]["input_tokens"], 10)
        self.assertEqual(response["tokens"]["output_tokens"], 5)
        self.assertEqual(response["tokens"]["cached_input_tokens"], 0)
        self.assertIsNone(response["transport_seconds"])
        self.assertIsNone(response["model_seconds"])
        self.assertGreaterEqual(response["client_http_seconds"], 0)
        self.assertTrue(self.queue.calls)

    def test_candidate_compression_records_hashes_and_timing_before_dispatch(self):
        assistant = json.dumps({"commands": [{"keystrokes": "ls -la /logs\n", "duration": 1}]})
        self.recorder.sender = lambda body: (self.sent.append(body), (200, response_fixture(assistant), {}))[1]
        self.recorder.complete("trial-one", canonical(request_fixture()))
        content = "root@123456789abc:/app# ls -la /logs\na.log\nb.log\nroot@123456789abc:/app# "
        payload = request_fixture()
        payload["messages"] = [{"role": "assistant", "content": assistant}, {"role": "user", "content": content}]
        self.recorder.complete("trial-one", canonical(payload))
        event = next(
            row for row in read_events(self.root / "transport/events.jsonl")
            if row["event"] == "compressor_completed"
        )
        self.assertEqual(event["before_sha256"], event["after_sha256"])
        self.assertFalse(event["changed"])
        self.assertGreaterEqual(event["compressor_wall_seconds"], event["adapter_execution_seconds"])
        self.assertEqual(event["audit"]["source"], event["audit"]["worker_input"])
        self.assertEqual(event["audit"]["worker_id"], None)
        local = json.loads((self.root / "transport/request-00002/local-input.json").read_text())
        self.assertEqual(local["candidates"][0]["compression"]["before_sha256"], event["before_sha256"])

    def test_provider_checkpoint_separates_model_and_transport_without_inventing_missing_values(self):
        response = {"usage": {"latency_checkpoint": {
            "engine_ttlt_ms": 500, "service_ttlt_ms": 800, "pre_inference_ms": 100,
        }}}
        timing = provider_timing(response, 1.25)
        self.assertEqual(timing["model_seconds"], 0.5)
        self.assertAlmostEqual(timing["transport_seconds"], 0.45)
        self.assertEqual(timing["provider_service_seconds"], 0.8)
        self.assertEqual(timing["pre_inference_seconds"], 0.1)
        self.assertEqual(timing["timing_status"], "complete")
        missing = provider_timing({"usage": {}}, 1.25)
        self.assertIsNone(missing["model_seconds"])
        self.assertIsNone(missing["transport_seconds"])

    def test_protected_mutation_blocks_this_and_all_later_trials(self):
        def corrupt(payload):
            payload = deepcopy(payload)
            payload["messages"][0]["content"] += " corruption"
            return canonical(payload)

        self.recorder.serialize = corrupt
        with self.assertRaises(ProtectionViolation):
            self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(self.sent, [])
        self.assertTrue(self.recorder.stopped.is_set())
        details = self.recorder.failure["details"]
        self.assertEqual(details["changes"][0]["path"], ["messages", 0, "content"])
        self.assertTrue(details["changes"][0]["affected_segments"])
        with self.assertRaises(ProtectionViolation):
            self.recorder.register_trial("trial-two", "next-task", 1)
        with self.assertRaises(ProtectionViolation):
            self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(self.sent, [])

    def test_verification_is_repeated_inside_queue_before_actual_dispatch(self):
        with patch.object(FrozenRequestGuard, "verify_serialized", side_effect=[{}, ProtectionViolation("synthetic queued violation")]):
            with self.assertRaises(ProtectionViolation):
                self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(len(self.queue.calls), 1)
        self.assertEqual(self.sent, [])
        self.assertTrue(self.recorder.stopped.is_set())

    def test_finished_trial_cannot_dispatch_late_requests(self):
        self.recorder.close_trial("trial-one")
        with self.assertRaises(ProtectionViolation):
            self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(self.sent, [])

    def test_duplicate_json_keys_and_settings_mismatch_never_reach_provider(self):
        source = canonical(request_fixture())
        for malformed in (b'{"model":"wrong",' + source[1:], canonical({**request_fixture(), "temperature": 1})):
            with self.assertRaises((ProtectionViolation, ValueError)):
                self.recorder.complete("trial-one", malformed)
        self.assertEqual(self.sent, [])

    def test_queued_request_is_rejected_after_an_earlier_violation(self):
        entered, release = threading.Event(), threading.Event()
        failures = []

        def corrupt(payload):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("Test synchronization timed out")
            return canonical({**payload, "temperature": 1})

        def call():
            try:
                self.recorder.complete("trial-one", canonical(request_fixture()))
            except Exception as error:
                failures.append(type(error).__name__)

        self.recorder.serialize = corrupt
        first = threading.Thread(target=call)
        second = threading.Thread(target=call)
        first.start()
        self.assertTrue(entered.wait(2))
        second.start()
        release.set()
        first.join(3)
        second.join(3)
        self.assertEqual(len(failures), 2)
        self.assertEqual(self.sent, [])

    def test_independent_trials_can_dispatch_concurrently(self):
        barrier = threading.Barrier(2)
        failures = []

        def sender(body):
            self.sent.append(body)
            barrier.wait(timeout=2)
            return 200, response_fixture(), {}

        self.recorder.sender = sender
        self.recorder.register_trial("trial-two", "synthetic-task", 1)

        def call(trial_id):
            try:
                self.recorder.complete(trial_id, canonical(request_fixture()))
            except Exception as error:
                failures.append(type(error).__name__)

        threads = [threading.Thread(target=call, args=(trial_id,)) for trial_id in ("trial-one", "trial-two")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        self.assertEqual(failures, [])
        self.assertEqual(len(self.sent), 2)

    def test_bounded_429_retries_count_every_attempt_and_record_known_cost(self):
        responses = iter([(429, b'{"error":"synthetic limit"}', {"Retry-After": "0"}),
                          (200, response_fixture(), {})])
        self.recorder.sender = lambda body: (self.sent.append(body), next(responses))[1]
        self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(len(self.sent), 2)
        events = read_events(self.root / "transport/events.jsonl")
        self.assertEqual(sum(event["event"] == "attempt_started" for event in events), 2)
        self.assertEqual(self.queue.cooldowns, [0])
        self.assertEqual(self.recorder.known_provider_cost_usd, 0.00002)

    def test_unknown_usage_or_ambiguous_network_failure_stops_without_outer_retry(self):
        def failed_sender(body):
            self.sent.append(body)
            raise TimeoutError("synthetic network timeout")

        self.recorder.sender = failed_sender
        with self.assertRaises(TimeoutError):
            self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(len(self.sent), 1)
        response = next(event for event in read_events(self.root / "transport/events.jsonl") if event["event"] == "http")
        self.assertIsNone(response["status"])
        self.assertTrue(response["billing_unknown"])
        self.assertTrue(self.recorder.stopped.is_set())

    def test_trial_scoped_network_failure_does_not_stop_other_screening_trial(self):
        recorder = LiveRecorder(
            self.root / "screening-transport", self.ledger, "a" * 40,
            NoOpCompressor({"options": {}}, self.root), FixtureEncoder(), self.queue,
            lambda _body: (_ for _ in ()).throw(TimeoutError("synthetic network timeout")),
            evidence_kind="synthetic_validation", request_error_scope="trial",
        )
        recorder.register_trial("trial-one", "task-one", 1)
        recorder.register_trial("trial-two", "task-two", 1)
        with self.assertRaises(TimeoutError):
            recorder.complete("trial-one", canonical(request_fixture()))
        self.assertFalse(recorder.stopped.is_set())
        with self.assertRaises(TrialRequestBlocked):
            recorder.complete("trial-one", canonical(request_fixture()))
        recorder.sender = lambda _body: (200, response_fixture(), {})
        self.assertEqual(recorder.complete("trial-two", canonical(request_fixture()))[0], 200)

    def test_trial_scoped_delivery_failure_does_not_stop_other_screening_trial(self):
        recorder = LiveRecorder(
            self.root / "screening-delivery", self.ledger, "a" * 40,
            NoOpCompressor({"options": {}}, self.root), FixtureEncoder(), self.queue,
            lambda _body: (200, response_fixture(), {}),
            evidence_kind="synthetic_validation", request_error_scope="trial",
        )
        recorder.register_trial("trial-one", "task-one", 1)
        recorder.register_trial("trial-two", "task-two", 1)
        recorder.record_delivery_failure("trial-one", OSError("synthetic client disconnect"))
        self.assertFalse(recorder.stopped.is_set())
        with self.assertRaises(TrialRequestBlocked):
            recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(recorder.complete("trial-two", canonical(request_fixture()))[0], 200)

    def test_run_scoped_delivery_failure_stops_subsequent_requests(self):
        self.recorder.record_delivery_failure("trial-one", OSError("synthetic client disconnect"))
        self.assertTrue(self.recorder.stopped.is_set())
        self.assertEqual(self.recorder.failure["reason"], "ClientDisconnectedAfterDispatch")
        with self.assertRaises(ProtectionViolation):
            self.recorder.complete("trial-one", canonical(request_fixture()))

    def test_trial_scope_keeps_protection_failure_run_wide(self):
        self.recorder.request_error_scope = "trial"
        self.recorder.serialize = lambda payload: canonical({**payload, "temperature": 1})
        with self.assertRaises(ProtectionViolation):
            self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertTrue(self.recorder.stopped.is_set())

    def test_loopback_proxy_uses_the_same_guarded_recorder(self):
        server = start_live_proxy(self.recorder, "synthetic-local-key")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        endpoint = f"http://127.0.0.1:{server.server_port}/trial-one/v1/chat/completions"
        request = urllib.request.Request(endpoint, data=canonical(request_fixture()), headers={"Authorization": "Bearer synthetic-local-key"})
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 200)
        self.recorder.serialize = lambda payload: canonical({**payload, "temperature": 1})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(error.exception.code, 503)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(len(self.sent), 1)

    def test_missing_usage_never_becomes_zero(self):
        response = json.loads(response_fixture())
        del response["usage"]
        self.recorder.sender = lambda body: (200, json.dumps(response).encode(), {})
        with self.assertRaisesRegex(ValueError, "usage"):
            self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertTrue(self.recorder.stopped.is_set())

    def test_sixty_first_call_is_dispatched_without_local_cost_or_call_stop(self):
        for _ in range(61):
            status, _body = self.recorder.complete("trial-one", canonical(request_fixture()))
            self.assertEqual(status, 200)
        self.assertEqual(len(self.sent), 61)
        self.assertEqual(self.recorder.trials["trial-one"]["calls"], 61)
        self.assertIsNone(self.recorder.trials["trial-one"]["failure"])
        self.assertNotIn("max_completion_tokens", json.loads(self.sent[-1]))


class QueueTests(unittest.TestCase):
    def test_same_deployment_queue_is_shared_and_survives_restarts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queue.json"
            queue = DeploymentQueue(path, "deployment", 5, 1000)
            second = DeploymentQueue(path, "deployment", 5, 1000)
            queue.reserve(50, threading.Event())
            second.reserve(60, threading.Event())
            self.assertEqual(len(json.loads(path.read_text())["reservations"]), 2)
            second.close()
            queue.close()
            reopened = DeploymentQueue(path, "deployment", 5, 1000)
            self.assertEqual(len(reopened.reservations), 2)
            reopened.close()
            with self.assertRaises(ValueError):
                DeploymentQueue(path, "different-deployment", 5, 1000)

    def test_independent_queue_instances_do_not_lose_concurrent_reservations(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queue.json"
            queues = [DeploymentQueue(path, "deployment", 8, 1000) for _ in range(8)]
            self.addCleanup(lambda: [queue.close() for queue in queues])
            barrier = threading.Barrier(8)
            failures = []

            def reserve(queue):
                try:
                    barrier.wait(timeout=2)
                    queue.reserve(50, threading.Event())
                except Exception as error:
                    failures.append(error)

            threads = [threading.Thread(target=reserve, args=(queue,)) for queue in queues]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(3)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(failures, [])
            self.assertEqual(len(json.loads(path.read_text())["reservations"]), 8)

    def test_separate_processes_share_one_persisted_rate_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queue.json"
            program = (
                "from pathlib import Path; import sys,threading; "
                "from src.live_transport import DeploymentQueue; "
                "queue=DeploymentQueue(Path(sys.argv[1]),'deployment',8,1000); "
                "queue.reserve(50,threading.Event()); queue.close()"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", program, str(path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(8)
            ]
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual((process.returncode, stdout, stderr), (0, "", ""))
            self.assertEqual(len(json.loads(path.read_text())["reservations"]), 8)

    def test_oversized_reservation_fails_and_explicit_stop_interrupts_rate_wait(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = DeploymentQueue(Path(temporary) / "queue", "deployment", 1, 100)
            self.addCleanup(queue.close)
            with self.assertRaises(ValueError):
                queue.reserve(101, threading.Event())
            queue.reserve(50, threading.Event())
            stopped = threading.Event()
            timer = threading.Timer(0.1, stopped.set)
            timer.start()
            self.addCleanup(timer.cancel)
            with self.assertRaisesRegex(ProtectionViolation, "stopped"):
                queue.reserve(50, stopped)

    def test_concurrent_reservations_are_persisted_without_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queue"
            queue = DeploymentQueue(path, "deployment", 8, 1000)
            self.addCleanup(queue.close)
            barrier = threading.Barrier(8)

            def reserve():
                barrier.wait(timeout=2)
                queue.reserve(50, threading.Event())

            threads = [threading.Thread(target=reserve) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(3)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(queue.reservations), 8)
            self.assertEqual(len(json.loads(path.read_text())["reservations"]), 8)

    def test_credentials_cannot_be_forwarded_to_arbitrary_hosts(self):
        for endpoint in ("http://unsafe/openai/v1", "https://example.com/openai/v1", "https://user:secret@service.openai.azure.com/openai/v1"):
            with self.assertRaises(ValueError):
                FoundrySender(endpoint, lambda: "unused")


if __name__ == "__main__":
    unittest.main()
