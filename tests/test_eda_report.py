import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from evidence import audit_files
from src.eda_report import (
    CANDIDATE_CAVEAT,
    COUNTING_METHOD_FACTS,
    COUNTING_METHOD_SUMMARY,
    REMOVED_WORK_HISTORY,
    audit_report,
    check_svg,
    json_digest,
    scan_public_text,
)
from src.protection import digest


ROOT = Path(__file__).resolve().parents[1]


class EdaReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.report = self.root / "docs/eda"
        shutil.copytree(ROOT / "docs/eda", self.report)
        self.markdown_path = self.report / "README.md"
        self.markdown = self.markdown_path.read_text(encoding="utf-8")
        self.manifest = json.loads((self.report / "manifest.json").read_bytes())

    def test_reviewed_assembly(self):
        self.assertEqual(audit_report(self.root), {"figures": 10, "tables": 27})

    def test_counting_method_excludes_internal_work_history(self):
        self.assertIn(COUNTING_METHOD_SUMMARY, self.markdown)
        self.assertIn(
            "분류 판단: 사람이 정한 규칙으로 나눈 결과. 규칙이 달라지면 값도 달라진다. 경계가 애매한 항목이 있다.",
            self.markdown,
        )
        for content in COUNTING_METHOD_FACTS:
            with self.subTest(required=content):
                self.assertIn(content, self.markdown)
        for content in REMOVED_WORK_HISTORY:
            with self.subTest(content=content):
                self.assertNotIn(content, self.markdown)

    def test_numeric_drift_in_either_direction(self):
        for replacement in ("1,974", "1,976"):
            with self.subTest(replacement=replacement):
                self.markdown_path.write_text(self.markdown.replace("1,975", replacement), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "table cells"):
                    audit_report(self.root)

    def test_sample_denominator_and_kind_are_required(self):
        metadata = dict(self.manifest["figures"][0]["metadata"])
        for label in ("표본", "분모 · 단위", "성격"):
            with self.subTest(label=label):
                original = f"- **{label}:** {metadata[label]}"
                self.markdown_path.write_text(self.markdown.replace(original, "- removed:", 1), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "sample, denominator or kind"):
                    audit_report(self.root)

    def test_limitation_cannot_be_removed(self):
        self.markdown_path.write_text(self.markdown.replace(CANDIDATE_CAVEAT, ""), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "limitation"):
            audit_report(self.root)

    def test_image_must_be_relative_and_unchanged(self):
        entry = self.manifest["figures"][0]
        self.markdown_path.write_text(self.markdown.replace(entry["path"], "https://example.invalid/figure.svg"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "image paths"):
            audit_report(self.root)
        self.markdown_path.write_text(self.markdown, encoding="utf-8")
        image = self.report / entry["path"]
        image.write_bytes(image.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "figure differs"):
            audit_report(self.root)

    def test_missing_figure_is_rejected(self):
        (self.report / self.manifest["figures"][0]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "Missing EDA asset"):
            audit_report(self.root)

    def test_symlink_is_not_a_public_asset(self):
        image = self.report / self.manifest["figures"][0]["path"]
        target = self.root / "synthetic-outside.svg"
        image.replace(target)
        image.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            audit_report(self.root)

    def test_table_provenance_is_required(self):
        entry = self.manifest["tables"][0]
        provenance = f"원문 표: {entry['source']} · 표 {entry['source_table']}."
        self.markdown_path.write_text(self.markdown.replace(provenance, ""), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "provenance"):
            audit_report(self.root)

    def test_symlinked_parent_is_not_a_public_asset(self):
        target = self.root / "synthetic-outside-docs"
        (self.root / "docs").replace(target)
        (self.root / "docs").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            audit_report(self.root)

    def test_tool_results_and_withdrawn_estimate_are_rejected(self):
        for content in ("squeez", "headroom", "13.79%"):
            with self.subTest(content=content):
                self.markdown_path.write_text(self.markdown + content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Tool experiment or withdrawn"):
                    audit_report(self.root)

    def test_sensitive_patterns_in_text(self):
        for content in (
            "_work/synthetic-input.json", "/home/synthetic/project", "file:///synthetic",
            "D:\\synthetic\\project", "analyst@example.invalid",
            "12345678-1234-1234-1234-123456789abc", "tenant_id=synthetic",
            "https://synthetic-resource.openai.azure.com/", "%2Fhome%2Fsynthetic",
        ):
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "private path or identifier"):
                scan_public_text(content, "synthetic")

    def test_public_repository_names_are_not_operational_accounts(self):
        scan_public_text("pmndrs/koota PyCQA/bandit datacurve/deep-swe", "public source labels")

    def check_synthetic_svg(self, body):
        content = f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>'.encode()
        check_svg(content, {
            "path": "figures/synthetic.svg", "sha256": digest(content),
            "visible_text_sha256": json_digest([]),
        })

    def test_svg_text_and_metadata_are_scanned(self):
        for body in (
            "<text>analyst&#64;example.invalid</text>",
            "<text>_wo<tspan>rk/</tspan>synthetic</text>",
            "<metadata>tenant_id=synthetic</metadata>",
        ):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, "private path or identifier"):
                self.check_synthetic_svg(body)

    def test_svg_cannot_load_external_or_active_content(self):
        for body in (
            '<script>alert("synthetic")</script>', '<g onload="synthetic"/>',
            '<use href="https://example.invalid/asset.svg"/>',
            '<style>path { fill: url(https://example.invalid/fill.svg); }</style>',
            '<foreignObject><div>synthetic</div></foreignObject>',
            '<image href="data:image/png;base64,c3ludGhldGlj"/>',
        ):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, "[Ee]xternal"):
                self.check_synthetic_svg(body)

    def test_publication_audit_checks_report_content(self):
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True, capture_output=True)
        (self.root / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
        audit_files(self.root)
        self.markdown_path.write_text(self.markdown + "\n/home/synthetic/private\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "private path or identifier"):
            audit_files(self.root)


if __name__ == "__main__":
    unittest.main()
