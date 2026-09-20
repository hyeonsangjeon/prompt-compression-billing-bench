from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from native_helpers import ledger_fixture
from src.native_contract import load_native_ledger, require_operational_values, validate_native_ledger
from src.native_run import harbor_config, preflight, runtime_versions


ROOT = Path(__file__).resolve().parents[1]


class NativeContractTests(unittest.TestCase):
    def test_template_is_structurally_valid_but_cannot_execute(self):
        ledger = load_native_ledger(ROOT / "ledgers/native.template.toml")
        with patch("src.native_run.capture") as capture, patch("src.native_run.ManagedIdentity") as identity:
            with self.assertRaisesRegex(ValueError, "approval"):
                preflight(ledger, ROOT / "ledgers/native.template.toml", "a" * 40)
            capture.assert_not_called()
            identity.assert_not_called()

    def test_incomplete_or_changed_design_is_rejected(self):
        original = ledger_fixture()
        with patch.dict(os.environ, {"PROVIDER_RPM_LIMIT": "17", "PROVIDER_TPM_LIMIT": "1700"}):
            self.assertEqual(require_operational_values(original)["status"], "applied")

        for section, field, value in (("benchmark", "tasks", []), ("model", "temperature", True),
                                      ("compressor", "tools", []), ("compressor", "tools", {"squeez": [], "none": {}}),
                                      ("runner", "concurrency", 4), ("queue", "rpm", 300),
                                      ("stability", "maximum_repetitions", 30), ("approval", "rule_accepted", "yes"),
                                      ("limits", "max_provider_calls_per_attempt", 300)):
            ledger = deepcopy(original)
            ledger[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                validate_native_ledger(ledger)
        changed = deepcopy(original)
        changed["compressor"]["tools"]["headroom"]["options"]["allowed_kind"] = "log"
        with self.assertRaises(ValueError):
            validate_native_ledger(changed)
        changed = deepcopy(original)
        changed["compressor"]["tools"]["llmlingua2"]["options"]["rate"] = 0.6
        with self.assertRaises(ValueError):
            validate_native_ledger(changed)
        changed = deepcopy(original)
        changed["benchmark"]["verifiers"]["nginx-request-logging"]["effective_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_native_ledger(changed)
        original["limits"]["run_deadline_utc"] = "2020-01-01T00:00:00+00:00"
        with patch.dict(os.environ, {"PROVIDER_RPM_LIMIT": "17", "PROVIDER_TPM_LIMIT": "1700"}), \
             self.assertRaisesRegex(ValueError, "future"):
            require_operational_values(original)

    def test_legacy_ledger_can_be_validated_but_cannot_start_new_provider_work(self):
        ledger = ledger_fixture()
        ledger["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "schema-v4"):
            require_operational_values(ledger)

    def test_serial_concurrency_is_explicitly_available_without_changing_the_default(self):
        ledger = ledger_fixture()
        self.assertEqual(ledger["runner"]["concurrency"], 8)
        ledger["runner"]["concurrency"] = 1
        validate_native_ledger(ledger)

    @unittest.skipUnless(importlib.util.find_spec("harbor"), "Install the locked native extra for Harbor integration")
    def test_real_job_schema_accepts_one_serial_trial_inside_fixed_outer_concurrency(self):
        from harbor.models.job.config import JobConfig

        config = harbor_config(ledger_fixture(), ROOT / "task", ROOT / "jobs", "synthetic", "http://127.0.0.1:1/synthetic/v1")
        parsed = JobConfig.model_validate(config)
        self.assertEqual(parsed.n_concurrent_trials, 1)
        self.assertEqual(ledger_fixture()["runner"]["concurrency"], 8)
        self.assertEqual(parsed.retry.max_retries, 0)
        self.assertFalse(parsed.verifier.disable)
        self.assertEqual(parsed.agents[0].kwargs["llm_kwargs"]["num_retries"], 0)
        self.assertNotIn("max_turns", parsed.agents[0].kwargs)
        self.assertEqual(parsed.agents[0].kwargs["llm_kwargs"]["max_completion_tokens"], 2048)
        self.assertEqual(runtime_versions()["harbor"], "0.22.0")

if __name__ == "__main__":
    unittest.main()
