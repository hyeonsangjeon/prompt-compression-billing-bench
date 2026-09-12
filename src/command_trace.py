"""Observe actual terminal submissions without counting replayed chat history."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .protection import digest


def shell_parts(command: str) -> tuple[list[str], list[str]]:
    text = command.strip()
    if not text or any(character in text for character in ("\n", "\r", "`", "$", "<", ">", "\\")):
        return [], []
    units, separators, quote, start, index = [], [], None, 0, 0
    while index < len(text):
        character = text[index]
        if quote:
            if character == quote:
                quote = None
        elif character in ("'", '"'):
            quote = character
        elif character in "(){}":
            return [], []
        elif character in "&|;":
            separator = text[index:index + 2]
            width = 2 if separator in ("&&", "||") else 1
            if character == "&" and width == 1:
                return [], []
            unit = text[start:index].strip()
            if not unit:
                return [], []
            units.append(unit)
            separators.append(text[index:index + width])
            index += width
            start = index
            continue
        index += 1
    if quote or not text[start:].strip():
        return [], []
    return [*units, text[start:].strip()], separators


def shell_units(command: str) -> list[str]:
    return shell_parts(command)[0]


def submission_kind(keystrokes: str) -> str:
    if not keystrokes.strip():
        return "wait"
    if not keystrokes.endswith("\n") or any(ord(character) < 32 and character not in "\n\r\t" for character in keystrokes):
        return "terminal_input_not_complete_command"
    return "command_block"


class CommandTrace:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=False)
        self.events = directory / "events.jsonl"
        self.events.touch(mode=0o600)
        self.sequence = 0
        self.batch = 0
        self.observation = 0

    def append(self, event: dict) -> None:
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **event}, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def session(self, original):
        self.batch += 1
        return TracedSession(original, self)


class TracedSession:
    def __init__(self, original, trace: CommandTrace):
        self.original, self.trace = original, trace

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def send_keys(self, keystrokes, *arguments, **keywords):
        self.trace.sequence += 1
        identifier = self.trace.sequence
        self.trace.append({
            "event": "submission_started", "command_id": identifier, "batch": self.trace.batch,
            "keystrokes": keystrokes, "command_sha256": digest(keystrokes.encode()),
            "submission_kind": submission_kind(keystrokes), "shell_units": shell_units(keystrokes),
        })
        try:
            result = await self.original.send_keys(keystrokes, *arguments, **keywords)
        except BaseException as error:
            self.trace.append({"event": "submission_finished", "command_id": identifier,
                               "status": "uncertain", "error_type": type(error).__name__})
            raise
        self.trace.append({"event": "submission_finished", "command_id": identifier, "status": "accepted_by_terminal"})
        return result

    async def get_incremental_output(self, *arguments, **keywords):
        output = await self.original.get_incremental_output(*arguments, **keywords)
        self.trace.observation += 1
        path = self.trace.directory / f"terminal-{self.trace.observation:05d}.txt"
        content = output.encode()
        path.write_bytes(content)
        self.trace.append({
            "event": "terminal_observation_before_harbor_limit", "batch": self.trace.batch,
            "path": path.name, "sha256": digest(content), "utf8_bytes": len(content),
        })
        return output
