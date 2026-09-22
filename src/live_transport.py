"""One fail-closed loopback transport for every trial in a native run."""

from collections import deque
import fcntl
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from accounting import now, provider_tokens
from .execution_safety import (
    SafetyLimitReached,
    effective_deadline_epoch,
    progress_signal,
    safety_failure,
    safety_policy_record,
)
from .live_observations import POLICY, partition
from .measurement import counts, token_count
from .protection import FrozenRequestGuard, ProtectionViolation, canonical, digest, parse_request


CACHE_NAMESPACE_PREFIX = "cache-reuse-namespace-v1:"


def cache_namespace_message(isolation_evidence_sha256: str) -> dict[str, str]:
    if not isinstance(isolation_evidence_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", isolation_evidence_sha256
    ):
        raise ValueError("Cache namespace evidence requires SHA-256")
    return {
        "role": "system",
        "content": CACHE_NAMESPACE_PREFIX + isolation_evidence_sha256,
    }


def write_json(path: Path, payload) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def compressor_timing(result, wall_seconds: float) -> dict:
    telemetry = result.telemetry or {}
    expected = {"serialization_wait_seconds", "adapter_execution_seconds", "worker_inference_seconds"}
    if set(telemetry) != expected:
        raise ProtectionViolation("Compressor timing fields differ from the live contract")
    values = {"compressor_wall_seconds": wall_seconds, **telemetry}
    for name, value in values.items():
        if value is None and name == "worker_inference_seconds":
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ProtectionViolation("Compressor returned invalid timing", {"field": name})
    if telemetry["serialization_wait_seconds"] + telemetry["adapter_execution_seconds"] > wall_seconds + 0.01:
        raise ProtectionViolation("Compressor sub-timings exceed observed wall time")
    if telemetry["worker_inference_seconds"] is not None and telemetry["worker_inference_seconds"] > telemetry["adapter_execution_seconds"] + 0.01:
        raise ProtectionViolation("Worker inference exceeds adapter execution time")
    return values


def compression_audit(result, source: str, condition: str) -> dict:
    audit = result.audit or {}
    required = {
        "kind", "line_count_definition", "overflow_policy", "overflow_applied",
        "discarded_suffix_artifact", "worker_id", "source", "worker_input", "output",
        "discarded_suffix",
    }
    if set(audit) != required or audit["kind"] != "measured_adapter_text_boundaries":
        raise ProtectionViolation("Compressor text-boundary audit differs from the live contract")
    if audit["line_count_definition"] != "Python_str.splitlines":
        raise ProtectionViolation("Compressor line-count definition differs from the live contract")
    for name in ("source", "worker_input", "output", "discarded_suffix"):
        record = audit[name]
        if not isinstance(record, dict) or set(record) != {"sha256", "characters", "utf8_bytes", "lines"}:
            raise ProtectionViolation("Compressor text measurement differs from the live contract", {"field": name})
        if not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            raise ProtectionViolation("Compressor text measurement has an invalid SHA-256", {"field": name})
        if any(type(record[field]) is not int or record[field] < 0 for field in ("characters", "utf8_bytes", "lines")):
            raise ProtectionViolation("Compressor text measurement has an invalid count", {"field": name})
    source_bytes, output_bytes = source.encode(), result.text.encode()
    expected_source = {"sha256": digest(source_bytes), "characters": len(source),
                       "utf8_bytes": len(source_bytes), "lines": len(source.splitlines())}
    expected_output = {"sha256": digest(output_bytes), "characters": len(result.text),
                       "utf8_bytes": len(output_bytes), "lines": len(result.text.splitlines())}
    if audit["source"] != expected_source or audit["output"] != expected_output:
        raise ProtectionViolation("Compressor audit does not match its actual input or output")
    worker_input, discarded = audit["worker_input"], audit["discarded_suffix"]
    if source and worker_input["characters"] + discarded["characters"] != len(source):
        raise ProtectionViolation("Compressor character boundary accounting is incomplete")
    if worker_input["utf8_bytes"] + discarded["utf8_bytes"] != len(source_bytes):
        raise ProtectionViolation("Compressor byte boundary accounting is incomplete")
    if audit["overflow_applied"] != bool(discarded["characters"]):
        raise ProtectionViolation("Compressor overflow flag differs from the discarded suffix")
    if audit["overflow_applied"] and not (
        isinstance(audit["discarded_suffix_artifact"], str)
        and re.fullmatch(r"span-\d{5}/discarded-suffix\.txt", audit["discarded_suffix_artifact"])
    ):
        raise ProtectionViolation("Discarded compressor input needs a private source artifact")
    if not audit["overflow_applied"] and worker_input != expected_source:
        raise ProtectionViolation("An uncapped compressor must account for its complete source input")
    worker_id = audit["worker_id"]
    if worker_id is not None and (type(worker_id) is not int or worker_id < 1):
        raise ProtectionViolation("Compressor worker identifier is invalid")
    if condition == "llmlingua2" and worker_id not in range(1, 9):
        raise ProtectionViolation("LLMLingua worker identifier differs from the fixed intervention")
    if condition != "llmlingua2" and worker_id is not None:
        raise ProtectionViolation("A non-LLMLingua adapter reported an unexpected worker")
    if (
        audit["overflow_policy"] != "none"
        or worker_input != expected_source
        or discarded["characters"]
        or audit["discarded_suffix_artifact"] is not None
    ):
        raise ProtectionViolation("A compressor reported an input cap under the no-cap policy")
    return audit


def provider_timing(response: dict | None, client_http_seconds: float) -> dict:
    timing = {
        "client_http_seconds": client_http_seconds,
        "transport_seconds": None,
        "model_seconds": None,
        "provider_service_seconds": None,
        "pre_inference_seconds": None,
        "transport_basis": "client_http_minus_provider_service_ttlt",
        "model_basis": "provider_usage_latency_checkpoint_engine_ttlt",
        "timing_status": "provider_checkpoint_unavailable",
    }
    usage = response.get("usage") if isinstance(response, dict) else None
    checkpoint = usage.get("latency_checkpoint") if isinstance(usage, dict) else None
    if not isinstance(checkpoint, dict):
        return timing

    def seconds(name: str) -> float | None:
        value = checkpoint.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return None
        return value / 1000

    model = seconds("engine_ttlt_ms")
    service = seconds("service_ttlt_ms")
    pre_inference = seconds("pre_inference_ms")
    transport = None if service is None or service > client_http_seconds else client_http_seconds - service
    timing.update(
        transport_seconds=transport,
        model_seconds=model,
        provider_service_seconds=service,
        pre_inference_seconds=pre_inference,
        timing_status=(
            "complete" if None not in (transport, model, service, pre_inference)
            else "provider_service_exceeds_client_http" if service is not None and service > client_http_seconds
            else "provider_checkpoint_incomplete"
        ),
    )
    return timing


class TrialRequestBlocked(RuntimeError):
    def __init__(self, trial_id: str, failure: dict):
        super().__init__(f"Trial {trial_id} cannot issue another request")
        self.trial_id = trial_id
        self.failure = failure


class DeploymentQueue:
    def __init__(self, path: Path, deployment: str, rpm: int, tpm: int, *, clock=time.time):
        if type(rpm) is not int or type(tpm) is not int or rpm < 1 or tpm < 1:
            raise ValueError("Verified positive deployment RPM and TPM are required")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("Shared queue must not be a symlink")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("Shared queue must be a regular file")
        self.file = os.fdopen(descriptor, "r+", encoding="utf-8")
        self.deployment, self.rpm, self.tpm, self.clock = deployment, rpm, tpm, clock
        self.reservations = deque()
        self.not_before = 0
        self.lock = threading.Lock()
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX)
            empty = not self._reload()
            if empty:
                self.persist()
        except Exception:
            self.file.close()
            raise
        finally:
            if not self.file.closed:
                fcntl.flock(self.file, fcntl.LOCK_UN)

    def _reload(self) -> bool:
        self.file.seek(0)
        saved = self.file.read()
        state = json.loads(saved) if saved else {
            "deployment": self.deployment, "reservations": [], "not_before": 0,
        }
        if state["deployment"] != self.deployment:
            raise ValueError("Shared queue belongs to another deployment")
        reservations = state["reservations"]
        if not isinstance(reservations, list) or any(
            not isinstance(row, list) or len(row) != 2
            or type(row[0]) not in (int, float) or not math.isfinite(row[0])
            or type(row[1]) is not int or row[1] < 1 for row in reservations
        ) or reservations != sorted(reservations, key=lambda row: row[0]):
            raise ValueError("Shared queue reservations are invalid")
        if type(state["not_before"]) not in (int, float) or not math.isfinite(state["not_before"]):
            raise ValueError("Shared queue cooldown is invalid")
        if reservations and reservations[-1][0] > self.clock() + 1:
            raise ValueError("Clock moved backwards; shared reservations must not be discarded")
        self.reservations = deque(reservations)
        self.not_before = state["not_before"]
        return bool(saved)

    def persist(self):
        self.file.seek(0)
        json.dump({"deployment": self.deployment, "reservations": list(self.reservations),
                   "not_before": self.not_before}, self.file)
        self.file.truncate()
        self.file.flush()
        os.fsync(self.file.fileno())

    def reserve(
        self,
        estimated_tokens: int,
        stopped: threading.Event,
        *,
        deadline: float | None = None,
        attempt_deadline: float | None = None,
        trial_id: str | None = None,
    ) -> float:
        if type(estimated_tokens) is not int or estimated_tokens < 1 or estimated_tokens > self.tpm:
            raise ValueError("Request token reservation exceeds the configured TPM; do not wait forever")
        started = self.clock()
        while True:
            current = self.clock()
            if stopped.is_set():
                raise ProtectionViolation("Run stopped while waiting")
            if deadline is not None and current >= deadline:
                raise SafetyLimitReached(
                    "run_deadline_utc", "run", deadline, current, stop_kind="censored"
                )
            if attempt_deadline is not None and current >= attempt_deadline:
                raise SafetyLimitReached(
                    "max_wall_seconds_per_attempt", "attempt", attempt_deadline, current,
                    trial_id=trial_id, stop_kind="censored",
                )
            with self.lock:
                fcntl.flock(self.file, fcntl.LOCK_EX)
                try:
                    current = self.clock()
                    self._reload()
                    while self.reservations and self.reservations[0][0] <= current - 60:
                        self.reservations.popleft()
                    limited = len(self.reservations) >= self.rpm or sum(row[1] for row in self.reservations) + estimated_tokens > self.tpm
                    ready = max(self.not_before, self.reservations[0][0] + 60 if limited else current)
                    if ready <= current:
                        self.reservations.append([current, estimated_tokens])
                        self.persist()
                        return current - started
                finally:
                    fcntl.flock(self.file, fcntl.LOCK_UN)
            if deadline is not None and ready >= deadline:
                raise SafetyLimitReached(
                    "run_deadline_utc", "run", deadline, ready, stop_kind="censored"
                )
            if attempt_deadline is not None and ready >= attempt_deadline:
                raise SafetyLimitReached(
                    "max_wall_seconds_per_attempt", "attempt", attempt_deadline, ready,
                    trial_id=trial_id, stop_kind="censored",
                )
            stopped.wait(min(ready - current, 1.0))

    def cooldown(self, seconds: float):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Invalid provider cooldown")
        with self.lock:
            fcntl.flock(self.file, fcntl.LOCK_EX)
            try:
                self._reload()
                self.not_before = max(self.not_before, self.clock() + seconds)
                self.persist()
            finally:
                fcntl.flock(self.file, fcntl.LOCK_UN)

    def close(self):
        self.file.close()


class FoundrySender:
    def __init__(self, endpoint: str, bearer, *, timeout_seconds: int | None = None):
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Foundry requires an explicit HTTPS base URL without credentials or query")
        if not parsed.path.rstrip("/").endswith("/openai/v1"):
            raise ValueError("Only the inspected Foundry OpenAI v1 base URL is supported")
        if not parsed.hostname.endswith((".openai.azure.com", ".services.ai.azure.com", ".cognitiveservices.azure.com")):
            raise ValueError("Credentials may only be sent to an explicit Azure Foundry host")
        if timeout_seconds is not None and (type(timeout_seconds) is not int or timeout_seconds < 1):
            raise ValueError("Provider HTTP timeout must be a positive integer")
        self.endpoint, self.bearer = endpoint.rstrip("/"), bearer
        self.timeout_seconds = timeout_seconds
        self.deadline = None

    def __call__(self, body: bytes, *, deadline: float | None = None) -> tuple[int, bytes, dict]:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *arguments, **keywords):
                raise ValueError("Provider redirects are not allowed")

        request = urllib.request.Request(self.endpoint + "/chat/completions", data=body, headers={
            "Authorization": "Bearer " + self.bearer(), "Content-Type": "application/json",
        })
        opener = urllib.request.build_opener(NoRedirect())
        timeout = self.timeout_seconds
        timeout_limit = (
            None if timeout is None else
            ("provider_http_timeout_seconds", "attempt", timeout)
        )
        effective_deadline = min(
            value for value in (self.deadline, deadline) if value is not None
        ) if self.deadline is not None or deadline is not None else None
        if effective_deadline is not None:
            remaining = effective_deadline - time.time()
            if remaining <= 0:
                run_wide = self.deadline is not None and effective_deadline == self.deadline
                raise SafetyLimitReached(
                    "run_deadline_utc" if run_wide else "max_wall_seconds_per_attempt",
                    "run" if run_wide else "attempt", effective_deadline, time.time(),
                    stop_kind="censored",
                )
            if timeout is None or remaining <= timeout:
                timeout = remaining
                run_wide = self.deadline is not None and effective_deadline == self.deadline
                timeout_limit = (
                    "run_deadline_utc" if run_wide else "max_wall_seconds_per_attempt",
                    "run" if run_wide else "attempt",
                    effective_deadline,
                )
        started = time.monotonic()
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)
        except (TimeoutError, urllib.error.URLError) as error:
            timed_out = isinstance(error, TimeoutError) or isinstance(error.reason, TimeoutError)
            if not timed_out or timeout_limit is None:
                raise
            limit_name, scope, applied_limit = timeout_limit
            observed = time.time() if limit_name == "run_deadline_utc" else time.monotonic() - started
            raise SafetyLimitReached(
                limit_name,
                scope,
                applied_limit,
                observed,
                stop_kind="censored",
            ) from error


class ManagedIdentity:
    def __init__(self):
        self.token, self.expires = "", 0
        self.lock = threading.Lock()

    def __call__(self) -> str:
        with self.lock:
            if time.time() >= self.expires - 300:
                query = urllib.parse.urlencode({"api-version": "2018-02-01", "resource": "https://cognitiveservices.azure.com"})
                request = urllib.request.Request("http://169.254.169.254/metadata/identity/oauth2/token?" + query,
                                                 headers={"Metadata": "true"})
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=15) as response:
                    token = json.load(response)
                self.token, self.expires = token["access_token"], int(token["expires_on"])
        return self.token


class LiveRecorder:
    def __init__(self, directory: Path, ledger: dict, source_commit: str, compressor, encoder, queue, sender,
                 *, condition="none", evidence_kind="native_measurement", request_error_scope="run",
                 request_observer=None, request_prefix_message=None):
        self.directory, self.ledger, self.source_commit = directory, ledger, source_commit
        self.compressor, self.encoder, self.queue, self.sender = compressor, encoder, queue, sender
        self.condition, self.evidence_kind = condition, evidence_kind
        if request_error_scope not in ("run", "trial"):
            raise ValueError("Request error scope must be run or trial")
        self.request_error_scope = request_error_scope
        self.request_observer = request_observer
        if request_prefix_message is not None:
            if (
                not isinstance(request_prefix_message, dict)
                or set(request_prefix_message) != {"role", "content"}
                or request_prefix_message.get("role") != "system"
                or not isinstance(request_prefix_message.get("content"), str)
            ):
                raise ValueError("Cache request prefix differs from the namespace contract")
            content = request_prefix_message["content"]
            try:
                expected_prefix = cache_namespace_message(
                    content.removeprefix(CACHE_NAMESPACE_PREFIX)
                )
            except ValueError as error:
                raise ValueError(
                    "Cache request prefix differs from the namespace contract"
                ) from error
            if request_observer is None or request_prefix_message != expected_prefix:
                raise ValueError("Cache request prefix differs from the namespace contract")
            request_prefix_message = dict(request_prefix_message)
        self.request_prefix_message = request_prefix_message
        directory.mkdir(parents=True, exist_ok=False)
        self.lock = threading.RLock()
        self.event_lock = threading.Lock()
        self.stopped = threading.Event()
        self.failure = None
        self.trials = {}
        self.sequence = 0
        self.known_provider_cost_usd = 0.0
        self.unconfirmed_provider_exposure_usd = 0.0
        self.pending_provider_exposure_usd = 0.0
        self.safety_policy = None
        self.safety_applied = False
        self.deadline = None
        if ledger.get("schema_version") == 4:
            self.safety_applied = (
                ledger["limits"]["max_api_cost_usd_per_attempt"] > 0
                and ledger["limits"]["max_api_cost_usd_per_run"] > 0
                and bool(ledger["limits"]["run_deadline_utc"])
            )
            self.safety_policy = safety_policy_record(ledger, applied=self.safety_applied)
            if self.safety_applied:
                self.deadline = effective_deadline_epoch(self.safety_policy)
                if hasattr(self.sender, "deadline"):
                    self.sender.deadline = self.deadline
        self.serialize = canonical

    def event(self, payload):
        with self.event_lock, (self.directory / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": now(), "kind": self.evidence_kind, "condition": self.condition,
                                     "source_commit": self.source_commit, **payload},
                                    ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def register_trial(self, trial_id: str, task: str, repetition: int):
        with self.lock:
            self.check()
            if not re.fullmatch(r"[a-z0-9-]+", trial_id) or trial_id in self.trials:
                raise ValueError("A new safe trial identifier is required")
            self.trials[trial_id] = {
                "task": task, "repetition": repetition, "calls": 0,
                "assistant_hashes": set(), "closed": False, "failure": None,
                "provider_http_attempts": 0, "pending_http_attempts": 0,
                "known_provider_cost_usd": 0.0,
                "unconfirmed_provider_exposure_usd": 0.0,
                "pending_provider_exposure_usd": 0.0,
                "pending_dispatches": {},
                "progress_signals": deque(),
                "last_request": None, "last_response": None,
                "started_at": now(), "started_monotonic": time.monotonic(),
            }

    def initialize_run_cost_exposure(
        self,
        *,
        known_cost_usd: float,
        unconfirmed_exposure_usd: float,
        unknown_without_estimate: int = 0,
    ) -> None:
        if not self.safety_applied:
            return
        values = (known_cost_usd, unconfirmed_exposure_usd)
        if any(
            type(value) not in (int, float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
            for value in values
        ):
            raise ValueError("Prior provider cost exposure must be finite and nonnegative")
        if type(unknown_without_estimate) is not int or unknown_without_estimate < 0:
            raise ValueError("Prior unknown provider request count is invalid")
        if unknown_without_estimate:
            raise ValueError("Cannot resume paid execution with unbounded prior provider exposure")
        with self.lock:
            if self.trials or any((
                self.known_provider_cost_usd,
                self.unconfirmed_provider_exposure_usd,
                self.pending_provider_exposure_usd,
            )):
                raise ValueError("Run cost exposure must be initialized before registering attempts")
            self.known_provider_cost_usd = float(known_cost_usd)
            self.unconfirmed_provider_exposure_usd = float(unconfirmed_exposure_usd)
            total = self.known_provider_cost_usd + self.unconfirmed_provider_exposure_usd
            if total > self.ledger["limits"]["max_api_cost_usd_per_run"]:
                raise SafetyLimitReached(
                    "max_api_cost_usd_per_run", "run",
                    self.ledger["limits"]["max_api_cost_usd_per_run"], total,
                )

    def close_trial(self, trial_id: str):
        with self.lock:
            self.trials[trial_id]["closed"] = True
            self.event({"event": "trial_closed", "trial_id": trial_id})

    def stop(self, reason: str, details=None):
        with self.lock:
            self.stopped.set()
            if self.failure is None:
                self.failure = {"reason": reason, "details": details or {}}
                self.event({"event": "run_stopped", **self.failure})

    def stop_trial(self, trial_id: str, reason: str, details=None) -> None:
        with self.lock:
            trial = self.trials.get(trial_id)
            if trial is not None and trial["failure"] is None:
                trial["failure"] = {"reason": reason, "details": details or {}}
                self.event({"event": "trial_stopped", "trial_id": trial_id, **trial["failure"]})

    def record_safety_stop(self, trial_id: str, error: SafetyLimitReached) -> None:
        self._bind_safety_error(trial_id, error)
        self.stop_trial(trial_id, type(error).__name__, error.details)
        if error.run_wide:
            self.stop(type(error).__name__, error.details)

    def _bind_safety_error(self, trial_id: str, error: SafetyLimitReached) -> None:
        if error.details["trial_id"] is None:
            error.details["trial_id"] = trial_id
        if error.details["limit_name"] == "max_wall_seconds_per_attempt":
            with self.lock:
                elapsed = time.monotonic() - self.trials[trial_id]["started_monotonic"]
            error.details["applied_limit"] = self.ledger["limits"]["max_wall_seconds_per_attempt"]
            error.details["observed"] = elapsed

    def safety_snapshot(self, trial_id: str) -> dict | None:
        if self.safety_policy is None:
            return None
        with self.lock:
            trial = self.trials[trial_id]
            termination = trial["failure"]
            if termination is None and safety_failure(self.failure) is not None:
                termination = self.failure
            return {
                "policy": self.safety_policy,
                "provider_http_attempts": trial["provider_http_attempts"],
                "confirmed_api_calculated_cost_usd": trial["known_provider_cost_usd"],
                "unconfirmed_api_cost_exposure_usd": trial["unconfirmed_provider_exposure_usd"],
                "pending_api_cost_exposure_usd": trial["pending_provider_exposure_usd"],
                "run_confirmed_api_calculated_cost_usd": self.known_provider_cost_usd,
                "run_unconfirmed_api_cost_exposure_usd": self.unconfirmed_provider_exposure_usd,
                "run_pending_api_cost_exposure_usd": self.pending_provider_exposure_usd,
                "last_request": trial["last_request"],
                "last_response": trial["last_response"],
                "termination": termination,
            }

    def record_delivery_failure(self, trial_id: str, error: OSError) -> None:
        failure = {
            "reason": "ClientDisconnectedAfterDispatch",
            "details": {"error_type": type(error).__name__, "message": str(error)},
        }
        if self.request_error_scope == "run":
            self.stop(failure["reason"], failure["details"])
            return
        with self.lock:
            trial = self.trials.get(trial_id)
            if trial is not None and trial["failure"] is None:
                trial["failure"] = failure
                self.event({
                    "event": "trial_response_delivery_failed", "trial_id": trial_id,
                    **failure,
                })

    def check(self):
        if self.stopped.is_set():
            raise ProtectionViolation("All subsequent requests are blocked", self.failure)
        if self.safety_applied and self.deadline is not None and time.time() >= self.deadline:
            raise SafetyLimitReached(
                "run_deadline_utc", "run", self.deadline, time.time(), stop_kind="censored"
            )

    def check_trial(self, trial_id: str) -> None:
        try:
            self.check()
        except SafetyLimitReached as error:
            self._bind_safety_error(trial_id, error)
            raise
        if not self.safety_applied:
            return
        with self.lock:
            trial = self.trials[trial_id]
            if trial["failure"] is not None:
                raise TrialRequestBlocked(trial_id, trial["failure"])
            elapsed = time.monotonic() - trial["started_monotonic"]
            limit = self.ledger["limits"]["max_wall_seconds_per_attempt"]
            if elapsed >= limit:
                raise SafetyLimitReached(
                    "max_wall_seconds_per_attempt", "attempt", limit, elapsed,
                    trial_id=trial_id, stop_kind="censored",
                )

    def attempt_deadline_epoch(self, trial_id: str) -> float | None:
        if not self.safety_applied:
            return None
        with self.lock:
            trial = self.trials[trial_id]
            elapsed = time.monotonic() - trial["started_monotonic"]
            remaining = self.ledger["limits"]["max_wall_seconds_per_attempt"] - elapsed
        return time.time() + max(0.0, remaining)

    def request_contract(self, payload):
        required = {"model", "temperature", "reasoning_effort", "messages"}
        if self.safety_applied:
            required.add("max_completion_tokens")
        if not required <= payload.keys() or payload.keys() - required - {"stream"}:
            raise ProtectionViolation("Unexpected or missing live request fields")
        expected = self.ledger["model"]
        for key in ("model", "temperature", "reasoning_effort"):
            value = expected["name"] if key == "model" else expected[key]
            if type(payload[key]) is bool or payload[key] != value:
                raise ProtectionViolation("Actual model settings differ from the ledger", {"field": key})
        if self.safety_applied and payload["max_completion_tokens"] != self.ledger["limits"]["max_output_tokens"]:
            raise ProtectionViolation("Actual output token cap differs from the ledger", {"field": "max_completion_tokens"})
        if payload.get("stream", False) is not False:
            raise ProtectionViolation("Only nonstreaming completions are supported")
        if not isinstance(payload["messages"], list) or not payload["messages"]:
            raise ProtectionViolation("A nonempty live conversation is required")
        for message in payload["messages"]:
            if not isinstance(message, dict) or set(message) != {"role", "content"} or message["role"] not in ("user", "assistant", "system") or not isinstance(message["content"], str):
                raise ProtectionViolation("Unexpected live message structure")

    def _record_progress(self, trial_id: str, payload: dict) -> None:
        if not self.safety_applied:
            return
        signal = progress_signal(payload)
        limits = self.ledger["limits"]
        with self.lock:
            trial = self.trials[trial_id]
            signals = trial["progress_signals"]
            signals.append(signal)
            while len(signals) > limits["no_progress_window_calls"]:
                signals.popleft()
            distinct = len(set(signals))
            self.event({
                "event": "progress_window_observed", "trial_id": trial_id,
                "window_size": len(signals), "distinct_signals": distinct,
                "latest_signal_sha256": signal,
            })
            if (
                len(signals) == limits["no_progress_window_calls"]
                and distinct < limits["no_progress_minimum_distinct_signals"]
            ):
                raise SafetyLimitReached(
                    "no_progress_window",
                    "attempt",
                    limits["no_progress_minimum_distinct_signals"],
                    distinct,
                    trial_id=trial_id,
                    stop_kind="censored",
                )

    def _reserve_dispatch(
        self,
        trial_id: str,
        request_number: int,
        http_attempt: int,
        reservation_usd: float,
        request_sha256: str,
        request_bytes: int,
    ) -> tuple[int, int]:
        if not self.safety_applied:
            return request_number, http_attempt
        self.check_trial(trial_id)
        limits = self.ledger["limits"]
        with self.lock:
            self.check()
            trial = self.trials[trial_id]
            attempted = trial["provider_http_attempts"] + trial["pending_http_attempts"]
            if attempted >= limits["max_provider_calls_per_attempt"]:
                raise SafetyLimitReached(
                    "max_provider_calls_per_attempt", "attempt",
                    limits["max_provider_calls_per_attempt"], attempted + 1,
                    trial_id=trial_id,
                )
            attempt_exposure = (
                trial["known_provider_cost_usd"]
                + trial["unconfirmed_provider_exposure_usd"]
                + trial["pending_provider_exposure_usd"]
            )
            run_exposure = (
                self.known_provider_cost_usd
                + self.unconfirmed_provider_exposure_usd
                + self.pending_provider_exposure_usd
            )
            if attempt_exposure + reservation_usd > limits["max_api_cost_usd_per_attempt"]:
                raise SafetyLimitReached(
                    "max_api_cost_usd_per_attempt", "attempt",
                    limits["max_api_cost_usd_per_attempt"], attempt_exposure + reservation_usd,
                    trial_id=trial_id,
                )
            if run_exposure + reservation_usd > limits["max_api_cost_usd_per_run"]:
                raise SafetyLimitReached(
                    "max_api_cost_usd_per_run", "run",
                    limits["max_api_cost_usd_per_run"], run_exposure + reservation_usd,
                    trial_id=trial_id,
                )
            key = (request_number, http_attempt)
            trial["pending_dispatches"][key] = reservation_usd
            trial["pending_http_attempts"] += 1
            trial["pending_provider_exposure_usd"] += reservation_usd
            self.pending_provider_exposure_usd += reservation_usd
            trial["last_request"] = {
                "logical_request": request_number,
                "http_attempt": http_attempt,
                "request_sha256": request_sha256,
                "request_bytes": request_bytes,
                "usage_status": "not_returned",
            }
            return key

    def _cancel_dispatch_reservation(self, trial_id: str, key: tuple[int, int]) -> None:
        if not self.safety_applied:
            return
        with self.lock:
            trial = self.trials[trial_id]
            reservation = trial["pending_dispatches"].pop(key)
            trial["pending_http_attempts"] -= 1
            trial["pending_provider_exposure_usd"] -= reservation
            self.pending_provider_exposure_usd -= reservation

    def _mark_dispatch_started(self, trial_id: str, key: tuple[int, int]) -> None:
        if not self.safety_applied:
            return
        with self.lock:
            trial = self.trials[trial_id]
            trial["pending_http_attempts"] -= 1
            trial["provider_http_attempts"] += 1

    def _settle_dispatch(
        self,
        trial_id: str,
        key: tuple[int, int],
        *,
        known_cost_usd: float | None,
        unconfirmed_exposure_usd: float | None,
        response: dict,
    ) -> None:
        if not self.safety_applied:
            if known_cost_usd is not None:
                with self.lock:
                    self.known_provider_cost_usd += known_cost_usd
            return
        with self.lock:
            trial = self.trials[trial_id]
            reservation = trial["pending_dispatches"].pop(key)
            trial["pending_provider_exposure_usd"] -= reservation
            self.pending_provider_exposure_usd -= reservation
            if known_cost_usd is not None:
                trial["known_provider_cost_usd"] += known_cost_usd
                self.known_provider_cost_usd += known_cost_usd
            else:
                exposure = reservation if unconfirmed_exposure_usd is None else unconfirmed_exposure_usd
                trial["unconfirmed_provider_exposure_usd"] += exposure
                self.unconfirmed_provider_exposure_usd += exposure
            trial["last_response"] = response
            if trial["last_request"] is not None:
                trial["last_request"]["usage_status"] = response.get("usage_status", "unknown")

    def _check_settled_cost_limits(self, trial_id: str) -> None:
        if not self.safety_applied:
            return
        limits = self.ledger["limits"]
        with self.lock:
            trial = self.trials[trial_id]
            attempt_exposure = (
                trial["known_provider_cost_usd"]
                + trial["unconfirmed_provider_exposure_usd"]
                + trial["pending_provider_exposure_usd"]
            )
            run_exposure = (
                self.known_provider_cost_usd
                + self.unconfirmed_provider_exposure_usd
                + self.pending_provider_exposure_usd
            )
        if attempt_exposure > limits["max_api_cost_usd_per_attempt"]:
            raise SafetyLimitReached(
                "max_api_cost_usd_per_attempt", "attempt",
                limits["max_api_cost_usd_per_attempt"], attempt_exposure,
                trial_id=trial_id,
            )
        if run_exposure > limits["max_api_cost_usd_per_run"]:
            raise SafetyLimitReached(
                "max_api_cost_usd_per_run", "run",
                limits["max_api_cost_usd_per_run"], run_exposure,
                trial_id=trial_id,
            )

    def reject_request_size(self, trial_id: str, observed: int) -> SafetyLimitReached:
        with self.lock:
            trial = self.trials[trial_id]
            trial["last_request"] = {
                "logical_request": None,
                "http_attempt": None,
                "request_sha256": None,
                "request_bytes": observed,
                "usage_status": "not_dispatched",
            }
        error = SafetyLimitReached(
            "max_request_bytes", "attempt", self.ledger["limits"]["max_request_bytes"], observed,
            trial_id=trial_id, stop_kind="censored",
        )
        self.record_safety_stop(trial_id, error)
        return error

    def complete(self, trial_id: str, source: bytes) -> tuple[int, bytes]:
        try:
            self.check()
            return self._complete(trial_id, source)
        except Exception as error:
            if isinstance(error, SafetyLimitReached):
                self.record_safety_stop(trial_id, error)
            details = getattr(error, "details", {"message": str(error)})
            run_wide = (
                error.run_wide if isinstance(error, SafetyLimitReached)
                else self.request_error_scope == "run" or isinstance(error, ProtectionViolation) or str(error) in {
                "Provider total tokens disagree with input plus output",
                "Provider-reported model revision differs from the ledger",
                }
            )
            if not isinstance(error, SafetyLimitReached):
                if run_wide:
                    self.stop(type(error).__name__, details)
                else:
                    with self.lock:
                        trial = self.trials.get(trial_id)
                        if trial is not None and trial["failure"] is None:
                            trial["failure"] = {"reason": type(error).__name__, "details": details}
                            self.event({
                                "event": "trial_request_failed", "trial_id": trial_id,
                                **trial["failure"],
                            })
            raise

    def _complete(self, trial_id: str, source: bytes) -> tuple[int, bytes]:
        limits, prices = self.ledger["limits"], self.ledger["prices"]
        with self.lock:
            self.check()
            trial = self.trials[trial_id]
            if trial["closed"]:
                raise ProtectionViolation("A finished trial cannot issue another request")
            if trial["failure"] is not None:
                raise TrialRequestBlocked(trial_id, trial["failure"])
            if self.safety_applied and len(source) > limits["max_request_bytes"]:
                trial["last_request"] = {
                    "logical_request": None,
                    "http_attempt": None,
                    "request_sha256": digest(source),
                    "request_bytes": len(source),
                    "usage_status": "not_dispatched",
                }
                raise SafetyLimitReached(
                    "max_request_bytes", "attempt", limits["max_request_bytes"], len(source),
                    trial_id=trial_id, stop_kind="censored",
                )
            self.sequence += 1
            request_number = self.sequence
            trial["calls"] += 1
            task = trial["task"]
            repetition = trial["repetition"]
            assistant_hashes = set(trial["assistant_hashes"])
            if self.safety_applied:
                trial["last_request"] = {
                    "logical_request": request_number,
                    "http_attempt": None,
                    "request_sha256": digest(source),
                    "request_bytes": len(source),
                    "usage_status": "not_dispatched",
                }
        self.event({"event": "call_received", "trial_id": trial_id, "request": request_number,
                    "task": task, "repetition": repetition, "request_sha256": digest(source)})
        directory = self.directory / f"request-{request_number:05d}"
        directory.mkdir()
        received = source
        payload = parse_request(source)
        self.request_contract(payload)
        if self.request_prefix_message is not None:
            payload = {
                **payload,
                "messages": [dict(self.request_prefix_message), *payload["messages"]],
            }
            source = canonical(payload)
            (directory / "received.json").write_bytes(received)
        (directory / "before.json").write_bytes(source)
        self._record_progress(trial_id, payload)
        segments = partition(payload, assistant_hashes)
        write_json(directory / "manifest.json", {"source_sha256": digest(source), "segments": segments,
                                                "classification_policy": POLICY, "trial_id": trial_id})
        guard = FrozenRequestGuard(source, digest(source), segments)
        originals = guard.candidate_texts()
        candidate_segments = [segment for segment in segments if segment["candidate"]]
        compressed = []
        compression_records = []
        for candidate_index, (segment, original) in enumerate(zip(candidate_segments, originals, strict=True)):
            started = time.monotonic()
            try:
                result = self.compressor.compress(original)
                timing = compressor_timing(result, time.monotonic() - started)
                audit = compression_audit(result, original, self.condition)
            except Exception as error:
                self.event({
                    "event": "compressor_failed", "trial_id": trial_id, "request": request_number,
                    "candidate_index": candidate_index, "before_sha256": digest(original.encode()),
                    "compressor_wall_seconds": time.monotonic() - started,
                    "error_type": type(error).__name__, **segment,
                })
                raise
            record = {
                "event": "compressor_completed", "trial_id": trial_id, "request": request_number,
                "candidate_index": candidate_index, "before_sha256": digest(original.encode()),
                "after_sha256": digest(result.text.encode()), "changed": original != result.text,
                "worker_id": audit["worker_id"], "audit": audit, **timing,
            }
            self.event(record)
            compression_records.append({key: value for key, value in record.items() if key not in {
                "event", "trial_id", "request", "candidate_index"
            }})
            compressed.append(result)
        transformed = guard.prepare([result.text for result in compressed])
        outgoing = self.serialize(transformed)
        request_observation = None
        if self.request_observer is not None:
            request_observation = self.request_observer(
                trial_id=trial_id,
                task=task,
                repetition=repetition,
                request=request_number,
                payload=transformed,
                serialized=outgoing,
            )
            if not isinstance(request_observation, dict):
                raise ProtectionViolation("Cache request observer must return a metadata object")
        observation_fields = {} if request_observation is None else {"cache_reuse": request_observation}
        (directory / "after.json").write_bytes(outgoing)
        proof = guard.verify_serialized(outgoing)
        if self.safety_applied and len(outgoing) > limits["max_request_bytes"]:
            with self.lock:
                trial["last_request"] = {
                    "logical_request": request_number,
                    "http_attempt": None,
                    "request_sha256": digest(outgoing),
                    "request_bytes": len(outgoing),
                    "usage_status": "not_dispatched",
                }
            raise SafetyLimitReached(
                "max_request_bytes", "attempt", limits["max_request_bytes"], len(outgoing),
                trial_id=trial_id, stop_kind="censored",
            )
        input_measurement = {
            "kind": "calculated", "before": counts(payload, originals, self.encoder),
            "after": counts(transformed, [result.text for result in compressed], self.encoder),
            "candidates": [{"before_sha256": digest(original.encode()), "after_sha256": digest(result.text.encode()),
                            "before_lines": len(original.splitlines()), "after_lines": len(result.text.splitlines()),
                            "changed": original != result.text, "tool_reported": result.tool_reported,
                            "compression": compression}
                           for original, result, compression in zip(originals, compressed, compression_records, strict=True)],
        }
        write_json(directory / "protection.json", proof)
        write_json(directory / "local-input.json", input_measurement)
        for candidate_index, (segment, original, result) in enumerate(zip(
            candidate_segments, originals, compressed
        )):
            if original != result.text:
                self.event({
                    "event": "candidate_changed", "trial_id": trial_id, "request": request_number,
                    "candidate_index": candidate_index, "before_sha256": digest(original.encode()),
                    "after_sha256": digest(result.text.encode()), **segment,
                    "before_lines": len(original.splitlines()), "after_lines": len(result.text.splitlines()),
                })
        local_input_tokens = token_count(outgoing.decode(), self.encoder)
        input_cost_estimate = local_input_tokens * prices["input_per_million_usd"] / 1_000_000
        if self.safety_applied:
            output_cap = limits["max_output_tokens"]
            reserved_input_tokens = local_input_tokens + limits["protocol_token_allowance"]
            reservation = (
                reserved_input_tokens * prices["input_per_million_usd"]
                + output_cap * prices["output_per_million_usd"]
            ) / 1_000_000
            rate_estimate = max(1, reserved_input_tokens + output_cap)
        else:
            reservation = None
            rate_estimate = max(1, local_input_tokens)
        for attempt in range(1, limits["transient_http_attempts"] + 1):
            request_sha256 = digest(outgoing)
            dispatch_key = self._reserve_dispatch(
                trial_id, request_number, attempt, reservation or 0.0, request_sha256,
                len(outgoing),
            )
            try:
                waited = self.queue.reserve(
                    rate_estimate,
                    self.stopped,
                    deadline=self.deadline,
                    attempt_deadline=self.attempt_deadline_epoch(trial_id),
                    trial_id=trial_id,
                )
                guard.verify_serialized(outgoing)
                self.check_trial(trial_id)
            except Exception:
                self._cancel_dispatch_reservation(trial_id, dispatch_key)
                raise
            self._mark_dispatch_started(trial_id, dispatch_key)
            self.event({"event": "attempt_started", "trial_id": trial_id, "request": request_number,
                        "attempt": attempt, "request_sha256": request_sha256,
                        "local_input_tokens": input_measurement["after"]["message_content_tokens"],
                        "queue_wait_seconds": waited, "rate_reservation_tokens": rate_estimate,
                        "input_cost_estimate_usd": input_cost_estimate,
                        "input_cost_estimate_is_total_cost_bound": False,
                        **({"budget_reservation_usd": reservation,
                            "reservation_is_provider_guarantee": False}
                           if reservation is not None else {}),
                        **observation_fields})
            started = time.monotonic()
            try:
                if isinstance(self.sender, FoundrySender):
                    status, raw, headers = self.sender(
                        outgoing, deadline=self.attempt_deadline_epoch(trial_id)
                    )
                else:
                    status, raw, headers = self.sender(outgoing)
            except Exception as error:
                elapsed = time.monotonic() - started
                self.event({"event": "http", "trial_id": trial_id, "request": request_number,
                            "attempt": attempt, "status": None, "provider_usage": None, "tokens": None,
                            "calculated_cost_usd": None, "error_type": type(error).__name__,
                            "elapsed_seconds": elapsed, **provider_timing(None, elapsed),
                            "billing_unknown": True, **observation_fields})
                self._settle_dispatch(
                    trial_id, dispatch_key, known_cost_usd=None,
                    unconfirmed_exposure_usd=reservation,
                    response={"http_status": None, "response_sha256": None, "usage_status": "unknown"},
                )
                raise
            elapsed = time.monotonic() - started
            (directory / f"response-{attempt:02d}.json").write_bytes(raw)
            record = {"event": "http", "trial_id": trial_id, "request": request_number, "attempt": attempt,
                      "status": status, "response_sha256": digest(raw), "elapsed_seconds": elapsed,
                      "provider_usage": None, "calculated_cost_usd": None,
                      "invoice_reconciled": False, "source_commit": self.source_commit,
                      **observation_fields,
                      **provider_timing(None, elapsed)}
            if status == 200:
                try:
                    response = parse_request(raw)
                except (ValueError, UnicodeError, TypeError):
                    self.event({**record, "error_type": "MalformedProviderResponse", "billing_unknown": True})
                    self._settle_dispatch(
                        trial_id, dispatch_key, known_cost_usd=None,
                        unconfirmed_exposure_usd=reservation,
                        response={
                            "http_status": status, "response_sha256": digest(raw),
                            "usage_status": "unknown",
                        },
                    )
                    raise ValueError("Provider response is not unambiguous JSON") from None
                tokens = provider_tokens(response)
                record.update(provider_timing(response, elapsed))
                if tokens is None:
                    self.event(record)
                    self._settle_dispatch(
                        trial_id, dispatch_key, known_cost_usd=None,
                        unconfirmed_exposure_usd=reservation,
                        response={"http_status": status, "response_sha256": digest(raw), "usage_status": "unknown"},
                    )
                    raise ValueError("Successful response lacks valid provider usage; actual cost remains unknown")
                cached = tokens["cached_input_tokens"]
                upper_cost = (tokens["input_tokens"] * prices["input_per_million_usd"] + tokens["output_tokens"] * prices["output_per_million_usd"]) / 1_000_000
                exact_cost = None if cached is None else upper_cost - cached * (prices["input_per_million_usd"] - prices["cached_input_per_million_usd"]) / 1_000_000
                choices = response.get("choices")
                choice = choices[0] if isinstance(choices, list) and len(choices) == 1 else None
                message = choice.get("message") if isinstance(choice, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                valid_content = isinstance(content, str) and message.get("role") == "assistant"
                record.update(provider_usage=response["usage"], provider_reported_model=response.get("model"),
                              provider_response_id=response.get("id"), tokens=tokens,
                              provider_fingerprint=response.get("system_fingerprint"),
                              finish_reason=None if choice is None else choice.get("finish_reason"),
                              calculated_cost_usd=exact_cost,
                              uncached_cost_ceiling_usd=upper_cost,
                              cost_basis="provider_usage_times_ledger_rates_not_invoice")
                if valid_content:
                    record["local_output"] = {
                        "content_utf8_bytes": len(content.encode()),
                        "content_tokens": token_count(content, self.encoder),
                        "tokenizer": "o200k_base",
                    }
                elif choice is None:
                    record["error_type"] = "UnexpectedChoiceCount"
                else:
                    record["error_type"] = "UnexpectedAssistantOutput"
                self.event(record)
                self._settle_dispatch(
                    trial_id, dispatch_key, known_cost_usd=exact_cost,
                    unconfirmed_exposure_usd=upper_cost if exact_cost is None else None,
                    response={
                        "http_status": status, "response_sha256": digest(raw),
                        "usage_status": "measured" if exact_cost is not None else "requires_review",
                        "provider_usage_present": True,
                    },
                )
                if self.safety_applied and tokens["output_tokens"] > limits["max_output_tokens"]:
                    raise SafetyLimitReached(
                        "max_output_tokens", "attempt", limits["max_output_tokens"],
                        tokens["output_tokens"], trial_id=trial_id, stop_kind="censored",
                    )
                self._check_settled_cost_limits(trial_id)
                if choice is None:
                    raise ValueError("Expected one textual assistant response")
                if not valid_content:
                    raise ValueError("Unexpected nontext assistant output")
                if response["usage"].get("total_tokens", tokens["input_tokens"] + tokens["output_tokens"]) != tokens["input_tokens"] + tokens["output_tokens"]:
                    raise ValueError("Provider total tokens disagree with input plus output")
                expected_model = self.ledger["model"]["reported_model"]
                if response.get("model") != expected_model:
                    raise ValueError("Provider-reported model revision differs from the ledger")
                with self.lock:
                    self.check()
                    trial["assistant_hashes"].add(digest(content.encode()))
                return status, raw
            self.event({**record, "billing_unknown": True})
            self._settle_dispatch(
                trial_id, dispatch_key, known_cost_usd=None,
                unconfirmed_exposure_usd=reservation,
                response={"http_status": status, "response_sha256": digest(raw), "usage_status": "unknown"},
            )
            if status == 429:
                if attempt < limits["transient_http_attempts"]:
                    normalized = {key.lower(): value for key, value in headers.items()}
                    wait = float(normalized.get("retry-after", "60"))
                    if not math.isfinite(wait) or wait < 0:
                        raise ValueError("Retry-After is invalid")
                    if self.safety_applied and wait > limits["max_retry_wait_seconds"]:
                        raise SafetyLimitReached(
                            "max_retry_wait_seconds", "attempt",
                            limits["max_retry_wait_seconds"], wait,
                            trial_id=trial_id, stop_kind="censored",
                        )
                    self.queue.cooldown(wait)
                    continue
            raise ValueError(f"Provider HTTP {status}; no outer retry budget restart")
        raise ValueError("HTTP retry budget exhausted")


def start_live_proxy(recorder: LiveRecorder, key: str) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            if recorder.safety_applied:
                self.connection.settimeout(min(30, recorder.ledger["limits"]["provider_http_timeout_seconds"]))

        def log_message(self, *arguments):
            return

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + key):
                self.send_error(403)
                return
            match = re.fullmatch(r"/([a-z0-9-]+)/v1/chat/completions", self.path)
            if not match or match[1] not in recorder.trials:
                self.send_error(404)
                return
            try:
                if len(self.headers.get_all("Content-Length", [])) != 1 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("Ambiguous request framing")
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1:
                    raise ValueError("Invalid request length")
                if recorder.safety_applied and length > recorder.ledger["limits"]["max_request_bytes"]:
                    raise recorder.reject_request_size(match[1], length)
                source = self.rfile.read(length)
                if len(source) != length:
                    raise ValueError("Incomplete request")
            except Exception as error:
                if not isinstance(error, SafetyLimitReached):
                    with recorder.lock:
                        recorder.stop(type(error).__name__, getattr(error, "details", {"message": str(error)}))
                source = b""
            try:
                status, body = recorder.complete(match[1], source)
            except Exception:
                with recorder.lock:
                    trial = recorder.trials.get(match[1])
                    failure = None if trial is None else trial.get("failure")
                if failure is not None and failure.get("reason") == "SafetyLimitReached":
                    status = 409
                    body = b'{"error":{"type":"safety_limit_reached","message":"See private run diagnostics; this attempt is technically incomplete"}}'
                else:
                    status, body = 503, b'{"error":{"type":"run_stopped","message":"See private run diagnostics; later requests are blocked"}}'
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
                if status == 200:
                    recorder.event({"event": "response_delivered", "trial_id": match[1]})
            except OSError as error:
                recorder.record_delivery_failure(match[1], error)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
