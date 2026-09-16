import asyncio
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from harbor.environments.docker.docker import DockerEnvironment

from src.replay_environment import (
    PreservingDockerEnvironment,
    archive_has_members,
    archive_installation,
    archive_inventory,
    changed_leaf_paths,
    deleted_root_paths,
    normalized_absolute_paths,
    nul_path_payload,
    outermost_absolute_paths,
    parse_docker_diff,
    redact_inspect,
    replay_bundle_manifest,
    sorted_mounts,
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

    def test_nul_path_payload_is_sorted_and_keeps_spaces_and_newlines(self):
        paths = ["/tmp/z value", "/tmp/a\nvalue"]
        self.assertEqual(normalized_absolute_paths(paths), sorted(paths))
        self.assertEqual(
            nul_path_payload(paths, relative=True),
            b"tmp/a\nvalue\0tmp/z value\0",
        )
        with self.assertRaises(ValueError):
            nul_path_payload(["/"], relative=True)

    def test_outermost_paths_remove_descendants_without_hiding_siblings(self):
        self.assertEqual(
            outermost_absolute_paths([
                "/tmp/tree/child", "/tmp/tree", "/tmp/other", "/tmp/tree/second",
            ]),
            ["/tmp/other", "/tmp/tree"],
        )

    async def test_remove_paths_uses_one_find_process_with_literal_path_arguments(self):
        environment = object.__new__(PreservingDockerEnvironment)
        environment._command = AsyncMock(return_value=(0, b""))

        await environment._remove_paths(
            "container-id", ["/tmp/tree/child", "/tmp/tree", "/tmp/other\nvalue"],
        )

        arguments = environment._command.await_args.args[0]
        self.assertEqual(arguments, [
            "docker", "exec", "container-id", "find",
            "/tmp/other\nvalue", "/tmp/tree", "-depth", "-delete",
        ])
        self.assertNotIn("input_bytes", environment._command.await_args.kwargs)

    def test_mounts_are_sorted_by_destination_before_hashing(self):
        mounts = [
            {"Destination": "/logs/verifier", "Type": "bind"},
            {"Destination": "/logs/agent", "Type": "bind"},
        ]
        self.assertEqual(
            [mount["Destination"] for mount in sorted_mounts({"Mounts": mounts})],
            ["/logs/agent", "/logs/verifier"],
        )

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

    def test_archive_installation_rebases_symlink_that_leaves_copy_destination(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w") as archive:
            link = tarfile.TarInfo("pdb3.11")
            link.type = tarfile.SYMTYPE
            link.linkname = "../lib/python3.11/pdb.py"
            archive.addfile(link)
        installation, destination = archive_installation(payload.getvalue(), "/usr/bin/pdb3.11")
        self.assertEqual(destination, "/")
        with tarfile.open(fileobj=io.BytesIO(installation), mode="r:*") as archive:
            member = archive.getmembers()[0]
        self.assertEqual(member.name, "usr/bin/pdb3.11")
        self.assertEqual(member.linkname, "../lib/python3.11/pdb.py")

    def test_archive_installation_keeps_internal_symlink_payload_byte_exact(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w") as archive:
            link = tarfile.TarInfo("pdb3")
            link.type = tarfile.SYMTYPE
            link.linkname = "pdb3.11"
            archive.addfile(link)
        source = payload.getvalue()
        installation, destination = archive_installation(source, "/usr/bin/pdb3")
        self.assertEqual(destination, "/usr/bin")
        self.assertEqual(installation, source)

    def test_archive_installation_rejects_members_from_another_target(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w") as archive:
            file = tarfile.TarInfo("other")
            file.size = 0
            archive.addfile(file, io.BytesIO())
        with self.assertRaisesRegex(ValueError, "do not match"):
            archive_installation(payload.getvalue(), "/usr/bin/pdb3")

    def test_archive_installation_keeps_empty_socket_snapshot_as_no_op(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w"):
            pass
        source = payload.getvalue()
        installation, destination = archive_installation(source, "/tmp/tmux-0/default")
        self.assertEqual(destination, "/tmp/tmux-0")
        self.assertIsNone(installation)
        self.assertFalse(archive_has_members(source))

    async def test_restore_leaves_matching_unarchived_socket_in_place(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            container_directory = directory / "container"
            container_directory.mkdir()
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w"):
                pass
            archive = container_directory / "change-00000.tar"
            archive.write_bytes(payload.getvalue())
            environment = object.__new__(PreservingDockerEnvironment)
            environment._replay_directory = directory
            environment._container_details = AsyncMock(return_value=(
                [{"Mounts": []}], [
                    {"change": "A", "path": "/tmp/tmux-0"},
                    {"change": "A", "path": "/tmp/tmux-0/default"},
                ], 0, b"",
            ))
            current_snapshot = {
                "status": "complete",
                "unarchived_special_paths": [{"path": "/tmp/tmux-0/default", "kind": "socket"}],
            }
            current_changed = [
                {"change": "A", "path": "/tmp/tmux-0", "kind": "directory", "archived": True},
                {"change": "A", "path": "/tmp/tmux-0/default", "kind": "socket", "archived": False},
            ]
            environment._root_snapshot = AsyncMock(return_value=(current_snapshot, current_changed))
            environment._remove_paths = AsyncMock()
            environment._install_root_archive = AsyncMock()
            environment._restore_mount = AsyncMock()
            await environment._restore_container({
                "container_id": "container-id",
                "container_name": "/container",
                "image_id": "sha256:image",
                "processes_sha256": sha256(b"").hexdigest(),
                "diff": [
                    {"change": "A", "path": "/tmp/tmux-0"},
                    {"change": "A", "path": "/tmp/tmux-0/default"},
                ],
                "changed_paths": [
                    {
                        "change": "A", "path": "/tmp/tmux-0", "kind": "directory",
                        "archived": True, "tree_sha256": "a" * 64,
                    },
                    {
                        "change": "A", "path": "/tmp/tmux-0/default", "kind": "socket",
                        "archived": False, "tree_sha256": None,
                    },
                ],
                "root_snapshot": {
                    "unarchived_special_paths": [{"path": "/tmp/tmux-0/default", "kind": "socket"}],
                    "payload": {"path": archive.name},
                },
                "mounts": [],
            })
            self.assertEqual(environment._remove_paths.await_count, 2)
            self.assertTrue(all(call.args[1] == [] for call in environment._remove_paths.await_args_list))
            environment._install_root_archive.assert_awaited_once()

    async def test_restore_does_not_remove_parent_of_bind_mounts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            container_directory = directory / "container"
            container_directory.mkdir()
            archive = container_directory / "root-snapshot.tar"
            archive.write_bytes(b"snapshot")
            environment = object.__new__(PreservingDockerEnvironment)
            environment._replay_directory = directory
            environment._container_details = AsyncMock(return_value=(
                [{"Mounts": [
                    {"Destination": "/logs/agent", "Type": "bind"},
                    {"Destination": "/logs/verifier", "Type": "bind"},
                ]}],
                [
                    {"change": "A", "path": "/logs"},
                    {"change": "A", "path": "/logs/agent"},
                    {"change": "A", "path": "/logs/verifier"},
                ],
                0,
                b"processes",
            ))
            environment._root_snapshot = AsyncMock(return_value=(
                {"status": "complete", "unarchived_special_paths": []},
                [{
                    "change": "A", "path": "/logs", "kind": "directory", "archived": True,
                }],
            ))
            environment._remove_paths = AsyncMock()
            environment._install_root_archive = AsyncMock()
            environment._restore_mount = AsyncMock()
            await environment._restore_container({
                "container_id": "container-id",
                "container_name": "/container",
                "image_id": "sha256:image",
                "processes_sha256": sha256(b"processes").hexdigest(),
                "diff": [
                    {"change": "A", "path": "/logs"},
                    {"change": "A", "path": "/logs/agent"},
                    {"change": "A", "path": "/logs/verifier"},
                ],
                "changed_paths": [{
                    "change": "A", "path": "/logs", "kind": "directory", "archived": True,
                }],
                "root_snapshot": {"unarchived_special_paths": [], "payload": {"path": archive.name}},
                "mounts": [],
            })
            self.assertEqual(environment._remove_paths.await_count, 2)
            self.assertTrue(all(call.args[1] == [] for call in environment._remove_paths.await_args_list))
            environment._install_root_archive.assert_awaited_once()

    async def test_special_path_classifier_passes_nul_delimiters_through_stdin_only(self):
        environment = object.__new__(PreservingDockerEnvironment)
        environment._command_streams = AsyncMock(return_value=(
            0, b"/tmp/socket path\0socket\0", b"",
        ))

        records = await environment._special_path_kinds(
            "container-id", ["/tmp/socket path"],
        )

        self.assertEqual(records, [{"path": "/tmp/socket path", "kind": "socket"}])
        arguments = environment._command_streams.await_args.args[0]
        self.assertNotIn("\0", arguments[-1])
        self.assertIn(r"printf '%s\0%s\0'", arguments[-1])
        self.assertEqual(
            environment._command_streams.await_args.kwargs["input_bytes"],
            b"/tmp/socket path\0",
        )

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
            ]
            environment._command = AsyncMock(side_effect=responses)
            environment._root_snapshot = AsyncMock(return_value=(
                {
                    "status": "incomplete",
                    "payload": {"tree_sha256": None},
                    "unarchived_special_paths": [],
                },
                [],
            ))
            manifest = await environment._capture_environment()
            self.assertEqual(manifest["status"], "incomplete")
            self.assertGreaterEqual(manifest["capture_wall_seconds"], 0)
            path = Path(temporary) / "workspace-replay/task__trial__env/manifest.json"
            self.assertTrue(path.is_file())
            self.assertEqual(json.loads(path.read_text())["manifest_sha256"], manifest["manifest_sha256"])
            self.assertEqual(replay_bundle_manifest(path)["status"], "incomplete")

    async def test_verifier_replay_runs_during_stop_not_inside_verifier_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verifier = root / "verifier"
            verifier.mkdir()
            environment = object.__new__(PreservingDockerEnvironment)
            environment.session_id = "task__trial__env"
            environment.trial_paths = SimpleNamespace(trial_dir=root, verifier_dir=verifier)
            environment._tests_uploaded = True
            environment._replay_started = False
            environment._replay_manifest = {"status": "complete"}
            environment._pending_verifier_replay = None
            environment._preparatory_verifier_commands = []
            environment._repeat_verifier = AsyncMock()
            result = SimpleNamespace(return_code=0)
            with patch.object(DockerEnvironment, "exec", AsyncMock(return_value=result)), patch.object(
                DockerEnvironment, "stop", AsyncMock()
            ) as base_stop:
                observed = await environment.exec(
                    "/tests/test.sh > /logs/verifier/test-stdout.txt",
                )
                self.assertIs(observed, result)
                environment._repeat_verifier.assert_not_awaited()
                self.assertIsNotNone(environment._pending_verifier_replay)
                self.assertGreaterEqual(
                    environment._pending_verifier_replay["original_verifier_wall_seconds"], 0
                )
                await environment.stop(delete=True)
                environment._repeat_verifier.assert_awaited_once()
                base_stop.assert_awaited_once_with(delete=True)

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
            verifier = root / "verifier"
            verifier.mkdir()
            (verifier / "result.txt").write_text("captured verifier\n")
            seed_name = "replay-seed-" + uuid.uuid4().hex[:12]
            seed = subprocess.run(
                [
                    "docker", "run", "-d", "--name", seed_name, "--user", "0", image,
                    "sh", "-c", "sleep 600",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            ).stdout.strip()
            try:
                subprocess.run(
                    [
                        "docker", "exec", seed, "sh", "-c",
                        "printf 'base root\\n' > /replay-base-modified && "
                        "mkdir /replay-base-deleted && printf 'base child\\n' > /replay-base-deleted/child && "
                        "mkdir /replay-base-untouched && printf 'keep child\\n' > /replay-base-untouched/child",
                    ],
                    check=True,
                    timeout=30,
                )
                committed_image = subprocess.run(
                    ["docker", "commit", seed],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                ).stdout.strip()
            finally:
                subprocess.run(["docker", "rm", "-f", seed], capture_output=True, timeout=30)
            self.addCleanup(
                lambda: subprocess.run(
                    ["docker", "image", "rm", committed_image], capture_output=True, timeout=30,
                )
            )
            name = "replay-contract-" + uuid.uuid4().hex[:12]
            created = subprocess.run(
                [
                    "docker", "run", "-d", "--name", name, "--user", "0",
                    "-v", f"{mounted}:/workspace",
                    "-v", f"{verifier}:/logs/verifier",
                    committed_image,
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
                [
                    "docker", "exec", container_id, "sh", "-c",
                    "printf 'captured root\\n' > /replay-base-modified && "
                    "rm -rf /replay-base-deleted && printf 'captured added\\n' > /replay-added",
                ],
                check=True,
                timeout=30,
            )
            subprocess.run(
                [
                    "docker", "exec", container_id, "sh", "-c",
                    "mkdir -p /usr/local/bin && ln -s ../../../tmp/replay-target /usr/local/bin/replay-link",
                ],
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
                [
                    "docker", "exec", container_id, "sh", "-c",
                    "printf 'mutated root\\n' > /replay-base-modified && "
                    "mkdir /replay-base-deleted && printf 'mutated child\\n' > /replay-base-deleted/child && "
                    "rm -rf /replay-base-untouched /replay-added /usr/local/bin/replay-link && "
                    "printf 'verifier only\\n' > /replay-verifier-only",
                ],
                check=True,
                timeout=30,
            )
            (mounted / "result.txt").write_text("mutated mount\n")
            (verifier / "result.txt").write_text("mutated verifier\n")
            await environment._restore_container(manifest["containers"][0])
            restored = await environment._state_signature(container_id)
            restored_hash = sha256(json.dumps(
                {"containers": [restored]}, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            self.assertEqual(restored_hash, manifest["state_sha256"])
            root_value = subprocess.run(
                ["docker", "exec", container_id, "cat", "/replay-base-modified"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
            self.assertEqual(root_value, "captured root\n")
            self.assertEqual(subprocess.run(
                ["docker", "exec", container_id, "cat", "/replay-added"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout, "captured added\n")
            self.assertEqual(subprocess.run(
                ["docker", "exec", container_id, "test", "!", "-e", "/replay-base-deleted"],
                timeout=30,
            ).returncode, 0)
            self.assertEqual(subprocess.run(
                ["docker", "exec", container_id, "cat", "/replay-base-untouched/child"],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout, "keep child\n")
            self.assertEqual(subprocess.run(
                ["docker", "exec", container_id, "test", "!", "-e", "/replay-verifier-only"],
                timeout=30,
            ).returncode, 0)
            self.assertEqual((mounted / "result.txt").read_text(), "captured mount\n")
            self.assertEqual((verifier / "result.txt").read_text(), "captured verifier\n")
            link_value = subprocess.run(
                ["docker", "exec", container_id, "readlink", "/usr/local/bin/replay-link"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
            self.assertEqual(link_value, "../../../tmp/replay-target\n")

            socket_path = mounted / "replay-special.sock"
            unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                unix_socket.bind(str(socket_path))
                self.assertEqual(
                    await environment._special_path_kinds(
                        container_id, ["/workspace/replay-special.sock"],
                    ),
                    [{"path": "/workspace/replay-special.sock", "kind": "socket"}],
                )
            finally:
                unix_socket.close()
                socket_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
