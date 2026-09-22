"""Export only allowlisted measurements, never prompts, generated keys, or endpoints."""

import argparse
import json
import math
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path

from accounting import read_attempts, sha256, totals
from run import require_commit_sha, save, verify
from src.eda_report import audit_report
from src.prompt_intake import archive_prompts


ATTEMPT_FIELDS = {
    "schema_version", "run_id", "repetition", "ledger_sha256", "source_sha256",
    "model", "tokenizer", "intervention", "benchmark", "task",
    "record_type", "kind", "source", "call_id", "attempt_id", "attempt_number",
    "is_retry", "started_at", "finished_at", "http_status", "error",
    "elapsed_seconds", "elapsed_source", "request_sha256", "response_sha256",
    "provider_usage", "tokens", "usage_status", "included_in_totals",
    "token_accounting", "provider_response_id", "provider_reported_cost_usd",
}
SUMMARY_FIELDS = {
    "schema_version", "record_type", "kind", "source", "run_id", "started_at",
    "finished_at", "status", "ledger_sha256", "source_sha256", "source_files", "source_commit",
    "model", "tokenizer", "intervention", "repetitions", "environment",
    "elapsed_seconds", "usage_totals", "model_manifest_sha256",
    "ollama_version", "model_cache_present_before_run", "not_proven",
}
PUBLIC_FILES = {
    "LICENSE", ".gitignore", ".python-version", "pyproject.toml", "uv.lock", "ledger.toml",
    "run.py", "accounting.py", "evidence.py", "README.md", "STATUS.md", "THIRD_PARTY_NOTICES.md",
    "third_party/licenses/terminal-bench-2.1-Apache-2.0.txt",
    "third_party/licenses/gsm8k-MIT.txt",
    "tests/test_accounting.py", "tests/test_evidence.py", "tests/test_run.py",
    "tests/test_root_license.py", ".github/workflows/check.yml",
    ".github/workflows/pages-static.yml", ".github/workflows/swe-lancer-offline-smoke.yml",
    "config/pages-static.json", "pages/assets/site.css",
    "requirements/pages-static.in", "requirements/pages-static.txt",
    "src/pages_build.py", "src/pages_verify.py", "src/pages_oracle.py",
    "src/pages_http_check.py", "src/pages_browser_check.py",
    "tests/test_pages_static.py", "tests/fixtures/pages-oracle-control.txt",
    "tests/fixtures/pages-oracle-control.html.txt", "docs/pages-home.md", "docs/pages-static.md",
    "evidence/local-baseline.json", "evidence/development-3b-failure.json",
    "evidence/development-7b-timeout.json", "evidence/development-reasoning-timeout.json",
    "evidence/local-baseline-repeat.json",
    "src/accountless_native.py", "ledgers/accountless-native.json",
    "schemas/accountless-native-result.schema.json", "requirements/accountless-native.txt",
    "fixtures/accountless-native/gsm8k-test-record-0000.json",
    "tests/test_accountless_native.py", "docs/accountless-native.md",
    "data/experiment/accountless-native-quickstart.json",
    "src/cache_reuse.py", "src/cache_runtime_context.py", "config/cache-runtime-context.json",
    "ledgers/cache-reuse.template.json",
    "schemas/cache-reuse-ledger.schema.json", "schemas/cache-reuse-runtime-facts.schema.json",
    "schemas/cache-reuse-result.schema.json", "fixtures/cache-reuse/fake-transport.json",
    "fixtures/cache-reuse/runtime-facts.template.json",
    "fixtures/cache-reuse/runtime-context-attestation.template.json",
    "tests/test_cache_reuse.py", "tests/test_cache_runtime_context.py",
    "tests/test_runtime_owner_handoff.py", "docs/cache-reuse.md",
    "docs/runtime-owner-handoff.md",
    "src/__init__.py", "src/compressors.py", "src/protection.py", "src/pipeline.py",
    "src/measurement.py", "src/provenance.py", "src/contracts.py", "src/static_run.py",
    "src/compare.py", "src/eda.py",
    "schemas/static-ledger.schema.json", "schemas/static-result.schema.json", "schemas/frozen-input.schema.json",
    "ledgers/static.toml", "ledgers/demo.toml",
    "examples/static/manifest.json", "examples/static/requests/0000.json",
    "examples/README.md", "examples/README_en.md",
    "ledgers/README.md", "ledgers/README_en.md",
    "data/eda/task-candidate-share.csv", "data/eda/lineage.json", "figures/task-candidate-share.svg",
    "docs/local-native.md", "docs/static-contract.md", "docs/publication.md",
    "docs_en/README.md", "docs_en/SNAPSHOT.md",
    "docs_en/pages-home.md", "docs_en/pages-static.md",
    "docs_en/publication.md", "docs_en/static-contract.md",
    "docs/experiment/README.md", "docs/experiment/protocol.md", "docs/experiment/baseline.md",
    "docs/experiment/compressors.md", "docs/experiment/decisions.md",
    "docs/experiment/screening-protocol.md", "docs/experiment/evaluation-protocol.md",
    "docs/experiment/reproducibility-contract.md", "docs/experiment/execution-safety-policy.md",
    "docs/experiment/01-preliminary-comparison/preliminary-comparison-20260916.md",
    "docs/experiment/01-preliminary-comparison/plain-language-results-20260917.md",
    "docs/experiment/01-preliminary-comparison/experiment-briefing-20260919.md",
    "docs/experiment/data-connection-guide-20260919.md",
    "docs/experiment/01-preliminary-comparison/lossless-lossy-compression-20260919.md",
    "docs/experiment/01-preliminary-comparison/README.md",
    "docs/experiment/01-preliminary-comparison/tasks.md",
    "docs/experiment/01-preliminary-comparison/metrics.md",
    "docs/experiment/01-preliminary-comparison/outcome-cost-accounting-20260918.md",
    "docs/experiment/01-preliminary-comparison/outcome-cost-accounting-plan-20260918.md",
    "docs/experiment/01-preliminary-comparison/visualization-guide-20260919.md",
    "docs_en/experiment/README.md", "docs_en/experiment/protocol.md",
    "docs_en/experiment/baseline.md", "docs_en/experiment/compressors.md",
    "docs_en/experiment/decisions.md", "docs_en/experiment/screening-protocol.md",
    "docs_en/experiment/evaluation-protocol.md",
    "docs_en/experiment/reproducibility-contract.md",
    "docs_en/experiment/execution-safety-policy.md",
    "docs_en/experiment/data-connection-guide-20260919.md",
    "docs_en/experiment/swe-lancer-candidate-evaluation-20260920.md",
    "docs_en/experiment/01-preliminary-comparison/README.md",
    "docs_en/experiment/01-preliminary-comparison/tasks.md",
    "docs_en/experiment/01-preliminary-comparison/metrics.md",
    "docs_en/experiment/01-preliminary-comparison/preliminary-comparison-20260916.md",
    "docs_en/experiment/01-preliminary-comparison/plain-language-results-20260917.md",
    "docs_en/experiment/01-preliminary-comparison/experiment-briefing-20260919.md",
    "docs_en/experiment/01-preliminary-comparison/lossless-lossy-compression-20260919.md",
    "docs_en/experiment/01-preliminary-comparison/outcome-cost-accounting-20260918.md",
    "docs_en/experiment/01-preliminary-comparison/outcome-cost-accounting-plan-20260918.md",
    "docs_en/experiment/01-preliminary-comparison/visualization-guide-20260919.md",
    "data/experiment/coverage-validation-v1.json",
    "data/experiment/terminal-bench-2.1-task-types.json", "ledgers/screening.template.toml",
    "data/experiment/preliminary-comparison-summary.json",
    "data/experiment/readme-benchmark-validation.json",
    "data/experiment/readme-benchmark-validation-20260920.json",
    "data/experiment/readme-benchmark-validation-20260920-accountless.json",
    "data/experiment/outcome-cost-evidence.json",
    "data/experiment/outcome-cost-accounting.json",
    "tests/test_protection.py", "tests/test_static.py", "tests/test_eda.py", "tests/test_compare.py",
    "src/eda_report.py", "tests/test_eda_report.py", "tests/test_document_localization.py",
    "docs/eda/README.md", "docs/eda/manifest.json",
    "docs_en/eda/README.md", "docs_en/eda/manifest.json",
    "docs/eda/figures/round1/01-input-size.svg", "docs/eda/figures/round1/02-input-composition.svg",
    "docs/eda/figures/round1/03-compressible-share.svg", "docs/eda/figures/round1/04-shared-prefix.svg",
    "docs/eda/figures/round1/05-corpus-bias.svg", "docs/eda/figures/round1/06-api-token-calibration.svg",
    "docs/eda/figures/round2/01-task-types.svg", "docs/eda/figures/round2/02-candidate-share-by-type.svg",
    "docs/eda/figures/round2/03-input-size-by-type.svg", "docs/eda/figures/round2/04-unknown-decomposition.svg",
    "src/baseline.py", "src/command_trace.py", "src/harbor_agent.py", "src/harbor_no_time_limits.py", "src/live_observations.py",
    "src/live_transport.py", "src/native_contract.py", "src/native_judge.py", "src/native_run.py",
    "src/llmlingua_worker.py", "src/adapter_preflight.py", "src/blob_retrieval.py", "src/prompt_intake.py", "src/task_metrics.py",
    "src/squeez_recovery.py", "src/local_recovery.py", "ledgers/recovery.template.toml", "docs/squeez-recovery.md",
    "src/swe_lancer_admission.py", "src/swe_lancer_carrier.py",
    "config/swe-lancer-carrier.json", "ledgers/swe-lancer.template.json",
    "fixtures/swe-lancer/carrier-attestation.template.json",
    "tests/test_swe_lancer_admission.py", "tests/test_swe_lancer_carrier.py",
    "docs/experiment/swe-lancer-candidate-evaluation-20260920.md",
    "data/experiment/swe-lancer-candidate-evaluation.json",
    "src/verifier_revisions.py", "verifiers/terminal-bench-2.1/nginx-request-logging/revision.json",
    "requirements/llmlingua2-cpu.txt", "fixtures/llmlingua2/path-listing.txt",
    "fixtures/llmlingua2/severity-log.txt", "fixtures/llmlingua2/package-install.txt",
    "fixtures/verifiers/nginx-request-logging/unbraced.conf",
    "fixtures/verifiers/nginx-request-logging/braced.conf",
    "fixtures/verifiers/nginx-request-logging/wrong-variable.conf",
    "ledgers/native.template.toml", "docs/native-contract.md",
    "src/experiment_run.py", "src/runtime_limits.py", "src/execution_safety.py",
    "src/benchmark_run.py", "src/experiment_figures.py",
    "schemas/experiment-request.schema.json", "schemas/experiment-result.schema.json",
    "schemas/execution-safety-policy.schema.json",
    "schemas/benchmark-request.schema.json",
    "examples/experiment/static.yaml", "examples/experiment/native.yaml",
    "examples/experiment/benchmark.yaml",
    "examples/experiment/static-result.json", "examples/experiment/native-preflight-result.json",
    "tests/native_helpers.py", "tests/test_baseline.py", "tests/test_live_observations.py",
    "tests/test_live_transport.py", "tests/test_native_judge.py", "tests/test_prompt_intake.py",
    "tests/test_task_metrics.py", "tests/test_native_contract.py", "tests/test_native_run.py",
    "tests/test_native_compressors.py", "tests/test_adapter_preflight.py", "tests/test_blob_retrieval.py", "tests/test_harbor_transport.py",
    "tests/test_squeez_recovery.py", "tests/test_local_recovery.py",
    "tests/native_test_harbor_preflight.py", "tests/test_verifier_revisions.py",
    "src/evaluation_coverage.py", "src/evaluation_statistics.py", "src/replay_environment.py",
    "src/screening_contract.py", "src/screening_cost.py", "src/screening_inventory.py",
    "src/screening_run.py", "src/screening_scheduler.py",
    "src/preliminary_comparison.py", "tests/test_preliminary_comparison.py",
    "tests/native_test_replay_environment.py", "tests/native_test_screening_run.py",
    "tests/test_evaluation_coverage.py", "tests/test_evaluation_statistics.py",
    "tests/test_screening_contract.py", "tests/test_screening_cost.py",
    "tests/test_screening_inventory.py", "tests/test_screening_scheduler.py",
    "tests/test_experiment_run.py", "tests/test_benchmark_run.py",
    "tests/test_execution_safety.py",
    "tests/test_experiment_figures.py", "tests/test_experiment_briefing.py",
    "tests/test_lossless_lossy_document.py",
    "tests/test_first_study_metrics.py",
    "src/outcome_cost_accounting.py", "tests/test_outcome_cost_accounting.py",
    "schemas/outcome-cost-accounting.schema.json",
    "tests/test_outcome_cost_plan.py",
    "figures/preliminary-quality.svg", "figures/preliminary-changed-conditions.svg",
    "figures/preliminary-changed-spans.svg", "figures/preliminary-request-events.svg",
    "figures/preliminary-provider-usage.svg", "figures/preliminary-calculated-cost.svg",
}

TIMING_ROWS = (
    ("image_preparation", "Image availability checks / cached pulls"),
    ("ollama_start", "Ollama container start"),
    ("model_pull_or_cache_check", "Model pull / cached-model check"),
    ("environment_setup", "Task environment start"),
    ("agent_setup", "Agent setup"),
    ("agent_execution", "Agent execution"),
    ("verifier", "Native verifier"),
    ("other", "Other startup, response drain and cleanup (remainder)"),
)


def phase_timings(source: dict, native_results: list[dict], whole_seconds: float) -> dict:
    phases = source["phases"]
    runner_timers = {
        name: phases[name]["elapsed_seconds"]
        for name in ("ollama_image", "task_image", "ollama_start", "model_download")
    }
    native_timers = []
    for result in native_results:
        native_timers.append({
            name: (
                datetime.fromisoformat(result[name]["finished_at"])
                - datetime.fromisoformat(result[name]["started_at"])
            ).total_seconds()
            for name in ("environment_setup", "agent_setup", "agent_execution", "verifier")
        })
    components = {
        "image_preparation": runner_timers["ollama_image"] + runner_timers["task_image"],
        "ollama_start": runner_timers["ollama_start"],
        "model_pull_or_cache_check": runner_timers["model_download"],
        **{name: sum(timer[name] for timer in native_timers)
           for name in ("environment_setup", "agent_setup", "agent_execution", "verifier")},
    }
    components["other"] = whole_seconds - sum(components.values())
    return {
        "kind": "calculated", "source": "runner_clocks_and_native_phase_timestamps",
        "unit": "seconds", "components": components,
        "runner_timers": runner_timers, "native_timers": native_timers,
        "note": "Agent execution includes local inference and commands. Other is a subtraction, not an isolated timer.",
    }


def validate_public_files(paths: list[str]) -> None:
    unexpected = set(paths) - PUBLIC_FILES
    if unexpected:
        raise ValueError(f"Files have no publication grade: {sorted(unexpected)}")


def audit_files(root: Path) -> None:
    archive_prompts(root)
    paths = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    ).decode().split("\0")
    validate_public_files([path for path in paths if path])
    if any(path.startswith("docs/eda/") for path in paths):
        audit_report(root)


def export(directory: Path, target: Path) -> None:
    source = verify(directory)
    attempts = [
        {key: value for key, value in record.items() if key in ATTEMPT_FIELDS}
        for record in read_attempts(directory)
        if record["record_type"] == "provider_attempt"
    ]
    output = {key: value for key, value in source.items() if key in SUMMARY_FIELDS}
    output["disclosure"] = "sanitized_measurements"
    output["raw_summary_sha256"] = sha256((directory / "summary.json").read_bytes())
    output["attempts"] = attempts
    output["expect"] = tomllib.loads((directory / "ledger.toml").read_text())["expect"]
    output["error_type"] = source.get("error", {}).get("type")
    timing = directory / "whole-command-time.txt"
    if timing.exists():
        values = dict(line.split() for line in timing.read_text().splitlines())
        output["whole_command_time"] = {
            "kind": "measured", "source": "external_time_command",
            "seconds": float(values["real"]), "raw_sha256": sha256(timing.read_bytes()),
        }
    output["trials"] = []
    native_results = []
    for trial in source["trials"]:
        result = json.loads((directory / trial["native_result"]).read_text())
        native_results.append(result)
        ctrf_path = (directory / trial["native_result"]).parent / "verifier/ctrf.json"
        tests = json.loads(ctrf_path.read_text())["results"]
        output["trials"].append({
            "kind": "measured", "source": "terminal_bench_native_verifier",
            "repetition": trial["repetition"], "reward": trial["reward"],
            "native_result_sha256": trial["native_result_sha256"],
            "native_exception_type": (result.get("exception_info") or {}).get("exception_type"),
            "tests": [{"name": test["name"], "status": test["status"]} for test in tests["tests"]],
        })
    if "whole_command_time" in output and native_results:
        output["phase_timings"] = phase_timings(source, native_results, output["whole_command_time"]["seconds"])
    if target.exists():
        raise ValueError("Evidence exists; choose a new filename rather than overwriting it")
    target.parent.mkdir(parents=True, exist_ok=True)
    save(target, output)
    check(target)


def check(path: Path) -> dict:
    data = json.loads(path.read_text())
    if set(data) - (SUMMARY_FIELDS | {
        "disclosure", "raw_summary_sha256", "attempts", "trials", "expect", "error_type",
        "whole_command_time",
        "phase_timings",
    }):
        raise ValueError("Non-allowlisted data in the public summary")
    if data["disclosure"] != "sanitized_measurements":
        raise ValueError("Unknown evidence disclosure grade")
    if "source_commit" in data:
        require_commit_sha(data["source_commit"])
    if totals(data["attempts"]) != data["usage_totals"]:
        raise ValueError("Evidence counters differ in either direction from the attempt records")
    for record in data["attempts"]:
        if set(record) - ATTEMPT_FIELDS:
            raise ValueError("Non-allowlisted data in a public attempt")
        for key in ("run_id", "ledger_sha256", "source_sha256", "model"):
            if record[key] != data[key]:
                raise ValueError(f"Evidence lineage differs: {key}")
    if data["status"] not in ("passed", "failed", "error"):
        raise ValueError("Unknown execution status")
    if len(data["trials"]) != data["repetitions"] and data["status"] != "error":
        raise ValueError("Evidence must contain exactly the declared number of native trials")
    for trial in data["trials"]:
        if trial["reward"] not in (0, 1):
            raise ValueError("Invalid native reward")
        if trial["reward"] == 1 and (
            not trial["tests"] or any(test["status"] != "passed" for test in trial["tests"])
        ):
            raise ValueError("Passing reward is not supported by the native test records")
    met_expectation = len(data["trials"]) == data["repetitions"] and all(
        data["expect"]["reward_min"] <= trial["reward"] <= data["expect"]["reward_max"]
        for trial in data["trials"]
    )
    if data["status"] != "error" and (data["status"] == "passed") != met_expectation:
        raise ValueError("Execution status differs from the declared native reward contract")
    if "phase_timings" in data:
        timing = data["phase_timings"]
        components = timing["components"]
        if set(components) != {name for name, _ in TIMING_ROWS}:
            raise ValueError("Unknown or missing phase timing")
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
               for value in components.values()):
            raise ValueError("Phase timings must be finite nonnegative seconds")
        timers = timing["runner_timers"]
        expected = {
            "image_preparation": timers["ollama_image"] + timers["task_image"],
            "ollama_start": timers["ollama_start"],
            "model_pull_or_cache_check": timers["model_download"],
            **{name: sum(timer[name] for timer in timing["native_timers"])
               for name in ("environment_setup", "agent_setup", "agent_execution", "verifier")},
        }
        expected["other"] = data["whole_command_time"]["seconds"] - sum(expected.values())
        if any(not math.isclose(components[name], value, abs_tol=1e-6)
               for name, value in expected.items()):
            raise ValueError("Timing breakdown differs from the recorded timers")
    return data


def result_text(data: dict) -> str:
    tests = [test for trial in data["trials"] for test in trial["tests"]]
    passed = sum(test["status"] == "passed" for test in tests)
    usage = data["usage_totals"]
    return (
        f"Recorded {data['started_at'][:10]}: `{data['model']}`, "
        f"{data['repetitions']} repetition, no added compression.\n"
        f"Native checks: **{passed}/{len(tests)}**; execution: **{data['status']}**.\n"
        f"Local provider tokens: **{usage['input_tokens']:,} input / "
        f"{usage['output_tokens']:,} output**; responses: **{usage['responses_with_usage']}**.\n"
        f"HTTP 429: **{usage['http_429']}**; retries: **{usage['retries']}**.\n"
        f"Whole command: **{data['whole_command_time']['seconds']:.2f} seconds**."
    )


def repeat_result_text(data: dict) -> str:
    tests = [test for trial in data["trials"] for test in trial["tests"]]
    passed = sum(test["status"] == "passed" for test in tests)
    exception = data["trials"][0]["native_exception_type"]
    return (
        f"One unchanged repeat took **{data['whole_command_time']['seconds']:.2f} seconds** "
        f"and ended with **{exception}**\n"
        f"(execution `{data['status']}`, native checks **{passed}/{len(tests)}**)."
    )


def timing_comparison_text(first: dict, second: dict) -> str:
    for field in (
        "ledger_sha256", "source_sha256", "source_files", "environment", "model",
        "model_manifest_sha256", "ollama_version", "intervention", "repetitions",
    ):
        if first[field] != second[field]:
            raise ValueError(f"Timing comparison conditions differ: {field}")
    lines = [
        "| Phase (seconds) | Earlier accepted run | One unchanged repeat |",
        "|---|---:|---:|",
    ]
    for name, label in TIMING_ROWS:
        lines.append(
            f"| {label} | {first['phase_timings']['components'][name]:.2f} "
            f"| {second['phase_timings']['components'][name]:.2f} |"
        )
    lines.append(
        f"| **Whole command** | **{first['whole_command_time']['seconds']:.2f}** "
        f"| **{second['whole_command_time']['seconds']:.2f}** |"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "check", "audit-files"])
    parser.add_argument("path", type=Path)
    parser.add_argument("target", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action == "export":
        if args.target is None:
            parser.error("export requires a target JSON path")
        export(args.path, args.target)
        print(args.target)
    elif args.action == "check":
        result = check(args.path)
        print(json.dumps({"run_id": result["run_id"], "status": result["status"]}))
    else:
        audit_files(args.path)
        print("All non-ignored files have a publication grade.")


if __name__ == "__main__":
    main()
