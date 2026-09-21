from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.cache_runtime_context import (
    DEFINITION_PATH,
    EXPECTED_COMMAND,
    EXPECTED_INPUT_ENVIRONMENTS,
    IDENTITY_FIELDS,
    ROOT,
    load_definition,
    probe,
    run,
)


ATTESTATION_TEMPLATE = ROOT / "fixtures/cache-reuse/runtime-context-attestation.template.json"


class CacheRuntimeContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        self.launcher = self.root / "src/cache_runtime_context.py"
        self.launcher.write_bytes(b"synthetic project launcher\n")
        launcher_sha256 = hashlib.sha256(self.launcher.read_bytes()).hexdigest()
        self.definition = {
            "schema_version": 1,
            "kind": "cache_reuse_runtime_context_definition",
            "SANCTIONED_PROJECT_RUNTIME_CONTEXT_COMMAND": deepcopy(EXPECTED_COMMAND),
            "SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_KIND": "repository_regular_file",
            "SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_SOURCE": "src/cache_runtime_context.py",
            "SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_SHA256": launcher_sha256,
            "SANCTIONED_PROJECT_RUNTIME_CONTEXT_OWNER": "runtime_owner",
            "input_environment_names": deepcopy(EXPECTED_INPUT_ENVIRONMENTS),
            "inline_values": False,
            "provider_model_api_calls": 0,
        }
        self.definition_path = self.root / "definition.json"
        self.write_definition()
        self.now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
        self.attestation_path = self.root / "attestation.json"
        self.write_attestation()
        self.output = self.root / "doctor.json"

    def write_definition(self):
        self.definition_path.write_text(
            json.dumps(self.definition, sort_keys=True) + "\n", encoding="utf-8"
        )

    def attestation(self):
        definition_sha256 = hashlib.sha256(self.definition_path.read_bytes()).hexdigest()
        value = {
            "schema_version": 1,
            "kind": "cache_reuse_runtime_context_attestation",
            "observed_at_utc": (self.now - timedelta(minutes=1)).isoformat(),
            "valid_through_utc": (self.now + timedelta(minutes=5)).isoformat(),
            "definition_sha256": definition_sha256,
        }
        for field in IDENTITY_FIELDS:
            value[field] = deepcopy(self.definition[field])
        return value

    def write_attestation(self, value=None):
        self.attestation_path.write_text(
            json.dumps(self.attestation() if value is None else value, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def environment(self):
        return {
            "CACHE_RUNTIME_PYTHON": "/private/locked/python",
            "CACHE_RUNTIME_CONTEXT_ATTESTATION": str(self.attestation_path),
            "CACHE_REUSE_LEDGER": str(ROOT / "ledgers/cache-reuse.template.json"),
            "CACHE_RUNTIME_FACTS": str(ROOT / "fixtures/cache-reuse/runtime-facts.template.json"),
            "NATIVE_CACHE_LEDGER": str(ROOT / "ledgers/native.template.toml"),
            "CACHE_REUSE_DOCTOR": str(self.output),
            "FOUNDRY_ENDPOINT": "secret-endpoint-value",
        }

    def check(self, environment):
        return probe(
            environment,
            root=self.root,
            definition_path=self.definition_path,
            current_time=self.now,
        )

    def test_project_definition_hashes_the_actual_launcher(self):
        definition, definition_fingerprint, source_fingerprint = load_definition(
            DEFINITION_PATH, ROOT
        )
        self.assertEqual(definition[IDENTITY_FIELDS[2]], "src/cache_runtime_context.py")
        self.assertEqual(definition[IDENTITY_FIELDS[3]], source_fingerprint["sha256"])
        self.assertEqual(len(definition_fingerprint["sha256"]), 64)

    def test_public_attestation_template_is_hash_bound_but_expired(self):
        environment = self.environment()
        environment["CACHE_RUNTIME_CONTEXT_ATTESTATION"] = str(ATTESTATION_TEMPLATE)
        with patch("src.cache_runtime_context.doctor") as doctor_call:
            result = probe(environment, current_time=self.now)
        self.assertEqual(result["context_status"], "stale")
        self.assertEqual(result["missing_or_invalid"], ["context_attestation.freshness"])
        doctor_call.assert_not_called()

    def test_missing_attestation_stops_before_doctor(self):
        environment = self.environment()
        del environment["CACHE_RUNTIME_CONTEXT_ATTESTATION"]
        with patch("src.cache_runtime_context.doctor") as doctor_call:
            result = self.check(environment)
        self.assertEqual(result["context_status"], "missing")
        self.assertEqual(
            result["missing_or_invalid"],
            ["environment.CACHE_RUNTIME_CONTEXT_ATTESTATION.present"],
        )
        doctor_call.assert_not_called()

    def test_stale_attestation_stops_before_runtime_inputs_or_doctor(self):
        value = self.attestation()
        value["observed_at_utc"] = (self.now - timedelta(hours=2)).isoformat()
        value["valid_through_utc"] = (self.now - timedelta(hours=1)).isoformat()
        self.write_attestation(value)
        with patch("src.cache_runtime_context.doctor") as doctor_call:
            result = self.check(self.environment())
        self.assertEqual(result["context_status"], "stale")
        self.assertEqual(result["side_effects"]["runtime_input_files_read"], 0)
        doctor_call.assert_not_called()

    def test_wrong_source_attestation_stops_before_doctor(self):
        value = self.attestation()
        value["SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_SOURCE"] = "src/other.py"
        self.write_attestation(value)
        with patch("src.cache_runtime_context.doctor") as doctor_call:
            result = self.check(self.environment())
        self.assertEqual(result["context_status"], "wrong_source")
        self.assertIn("IDENTITY_SOURCE", result["missing_or_invalid"][0])
        doctor_call.assert_not_called()

    def test_verified_context_runs_only_doctor_and_never_records_values(self):
        environment = self.environment()
        result = self.check(environment)
        serialized = json.dumps(result, sort_keys=True)
        self.assertEqual(result["context_status"], "verified")
        self.assertEqual(result["decision"], "no_go")
        self.assertEqual(result["side_effects"]["doctor_invocations"], 1)
        self.assertEqual(result["side_effects"]["provider_model_api_calls"], 0)
        self.assertEqual(result["side_effects"]["network_calls"], 0)
        self.assertFalse(result["side_effects"]["provider_dispatch_started"])
        for value in environment.values():
            self.assertNotIn(value, serialized)
        self.assertTrue(result["doctor"]["environment_presence"]["FOUNDRY_ENDPOINT"])

    def test_missing_runtime_input_stops_before_doctor(self):
        environment = self.environment()
        del environment["NATIVE_CACHE_LEDGER"]
        with patch("src.cache_runtime_context.doctor") as doctor_call:
            result = self.check(environment)
        self.assertEqual(result["context_status"], "missing")
        self.assertEqual(result["side_effects"]["runtime_input_files_read"], 0)
        doctor_call.assert_not_called()

    def test_no_clobber_preserves_existing_output_without_reading_inputs(self):
        environment = self.environment()
        sentinel = b'{"sentinel":true}\n'
        self.output.write_bytes(sentinel)
        with patch("src.cache_runtime_context.probe") as probe_call:
            exit_code, result = run(
                environment,
                root=self.root,
                definition_path=self.definition_path,
                current_time=self.now,
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(result["missing_or_invalid"], ["output.no_clobber"])
        self.assertEqual(self.output.read_bytes(), sentinel)
        probe_call.assert_not_called()

    def test_missing_output_stops_before_definition_or_inputs(self):
        environment = self.environment()
        del environment["CACHE_REUSE_DOCTOR"]
        with patch("src.cache_runtime_context.probe") as probe_call:
            exit_code, result = run(
                environment,
                root=self.root,
                definition_path=self.definition_path,
                current_time=self.now,
            )
        self.assertEqual(exit_code, 3)
        self.assertEqual(result["context_status"], "missing")
        self.assertEqual(
            result["missing_or_invalid"], ["environment.CACHE_REUSE_DOCTOR.present"]
        )
        probe_call.assert_not_called()

    def test_fresh_context_result_is_private_mode_and_doctor_no_go_exit_three(self):
        exit_code, result = run(
            self.environment(),
            root=self.root,
            definition_path=self.definition_path,
            current_time=self.now,
        )
        self.assertEqual(exit_code, 3)
        self.assertEqual(result["context_status"], "verified")
        self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.output.read_text()), result)

    def test_source_hash_drift_is_a_source_error(self):
        self.launcher.write_bytes(b"changed launcher\n")
        result = self.check(self.environment())
        self.assertEqual(result["failure_class"], "source")
        self.assertEqual(result["context_status"], "wrong_source")
        self.assertEqual(result["side_effects"]["doctor_invocations"], 0)


if __name__ == "__main__":
    unittest.main()
