import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from native_helpers import FixtureEncoder, ImmediateQueue, ledger_fixture, response_fixture
from src.compressors import NoOpCompressor
from src.live_transport import LiveRecorder, start_live_proxy
from src.task_metrics import read_events


@unittest.skipUnless(importlib.util.find_spec("harbor"), "Install the locked native extra for Harbor integration")
class HarborTransportTests(unittest.IsolatedAsyncioTestCase):
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
                                      use_responses_api=False, max_turns=60,
                                      llm_kwargs={"max_completion_tokens": ledger["model"]["max_completion_tokens"],
                                                  "num_retries": 0})
            response = await agent._llm.call("Synthetic protected instruction")
        recorder.close_trial("trial")
        self.assertIn("synthetic", response.content)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["temperature"], 0)
        self.assertEqual(sent[0]["reasoning_effort"], "none")
        self.assertEqual(sent[0]["max_completion_tokens"], ledger["model"]["max_completion_tokens"])
        self.assertEqual(sent[0]["messages"][-1]["content"], "Synthetic protected instruction")
        events = read_events(root / "transport/events.jsonl")
        self.assertEqual(sum(event["event"] == "response_delivered" for event in events), 1)
        self.assertFalse(recorder.stopped.is_set())


if __name__ == "__main__":
    unittest.main()
