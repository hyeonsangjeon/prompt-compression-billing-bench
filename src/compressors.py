"""A single text interface; tool diagnostics are never provider usage."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
from typing import Protocol

from .protection import digest


class CompressorError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompressionResult:
    text: str
    tool_reported: dict


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
        return CompressionResult(text=text, tool_reported=report([], "none"))


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
        stdout, _stderr = self._execute([str(self.binary), "wrap", "cat input.txt"], directory)
        try:
            transformed = stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise CompressorError("squeez did not return valid UTF-8") from None
        headers = [line for line in transformed.splitlines() if line.startswith("# squeez ")]
        return CompressionResult(text=transformed, tool_reported=report(headers, "squeez"))


def make_compressor(configuration: dict, artifacts: Path) -> Compressor:
    factories = {"none": NoOpCompressor, "squeez": SqueezCompressor}
    name = configuration["name"]
    if name not in factories:
        raise ValueError(f"Unsupported compressor: {name}; implemented: none, squeez")
    return factories[name](configuration["tools"][name], artifacts)
