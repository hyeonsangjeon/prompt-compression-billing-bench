import tomllib
import unittest
from pathlib import Path

import evidence


ROOT = Path(__file__).resolve().parents[1]


class RootLicenseTests(unittest.TestCase):
    def test_mit_license_has_resolved_owner_and_year(self):
        text = (ROOT / "LICENSE").read_text()
        self.assertTrue(text.startswith("MIT License\n\n"))
        self.assertIn("Copyright (c) 2026 Hyeonsangjeon", text)
        self.assertIn("Permission is hereby granted, free of charge", text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', text)
        self.assertNotIn("{{COPYRIGHT_", text)

    def test_project_metadata_declares_mit_license_file(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project["license-files"], ["LICENSE"])

    def test_publication_allowlist_includes_license_contract(self):
        self.assertIn("LICENSE", evidence.PUBLIC_FILES)
        self.assertIn("tests/test_root_license.py", evidence.PUBLIC_FILES)

    def test_documents_keep_third_party_and_rights_boundaries(self):
        readme = (ROOT / "README.md").read_text()
        publication = (ROOT / "docs" / "publication.md").read_text()
        status = (ROOT / "STATUS.md").read_text()
        normalized_readme = " ".join(readme.split())
        self.assertIn("Project-authored source is licensed", readme)
        self.assertIn("Third-party materials remain subject to their own terms", readme)
        self.assertIn("does not grant rights to unapproved assets", normalized_readme)
        self.assertIn("third-party materials", publication)
        self.assertIn("DeepSWE redistribution rights", publication)
        self.assertIn("root MIT license", status)


if __name__ == "__main__":
    unittest.main()
