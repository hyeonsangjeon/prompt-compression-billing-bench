"""A single text interface; tool diagnostics are never provider usage."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
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


class NoOpCompressor:
    def __init__(self, specification: dict, artifacts: Path):
        self.metadata = {"name": "none", "version": "unavailable", "binary_sha256": None, "options": specification["options"]}

    def compress(self, text: str) -> CompressionResult:
        return CompressionResult(
            text=text,
            tool_reported=report([], "none"),
            telemetry={"serialization_wait_seconds": 0.0, "adapter_execution_seconds": 0.0,
                       "worker_inference_seconds": None},
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
        home = self.artifacts / "home"
        home.mkdir()
        self.calls = 0
        self.calls_lock = threading.Lock()
        self.inference_lock = threading.Lock()
        self.stderr_handle = (self.artifacts / "worker-stderr.txt").open("xb")
        environment = {
            "PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "TMPDIR": str(home), "HF_HOME": str(home / "huggingface"), "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false", "CUDA_VISIBLE_DEVICES": "",
            "TIKTOKEN_CACHE_DIR": str(self.tokenizer_cache),
            "OMP_NUM_THREADS": str(self.options["torch_threads"]),
            "MKL_NUM_THREADS": str(self.options["torch_threads"]),
        }
        self.process = subprocess.Popen(
            [str(self.python), "-I", "-u", str(self.worker_path)], cwd=self.artifacts, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr_handle,
            text=True, encoding="utf-8", start_new_session=True,
        )
        try:
            worker_specification = {
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
            self._send({"operation": "initialize", "model_path": str(self.model),
                        "specification": worker_specification})
            initialized = self._receive(self.options["initialize_timeout_seconds"])
            if initialized.get("operation") != "initialized" or initialized.get("ok") is not True:
                raise CompressorError("LLMLingua worker initialization failed; inspect worker-stderr.txt")
            self._validate_initialized(initialized, worker_specification)
            probes = self._probe_fixtures()
            self.metadata = {
                "name": "llmlingua2", "version": specification["version"], "binary_sha256": None,
                "worker_sha256": specification["worker_sha256"],
                "requirements_sha256": specification["requirements_sha256"],
                "model_id": specification["model_id"], "model_revision": specification["model_revision"],
                "model_files": initialized["model_files"], "runtime": initialized["runtime"],
                "tokenizer_cache_files": initialized["tokenizer_cache_files"],
                "options": self.options, "model_load_seconds": initialized["load_seconds"],
                "determinism_probes": probes,
            }
        except BaseException:
            self._terminate()
            self._close_pipes()
            self.stderr_handle.close()
            raise

    def _send(self, payload: dict) -> None:
        if self.process.poll() is not None or self.process.stdin is None:
            raise CompressorError("LLMLingua worker exited; inspect worker-stderr.txt")
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
        self.process.stdin.flush()

    def _receive(self, timeout: float) -> dict:
        if self.process.stdout is None:
            raise CompressorError("LLMLingua worker stdout is unavailable")
        readable, _, _ = select.select([self.process.stdout], [], [], timeout)
        if not readable:
            raise CompressorError("LLMLingua worker timed out")
        line = self.process.stdout.readline()
        if not line:
            raise CompressorError("LLMLingua worker exited; inspect worker-stderr.txt")
        response = json.loads(line)
        if not isinstance(response, dict):
            raise CompressorError("LLMLingua worker returned a non-object")
        if response.get("ok") is False:
            raise CompressorError("LLMLingua worker failed; inspect worker-stderr.txt")
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
        if runtime.get("python") != self.specification["python_version"]:
            raise CompressorError("LLMLingua runtime differs from the ledger")
        for key in ("load_seconds",):
            if type(response[key]) not in (int, float) or not math.isfinite(response[key]) or response[key] < 0:
                raise CompressorError("LLMLingua worker returned invalid timing")

    def _exchange(self, identifier, text: str, timeout: float) -> dict:
        self._send({"operation": "compress", "id": identifier, "text": text})
        response = self._receive(timeout)
        required = {"operation", "ok", "id", "text", "inference_seconds", "tool_reported"}
        if set(response) != required or response["operation"] != "compressed" or response["id"] != identifier:
            raise CompressorError("LLMLingua worker response lineage differs")
        if not isinstance(response["text"], str):
            raise CompressorError("LLMLingua worker output is not text")
        elapsed = response["inference_seconds"]
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            raise CompressorError("LLMLingua worker returned invalid inference time")
        return response

    def _probe_fixtures(self) -> list[dict]:
        directory = self.artifacts / "preflight"
        directory.mkdir()
        probes = []
        for fixture, path in self.fixtures:
            text = path.read_text(encoding="utf-8")
            started = time.monotonic()
            response = self._exchange("fixture-" + fixture["name"], text,
                                      self.options["inference_timeout_seconds"])
            wall = time.monotonic() - started
            output_sha256 = digest(response["text"].encode("utf-8"))
            if output_sha256 != fixture["output_sha256"]:
                raise CompressorError(f"LLMLingua determinism fixture changed: {fixture['name']}")
            target = directory / fixture["name"]
            target.mkdir()
            (target / "input.txt").write_text(text, encoding="utf-8")
            (target / "output.txt").write_text(response["text"], encoding="utf-8")
            record = {"name": fixture["name"], "input_sha256": fixture["input_sha256"],
                      "output_sha256": output_sha256, "wall_seconds": wall,
                      "worker_inference_seconds": response["inference_seconds"]}
            write_json(target / "observation.json", record)
            probes.append(record)
        return probes

    def compress(self, text: str) -> CompressionResult:
        with self.calls_lock:
            self.calls += 1
            call = self.calls
        directory = self.artifacts / f"span-{call:05d}"
        directory.mkdir()
        (directory / "input.txt").write_text(text, encoding="utf-8")
        wait_started = time.monotonic()
        if not self.inference_lock.acquire(timeout=self.options["lock_timeout_seconds"]):
            raise CompressorError("LLMLingua serialization wait exceeded its fixed limit")
        wait_seconds = time.monotonic() - wait_started
        try:
            execution_started = time.monotonic()
            response = self._exchange(call, text, self.options["inference_timeout_seconds"])
            execution_seconds = time.monotonic() - execution_started
        finally:
            self.inference_lock.release()
        transformed = response["text"]
        (directory / "output.txt").write_text(transformed, encoding="utf-8")
        observation = {
            "input_sha256": digest(text.encode("utf-8")),
            "output_sha256": digest(transformed.encode("utf-8")),
            "serialization_wait_seconds": wait_seconds, "adapter_execution_seconds": execution_seconds,
            "worker_inference_seconds": response["inference_seconds"],
        }
        write_json(directory / "observation.json", observation)
        return CompressionResult(
            text=transformed,
            tool_reported=response["tool_reported"],
            telemetry={key: observation[key] for key in (
                "serialization_wait_seconds", "adapter_execution_seconds", "worker_inference_seconds"
            )},
        )

    def _terminate(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=5)

    def _close_pipes(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        if self.process.stdout is not None and not self.process.stdout.closed:
            self.process.stdout.close()

    def close(self) -> None:
        close_error = None
        if self.process.poll() is None:
            try:
                with self.inference_lock:
                    self._send({"operation": "close"})
                    response = self._receive(10)
                    if response != {"operation": "closed", "ok": True}:
                        raise CompressorError("LLMLingua worker did not close cleanly")
                self.process.wait(timeout=10)
                if self.process.returncode != 0:
                    raise CompressorError("LLMLingua worker exited unsuccessfully after the close handshake")
            except (CompressorError, subprocess.TimeoutExpired) as error:
                close_error = CompressorError("LLMLingua worker did not close cleanly; inspect worker-stderr.txt")
                close_error.__cause__ = error
                self._terminate()
        else:
            close_error = CompressorError("LLMLingua worker exited before the close handshake; inspect worker-stderr.txt")
        self._close_pipes()
        if not self.stderr_handle.closed:
            self.stderr_handle.close()
        if close_error is not None:
            raise close_error


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
