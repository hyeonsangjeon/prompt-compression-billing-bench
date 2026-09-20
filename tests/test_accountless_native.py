import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

from src import accountless_native


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ledgers/accountless-native.json"
FIXTURE = ROOT / "fixtures/accountless-native/gsm8k-test-record-0000.json"
PUBLIC_RECORD = ROOT / "data/experiment/accountless-native-quickstart.json"
RESULT_SCHEMA = ROOT / "schemas/accountless-native-result.schema.json"


class AccountlessNativeJudgeTests(unittest.TestCase):
    def test_official_correct_wrong_and_format_controls(self):
        reference = "reasoning\n#### 18"
        self.assertEqual(accountless_native.judge_output("work\n#### 18", reference)["verdict"], "pass")
        self.assertEqual(accountless_native.judge_output("work\n#### 19", reference)["verdict"], "wrong_answer")
        self.assertEqual(accountless_native.judge_output("18", reference)["verdict"], "wrong_format")

    def test_official_comma_and_first_marker_semantics_are_preserved(self):
        self.assertEqual(accountless_native.extract_answer("#### 1,234"), "1234")
        judged = accountless_native.judge_output("#### 18\n#### 19", "#### 18")
        self.assertEqual(judged["verdict"], "pass")
        self.assertEqual(judged["observed"], "18")

    def test_invalid_reference_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "no valid GSM8K"):
            accountless_native.judge_output("#### 18", "missing marker")


class AccountlessNativeContractTests(unittest.TestCase):
    def test_public_ledger_and_fixture_are_hash_bound(self):
        ledger, content = accountless_native.load_ledger(LEDGER)
        fixture, fixture_bytes = accountless_native.load_fixture(ledger)
        self.assertGreater(len(content), 0)
        self.assertGreater(len(fixture_bytes), 0)
        self.assertEqual(fixture["record_index"], 0)
        self.assertEqual(accountless_native.extract_answer(fixture["answer"]), "18")

    def test_model_file_preflight_rejects_missing_and_changed_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "weight.bin"
            path.write_bytes(b"fixed")
            specification = [{
                "name": "weight.bin", "bytes": 5,
                "sha256": accountless_native.digest_bytes(b"fixed"),
            }]
            self.assertEqual(accountless_native.verify_file_set(root, specification)[0]["bytes"], 5)
            path.write_bytes(b"drift")
            with self.assertRaisesRegex(ValueError, "differs"):
                accountless_native.verify_file_set(root, specification)
            path.unlink()
            with self.assertRaisesRegex(ValueError, "Missing"):
                accountless_native.verify_file_set(root, specification)

    def test_no_clobber_json_writer_preserves_existing_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            accountless_native.write_json_x(path, {"first": True})
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                accountless_native.write_json_x(path, {"second": True})
            self.assertEqual(path.read_bytes(), original)

    def test_existing_run_id_collides_before_model_preflight(self):
        ledger = json.loads(LEDGER.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            run_id = "collision-control"
            (output / run_id).mkdir()
            with mock.patch.dict(os.environ, {
                ledger["output"]["root_env"]: str(output),
                ledger["model"]["root_env"]: str(output / "missing-model"),
            }, clear=False):
                self.assertEqual(accountless_native.run_command(LEDGER, run_id), accountless_native.EXIT_COLLISION)

    def test_verify_rejects_raw_output_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            raw = b"#### 18"
            (directory / "raw-output.txt").write_bytes(raw)
            record = {
                "record_type": "accountless_native_attempt",
                "run_id": "control",
                "counts": {"model_invocations": 1, "native_verdicts": 1, "retries": 0},
                "native_verdict": {"verdict": "pass"},
                "raw_output": {"bytes": len(raw), "sha256": accountless_native.digest_bytes(raw)},
                "flags": {"measured": True, "synthetic": False, "projected": False},
            }
            (directory / "result.json").write_text(json.dumps(record))
            self.assertEqual(accountless_native.verify_run(directory)["run_id"], "control")
            (directory / "raw-output.txt").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "differs"):
                accountless_native.verify_run(directory)

    def test_source_contains_offline_and_timeout_guards(self):
        source = (ROOT / "src/accountless_native.py").read_text()
        for literal in (
            'local_files_only=True', 'TRANSFORMERS_OFFLINE', 'HF_HUB_OFFLINE',
            'NoProgressTimeout', 'AttemptTimeout', 'start_new_session=True',
        ):
            self.assertIn(literal, source)

    def test_finished_event_requires_both_token_counts(self):
        event = {
            "event": "inference_finished",
            "input_tokens": 12,
            "output_tokens": 3,
            "runtime_import_seconds": 1.0,
            "model_load_seconds": 2.0,
            "elapsed_seconds": 3.0,
            "model_visible_prompt_sha256": "a" * 64,
            "raw_output": "#### 18",
        }
        self.assertEqual(accountless_native.validate_finished_event(event), event)
        del event["input_tokens"]
        with self.assertRaisesRegex(ValueError, "input_tokens"):
            accountless_native.validate_finished_event(event)

    def test_sanitized_measured_record_matches_schema_and_sources(self):
        record_text = PUBLIC_RECORD.read_text(encoding="utf-8")
        record = json.loads(record_text)
        schema = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(record)

        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["exit_code"], accountless_native.EXIT_WRONG)
        self.assertEqual(record["native_verdict"]["verdict"], "wrong_format")
        self.assertEqual(record["counts"], {"model_invocations": 1, "retries": 0, "native_verdicts": 1})
        self.assertEqual(record["proof_summary"]["actual_model_invocations_in_bounded_proof"], 2)
        self.assertFalse(record["prior_red"]["preserved_as_pass"])
        self.assertIsNone(record["provider_usage"])
        self.assertIsNone(record["calculated_cost_usd"])
        for forbidden in ("/home/", "/tmp/", "/ai-work/", "raw-output.txt", "private-runs"):
            self.assertNotIn(forbidden, record_text)

        for source in record["preflight"]["source"]["files"]:
            content = (ROOT / source["path"]).read_bytes()
            self.assertEqual(len(content), source["bytes"])
            self.assertEqual(hashlib.sha256(content).hexdigest(), source["sha256"])

    def test_documented_cached_boundary_and_failure_codes(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        document = (ROOT / "docs/accountless-native.md").read_text(encoding="utf-8")
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        for text in (readme, document, status):
            self.assertIn("7.761", text)
            self.assertIn("wrong_format", text)
        for literal in (
            "Dependency installation", "model download", "does not establish",
            "300-second", "120-second", "0 model/runtime/package downloads",
            "accountless_native verify", "Exit codes and diagnostics",
        ):
            self.assertIn(literal.lower(), document.lower())
        self.assertRegex(document.lower(), r"0\s+package installs")

    def test_gsm8k_license_copy_and_notice_are_hash_bound(self):
        license_copy = (ROOT / "third_party/licenses/gsm8k-MIT.txt").read_bytes()
        self.assertEqual(len(license_copy), 1063)
        self.assertEqual(
            hashlib.sha256(license_copy).hexdigest(),
            "893951b3bf94db8df1b13e05da5cdeb499400960e4d44a3962a8b33ed0b4f28e",
        )
        self.assertTrue(license_copy.endswith(b"\n"))
        self.assertEqual(
            hashlib.sha256(license_copy[:-1]).hexdigest(),
            "86bbb73e855821d7c401912fd4bf82e34313e6e3b6fd6f909f2b6cc9e209a53b",
        )
        notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("3101c7d5072418e28b9008a6636bde82a006892c", notice)
        self.assertIn("one terminal line-feed byte", notice)


if __name__ == "__main__":
    unittest.main()
