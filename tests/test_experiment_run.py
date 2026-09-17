from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

import run as entrypoint
from src.contracts import validate
from src.experiment_run import _native_result, load_request, run_request


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "a" * 40


class ExperimentRequestTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".cache").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="experiment-request-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.static = yaml.safe_load((ROOT / "examples/experiment/static.yaml").read_text())
        self.native = yaml.safe_load((ROOT / "examples/experiment/native.yaml").read_text())
        self.environment = patch.dict(os.environ, {"SOURCE_COMMIT": SOURCE_COMMIT}, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write(self, value: dict, name: str = "request.yaml") -> Path:
        path = self.directory / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def test_examples_bind_to_the_exact_low_level_ledgers(self):
        for name in ("static", "native"):
            resolved = load_request(ROOT / f"examples/experiment/{name}.yaml")
            self.assertEqual(resolved.ledger_sha256, resolved.request["low_level_ledger"]["sha256"])
            self.assertEqual(resolved.source_commit, SOURCE_COMMIT)

    def test_missing_field_wrong_type_and_changed_hash_are_rejected(self):
        mutations = []
        missing = deepcopy(self.static)
        del missing["input"]
        mutations.append(missing)
        wrong_type = deepcopy(self.static)
        wrong_type["execution"]["concurrency"] = "one"
        mutations.append(wrong_type)
        wrong_hash = deepcopy(self.static)
        wrong_hash["low_level_ledger"]["sha256"] = "0" * 64
        mutations.append(wrong_hash)
        for index, value in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                load_request(self.write(value, f"invalid-{index}.yaml"))

    def test_direct_endpoint_or_secret_field_is_rejected(self):
        direct_url = deepcopy(self.native)
        direct_url["provider"]["endpoint_env"] = "https://provider.example/v1"
        direct_secret = deepcopy(self.native)
        direct_secret["model"]["settings"]["api_key"] = "not-a-real-secret"
        for index, value in enumerate((direct_url, direct_secret)):
            with self.subTest(index=index), self.assertRaises(ValueError):
                load_request(self.write(value, f"secret-{index}.yaml"))

    def test_native_missing_endpoint_fails_without_entering_lower_runner(self):
        with patch.dict(os.environ, {"FOUNDRY_ENDPOINT": ""}), patch("src.native_run.main") as lower:
            result, code = run_request(ROOT / "examples/experiment/native.yaml")
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["completion"]["technical_status"], "incomplete")
        self.assertNotIn("http", json.dumps(result).lower())
        lower.assert_not_called()

    def test_native_default_is_no_call_preflight(self):
        def checked(arguments):
            self.assertIn("--check", arguments)
            self.assertNotIn("--execute", arguments)
            print(json.dumps({"status": "local_preflight_passed", "model_calls": 0}))
            return 0

        with patch.dict(os.environ, {"FOUNDRY_ENDPOINT": "https://provider.example/v1"}), \
             patch("src.native_run.main", side_effect=checked) as lower:
            result, code = run_request(ROOT / "examples/experiment/native.yaml")
        self.assertEqual(code, 0)
        self.assertEqual(result["outcome"], "preflight_passed")
        self.assertEqual(result["provider_usage"]["status"], "not_measured")
        self.assertNotIn("provider.example", json.dumps(result))
        lower.assert_called_once()

    def test_native_execute_needs_separate_yaml_approval(self):
        with patch.dict(os.environ, {"FOUNDRY_ENDPOINT": "https://provider.example/v1"}), \
             patch("src.native_run.main") as lower:
            result, code = run_request(ROOT / "examples/experiment/native.yaml", execute=True)
        self.assertEqual(code, 3)
        self.assertIn("approval", result["error"]["message"].lower())
        lower.assert_not_called()

    def test_lower_level_technical_failure_stays_incomplete_not_wrong_answer(self):
        def failed(_arguments):
            print("synthetic low-level failure", file=__import__("sys").stderr)
            return 2

        with patch("src.static_run.main", side_effect=failed):
            result, code = run_request(ROOT / "examples/experiment/static.yaml")
        self.assertEqual(code, 3)
        self.assertEqual(result["outcome"], "technical_incomplete")
        self.assertEqual(result["quality"]["status"], "not_measured")
        validate(result, "experiment-result.schema.json")

    def test_run_py_dispatches_experiment_without_native_or_static_fallthrough(self):
        with patch("sys.argv", ["run.py", "experiment", "--verify-result", "examples/experiment/static-result.json"]), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(entrypoint.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "verified")

    def test_example_results_validate_and_preserve_unknowns_as_null(self):
        for name in ("static-result.json", "native-preflight-result.json"):
            result = json.loads((ROOT / "examples/experiment" / name).read_bytes())
            validate(result, "experiment-result.schema.json")
            self.assertIsNone(result["lineage"]["source_sha256"])
            self.assertIsNone(result["provider_usage"]["input_tokens"])
            self.assertFalse(result["labels"]["measured"])
            self.assertEqual(result["status"], "checked")

    def test_execute_preserves_the_yaml_and_summary_hashes(self):
        summary = {
            "run_id": "static-test",
            "source_sha256": "b" * 64,
            "measured_local": {
                "units": {"message_content_tokens": "tokens"},
                "before": {"message_content_tokens": 2},
                "after": {"message_content_tokens": 1},
            },
            "artifacts": {},
        }
        (self.directory / "summary.json").write_text(json.dumps(summary))

        def completed(_arguments):
            print(json.dumps({"directory": str(self.directory)}))
            return 0

        with patch("src.static_run.main", side_effect=completed):
            result, code = run_request(
                ROOT / "examples/experiment/static.yaml",
                execute=True,
            )
        self.assertEqual(code, 0)
        copied = self.directory / "experiment-request.yaml"
        self.assertEqual(
            copied.read_bytes(),
            (ROOT / "examples/experiment/static.yaml").read_bytes(),
        )
        self.assertEqual(
            result["artifacts"]["experiment-request.yaml"],
            result["lineage"]["config_sha256"],
        )
        self.assertEqual(
            result["artifacts"]["summary.json"],
            __import__("hashlib").sha256(
                (self.directory / "summary.json").read_bytes()
            ).hexdigest(),
        )
        validate(result, "experiment-result.schema.json")

    def test_invalid_request_cli_error_is_json_without_a_local_path(self):
        missing = self.directory / "missing.yaml"
        errors = io.StringIO()
        with patch("sys.argv", ["run.py", "experiment", str(missing)]), patch(
            "sys.stderr",
            errors,
        ):
            self.assertEqual(entrypoint.main(), 2)
        payload = json.loads(errors.getvalue())
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["outcome"], "technical_incomplete")
        self.assertNotIn(str(self.directory), payload["error"]["message"])

    def test_native_inconclusive_is_a_complete_measurement_not_a_technical_failure(self):
        result = json.loads((ROOT / "examples/experiment/native-preflight-result.json").read_bytes())
        (self.directory / "summary.json").write_text(json.dumps({
            "status": "inconclusive",
            "run_id": "native-inconclusive",
            "trials": [],
            "artifact_manifest_sha256": "b" * 64,
        }))
        (self.directory / "provenance.json").write_text(json.dumps({"source_sha256": "c" * 64}))
        _native_result(result, self.directory)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["outcome"], "measurement_completed")
        self.assertEqual(result["quality"]["status"], "aggregate_measured")
        self.assertEqual(result["completion"], {
            "technical_status": "complete", "operator_status": "not_stopped",
        })
        self.assertIsNone(result["error"])
        validate(result, "experiment-result.schema.json")

    def test_native_operator_stop_stays_quality_unknown(self):
        result = json.loads((ROOT / "examples/experiment/native-preflight-result.json").read_bytes())
        (self.directory / "summary.json").write_text(json.dumps({
            "status": "stopped",
            "run_id": "native-stopped",
            "trials": [],
            "artifact_manifest_sha256": "b" * 64,
        }))
        (self.directory / "provenance.json").write_text(json.dumps({"source_sha256": "c" * 64}))
        _native_result(result, self.directory)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["outcome"], "technical_incomplete")
        self.assertEqual(result["quality"]["status"], "unknown")
        self.assertEqual(result["completion"], {
            "technical_status": "incomplete", "operator_status": "stopped",
        })
        self.assertEqual(result["error"]["category"], "operator_stopped")
        validate(result, "experiment-result.schema.json")


if __name__ == "__main__":
    unittest.main()
