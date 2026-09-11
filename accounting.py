"""Local Ollama transport. Every upstream attempt is recorded exactly once."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def provider_tokens(response: dict[str, Any]) -> dict[str, Any] | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    values = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
    if any(type(value) is not int or value < 0 for value in values):
        return None
    details = usage.get("prompt_tokens_details")
    if details is not None and not isinstance(details, dict):
        return None
    cached = (details or {}).get("cached_tokens")
    if cached is not None and (type(cached) is not int or not 0 <= cached <= values[0]):
        return None
    return {
        "input_tokens": values[0],
        "output_tokens": values[1],
        "cached_input_tokens": cached,
        "cache_status": "reported" if cached is not None else "not_reported",
    }


class AttemptRecorder:
    def __init__(
        self, directory: Path, ledger: dict, run_id: str, repetition: int,
        ledger_hash: str, source_hash: str, upstream: str, key: str,
    ):
        self.directory = directory
        self.ledger = ledger
        self.upstream = upstream
        self.key = key
        self.calls = 0
        self.failure: str | None = None
        self.lock = threading.Lock()
        self.base = {
            "schema_version": 1,
            "run_id": run_id,
            "repetition": repetition,
            "ledger_sha256": ledger_hash,
            "source_sha256": source_hash,
            "model": ledger["model"]["name"],
            "benchmark": ledger["benchmark"]["name"],
            "task": ledger["benchmark"]["task"],
            "tokenizer": "unverified",
            "intervention": "none",
        }
        self.directory.mkdir(parents=True, exist_ok=False)
        self.events = self.directory / "attempts.jsonl"
        self.events.touch()

    def append(self, value: dict) -> None:
        with self.events.open("a", encoding="utf-8") as file:
            file.write(json.dumps({**self.base, **value}, ensure_ascii=False) + "\n")
            file.flush()

    def forward(self, payload: dict) -> tuple[int, bytes]:
        if self.failure:
            self.append({
                "record_type": "request_denied", "kind": "measured", "source": "runner",
                "at": now(), "reason": self.failure,
            })
            raise ValueError(self.failure)
        self.calls += 1
        if self.calls > self.ledger["limits"]["max_calls_per_repetition"]:
            self.failure = "max_calls_per_repetition reached"
            raise ValueError(self.failure)
        if (
            payload.get("model") != self.ledger["model"]["name"]
            or payload.get("stream")
            or payload.get("max_tokens") != self.ledger["model"]["max_output_tokens"]
            or payload.get("temperature") != self.ledger["model"]["temperature"]
            or payload.get("reasoning_effort") != self.ledger["model"]["reasoning_effort"]
        ):
            self.failure = "Runner request differs from the model ledger"
            self.append({
                "record_type": "request_denied", "kind": "measured", "source": "runner",
                "at": now(), "reason": self.failure,
            })
            raise ValueError(self.failure)
        call_id = f"r{self.base['repetition']:03d}-call-{self.calls:04d}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        policy = self.ledger["retry"]
        for attempt in range(1, policy["max_attempts_per_call"] + 1):
            attempt_id = f"{call_id}-attempt-{attempt:02d}"
            request_path = self.directory / f"{attempt_id}.request.json"
            response_path = self.directory / f"{attempt_id}.response.json"
            request_path.write_bytes(body)
            started_at = now()
            started = time.monotonic()
            request = urllib.request.Request(
                self.upstream + "/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json"},
            )
            raw, status, error, retry_after = b"", None, None, None
            try:
                with urllib.request.urlopen(
                    request, timeout=self.ledger["limits"]["request_timeout_seconds"]
                ) as response:
                    status, raw = response.status, response.read()
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read()
                retry_after = exc.headers.get("Retry-After")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                error = type(exc).__name__
            response_path.write_bytes(raw)
            try:
                decoded = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                decoded = {}
                error = "invalid_json_response"
            tokens = provider_tokens(decoded) if isinstance(decoded, dict) else None
            included = status == 200 and tokens is not None
            record = {
                "record_type": "provider_attempt", "kind": "measured",
                "source": "ollama_response",
                "call_id": call_id, "attempt_id": attempt_id,
                "attempt_number": attempt, "is_retry": attempt > 1,
                "started_at": started_at, "finished_at": now(),
                "http_status": status, "error": error,
                "elapsed_seconds": time.monotonic() - started,
                "elapsed_source": "runner_monotonic_clock",
                "request_file": request_path.name, "response_file": response_path.name,
                "request_sha256": sha256(body), "response_sha256": sha256(raw),
                "provider_usage": decoded.get("usage") if isinstance(decoded, dict) else None,
                "provider_response_id": decoded.get("id") if isinstance(decoded, dict) else None,
                "usage_status": "reported" if tokens is not None else "not_reported",
                "tokens": tokens, "included_in_totals": included,
                "token_accounting": "local_runtime_not_billable",
                "provider_reported_cost_usd": None,
            }
            self.append(record)
            if included:
                return status, raw
            if status == 200:
                self.failure = "Successful HTTP response has missing or invalid usage"
                raise ValueError(self.failure)
            retryable = status in policy["http_statuses"] and attempt < policy["max_attempts_per_call"]
            if retryable:
                delay = policy["delay_seconds"]
                if retry_after is not None:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        self.failure = "Non-numeric Retry-After; not retrying ambiguously"
                        raise ValueError(self.failure) from None
                if delay > policy["max_delay_seconds"]:
                    self.failure = "Retry-After exceeds the ledger wait limit"
                    raise ValueError(self.failure)
                time.sleep(delay)
                continue
            # Latch exhaustion so a retry by Harbor never starts another upstream retry budget.
            self.failure = f"Upstream failed: HTTP {status}, error={error}"
            raise ValueError(self.failure)
        raise RuntimeError("Unreachable retry state")


def start_proxy(recorder: AttemptRecorder) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status: int, body: bytes):
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                recorder.failure = "Runner disconnected before receiving the response"
                recorder.append({
                    "record_type": "downstream_disconnect", "kind": "measured",
                    "source": "runner_transport", "at": now(),
                    "call_id": f"r{recorder.base['repetition']:03d}-call-{recorder.calls:04d}",
                    "reason": recorder.failure,
                })

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.reply(404, b'{"error":{"message":"Unknown route"}}')
                return
            if self.headers.get("Authorization") != f"Bearer {recorder.key}":
                self.reply(401, b'{"error":{"message":"Unauthorized"}}')
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                self.reply(413, b'{"error":{"message":"Request too large"}}')
                return
            with recorder.lock:
                try:
                    payload = json.loads(self.rfile.read(length))
                    status, body = recorder.forward(payload)
                except (ValueError, KeyError, TypeError) as exc:
                    status, body = 502, json.dumps({"error": {"message": str(exc)}}).encode()
                self.reply(status, body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # Wait for bounded upstream calls before calculating totals, including late responses.
    server.daemon_threads = False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def totals(records: list[dict]) -> dict:
    attempts = [record for record in records if record["record_type"] == "provider_attempt"]
    ids = [record["attempt_id"] for record in attempts]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate attempt_id; refusing to double-count usage")
    accepted = []
    for record in attempts:
        tokens = provider_tokens({"usage": record["provider_usage"]})
        should_include = record["http_status"] == 200 and tokens is not None
        if record["included_in_totals"] != should_include or record["tokens"] != tokens:
            raise ValueError("Attempt usage attribution does not match the provider payload")
        if should_include:
            accepted.append(record)
    return {
        "kind": "calculated", "source": "unique_successful_provider_attempts",
        "http_attempts": len(attempts),
        "http_429": sum(record["http_status"] == 429 for record in attempts),
        "retries": sum(record["is_retry"] for record in attempts),
        "responses_with_usage": len(accepted),
        "input_tokens": sum(record["tokens"]["input_tokens"] for record in accepted),
        "output_tokens": sum(record["tokens"]["output_tokens"] for record in accepted),
        "included_attempt_ids": [record["attempt_id"] for record in accepted],
        "token_accounting": "local_runtime_not_billable",
        "api_cost_usd": {
            "value": 0.0, "kind": "calculated", "source": "local_only_execution",
            "scope": "API spending only; hardware, electricity and VM costs excluded",
        },
    }


def read_attempts(directory: Path, *, check_raw: bool = True) -> list[dict]:
    records = []
    for path in sorted(directory.glob("repetition-*/attempts.jsonl")):
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if check_raw and record["record_type"] == "provider_attempt":
                for field in ("request", "response"):
                    data = (path.parent / record[f"{field}_file"]).read_bytes()
                    if sha256(data) != record[f"{field}_sha256"]:
                        raise ValueError(f"{field} artifact hash differs from the recorded hash")
                try:
                    response = json.loads((path.parent / record["response_file"]).read_bytes() or b"{}")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    response = None
                raw_usage = response.get("usage") if isinstance(response, dict) else None
                if raw_usage != record["provider_usage"]:
                    raise ValueError("Recorded provider usage differs from the raw response")
            records.append(record)
    return records
