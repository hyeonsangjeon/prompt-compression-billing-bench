import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from evidence import audit_files
from src.prompt_intake import archive_prompts


class PromptIntakeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("/_work/\n")

    def test_audit_archives_new_root_prompts_and_records_their_kind(self):
        source = self.root / "prompt_new (2).md"
        source.write_text("사용자 프롬프트\n")
        audit_files(self.root)
        self.assertFalse(source.exists())
        manifest = json.loads((self.root / "_work/prompts/manifest.json").read_bytes())
        self.assertEqual(manifest["entries"][0]["kind"], "user_request_not_measurement")
        self.assertEqual((self.root / manifest["entries"][0]["archive_path"]).read_text(), "사용자 프롬프트\n")
        self.assertEqual(archive_prompts(self.root), [])

    def test_same_name_different_content_is_preserved_without_overwrite(self):
        source = self.root / "prompt_plan.md"
        source.write_text("first")
        first = archive_prompts(self.root)[0]
        source.write_text("second")
        second = archive_prompts(self.root)[0]
        self.assertNotEqual(first["archive_path"], second["archive_path"])
        self.assertEqual((self.root / first["archive_path"]).read_text(), "first")
        self.assertEqual((self.root / second["archive_path"]).read_text(), "second")

    def test_tracked_prompt_is_not_moved_or_hidden(self):
        source = self.root / "prompt_tracked.md"
        source.write_text("tracked")
        subprocess.run(["git", "-C", str(self.root), "add", "prompt_tracked.md"], check=True)
        with self.assertRaises(ValueError):
            audit_files(self.root)
        self.assertTrue(source.exists())

    def test_unknown_and_nested_files_still_fail_the_audit(self):
        (self.root / "new-result.json").write_text("{}")
        with self.assertRaises(ValueError):
            audit_files(self.root)
        self.assertTrue((self.root / "new-result.json").exists())

    def test_symlink_and_missing_private_ignore_are_rejected(self):
        (self.root / "outside.txt").write_text("private")
        source = self.root / "prompt_link.md"
        source.symlink_to(self.root / "outside.txt")
        with self.assertRaises(ValueError):
            archive_prompts(self.root)
        source.unlink()
        source.write_text("user prompt")
        (self.root / ".gitignore").write_text("")
        with self.assertRaises(ValueError):
            archive_prompts(self.root)
        self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
