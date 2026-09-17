import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.screening_inventory import _direct_dependency_pins, canonical_json, resolve_docker_hub_image, verify_inventory


class _Response:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *arguments):
        return False

    def read(self):
        return self.body


class ScreeningInventoryTests(unittest.TestCase):
    def test_canonical_json_is_stable(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), b'{"a":1,"b":2}')

    def test_direct_dependency_pins_are_recorded_without_guessing_transitive_dependencies(self):
        command = "pip install pytest==8.4.1 thing@abcdef1 other>=2"
        self.assertEqual(_direct_dependency_pins(command), ["pytest==8.4.1", "thing@abcdef1"])

    def test_registry_resolution_selects_one_linux_amd64_manifest(self):
        index = json.dumps({"manifests": [
            {"digest": "sha256:" + "a" * 64, "platform": {"os": "linux", "architecture": "amd64"}},
            {"digest": "sha256:" + "b" * 64, "platform": {"os": "linux", "architecture": "arm64"}},
        ]}).encode()
        with patch("src.screening_inventory.urllib.request.urlopen", return_value=_Response(b'{"token":"secret"}')), patch(
            "src.screening_inventory._registry_request",
            side_effect=[({"Docker-Content-Digest": "sha256:" + "c" * 64}, index),
                         ({"Docker-Content-Digest": "sha256:" + "a" * 64}, b"")],
        ):
            resolved = resolve_docker_hub_image("owner/image:tag")
        self.assertEqual(resolved["pinned_reference"], "owner/image@sha256:" + "a" * 64)

    def test_inventory_hash_and_image_contract_fail_closed(self):
        tasks = [{"task_id": f"task-{index:03d}", "image": {"pinned_reference": "image@sha256:" + "a" * 64}}
                 for index in range(89)]
        payload = {"tasks": tasks}
        from src.screening_inventory import digest
        inventory = {**payload, "inventory_sha256": digest(canonical_json(payload))}
        self.assertIs(verify_inventory(inventory), inventory)
        inventory["tasks"][0]["image"]["pinned_reference"] = None
        with self.assertRaises(ValueError):
            verify_inventory(inventory)


if __name__ == "__main__":
    unittest.main()
