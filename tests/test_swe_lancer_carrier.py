from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import src.swe_lancer_admission as admission
import src.swe_lancer_carrier as carrier


ATTESTATION_TEMPLATE = (
    carrier.ROOT / "fixtures/swe-lancer/carrier-attestation.template.json"
)


class ProtectedEnvironment(dict):
    protected = {"OPENAI_API_KEY", "SWE_LANCER_DOCKER_HOST"}

    def get(self, key, default=None):
        if key in self.protected:
            raise AssertionError(f"value read forbidden for {key}")
        return super().get(key, default)

    def __getitem__(self, key):
        if key in self.protected:
            raise AssertionError(f"value read forbidden for {key}")
        return super().__getitem__(key)


class SweLancerCarrierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        self.launcher = self.root / "src/swe_lancer_carrier.py"
        self.launcher.write_bytes(b"synthetic SWE-Lancer carrier\n")
        self.definition = {
            "schema_version": 1,
            "kind": "swe_lancer_private_carrier_definition",
            "SANCTIONED_SWE_LANCER_CARRIER_COMMAND": deepcopy(carrier.EXPECTED_COMMAND),
            "SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_KIND": "repository_regular_file",
            "SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_SOURCE": "src/swe_lancer_carrier.py",
            "SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_SHA256": hashlib.sha256(
                self.launcher.read_bytes()
            ).hexdigest(),
            "SANCTIONED_SWE_LANCER_CARRIER_OWNER": "runtime_owner",
            "input_environment_names": deepcopy(carrier.EXPECTED_INPUT_ENVIRONMENTS),
            "admission_environment_names": deepcopy(
                carrier.EXPECTED_ADMISSION_ENVIRONMENTS
            ),
            "inline_values": False,
            "provider_model_api_grader_calls": 0,
        }
        self.definition_path = self.root / "definition.json"
        self.write_json(self.definition_path, self.definition)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.ledger = json.loads(
            (carrier.ROOT / "ledgers/swe-lancer.template.json").read_text(
                encoding="utf-8"
            )
        )
        self.environment = ProtectedEnvironment(
            {
                "SWE_LANCER_RUNTIME_PYTHON": "controlled-runtime-python",
                "OPENAI_API_KEY": "credential-sentinel-never-read",
                "SWE_LANCER_DOCKER_HOST": "endpoint-sentinel-never-read",
                "SWE_LANCER_DEADLINE_UTC": (
                    datetime.now(timezone.utc) + timedelta(seconds=4800)
                ).isoformat().replace("+00:00", "Z"),
            }
        )
        source_files = {
            "solver": b"controlled solver source\n",
            "catalog": b"controlled private catalog\n",
        }
        for pin in self.ledger["source"]["pins"]:
            path = self.root / pin["name"]
            path.write_bytes(source_files[pin["name"]])
            pin.update(admission.fingerprint(path))
            self.environment[pin["path_env"]] = str(path)
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
            self.write_json(path, {"reviewed": True})
            pin.update(admission.fingerprint(path))
            self.environment[pin["path_env"]] = str(path)
        self.ledger["provider"].update(
            {
                "reported_model_revision": "controlled-revision",
                "price_source_url": "https://example.invalid/reviewed-price-source",
                "price_source_revision_or_retrieved_at": "controlled-price-review",
                "input_usd_per_million_tokens": "1.00",
                "output_usd_per_million_tokens": "2.00",
            }
        )
        self.ledger["approval"].update(
            {
                "approval_record": "controlled-approval-record",
                "execution_approved": True,
            }
        )
        self.ledger_path = self.root / "admission-ledger.json"
        self.write_json(self.ledger_path, self.ledger)
        self.environment["SWE_LANCER_ADMISSION_LEDGER"] = str(self.ledger_path)
        self.receipt_paths = {
            "provider_contract_receipt": self.root / "provider-contract-receipt.json",
            "price_receipt": self.root / "price-receipt.json",
            "outbound_receipt": self.root / "outbound-receipt.json",
        }
        self.receipts = self.make_receipts()
        self.write_receipts()
        self.output = self.root / "carrier-result.json"
        self.environment["SWE_LANCER_ADMISSION_RESULT"] = str(self.output)
        self.attestation_path = self.root / "carrier-attestation.json"
        self.refresh_attestation()
        self.environment["SWE_LANCER_CARRIER_ATTESTATION"] = str(
            self.attestation_path
        )

    @staticmethod
    def write_json(path, value):
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def make_receipts(self):
        ledger_sha256 = admission.fingerprint(self.ledger_path)["sha256"]
        observed = (self.now - timedelta(minutes=1)).isoformat().replace(
            "+00:00", "Z"
        )
        valid_through = (self.now + timedelta(minutes=5)).isoformat().replace(
            "+00:00", "Z"
        )
        return {
            "provider_contract_receipt": {
                "schema_version": 1,
                "kind": "swe_lancer_provider_contract_receipt",
                "observed_at_utc": observed,
                "valid_through_utc": valid_through,
                "ledger_sha256": ledger_sha256,
                "provider_name": "openai",
                "model_setting": "openai/gpt-4o",
                "deployment_identity_sha256": hashlib.sha256(
                    b"controlled deployment identity"
                ).hexdigest(),
                "api_version": "controlled-api-version",
                "reported_model_revision": "controlled-revision",
                "credential_environment_name": "OPENAI_API_KEY",
                "endpoint_environment_name": "SWE_LANCER_DOCKER_HOST",
                "credential_permission_verified": True,
                "credential_value_recorded": False,
                "endpoint_value_recorded": False,
                "provider_model_api_calls": 0,
            },
            "price_receipt": {
                "schema_version": 1,
                "kind": "swe_lancer_fixed_price_receipt",
                "observed_at_utc": observed,
                "valid_through_utc": valid_through,
                "ledger_sha256": ledger_sha256,
                "currency": "USD",
                "input_usd_per_million_tokens": "1.00",
                "output_usd_per_million_tokens": "2.00",
                "price_source_url": "https://example.invalid/reviewed-price-source",
                "price_source_revision_or_retrieved_at": "controlled-price-review",
                "provider_model_api_calls": 0,
            },
            "outbound_receipt": {
                "schema_version": 1,
                "kind": "swe_lancer_outbound_cleanup_receipt",
                "observed_at_utc": observed,
                "valid_through_utc": valid_through,
                "ledger_sha256": ledger_sha256,
                "carrier_instance_identity_sha256": hashlib.sha256(
                    b"controlled carrier instance"
                ).hexdigest(),
                "runtime_kind": "controlled-container-runtime",
                "platform": "linux/amd64",
                "image_manifest_digest": admission.FIXED_IMAGE_DIGEST,
                "image_config_digest": carrier.FIXED_IMAGE_CONFIG_DIGEST,
                "paid_provider_outbound_verified": True,
                "cleanup_contract_verified": True,
                "credential_value_recorded": False,
                "endpoint_value_recorded": False,
                "provider_model_api_grader_calls": 0,
                "network_calls": 0,
                "survivor_count": 0,
            },
        }

    def write_receipts(self):
        for name, path in self.receipt_paths.items():
            self.write_json(path, self.receipts[name])
            self.environment[carrier.EXPECTED_INPUT_ENVIRONMENTS[name]] = str(path)

    def attestation(self):
        definition_sha256 = admission.fingerprint(self.definition_path)["sha256"]
        value = {
            "schema_version": 1,
            "kind": "swe_lancer_private_carrier_attestation",
            "observed_at_utc": (self.now - timedelta(minutes=1))
            .isoformat()
            .replace("+00:00", "Z"),
            "valid_through_utc": (self.now + timedelta(minutes=5))
            .isoformat()
            .replace("+00:00", "Z"),
            "definition_sha256": definition_sha256,
            "input_fingerprints": {
                "ledger": admission.fingerprint(self.ledger_path),
                **{
                    name: admission.fingerprint(path)
                    for name, path in self.receipt_paths.items()
                },
            },
        }
        for field in carrier.IDENTITY_FIELDS:
            value[field] = deepcopy(self.definition[field])
        return value

    def refresh_attestation(self, value=None):
        self.write_json(
            self.attestation_path,
            self.attestation() if value is None else value,
        )

    def refresh_ledger_bindings(self):
        self.write_json(self.ledger_path, self.ledger)
        ledger_sha256 = admission.fingerprint(self.ledger_path)["sha256"]
        for receipt in self.receipts.values():
            receipt["ledger_sha256"] = ledger_sha256
        self.write_receipts()
        self.refresh_attestation()

    def ready_admission_result(self):
        with patch.object(admission, "FIXED_SOURCE_PINS", self.control_source_pins):
            return admission.check_admission(
                self.ledger,
                admission.fingerprint(self.ledger_path),
                self.environment["SWE_LANCER_DEADLINE_UTC"],
                self.environment,
                presence_only_environment_names=frozenset(
                    {"OPENAI_API_KEY", "SWE_LANCER_DOCKER_HOST"}
                ),
            )

    def check(self, environment=None):
        with patch.object(
            admission, "FIXED_SOURCE_PINS", self.control_source_pins
        ):
            return carrier.probe(
                self.environment if environment is None else environment,
                root=self.root,
                definition_path=self.definition_path,
                current_time=self.now,
            )

    def test_project_definition_hashes_the_actual_carrier(self):
        definition, definition_fingerprint, source_fingerprint = carrier.load_definition(
            carrier.DEFINITION_PATH, carrier.ROOT
        )
        self.assertEqual(
            definition[carrier.IDENTITY_FIELDS[2]], "src/swe_lancer_carrier.py"
        )
        self.assertEqual(
            definition[carrier.IDENTITY_FIELDS[3]], source_fingerprint["sha256"]
        )
        self.assertEqual(len(definition_fingerprint["sha256"]), 64)

    def test_public_attestation_is_hash_bound_but_expired(self):
        environment = ProtectedEnvironment(
            {
                "SWE_LANCER_CARRIER_ATTESTATION": str(ATTESTATION_TEMPLATE),
            }
        )
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = carrier.probe(environment, current_time=self.now)
        self.assertEqual(result["context_status"], "stale")
        self.assertEqual(
            result["missing_or_invalid"], ["context_attestation.freshness"]
        )
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_missing_attestation_stops_before_admission(self):
        environment = ProtectedEnvironment(self.environment)
        del environment["SWE_LANCER_CARRIER_ATTESTATION"]
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = self.check(environment)
        self.assertEqual(result["context_status"], "missing")
        self.assertEqual(result["side_effects"]["runtime_input_files_read"], 0)
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_wrong_source_attestation_stops_before_admission(self):
        value = self.attestation()
        value["SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_SOURCE"] = "src/other.py"
        self.refresh_attestation(value)
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = self.check()
        self.assertEqual(result["context_status"], "wrong_source")
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_ready_context_binds_receipts_without_reading_secret_values(self):
        actual_check = admission.check_admission
        with patch.object(
            admission, "FIXED_SOURCE_PINS", self.control_source_pins
        ), patch(
            "src.swe_lancer_carrier.admission.check_admission",
            wraps=actual_check,
        ) as admission_call:
            result = carrier.probe(
                self.environment,
                root=self.root,
                definition_path=self.definition_path,
                current_time=self.now,
            )
        serialized = json.dumps(result, sort_keys=True)
        self.assertTrue(result["ready"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(admission_call.call_count, 1)
        self.assertEqual(result["side_effects"]["admission_invocations"], 1)
        self.assertEqual(result["side_effects"]["runtime_input_files_read"], 4)
        inactive_side_effects = {
            key: value
            for key, value in result["side_effects"].items()
            if key not in {"runtime_input_files_read", "admission_invocations"}
        }
        self.assertTrue(all(not value for value in inactive_side_effects.values()))
        self.assertNotIn("credential-sentinel-never-read", serialized)
        self.assertNotIn("endpoint-sentinel-never-read", serialized)
        self.assertNotIn(str(self.root), serialized)

    def test_invalid_pin_environment_is_rejected_before_value_or_file_read(self):
        self.ledger["source"]["pins"][0]["path_env"] = "OPENAI_API_KEY"
        self.refresh_ledger_bindings()
        result = self.check()
        self.assertFalse(result["ready"])
        self.assertIn("source.pins[0].path_env", result["missing_or_invalid"])
        self.assertEqual(result["side_effects"]["admission_invocations"], 1)

    def test_private_shaped_api_version_is_rejected_without_reflection(self):
        sentinel = "https://example.invalid/endpoint?token=SYNTHETIC_SENTINEL"
        self.receipts["provider_contract_receipt"]["api_version"] = sentinel
        self.write_receipts()
        self.refresh_attestation()
        result = self.check()
        self.assertFalse(result["ready"])
        self.assertEqual(
            result["missing_or_invalid"], ["provider_contract_receipt.api_version"]
        )
        self.assertNotIn(sentinel, json.dumps(result, sort_keys=True))

    def test_private_shaped_pin_name_is_rejected_without_reflection(self):
        sentinel = "/private/SYNTHETIC_PIN"
        self.ledger["source"]["pins"][0]["name"] = sentinel
        self.refresh_ledger_bindings()
        result = self.check()
        serialized = json.dumps(result, sort_keys=True)
        self.assertFalse(result["ready"])
        self.assertIn("source.pins[0].name", result["missing_or_invalid"])
        self.assertNotIn(sentinel, serialized)

    def test_private_shaped_image_digest_is_not_reflected(self):
        sentinel = "/private/SYNTHETIC_IMAGE_DIGEST"
        self.ledger["sandbox"]["image_manifest_digest"] = sentinel
        self.refresh_ledger_bindings()
        result = self.check()
        self.assertFalse(result["ready"])
        self.assertIn(
            "sandbox.image_manifest_digest", result["missing_or_invalid"]
        )
        self.assertIsNone(result["admission"]["sandbox"]["image_manifest_digest"])
        self.assertNotIn(sentinel, json.dumps(result, sort_keys=True))

    def test_private_shaped_revision_and_runtime_are_not_reflected(self):
        sentinel = "/private/SYNTHETIC_METADATA"
        self.ledger["provider"]["reported_model_revision"] = sentinel
        self.receipts["provider_contract_receipt"]["reported_model_revision"] = sentinel
        self.refresh_ledger_bindings()
        result = self.check()
        self.assertEqual(
            result["missing_or_invalid"],
            ["provider_contract_receipt.reported_model_revision"],
        )
        self.assertNotIn(sentinel, json.dumps(result, sort_keys=True))

        self.ledger["provider"]["reported_model_revision"] = "controlled-revision"
        self.receipts["provider_contract_receipt"][
            "reported_model_revision"
        ] = "controlled-revision"
        self.receipts["outbound_receipt"]["runtime_kind"] = sentinel
        self.refresh_ledger_bindings()
        result = self.check()
        self.assertEqual(
            result["missing_or_invalid"], ["outbound_receipt.runtime_kind"]
        )
        self.assertNotIn(sentinel, json.dumps(result, sort_keys=True))

    def test_downstream_side_effect_violation_preserves_typed_report(self):
        admission_result = self.ready_admission_result()
        admission_result["side_effects"]["network_used"] = True
        with patch(
            "src.swe_lancer_carrier.admission.check_admission",
            return_value=admission_result,
        ) as admission_call:
            result = self.check()
        self.assertEqual(admission_call.call_count, 1)
        self.assertFalse(result["ready"])
        self.assertEqual(result["missing_or_invalid"], ["admission.side_effects"])
        self.assertEqual(result["side_effects"]["admission_invocations"], 1)
        self.assertTrue(result["side_effects"]["network_used"])
        self.assertEqual(
            result["side_effects"]["provider_model_api_grader_calls"], 0
        )
        self.assertIsNone(result["admission"])

    def test_reported_provider_call_does_not_claim_zero_call_count(self):
        admission_result = self.ready_admission_result()
        admission_result["side_effects"]["provider_called"] = True
        with patch(
            "src.swe_lancer_carrier.admission.check_admission",
            return_value=admission_result,
        ):
            result = self.check()
        self.assertTrue(result["side_effects"]["provider_called"])
        self.assertIsNone(
            result["side_effects"]["provider_model_api_grader_calls"]
        )

    def test_malformed_effect_does_not_erase_valid_provider_report(self):
        admission_result = self.ready_admission_result()
        sentinel = "MALFORMED_SYNTHETIC_FLAG"
        admission_result["side_effects"]["provider_called"] = True
        admission_result["side_effects"]["network_used"] = sentinel
        with patch(
            "src.swe_lancer_carrier.admission.check_admission",
            return_value=admission_result,
        ) as admission_call:
            result = self.check()
        self.assertEqual(admission_call.call_count, 1)
        self.assertFalse(result["ready"])
        self.assertEqual(result["missing_or_invalid"], ["admission.side_effects"])
        self.assertEqual(result["side_effects"]["admission_invocations"], 1)
        self.assertTrue(result["side_effects"]["provider_called"])
        self.assertIsNone(result["side_effects"]["network_used"])
        self.assertIsNone(result["side_effects"]["provider_model_api_grader_calls"])
        self.assertNotIn(sentinel, json.dumps(result, sort_keys=True))

    def test_missing_effects_are_unknown_not_zero(self):
        for effects in (None, {}):
            with self.subTest(effects=effects):
                admission_result = self.ready_admission_result()
                admission_result["side_effects"] = effects
                with patch(
                    "src.swe_lancer_carrier.admission.check_admission",
                    return_value=admission_result,
                ):
                    result = self.check()
                self.assertFalse(result["ready"])
                self.assertEqual(
                    result["missing_or_invalid"], ["admission.side_effects"]
                )
                self.assertEqual(result["side_effects"]["admission_invocations"], 1)
                for name in carrier.ADMISSION_SIDE_EFFECT_FIELDS:
                    self.assertIsNone(result["side_effects"][name])
                self.assertIsNone(
                    result["side_effects"]["provider_model_api_grader_calls"]
                )

    def test_attested_receipt_fingerprint_drift_stops_before_admission(self):
        self.receipts["price_receipt"]["currency"] = "EUR"
        self.write_receipts()
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = self.check()
        self.assertEqual(result["context_status"], "wrong_source")
        self.assertEqual(
            result["missing_or_invalid"],
            ["context_attestation.input_fingerprints.price_receipt"],
        )
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_privacy_red_receipt_stops_before_admission(self):
        self.receipts["provider_contract_receipt"]["credential_value_recorded"] = True
        self.write_receipts()
        self.refresh_attestation()
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = self.check()
        self.assertEqual(result["context_status"], "invalid")
        self.assertEqual(
            result["missing_or_invalid"], ["provider_contract_receipt.contract"]
        )
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_stale_provider_receipt_stops_before_admission(self):
        receipt = self.receipts["provider_contract_receipt"]
        receipt["observed_at_utc"] = (self.now - timedelta(hours=2)).isoformat()
        receipt["valid_through_utc"] = (self.now - timedelta(hours=1)).isoformat()
        self.write_receipts()
        self.refresh_attestation()
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = self.check()
        self.assertEqual(result["context_status"], "stale")
        self.assertEqual(
            result["missing_or_invalid"], ["provider_contract_receipt.freshness"]
        )
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_receipt_ledger_binding_drift_stops_before_admission(self):
        self.receipts["price_receipt"]["ledger_sha256"] = "0" * 64
        self.write_receipts()
        self.refresh_attestation()
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = self.check()
        self.assertEqual(result["context_status"], "wrong_source")
        self.assertEqual(
            result["missing_or_invalid"], ["price_receipt.ledger_sha256"]
        )
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_cleanup_contract_red_stops_before_admission(self):
        self.receipts["outbound_receipt"]["cleanup_contract_verified"] = False
        self.write_receipts()
        self.refresh_attestation()
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = self.check()
        self.assertEqual(result["context_status"], "invalid")
        self.assertEqual(result["missing_or_invalid"], ["outbound_receipt.contract"])
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_missing_receipt_path_stops_before_private_input_reads(self):
        environment = ProtectedEnvironment(self.environment)
        del environment["SWE_LANCER_PRICE_RECEIPT"]
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = self.check(environment)
        self.assertEqual(result["context_status"], "missing")
        self.assertEqual(result["side_effects"]["runtime_input_files_read"], 0)
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_source_hash_drift_is_a_source_error(self):
        self.launcher.write_bytes(b"changed carrier\n")
        with patch("src.swe_lancer_carrier.admission.check_admission") as admission_call:
            result = self.check()
        self.assertEqual(result["failure_class"], "source")
        self.assertEqual(result["context_status"], "wrong_source")
        self.assertEqual(result["side_effects"]["admission_invocations"], 0)
        admission_call.assert_not_called()

    def test_no_clobber_preserves_output_before_probe(self):
        sentinel = b'{"sentinel":true}\n'
        self.output.write_bytes(sentinel)
        with patch("src.swe_lancer_carrier.probe") as probe_call:
            exit_code, result = carrier.run(
                self.environment,
                root=self.root,
                definition_path=self.definition_path,
                current_time=self.now,
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(result["missing_or_invalid"], ["output.no_clobber"])
        self.assertEqual(self.output.read_bytes(), sentinel)
        probe_call.assert_not_called()

    def test_ready_run_writes_private_mode_result(self):
        with patch.object(
            admission, "FIXED_SOURCE_PINS", self.control_source_pins
        ):
            exit_code, result = carrier.run(
                self.environment,
                root=self.root,
                definition_path=self.definition_path,
                current_time=self.now,
            )
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ready"])
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), result)
        self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
