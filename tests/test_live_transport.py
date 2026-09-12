from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from native_helpers import FixtureEncoder, ImmediateQueue, ledger_fixture, request_fixture, response_fixture
from src.compressors import NoOpCompressor
from src.live_transport import DeploymentQueue, FoundrySender, LiveRecorder, start_live_proxy
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
        self.assertTrue(self.queue.calls)

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

    def test_bounded_429_retries_count_every_attempt_and_keep_unknown_budget(self):
        responses = iter([(429, b'{"error":"synthetic limit"}', {"Retry-After": "0"}),
                          (200, response_fixture(), {})])
        self.recorder.sender = lambda body: (self.sent.append(body), next(responses))[1]
        self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(len(self.sent), 2)
        events = read_events(self.root / "transport/events.jsonl")
        self.assertEqual(sum(event["event"] == "attempt_started" for event in events), 2)
        self.assertEqual(self.queue.cooldowns, [0])
        self.assertGreater(self.recorder.budget_used_usd, 0.00002)

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

    def test_budget_and_request_limits_fail_before_provider_dispatch(self):
        self.ledger["limits"]["api_cost_usd"] = 0
        with self.assertRaisesRegex(ValueError, "budget"):
            self.recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(self.sent, [])


class QueueTests(unittest.TestCase):
    def test_same_deployment_queue_is_exclusive_and_survives_restarts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queue.json"
            queue = DeploymentQueue(path, "deployment", 5, 1000)
            with self.assertRaises(BlockingIOError):
                DeploymentQueue(path, "deployment", 5, 1000)
            queue.reserve(50, threading.Event(), time.time() + 5)
            queue.close()
            reopened = DeploymentQueue(path, "deployment", 5, 1000)
            self.assertEqual(len(reopened.reservations), 1)
            reopened.close()
            with self.assertRaises(ValueError):
                DeploymentQueue(path, "different-deployment", 5, 1000)

    def test_rate_deadline_and_oversized_reservation_do_not_wait_forever(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = DeploymentQueue(Path(temporary) / "queue", "deployment", 1, 100)
            self.addCleanup(queue.close)
            with self.assertRaises(ValueError):
                queue.reserve(101, threading.Event(), time.time() + 5)
            queue.reserve(50, threading.Event(), time.time() + 5)
            with self.assertRaisesRegex(ValueError, "deadline"):
                queue.reserve(50, threading.Event(), time.time() + 0.1)

    def test_concurrent_reservations_are_persisted_without_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queue"
            queue = DeploymentQueue(path, "deployment", 8, 1000)
            self.addCleanup(queue.close)
            barrier = threading.Barrier(8)

            def reserve():
                barrier.wait(timeout=2)
                queue.reserve(50, threading.Event(), time.time() + 5)

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
                FoundrySender(endpoint, 1, lambda: "unused")


if __name__ == "__main__":
    unittest.main()
