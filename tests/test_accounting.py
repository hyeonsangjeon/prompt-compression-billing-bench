import copy
import json
import tempfile
import threading
import tomllib
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from accounting import AttemptRecorder, provider_tokens, read_attempts, sha256, start_proxy, totals
from run import load_ledger, save, verify


ROOT = Path(__file__).resolve().parents[1]


class AccountingTests(unittest.TestCase):
    """Synthetic transport responses are unit fixtures, never a quickstart path."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = tomllib.loads((ROOT / "ledger.toml").read_text())
        self.ledger["retry"]["delay_seconds"] = 0
        self.responses = []
        self.requests = 0
        self.response_started = None
        self.release_response = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                owner.requests += 1
                status, value, headers = owner.responses.pop(0)
                if owner.response_started is not None:
                    owner.response_started.set()
                    owner.release_response.wait(timeout=5)
                data = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.recorder = AttemptRecorder(
            self.root / "repetition-001", self.ledger, "unit-test-synthetic", 1,
            "ledger-hash", "source-hash", f"http://127.0.0.1:{self.server.server_port}", "test-only",
        )
        self.payload = {
            "model": self.ledger["model"]["name"],
            "max_tokens": self.ledger["model"]["max_output_tokens"],
            "temperature": self.ledger["model"]["temperature"],
            "reasoning_effort": self.ledger["model"]["reasoning_effort"],
            "messages": [{"role": "user", "content": "unit fixture"}],
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def success(self, input_tokens=10, output_tokens=3):
        return {
            "choices": [{"message": {"content": "unit fixture"}}],
            "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
        }

    def test_429_retry_usage_is_not_double_counted(self):
        self.responses = [
            (429, {"usage": {"prompt_tokens": 999, "completion_tokens": 999}}, {"Retry-After": "0"}),
            (200, self.success(), {}),
        ]
        status, _ = self.recorder.forward(self.payload)
        self.assertEqual(status, 200)
        records = read_attempts(self.root)
        result = totals(records)
        self.assertEqual((result["http_attempts"], result["http_429"], result["retries"]), (2, 1, 1))
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (10, 3))
        self.assertEqual(len({row["call_id"] for row in records}), 1)
        self.assertEqual(len({row["attempt_id"] for row in records}), 2)
        self.assertFalse(records[0]["included_in_totals"])

    def test_exhausted_retry_budget_cannot_restart_in_outer_runner(self):
        self.responses = [(429, {"error": "fixture"}, {})] * 2
        with self.assertRaises(ValueError):
            self.recorder.forward(self.payload)
        with self.assertRaises(ValueError):
            self.recorder.forward(self.payload)
        self.assertEqual(self.requests, 2)
        result = totals(read_attempts(self.root))
        self.assertEqual(result["http_429"], 2)
        self.assertEqual(result["responses_with_usage"], 0)

    def test_missing_usage_is_visible_and_stops(self):
        self.responses = [(200, {"choices": []}, {})]
        with self.assertRaisesRegex(ValueError, "usage"):
            self.recorder.forward(self.payload)
        records = read_attempts(self.root)
        self.assertEqual(records[0]["usage_status"], "not_reported")
        self.assertEqual(totals(records)["input_tokens"], 0)
        self.assertEqual(totals(records)["responses_with_usage"], 0)

    def test_cached_input_is_not_added_again(self):
        response = self.success()
        response["usage"]["prompt_tokens_details"] = {"cached_tokens": 7}
        self.responses = [(200, response, {})]
        self.recorder.forward(self.payload)
        self.assertEqual(totals(read_attempts(self.root))["input_tokens"], 10)

    def test_duplicate_attempt_is_rejected(self):
        self.responses = [(200, self.success(), {})]
        self.recorder.forward(self.payload)
        records = read_attempts(self.root)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            totals(records + records)

    def test_modified_counter_is_rejected_in_both_directions(self):
        self.responses = [(200, self.success(), {})]
        self.recorder.forward(self.payload)
        records = read_attempts(self.root)
        for difference in (-1, 1):
            changed = copy.deepcopy(records)
            changed[0]["tokens"]["input_tokens"] += difference
            with self.assertRaises(ValueError):
                totals(changed)

    def test_modified_raw_response_is_rejected(self):
        self.responses = [(200, self.success(), {})]
        self.recorder.forward(self.payload)
        path = next((self.root / "repetition-001").glob("*.response.json"))
        path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "hash"):
            read_attempts(self.root)

    def test_refuses_wrong_model_before_contact(self):
        self.payload["model"] = "a-paid-model"
        with self.assertRaises(ValueError):
            self.recorder.forward(self.payload)
        self.assertEqual(self.requests, 0)

    def test_missing_reasoning_control_is_not_a_silent_default(self):
        del self.payload["reasoning_effort"]
        with self.assertRaisesRegex(ValueError, "differs"):
            self.recorder.forward(self.payload)
        self.assertEqual(self.requests, 0)

    def test_shutdown_drains_late_usage_after_client_disconnect(self):
        import socket
        import struct
        self.responses = [(200, self.success(), {})]
        self.response_started = threading.Event()
        self.release_response = threading.Event()
        proxy = start_proxy(self.recorder)
        connection = socket.create_connection(("127.0.0.1", proxy.server_port))
        body = json.dumps(self.payload).encode()
        request = (
            f"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
            f"Authorization: Bearer test-only\r\nContent-Length: {len(body)}\r\n\r\n"
        ).encode() + body
        try:
            connection.sendall(request)
            self.assertTrue(self.response_started.wait(timeout=3))
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            connection.close()
            closed = threading.Event()

            def close_proxy():
                proxy.shutdown()
                proxy.server_close()
                closed.set()

            closer = threading.Thread(target=close_proxy)
            closer.start()
            self.assertFalse(closed.wait(timeout=0.7))
            self.release_response.set()
            self.assertTrue(closed.wait(timeout=3))
            closer.join()
            records = read_attempts(self.root)
            self.assertEqual(totals(records)["input_tokens"], 10)
            self.assertEqual(totals(records)["responses_with_usage"], 1)
            self.assertTrue(any(row["record_type"] == "downstream_disconnect" for row in records))
        finally:
            self.release_response.set()
            connection.close()
            proxy.shutdown()
            proxy.server_close()

    def test_retry_after_larger_than_budget_stops(self):
        self.responses = [(429, {"error": "fixture"}, {"Retry-After": "300"})]
        with self.assertRaisesRegex(ValueError, "wait limit"):
            self.recorder.forward(self.payload)
        self.assertEqual(self.requests, 1)

    def test_max_calls_is_per_repetition(self):
        self.ledger["limits"]["max_calls_per_repetition"] = 1
        self.responses = [(200, self.success(), {})]
        self.recorder.forward(self.payload)
        with self.assertRaisesRegex(ValueError, "max_calls"):
            self.recorder.forward(self.payload)
        self.assertEqual(self.requests, 1)

    def test_summary_changes_are_rejected_up_and_down(self):
        self.responses = [(200, self.success(), {})]
        self.recorder.forward(self.payload)
        ledger_bytes = b"test ledger"
        (self.root / "ledger.toml").write_bytes(ledger_bytes)
        original = {
            "run_id": "unit-test-synthetic", "ledger_sha256": sha256(ledger_bytes),
            "trials": [], "usage_totals": totals(read_attempts(self.root)),
        }
        for difference in (-1, 1):
            changed = copy.deepcopy(original)
            changed["usage_totals"]["input_tokens"] += difference
            save(self.root / "summary.json", changed)
            with self.assertRaisesRegex(ValueError, "either direction"):
                verify(self.root)


class LedgerTests(unittest.TestCase):
    def test_default_is_one_uncompressed_real_model_task(self):
        ledger = load_ledger(ROOT / "ledger.toml")
        self.assertEqual(ledger["repetitions"], 1)
        self.assertEqual(ledger["intervention"], "none")
        self.assertEqual(ledger["model"]["provider"], "ollama")
        self.assertEqual(ledger["benchmark"]["judge"], "native")

    def test_repetition_is_not_hardcoded(self):
        text = (ROOT / "ledger.toml").read_text().replace("repetitions = 1", "repetitions = 2")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.toml"
            path.write_text(text)
            self.assertEqual(load_ledger(path)["repetitions"], 2)

    def test_unknown_fields_are_not_ignored(self):
        text = (ROOT / "ledger.toml").read_text().replace("repetitions = 1", "repetitons = 1")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.toml"
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, "fields"):
                load_ledger(path)

    def test_malformed_usage_is_not_measured_zero(self):
        for usage in ({}, {"prompt_tokens": -1, "completion_tokens": 1},
                      {"prompt_tokens": True, "completion_tokens": 1},
                      {"prompt_tokens": 10, "completion_tokens": 1, "prompt_tokens_details": "bad"}):
            self.assertIsNone(provider_tokens({"usage": usage}))


if __name__ == "__main__":
    unittest.main()
