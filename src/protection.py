"""Fail closed when a transformation changes a designated protected span."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json


class ProtectionViolation(RuntimeError):
    def __init__(self, reason: str, details: dict | None = None):
        super().__init__(reason)
        self.details = {"reason": reason, **(details or {})}


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def parse_request(source: bytes) -> dict:
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    payload = json.loads(source, object_pairs_hook=unique_fields)
    if not isinstance(payload, dict):
        raise ValueError("Request must be a JSON object")
    canonical(payload)
    return payload


def changed_fields(expected, actual, path=()):
    if type(expected) is type(actual) and expected == actual:
        return []
    if isinstance(expected, dict) and isinstance(actual, dict):
        changes = []
        for key in sorted(expected.keys() | actual.keys()):
            if key not in expected or key not in actual:
                changes.append({"path": [*path, key], "change": "added" if key in actual else "removed"})
            else:
                changes.extend(changed_fields(expected[key], actual[key], (*path, key)))
        return changes
    if isinstance(expected, list) and isinstance(actual, list):
        changes = []
        for index in range(max(len(expected), len(actual))):
            if index >= len(expected) or index >= len(actual):
                changes.append({"path": [*path, index], "change": "added" if index < len(actual) else "removed"})
            else:
                changes.extend(changed_fields(expected[index], actual[index], (*path, index)))
        return changes
    change = {
        "path": list(path), "change": "replaced",
        "expected_sha256": digest(canonical(expected)), "actual_sha256": digest(canonical(actual)),
    }
    if isinstance(expected, str) and isinstance(actual, str):
        prefix = 0
        while prefix < min(len(expected), len(actual)) and expected[prefix] == actual[prefix]:
            prefix += 1
        suffix = 0
        while suffix < min(len(expected), len(actual)) - prefix and expected[-suffix - 1] == actual[-suffix - 1]:
            suffix += 1
        expected_end, actual_end = len(expected) - suffix, len(actual) - suffix
        change.update(first_difference_char=prefix, expected_changed_end=expected_end,
                      actual_changed_end=actual_end,
                      removed_chars=expected_end - prefix, inserted_chars=actual_end - prefix)
        if expected_end == prefix:
            change["change"] = "inserted_text"
        elif actual_end == prefix:
            change["change"] = "deleted_text"
    return [change]


class FrozenRequestGuard:
    def __init__(self, source: bytes, source_sha256: str, segments: list[dict]):
        self.failure = None
        self.failure_details = None
        self._expected = None
        self._expected_payload = None
        self._output_segments = []
        self._source_sha256 = source_sha256
        self._segments = deepcopy(segments)
        self.candidate_count = 0
        self.candidate_bytes = 0
        self.protected_count = 0
        self.protected_bytes = 0
        if digest(source) != source_sha256:
            self._fail("Original request hash differs from the frozen manifest")
        try:
            self._original = parse_request(source)
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

    def _fail(self, reason: str, details: dict | None = None):
        self.failure = reason
        self.failure_details = details or {}
        raise ProtectionViolation(reason, self.failure_details)

    def _check_latch(self):
        if self.failure is not None:
            raise ProtectionViolation(f"Request remains stopped: {self.failure}", self.failure_details)

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
            output_position = 0
            for segment in self._grouped.get(message_index, []):
                piece = message["content"][segment["char_start"]:segment["char_end"]]
                if segment["candidate"] and replacements is not None:
                    piece = replacements[replacement_index]
                    replacement_index += 1
                pieces.append(piece)
                self._output_segments.append({
                    **segment, "output_char_start": output_position,
                    "output_char_end": output_position + len(piece),
                })
                output_position += len(piece)
            transformed["messages"][message_index]["content"] = "".join(pieces)
        self._expected = canonical(transformed)
        self._expected_payload = deepcopy(transformed)
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
            changes = changed_fields(self._expected_payload, transformed)
            for change in changes:
                path = change["path"]
                if len(path) == 3 and path[0] == "messages" and path[2] == "content":
                    start = change.get("first_difference_char", 0)
                    end = change.get("expected_changed_end", float("inf"))
                    change["affected_segments"] = [
                        segment for segment in self._output_segments
                        if segment["message_index"] == path[1]
                        and segment["output_char_start"] <= end
                        and segment["output_char_end"] >= start
                    ]
            self._fail("Protected content, message structure, settings, or approved edits changed", {
                "source_sha256": self._source_sha256,
                "expected_canonical_sha256": digest(self._expected),
                "actual_canonical_sha256": digest(observed), "changes": changes,
            })
        return {
            "source_sha256": self._source_sha256,
            "transformed_canonical_sha256": digest(observed),
            "candidate_segments": self.candidate_count,
            "candidate_utf8_bytes": self.candidate_bytes,
            "protected_segments": self.protected_count,
            "protected_utf8_bytes": self.protected_bytes,
        }

    def verify_serialized(self, source: bytes) -> dict:
        self._check_latch()
        try:
            payload = parse_request(source)
        except (TypeError, ValueError, UnicodeError):
            self._fail("Outbound request is not unambiguous JSON", {"outbound_sha256": digest(source)})
        return self.verify(payload)

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
