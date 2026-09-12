"""Retain native scores and classify observed failure evidence, not its cause."""

from collections import Counter
import json
from pathlib import Path
import re

from .protection import digest, parse_request


CATEGORIES = ("wrong_answer", "wrong_format", "timeout", "tool_error", "other")
ARTIFACT_TESTS = {
    "test_summary_file_exists", "test_output_files_exist", "test_run_py_file_exists",
    "test_directory_structure", "test_key_file", "test_certificate_file",
    "test_combined_pem_file", "test_verification_file", "test_python_verification_script",
}


def test_failure(test: dict) -> dict:
    trace = test.get("trace") or ""
    if not isinstance(trace, str):
        trace = ""
    active = "\n".join(re.findall(r"(?m)^E\s+(.*)$", trace))
    name = str(test.get("name", "unknown"))
    category, reason = "other", "unclassified_native_failure"
    if re.search(r"(?:TimeoutExpired|TimeoutError|timed out)", active):
        category, reason = "timeout", "test_timeout_evidence"
    elif re.search(r"(?:JSONDecodeError|csv\.Error|yaml\.(?:parser|scanner)\.)", active):
        category, reason = "wrong_format", "output_parse_error"
    elif re.search(r"(?:FileNotFoundError|CalledProcessError|ConnectionError|ConnectionRefusedError)", active):
        category, reason = "tool_error", "test_invoked_command_or_connection_error"
    elif test.get("raw_status") in ("setup_failed", "teardown_failed"):
        category, reason = "tool_error", "test_setup_or_teardown_failed"
    elif "AssertionError" in active:
        category, reason = "wrong_answer", "native_assertion_failed"
        if any(marker in active for marker in ("Unexpected header:", "CSV file is empty")):
            category, reason = "wrong_format", "output_shape_assertion"
        if name.split("::")[-1] in ARTIFACT_TESTS and re.search(r"does not exist|not found|is not a directory", active):
            category, reason = "wrong_format", "required_artifact_missing"
    return {
        "test": name, "category": category, "reason": reason,
        "native_status": test.get("status"), "native_phase": test.get("raw_status"),
        "trace_sha256": digest(trace.encode()), "active_exception": active or None,
        "evidence_kind": "observed_failure_signature_not_root_cause",
    }


def classify_native(
    result: dict | None, ctrf: dict | None, *, benchmark="terminal-bench",
    process: dict | None = None, stdout="", transport_failure: dict | None = None,
) -> dict:
    if benchmark not in ("terminal-bench", "deep-swe"):
        raise ValueError("Only the inspected Harbor-format judges are supported")
    process = process or {}
    issues, failures, warnings = [], [], []
    def mapping(value, field):
        if value is None:
            return {}
        if not isinstance(value, dict):
            issues.append(field + "_malformed")
            return {}
        return value

    result = mapping(result, "native_result")
    process = mapping(process, "process")
    verifier = mapping(result.get("verifier_result"), "verifier_result")
    reward = mapping(verifier.get("rewards"), "rewards").get("reward")
    reward_valid = type(reward) in (int, float) and reward in (0, 1)
    if not reward_valid:
        issues.append("native_binary_reward_missing_or_invalid")
    exception = mapping(result.get("exception_info"), "exception_info")
    exception_type = exception.get("exception_type", "")
    if not isinstance(exception_type, str):
        issues.append("exception_type_malformed")
        exception_type = ""
    if process.get("timed_out") or "Timeout" in exception_type:
        failures.append({"category": "timeout", "reason": "native_execution_timeout", "exception_type": exception_type or None})
        if process.get("timed_out"):
            issues.append("native_execution_did_not_complete")
        else:
            warnings.append("agent_timeout_retained_alongside_native_reward")
    elif exception:
        category = "tool_error" if re.search(r"Docker|Environment|Transport|Connection|Authentication|RateLimit|Reward|Verifier", exception_type) else "other"
        failures.append({"category": category, "reason": "native_exception", "exception_type": exception_type})
        if category == "tool_error":
            issues.append("native_infrastructure_exception_present")
        else:
            warnings.append("agent_exception_retained_alongside_native_reward")
    if process.get("stopped_by_guard") or transport_failure:
        failures.append({"category": "tool_error", "reason": "transport_stopped", "details": transport_failure})
        issues.append("transport_stopped")
    if process.get("returncode", 0) != 0 and not failures:
        failures.append({"category": "tool_error", "reason": "harness_process_failed", "returncode": process["returncode"]})
        issues.append("harness_process_failed")
    ctrf = mapping(ctrf, "ctrf")
    ctrf_results = mapping(ctrf.get("results"), "ctrf_results")
    tests = ctrf_results.get("tests")
    test_counts = None
    modes = None
    if benchmark == "terminal-bench":
        if not isinstance(tests, list) or not tests or any(
            not isinstance(test, dict) or not isinstance(test.get("name"), str)
            or not isinstance(test.get("status"), str) for test in tests
        ):
            issues.append("individual_test_evidence_missing")
        else:
            test_counts = dict(Counter(test.get("status", "missing") for test in tests))
            reported = mapping(ctrf_results.get("summary"), "ctrf_summary").get("tests")
            if type(reported) is not int or reported != len(tests):
                issues.append("test_count_inconsistent")
            if len({test.get("name") for test in tests}) != len(tests):
                issues.append("duplicate_test_identifiers")
            failed = [test for test in tests if test.get("status") in ("failed", "error")]
            failures.extend(test_failure(test) for test in failed)
            if any(status not in ("passed", "failed", "error", "skipped", "pending") for status in test_counts):
                issues.append("unrecognized_test_status")
            if any(test.get("status") in ("skipped", "pending") for test in tests):
                warnings.append("skipped_or_pending_tests_are_not_passes")
            if reward == 1 and (failed or test_counts.get("passed", 0) == 0):
                issues.append("reward_and_individual_tests_disagree")
            if reward == 0 and not failed:
                issues.append("failure_without_individual_failed_tests")
    else:
        if not isinstance(stdout, str):
            stdout = ""
            issues.append("test_stdout_malformed")
        baseline = re.findall(r"(?m)^\[verifier\] Baseline exit code: (\d+)\s*$", stdout)
        added = re.findall(r"(?m)^\[verifier\] New tests exit code: (\d+)\s*$", stdout)
        modes = {"base_exit_code": int(baseline[-1]) if baseline else None,
                 "new_exit_code": int(added[-1]) if added else None}
        if len(baseline) != 1 or len(added) != 1:
            issues.append("base_or_new_mode_evidence_missing")
        elif reward_valid and int(all(value == 0 for value in modes.values())) != reward:
            issues.append("reward_and_mode_exit_codes_disagree")
        if reward == 0 and not failures:
            failures.append({"category": "other", "reason": "native_test_mode_nonzero_requires_log_review"})
        warnings.append("mode_exit_codes_do_not_supply_individual_test_failure_causes")
    if reward == 0 and not failures:
        failures.append({"category": "other", "reason": "native_failure_without_classifiable_evidence"})
    if issues and not failures:
        failures.append({"category": "other", "reason": "incomplete_or_inconsistent_judge_evidence"})
    priority = ("timeout", "tool_error", "wrong_format", "wrong_answer", "other")
    categories = [category for category in priority if any(failure["category"] == category for failure in failures)]
    return {
        "schema_version": 1, "kind": "classification", "benchmark": benchmark,
        "native_reward": reward, "native_pass": bool(reward) if reward_valid else None,
        "native_score_source": "benchmark_builtin_verifier_not_regraded",
        "status": "invalid" if issues else "passed" if reward == 1 else "failed",
        "quality_valid": not issues, "primary_failure": categories[0] if categories else None,
        "failure_categories": categories, "failures": failures,
        "individual_test_counts": test_counts, "test_modes": modes,
        "integrity_issues": issues, "warnings": warnings,
        "truncation_causality": "not_established", "process": process,
    }


def collect_native_outcome(
    job_directory: Path, *, benchmark="terminal-bench", process=None, transport_failure=None,
) -> dict:
    paths = list(job_directory.glob("*/result.json"))
    result, ctrf, stdout, reward_text = None, None, "", None
    artifacts, read_errors = {}, []
    if len(paths) == 1:
        trial = paths[0].parent
        for name, path in {
            "native_result": paths[0], "ctrf": trial / "verifier/ctrf.json",
            "test_stdout": trial / "verifier/test-stdout.txt", "reward_text": trial / "verifier/reward.txt",
        }.items():
            if not path.exists():
                continue
            if not path.resolve().is_relative_to(job_directory.resolve()):
                read_errors.append(name + "_escapes_job_directory")
                continue
            try:
                content = path.read_bytes()
            except OSError:
                read_errors.append(name + "_unreadable")
                continue
            artifacts[name] = {"path": str(path.relative_to(job_directory)), "sha256": digest(content)}
            try:
                if name == "native_result":
                    result = parse_request(content)
                    if not isinstance(result, dict):
                        raise ValueError("Malformed native result")
                elif name == "ctrf":
                    ctrf = parse_request(content)
                    if not isinstance(ctrf, dict) or not isinstance(ctrf.get("results"), dict):
                        raise ValueError("Malformed CTRF")
                elif name == "test_stdout":
                    stdout = content.decode("utf-8", errors="replace")
                elif name == "reward_text":
                    reward_text = float(content.decode().strip())
            except (ValueError, TypeError):
                read_errors.append(name + "_malformed")
                if name == "native_result":
                    result = None
                elif name == "ctrf":
                    ctrf = None
    outcome = classify_native(result, ctrf, benchmark=benchmark, process=process, stdout=stdout,
                              transport_failure=transport_failure)
    outcome["artifacts"] = artifacts
    if reward_text not in (0, 1) or reward_text != outcome["native_reward"]:
        read_errors.append("native_result_and_reward_file_disagree_or_missing")
    if len(paths) != 1 or read_errors:
        outcome["integrity_issues"].extend(read_errors or ["expected_exactly_one_native_trial"])
        outcome.update(status="invalid", quality_valid=False)
        if not outcome["failures"]:
            outcome.update(primary_failure="other", failure_categories=["other"])
            outcome["failures"].append({"category": "other", "reason": "incomplete_or_inconsistent_judge_artifacts"})
    return outcome
