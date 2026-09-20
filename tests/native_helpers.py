from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def ledger_fixture_document() -> tuple[dict, bytes]:
    checked_at = datetime.now(timezone.utc).isoformat()
    deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    text = (ROOT / "ledgers/native.template.toml").read_text()
    replacements = {
        'deployment_isolation_reference = ""': 'deployment_isolation_reference = "synthetic test isolation"',
        "max_api_cost_usd_per_attempt = 0": "max_api_cost_usd_per_attempt = 10",
        "max_api_cost_usd_per_run = 0": "max_api_cost_usd_per_run = 100",
        'run_deadline_utc = ""': f'run_deadline_utc = "{deadline}"',
        "\ninput_per_million_usd = 0": "\ninput_per_million_usd = 1",
        "\ncached_input_per_million_usd = 0": "\ncached_input_per_million_usd = 0.1",
        "\noutput_per_million_usd = 0": "\noutput_per_million_usd = 2",
        'source_reference = ""': 'source_reference = "synthetic test rates"',
        'checked_at_utc = ""': f'checked_at_utc = "{checked_at}"',
        "execution_approved = false": "execution_approved = true",
        "rule_accepted = false": "rule_accepted = true",
        "cost_limits_approved = false": "cost_limits_approved = true",
        'reference = ""': 'reference = "synthetic test only"',
    }
    for before, after in replacements.items():
        if text.count(before) != 1:
            raise AssertionError(f"Synthetic ledger replacement is not unique: {before}")
        text = text.replace(before, after)
    content = text.encode()
    return tomllib.loads(text), content


def ledger_fixture():
    ledger, _content = ledger_fixture_document()
    return ledger


def request_fixture(content="Protected instruction"):
    return {"model": "gpt-5.4", "temperature": 0, "reasoning_effort": "none",
            "max_completion_tokens": 2048,
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

    def reserve(self, estimate, stopped, **limits):
        self.calls.append(estimate)
        return 0

    def cooldown(self, seconds):
        self.cooldowns.append(seconds)
