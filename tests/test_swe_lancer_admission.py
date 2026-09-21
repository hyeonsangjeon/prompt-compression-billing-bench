from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.swe_lancer_admission import (
    FIXED_IMAGE_DIGEST,
    FIXED_IMAGE_REFERENCE,
    check_admission,
    fingerprint,
    load_ledger,
    run,
    validate_public_evaluation,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "ledgers" / "swe-lancer.template.json"
EVALUATION = ROOT / "data" / "experiment" / "swe-lancer-candidate-evaluation.json"
REPORT = ROOT / "docs" / "experiment" / "swe-lancer-candidate-evaluation-20260920.md"
OFFLINE_SMOKE_WORKFLOW = ROOT / ".github" / "workflows" / "swe-lancer-offline-smoke.yml"


def deadline(seconds=4800):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z"
    )


class SweLancerAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ledger = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    def prepare_ready(self):
        environment = {
            "OPENAI_API_KEY": "test-secret-never-recorded",
            "SWE_LANCER_DOCKER_HOST": "task-owned-control-endpoint",
        }
        source_files = {
            "solver": b"controlled solver source\n",
            "catalog": b"controlled private catalog\n",
        }
        for pin in self.ledger["source"]["pins"]:
            path = self.root / pin["name"]
            path.write_bytes(source_files[pin["name"]])
            pin.update(fingerprint(path))
            environment[pin["path_env"]] = str(path)
        self.control_source_pins = {
            pin["name"]: {
                "path_env": pin["path_env"],
                "bytes": pin["bytes"],
                "sha256": pin["sha256"],
            }
            for pin in self.ledger["source"]["pins"]
        }
        for pin in self.ledger["sandbox"]["evidence_pins"]:
            path = self.root / f"{pin['name']}.json"
            path.write_text('{"reviewed":true}\n', encoding="utf-8")
            pin.update(fingerprint(path))
            environment[pin["path_env"]] = str(path)
        self.ledger["provider"].update(
            {
                "reported_model_revision": "controlled-revision",
                "price_source_url": "https://example.invalid/reviewed-price-source",
                "price_source_revision_or_retrieved_at": "controlled-review",
                "input_usd_per_million_tokens": "1.00",
                "output_usd_per_million_tokens": "2.00",
            }
        )
        self.ledger["approval"].update(
            {
                "approval_record": "controlled-review-record",
                "execution_approved": True,
            }
        )
        return environment

    def check(self, environment, selected_deadline=None):
        payload = json.dumps(self.ledger, sort_keys=True).encode()
        ledger_fingerprint = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        source_pins = getattr(self, "control_source_pins", None)
        if source_pins is None:
            return check_admission(
                self.ledger,
                ledger_fingerprint,
                selected_deadline or deadline(),
                environment,
            )
        with patch("src.swe_lancer_admission.FIXED_SOURCE_PINS", source_pins):
            return check_admission(
                self.ledger,
                ledger_fingerprint,
                selected_deadline or deadline(),
                environment,
            )

    def test_public_template_is_non_operational_and_side_effect_free(self):
        result = self.check({})
        self.assertEqual(result["status"], "not_ready")
        self.assertFalse(result["ready"])
        self.assertIn("approval.execution_approved", result["missing_or_invalid"])
        self.assertIn("environment.OPENAI_API_KEY.present", result["missing_or_invalid"])
        self.assertTrue(all(value in (False, 0) for value in result["side_effects"].values()))

    def test_ready_control_hashes_sources_and_records_no_secret_or_path_values(self):
        environment = self.prepare_ready()
        result = self.check(environment)
        self.assertTrue(result["ready"])
        self.assertEqual(result["status"], "ready")
        self.assertTrue(all(row["match"] for row in result["source_pins"]))
        self.assertTrue(all(row["match"] for row in result["sandbox"]["evidence_pins"]))
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(environment["OPENAI_API_KEY"], serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertFalse(result["provider"]["credential_value_recorded"])
        self.assertFalse(result["sandbox"]["endpoint_value_recorded"])

    def test_source_drift_fails_closed(self):
        environment = self.prepare_ready()
        (self.root / "solver").write_bytes(b"changed")
        result = self.check(environment)
        self.assertFalse(result["ready"])
        self.assertIn("source.pins.solver.fingerprint", result["missing_or_invalid"])

    def test_source_pin_definition_and_evidence_set_drift_fail_closed(self):
        environment = self.prepare_ready()
        (self.root / "solver").write_bytes(b"alternate controlled solver source\n")
        self.ledger["source"]["pins"][0]["sha256"] = fingerprint(self.root / "solver")["sha256"]
        self.ledger["source"]["pins"][0]["bytes"] = fingerprint(self.root / "solver")["bytes"]
        self.ledger["sandbox"]["evidence_pins"].pop()
        result = self.check(environment)
        self.assertFalse(result["ready"])
        self.assertIn("source.pins.solver.bytes", result["missing_or_invalid"])
        self.assertIn("source.pins.solver.sha256", result["missing_or_invalid"])
        self.assertIn("sandbox.evidence_pins.set", result["missing_or_invalid"])

    def test_nonfinite_price_and_endpoint_name_drift_fail_closed(self):
        environment = self.prepare_ready()
        self.ledger["provider"]["input_usd_per_million_tokens"] = "Infinity"
        self.ledger["sandbox"]["endpoint_env"] = "OTHER_ENDPOINT"
        environment["OTHER_ENDPOINT"] = "task-owned-control-endpoint"
        result = self.check(environment)
        self.assertFalse(result["ready"])
        self.assertIn("provider.input_usd_per_million_tokens", result["missing_or_invalid"])
        self.assertIn("sandbox.endpoint_env", result["missing_or_invalid"])

    def test_stale_and_far_deadlines_fail_closed(self):
        environment = self.prepare_ready()
        for selected in (deadline(-1), deadline(5000)):
            with self.subTest(deadline=selected):
                result = self.check(environment, selected)
                self.assertFalse(result["ready"])
                self.assertIn("deadline.fresh_absolute_utc", result["missing_or_invalid"])

    def test_existing_result_is_unchanged_before_ledger_read(self):
        result = self.root / "result.json"
        sentinel = b'{"sentinel":true}\n'
        result.write_bytes(sentinel)
        code = run(self.root / "missing-ledger.json", result, deadline(), {})
        self.assertEqual(code, 3)
        self.assertEqual(result.read_bytes(), sentinel)

    def test_result_symlink_is_rejected_and_target_is_unchanged(self):
        target = self.root / "target.json"
        target.write_bytes(b'{"target":true}\n')
        result = self.root / "result.json"
        result.symlink_to(target)
        code = run(self.root / "missing-ledger.json", result, deadline(), {})
        self.assertEqual(code, 3)
        self.assertEqual(target.read_bytes(), b'{"target":true}\n')

    def test_invalid_ledger_writes_structured_error_to_reserved_result(self):
        ledger = self.root / "ledger.json"
        ledger.write_text("not JSON", encoding="utf-8")
        result = self.root / "result.json"
        code = run(ledger, result, deadline(), {})
        record = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(code, 3)
        self.assertEqual(record["status"], "error")
        self.assertFalse(record["ready"])
        self.assertEqual(record["error_type"], "JSONDecodeError")
        self.assertTrue(all(value is False for value in record["side_effects"].values()))

    def test_result_reservation_error_is_structured_and_side_effect_free(self):
        result = self.root / "missing-parent" / "result.json"
        code = run(self.root / "missing-ledger.json", result, deadline(), {})
        self.assertEqual(code, 3)
        self.assertFalse(result.exists())

    def test_ready_run_writes_mode_600_result(self):
        environment = self.prepare_ready()
        ledger = self.root / "ledger.json"
        ledger.write_text(json.dumps(self.ledger), encoding="utf-8")
        result = self.root / "result.json"
        with patch("src.swe_lancer_admission.FIXED_SOURCE_PINS", self.control_source_pins):
            code = run(ledger, result, deadline(), environment)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(result.read_text(encoding="utf-8"))["ready"])
        self.assertEqual(os.stat(result).st_mode & 0o777, 0o600)

    def test_template_preserves_fixed_public_selection_and_image_digest(self):
        value, _fingerprint = load_ledger(TEMPLATE)
        self.assertEqual(
            value["selection"],
            {
                "task_id": "28565_1001",
                "split": "diamond",
                "task_type": "ic_swe",
                "task_count": 1,
            },
        )
        self.assertEqual(value["sandbox"]["image_manifest_digest"], FIXED_IMAGE_DIGEST)
        self.assertEqual(value["sandbox"]["image_reference"], FIXED_IMAGE_REFERENCE)

    def test_hosted_offline_smoke_is_exact_secret_free_and_fail_closed(self):
        workflow = OFFLINE_SMOKE_WORKFLOW.read_text(encoding="utf-8")
        for required in (
            "github.event.pull_request.head.repo.full_name == github.repository",
            "runs-on: ubuntu-24.04",
            "timeout-minutes: 45",
            "REQUIRED_FREE_BYTES: \"34000000000\"",
            "COMPRESSED_LAYER_BYTES: \"6419837118\"",
            FIXED_IMAGE_DIGEST,
            "sha256:3ac386d8f793eb2c3fdef76766b551bb2c04da8b7dd9703a01b561c293b82400",
            "test -z \"${OPENAI_API_KEY:-}\"",
            "test -z \"${SWE_LANCER_DOCKER_HOST:-}\"",
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
            "--pids-limit 64",
            "--memory 512m",
            "--cpus 1",
            "test ! -e /sys/class/net/eth0",
            "provider_model_api_grader_calls\\\":0",
            "survivor_containers\\\":0",
            "image_present_after_cleanup\\\":false",
            "docker image rm -f",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)
        for forbidden in (
            "${{ secrets.",
            "docker login",
            "/tmp/",
            "/home/",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, workflow)
        for environment_name in ("OPENAI_API_KEY", "SWE_LANCER_DOCKER_HOST"):
            with self.subTest(environment_name=environment_name):
                self.assertNotRegex(
                    workflow,
                    rf"(?m)^\s+{environment_name}\s*:",
                )

    def test_sanitized_evaluation_preserves_no_trace_boundary(self):
        value = json.loads(EVALUATION.read_text(encoding="utf-8"))
        validate_public_evaluation(value)
        self.assertFalse(value["trace_obtained"])
        self.assertEqual(value["attempt"]["exit_code"], 2)
        self.assertEqual(sum(value["counts"].values()), 0)

    def test_evaluation_rejects_trace_promotion(self):
        value = json.loads(EVALUATION.read_text(encoding="utf-8"))
        value["trace_obtained"] = True
        with self.assertRaisesRegex(ValueError, "deferred no-trace"):
            validate_public_evaluation(value)

    def test_evaluation_rejects_missing_zero_denominator_and_started_provider(self):
        value = json.loads(EVALUATION.read_text(encoding="utf-8"))
        del value["counts"]["tool_results"]
        with self.assertRaisesRegex(ValueError, "trace count"):
            validate_public_evaluation(value)

        value = json.loads(EVALUATION.read_text(encoding="utf-8"))
        value["direct_observations"]["provider_called"] = True
        with self.assertRaisesRegex(ValueError, "direct-observation"):
            validate_public_evaluation(value)

    def test_evaluation_rejects_private_paths(self):
        value = json.loads(EVALUATION.read_text(encoding="utf-8"))
        value["claim_boundary"] = "/tmp/private/raw-trace.json"
        with self.assertRaisesRegex(ValueError, "private-path"):
            validate_public_evaluation(value)

    def test_sanitized_report_preserves_outcome_counts_and_limits(self):
        report = REPORT.read_text(encoding="utf-8")
        for required in (
            "**보류**",
            "4.417423510초",
            "exit 2",
            "logical model request | 0",
            "provider HTTP attempt | 0",
            "tool call / result | 0 / 0",
            "trace event | 0",
            "provider usage record | 0",
            "실제 trace와 grader 결과는 없다",
            "USD 20.00",
            "18/18",
            "4/4",
        ):
            self.assertIn(required, report)

    def test_sanitized_report_links_resolve_and_private_markers_are_absent(self):
        report = REPORT.read_text(encoding="utf-8")
        for relative in (
            "../../ledgers/swe-lancer.template.json",
            "../../src/swe_lancer_admission.py",
            "../../data/experiment/swe-lancer-candidate-evaluation.json",
        ):
            self.assertTrue((REPORT.parent / relative).resolve().is_file())
        for marker in ("/tmp/", "/home/", "Authorization:", "Bearer "):
            self.assertNotIn(marker, report)


if __name__ == "__main__":
    unittest.main()
