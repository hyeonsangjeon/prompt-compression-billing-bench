"""Export only allowlisted measurements, never prompts, generated keys, or endpoints."""

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

from accounting import read_attempts, sha256, totals
from run import save, verify


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
    "finished_at", "status", "ledger_sha256", "source_sha256", "source_files",
    "model", "tokenizer", "intervention", "repetitions", "environment",
    "elapsed_seconds", "usage_totals", "model_manifest_sha256",
    "ollama_version", "model_cache_present_before_run", "not_proven",
}
PUBLIC_FILES = {
    ".gitignore", ".python-version", "pyproject.toml", "uv.lock", "ledger.toml",
    "run.py", "accounting.py", "evidence.py", "README.md", "STATUS.md",
    "tests/test_accounting.py", "tests/test_evidence.py", ".github/workflows/check.yml",
    "evidence/local-baseline.json", "evidence/development-3b-failure.json",
    "evidence/development-7b-timeout.json", "evidence/development-reasoning-timeout.json",
}


def validate_public_files(paths: list[str]) -> None:
    unexpected = set(paths) - PUBLIC_FILES
    if unexpected:
        raise ValueError(f"Files have no publication grade: {sorted(unexpected)}")


def audit_files(root: Path) -> None:
    paths = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    ).decode().split("\0")
    validate_public_files([path for path in paths if path])


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
    for trial in source["trials"]:
        ctrf_path = (directory / trial["native_result"]).parent / "verifier/ctrf.json"
        tests = json.loads(ctrf_path.read_text())["results"]
        output["trials"].append({
            "kind": "measured", "source": "terminal_bench_native_verifier",
            "repetition": trial["repetition"], "reward": trial["reward"],
            "native_result_sha256": trial["native_result_sha256"],
            "tests": [{"name": test["name"], "status": test["status"]} for test in tests["tests"]],
        })
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
    }):
        raise ValueError("Non-allowlisted data in the public summary")
    if data["disclosure"] != "sanitized_measurements":
        raise ValueError("Unknown evidence disclosure grade")
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
