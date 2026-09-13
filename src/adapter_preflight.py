"""Run every pinned compressor through the guarded live path without a provider call."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time

from .compressors import check_compressor_artifacts, make_compressor
from .contracts import safe_child, save_json
from .live_transport import LiveRecorder
from .measurement import load_encoder
from .native_contract import CONDITIONS, load_native_ledger
from .protection import ProtectionViolation, canonical, digest
from .protection import parse_request
from .provenance import capture
from .task_metrics import read_events


COMMAND = "ls /logs"
ASSISTANT = json.dumps({"commands": [{"keystrokes": COMMAND + "\n", "duration": 0.1}]})
SYSTEM_INSTRUCTION = "Protected system instruction for the model-free adapter preflight."
TASK_INSTRUCTION = "Protected task instruction: inspect the public synthetic workspace."
FILE_READ_PREFIX = "src/example.py:\n```python\ndef preserved_identifier():\n    return 'byte-exact'\n```\n"
FILE_READ_SUFFIX = "\nProtected file-read suffix: do not alter code, identifiers, or status text.\n"


class ImmediateQueue:
    def reserve(self, estimate, stopped, deadline):
        return 0.0

    def cooldown(self, seconds):
        raise AssertionError("The model-free sender never returns 429")


class SyntheticSender:
    def __init__(self, model: str):
        self.model = model
        self.calls = 0
        self.bodies = []
        self.lock = threading.Lock()

    def __call__(self, body: bytes) -> tuple[int, bytes, dict]:
        with self.lock:
            self.calls += 1
            self.bodies.append(body)
        response = {
            "id": "software-preflight-not-provider-response",
            "object": "chat.completion",
            "created": 0,
            "model": self.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": ASSISTANT},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                      "prompt_tokens_details": {"cached_tokens": 0}},
        }
        return 200, canonical(response), {}


def request(ledger: dict, messages: list[dict]) -> bytes:
    model = ledger["model"]
    return canonical({
        "model": model["name"], "temperature": model["temperature"],
        "reasoning_effort": model["reasoning_effort"],
        "max_completion_tokens": model["max_completion_tokens"], "messages": messages,
    })


def candidate_content() -> str:
    rows = "".join(f"/long/shared/preflight/file-{index:04d}.log\n" for index in range(240))
    if len(rows) <= 5000:
        raise AssertionError("The fixed preflight candidate must exercise the LLMLingua input cap")
    prompt = "root@123456789abc:/app# "
    return f"{FILE_READ_PREFIX}{prompt}{COMMAND}\n{rows}{prompt}{FILE_READ_SUFFIX}"


def run_condition(root: Path, ledger: dict, condition: str, source_commit: str, encoder) -> dict:
    directory = root / condition
    directory.mkdir()
    compressor = make_compressor({**ledger["compressor"], "name": condition}, directory / "compressor")
    sender = SyntheticSender(ledger["model"]["reported_model"])
    recorder = None
    try:
        local_ledger = deepcopy(ledger)
        local_ledger["limits"]["api_cost_usd"] = 1
        local_ledger["limits"]["deadline_utc"] = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        recorder = LiveRecorder(
            directory / "transport", local_ledger, source_commit, compressor, encoder,
            ImmediateQueue(), sender, condition=condition,
            evidence_kind="software_preflight_not_native_measurement",
        )
        trial_ids = [f"probe-{index:02d}" for index in range(1, 9)]
        for trial_id in trial_ids:
            recorder.register_trial(trial_id, "synthetic-preflight", 1)
            recorder.complete(trial_id, request(local_ledger, [{"role": "user", "content": "Protected preflight instruction"}]))

        payload = request(local_ledger, [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": TASK_INSTRUCTION},
            {"role": "assistant", "content": ASSISTANT},
            {"role": "user", "content": candidate_content()},
        ])
        barrier = threading.Barrier(8)

        def invoke(trial_id: str):
            barrier.wait(timeout=30)
            return recorder.complete(trial_id, payload)

        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix=f"preflight-{condition}") as executor:
            responses = list(executor.map(invoke, trial_ids))
        concurrent_wall_seconds = time.monotonic() - started
        if any(status != 200 for status, _body in responses):
            raise ValueError(f"{condition} did not complete eight guarded synthetic requests")
        outgoing = [parse_request(body) for body in sender.bodies[-8:]]
        protected_checks = {
            "system_instruction": all(row["messages"][0] == {
                "role": "system", "content": SYSTEM_INSTRUCTION,
            } for row in outgoing),
            "task_instruction": all(row["messages"][1] == {
                "role": "user", "content": TASK_INSTRUCTION,
            } for row in outgoing),
            "assistant_history": all(row["messages"][2] == {
                "role": "assistant", "content": ASSISTANT,
            } for row in outgoing),
            "file_read_code": all(
                row["messages"][3]["content"].startswith(FILE_READ_PREFIX)
                and row["messages"][3]["content"].endswith(FILE_READ_SUFFIX)
                for row in outgoing
            ),
        }
        if not all(protected_checks.values()):
            raise ValueError(f"{condition} changed a byte-exact protected preflight category")
        protected_exclusion = []
        for request_number in range(9, 17):
            manifest = json.loads((directory / f"transport/request-{request_number:05d}/manifest.json").read_bytes())
            segments = manifest["segments"]
            excluded = all(
                not segment["candidate"] for segment in segments
                if segment["message_index"] in (0, 1, 2)
            ) and all(
                not segment["candidate"]
                for segment in segments
                if segment["message_index"] == 3 and (
                    segment["char_start"] < len(FILE_READ_PREFIX)
                    or segment["char_end"] > len(candidate_content()) - len(FILE_READ_SUFFIX)
                )
            )
            protected_exclusion.append(excluded)
        if not all(protected_exclusion):
            raise ValueError(f"{condition} exposed protected preflight text to the compressor")

        events = read_events(directory / "transport/events.jsonl")
        completions = [event for event in events if event.get("event") == "compressor_completed"]
        if len(completions) != 8 or any(event["audit"]["source"]["characters"] <= 5000 for event in completions):
            raise ValueError(f"{condition} did not produce eight complete candidate audits")
        worker_ids = sorted({event["worker_id"] for event in completions if event["worker_id"] is not None})
        overflow_calls = sum(event["audit"]["overflow_applied"] for event in completions)
        if condition == "llmlingua2" and (worker_ids != list(range(1, 9)) or overflow_calls != 8):
            raise ValueError("LLMLingua did not exercise all eight workers and the fixed 5000-character cap")
        if condition != "llmlingua2" and (worker_ids or overflow_calls):
            raise ValueError(f"{condition} unexpectedly reported LLMLingua worker or cap behavior")

        calls_before_violation = sender.calls
        original_serializer = recorder.serialize

        def corrupt(value: dict) -> bytes:
            changed = deepcopy(value)
            changed["messages"][0]["content"] += " protected mutation"
            return original_serializer(changed)

        recorder.serialize = corrupt
        try:
            recorder.complete(
                trial_ids[0],
                request(local_ledger, [{"role": "user", "content": "Protected preflight instruction"}]),
            )
        except ProtectionViolation:
            pass
        else:
            raise ValueError(f"{condition} did not block a protected mutation")
        if sender.calls != calls_before_violation or not recorder.stopped.is_set():
            raise ValueError(f"{condition} protection failure reached the synthetic sender")
        record = {
            "condition": condition, "kind": "software_preflight_not_native_measurement",
            "external_model_calls": 0, "concurrent_candidate_requests": 8,
            "concurrent_wall_seconds": concurrent_wall_seconds,
            "completed_compressor_calls": len(completions),
            "changed_compressor_calls": sum(event["changed"] for event in completions),
            "compressor_wall_seconds": sum(event["compressor_wall_seconds"] for event in completions),
            "serialization_wait_seconds": sum(event["serialization_wait_seconds"] for event in completions),
            "worker_inference_seconds": sum(
                event["worker_inference_seconds"] for event in completions
                if event["worker_inference_seconds"] is not None
            ),
            "worker_ids": worker_ids, "overflow_calls": overflow_calls,
            "adapter_path": "LiveRecorder.complete_then_FrozenRequestGuard_then_sender",
            "protected_byte_exact": protected_checks,
            "protected_not_sent_to_compressor": all(protected_exclusion),
            "protected_mutation_blocked_before_sender": True,
            "events_sha256": digest((directory / "transport/events.jsonl").read_bytes()),
        }
    except BaseException as primary_error:
        try:
            compressor.close()
        except BaseException as close_error:
            raise RuntimeError(
                f"{condition} failed before close: {primary_error}; close also failed: {close_error}"
            ) from primary_error
        raise
    else:
        compressor.close()
        return record


def run(ledger_path: Path, source_commit: str, output: Path) -> dict:
    ledger = load_native_ledger(ledger_path)
    provenance, snapshots = capture(ledger_path.resolve(), source_commit)
    if output.exists() or output.is_symlink():
        raise ValueError("Adapter preflight output must be a new private directory")
    output.mkdir(parents=True)
    for name, content in snapshots.items():
        path = safe_child(output, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    save_json(output / "provenance.json", provenance)
    for condition in CONDITIONS:
        check_compressor_artifacts(ledger["compressor"], condition)
    encoder = load_encoder(ledger["measurement"])
    records = [run_condition(output, ledger, condition, source_commit, encoder) for condition in CONDITIONS]
    summary = {
        "schema_version": 1, "kind": "software_preflight_not_native_measurement",
        "source_commit": provenance["source_commit"], "source_sha256": provenance["source_sha256"],
        "ledger_sha256": provenance["ledger_sha256"], "external_model_calls": 0,
        "conditions": records,
    }
    save_json(output / "summary.json", summary)
    return summary


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        summary = run(args.ledger, args.source_commit, args.output)
    except (OSError, RuntimeError, ValueError, ProtectionViolation) as error:
        print(f"Adapter preflight failed: {error}")
        return 2
    print(json.dumps({"status": "passed", "external_model_calls": 0,
                      "source_commit": summary["source_commit"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
