"""Fail closed when a transformation changes a designated protected span."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json


class ProtectionViolation(RuntimeError):
    pass


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


class FrozenRequestGuard:
    def __init__(self, source: bytes, source_sha256: str, segments: list[dict]):
        self.failure = None
        self._expected = None
        self._source_sha256 = source_sha256
        self._segments = deepcopy(segments)
        self.candidate_count = 0
        self.candidate_bytes = 0
        self.protected_count = 0
        self.protected_bytes = 0
        if digest(source) != source_sha256:
            self._fail("Original request hash differs from the frozen manifest")
        try:
            self._original = json.loads(source)
            canonical(self._original)
            messages = self._original["messages"]
            if not isinstance(messages, list) or not messages:
                self._fail("A nonempty message list is required")
            grouped = defaultdict(list)
            for segment in self._segments:
                message_index = segment["message_index"]
                if type(message_index) is not int or not 0 <= message_index < len(messages):
                    self._fail("Invalid message index")
                grouped[message_index].append(segment)
            for message_index, message in enumerate(messages):
                content = message["content"]
                if not isinstance(content, str):
                    self._fail("Only fully partitioned text messages are supported")
                position = 0
                for segment in grouped[message_index]:
                    start, end = segment["char_start"], segment["char_end"]
                    if type(start) is not int or type(end) is not int:
                        self._fail("Segment offsets must be integer character offsets")
                    if start != position or not start < end <= len(content):
                        self._fail("Segments overlap, leave a gap, or exceed the message")
                    piece = content[start:end].encode("utf-8")
                    if digest(piece) != segment["sha256"] or len(piece) != segment["utf8_bytes"]:
                        self._fail("Segment content differs from the frozen manifest")
                    if type(segment["candidate"]) is not bool:
                        self._fail("Candidate labels must be explicit booleans")
                    if segment["candidate"]:
                        if segment["category"] != "log" or message_index == 0 or message["role"] != "user":
                            self._fail("Only classified observation logs may be transformed")
                        self.candidate_count += 1
                        self.candidate_bytes += len(piece)
                    else:
                        self.protected_count += 1
                        self.protected_bytes += len(piece)
                    position = end
                if position != len(content):
                    self._fail("A message is not completely covered by the manifest")
            self._grouped = dict(grouped)
        except (KeyError, TypeError, ValueError) as error:
            self._fail(f"Malformed frozen request or manifest: {type(error).__name__}")

    def _fail(self, reason: str):
        self.failure = reason
        raise ProtectionViolation(reason)

    def _check_latch(self):
        if self.failure is not None:
            raise ProtectionViolation(f"Request remains stopped: {self.failure}")

    def candidate_texts(self) -> list[str]:
        self._check_latch()
        return [
            message["content"][segment["char_start"]:segment["char_end"]]
            for message_index, message in enumerate(self._original["messages"])
            for segment in self._grouped.get(message_index, [])
            if segment["candidate"]
        ]

    def prepare(self, replacements: list[str] | None = None) -> dict:
        self._check_latch()
        if self._expected is not None:
            self._fail("A guard is bound to exactly one transformation")
        if replacements is not None and (
            not isinstance(replacements, list)
            or len(replacements) != self.candidate_count
            or any(not isinstance(value, str) for value in replacements)
        ):
            self._fail("Exactly one string per candidate segment is required")
        transformed = deepcopy(self._original)
        replacement_index = 0
        for message_index, message in enumerate(self._original["messages"]):
            pieces = []
            for segment in self._grouped.get(message_index, []):
                piece = message["content"][segment["char_start"]:segment["char_end"]]
                if segment["candidate"] and replacements is not None:
                    piece = replacements[replacement_index]
                    replacement_index += 1
                pieces.append(piece)
            transformed["messages"][message_index]["content"] = "".join(pieces)
        self._expected = canonical(transformed)
        return transformed

    def verify(self, transformed: dict) -> dict:
        self._check_latch()
        if self._expected is None:
            self._fail("No transformation has been prepared")
        try:
            observed = canonical(transformed)
        except (TypeError, ValueError):
            self._fail("Transformed payload is not valid JSON")
        if observed != self._expected:
            self._fail("Protected content, message structure, settings, or approved edits changed")
        return {
            "source_sha256": self._source_sha256,
            "transformed_canonical_sha256": digest(observed),
            "candidate_segments": self.candidate_count,
            "candidate_utf8_bytes": self.candidate_bytes,
            "protected_segments": self.protected_count,
            "protected_utf8_bytes": self.protected_bytes,
        }

    def forward(self, transformed: dict, sender):
        outgoing = deepcopy(transformed)
        self.verify(outgoing)
        return sender(outgoing)


class RunProtectionGate:
    def __init__(self):
        self.failure = None

    def forward(self, guard: FrozenRequestGuard, transformed: dict, sender):
        if self.failure is not None:
            raise ProtectionViolation(f"Run remains stopped: {self.failure}")
        try:
            return guard.forward(transformed, sender)
        except ProtectionViolation as error:
            self.failure = str(error)
            raise
