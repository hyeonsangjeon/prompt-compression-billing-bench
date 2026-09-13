import io
import json
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest

from src.blob_retrieval import AzureBlobClient, BlobSpool, BlobUploadError


class FakeBlobClient:
    def __init__(self, failures=0):
        self.account_url = "https://synthetic.blob.core.windows.net"
        self.container = "runs"
        self.timeout_seconds = 1
        self.failures = failures
        self.calls = []
        self.blobs = {}
        self.lock = threading.Lock()

    def _store(self, name, payload):
        with self.lock:
            self.calls.append(name)
            if self.failures:
                self.failures -= 1
                raise BlobUploadError(503, "service_unavailable")
            self.blobs[name] = payload
        return {"etag": f"etag-{len(self.calls)}", "request_id": "synthetic", "bytes": len(payload)}

    def put_file(self, name, path, sha256):
        return self._store(name, path.read_bytes())

    def put_bytes(self, name, payload):
        return self._store(name, payload)


def make_spool(root, client, *, attempts=5, initial=0):
    return BlobSpool(
        root, "native-none-20260913t000000z-deadbeef", "a" * 40, "b" * 64, "none", client,
        prefix="runs", maximum_attempts=attempts, initial_backoff_seconds=initial,
        maximum_backoff_seconds=max(initial, 0),
    )


class BlobRetrievalTests(unittest.TestCase):
    def test_real_sized_payload_retries_and_uploads_manifest_last(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "result.tar"
            payload.write_bytes(b"result-block\n" * 200000)
            payload_size = payload.stat().st_size
            client = FakeBlobClient(failures=2)
            spool = make_spool(root / "spool", client)
            spool.stage_file(payload, "adapter-preflight", kind="software_preflight", metadata={"model_calls": 0})
            report = spool.finish(3)
        self.assertEqual(report["upload_state"], "uploaded")
        self.assertEqual(report["items"][0]["attempts"], 3)
        self.assertEqual(report["items"][0]["payload"]["bytes"], payload_size)
        self.assertTrue(client.calls[-1].endswith("/manifest.json"))
        manifest = json.loads(client.blobs[client.calls[-1]])
        self.assertTrue(manifest["manifest_uploaded_last"])

    def test_failed_upload_keeps_atomic_local_payload_and_error_classification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "result.tar"
            payload.write_bytes(b"private result")
            spool = make_spool(root / "spool", FakeBlobClient(failures=20), attempts=1)
            spool.stage_file(payload, "adapter-preflight", kind="software_preflight", metadata={})
            report = spool.finish(1)
            state_path = next((root / "spool").glob("*/adapter-preflight/state.json"))
            local_payload = state_path.parent / "payload.tar"
            state = json.loads(state_path.read_bytes())
            retained = local_payload.read_bytes()
        self.assertEqual(report["upload_state"], "retrieval_pending")
        self.assertEqual(state["upload_state"], "failed")
        self.assertEqual(state["last_error_category"], "service_unavailable")
        self.assertEqual(retained, b"private result")

    def test_preserved_failed_spool_can_resume_without_recreating_the_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "result.tar"
            payload.write_bytes(b"recoverable private result")
            first = make_spool(root / "spool", FakeBlobClient(failures=10), attempts=1)
            first.stage_file(payload, "adapter-preflight", kind="software_preflight", metadata={})
            failed = first.finish(1)
            resumed_client = FakeBlobClient()
            resumed = BlobSpool.resume(
                root / "spool/native-none-20260913t000000z-deadbeef", resumed_client,
                prefix="runs", maximum_attempts=2, initial_backoff_seconds=0,
                maximum_backoff_seconds=0,
            )
            recovered = resumed.finish(2)
        self.assertEqual(failed["upload_state"], "retrieval_pending")
        self.assertEqual(recovered["upload_state"], "uploaded")
        self.assertEqual(recovered["items"][0]["attempts"], 2)
        self.assertTrue(resumed_client.calls[-1].endswith("/manifest.json"))

    def test_native_snapshot_contains_actual_trial_and_transport_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "run"
            (run / "transport/request-00001").mkdir(parents=True)
            (run / "transport/request-00001/manifest.json").write_text(json.dumps({"trial_id": "r01-task-1"}))
            (run / "transport/request-00001/before.json").write_bytes(b"{}")
            (run / "transport/events.jsonl").write_text(json.dumps({"trial_id": "r01-task-1", "event": "http"}) + "\n")
            trials = []
            for index in range(1, 6):
                trial_id = f"r01-task-{index}"
                (run / f"trials/{trial_id}").mkdir(parents=True)
                (run / f"trials/{trial_id}/trial.json").write_text("{}")
                (run / f"jobs/{trial_id}").mkdir(parents=True)
                (run / f"jobs/{trial_id}/result.json").write_text("{}")
                trials.append({
                    "trial_id": trial_id, "repetition": 1, "task": f"task-{index}",
                    "native_outcome": {"native_reward": index % 2},
                })
            client = FakeBlobClient()
            spool = make_spool(root / "spool", client)
            staged = spool.stage_run_snapshot(run, 1, trials)
            report = spool.finish(2)
            archive_bytes = client.blobs[staged["payload"]["blob"]]
        self.assertEqual(report["upload_state"], "uploaded")
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
            names = set(archive.getnames())
        self.assertIn("retrieval-snapshot.json", names)
        self.assertIn("trials/r01-task-5/trial.json", names)
        self.assertIn("jobs/r01-task-5/result.json", names)
        self.assertIn("transport/request-00001/before.json", names)

    def test_blob_account_url_cannot_carry_credentials_or_arbitrary_hosts(self):
        for value in (
            "http://synthetic.blob.core.windows.net", "https://example.com",
            "https://user:secret@synthetic.blob.core.windows.net", "https://synthetic.blob.core.windows.net/path",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AzureBlobClient(value, "runs")


if __name__ == "__main__":
    unittest.main()
