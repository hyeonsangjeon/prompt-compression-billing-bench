"""Protect unknown, mixed, code and structured output in new native requests."""

import json
import re
import shlex

from .command_trace import shell_parts
from .protection import digest


POLICY = "echo_bound_terminal_logs_v2"
PROMPT = re.compile(r"(?m)^[A-Za-z_][\w-]*@[a-f0-9]{12}:[^\n#$]*[#$] ?(?P<command>[^\n]*)(?:\n|$)")
CODE_OR_STRUCTURE = re.compile(
    r"(?m)^\s*(?:[{}\[\]]|---\s*$|diff --git |@@ |(?:def|class|import|from|function|const|let|var|package|func)\s|[\w.-]+\s*[:=]\s)"
)
HARBOR_OMISSION = re.compile(r"(?m)^\[\.\.\. output limited to \d+ bytes; \d+ interior bytes omitted \.\.\.\]$")
VERSIONS = {
    "python": {"--version", "-V"}, "python3": {"--version", "-V"},
    "pip": {"--version", "-V"}, "pip3": {"--version", "-V"},
    "node": {"--version", "-v"}, "npm": {"--version", "-v"},
    "git": {"--version", "version"}, "nginx": {"-v", "-V"},
    "openssl": {"version"}, "bash": {"--version"},
}


def simple_kind(command: str) -> str | None:
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if not words:
        return None
    program = words[0]
    if len(words) == 2 and words[1] in VERSIONS.get(program, set()):
        return "version"
    if program == "ls" and all(not word.startswith("--") or word == "--" for word in words[1:]):
        return "file_list"
    if program == "find":
        options = {"-type", "-name", "-iname", "-maxdepth", "-mindepth", "-print"}
        if all(not word.startswith("-") or word in options for word in words[1:]):
            return "file_list"
    if program in ("apt", "apt-get") and len(words) > 1 and words[1] in ("update", "install"):
        return "installation"
    if program in ("head", "tail"):
        remaining = words[1:]
        if remaining[:1] == ["-n"] and len(remaining) > 1 and remaining[1].isdigit():
            remaining = remaining[2:]
        elif remaining and re.fullmatch(r"-\d+", remaining[0]):
            remaining = remaining[1:]
        if remaining and all(not word.startswith("-") and word.endswith(".log") for word in remaining):
            return "task_log"
    if program == "grep" and len(words) == 3 and not words[1].startswith("-") and not words[2].startswith("-") and words[2].endswith(".log"):
        return "task_log"
    return None


def command_kind(command: str) -> str | None:
    units, separators = shell_parts(command)
    if not units or any(character in command for character in ("\n", "\r")):
        return None
    if len(units) == 1:
        return simple_kind(units[0])
    kinds = [simple_kind(unit) for unit in units]
    if all(kind == "installation" for kind in kinds) and all(separator == "&&" for separator in separators):
        return "installation"
    for index, unit in enumerate(units):
        if unit == "sort" or re.fullmatch(r"sed -n ['\"]1,\d+p['\"]", unit):
            kinds[index] = "file_list" if index and separators[index - 1] == "|" and kinds[index - 1] == "file_list" else None
    if all(kind == "file_list" for kind in kinds) and all(separator in ("&&", "|") for separator in separators):
        return "file_list"
    return None


def candidate_ranges(content: str, assistant: str) -> list[dict]:
    try:
        commands = json.loads(assistant)["commands"]
        if not isinstance(commands, list):
            return []
        sent = [command["keystrokes"] for command in commands]
        if any(not isinstance(command, str) for command in sent):
            return []
    except (ValueError, KeyError, TypeError):
        return []
    prompts = list(PROMPT.finditer(content))
    ranges, consumed = [], -1
    for first, following in zip(prompts, prompts[1:]):
        command = first["command"]
        matching = [index for index in range(consumed + 1, len(sent)) if sent[index] == command + "\n"]
        if not matching:
            continue
        consumed = matching[0]
        kind = command_kind(command)
        start, end = first.end(), following.start()
        body = content[start:end]
        if kind is None or not body.strip() or "\x1b" in body or CODE_OR_STRUCTURE.search(HARBOR_OMISSION.sub("", body)):
            continue
        if kind == "task_log" and not all(
            re.match(r"(?:[^\s:]+\.log:)?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}.*\b(?:ERROR|WARNING|INFO|DEBUG|WARN|CRITICAL)\b", line)
            for line in body.splitlines() if line.strip()
        ):
            continue
        ranges.append({"start": start, "end": end, "output_kind": kind, "echoed_command": command,
                       "source_assistant_sha256": digest(assistant.encode()), "command_index": consumed})
    return ranges


def partition(payload: dict, known_assistant_hashes: set[str]) -> list[dict]:
    segments = []
    for message_index, message in enumerate(payload["messages"]):
        content = message["content"]
        if not isinstance(content, str):
            raise ValueError("Live observations only support text message content")
        ranges = []
        if message_index and message["role"] == "user":
            preceding = payload["messages"][message_index - 1]
            assistant = preceding.get("content")
            if preceding.get("role") == "assistant" and isinstance(assistant, str) and digest(assistant.encode()) in known_assistant_hashes:
                ranges = candidate_ranges(content, assistant)
        intervals, position = [], 0
        for candidate in ranges:
            intervals.extend([(position, candidate["start"], False, {}), (candidate["start"], candidate["end"], True, candidate)])
            position = candidate["end"]
        intervals.append((position, len(content), False, {}))
        for start, end, candidate, details in intervals:
            if start == end:
                continue
            piece = content[start:end].encode()
            segments.append({
                "message_index": message_index, "char_start": start, "char_end": end,
                "utf8_bytes": len(piece), "sha256": digest(piece), "candidate": candidate,
                "category": "log" if candidate else "protected",
                "classification_policy": POLICY, "source_message_sha256": digest(content.encode()),
                **{key: value for key, value in details.items() if key not in ("start", "end")},
            })
    return segments
