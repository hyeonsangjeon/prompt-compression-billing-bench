from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

import run as entrypoint
from src.benchmark_run import load_benchmark_request, run_benchmark_request
from src.contracts import validate


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "a" * 40


class BenchmarkRunTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "runs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="benchmark-request-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.request = yaml.safe_load((ROOT / "examples/experiment/benchmark.yaml").read_text())
        self.request["output"] = (self.directory / "result.json").relative_to(ROOT).as_posix()

    def write_request(self, value: dict, name: str = "request.yaml") -> Path:
        path = self.directory / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def test_public_yaml_contains_only_the_simple_user_choices(self):
        request = yaml.safe_load((ROOT / "examples/experiment/benchmark.yaml").read_text())
        self.assertEqual(set(request), {
            "schema_version", "experiment", "endpoint_env", "benchmark", "model", "condition", "output",
        })
        resolved = load_benchmark_request(ROOT / "examples/experiment/benchmark.yaml")
        self.assertEqual(resolved.request["benchmark"]["task"], "cancel-async-tasks")
        self.assertEqual(resolved.reference_ledger["replay"]["require_complete_capture"], True)

    def test_readme_no_call_validation_record_matches_sources_and_boundaries(self):
        record = json.loads((ROOT / "data/experiment/readme-benchmark-validation-20260920.json").read_bytes())
        bridge = json.loads((ROOT / "data/experiment/readme-benchmark-validation-20260920-accountless.json").read_bytes())
        self.assertEqual(record["kind"], "readme_benchmark_no_call_validation")
        self.assertEqual(
            hashlib.sha256((ROOT / bridge["base_record"]["path"]).read_bytes()).hexdigest(),
            bridge["base_record"]["sha256"],
        )
        self.assertFalse(bridge["commands_reexecuted"])
        self.assertFalse(bridge["provider_execution_performed"])
        historical_changed_sources = {
            "schemas/experiment-result.schema.json",
            "src/benchmark_run.py",
            "src/experiment_run.py",
        }
        for relative, expected in record["source_files"].items():
            with self.subTest(relative=relative):
                current = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                if relative in historical_changed_sources:
                    self.assertNotEqual(current, expected)
                else:
                    self.assertEqual(current, expected)
        readme = (ROOT / "README.md").read_text()
        section = bridge["current_readme"]
        start = readme.index(section["section_heading"])
        end = readme.index("\n## ", start + len(section["section_heading"]))
        self.assertEqual(
            json.loads((ROOT / "data/experiment/readme-benchmark-validation.json").read_bytes())[
                "readme_execution_section"
            ]["sha256"],
            "85fca6f62890e2c0c908e96410774c8873709f7abb22007a689a7fa44b8dd0af",
        )
        self.assertEqual(
            section["section_sha256"],
            "1013fe55b4fad6db1330c46c2664c5a6fdbc058dad2261f9071b90aaf97202bf",
        )
        self.assertNotEqual(
            hashlib.sha256(readme[start:end].encode()).hexdigest(),
            section["section_sha256"],
        )
        self.assertIn("provider execution safety policy", readme[start:end])
        codes = {item["stage"]: item["exit_code"] for item in record["commands"]}
        self.assertEqual(codes, {
            "install": 0,
            "no_call_preflight": 0,
            "verify_preflight_json": 0,
            "missing_endpoint_error": 3,
            "verify_error_json": 0,
        })
        self.assertEqual(record["outputs"]["preflight"]["outcome"], "preflight_passed")
        self.assertTrue(record["outputs"]["preflight"]["clean_checkout"])
        self.assertEqual(record["outputs"]["missing_endpoint"]["outcome"], "technical_incomplete")
        self.assertFalse(record["provider_execution"]["performed"])
        self.assertIsNone(record["provider_execution"]["wall_time_seconds"])

    def test_previous_readme_validation_record_is_preserved(self):
        historical = ROOT / "data/experiment/readme-benchmark-validation.json"
        self.assertEqual(
            hashlib.sha256(historical.read_bytes()).hexdigest(),
            "7c41509855045881ea37e04d42d839d1fe42f080d44054310845f6da1b4f08cb",
        )
        current_historical = ROOT / "data/experiment/readme-benchmark-validation-20260920.json"
        self.assertEqual(
            hashlib.sha256(current_historical.read_bytes()).hexdigest(),
            "e32f242ce0148d9fdbb274c15d7039e45a5ecf73768641dea388fcb478a43e77",
        )

    def test_missing_wrong_type_url_and_unknown_task_are_rejected(self):
        missing = deepcopy(self.request)
        del missing["model"]
        wrong_type = deepcopy(self.request)
        wrong_type["benchmark"]["task"] = ["cancel-async-tasks"]
        direct_url = deepcopy(self.request)
        direct_url["endpoint_env"] = "https://example.invalid"
        unknown_task = deepcopy(self.request)
        unknown_task["benchmark"]["task"] = "not-a-terminal-bench-task"
        for index, request in enumerate((missing, wrong_type, direct_url, unknown_task)):
            with self.subTest(index=index), self.assertRaises(ValueError):
                load_benchmark_request(self.write_request(request, f"invalid-{index}.yaml"))

    def test_default_preflight_makes_no_lower_runner_call_and_writes_json(self):
        request_path = self.write_request(self.request)
        sys.modules.pop("src.screening_run", None)
        with patch("src.benchmark_run._source_commit", return_value=SOURCE_COMMIT):
            result, code = run_benchmark_request(request_path)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "checked")
        self.assertEqual(result["quality"]["status"], "not_measured")
        self.assertEqual(result["provider_usage"]["status"], "not_measured")
        self.assertFalse(result["labels"]["synthetic"])
        self.assertIsNone(result["resolved_contract"]["execution_ledger_sha256"])
        self.assertNotIn("src.screening_run", sys.modules)
        saved = json.loads((ROOT / self.request["output"]).read_bytes())
        self.assertEqual(saved, result)
        validate(saved, "experiment-result.schema.json")

    def test_execute_without_endpoint_is_json_technical_failure(self):
        request_path = self.write_request(self.request)
        sys.modules.pop("src.screening_run", None)
        with patch("src.benchmark_run._source_commit", return_value=SOURCE_COMMIT), \
             patch.dict(os.environ, {"FOUNDRY_ENDPOINT": ""}):
            result, code = run_benchmark_request(request_path, execute=True)
        self.assertEqual(code, 3)
        self.assertEqual(result["outcome"], "technical_incomplete")
        self.assertEqual(result["quality"]["status"], "not_measured")
        self.assertIn("FOUNDRY_ENDPOINT", result["error"]["message"])
        self.assertNotIn("src.screening_run", sys.modules)
        validate(result, "experiment-result.schema.json")

    def test_dirty_checkout_is_a_json_preflight_failure(self):
        request_path = self.write_request(self.request)
        git_results = [str(ROOT).encode() + b"\n", SOURCE_COMMIT.encode() + b"\n", b" M src/example.py\n"]
        with patch("src.benchmark_run._git", side_effect=git_results):
            result, code = run_benchmark_request(request_path)
        self.assertEqual(code, 3)
        self.assertEqual(result["error"]["category"], "preflight_error")
        self.assertIn("not clean", result["error"]["message"])
        self.assertFalse(result["resolved_contract"]["clean_checkout"])
        validate(result, "experiment-result.schema.json")

    def test_execute_uses_the_existing_single_task_runner_and_maps_complete_evidence(self):
        request_path = self.write_request(self.request)
        operational = self.directory / "operational.toml"
        text = (ROOT / "ledgers/screening.template.toml").read_text()
        text = text.replace('inventory_sha256 = "' + "0" * 64 + '"', 'inventory_sha256 = "' + "b" * 64 + '"')
        text = text.replace('deployment_isolation_reference = ""', 'deployment_isolation_reference = "test isolation record"')
        text = text.replace("preregistered = false", "preregistered = true")
        text = text.replace("execution_authorized = false", "execution_authorized = true")
        text = text.replace("cost_limits_approved = false", "cost_limits_approved = true")
        text = text.replace("max_api_cost_usd_per_attempt = 0", "max_api_cost_usd_per_attempt = 1")
        text = text.replace("max_api_cost_usd_per_run = 0", "max_api_cost_usd_per_run = 10")
        deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        text = text.replace('run_deadline_utc = ""', f'run_deadline_utc = "{deadline}"')
        text = text.replace('reference = ""', 'reference = "test operator approval"')
        operational.write_text(text)

        run_directory = self.directory / "screening-result"
        attempt_directory = run_directory / "attempts" / "attempt-1"
        attempt_directory.mkdir(parents=True)
        (run_directory / "inputs").mkdir()
        (run_directory / "summary.json").write_text(json.dumps({
            "run_id": "screening-diagnostic-test",
            "status": "complete",
        }))
        (run_directory / "inputs" / "provenance.json").write_text(json.dumps({"source_sha256": "c" * 64}))
        (attempt_directory / "attempt.json").write_text(json.dumps({
            "evidence_disposition": "quality_result_complete",
            "classification": {
                "result": "pass",
                "termination": None,
                "provider_cost": {"calculated_cost_usd": 0.25},
                "metrics": {
                    "provider_tokens": {
                        "unknown_usage_attempts": 0,
                        "input_tokens": 20,
                        "cached_input_tokens": 3,
                        "output_tokens": 5,
                    },
                    "local_tokens": {"input_tokens": 18, "output_tokens": 4},
                },
            },
        }))

        def completed(arguments):
            self.assertIn("--diagnose-task", arguments)
            self.assertIn("cancel-async-tasks", arguments)
            self.assertIn(SOURCE_COMMIT, arguments)
            return {"directory": str(run_directory), "status": "complete"}

        environment = {
            "FOUNDRY_ENDPOINT": "configured",
            "SCREENING_OPERATIONAL_LEDGER": str(operational),
            "PROVIDER_RPM_LIMIT": "17",
            "PROVIDER_TPM_LIMIT": "1700",
        }
        with patch("src.benchmark_run._source_commit", return_value=SOURCE_COMMIT), \
             patch.dict(os.environ, environment, clear=False), \
             patch("src.benchmark_run._invoke_screening", side_effect=completed) as lower:
            result, code = run_benchmark_request(request_path, execute=True)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["quality"]["status"], "pass")
        self.assertEqual(result["provider_usage"]["input_tokens"], 20)
        self.assertEqual(result["cost"]["calculated_usd"], 0.25)
        self.assertFalse(result["cost"]["invoice_reconciled"])
        self.assertIsNotNone(result["resolved_contract"]["execution_ledger_sha256"])
        lower.assert_called_once()
        validate(result, "experiment-result.schema.json")

    def test_screening_adapter_calls_the_existing_main(self):
        from src.benchmark_run import _invoke_screening

        def existing_main(arguments):
            self.assertEqual(arguments, ["ledger.toml", "--diagnose-task", "task"])
            print(json.dumps({"directory": "runs/example", "status": "complete"}))
            return 0

        module = SimpleNamespace(main=existing_main)
        with patch.dict(sys.modules, {"src.screening_run": module}):
            result = _invoke_screening(["ledger.toml", "--diagnose-task", "task"])
        self.assertEqual(result["status"], "complete")

    def test_run_py_experiment_dispatches_schema_version_two(self):
        request_path = self.write_request(self.request)
        output = io.StringIO()
        expected = {"status": "checked", "run_id": "test"}
        with patch("sys.argv", ["run.py", "experiment", str(request_path)]), \
             patch("src.benchmark_run.run_benchmark_request", return_value=(expected, 0)), \
             patch("sys.stdout", output):
            self.assertEqual(entrypoint.main(), 0)
        self.assertEqual(json.loads(output.getvalue()), expected)

    def test_unknown_task_cli_error_is_json_without_a_local_path(self):
        invalid = deepcopy(self.request)
        invalid["benchmark"]["task"] = "not-a-terminal-bench-task"
        request_path = self.write_request(invalid)
        errors = io.StringIO()
        with patch("sys.argv", ["run.py", "experiment", str(request_path)]), patch("sys.stderr", errors):
            self.assertEqual(entrypoint.main(), 2)
        payload = json.loads(errors.getvalue())
        self.assertEqual(payload["outcome"], "technical_incomplete")
        self.assertEqual(payload["error"]["category"], "request_error")
        self.assertNotIn(str(self.directory), payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()
