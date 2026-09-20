from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.cache_reuse import (
    CONDITIONS,
    REUSE_CONTRASTS,
    REQUIRED_RUNTIME_CHECKS,
    PrefixTracker,
    bundle_metrics,
    cache_stability,
    cache_verdict,
    doctor,
    execute_cycle,
    load_cache_ledger,
    load_json,
    main,
    make_plan,
    provider_usage_record,
    result_row,
    validate_cache_ledger,
    validate_plan,
    validate_runtime_facts,
    write_no_clobber,
)
from src.contracts import validate
from src.native_contract import TASKS, load_native_ledger, parse_native_ledger
from src.protection import canonical, digest


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "ledgers/cache-reuse.template.json"
FACTS_PATH = ROOT / "fixtures/cache-reuse/runtime-facts.template.json"
TRANSPORT_PATH = ROOT / "fixtures/cache-reuse/fake-transport.json"
PRICE_SOURCE = "synthetic fixed price source"
PRICE_CHECKED_AT = "2026-09-20T00:00:00Z"


def approved_facts():
    facts = load_json(FACTS_PATH)
    for check in facts["checks"]:
        check.update(
            status="verified",
            evidence_sha256="e" * 64,
            observed_at_utc="2026-09-20T00:00:00Z",
            method="synthetic model-free fixture",
            predicate="synthetic positive control only",
        )
    facts["prefix_contract"] = {
        "message_count": 1,
        "namespace_message_index": 0,
        "namespace_content_sha256": digest(b"fixed public synthetic namespace"),
    }
    return facts


def approved_ledger():
    ledger = load_cache_ledger(LEDGER_PATH)
    ledger["status"] = "runtime_bound_approved"
    ledger["live_execution_authorized"] = True
    ledger["pricing"].update(
        status="verified",
        input_per_million_usd=2.0,
        cached_input_per_million_usd=0.5,
        output_per_million_usd=4.0,
        source_reference_sha256=digest(PRICE_SOURCE.encode()),
        checked_at_utc=PRICE_CHECKED_AT,
    )
    return ledger


def serial_native_ledger_bytes():
    content = (ROOT / "ledgers/native.template.toml").read_bytes()
    replacements = {
        b"concurrency = 8": b"concurrency = 1",
        b'deployment_isolation_reference = ""': b'deployment_isolation_reference = "synthetic isolated deployment"',
        b"\ninput_per_million_usd = 0\n": b"\ninput_per_million_usd = 2.0\n",
        b"\ncached_input_per_million_usd = 0\n": b"\ncached_input_per_million_usd = 0.5\n",
        b"\noutput_per_million_usd = 0\n": b"\noutput_per_million_usd = 4.0\n",
        b'\nsource_reference = ""\n': f'\nsource_reference = "{PRICE_SOURCE}"\n'.encode(),
        b'\nchecked_at_utc = ""\n': f'\nchecked_at_utc = "{PRICE_CHECKED_AT}"\n'.encode(),
        b"execution_approved = false": b"execution_approved = true",
        b"rule_accepted = false": b"rule_accepted = true",
        b'\nreference = ""\n': b'\nreference = "synthetic cache-reuse approval"\n',
    }
    for before, after in replacements.items():
        if content.count(before) != 1:
            raise AssertionError(f"Expected one native fixture field: {before!r}")
        content = content.replace(before, after)
    return content


def serial_native_ledger():
    return parse_native_ledger(serial_native_ledger_bytes())


def stable_cycles(share_difference=0.1, cost_difference=-0.01, count=10, start=1):
    return [
        {
            "run_id": f"run-{index:02d}",
            "cycle_id": f"cycle-{index:02d}-{digest(f'run-{index:02d}'.encode())}",
            "cycle_number": index,
            "source_commit": "a" * 40,
            "cache_ledger_sha256": "b" * 64,
            "native_ledger_sha256": "c" * 64,
            "runtime_facts_sha256": "d" * 64,
            "pins": {
                "provider": "foundry",
                "model": "gpt-5.4",
                "reported_revision": "gpt-5.4-2026-03-05",
                "endpoint_env": "FOUNDRY_ENDPOINT",
                "api_surface": "openai_v1_chat_completions",
                "temperature": 0,
                "reasoning_effort": "none",
                "isolation_evidence_sha256": "e" * 64,
            },
            "valid": True,
            "contrasts": {
                contrast: {
                    "cache_share_difference": share_difference,
                    "input_cost_difference": cost_difference,
                }
                for contrast in REUSE_CONTRASTS
            },
        }
        for index in range(start, start + count)
    ]


class LedgerAndPlanTests(unittest.TestCase):
    def test_template_encodes_one_axis_but_remains_live_no_go(self):
        ledger = load_cache_ledger(LEDGER_PATH)
        validate(ledger, "cache-reuse-ledger.schema.json")
        self.assertFalse(ledger["live_execution_authorized"])
        self.assertEqual(ledger["runner"]["concurrency"], 1)
        self.assertEqual(ledger["conditions"], ["none", "squeez"])
        self.assertEqual(ledger["reuse_levels"], [0, 1, 2])
        self.assertNotIn("max_completion_tokens", ledger["generation"])
        self.assertEqual(ledger["execution_unit"]["task_ids"], list(TASKS))
        self.assertEqual(len(ledger["runtime_required_checks"]), 14)

    def test_ten_cycle_plan_has_exact_six_cells_and_five_tasks(self):
        ledger = load_cache_ledger(LEDGER_PATH)
        plan = make_plan(ledger, 10)
        self.assertEqual(plan["cell_count"], 60)
        self.assertEqual(plan["task_trials"], 300)
        self.assertTrue(all(row["concurrency"] == 1 for row in plan["rows"]))
        self.assertTrue(all(row["task_ids"] == list(TASKS) for row in plan["rows"]))
        first = [(row["condition"], row["reuse_level"]) for row in plan["rows"][:6]]
        second = [(row["condition"], row["reuse_level"]) for row in plan["rows"][6:12]]
        self.assertEqual(first, [("none", 0), ("none", 1), ("none", 2), ("squeez", 0), ("squeez", 1), ("squeez", 2)])
        self.assertEqual(second, [("squeez", 0), ("squeez", 1), ("squeez", 2), ("none", 0), ("none", 1), ("none", 2)])

    def test_plan_mutations_fail_closed(self):
        ledger = load_cache_ledger(LEDGER_PATH)
        mutations = []
        plan = make_plan(ledger, 1)
        changed = deepcopy(plan)
        changed["rows"][1]["reuse_level"] = 2
        mutations.append(changed)
        changed = deepcopy(plan)
        changed["rows"][0]["concurrency"] = 8
        mutations.append(changed)
        changed = deepcopy(plan)
        changed["allowed_contrasts"]["reuse"].append("diagonal:none0-squeez1")
        mutations.append(changed)
        changed = deepcopy(plan)
        changed["task_trials"] -= 1
        mutations.append(changed)
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_plan(mutation, ledger)

    def test_ledger_mutations_fail_closed(self):
        ledger = load_cache_ledger(LEDGER_PATH)
        mutations = []
        changed = deepcopy(ledger)
        changed["runner"]["concurrency"] = 8
        mutations.append(changed)
        changed = deepcopy(ledger)
        changed["conditions"] = ["none", "squeez", "headroom"]
        mutations.append(changed)
        changed = deepcopy(ledger)
        changed["measurement"]["missing_native_usage"] = "zero"
        mutations.append(changed)
        changed = deepcopy(ledger)
        changed["contrasts"]["forbidden"] = []
        mutations.append(changed)
        changed = deepcopy(ledger)
        changed["output"]["no_clobber"] = False
        mutations.append(changed)
        changed = deepcopy(ledger)
        changed["live_execution_authorized"] = True
        mutations.append(changed)
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_cache_ledger(mutation)

    def test_no_clobber_preserves_first_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.json"
            write_no_clobber(path, {"state": "first"})
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_no_clobber(path, {"state": "second"})
            self.assertEqual(path.read_bytes(), original)


class RuntimeDoctorTests(unittest.TestCase):
    def test_public_templates_are_no_go_without_reading_values(self):
        ledger = load_cache_ledger(LEDGER_PATH)
        facts = load_json(FACTS_PATH)
        native = load_native_ledger(ROOT / "ledgers/native.template.toml")
        with patch.dict(os.environ, {"FOUNDRY_ENDPOINT": "must-not-be-recorded"}, clear=False):
            result = doctor(ledger, facts, native)
        self.assertEqual(result["decision"], "no_go")
        self.assertEqual(result["provider_model_api_calls"], 0)
        self.assertFalse(result["credential_values_read"])
        self.assertIs(result["environment_presence"]["FOUNDRY_ENDPOINT"], True)
        self.assertNotIn("must-not-be-recorded", json.dumps(result))

    def test_all_verified_facts_and_serial_native_config_open_model_free_gate(self):
        with patch.dict(
            os.environ, {"FOUNDRY_ENDPOINT": "synthetic-not-read"}, clear=False
        ), patch("src.cache_reuse.importlib.util.find_spec", return_value=object()):
            result = doctor(approved_ledger(), approved_facts(), serial_native_ledger())
        self.assertEqual(result["decision"], "go")
        self.assertEqual(result["passed"], result["total"])

    def test_cross_ledger_mismatches_remain_no_go(self):
        cases = []
        changed = serial_native_ledger()
        changed["model"]["reported_model"] = "gpt-5.4-2026-04-01"
        cases.append((changed, "native_model_contract"))
        changed = serial_native_ledger()
        changed["model"]["temperature"] = 0.1
        cases.append((changed, "native_generation_contract"))
        changed = serial_native_ledger()
        changed["prices"]["input_per_million_usd"] = 3.0
        cases.append((changed, "native_price_contract"))
        changed = serial_native_ledger()
        changed["approval"]["execution_approved"] = False
        cases.append((changed, "native_execution_authorized"))
        for native, expected in cases:
            with self.subTest(expected=expected), patch.dict(
                os.environ, {"FOUNDRY_ENDPOINT": "synthetic-not-read"}, clear=False
            ), patch("src.cache_reuse.importlib.util.find_spec", return_value=object()):
                result = doctor(approved_ledger(), approved_facts(), native)
            failed = {row["id"] for row in result["checks"] if not row["passed"]}
            self.assertEqual(result["decision"], "no_go")
            self.assertIn(expected, failed)
            self.assertEqual(result["provider_model_api_calls"], 0)

    def test_missing_prefix_and_concurrency_eight_remain_no_go(self):
        facts = approved_facts()
        del facts["prefix_contract"]
        result = doctor(approved_ledger(), facts, load_native_ledger(ROOT / "ledgers/native.template.toml"))
        failed = {row["id"] for row in result["checks"] if not row["passed"]}
        self.assertIn("prefix_contract", failed)
        self.assertIn("native_concurrency_one", failed)

    def test_runtime_fact_ids_are_exact_and_values_are_forbidden(self):
        ledger = load_cache_ledger(LEDGER_PATH)
        facts = approved_facts()
        validate(facts, "cache-reuse-runtime-facts.schema.json")
        validate_runtime_facts(facts, ledger)
        changed = deepcopy(facts)
        changed["checks"][0]["endpoint"] = "https:" + "//example.invalid"
        with self.assertRaises(ValueError):
            validate_runtime_facts(changed, ledger)
        changed = deepcopy(facts)
        changed["checks"][0]["id"] = "R01_DIFFERENT"
        with self.assertRaises(ValueError):
            validate_runtime_facts(changed, ledger)
        changed = deepcopy(facts)
        changed["checks"][0]["owner"] = "source"
        with self.assertRaises(ValueError):
            validate_runtime_facts(changed, ledger)
        changed = deepcopy(facts)
        del changed["checks"][0]["evidence_sha256"]
        with self.assertRaises(ValueError):
            validate_runtime_facts(changed, ledger)
        changed = deepcopy(facts)
        changed["environment_presence"]["/" + "restricted/runtime/path"] = True
        with self.assertRaises(ValueError):
            validate_runtime_facts(changed, ledger)
        self.assertEqual(tuple(row["id"] for row in facts["checks"]), REQUIRED_RUNTIME_CHECKS)

    def test_cli_doctor_stops_before_any_provider_surface(self):
        with patch("src.cache_reuse.doctor") as doctor_call, patch("sys.stdout", new_callable=io.StringIO):
            doctor_call.return_value = {"decision": "no_go"}
            self.assertEqual(main([str(LEDGER_PATH), "--runtime-facts", str(FACTS_PATH), "--doctor"]), 3)
            doctor_call.assert_called_once()


class PrefixTrackerTests(unittest.TestCase):
    def setUp(self):
        self.namespace = "fixed public synthetic namespace"
        self.contract = {
            "message_count": 1,
            "namespace_message_index": 0,
            "namespace_content_sha256": digest(self.namespace.encode()),
        }

    def payload(self, suffix="question"):
        return {
            "model": "gpt-5.4",
            "temperature": 0,
            "reasoning_effort": "none",
            "messages": [
                {"role": "system", "content": self.namespace},
                {"role": "user", "content": suffix},
            ],
        }

    def complete_level(self, tracker, level, suffix="question", requests=1):
        for task in TASKS:
            for request_index in range(requests):
                payload = self.payload(f"{suffix}-{request_index}")
                tracker.observe(
                    condition="none", reuse_level=level, task=task,
                    payload=payload, serialized=canonical(payload),
                )
        tracker.finish_bundle("none", level, list(TASKS), successful=True)

    def test_equal_prefixes_open_exact_zero_one_two_predecessors(self):
        tracker = PrefixTracker(self.contract, "cycle-01")
        self.complete_level(tracker, 0, "cold", requests=2)
        self.complete_level(tracker, 1, "warm-one", requests=2)
        self.complete_level(tracker, 2, "warm-two", requests=2)
        self.assertEqual(len(tracker.completed[("none", TASKS[0])]), 3)

    def test_prefix_hash_drift_fails_before_dispatch(self):
        tracker = PrefixTracker(self.contract, "cycle-01")
        self.complete_level(tracker, 0)
        payload = self.payload()
        payload["messages"][0]["content"] = "different namespace"
        with self.assertRaisesRegex(ValueError, "namespace hash"):
            tracker.observe(
                condition="none", reuse_level=1, task=TASKS[0],
                payload=payload, serialized=canonical(payload),
            )

    def test_missing_predecessor_and_request_width_drift_fail(self):
        tracker = PrefixTracker(self.contract, "cycle-01")
        with self.assertRaisesRegex(ValueError, "predecessor"):
            tracker.observe(
                condition="none", reuse_level=1, task=TASKS[0],
                payload=self.payload(), serialized=canonical(self.payload()),
            )
        self.complete_level(tracker, 0, requests=2)
        for task in TASKS:
            tracker.observe(
                condition="none", reuse_level=1, task=task,
                payload=self.payload(), serialized=canonical(self.payload()),
            )
        with self.assertRaisesRegex(ValueError, "request count"):
            tracker.finish_bundle("none", 1, list(TASKS), successful=True)

    def test_noncanonical_serialization_is_rejected(self):
        tracker = PrefixTracker(self.contract, "cycle-01")
        payload = self.payload()
        with self.assertRaisesRegex(ValueError, "canonical"):
            tracker.observe(
                condition="none", reuse_level=0, task=TASKS[0],
                payload=payload, serialized=json.dumps(payload).encode(),
            )


class UsageAndVerdictTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load_json(TRANSPORT_PATH)["cases"]
        self.pricing = approved_ledger()["pricing"]

    def record(self, name, level=1):
        case = self.fixture[name]
        return provider_usage_record({"usage": case.get("usage")}, case.get("http_status"), level, self.pricing)

    def test_missing_zero_positive_and_invalid_denominator_remain_distinct(self):
        self.assertEqual(self.record("missing")["cache_field_status"], "missing")
        self.assertEqual(self.record("missing")["status"], "missing_native_usage")
        self.assertEqual(self.record("explicit_zero")["cache_field_status"], "explicit_zero")
        self.assertEqual(self.record("positive")["cache_field_status"], "positive")
        self.assertEqual(self.record("invalid_denominator")["status"], "invalid_denominator")
        self.assertEqual(self.record("positive", 0)["opportunity"], "not_applicable")

    def test_provider_local_computed_and_invoice_units_stay_separate(self):
        usage = self.record("positive")
        self.assertEqual(usage["provider_usage"]["kind"], "measured_provider_native")
        self.assertIsNotNone(usage["computed_input_cost_usd"])
        self.assertEqual(usage["invoice"], {"status": "not_measured", "value": None})
        row = result_row(
            run_id="run-01", cycle_id="cycle-01", bundle_id="cycle-01-none-reuse-1",
            attempt_id="attempt-01", source_commit="a" * 40, ledger_sha256="b" * 64,
            native_ledger_sha256="c" * 64, runtime_facts_sha256="d" * 64,
            condition="none", reuse_level=1, task_id=TASKS[0],
            request_observation={"serialized_prefix_sha256": "c" * 64, "request_sha256": "d" * 64},
            usage=usage, local_tokens={"kind": "calculated_diagnostic_only", "input_tokens": 101},
            native_verdict="wrong_answer", pins={"source": "a" * 40}, synthetic=True,
        )
        self.assertTrue(row["flags"]["synthetic"])
        self.assertFalse(row["flags"]["measured"])
        self.assertFalse(row["flags"]["invoice"])
        self.assertNotEqual(row["provider_usage"], row["local_tokens"])
        validate(row, "cache-reuse-result.schema.json")

    def test_bundle_denominators_fail_closed_on_missing_429_or_zero_input(self):
        complete = bundle_metrics([self.record("explicit_zero"), self.record("positive")])
        self.assertTrue(complete["valid"])
        self.assertEqual(complete["request_denominator"], 2)
        for case in ("missing", "invalid_denominator", "rate_limited", "no_progress"):
            with self.subTest(case=case):
                self.assertFalse(bundle_metrics([self.record(case)])["valid"])

    def test_ten_cycle_stability_and_all_verdict_branches(self):
        self.assertEqual(cache_verdict(stable_cycles(), quality_conclusive=True)["verdict"], "supported")
        self.assertEqual(cache_verdict(stable_cycles(0, 0), quality_conclusive=True)["verdict"], "not_observed")
        self.assertEqual(cache_verdict(stable_cycles(-0.1, 0.01), quality_conclusive=True)["verdict"], "wrong_direction")
        self.assertEqual(cache_verdict(stable_cycles(0.1, 0.01), quality_conclusive=True)["verdict"], "no_separation")
        self.assertEqual(cache_verdict(stable_cycles(), quality_conclusive=False)["verdict"], "quality_inconclusive")

    def test_unstable_ten_extends_once_and_unstable_twenty_stops(self):
        ten = stable_cycles()
        for cycle in ten[5:]:
            for contrast in REUSE_CONTRASTS:
                cycle["contrasts"][contrast]["cache_share_difference"] = 2.0
                cycle["contrasts"][contrast]["input_cost_difference"] = -2.0
        self.assertEqual(cache_stability(ten)["status"], "extend_to_20")
        twenty = ten + stable_cycles(4.0, -4.0, 10, start=11)
        self.assertEqual(cache_stability(twenty)["status"], "same_condition_width_excess")

    def test_duplicate_mixed_or_unjustified_cycle_cohorts_fail_closed(self):
        duplicate = stable_cycles()
        duplicate[-1] = deepcopy(duplicate[0])
        with self.assertRaisesRegex(ValueError, "unique"):
            cache_verdict(duplicate, quality_conclusive=True)
        mixed = stable_cycles()
        mixed[-1]["runtime_facts_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "provenance"):
            cache_verdict(mixed, quality_conclusive=True)
        with self.assertRaisesRegex(ValueError, "unstable ten-cycle"):
            cache_stability(stable_cycles(count=20))

    def test_missing_usage_is_preserved_as_its_own_verdict(self):
        cycles = stable_cycles()
        cycles[0]["valid"] = False
        cycles[0]["invalid_reason"] = "missing_native_usage"
        self.assertEqual(cache_verdict(cycles, quality_conclusive=True)["verdict"], "missing_native_usage")

    def test_fake_fixture_declares_zero_network_and_all_required_controls(self):
        fixture = load_json(TRANSPORT_PATH)
        self.assertEqual(fixture["network_calls"], 0)
        self.assertEqual(
            set(fixture["cases"]),
            {"missing", "explicit_zero", "positive", "invalid_denominator", "rate_limited", "no_progress"},
        )


class ExecutionOrchestrationTests(unittest.TestCase):
    def test_fake_native_dispatch_is_serial_exact_order_and_zero_network(self):
        namespace = "fixed public synthetic namespace"
        ledger = approved_ledger()
        facts = approved_facts()
        native_content = serial_native_ledger_bytes()
        calls = []
        active = 0
        maximum_active = 0
        network_calls = 0

        def fake_execute(_native_path, _native, _source_commit, condition, *, cache_context, request_observer):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            try:
                calls.append((condition, cache_context["reuse_level"], cache_context["bundle_id"]))
                for task in TASKS:
                    payload = {
                        "model": "gpt-5.4", "temperature": 0, "reasoning_effort": "none",
                        "messages": [
                            {"role": "system", "content": namespace},
                            {"role": "user", "content": f"public synthetic {task}"},
                        ],
                    }
                    request_observer(task=task, payload=payload, serialized=canonical(payload))
                return Path("synthetic-no-network")
            finally:
                active -= 1

        def fake_summary(_directory, row, _pricing, **_keywords):
            level = row["reuse_level"]
            return {
                "cycle_id": row["cycle_id"], "bundle_id": row["bundle_id"],
                "condition": row["condition"], "reuse_level": level,
                "eligible_predecessor_count": level,
                "task_denominator": 5, "run_denominator": 1, "request_denominator": 5,
                "provider_http_attempt_denominator": 5, "provider_http_429": 0,
                "metrics": {
                    "valid": True,
                    "provider_cache_share": level * 0.1,
                    "computed_input_cost_usd": 1 - level * 0.1,
                },
                "lineage": {"native_ledger_sha256": digest(native_content)},
            }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache_path = root / "cache.json"
            facts_path = root / "facts.json"
            native_path = root / "native.toml"
            cache_path.write_text(json.dumps(ledger))
            facts_path.write_text(json.dumps(facts))
            native_path.write_bytes(native_content)
            cycle_id = f"cycle-01-{digest(b'synthetic-run')}"
            output = root / "runs/cache-reuse/synthetic-run" / cycle_id
            with patch.dict(
                os.environ, {"FOUNDRY_ENDPOINT": "synthetic-not-read"}, clear=False
            ), patch(
                "src.cache_reuse.importlib.util.find_spec", return_value=object()
            ), patch("src.cache_reuse.ROOT", root), patch(
                "src.cache_reuse.verify_source_commit"
            ), patch(
                "src.cache_reuse.summarize_native_bundle", side_effect=fake_summary
            ):
                cycle = execute_cycle(
                    cache_path, facts_path, native_path, "a" * 40, 1, "synthetic-run", output,
                    native_execute=fake_execute,
                )
            self.assertEqual(
                [(condition, level) for condition, level, _bundle in calls],
                [("none", 0), ("none", 1), ("none", 2), ("squeez", 0), ("squeez", 1), ("squeez", 2)],
            )
            self.assertEqual(maximum_active, 1)
            self.assertEqual(network_calls, 0)
            self.assertEqual(cycle["bundle_denominator"], 6)
            self.assertEqual(cycle["task_denominator"], 30)
            self.assertEqual(cycle["request_denominator"], 30)
            self.assertEqual(cycle["cycle_id"], cycle_id)
            self.assertEqual(cycle["cycle_number"], 1)
            self.assertEqual(cycle["cache_ledger_sha256"], digest(cache_path.read_bytes()))
            self.assertEqual(cycle["runtime_facts_sha256"], digest(facts_path.read_bytes()))
            self.assertEqual(cycle["native_ledger_sha256"], digest(native_content))
            self.assertEqual((output / "ledger.json").read_bytes(), cache_path.read_bytes())
            self.assertEqual((output / "runtime-facts.json").read_bytes(), facts_path.read_bytes())
            self.assertEqual((output / "native-ledger.toml").read_bytes(), native_content)
            self.assertTrue(all(bundle_id.startswith(cycle["cycle_id"] + "-") for _condition, _level, bundle_id in calls))
            before = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            with patch.dict(
                os.environ, {"FOUNDRY_ENDPOINT": "synthetic-not-read"}, clear=False
            ), patch(
                "src.cache_reuse.importlib.util.find_spec", return_value=object()
            ), patch("src.cache_reuse.ROOT", root), patch(
                "src.cache_reuse.verify_source_commit"
            ), self.assertRaises(FileExistsError):
                execute_cycle(
                    cache_path, facts_path, native_path, "a" * 40, 1, "synthetic-run", output,
                    native_execute=fake_execute,
                )
            after = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            self.assertEqual(after, before)
            with patch.dict(
                os.environ, {"FOUNDRY_ENDPOINT": "synthetic-not-read"}, clear=False
            ), patch(
                "src.cache_reuse.importlib.util.find_spec", return_value=object()
            ), patch("src.cache_reuse.ROOT", root), patch(
                "src.cache_reuse.verify_source_commit"
            ), self.assertRaisesRegex(ValueError, "fixed ledger root"):
                execute_cycle(
                    cache_path, facts_path, native_path, "a" * 40, 2, "another-run",
                    root / "alternate-output", native_execute=fake_execute,
                )


if __name__ == "__main__":
    unittest.main()
