from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import platform
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from native_helpers import ledger_fixture
from src.compressors import CompressorError, HeadroomPathsCompressor, LLMLingua2Compressor
from src.protection import digest


def file_record(path: Path) -> dict:
    return {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}


class HeadroomAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.module = self.root / "lossless_compaction.py"
        self.module.write_text(
            "def compact_lossless(text, kind):\n"
            "    if kind != 'paths': return text\n"
            "    lines = text.splitlines(keepends=True)\n"
            "    if lines == ['/long/shared/first.log\\n', '/long/shared/second.log\\n']:\n"
            "        return '/long/shared/\\nfirst.log\\nsecond.log\\n'\n"
            "    return text\n"
            "def path_unheading(text):\n"
            "    if text == '/long/shared/\\nfirst.log\\nsecond.log\\n':\n"
            "        return '/long/shared/first.log\\n/long/shared/second.log\\n'\n"
            "    return text\n",
            encoding="utf-8",
        )
        self.specification = deepcopy(ledger_fixture()["compressor"]["tools"]["headroom"])
        self.specification["module_sha256"] = digest(self.module.read_bytes())

    def test_paths_only_profile_is_smaller_and_byte_reversible(self):
        with patch.dict(os.environ, {"HEADROOM_LOSSLESS_MODULE": str(self.module)}):
            compressor = HeadroomPathsCompressor(self.specification, self.root / "artifacts")
            result = compressor.compress("/long/shared/first.log\n/long/shared/second.log\n")
            unchanged = compressor.compress("2025-01-01 [ERROR] failed\n")
        self.assertEqual(result.text, "/long/shared/\nfirst.log\nsecond.log\n")
        self.assertEqual(result.tool_reported["method"], "paths")
        self.assertTrue(result.tool_reported["roundtrip_byte_exact"])
        self.assertEqual(unchanged.text, "2025-01-01 [ERROR] failed\n")
        self.assertEqual(unchanged.tool_reported["method"], "identity")

    def test_module_hash_and_inverse_fail_closed(self):
        changed = deepcopy(self.specification)
        changed["module_sha256"] = "0" * 64
        with patch.dict(os.environ, {"HEADROOM_LOSSLESS_MODULE": str(self.module)}), self.assertRaises(CompressorError):
            HeadroomPathsCompressor(changed, self.root / "hash-failure")
        self.module.write_text(self.module.read_text().replace("return '/long/shared/first.log", "return '/wrong"))
        changed["module_sha256"] = digest(self.module.read_bytes())
        with patch.dict(os.environ, {"HEADROOM_LOSSLESS_MODULE": str(self.module)}), self.assertRaises(CompressorError):
            HeadroomPathsCompressor(changed, self.root / "inverse-failure")


class LLMLinguaAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.worker = self.root / "worker.py"
        self.worker.write_text(
            "import json, sys, time\n"
            "def receive(): return json.loads(sys.stdin.readline())\n"
            "def emit(value): print(json.dumps(value), flush=True)\n"
            "initial = receive(); spec = initial['specification']\n"
            "files = lambda rows: [{'name': n, 'bytes': r['bytes'], 'sha256': r['sha256']} for n, r in rows.items()]\n"
            "emit({'operation':'initialized','ok':True,'runtime':{'python':spec['python_version']},"
            "'model_files':files(spec['model_files']),'tokenizer_cache_files':files(spec['tokenizer_cache_files']),"
            "'model_id':spec['model_id'],'model_revision':spec['model_revision'],'profile':spec['profile'],'load_seconds':0.01})\n"
            "while True:\n"
            "    request = receive()\n"
            "    if request == {'operation':'close'}:\n"
            "        emit({'operation':'closed','ok':True}); break\n"
            "    time.sleep(0.03)\n"
            "    text = request['text'] if str(request['id']).startswith('fixture-') else request['text'].upper()\n"
            "    emit({'operation':'compressed','ok':True,'id':request['id'],'text':text,'inference_seconds':0.02,"
            "'tool_reported':{'kind':'tool_reported','status':'reported','not_provider_usage':True}})\n",
            encoding="utf-8",
        )
        self.requirements = self.root / "requirements.txt"
        self.requirements.write_text("synthetic==1\n", encoding="utf-8")
        self.model = self.root / "model"
        self.cache = self.root / "cache"
        self.model.mkdir()
        self.cache.mkdir()
        (self.model / "weights").write_text("model", encoding="utf-8")
        (self.cache / "tokens").write_text("tokens", encoding="utf-8")
        self.fixture = self.root / "fixture.txt"
        self.fixture.write_text("fixture text\n", encoding="utf-8")
        self.specification = deepcopy(ledger_fixture()["compressor"]["tools"]["llmlingua2"])
        self.specification.update({
            "python_version": platform.python_version(), "worker_path": str(self.worker),
            "worker_sha256": digest(self.worker.read_bytes()), "requirements_path": str(self.requirements),
            "requirements_sha256": digest(self.requirements.read_bytes()),
            "model_files": {"weights": file_record(self.model / "weights")},
            "tokenizer_cache_files": {"tokens": file_record(self.cache / "tokens")},
            "fixtures": [{"name": "synthetic", "path": str(self.fixture),
                          "input_sha256": digest(self.fixture.read_bytes()),
                          "output_sha256": digest(self.fixture.read_bytes())}],
        })
        self.environment = {
            "LLMLINGUA_PYTHON": sys.executable,
            "LLMLINGUA_MODEL": str(self.model),
            "TIKTOKEN_CACHE_DIR": str(self.cache),
        }

    def test_eight_workers_run_in_parallel_and_identify_each_worker(self):
        with patch.dict(os.environ, self.environment):
            compressor = LLMLingua2Compressor(self.specification, self.root / "artifacts")
            barrier = threading.Barrier(8)

            def compress(source):
                barrier.wait(timeout=2)
                return compressor.compress(source)

            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(compress, [f"input-{index}" for index in range(8)]))
            elapsed = time.monotonic() - started
            compressor.close()
        self.assertEqual([result.text for result in results], [f"INPUT-{index}" for index in range(8)])
        self.assertEqual(compressor.calls, 8)
        self.assertLess(elapsed, 0.2)
        self.assertEqual({result.audit["worker_id"] for result in results}, set(range(1, 9)))
        self.assertEqual([result.telemetry["worker_inference_seconds"] for result in results], [0.02] * 8)
        self.assertEqual(len(compressor.metadata["determinism_probes"]), 8)
        self.assertEqual(compressor.metadata["worker_pool"]["size"], 8)

    def test_ninth_call_records_worker_pool_wait(self):
        with patch.dict(os.environ, self.environment):
            compressor = LLMLingua2Compressor(self.specification, self.root / "wait-artifacts")
            barrier = threading.Barrier(9)

            def compress(source):
                barrier.wait(timeout=2)
                return compressor.compress(source)

            with ThreadPoolExecutor(max_workers=9) as executor:
                results = list(executor.map(compress, [f"input-{index}" for index in range(9)]))
            compressor.close()
        self.assertGreater(max(result.telemetry["serialization_wait_seconds"] for result in results), 0.01)

    def test_input_over_5000_characters_is_compressed_once_and_suffix_is_audited(self):
        source = "a" * 5000 + "discarded"
        with patch.dict(os.environ, self.environment):
            compressor = LLMLingua2Compressor(self.specification, self.root / "cap-artifacts")
            result = compressor.compress(source)
            compressor.close()
        self.assertEqual(result.text, "A" * 5000)
        self.assertEqual(result.audit["source"]["characters"], 5009)
        self.assertEqual(result.audit["worker_input"]["characters"], 5000)
        self.assertEqual(result.audit["discarded_suffix"]["characters"], 9)
        self.assertTrue(result.audit["overflow_applied"])
        self.assertEqual((self.root / "cap-artifacts/span-00001/discarded-suffix.txt").read_text(), "discarded")

    def test_input_at_cap_has_no_discarded_suffix_artifact(self):
        with patch.dict(os.environ, self.environment):
            compressor = LLMLingua2Compressor(self.specification, self.root / "exact-cap-artifacts")
            result = compressor.compress("a" * 5000)
            compressor.close()
        self.assertFalse(result.audit["overflow_applied"])
        self.assertIsNone(result.audit["discarded_suffix_artifact"])
        self.assertFalse((self.root / "exact-cap-artifacts/span-00001/discarded-suffix.txt").exists())

    def test_fixture_mismatch_stops_before_live_compression(self):
        self.specification["fixtures"][0]["output_sha256"] = hashlib.sha256(b"different").hexdigest()
        with patch.dict(os.environ, self.environment), self.assertRaisesRegex(CompressorError, "fixture changed"):
            LLMLingua2Compressor(self.specification, self.root / "failed")

    def test_cross_worker_fixture_mismatch_stops_initialization(self):
        source = self.worker.read_text(encoding="utf-8").replace(
            "text = request['text'] if str(request['id']).startswith('fixture-') else request['text'].upper()",
            "text = request['text'] if str(request['id']).startswith('fixture-') else request['text'].upper()\n"
            "    if str(request['id']).startswith('fixture-08-'): text += 'different'",
        )
        self.worker.write_text(source, encoding="utf-8")
        self.specification["worker_sha256"] = digest(self.worker.read_bytes())
        with patch.dict(os.environ, self.environment), self.assertRaisesRegex(CompressorError, "cross-worker"):
            LLMLingua2Compressor(self.specification, self.root / "cross-worker-failure")

    def test_close_handshake_failure_is_not_silently_accepted(self):
        source = self.worker.read_text(encoding="utf-8").replace(
            "emit({'operation':'closed','ok':True}); break",
            "emit({'operation':'closed','ok':False}); break",
        )
        self.worker.write_text(source, encoding="utf-8")
        self.specification["worker_sha256"] = digest(self.worker.read_bytes())
        with patch.dict(os.environ, self.environment):
            compressor = LLMLingua2Compressor(self.specification, self.root / "close-failure")
            with self.assertRaisesRegex(CompressorError, "did not close cleanly"):
                compressor.close()


if __name__ == "__main__":
    unittest.main()
