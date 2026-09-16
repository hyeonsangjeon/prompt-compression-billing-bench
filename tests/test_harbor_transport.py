import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from native_helpers import FixtureEncoder, ImmediateQueue, ledger_fixture, response_fixture
from src.compressors import NoOpCompressor
from src.live_transport import LiveRecorder, start_live_proxy
from src.task_metrics import read_events


@unittest.skipUnless(importlib.util.find_spec("harbor"), "Install the locked native extra for Harbor integration")
class HarborTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_harbor_phase_time_limits_are_none_and_agent_loop_is_not_wrapped(self):
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
                                      llm_kwargs={"num_retries": 0})
            response = await agent._llm.call("Synthetic protected instruction")
        recorder.close_trial("trial")
        self.assertIn("synthetic", response.content)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["temperature"], 0)
        self.assertEqual(sent[0]["reasoning_effort"], "none")
        self.assertNotIn("max_completion_tokens", sent[0])
        self.assertEqual(sent[0]["messages"][-1]["content"], "Synthetic protected instruction")
        self.assertEqual(agent._max_episodes, 1_000_000)
        events = read_events(root / "transport/events.jsonl")
        self.assertEqual(sum(event["event"] == "response_delivered" for event in events), 1)
        self.assertFalse(recorder.stopped.is_set())

    async def test_length_recovery_allows_calls_after_sixty_and_then_allows_grading(self):
        """Actual Harbor and LiteLLM code use loopback only; verifier output is deterministic input."""
        from harbor.agents.terminus_2.terminus_2 import Terminus2
        from harbor.llms.chat import Chat
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
            if len(sent) == 1:
                content = "truncated"
            elif len(sent) < 61:
                content = '{"analysis":"synthetic","plan":"continue","commands":[],"task_complete":false}'
            else:
                content = '{"analysis":"synthetic","plan":"done","commands":[],"task_complete":true}'
            response = json.loads(response_fixture(content))
            if len(sent) == 1:
                response["choices"][0]["finish_reason"] = "length"
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

        class Session:
            async def is_session_alive(self):
                return True

            async def get_incremental_output(self):
                return ""

        agent = ObservedTerminus2(
            logs_dir=root / "agent", model_name="openai/gpt-5.4",
            api_base=f"http://127.0.0.1:{server.server_port}/trial/v1",
            temperature=0, reasoning_effort="none", enable_summarize=False,
            use_responses_api=False,
            llm_kwargs={"num_retries": 0},
        )
        agent._context = SimpleNamespace(
            n_input_tokens=0, n_output_tokens=0, n_cache_tokens=0, cost_usd=None,
        )
        agent._session = Session()
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
             patch.object(Terminus2._query_llm.retry, "wait", wait_none()), \
             patch.object(LiteLLM.call.retry, "wait", wait_none()):
            await agent._run_agent_loop(
                "Synthetic protected instruction", Chat(agent._llm)
            )

        events = read_events(root / "transport/events.jsonl")
        self.assertEqual(len(sent), 62)
        self.assertEqual(recorder.trials["trial"]["calls"], 62)
        self.assertIsNone(recorder.trials["trial"]["failure"])
        self.assertEqual(sum(event["event"] == "call_received" for event in events), 62)
        self.assertEqual(sum(event["event"] == "http" for event in events), 62)
        self.assertEqual(sum(event["event"] == "response_delivered" for event in events), 62)
        self.assertTrue(all("max_completion_tokens" not in request for request in sent))
        self.assertIn("NONE of the actions", sent[1]["messages"][-1]["content"])
        self.assertEqual(sent[1]["messages"][-2]["content"], "truncated")

        attempt_directory = root / "attempt"
        attempt_directory.mkdir()
        (attempt_directory / "harbor.log").write_text("synthetic local integration\n")
        replay = {
            "status": "complete",
            "capture_phase": "after_tests_upload_before_verifier",
            "capture_wall_seconds": 1.0,
            "manifest_sha256": "b" * 64,
            "verifier_replay": {
                "status": "complete",
                "state_restored": True,
                "same_judgement": True,
                "original_verifier_wall_seconds": 1.0,
                "restore_wall_seconds": 1.0,
                "repeated_verifier_wall_seconds": 1.0,
                "wall_seconds": 2.0,
            },
        }
        outcome = {
            "native_reward": 0,
            "quality_valid": True,
            "failure_categories": ["wrong_answer"],
            "failures": [{"category": "wrong_answer", "test": "synthetic-verifier"}],
        }
        with patch("src.screening_run.collect_native_outcome", return_value=outcome) as verifier, \
             patch("src.screening_run.collect_trial_metrics", return_value={"measurement_complete": True}), \
             patch("src.screening_run._attempt_replay", return_value=(replay, None)):
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
        self.assertEqual(classified["result"], "wrong_answer")
        self.assertEqual(classified["provider_cost"]["http_attempts"], 62)


if __name__ == "__main__":
    unittest.main()
