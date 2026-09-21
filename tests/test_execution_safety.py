from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

from native_helpers import FixtureEncoder, ImmediateQueue, ledger_fixture, request_fixture, response_fixture
from src.compressors import NoOpCompressor
from src.contracts import validate
from src.execution_safety import (
    SafetyLimitReached,
    require_operational_safety,
    safety_policy_record,
    validate_safety_limits,
)
from src.live_transport import FoundrySender, LiveRecorder
from src.protection import canonical


class ExecutionSafetyPolicyTests(unittest.TestCase):
    def test_public_templates_and_current_documents_keep_one_safety_policy(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ("ledgers/native.template.toml", "ledgers/screening.template.toml"):
            ledger = tomllib.loads((root / relative).read_text())
            self.assertEqual(ledger["schema_version"], 4)
            validate_safety_limits(ledger["limits"])
            self.assertEqual(ledger["limits"]["max_provider_calls_per_attempt"], 60)
            self.assertEqual(ledger["limits"]["max_wall_seconds_per_attempt"], 2400)
            self.assertEqual(ledger["limits"]["max_request_bytes"], 8_000_000)
            self.assertEqual(ledger["limits"]["max_output_tokens"], 2048)
            self.assertEqual(ledger["limits"]["no_progress_window_calls"], 8)
            self.assertEqual(ledger["limits"]["no_progress_minimum_distinct_signals"], 3)
            self.assertEqual(ledger["limits"]["max_api_cost_usd_per_attempt"], 0)
            self.assertEqual(ledger["limits"]["max_api_cost_usd_per_run"], 0)
            self.assertEqual(ledger["limits"]["run_deadline_utc"], "")

        current_guidance = "\n".join(
            (root / relative).read_text()
            for relative in (
                "README.md",
                "STATUS.md",
                "docs/native-contract.md",
                "docs/experiment/README.md",
                "docs/experiment/data-connection-guide-20260919.md",
                "docs/experiment/screening-protocol.md",
                "docs/experiment/evaluation-protocol.md",
                "docs/experiment/execution-safety-policy.md",
            )
        )
        for stale_instruction in (
            "do not set time or cost limits",
            "do not apply a full-run time or deadline stop",
            "run with no limits",
        ):
            self.assertNotIn(stale_instruction, current_guidance)

        decisions = " ".join(
            (root / "docs/experiment/decisions.md").read_text().split()
        )
        self.assertIn("This paragraph is a historical record of conditions at the time", decisions)
        self.assertIn("Future paid execution follows schema version 4 below", decisions)
        policy = " ".join(
            (root / "docs/experiment/execution-safety-policy.md").read_text().split()
        )
        self.assertIn("Waiting for natural termination is not allowed in the general comparison", policy)
        self.assertIn("A limit stop is not a quality judgment such as `pass`, `wrong_answer`, or `wrong_format`", policy)

    def test_template_and_applied_policy_are_strict_and_schema_valid(self):
        ledger = ledger_fixture()
        applied = require_operational_safety(ledger)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["limits"]["provider_http_attempts_per_attempt"], 60)
        self.assertFalse(applied["natural_termination"]["pilot_execution_available"])
        self.assertEqual(applied["stop_classification"]["outcome"], "technical_incomplete")
        self.assertFalse(applied["stop_classification"]["wrong_answer_allowed"])
        validate(applied, "execution-safety-policy.schema.json")

        template = deepcopy(ledger)
        template["limits"].update(
            max_api_cost_usd_per_attempt=0,
            max_api_cost_usd_per_run=0,
            run_deadline_utc="",
        )
        unapproved = safety_policy_record(template, applied=False)
        self.assertEqual(unapproved["status"], "template_unapproved")
        self.assertIsNone(unapproved["limits"]["api_calculated_cost_usd_per_run"])
        validate(unapproved, "execution-safety-policy.schema.json")

        configured_but_not_applied = safety_policy_record(ledger, applied=False)
        self.assertEqual(configured_but_not_applied["status"], "template_unapproved")
        self.assertIsNone(
            configured_but_not_applied["limits"]["api_calculated_cost_usd_per_attempt"]
        )
        self.assertIsNone(configured_but_not_applied["limits"]["run_deadline_utc"])
        validate(configured_but_not_applied, "execution-safety-policy.schema.json")

        unexpected = deepcopy(applied)
        unexpected["limits"]["extra"] = 1
        with self.assertRaises(ValueError):
            validate(unexpected, "execution-safety-policy.schema.json")

    def test_partial_approval_fixed_limit_drift_and_expired_deadline_fail_closed(self):
        ledger = ledger_fixture()
        partial = deepcopy(ledger["limits"])
        partial["max_api_cost_usd_per_run"] = 0
        with self.assertRaisesRegex(ValueError, "all unresolved or all operational"):
            validate_safety_limits(partial)

        drifted = deepcopy(ledger["limits"])
        drifted["max_provider_calls_per_attempt"] = 61
        with self.assertRaisesRegex(ValueError, "fixed"):
            validate_safety_limits(drifted)

        expired = deepcopy(ledger)
        expired["limits"]["run_deadline_utc"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        with self.assertRaisesRegex(ValueError, "future"):
            require_operational_safety(expired)

    def test_common_result_schema_keeps_safety_stops_out_of_quality_results(self):
        root = Path(__file__).resolve().parents[1]
        result = json.loads(
            (root / "examples/experiment/native-preflight-result.json").read_bytes()
        )
        result.update(
            execution_safety=require_operational_safety(ledger_fixture()),
            termination=SafetyLimitReached(
                "max_provider_calls_per_attempt", "attempt", 60, 61,
                trial_id="trial-one",
            ).details,
            status="completed",
            outcome="measurement_completed",
            quality={"status": "wrong_answer", "judge": "terminal-bench-native"},
            completion={"technical_status": "complete", "operator_status": "not_stopped"},
        )
        with self.assertRaises(ValueError):
            validate(result, "experiment-result.schema.json")

        result.update(
            status="failed",
            outcome="technical_incomplete",
            quality={"status": "unknown", "judge": None},
            completion={"technical_status": "incomplete", "operator_status": "not_stopped"},
        )
        validate(result, "experiment-result.schema.json")


class LiveSafetyBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ledger = ledger_fixture()
        self.sent = []

    def recorder(self, sender=None, *, ledger=None):
        current_ledger = ledger or self.ledger
        if sender is None:
            sender = lambda body: (self.sent.append(body), (200, response_fixture(), {}))[1]
        recorder = LiveRecorder(
            self.root / f"transport-{len(list(self.root.iterdir())):02d}",
            current_ledger,
            "a" * 40,
            NoOpCompressor({"options": {}}, self.root),
            FixtureEncoder(),
            ImmediateQueue(),
            sender,
            evidence_kind="synthetic_validation",
            request_error_scope="trial",
        )
        recorder.register_trial("trial-one", "synthetic-task", 1)
        return recorder

    def test_request_and_output_caps_stop_as_censored_not_wrong_answer(self):
        recorder = self.recorder()
        oversized = b"x" * (self.ledger["limits"]["max_request_bytes"] + 1)
        with self.assertRaises(SafetyLimitReached):
            recorder.complete("trial-one", oversized)
        failure = recorder.trials["trial-one"]["failure"]["details"]
        self.assertEqual(failure["stop_kind"], "censored")
        self.assertEqual(failure["quality_status"], "unknown")
        self.assertEqual(self.sent, [])

        response = json.loads(response_fixture())
        response["usage"].update(completion_tokens=2049, total_tokens=2059)
        second = self.recorder(lambda _body: (200, canonical(response), {}))
        with self.assertRaises(SafetyLimitReached):
            second.complete("trial-one", canonical(request_fixture()))
        details = second.trials["trial-one"]["failure"]["details"]
        self.assertEqual(details["limit_name"], "max_output_tokens")
        self.assertEqual(details["stop_kind"], "censored")
        self.assertGreater(second.known_provider_cost_usd, 0)

    def test_attempt_and_run_cost_reservations_block_before_dispatch(self):
        attempt_ledger = ledger_fixture()
        attempt_ledger["limits"].update(
            max_api_cost_usd_per_attempt=0.000001,
            max_api_cost_usd_per_run=1,
        )
        recorder = self.recorder(ledger=attempt_ledger)
        with self.assertRaises(SafetyLimitReached):
            recorder.complete("trial-one", canonical(request_fixture()))
        self.assertEqual(recorder.trials["trial-one"]["provider_http_attempts"], 0)
        self.assertEqual(
            recorder.trials["trial-one"]["failure"]["details"]["limit_name"],
            "max_api_cost_usd_per_attempt",
        )

        run_ledger = ledger_fixture()
        run_ledger["limits"].update(max_api_cost_usd_per_attempt=1, max_api_cost_usd_per_run=1)
        resumed = self.recorder(ledger=run_ledger)
        with self.assertRaisesRegex(ValueError, "before registering"):
            resumed.initialize_run_cost_exposure(known_cost_usd=0.99, unconfirmed_exposure_usd=0)

        fresh = LiveRecorder(
            self.root / "resume-transport",
            run_ledger,
            "a" * 40,
            NoOpCompressor({"options": {}}, self.root),
            FixtureEncoder(),
            ImmediateQueue(),
            lambda body: (self.sent.append(body), (200, response_fixture(), {}))[1],
            evidence_kind="synthetic_validation",
            request_error_scope="trial",
        )
        fresh.initialize_run_cost_exposure(known_cost_usd=0.999, unconfirmed_exposure_usd=0)
        fresh.register_trial("trial-one", "synthetic-task", 1)
        with self.assertRaises(SafetyLimitReached) as error:
            fresh.complete("trial-one", canonical(request_fixture()))
        self.assertTrue(error.exception.run_wide)
        self.assertEqual(error.exception.details["limit_name"], "max_api_cost_usd_per_run")
        self.assertEqual(fresh.failure["reason"], "SafetyLimitReached")
        self.assertEqual(fresh.trials["trial-one"]["failure"]["reason"], "SafetyLimitReached")
        self.assertEqual(
            fresh.safety_snapshot("trial-one")["termination"]["details"]["scope"],
            "run",
        )

    def test_unknown_or_malformed_response_keeps_reserved_exposure(self):
        recorder = self.recorder(lambda _body: (200, b"{", {}))
        with self.assertRaisesRegex(ValueError, "unambiguous JSON"):
            recorder.complete("trial-one", canonical(request_fixture()))
        snapshot = recorder.safety_snapshot("trial-one")
        self.assertGreater(snapshot["unconfirmed_api_cost_exposure_usd"], 0)
        self.assertEqual(snapshot["pending_api_cost_exposure_usd"], 0)
        self.assertEqual(snapshot["last_response"]["usage_status"], "unknown")

        invalid = json.loads(response_fixture())
        invalid["choices"] = []
        second = self.recorder(lambda _body: (200, canonical(invalid), {}))
        with self.assertRaisesRegex(ValueError, "one textual"):
            second.complete("trial-one", canonical(request_fixture()))
        self.assertGreater(second.known_provider_cost_usd, 0)
        self.assertEqual(second.safety_snapshot("trial-one")["pending_api_cost_exposure_usd"], 0)

    def test_run_deadline_stops_before_dispatch_and_marks_quality_unknown(self):
        recorder = self.recorder()
        recorder.deadline = time.time() - 1
        with self.assertRaises(SafetyLimitReached) as error:
            recorder.complete("trial-one", canonical(request_fixture()))
        self.assertTrue(error.exception.run_wide)
        self.assertEqual(error.exception.details["limit_name"], "run_deadline_utc")
        self.assertEqual(error.exception.details["quality_status"], "unknown")
        self.assertEqual(recorder.failure["reason"], "SafetyLimitReached")
        self.assertEqual(recorder.trials["trial-one"]["failure"]["reason"], "SafetyLimitReached")
        self.assertEqual(self.sent, [])

    def test_provider_http_timeout_is_a_structured_censored_stop(self):
        sender = FoundrySender(
            "https://synthetic.openai.azure.com/openai/v1",
            lambda: "synthetic-token",
            timeout_seconds=300,
        )
        with patch("urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = TimeoutError("synthetic timeout")
            with self.assertRaises(SafetyLimitReached) as error:
                sender(b"{}")
        self.assertEqual(error.exception.details["limit_name"], "provider_http_timeout_seconds")
        self.assertEqual(error.exception.details["applied_limit"], 300)
        self.assertEqual(error.exception.details["stop_kind"], "censored")

    def test_no_progress_window_attempt_wall_and_retry_wait_are_censored(self):
        recorder = self.recorder()
        assistant = json.dumps({"commands": [{"keystrokes": "pwd\n"}], "task_complete": False})
        request = request_fixture()
        request["messages"] = [
            {"role": "assistant", "content": assistant},
            {"role": "user", "content": "unchanged observation"},
        ]
        for _ in range(7):
            recorder.complete("trial-one", canonical(request))
        with self.assertRaises(SafetyLimitReached):
            recorder.complete("trial-one", canonical(request))
        details = recorder.trials["trial-one"]["failure"]["details"]
        self.assertEqual(details["limit_name"], "no_progress_window")
        self.assertEqual(details["stop_kind"], "censored")

        wall = self.recorder()
        wall.trials["trial-one"]["started_monotonic"] = (
            time.monotonic() - self.ledger["limits"]["max_wall_seconds_per_attempt"] - 1
        )
        with self.assertRaises(SafetyLimitReached) as error:
            wall.check_trial("trial-one")
        wall.record_safety_stop("trial-one", error.exception)
        self.assertEqual(error.exception.details["applied_limit"], 2400)
        self.assertGreaterEqual(error.exception.details["observed"], 2400)
        self.assertEqual(error.exception.details["trial_id"], "trial-one")
        self.assertEqual(
            wall.trials["trial-one"]["failure"]["details"]["limit_name"],
            "max_wall_seconds_per_attempt",
        )

        retry = self.recorder(lambda _body: (429, b'{"error":"busy"}', {"Retry-After": "121"}))
        with self.assertRaises(SafetyLimitReached):
            retry.complete("trial-one", canonical(request_fixture()))
        retry_details = retry.trials["trial-one"]["failure"]["details"]
        self.assertEqual(retry_details["limit_name"], "max_retry_wait_seconds")
        self.assertGreater(retry.unconfirmed_provider_exposure_usd, 0)

    def test_missing_progress_signals_are_counted_in_the_fixed_window(self):
        recorder = self.recorder()
        request = request_fixture()
        for _index in range(7):
            recorder.complete("trial-one", canonical(request))
        with self.assertRaises(SafetyLimitReached):
            recorder.complete("trial-one", canonical(request))
        details = recorder.trials["trial-one"]["failure"]["details"]
        self.assertEqual(details["limit_name"], "no_progress_window")
        self.assertEqual(details["observed"], 1)


if __name__ == "__main__":
    unittest.main()
