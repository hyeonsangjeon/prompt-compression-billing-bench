import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from native_helpers import FixtureEncoder, ImmediateQueue, ledger_fixture, response_fixture
from src.compressors import NoOpCompressor
from src.live_transport import LiveRecorder, start_live_proxy
from src.task_metrics import read_events


@unittest.skipUnless(importlib.util.find_spec("harbor"), "Install the locked native extra for Harbor integration")
class HarborTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_harbor_phase_timers_stay_disabled_beneath_the_outer_safety_guard(self):
        from harbor.agents.terminus_2.terminus_2 import Terminus2
        from harbor.trial.multi_step import MultiStepTrial
        from harbor.trial.trial import Trial

        from src.harbor_agent import ObservedTerminus2
        from src.harbor_no_time_limits import apply_no_time_limit_policy

        policy = apply_no_time_limit_policy()
        placeholder = object()
        self.assertIsNone(Trial._compute_agent_timeout_sec(placeholder))
        self.assertIsNone(Trial._compute_verifier_timeout_sec(placeholder))
        self.assertIsNone(Trial._compute_agent_setup_timeout_sec(placeholder))
        self.assertIsNone(Trial._compute_environment_build_timeout_sec(placeholder))
        self.assertIsNone(MultiStepTrial._step_agent_timeout_sec(placeholder, None))
        self.assertIsNone(MultiStepTrial._step_verifier_timeout_sec(placeholder, None))
        self.assertIs(ObservedTerminus2._run_agent_loop, Terminus2._run_agent_loop)
        self.assertEqual(policy["terminus_max_turns_argument"], None)
        self.assertEqual(policy["llm_http_timeout_seconds"], None)

    async def test_actual_harbor_sdk_defers_http_timeout_to_the_guarded_proxy(self):
        import httpx
        import litellm

        from harbor.llms.lite_llm import LiteLLM
        from tenacity import wait_none

        from src.harbor_agent import ObservedTerminus2

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        ledger = ledger_fixture()
        sent = []

        def sender(body):
            sent.append(json.loads(body))
            time.sleep(0.2)
            return 200, response_fixture(
                '{"analysis":"synthetic","plan":"done","commands":[],"task_complete":true}'
            ), {}

        recorder = LiveRecorder(
            root / "transport", ledger, "a" * 40,
            NoOpCompressor({"options": {}}, root), FixtureEncoder(), ImmediateQueue(), sender,
            evidence_kind="synthetic_validation", request_error_scope="trial",
        )
        recorder.register_trial("trial", "synthetic", 1)
        server = start_live_proxy(recorder, "synthetic-key")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        original_connect = socket.socket.connect

        def local_only(connection, address):
            if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
                raise AssertionError("Synthetic validation attempted a non-loopback connection")
            return original_connect(connection, address)

        environment = {
            "OPENAI_API_KEY": "synthetic-key",
            "LITELLM_LOCAL_MODEL_COST_MAP": "true",
            "NO_PROXY": "127.0.0.1,localhost",
        }
        agent = ObservedTerminus2(
            logs_dir=root / "agent", model_name="openai/gpt-5.4",
            api_base=f"http://127.0.0.1:{server.server_port}/trial/v1",
            temperature=0, reasoning_effort="none", enable_summarize=False,
            use_responses_api=False,
            llm_kwargs={"num_retries": 0, "max_completion_tokens": 2048},
        )
        timeout = agent._llm._llm_kwargs["timeout"]
        self.assertIsInstance(timeout, httpx.Timeout)
        self.assertIsNone(timeout.connect)
        self.assertIsNone(timeout.read)
        self.assertIsNone(timeout.write)
        self.assertIsNone(timeout.pool)
        with patch.dict(os.environ, environment), \
             patch.object(socket.socket, "connect", local_only), \
             patch.object(litellm, "request_timeout", 0.05), \
             patch.object(LiteLLM.call.retry, "wait", wait_none()):
            response = await agent._llm.call("Synthetic protected instruction")
        self.assertIn("synthetic", response.content)
        self.assertEqual(len(sent), 1)
        self.assertEqual(recorder.trials["trial"]["calls"], 1)
        self.assertIsNone(recorder.trials["trial"]["failure"])

    async def test_actual_harbor_sdk_serialization_reaches_only_fake_upstream(self):
        """Real SDK to loopback; non-loopback socket connections are forbidden."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        ledger = ledger_fixture()
        sent = []

        def sender(body):
            sent.append(json.loads(body))
            return 200, response_fixture('{"analysis":"synthetic","plan":"none","commands":[],"task_complete":true}'), {}

        recorder = LiveRecorder(root / "transport", ledger, "a" * 40, NoOpCompressor({"options": {}}, root),
                                FixtureEncoder(), ImmediateQueue(), sender, evidence_kind="synthetic_validation")
        recorder.register_trial("trial", "synthetic", 1)
        server = start_live_proxy(recorder, "synthetic-key")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        original_connect = socket.socket.connect

        def local_only(connection, address):
            if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
                raise AssertionError("Synthetic validation attempted a non-loopback connection")
            return original_connect(connection, address)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-key", "LITELLM_LOCAL_MODEL_COST_MAP": "true", "NO_PROXY": "127.0.0.1,localhost"}), patch.object(socket.socket, "connect", local_only):
            from src.harbor_agent import ObservedTerminus2

            agent = ObservedTerminus2(logs_dir=root / "agent", model_name="openai/gpt-5.4",
                                      api_base=f"http://127.0.0.1:{server.server_port}/trial/v1",
                                      temperature=0, reasoning_effort="none", enable_summarize=False,
                                      use_responses_api=False,
                                      llm_kwargs={"num_retries": 0, "max_completion_tokens": 2048})
            response = await agent._llm.call("Synthetic protected instruction")
        recorder.close_trial("trial")
        self.assertIn("synthetic", response.content)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["temperature"], 0)
        self.assertEqual(sent[0]["reasoning_effort"], "none")
        self.assertEqual(sent[0]["max_completion_tokens"], 2048)
        self.assertEqual(sent[0]["messages"][-1]["content"], "Synthetic protected instruction")
        self.assertEqual(agent._max_episodes, 1_000_000)
        events = read_events(root / "transport/events.jsonl")
        self.assertEqual(sum(event["event"] == "response_delivered" for event in events), 1)
        self.assertFalse(recorder.stopped.is_set())

    async def test_actual_sdk_stops_before_the_sixty_first_provider_dispatch(self):
        """Actual Harbor and LiteLLM code use loopback only; no provider is contacted."""
        from harbor.llms.lite_llm import LiteLLM
        from tenacity import wait_none

        from src.harbor_agent import ObservedTerminus2
        from src.screening_run import _classify_attempt

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        ledger = ledger_fixture()
        sent = []

        def sender(body):
            sent.append(json.loads(body))
            content = '{"analysis":"synthetic","plan":"continue","commands":[],"task_complete":false}'
            response = json.loads(response_fixture(content))
            response["id"] = f"synthetic-completion-{len(sent):02d}"
            return 200, json.dumps(response, separators=(",", ":")).encode(), {}

        recorder = LiveRecorder(
            root / "transport", ledger, "a" * 40,
            NoOpCompressor({"options": {}}, root), FixtureEncoder(), ImmediateQueue(), sender,
            evidence_kind="synthetic_validation", request_error_scope="trial",
        )
        recorder.register_trial("trial", "synthetic", 1)
        server = start_live_proxy(recorder, "synthetic-key")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        agent = ObservedTerminus2(
            logs_dir=root / "agent", model_name="openai/gpt-5.4",
            api_base=f"http://127.0.0.1:{server.server_port}/trial/v1",
            temperature=0, reasoning_effort="none", enable_summarize=False,
            use_responses_api=False,
            llm_kwargs={"num_retries": 0, "max_completion_tokens": 2048},
        )
        original_connect = socket.socket.connect

        def local_only(connection, address):
            if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
                raise AssertionError("Synthetic validation attempted a non-loopback connection")
            return original_connect(connection, address)

        environment = {
            "OPENAI_API_KEY": "synthetic-key",
            "LITELLM_LOCAL_MODEL_COST_MAP": "true",
            "NO_PROXY": "127.0.0.1,localhost",
        }
        with patch.dict(os.environ, environment), \
             patch.object(socket.socket, "connect", local_only), \
             patch.object(LiteLLM.call.retry, "wait", wait_none()), \
             patch("src.live_transport.progress_signal", side_effect=(str(index) for index in range(61))):
            for _index in range(60):
                response = await agent._llm.call("Synthetic protected instruction")
                self.assertIn("synthetic", response.content)
            with self.assertRaises(Exception):
                await agent._llm.call("Synthetic protected instruction")

        events = read_events(root / "transport/events.jsonl")
        self.assertEqual(len(sent), 60)
        self.assertEqual(recorder.trials["trial"]["calls"], 61)
        self.assertEqual(
            recorder.trials["trial"]["failure"]["details"]["limit_name"],
            "max_provider_calls_per_attempt",
        )
        self.assertEqual(sum(event["event"] == "call_received" for event in events), 61)
        self.assertEqual(sum(event["event"] == "http" for event in events), 60)
        self.assertEqual(sum(event["event"] == "response_delivered" for event in events), 60)
        self.assertTrue(all(request["max_completion_tokens"] == 2048 for request in sent))

        attempt_directory = root / "attempt"
        attempt_directory.mkdir()
        (attempt_directory / "harbor.log").write_text("synthetic local integration\n")
        replay = {
            "status": "complete",
            "capture_phase": "teardown_without_verifier",
            "capture_wall_seconds": 1.0,
            "manifest_sha256": "b" * 64,
        }
        outcome = {
            "native_reward": None,
            "quality_valid": False,
            "failure_categories": [],
            "failures": [],
        }
        with patch("src.screening_run.collect_native_outcome", return_value=outcome) as verifier, \
             patch("src.screening_run.collect_trial_metrics", return_value={"measurement_complete": True}), \
             patch(
                 "src.screening_run._attempt_replay",
                 return_value=(replay, "replay_capture_phase_invalid"),
             ):
            classified = _classify_attempt(
                {"attempt_id": "trial", "attempt_directory": attempt_directory},
                {
                    "returncode": 0, "timed_out": False, "stopped_by_guard": False,
                    "elapsed_seconds": 1.0,
                },
                recorder,
                root / "transport",
            )
        verifier.assert_called_once()
        self.assertEqual(classified["result"], "budget_stopped")
        self.assertEqual(classified["termination"]["quality_status"], "unknown")
        self.assertEqual(classified["provider_cost"]["http_attempts"], 60)


if __name__ == "__main__":
    unittest.main()
