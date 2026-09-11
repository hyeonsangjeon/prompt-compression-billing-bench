"""One frozen-observation path for every compressor, including no-op."""

from __future__ import annotations

from .compressors import Compressor
from .protection import FrozenRequestGuard, ProtectionViolation, RunProtectionGate


class ObservationPipeline:
    def __init__(self, compressor: Compressor):
        self.compressor = compressor
        self.gate = RunProtectionGate()
        self.failure = None

    def transform(self, source: bytes, source_sha256: str, segments: list[dict]):
        if self.failure is not None:
            raise ProtectionViolation("The observation pipeline remains stopped")
        try:
            guard = FrozenRequestGuard(source, source_sha256, segments)
            originals = guard.candidate_texts()
            compressed = [self.compressor.compress(text) for text in originals]
            transformed = guard.prepare([result.text for result in compressed])
            checked = guard.verify(transformed)
            forwarded = self.gate.forward(guard, transformed, lambda payload: payload)
            return forwarded, checked, originals, compressed
        except Exception as error:
            self.failure = type(error).__name__
            raise
