"""Dispatch offline static measurements or the separate local Ollama native runner."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from accounting import AttemptRecorder, now, read_attempts, sha256, start_proxy, totals


ROOT = Path(__file__).resolve().parent
SOURCE_FILES = ("run.py", "accounting.py", "pyproject.toml", "uv.lock")
FIELDS = {
    "benchmark": {"name", "version", "repository", "revision", "task", "image", "judge"},
    "model": {
        "provider", "name", "manifest_sha256", "server_image", "context_tokens",
        "max_output_tokens", "temperature", "reasoning_effort", "credential_env_names",
    },
    "runner": {
        "harbor_version", "agent", "agent_timeout_seconds",
        "verifier_timeout_seconds", "setup_timeout_seconds",
    },
    "retry": {"max_attempts_per_call", "http_statuses", "delay_seconds", "max_delay_seconds"},
    "limits": {"api_cost_usd", "max_calls_per_repetition", "request_timeout_seconds"},
    "expect": {"reward_min", "reward_max"},
}


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def load_ledger(path: Path) -> dict:
    ledger = tomllib.loads(path.read_text())
    expected = set(FIELDS) | {"schema_version", "intervention", "repetitions", "output_dir"}
    if set(ledger) != expected:
        raise ValueError(f"Ledger top-level fields differ: {set(ledger) ^ expected}")
    for section, names in FIELDS.items():
        if not isinstance(ledger[section], dict) or set(ledger[section]) != names:
            raise ValueError(f"Unexpected or missing fields in [{section}]")
    if ledger["schema_version"] != 1 or ledger["intervention"] != "none":
        raise ValueError("Only schema_version=1 and intervention=none are implemented")
    if type(ledger["repetitions"]) is not int or ledger["repetitions"] < 1:
        raise ValueError("repetitions must be a positive integer")
    benchmark, model, runner = (ledger[key] for key in ("benchmark", "model", "runner"))
    if benchmark["name"] != "terminal-bench" or benchmark["judge"] != "native":
        raise ValueError("Only Terminal-Bench with its native judge is implemented")
    if benchmark["repository"] != "https://github.com/harbor-framework/terminal-bench-2-1.git":
        raise ValueError("This first runner supports the pinned Terminal-Bench 2.1 repository only")
    if benchmark["version"] != "2.1" or not re.fullmatch(r"[0-9a-f]{40}", benchmark["revision"]):
        raise ValueError("Terminal-Bench version and immutable revision are required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", benchmark["task"]):
        raise ValueError("task must be a single task directory name")
    if model["provider"] != "ollama" or model["credential_env_names"] != []:
        raise ValueError("Only a managed, accountless local Ollama model is implemented")
    if not re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_.-]+", model["name"]) or "cloud" in model["name"]:
        raise ValueError("A local Ollama library model and tag are required")
    if not re.fullmatch(r"[0-9a-f]{64}", model["manifest_sha256"]):
        raise ValueError("Pin the Ollama model manifest SHA-256")
    for image in (benchmark["image"], model["server_image"]):
        if not re.fullmatch(r"[a-z0-9_./-]+@sha256:[0-9a-f]{64}", image):
            raise ValueError("Both Docker images must be pinned by digest")
    if not model["server_image"].startswith("ollama/ollama@"):
        raise ValueError("Use the official local Ollama server image")
    if runner["agent"] != "terminus-2":
        raise ValueError("The first runner uses Terminus 2, not an oracle or mock agent")
    if model["reasoning_effort"] not in ("none", "low", "medium", "high"):
        raise ValueError("Use an explicit supported Ollama reasoning_effort")
    if type(ledger["limits"]["api_cost_usd"]) not in (int, float) or ledger["limits"]["api_cost_usd"] != 0:
        raise ValueError("Only zero-API-spend local execution is supported; cloud billing is not implemented")
    for section, key in (
        ("model", "context_tokens"), ("model", "max_output_tokens"),
        ("runner", "agent_timeout_seconds"), ("runner", "verifier_timeout_seconds"),
        ("runner", "setup_timeout_seconds"), ("limits", "max_calls_per_repetition"),
        ("limits", "request_timeout_seconds"), ("retry", "max_attempts_per_call"),
    ):
        if type(ledger[section][key]) is not int or ledger[section][key] < 1:
            raise ValueError(f"{section}.{key} must be a positive integer")
    if ledger["retry"]["http_statuses"] != [429]:
        raise ValueError("Only explicit HTTP 429 retries are supported; ambiguous network failures are not retried")
    for value in (model["temperature"], ledger["retry"]["delay_seconds"], ledger["retry"]["max_delay_seconds"]):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Temperature and retry delays must be finite numbers")
    if not 0 <= ledger["retry"]["delay_seconds"] <= ledger["retry"]["max_delay_seconds"]:
        raise ValueError("Retry delays must be nonnegative and bounded")
    if not 0 <= ledger["expect"]["reward_min"] <= ledger["expect"]["reward_max"] <= 1:
        raise ValueError("Native reward bounds must lie between 0 and 1")
    output = Path(ledger["output_dir"])
    if not output.parts or output.is_absolute() or ".." in output.parts or output.parts[0] in (".git", "evidence", ".cache"):
        raise ValueError("output_dir must be a relative, non-reserved directory")
    return ledger


def require_commit_sha(source_commit: str | None) -> str:
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit must be a full 40-character SHA; specify --source-commit for execution")
    return source_commit


def source_git(*arguments: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "--no-replace-objects", "-C", str(ROOT), *arguments], stderr=subprocess.PIPE,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip()
        raise ValueError(f"Source Git verification failed: {detail}") from exc


def committed_inputs(source_commit: str | None, ledger_source_path: str | None) -> dict[str, bytes]:
    source_commit = require_commit_sha(source_commit)
    if source_git("cat-file", "-t", source_commit).strip() != b"commit":
        raise ValueError("source_commit must identify a Git commit object")
    if not isinstance(ledger_source_path, str) or not ledger_source_path:
        raise ValueError("Missing committed ledger_source_path")
    path = Path(ledger_source_path)
    if not path.parts or path.is_absolute() or ".." in path.parts or path.as_posix() != ledger_source_path:
        raise ValueError("ledger_source_path must be a repository-relative file path")
    return {
        name: source_git("show", f"{source_commit}:{name}")
        for name in (*SOURCE_FILES, ledger_source_path)
    }


def capture_source(
    ledger_path: Path, ledger: dict, source_commit: str | None,
) -> tuple[dict, bytes, dict[str, bytes]]:
    source_commit = require_commit_sha(source_commit)
    if source_git("rev-parse", "--show-toplevel").decode().strip() != str(ROOT):
        raise ValueError("Execution source must be at the Git checkout root")
    if source_git("rev-parse", "--verify", "HEAD").decode().strip() != source_commit:
        raise ValueError("Checkout HEAD differs from the designated source_commit")
    if source_git("status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"):
        raise ValueError("Execution checkout has tracked changes or untracked files; use a clean committed checkout")
    try:
        ledger_source_path = ledger_path.resolve().relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("Execution ledger must be inside the source checkout") from exc
    committed = committed_inputs(source_commit, ledger_source_path)
    captured = {name: (ROOT / name).read_bytes() for name in committed}
    for name, content in captured.items():
        if content != committed[name]:
            raise ValueError(f"Execution input differs from source_commit: {name}")
    ledger_bytes = captured[ledger_source_path]
    if tomllib.loads(ledger_bytes.decode("utf-8")) != ledger:
        raise ValueError("Parsed ledger differs from its captured committed bytes")
    source_bytes = {name: captured[name] for name in SOURCE_FILES}
    source_files = {name: sha256(content) for name, content in source_bytes.items()}
    provenance = {
        "source_commit": source_commit, "source_snapshot": "source",
        "source_files": source_files,
        "source_sha256": sha256(json.dumps(source_files, sort_keys=True).encode()),
        "ledger_source_path": ledger_source_path, "ledger_sha256": sha256(ledger_bytes),
    }
    return provenance, ledger_bytes, source_bytes


def preflight(ledger: dict) -> dict:
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise ValueError("This first execution path requires Linux x86_64 with Docker")
    for command in ("git", "docker"):
        if not shutil.which(command):
            raise ValueError(f"Missing dependency: {command}; install it before running")
    installed = importlib.metadata.version("harbor")
    if installed != ledger["runner"]["harbor_version"]:
        raise ValueError("Harbor differs from the ledger; run uv sync --locked --extra native")
    info = subprocess.run(
        ["docker", "info", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    docker = json.loads(info.stdout)
    if docker["OSType"] != "linux":
        raise ValueError("A Linux Docker daemon is required")
    return {
        "kernel": platform.release(), "platform": "linux/amd64",
        "cpus": docker["NCPU"], "memory_bytes": docker["MemTotal"],
        "docker_version": docker["ServerVersion"], "harbor_version": installed,
    }


def execute(command: list[str], log: Path, timeout: float, *, env=None) -> dict:
    started_at, started = now(), time.monotonic()
    with log.open("xb") as output:
        process = subprocess.Popen(
            command, stdout=output, stderr=subprocess.STDOUT,
            env=env, start_new_session=True,
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise TimeoutError(f"Command deadline exceeded; see {log.name}") from None
    phase = {
        "kind": "measured", "source": "runner_monotonic_clock",
        "started_at": started_at, "finished_at": now(),
        "elapsed_seconds": time.monotonic() - started, "returncode": code,
        "log": log.name,
    }
    if code:
        raise RuntimeError(f"Command exited {code}; see {log.name}")
    return phase


def api(url: str, data: dict | None = None, timeout: int = 30) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def materialize_task(ledger: dict, directory: Path, phases: dict) -> Path:
    benchmark = ledger["benchmark"]
    cache = ROOT / ".cache" / ("terminal-bench-" + benchmark["revision"])
    timeout = ledger["runner"]["setup_timeout_seconds"]
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        phases["task_fetch"] = execute(
            ["git", "clone", "--quiet", "--filter=blob:none", "--sparse", "--no-checkout",
             benchmark["repository"], str(cache)],
            directory / "task-fetch.log", timeout,
        )
        phases["task_select"] = execute(
            ["git", "-C", str(cache), "sparse-checkout", "set", "tasks/" + benchmark["task"]],
            directory / "task-select.log", timeout,
        )
        phases["task_checkout"] = execute(
            ["git", "-C", str(cache), "checkout", "--quiet", benchmark["revision"]],
            directory / "task-checkout.log", timeout,
        )
    revision = subprocess.check_output(["git", "-C", str(cache), "rev-parse", "HEAD"]).decode().strip()
    if revision != benchmark["revision"]:
        raise ValueError("Task cache revision differs from the ledger")
    subprocess.run(["git", "-C", str(cache), "diff", "--exit-code", "HEAD"], check=True, capture_output=True)
    source = cache / "tasks" / benchmark["task"]
    if not source.is_dir():
        raise ValueError("Selected task is not materialized; remove only its .cache checkout and retry")
    destination = directory / "task"
    shutil.copytree(source, destination)
    config = destination / "task.toml"
    text = config.read_text()
    text, changed = re.subn(
        r'(?m)^docker_image = "[^"]+"$',
        f'docker_image = "{benchmark["image"]}"', text,
    )
    if changed != 1:
        raise ValueError("Expected one native task image; refusing an ambiguous override")
    config.write_text(text)
    return destination


def run(ledger_path: Path, ledger: dict, *, source_commit: str | None = None) -> Path:
    provenance, ledger_bytes, source_bytes = capture_source(ledger_path, ledger, source_commit)
    os.umask(0o077)
    environment = preflight(ledger)
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(4)
    directory = ledger_path.parent / ledger["output_dir"] / run_id
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "ledger.toml").write_bytes(ledger_bytes)
    source_hash = provenance["source_sha256"]
    snapshot = directory / "source"
    snapshot.mkdir()
    for name, content in source_bytes.items():
        (snapshot / name).write_bytes(content)
    summary = {
        "schema_version": 1, "record_type": "run_summary", "kind": "calculated",
        "source": "recorded_provider_attempts_and_native_verifier",
        "run_id": run_id, "started_at": now(), "status": "running",
        **provenance, "model": ledger["model"]["name"],
        "tokenizer": "unverified", "intervention": "none",
        "repetitions": ledger["repetitions"], "environment": environment,
        "phases": {}, "trials": [], "limits": ledger["limits"],
        "disclosure": "private_raw", "not_proven": [
            "Provider billing or paid API spending", "Compression effectiveness",
            "Repeated-run stability", "Performance on other Terminal-Bench tasks",
        ],
    }
    save(directory / "summary.json", summary)
    print(f"Run: {directory}", flush=True)
    server_name = "billing-bench-ollama-" + run_id.lower()
    server_created = False
    started = time.monotonic()
    try:
        task = materialize_task(ledger, directory, summary["phases"])
        model = ledger["model"]
        timeout = ledger["runner"]["setup_timeout_seconds"]
        for name, image in (("ollama_image", model["server_image"]), ("task_image", ledger["benchmark"]["image"])):
            summary["phases"][name] = execute(
                ["docker", "pull", "--platform", "linux/amd64", image],
                directory / f"{name}.log", timeout,
            )
        models = ROOT / ".cache" / "ollama-models"
        models.mkdir(parents=True, exist_ok=True)
        summary["model_cache_present_before_run"] = (models / "models/manifests").exists()
        summary["phases"]["ollama_start"] = execute(
            ["docker", "run", "-d", "--name", server_name,
             "-p", "127.0.0.1::11434", "-v", f"{models}:/root/.ollama",
             "-e", "OLLAMA_NO_CLOUD=1", "-e", "OLLAMA_NUM_PARALLEL=1",
             "-e", f"OLLAMA_CONTEXT_LENGTH={model['context_tokens']}",
             model["server_image"]],
            directory / "ollama-start.log", timeout,
        )
        server_created = True
        address = subprocess.check_output(["docker", "port", server_name, "11434/tcp"]).decode().strip()
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", address):
            raise ValueError("Managed Ollama must bind only to IPv4 loopback")
        endpoint = "http://" + address
        for _ in range(30):
            try:
                summary["ollama_version"] = api(endpoint + "/api/version")["version"]
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(1)
        else:
            raise TimeoutError("Managed Ollama did not become ready")
        model_start = time.monotonic()
        pulled = api(endpoint + "/api/pull", {"model": model["name"], "stream": False}, timeout)
        if pulled.get("status") != "success":
            raise ValueError(f"Ollama pull failed: {pulled}")
        tags = api(endpoint + "/api/tags")["models"]
        matching = [tag for tag in tags if tag["name"] == model["name"]]
        if len(matching) != 1 or matching[0]["digest"] != model["manifest_sha256"]:
            raise ValueError("Ollama model manifest differs from the ledger")
        summary["model_manifest_sha256"] = matching[0]["digest"]
        summary["phases"]["model_download"] = {
            "kind": "measured", "source": "runner_monotonic_clock",
            "elapsed_seconds": time.monotonic() - model_start,
        }
        native_config = tomllib.loads((task / "task.toml").read_text())
        harbor = str(Path(sys.executable).parent / "harbor")
        for repetition in range(1, ledger["repetitions"] + 1):
            key = secrets.token_urlsafe(32)
            recorder = AttemptRecorder(
                directory / f"repetition-{repetition:03d}", ledger, run_id, repetition,
                summary["ledger_sha256"], source_hash, endpoint, key,
            )
            proxy = start_proxy(recorder)
            proxy_url = f"http://127.0.0.1:{proxy.server_port}/v1"
            environment_vars = {
                **os.environ, "OPENAI_API_KEY": key, "LITELLM_TELEMETRY": "false",
                "TMPDIR": str(ROOT / ".cache" / "tmp"),
                "XDG_CACHE_HOME": str(ROOT / ".cache"),
            }
            Path(environment_vars["TMPDIR"]).mkdir(exist_ok=True)
            model_info = {
                "max_input_tokens": model["context_tokens"],
                "max_output_tokens": model["max_output_tokens"],
                "input_cost_per_token": 0, "output_cost_per_token": 0,
                "litellm_provider": "openai", "mode": "chat",
            }
            command = [
                harbor, "run", "-p", str(task), "-e", "docker", "-a", "terminus-2",
                "-m", "openai/" + model["name"], "-n", "1", "-k", "1", "-r", "0",
                "--ak", f"api_base={proxy_url}",
                "--ak", f"max_turns={ledger['limits']['max_calls_per_repetition']}",
                "--ak", "enable_summarize=false", "--ak", "use_responses_api=false",
                "--ak", "store_all_messages=true", "--ak", f"temperature={model['temperature']}",
                "--ak", "llm_call_kwargs=" + json.dumps({
                    "extra_body": {"reasoning_effort": model["reasoning_effort"]}
                }),
                "--ak", "model_info=" + json.dumps(model_info),
                "--ak", "llm_kwargs=" + json.dumps({"max_tokens": model["max_output_tokens"], "num_retries": 0}),
                "--agent-timeout-multiplier", str(
                    ledger["runner"]["agent_timeout_seconds"] / native_config["agent"]["timeout_sec"]
                ),
                "--verifier-timeout-multiplier", str(
                    ledger["runner"]["verifier_timeout_seconds"] / native_config["verifier"]["timeout_sec"]
                ),
                "--jobs-dir", str(directory / "native"),
                "--job-name", f"repetition-{repetition:03d}", "-q",
            ]
            try:
                summary["phases"][f"repetition-{repetition:03d}"] = execute(
                    command, directory / f"repetition-{repetition:03d}.log",
                    timeout + ledger["runner"]["agent_timeout_seconds"]
                    + ledger["runner"]["verifier_timeout_seconds"] + 60,
                    env=environment_vars,
                )
            finally:
                proxy.shutdown()
                proxy.server_close()
            result_paths = list((directory / "native" / f"repetition-{repetition:03d}").glob("*/result.json"))
            if len(result_paths) != 1:
                raise ValueError("Expected exactly one native trial result")
            result = json.loads(result_paths[0].read_text())
            reward = result["verifier_result"]["rewards"]["reward"]
            summary["trials"].append({
                "kind": "measured", "source": "terminal_bench_native_verifier",
                "repetition": repetition, "reward": reward,
                "native_result": str(result_paths[0].relative_to(directory)),
                "native_result_sha256": sha256(result_paths[0].read_bytes()),
            })
            if recorder.failure or result.get("exception_info"):
                raise ValueError(recorder.failure or f"Native execution error: {result['exception_info']['exception_type']}")
        bounds = ledger["expect"]
        summary["status"] = "passed" if all(
            bounds["reward_min"] <= trial["reward"] <= bounds["reward_max"]
            for trial in summary["trials"]
        ) else "failed"
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, urllib.error.URLError) as exc:
        summary["status"] = "error"
        summary["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if server_created:
            cleanup = subprocess.run(["docker", "rm", "-f", server_name], capture_output=True, text=True)
            if cleanup.returncode:
                summary["cleanup_error"] = cleanup.stderr
                summary["status"] = "error"
        summary["finished_at"] = now()
        summary["elapsed_seconds"] = time.monotonic() - started
        try:
            summary["usage_totals"] = totals(read_attempts(directory))
        except (ValueError, OSError) as exc:
            summary["status"] = "error"
            summary["usage_totals"] = None
            summary["accounting_error"] = str(exc)
        save(directory / "summary.json", summary)
    print(json.dumps({
        "run_id": run_id, "status": summary["status"],
        "rewards": [trial["reward"] for trial in summary["trials"]],
        "usage_totals": summary["usage_totals"],
        "summary": str(directory / "summary.json"),
    }, indent=2))
    return directory


def verify(directory: Path, source_commit: str | None = None) -> dict:
    summary = json.loads((directory / "summary.json").read_text())
    ledger_bytes = (directory / "ledger.toml").read_bytes()
    if sha256(ledger_bytes) != summary["ledger_sha256"]:
        raise ValueError("Ledger hash mismatch")
    if totals(read_attempts(directory)) != summary["usage_totals"]:
        raise ValueError("Summary totals differ in either direction from unique provider attempts")
    if source_commit is not None and summary.get("source_commit") != require_commit_sha(source_commit):
        raise ValueError("Recorded source_commit differs from the designated source_commit")
    committed = committed_inputs(summary.get("source_commit"), summary.get("ledger_source_path"))
    source_files = summary.get("source_files")
    if (
        summary.get("source_snapshot") != "source"
        or not isinstance(source_files, dict) or set(source_files) != set(SOURCE_FILES)
    ):
        raise ValueError("Missing or incomplete source snapshot manifest")
    if sha256(json.dumps(source_files, sort_keys=True).encode()) != summary.get("source_sha256"):
        raise ValueError("Aggregate source hash mismatch")
    for name, digest in source_files.items():
        content = (directory / "source" / name).read_bytes()
        if sha256(content) != digest:
            raise ValueError(f"Source snapshot hash mismatch: {name}")
        if content != committed[name]:
            raise ValueError(f"Source snapshot differs from source_commit: {name}")
    if ledger_bytes != committed[summary["ledger_source_path"]]:
        raise ValueError("Ledger snapshot differs from source_commit")
    for trial in summary["trials"]:
        result_path = directory / trial["native_result"]
        if sha256(result_path.read_bytes()) != trial["native_result_sha256"]:
            raise ValueError("Native result hash mismatch")
        actual = json.loads(result_path.read_text())["verifier_result"]["rewards"]["reward"]
        if actual != trial["reward"]:
            raise ValueError("Summary reward differs from native grading")
    return summary


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "static":
        from src.static_run import main as static_main

        return static_main(sys.argv[2:])
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", nargs="?", type=Path, default=ROOT / "ledger.toml")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument(
        "--source-commit",
        help="Full execution-designated Git SHA; required for run/--check, optional expected SHA for --verify",
    )
    args = parser.parse_args()
    try:
        if args.verify:
            checked = verify(args.verify, args.source_commit)
            print(json.dumps({
                "verified": checked["run_id"], "status": checked["status"],
                "source_commit": checked["source_commit"],
            }))
            return 0
        ledger_path = args.ledger.resolve()
        ledger = load_ledger(ledger_path)
        if args.check:
            provenance = capture_source(ledger_path, ledger, args.source_commit)[0]
            print(json.dumps({"source_commit": provenance["source_commit"], **preflight(ledger)}, indent=2))
            return 0
        directory = run(ledger_path, ledger, source_commit=args.source_commit)
        checked = verify(directory, args.source_commit)
        return {"passed": 0, "failed": 1, "error": 3}[checked["status"]]
    except (ValueError, OSError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as exc:
        print(f"Preflight or verification failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
