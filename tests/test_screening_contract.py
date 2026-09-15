from copy import deepcopy
from pathlib import Path
import unittest

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
            "reference": "delegated-final-design-2026-09-15",
        }
        ledger["limits"]["api_cost_usd"] = 1
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


if __name__ == "__main__":
    unittest.main()
