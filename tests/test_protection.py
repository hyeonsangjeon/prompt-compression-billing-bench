import copy
import json
import unittest
from unittest.mock import Mock

from src.compressors import NoOpCompressor
from src.pipeline import ObservationPipeline
from src.protection import FrozenRequestGuard, ProtectionViolation, RunProtectionGate, digest


def fixture():
    pieces = ["Observation:\n", "def keep_code():\n    return 'α'\n", "INFO complete\nINFO complete\n", "End observation."]
    payload = {
        "model": "synthetic-not-called", "temperature": 0, "reasoning_effort": "none",
        "messages": [
            {"role": "user", "content": "Keep the complete instruction."},
            {"role": "assistant", "content": "Do not change this code: print('α')"},
            {"role": "user", "content": "".join(pieces)},
        ],
    }
    segments = []
    for message_index, message in enumerate(payload["messages"]):
        chunks = pieces if message_index == 2 else [message["content"]]
        offset = 0
        for chunk_index, content in enumerate(chunks):
            candidate = message_index == 2 and chunk_index == 2
            segments.append({
                "message_index": message_index, "char_start": offset, "char_end": offset + len(content),
                "utf8_bytes": len(content.encode("utf-8")), "sha256": digest(content.encode("utf-8")),
                "category": "log" if candidate else "code_mixed", "candidate": candidate,
            })
            offset += len(content)
    source = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return source, segments, payload


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.source, self.segments, self.original = fixture()

    def guard(self, segments=None):
        return FrozenRequestGuard(self.source, digest(self.source), segments if segments is not None else self.segments)

    def test_noop_takes_the_same_candidate_adapter_path(self):
        compressor = NoOpCompressor({"options": {}}, None)
        compressor.compress = Mock(wraps=compressor.compress)
        pipeline = ObservationPipeline(compressor)
        transformed, checked, originals, compressed = pipeline.transform(self.source, digest(self.source), self.segments)
        self.assertEqual(transformed, self.original)
        self.assertEqual(originals, [result.text for result in compressed])
        compressor.compress.assert_called_once_with("INFO complete\nINFO complete\n")
        self.assertEqual(checked["candidate_segments"], 1)
        self.assertEqual(checked["protected_segments"], 5)

    def test_only_candidate_text_can_be_replaced_or_deleted(self):
        for replacement in ("short log", "", "expanded log\n" * 40):
            with self.subTest(replacement=replacement):
                guard = self.guard()
                transformed = guard.prepare([replacement])
                guard.verify(transformed)
                self.assertEqual(transformed["messages"][:2], self.original["messages"][:2])
                expected = self.original["messages"][2]["content"].replace("INFO complete\nINFO complete\n", replacement)
                self.assertEqual(transformed["messages"][2]["content"], expected)
                self.assertEqual(transformed["temperature"], 0)

    def test_mutations_never_reach_sender_and_latch_run(self):
        mutations = [
            lambda payload: payload["messages"][0].update(content="changed instruction"),
            lambda payload: payload["messages"][1].update(content="changed code"),
            lambda payload: payload["messages"][2].update(role="tool"),
            lambda payload: payload["messages"].reverse(),
            lambda payload: payload.update(temperature=0.1),
            lambda payload: payload.update(reasoning_effort="low"),
            lambda payload: payload["messages"].append({"role": "user", "content": "extra"}),
            lambda payload: payload["messages"][2].update(content="missing protected code"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                gate = RunProtectionGate()
                guard = self.guard()
                transformed = guard.prepare(["log"])
                mutation(transformed)
                sender = Mock()
                with self.assertRaises(ProtectionViolation):
                    gate.forward(guard, transformed, sender)
                another = self.guard()
                with self.assertRaises(ProtectionViolation):
                    gate.forward(another, another.prepare(["valid"]), sender)
                sender.assert_not_called()

    def test_source_partition_and_code_labels_fail_closed(self):
        mutations = [
            lambda parts: parts.pop(),
            lambda parts: parts[3].update(char_start=0),
            lambda parts: parts[4].update(char_end=99999),
            lambda parts: parts[4].update(sha256="a" * 64),
            lambda parts: parts[4].update(utf8_bytes=1),
            lambda parts: parts[4].update(candidate=1),
            lambda parts: parts[4].update(category="code"),
            lambda parts: parts[4].update(category="code_mixed"),
            lambda parts: parts[0].update(candidate=True, category="log"),
            lambda parts: parts[1].update(candidate=True, category="log"),
            lambda parts: parts.reverse(),
        ]
        for mutation in mutations:
            parts = copy.deepcopy(self.segments)
            mutation(parts)
            with self.subTest(mutation=mutation), self.assertRaises(ProtectionViolation):
                self.guard(parts)
        with self.assertRaises(ProtectionViolation):
            FrozenRequestGuard(self.source + b" ", digest(self.source), self.segments)

    def test_manifest_is_copied_and_guard_is_one_shot(self):
        guard = self.guard()
        self.segments[0]["candidate"] = True
        transformed = guard.prepare(["log"])
        guard.verify(transformed)
        with self.assertRaises(ProtectionViolation):
            guard.prepare(["second edit"])
        with self.assertRaises(ProtectionViolation):
            guard.verify(transformed)

    def test_pipeline_latches_manifest_and_adapter_failures(self):
        compressor = NoOpCompressor({"options": {}}, None)
        pipeline = ObservationPipeline(compressor)
        with self.assertRaises(ProtectionViolation):
            pipeline.transform(self.source, "a" * 64, self.segments)
        with self.assertRaises(ProtectionViolation):
            pipeline.transform(self.source, digest(self.source), self.segments)
        compressor.compress = Mock(side_effect=RuntimeError("synthetic adapter failure"))
        pipeline = ObservationPipeline(compressor)
        with self.assertRaises(RuntimeError):
            pipeline.transform(self.source, digest(self.source), self.segments)
        with self.assertRaises(ProtectionViolation):
            pipeline.transform(self.source, digest(self.source), self.segments)
        compressor.compress.assert_called_once()

    def test_invalid_replacements_and_unprepared_forward_fail(self):
        for replacements in ([], [1], ["first", "second"], "not a list"):
            with self.subTest(replacements=replacements), self.assertRaises(ProtectionViolation):
                self.guard().prepare(replacements)
        sender = Mock()
        with self.assertRaises(ProtectionViolation):
            self.guard().forward(self.original, sender)
        sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
