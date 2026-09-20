from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from src.screening_contract import load_screening_ledger, require_operational_screening, validate_screening_ledger


class ScreeningContractTests(unittest.TestCase):
    def setUp(self):
        self.path = Path("ledgers/screening.template.toml")

    def test_template_structure_is_valid_but_cannot_execute(self):
        ledger = load_screening_ledger(self.path)
        with self.assertRaises(ValueError):
            require_operational_screening(ledger)

    def test_execution_requires_shared_deployment_reference(self):
        ledger = load_screening_ledger(self.path)
        ledger["approval"] = {
            "preregistered": True,
            "execution_authorized": True,
            "cost_limits_approved": True,
            "reference": "delegated-final-design-2026-09-15",
        }
        ledger["limits"].update(
            max_api_cost_usd_per_attempt=1,
            max_api_cost_usd_per_run=10,
            run_deadline_utc=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
        with self.assertRaisesRegex(ValueError, "shared-deployment coordination"):
            require_operational_screening(ledger)

    def test_fixed_screening_settings_reject_drift(self):
        ledger = load_screening_ledger(self.path)
        for section, name, value in (
            ("runner", "concurrency", 4),
            ("screening", "passes_required", 17),
            ("screening", "preparation_retry_maximum", 2),
            ("replay", "require_complete_capture", False),
            ("model", "reasoning_effort", "low"),
        ):
            changed = deepcopy(ledger)
            changed[section][name] = value
            with self.subTest(section=section, name=name), self.assertRaises(ValueError):
                validate_screening_ledger(changed)

    def test_runtime_limits_are_required_from_private_environment(self):
        ledger = load_screening_ledger(self.path)
        ledger["approval"] = {
            "preregistered": True,
            "execution_authorized": True,
            "cost_limits_approved": True,
            "reference": "synthetic test approval",
        }
        ledger["limits"].update(
            max_api_cost_usd_per_attempt=1,
            max_api_cost_usd_per_run=10,
            run_deadline_utc=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
        ledger["queue"]["deployment_isolation_reference"] = "synthetic test isolation"
        with patch.dict(os.environ, {"PROVIDER_RPM_LIMIT": "17", "PROVIDER_TPM_LIMIT": "1700"}):
            self.assertEqual(require_operational_screening(ledger)["status"], "applied")

    def test_legacy_ledger_cannot_start_new_provider_work(self):
        ledger = load_screening_ledger(self.path)
        ledger["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "schema-v4"):
            require_operational_screening(ledger)


if __name__ == "__main__":
    unittest.main()
