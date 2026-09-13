"""A single text interface; tool diagnostics are never provider usage."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import re
import select
import signal
import subprocess
import tempfile
import threading
import time
from typing import Protocol

from .protection import digest


class CompressorError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompressionResult:
    text: str
    tool_reported: dict
    telemetry: dict = field(default_factory=dict)
    audit: dict = field(default_factory=dict)


class Compressor(Protocol):
    metadata: dict

    def compress(self, text: str) -> CompressionResult: ...


def report(headers: list[str], name: str) -> dict:
    metrics = []
    for header in headers:
        number = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
        match = re.search(rf"(?<![\w.,])({number})\s*→\s*({number})(?:\s*tokens)?\s*\(([+-]?\d+(?:\.\d+)?)%\)", header)
        if match:
            for metric_name, value, unit in (
                ("input_display", int(match[1].replace(",", "")), "squeez_input_estimate"),
                ("output_display", int(match[2].replace(",", "")), "squeez_output_estimate"),
                ("change_display", float(match[3]), "percent_tool_defined"),
            ):
                metrics.append({"name": metric_name, "value": value, "unit": unit, "kind": "tool_reported"})
    return {
        "kind": "tool_reported",
        "status": "reported" if headers else "not_applicable" if name == "none" else "not_reported",
        "headers": headers,
        "metrics": metrics,
        "not_provider_usage": True,
    }


def text_measurement(text: str) -> dict:
    encoded = text.encode("utf-8")
    return {
        "sha256": digest(encoded), "characters": len(text),
        "utf8_bytes": len(encoded), "lines": len(text.splitlines()),
    }


def compression_audit(source: str, adapter_input: str, output: str, *,
                      discarded_suffix: str = "", worker_id: int | None = None,
                      overflow_policy: str = "none",
                      discarded_suffix_artifact: str | None = None) -> dict:
    return {
        "kind": "measured_adapter_text_boundaries",
        "line_count_definition": "Python_str.splitlines",
        "overflow_policy": overflow_policy,
        "overflow_applied": bool(discarded_suffix),
        "discarded_suffix_artifact": discarded_suffix_artifact,
        "worker_id": worker_id,
        "source": text_measurement(source),
        "worker_input": text_measurement(adapter_input),
        "output": text_measurement(output),
        "discarded_suffix": text_measurement(discarded_suffix),
    }


class NoOpCompressor:
    def __init__(self, specification: dict, artifacts: Path):
        self.metadata = {"name": "none", "version": "unavailable", "binary_sha256": None, "options": specification["options"]}

    def compress(self, text: str) -> CompressionResult:
        return CompressionResult(
            text=text,
            tool_reported=report([], "none"),
            telemetry={"serialization_wait_seconds": 0.0, "adapter_execution_seconds": 0.0,
                       "worker_inference_seconds": None},
            audit=compression_audit(text, text, text),
        )

    def close(self) -> None:
        return


class SqueezCompressor:
    def __init__(self, specification: dict, artifacts: Path):
        binary_value = os.environ.get(specification["binary_env"])
        if not binary_value:
            raise CompressorError(f"Set {specification['binary_env']} to the pinned squeez executable")
        self.binary = Path(binary_value).resolve(strict=True)
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise CompressorError("The squeez binary is not executable")
        if digest(self.binary.read_bytes()) != specification["sha256"]:
            raise CompressorError("The squeez binary SHA-256 differs from the ledger")
        self.options = specification["options"]
        self.artifacts = artifacts
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.calls = 0
        self.lock = threading.Lock()
        with tempfile.TemporaryDirectory(prefix="version-", dir=artifacts) as temporary:
            stdout, _stderr = self._execute([str(self.binary), "--version"], Path(temporary))
        version = stdout.decode("utf-8").strip()
        if version != f"squeez {specification['version']}":
            raise CompressorError("The squeez reported version differs from the ledger")
        self.metadata = {
            "name": "squeez", "version": specification["version"],
            "binary_sha256": specification["sha256"], "options": self.options,
        }

    def _execute(self, command: list[str], directory: Path) -> tuple[bytes, bytes]:
        home = directory / "home"
        home.mkdir()
        environment = {
            "PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8",
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "NO_COLOR": "1", "DO_NOT_TRACK": "1",
        }
        process = subprocess.Popen(
            command, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=self.options["timeout_seconds"])
        except BaseException as error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
            (directory / "stdout.txt").write_bytes(stdout)
            (directory / "stderr.txt").write_bytes(stderr)
            if isinstance(error, subprocess.TimeoutExpired):
                raise CompressorError("squeez timed out; the process group was stopped") from None
            raise
        (directory / "stdout.txt").write_bytes(stdout)
        (directory / "stderr.txt").write_bytes(stderr)
        if process.returncode:
            raise CompressorError(f"squeez exited with status {process.returncode}; inspect its private stderr.txt")
        return stdout, stderr

    def compress(self, text: str) -> CompressionResult:
        if digest(self.binary.read_bytes()) != self.metadata["binary_sha256"]:
            raise CompressorError("The squeez binary changed during the run")
        with self.lock:
            self.calls += 1
            call = self.calls
        directory = self.artifacts / f"span-{call:05d}"
        directory.mkdir()
        (directory / "input.txt").write_bytes(text.encode("utf-8"))
        started = time.monotonic()
        stdout, _stderr = self._execute([str(self.binary), "wrap", "cat input.txt"], directory)
        elapsed = time.monotonic() - started
        try:
            transformed = stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise CompressorError("squeez did not return valid UTF-8") from None
        headers = [line for line in transformed.splitlines() if line.startswith("# squeez ")]
        return CompressionResult(
            text=transformed,
            tool_reported=report(headers, "squeez"),
            telemetry={"serialization_wait_seconds": 0.0, "adapter_execution_seconds": elapsed,
                       "worker_inference_seconds": None},
            audit=compression_audit(text, text, transformed),
        )

    def close(self) -> None:
        return


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def source_path(value: str) -> Path:
    path = Path(value)
    return path.resolve(strict=True) if path.is_absolute() else (ROOT / path).resolve(strict=True)


def environment_path(name: str, *, resolve: bool = True) -> Path:
    value = os.environ.get(name)
    if not value or not Path(value).is_absolute():
        raise CompressorError(f"Set {name} to an absolute pinned artifact path")
    path = Path(value)
    if not path.exists():
        raise CompressorError(f"Pinned artifact from {name} does not exist")
    return path.resolve(strict=True) if resolve else path.absolute()


def checked_source(value: str, expected_sha256: str) -> Path:
    path = source_path(value)
    if not path.is_file() or digest(path.read_bytes()) != expected_sha256:
        raise CompressorError(f"Pinned source differs: {value}")
    return path


def file_digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


class HeadroomPathsCompressor:
    def __init__(self, specification: dict, artifacts: Path):
        self.module_path = environment_path(specification["module_env"])
        if not self.module_path.is_file() or digest(self.module_path.read_bytes()) != specification["module_sha256"]:
            raise CompressorError("The Headroom lossless helper differs from the ledger")
        module_specification = importlib.util.spec_from_file_location("pinned_headroom_lossless_compaction", self.module_path)
        if module_specification is None or module_specification.loader is None:
            raise CompressorError("The Headroom helper cannot be loaded")
        self.module = importlib.util.module_from_spec(module_specification)
        module_specification.loader.exec_module(self.module)
        self.options = specification["options"]
        self.artifacts = artifacts
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.calls = 0
        self.calls_lock = threading.Lock()
        probe = "/long/shared/first.log\n/long/shared/second.log\n"
        transformed = self.module.compact_lossless(probe, self.options["allowed_kind"])
        if transformed == probe or self.module.path_unheading(transformed) != probe:
            raise CompressorError("The pinned Headroom paths helper failed its exact inverse check")
        self.metadata = {
            "name": "headroom", "version": specification["version"], "binary_sha256": None,
            "module_sha256": specification["module_sha256"], "wheel_sha256": specification["wheel_sha256"],
            "options": self.options, "preflight_roundtrip_byte_exact": True,
        }

    def compress(self, text: str) -> CompressionResult:
        if digest(self.module_path.read_bytes()) != self.metadata["module_sha256"]:
            raise CompressorError("The Headroom helper changed during the run")
        with self.calls_lock:
            self.calls += 1
            call = self.calls
        directory = self.artifacts / f"span-{call:05d}"
        directory.mkdir()
        (directory / "input.txt").write_text(text, encoding="utf-8")
        started = time.monotonic()
        candidate = self.module.compact_lossless(text, self.options["allowed_kind"])
        method = self.options["allowed_kind"] if candidate != text else "identity"
        if len(candidate.encode("utf-8")) >= len(text.encode("utf-8")):
            candidate, method = text, "identity"
        if len(candidate.splitlines()) < len(text.splitlines()):
            raise CompressorError("Headroom paths reduced displayed lines")
        restored = candidate if method == "identity" else self.module.path_unheading(candidate)
        if restored.encode("utf-8") != text.encode("utf-8"):
            raise CompressorError("Headroom paths did not restore the input byte-exactly")
        elapsed = time.monotonic() - started
        (directory / "output.txt").write_text(candidate, encoding="utf-8")
        (directory / "restored.txt").write_text(restored, encoding="utf-8")
        observation = {
            "kind": "adapter_observation", "status": "recorded", "not_provider_usage": True,
            "method": method, "inverse": None if method == "identity" else self.options["inverse"],
            "roundtrip_byte_exact": True,
        }
        write_json(directory / "observation.json", observation)
        return CompressionResult(
            text=candidate,
            tool_reported=observation,
            telemetry={"serialization_wait_seconds": 0.0, "adapter_execution_seconds": elapsed,
                       "worker_inference_seconds": None},
            audit=compression_audit(text, text, candidate),
        )

    def close(self) -> None:
        return


class LLMLingua2Compressor:
    def __init__(self, specification: dict, artifacts: Path):
        self.specification = specification
        self.python = environment_path(specification["python_env"], resolve=False)
        if not self.python.is_file() or not os.access(self.python, os.X_OK):
            raise CompressorError("The LLMLingua Python is not executable")
        self.model = environment_path(specification["model_env"])
        if not self.model.is_dir():
            raise CompressorError("The LLMLingua model path is not a directory")
        self.worker_path = checked_source(specification["worker_path"], specification["worker_sha256"])
        self.requirements_path = checked_source(
            specification["requirements_path"], specification["requirements_sha256"]
        )
        self.tokenizer_cache = environment_path(specification["tokenizer_cache_env"])
        if not self.tokenizer_cache.is_dir():
            raise CompressorError("The LLMLingua tokenizer cache is not a directory")
        self.fixtures = []
        for fixture in specification["fixtures"]:
            path = source_path(fixture["path"])
            if not path.is_file() or digest(path.read_bytes()) != fixture["input_sha256"]:
                raise CompressorError(f"LLMLingua fixture differs: {fixture['name']}")
            self.fixtures.append((fixture, path))
        self.options = specification["options"]
        self.artifacts = artifacts
        self.artifacts.mkdir(parents=True, exist_ok=False)
        (self.artifacts / "preflight").mkdir()
        self.calls = 0
        self.calls_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.closed = False
        self.worker_count = self.options["worker_processes_per_run"]
        self.worker_pool: Queue = Queue(maxsize=self.worker_count)
        self.workers = []
        self.worker_specification = {
            "python_version": specification["python_version"],
            "requirements_path": str(self.requirements_path),
            "requirements_sha256": specification["requirements_sha256"],
            "model_id": specification["model_id"], "model_revision": specification["model_revision"],
            "model_files": specification["model_files"],
            "tokenizer_cache_path": str(self.tokenizer_cache),
            "tokenizer_cache_files": specification["tokenizer_cache_files"],
            "profile": {key: self.options[key] for key in (
                "method", "rate", "target_token", "force_tokens", "force_reserve_digit", "drop_consecutive",
                "chunk_end_tokens", "device", "torch_dtype", "seed", "torch_threads",
                "torch_interop_threads", "deterministic_algorithms",
            )},
        }
        try:
            self.workers = [self._spawn_worker(identifier) for identifier in range(1, self.worker_count + 1)]
            with ThreadPoolExecutor(max_workers=self.worker_count, thread_name_prefix="llmlingua-init") as executor:
                initialized = list(executor.map(self._initialize_worker, self.workers))
            self._validate_probe_agreement(initialized)
            for worker in self.workers:
                self.worker_pool.put_nowait(worker)
            first = initialized[0]["initialized"]
            probes = [probe for record in initialized for probe in record["probes"]]
            self.metadata = {
                "name": "llmlingua2", "version": specification["version"], "binary_sha256": None,
                "worker_sha256": specification["worker_sha256"],
                "requirements_sha256": specification["requirements_sha256"],
                "model_id": specification["model_id"], "model_revision": specification["model_revision"],
                "model_files": first["model_files"], "tokenizer_cache_files": first["tokenizer_cache_files"],
                "options": self.options,
                "worker_pool": {
                    "size": self.worker_count, "parallel_inference": self.options["parallel_inference"],
                    "runtime_by_worker": [
                        {"worker_id": record["worker_id"], "runtime": record["initialized"]["runtime"],
                         "model_load_seconds": record["initialized"]["load_seconds"]}
                        for record in initialized
                    ],
                },
                "determinism_probes": probes,
            }
        except BaseException:
            self._dispose_workers()
            raise

    def _spawn_worker(self, identifier: int) -> dict:
        directory = self.artifacts / f"worker-{identifier:02d}"
        directory.mkdir()
        home = directory / "home"
        home.mkdir()
        stderr_handle = (directory / "stderr.txt").open("xb")
        environment = {
            "PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "TMPDIR": str(home), "HF_HOME": str(home / "huggingface"), "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false", "CUDA_VISIBLE_DEVICES": "",
            "TIKTOKEN_CACHE_DIR": str(self.tokenizer_cache),
            "OMP_NUM_THREADS": str(self.options["torch_threads"]),
            "MKL_NUM_THREADS": str(self.options["torch_threads"]),
        }
        try:
            process = subprocess.Popen(
                [str(self.python), "-I", "-u", str(self.worker_path)], cwd=directory, env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_handle,
                text=True, encoding="utf-8", start_new_session=True,
            )
        except BaseException:
            stderr_handle.close()
            raise
        return {"id": identifier, "directory": directory, "process": process, "stderr": stderr_handle}

    def _send(self, worker: dict, payload: dict) -> None:
        process = worker["process"]
        if process.poll() is not None or process.stdin is None:
            raise CompressorError(f"LLMLingua worker {worker['id']} exited; inspect its stderr.txt")
        process.stdin.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
        process.stdin.flush()

    def _receive(self, worker: dict, timeout: float) -> dict:
        process = worker["process"]
        if process.stdout is None:
            raise CompressorError(f"LLMLingua worker {worker['id']} stdout is unavailable")
        readable, _, _ = select.select([process.stdout], [], [], timeout)
        if not readable:
            raise CompressorError(f"LLMLingua worker {worker['id']} timed out")
        line = process.stdout.readline()
        if not line:
            raise CompressorError(f"LLMLingua worker {worker['id']} exited; inspect its stderr.txt")
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            raise CompressorError(f"LLMLingua worker {worker['id']} returned invalid JSON") from None
        if not isinstance(response, dict):
            raise CompressorError(f"LLMLingua worker {worker['id']} returned a non-object")
        if response.get("ok") is False:
            raise CompressorError(f"LLMLingua worker {worker['id']} failed; inspect its stderr.txt")
        return response

    def _validate_initialized(self, response: dict, expected: dict) -> None:
        required = {"operation", "ok", "runtime", "model_files", "tokenizer_cache_files", "model_id", "model_revision", "profile", "load_seconds"}
        if set(response) != required or response["profile"] != expected["profile"]:
            raise CompressorError("LLMLingua worker metadata differs from the ledger")
        if (response["model_id"], response["model_revision"]) != (expected["model_id"], expected["model_revision"]):
            raise CompressorError("LLMLingua model identity differs from the ledger")
        expected_files = [{"name": name, "bytes": record["bytes"], "sha256": record["sha256"]}
                          for name, record in self.specification["model_files"].items()]
        if response["model_files"] != expected_files:
            raise CompressorError("LLMLingua model files differ from the ledger")
        expected_cache = [{"name": name, "bytes": record["bytes"], "sha256": record["sha256"]}
                          for name, record in self.specification["tokenizer_cache_files"].items()]
        if response["tokenizer_cache_files"] != expected_cache:
            raise CompressorError("LLMLingua tokenizer cache differs from the ledger")
        runtime = response["runtime"]
        if (runtime.get("python") != self.specification["python_version"]
                or runtime.get("token_boundary_model_name") != self.specification["model_id"]):
            raise CompressorError("LLMLingua runtime differs from the ledger")
        for key in ("load_seconds",):
            if type(response[key]) not in (int, float) or not math.isfinite(response[key]) or response[key] < 0:
                raise CompressorError("LLMLingua worker returned invalid timing")

    def _exchange(self, worker: dict, identifier, text: str, timeout: float) -> dict:
        self._send(worker, {"operation": "compress", "id": identifier, "text": text})
        response = self._receive(worker, timeout)
        required = {"operation", "ok", "id", "text", "inference_seconds", "tool_reported"}
        if set(response) != required or response["operation"] != "compressed" or response["id"] != identifier:
            raise CompressorError("LLMLingua worker response lineage differs")
        if not isinstance(response["text"], str):
            raise CompressorError("LLMLingua worker output is not text")
        elapsed = response["inference_seconds"]
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            raise CompressorError("LLMLingua worker returned invalid inference time")
        return response

    def _initialize_worker(self, worker: dict) -> dict:
        self._send(worker, {"operation": "initialize", "model_path": str(self.model),
                            "specification": self.worker_specification})
        initialized = self._receive(worker, self.options["initialize_timeout_seconds"])
        if initialized.get("operation") != "initialized" or initialized.get("ok") is not True:
            raise CompressorError(f"LLMLingua worker {worker['id']} initialization failed")
        self._validate_initialized(initialized, self.worker_specification)
        return {"worker_id": worker["id"], "initialized": initialized,
                "probes": self._probe_fixtures(worker)}

    def _probe_fixtures(self, worker: dict) -> list[dict]:
        directory = self.artifacts / "preflight" / f"worker-{worker['id']:02d}"
        directory.mkdir()
        probes = []
        for fixture, path in self.fixtures:
            text = path.read_text(encoding="utf-8")
            started = time.monotonic()
            response = self._exchange(worker, f"fixture-{worker['id']:02d}-{fixture['name']}", text,
                                      self.options["inference_timeout_seconds"])
            wall = time.monotonic() - started
            output_sha256 = digest(response["text"].encode("utf-8"))
            target = directory / fixture["name"]
            target.mkdir()
            (target / "input.txt").write_text(text, encoding="utf-8")
            (target / "output.txt").write_text(response["text"], encoding="utf-8")
            record = {"worker_id": worker["id"], "name": fixture["name"],
                      "input_sha256": fixture["input_sha256"],
                      "output_sha256": output_sha256, "wall_seconds": wall,
                      "worker_inference_seconds": response["inference_seconds"]}
            write_json(target / "observation.json", record)
            probes.append(record)
        return probes

    def _validate_probe_agreement(self, initialized: list[dict]) -> None:
        for fixture, _path in self.fixtures:
            outputs = {
                probe["output_sha256"]
                for record in initialized for probe in record["probes"]
                if probe["name"] == fixture["name"]
            }
            if len(outputs) != 1:
                raise CompressorError(f"LLMLingua cross-worker fixture output differs: {fixture['name']}")
            if outputs != {fixture["output_sha256"]}:
                raise CompressorError(f"LLMLingua determinism fixture changed: {fixture['name']}")

    def compress(self, text: str) -> CompressionResult:
        with self.state_lock:
            if self.closed:
                raise CompressorError("LLMLingua worker pool is closed")
        with self.calls_lock:
            self.calls += 1
            call = self.calls
        directory = self.artifacts / f"span-{call:05d}"
        directory.mkdir()
        (directory / "input.txt").write_text(text, encoding="utf-8")
        maximum = self.options["max_input_characters"]
        worker_input, discarded_suffix = text[:maximum], text[maximum:]
        (directory / "worker-input.txt").write_text(worker_input, encoding="utf-8")
        discarded_suffix_artifact = None
        if discarded_suffix:
            discarded_suffix_artifact = f"span-{call:05d}/discarded-suffix.txt"
            (directory / "discarded-suffix.txt").write_text(discarded_suffix, encoding="utf-8")
        wait_started = time.monotonic()
        try:
            worker = self.worker_pool.get(timeout=self.options["pool_wait_timeout_seconds"])
        except Empty:
            raise CompressorError("LLMLingua worker-pool wait exceeded its fixed limit") from None
        wait_seconds = time.monotonic() - wait_started
        try:
            execution_started = time.monotonic()
            response = self._exchange(worker, call, worker_input, self.options["inference_timeout_seconds"])
            execution_seconds = time.monotonic() - execution_started
        finally:
            self.worker_pool.put(worker)
        transformed = response["text"]
        (directory / "output.txt").write_text(transformed, encoding="utf-8")
        audit = compression_audit(
            text, worker_input, transformed, discarded_suffix=discarded_suffix,
            worker_id=worker["id"], overflow_policy=self.options["overflow_policy"],
            discarded_suffix_artifact=discarded_suffix_artifact,
        )
        observation = {
            "serialization_wait_seconds": wait_seconds, "adapter_execution_seconds": execution_seconds,
            "worker_inference_seconds": response["inference_seconds"], **audit,
        }
        write_json(directory / "observation.json", observation)
        return CompressionResult(
            text=transformed,
            tool_reported=response["tool_reported"],
            telemetry={key: observation[key] for key in (
                "serialization_wait_seconds", "adapter_execution_seconds", "worker_inference_seconds"
            )},
            audit=audit,
        )

    def _terminate(self, worker: dict) -> None:
        process = worker["process"]
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)

    def _close_pipes(self, worker: dict) -> None:
        process = worker["process"]
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.stdout is not None and not process.stdout.closed:
            process.stdout.close()

    def _dispose_workers(self) -> None:
        for worker in self.workers:
            self._terminate(worker)
            self._close_pipes(worker)
            if not worker["stderr"].closed:
                worker["stderr"].close()

    def _close_worker(self, worker: dict) -> None:
        process = worker["process"]
        try:
            if process.poll() is not None:
                raise CompressorError(f"LLMLingua worker {worker['id']} exited before the close handshake")
            self._send(worker, {"operation": "close"})
            response = self._receive(worker, 10)
            if response != {"operation": "closed", "ok": True}:
                raise CompressorError(f"LLMLingua worker {worker['id']} did not close cleanly")
            process.wait(timeout=10)
            if process.returncode != 0:
                raise CompressorError(f"LLMLingua worker {worker['id']} exited unsuccessfully")
        except (CompressorError, subprocess.TimeoutExpired) as error:
            self._terminate(worker)
            raise CompressorError(
                f"LLMLingua worker {worker['id']} did not close cleanly; inspect its stderr.txt"
            ) from error
        finally:
            self._close_pipes(worker)
            if not worker["stderr"].closed:
                worker["stderr"].close()

    def close(self) -> None:
        with self.state_lock:
            if self.closed:
                return
            self.closed = True
        available = []
        deadline = time.monotonic() + self.options["pool_wait_timeout_seconds"]
        try:
            for _ in range(self.worker_count):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CompressorError("LLMLingua workers did not return to the pool before close")
                try:
                    available.append(self.worker_pool.get(timeout=remaining))
                except Empty:
                    raise CompressorError("LLMLingua workers did not return to the pool before close") from None
            errors = []
            with ThreadPoolExecutor(max_workers=self.worker_count, thread_name_prefix="llmlingua-close") as executor:
                futures = [executor.submit(self._close_worker, worker) for worker in available]
                for future in futures:
                    try:
                        future.result()
                    except CompressorError as error:
                        errors.append(error)
            if errors:
                raise CompressorError(
                    f"{len(errors)} LLMLingua worker(s) did not close cleanly"
                ) from errors[0]
        except BaseException:
            self._dispose_workers()
            raise


def check_compressor_artifacts(configuration: dict, name: str) -> None:
    specification = configuration["tools"][name]
    if name == "none":
        return
    if name == "squeez":
        binary = environment_path(specification["binary_env"])
        if not binary.is_file() or digest(binary.read_bytes()) != specification["sha256"]:
            raise CompressorError("The squeez binary differs from the ledger")
        return
    if name == "headroom":
        module = environment_path(specification["module_env"])
        if not module.is_file() or digest(module.read_bytes()) != specification["module_sha256"]:
            raise CompressorError("The Headroom helper differs from the ledger")
        return
    if name == "llmlingua2":
        python = environment_path(specification["python_env"], resolve=False)
        model = environment_path(specification["model_env"])
        cache = environment_path(specification["tokenizer_cache_env"])
        if not python.is_file() or not os.access(python, os.X_OK) or not model.is_dir() or not cache.is_dir():
            raise CompressorError("LLMLingua runtime paths are invalid")
        checked_source(specification["worker_path"], specification["worker_sha256"])
        checked_source(specification["requirements_path"], specification["requirements_sha256"])
        for fixture in specification["fixtures"]:
            checked_source(fixture["path"], fixture["input_sha256"])
        for filename, record in specification["model_files"].items():
            path = model / filename
            if not path.is_file():
                raise CompressorError(f"LLMLingua model file is missing: {filename}")
            if path.stat().st_size != record["bytes"] or file_digest(path) != record["sha256"]:
                raise CompressorError(f"LLMLingua model file differs: {filename}")
        for filename, record in specification["tokenizer_cache_files"].items():
            path = cache / filename
            if not path.is_file():
                raise CompressorError(f"LLMLingua tokenizer cache file is missing: {filename}")
            if path.stat().st_size != record["bytes"] or file_digest(path) != record["sha256"]:
                raise CompressorError(f"LLMLingua tokenizer cache file differs: {filename}")
        return
    raise ValueError(f"Unsupported compressor: {name}")


def make_compressor(configuration: dict, artifacts: Path) -> Compressor:
    factories = {
        "none": NoOpCompressor,
        "squeez": SqueezCompressor,
        "headroom": HeadroomPathsCompressor,
        "llmlingua2": LLMLingua2Compressor,
    }
    name = configuration["name"]
    if name not in factories:
        raise ValueError(f"Unsupported compressor: {name}; implemented: {', '.join(factories)}")
    return factories[name](configuration["tools"][name], artifacts)
