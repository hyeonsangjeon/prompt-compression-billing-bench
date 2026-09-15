import asyncio
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock

from src.replay_environment import (
    PreservingDockerEnvironment,
    archive_inventory,
    changed_leaf_paths,
    deleted_root_paths,
    parse_docker_diff,
    redact_inspect,
    replay_bundle_manifest,
    verifier_signature,
)


class ReplayEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    def test_diff_parser_rejects_ambiguous_lines_and_excludes_pseudo_filesystems(self):
        self.assertEqual(parse_docker_diff("C /app\nA /proc/1/x\nD /tmp/gone\n"), [
            {"change": "C", "path": "/app"}, {"change": "D", "path": "/tmp/gone"},
        ])
        with self.assertRaises(ValueError):
            parse_docker_diff("changed /app\n")

    def test_inspect_redacts_sensitive_environment_values(self):
        value = [{"Config": {"Env": ["PATH=/bin", "OPENAI_API_KEY=local-key"]}}]
        redacted = redact_inspect(value)
        self.assertEqual(redacted[0]["Config"]["Env"][0], "PATH=/bin")
        self.assertRegex(redacted[0]["Config"]["Env"][1], r"^OPENAI_API_KEY=sha256:[0-9a-f]{64}$")
        self.assertEqual(value[0]["Config"]["Env"][1], "OPENAI_API_KEY=local-key")

    def test_changed_paths_copy_only_leaves_when_docker_reports_ancestors(self):
        records = parse_docker_diff("C /app\nC /app/result\nA /app/result/output.txt\nA /tmp/empty\n")
        self.assertEqual(changed_leaf_paths(records), [
            {"change": "A", "path": "/app/result/output.txt"},
            {"change": "A", "path": "/tmp/empty"},
        ])

    def test_changed_paths_handle_observed_large_diff_without_pairwise_comparison(self):
        records = [{"change": "C", "path": "/usr"}] + [
            {"change": "A", "path": f"/usr/lib/package-{index}/output"}
            for index in range(13_108)
        ]
        selected = changed_leaf_paths(records)
        self.assertEqual(len(selected), 13_108)
        self.assertNotIn(records[0], selected)

    def test_deleted_paths_copy_only_outer_roots(self):
        records = parse_docker_diff("D /app/old\nD /app/old/child\nD /tmp/other\n")
        self.assertEqual(deleted_root_paths(records), ["/app/old", "/tmp/other"])

    def test_archive_inventory_records_file_identity_without_tar_header_noise(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w") as archive:
            directory = tarfile.TarInfo("workspace")
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            archive.addfile(directory)
            content = b"answer\n"
            file = tarfile.TarInfo("workspace/result.txt")
            file.size = len(content)
            file.mode = 0o640
            file.uid = 1000
            file.gid = 1000
            archive.addfile(file, io.BytesIO(content))
        inventory = archive_inventory(payload.getvalue())
        self.assertEqual(inventory["entries"][1], {
            "path": "workspace/result.txt", "kind": "file", "mode": 0o640,
            "uid": 1000, "gid": 1000, "size": 7, "link_target": None,
            "sha256": sha256(b"answer\n").hexdigest(),
        })

    def test_verifier_signature_ignores_duration_but_keeps_test_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "reward.txt").write_text("1\n")
            (directory / "ctrf.json").write_text(json.dumps({"results": {"tests": [{
                "name": "test_value", "status": "passed", "raw_status": "passed", "duration": 2.5,
            }]}}))
            self.assertEqual(verifier_signature(directory, 0), {
                "command_return_code": 0,
                "reward_source": "reward.txt",
                "rewards": {"reward": 1.0},
                "tests": [{"name": "test_value", "status": "passed", "raw_status": "passed"}],
            })

    async def test_capture_writes_hash_manifest_and_marks_failed_copy_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = object.__new__(PreservingDockerEnvironment)
            environment.session_id = "task__trial__env"
            environment.trial_paths = SimpleNamespace(trial_dir=Path(temporary))
            environment._run_docker_compose_command = AsyncMock(return_value=SimpleNamespace(
                stdout="container-1\n", return_code=0,
            ))
            inspect = [{
                "Name": "/container-1", "Image": "sha256:image", "Config": {"Env": []},
                "Mounts": [],
            }]
            responses = [
                (0, json.dumps(inspect).encode()),
                (0, b"A /app/result.txt\n"),
                (0, b"processes"),
                (0, b"logs"),
                (1, b"copy failed"),
            ]
            environment._command = AsyncMock(side_effect=responses)
            manifest = await environment._capture_environment()
            self.assertEqual(manifest["status"], "incomplete")
            path = Path(temporary) / "workspace-replay/task__trial__env/manifest.json"
            self.assertTrue(path.is_file())
            self.assertEqual(json.loads(path.read_text())["manifest_sha256"], manifest["manifest_sha256"])
            self.assertEqual(replay_bundle_manifest(path)["status"], "incomplete")

    @unittest.skipUnless(
        os.environ.get("RUN_DOCKER_REPLAY_TESTS") == "1",
        "Set RUN_DOCKER_REPLAY_TESTS=1 on the Docker execution VM",
    )
    async def test_real_docker_capture_restore_preserves_root_and_mounted_state(self):
        image = os.environ.get("REPLAY_TEST_IMAGE", "")
        self.assertRegex(image, r"^[^\s]+@sha256:[0-9a-f]{64}$")
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=30)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mounted = root / "mounted"
            mounted.mkdir()
            (mounted / "result.txt").write_text("captured mount\n")
            name = "replay-contract-" + uuid.uuid4().hex[:12]
            created = subprocess.run(
                [
                    "docker", "run", "-d", "--name", name,
                    "-v", f"{mounted}:/workspace", image,
                    "sh", "-c", "sleep 600",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            container_id = created.stdout.strip()
            self.addCleanup(
                lambda: subprocess.run(
                    ["docker", "rm", "-f", container_id], capture_output=True, timeout=30,
                )
            )
            subprocess.run(
                ["docker", "exec", container_id, "sh", "-c", "printf 'captured root\\n' > /replay-root.txt"],
                check=True,
                timeout=30,
            )
            environment = object.__new__(PreservingDockerEnvironment)
            environment.session_id = name
            environment.trial_paths = SimpleNamespace(trial_dir=root / "trial")
            environment.trial_paths.trial_dir.mkdir()
            environment._run_docker_compose_command = AsyncMock(return_value=SimpleNamespace(
                stdout=container_id + "\n", return_code=0,
            ))
            manifest = await environment._capture_environment("docker_contract_test")
            self.assertEqual(manifest["status"], "complete")

            subprocess.run(
                ["docker", "exec", container_id, "sh", "-c", "printf 'mutated root\\n' > /replay-root.txt"],
                check=True,
                timeout=30,
            )
            (mounted / "result.txt").write_text("mutated mount\n")
            await environment._restore_container(manifest["containers"][0])
            restored = await environment._state_signature(container_id)
            restored_hash = sha256(json.dumps(
                {"containers": [restored]}, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            self.assertEqual(restored_hash, manifest["state_sha256"])
            root_value = subprocess.run(
                ["docker", "exec", container_id, "cat", "/replay-root.txt"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
            self.assertEqual(root_value, "captured root\n")
            self.assertEqual((mounted / "result.txt").read_text(), "captured mount\n")


if __name__ == "__main__":
    unittest.main()
