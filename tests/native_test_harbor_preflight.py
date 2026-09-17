import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native_helpers import ledger_fixture
from src.native_contract import CONDITIONS
from src.native_run import preflight


ROOT = Path(__file__).resolve().parents[1]


class HarborPreflightTests(unittest.TestCase):
    def test_baseline_preflight_checks_every_compressor_artifact(self):
        ledger = ledger_fixture()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "FOUNDRY_ENDPOINT": "https://synthetic.openai.azure.com/openai/v1",
            "FOUNDRY_QUEUE_STATE": str(Path(temporary) / "deployment-queue.json"),
            "NATIVE_BLOB_ACCOUNT_URL": "https://synthetic.blob.core.windows.net",
            "NATIVE_BLOB_SPOOL_ROOT": str(Path(temporary) / "blob-spool"),
            "PROVIDER_RPM_LIMIT": "10000",
            "PROVIDER_TPM_LIMIT": "1000000",
        }), patch("src.native_run.capture", return_value=({"source_commit": "a" * 40}, {})), \
             patch("src.native_run.runtime_versions", return_value={}), \
             patch("src.native_run.load_encoder", return_value=object()), \
             patch("src.native_run.benchmark_sources", return_value=(Path(temporary), {})), \
             patch("src.native_run.check_compressor_artifacts") as check:
            preflight(ledger, ROOT / "ledgers/native.template.toml", "a" * 40, "none")
        self.assertEqual([call.args[1] for call in check.call_args_list], list(CONDITIONS))


if __name__ == "__main__":
    unittest.main()
