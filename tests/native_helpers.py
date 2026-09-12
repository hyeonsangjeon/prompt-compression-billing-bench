from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.native_contract import load_native_ledger


ROOT = Path(__file__).resolve().parents[1]


def ledger_fixture():
    ledger = load_native_ledger(ROOT / "ledgers/native.template.toml")
    ledger["model"]["max_completion_tokens"] = 16
    ledger["limits"]["protocol_token_allowance"] = 1
    ledger["limits"].update(api_cost_usd=100, deadline_utc=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    ledger["prices"].update(input_per_million_usd=1, cached_input_per_million_usd=0.1,
                             output_per_million_usd=2, source_reference="synthetic test rates",
                             checked_at_utc=datetime.now(timezone.utc).isoformat())
    ledger["queue"].update(deployment_isolation_reference="synthetic test isolation")
    ledger["approval"].update(execution_approved=True, rule_accepted=True, reference="synthetic test only")
    return deepcopy(ledger)


def request_fixture(content="Protected instruction"):
    return {"model": "gpt-5.4", "temperature": 0, "reasoning_effort": "none", "max_completion_tokens": 16,
            "messages": [{"role": "user", "content": content}]}


def response_fixture(content="synthetic response"):
    return json.dumps({
        "id": "synthetic-completion", "object": "chat.completion", "created": 0,
        "model": "gpt-5.4-2026-03-05",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                  "prompt_tokens_details": {"cached_tokens": 0}},
    }).encode()


class FixtureEncoder:
    def encode(self, content, **keywords):
        return list(content.encode())


class ImmediateQueue:
    def __init__(self):
        self.calls = []
        self.cooldowns = []

    def reserve(self, estimate, stopped, deadline):
        self.calls.append(estimate)
        return 0

    def cooldown(self, seconds):
        self.cooldowns.append(seconds)
