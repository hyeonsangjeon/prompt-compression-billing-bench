"""Count UTF-8 bytes and local tokens without equating either with billing."""

from __future__ import annotations

from collections import Counter
import importlib.metadata
import os
from pathlib import Path
import re
import urllib.request

from .protection import digest


TOKENIZER_FILE = "fb374d419588a4632f3f557e76b4b70aebbca790"
TOKENIZER_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
TOKENIZER_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
UNITS = {
    "message_content_utf8_bytes": "UTF-8 bytes",
    "message_content_tokens": "o200k_base tokens, message content only",
    "candidate_utf8_bytes": "UTF-8 bytes",
    "candidate_tokens_separately": "o200k_base tokens, each span encoded separately",
}
PATTERNS = {
    "iso_timestamp_prefix": re.compile(r"(?m)^\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\]?\s*"),
    "ansi_escape": re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]"),
    "carriage_return": re.compile(r"\r"),
    "percentage_progress_line": re.compile(r"(?m)^.*\b\d{1,3}%.*$"),
    "package_install_line": re.compile(r"(?mi)^(?:Collecting |Downloading |Installing |Successfully installed |Setting up |Unpacking |Get:\d|Hit:\d|Fetched |Reading package lists).*$"),
    "unix_long_listing_line": re.compile(r"(?m)^[dl-][rwxstST-]{9}[+@]?\s+\d+\s+\S+\s+\S+\s+\d+\s+.*$"),
    "absolute_path_line": re.compile(r"(?m)^/[^\r\n]+$"),
}


def prepare_tokenizer(cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / TOKENIZER_FILE
    if target.exists():
        if digest(target.read_bytes()) != TOKENIZER_SHA256:
            raise ValueError("Existing tokenizer cache has the wrong SHA-256; it was not overwritten")
        return target
    with urllib.request.urlopen(TOKENIZER_URL, timeout=30) as response:
        content = response.read(8_000_001)
    if digest(content) != TOKENIZER_SHA256:
        raise ValueError("Downloaded tokenizer table differs from the pinned SHA-256")
    with target.open("xb") as handle:
        handle.write(content)
    return target


def load_encoder(configuration: dict):
    if importlib.metadata.version("tiktoken") != configuration["tiktoken_version"]:
        raise ValueError("tiktoken version differs from the ledger; run uv sync --locked")
    cache_value = os.environ.get(configuration["cache_env"])
    if not cache_value:
        raise ValueError(f"Set {configuration['cache_env']} to an already prepared tokenizer cache")
    cache = Path(cache_value).resolve()
    table = cache / TOKENIZER_FILE
    if not table.is_file() or digest(table.read_bytes()) != configuration["table_sha256"]:
        raise ValueError("Tokenizer table missing or changed; use static --prepare-tokenizer before measurement")
    os.environ["TIKTOKEN_CACHE_DIR"] = str(cache)
    import tiktoken

    return tiktoken.get_encoding(configuration["tokenizer"])


def token_count(text: str, encoder) -> int:
    return len(encoder.encode(text, disallowed_special=()))


def counts(payload: dict, candidates: list[str], encoder) -> dict:
    contents = [message["content"] for message in payload["messages"]]
    return {
        "message_content_utf8_bytes": sum(len(text.encode("utf-8")) for text in contents),
        "message_content_tokens": sum(token_count(text, encoder) for text in contents),
        "candidate_utf8_bytes": sum(len(text.encode("utf-8")) for text in candidates),
        "candidate_tokens_separately": sum(token_count(text, encoder) for text in candidates),
    }


def percent(saved: int, original: int) -> float | None:
    return 100.0 * saved / original if original else None


def reductions(before: dict, after: dict) -> dict:
    return {
        "kind": "calculated", "source": "measured_local.before_minus_after",
        "saved": {name: before[name] - after[name] for name in UNITS},
        "saved_percent": {name: percent(before[name] - after[name], before[name]) for name in UNITS},
        "units": UNITS,
    }


def billed_unavailable() -> dict:
    return {
        "kind": "unavailable", "status": "not_measured", "source": "no_provider_calls",
        "input_tokens": None, "cached_input_tokens": None, "output_tokens": None,
        "cost_usd": None, "token_unit": "provider_usage_tokens", "cost_unit": "USD",
    }


def pattern_counts(text: str) -> dict:
    text = re.sub(r"(?m)^(?:# squeez \[|\[squeez:)[^\n]*(?:\n|$)", "", text)
    lines = Counter(line for line in text.splitlines() if line.strip())
    return {
        **{name: len(pattern.findall(text)) for name, pattern in PATTERNS.items()},
        "duplicate_nonempty_line_excess": sum(count - 1 for count in lines.values()),
    }


def pattern_observation(before: str, after: str) -> dict:
    original_lines = Counter(before.splitlines(keepends=True))
    output_lines = Counter(after.splitlines(keepends=True))
    missing_lines = list((original_lines - output_lines).elements())
    return {
        "kind": "classification", "method": "regex_counts_and_exact_line_multiset_difference",
        "before": pattern_counts(before), "after": pattern_counts(after),
        "original_lines_not_retained_verbatim": len(missing_lines),
        "original_line_bytes_not_retained_verbatim": sum(len(line.encode("utf-8")) for line in missing_lines),
        "changed": before != after,
        "does_not_prove": "Missing verbatim lines may be rewritten, summarized or removed; pattern counts do not establish the compressor's internal rule or semantic safety.",
    }
