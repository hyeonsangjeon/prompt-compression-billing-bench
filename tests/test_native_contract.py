from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native_helpers import ledger_fixture
from src.native_contract import CONDITIONS, load_native_ledger, require_operational_values, validate_native_ledger
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
        self.assertGreater(require_operational_values(original), 0)
        for section, field, value in (("benchmark", "tasks", []), ("model", "temperature", True),
                                      ("compressor", "tools", []), ("compressor", "tools", {"squeez": [], "none": {}}),
                                      ("runner", "concurrency", 4), ("queue", "rpm", 300),
                                      ("stability", "maximum_repetitions", 30), ("approval", "rule_accepted", "yes"),
                                      ("limits", "api_cost_usd", float("nan"))):
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
        original["limits"]["deadline_utc"] = "2020-01-01T00:00:00+00:00"
        with self.assertRaises(ValueError):
            require_operational_values(original)

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
        self.assertEqual(runtime_versions()["harbor"], "0.22.0")

    def test_baseline_preflight_checks_every_compressor_artifact(self):
        ledger = ledger_fixture()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "FOUNDRY_ENDPOINT": "https://synthetic.openai.azure.com/openai/v1",
            "FOUNDRY_QUEUE_STATE": str(Path(temporary) / "deployment-queue.json"),
            "NATIVE_BLOB_ACCOUNT_URL": "https://synthetic.blob.core.windows.net",
            "NATIVE_BLOB_SPOOL_ROOT": str(Path(temporary) / "blob-spool"),
        }), patch("src.native_run.capture", return_value=({"source_commit": "a" * 40}, {})), \
             patch("src.native_run.runtime_versions", return_value={}), \
             patch("src.native_run.load_encoder", return_value=object()), \
             patch("src.native_run.benchmark_sources", return_value=(Path(temporary), {})), \
             patch("src.native_run.check_compressor_artifacts") as check:
            preflight(ledger, ROOT / "ledgers/native.template.toml", "a" * 40, "none")
        self.assertEqual([call.args[1] for call in check.call_args_list], list(CONDITIONS))


if __name__ == "__main__":
    unittest.main()
