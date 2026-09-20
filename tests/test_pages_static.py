import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from src import pages_build, pages_oracle


ROOT = Path(__file__).resolve().parents[1]
PROJECT_PREFIX = "prompt-compression-billing-bench"
PAGES_RUNTIME_VERSIONS = {
    "markdown-it-py": "3.0.0",
    "mdurl": "0.1.2",
}


def pages_runtime_ready() -> bool:
    try:
        return all(metadata.version(name) == version for name, version in PAGES_RUNTIME_VERSIONS.items())
    except metadata.PackageNotFoundError:
        return False


def tree_summary(root: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AssertionError(f"unexpected symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        file_sha256 = hashlib.sha256(data).hexdigest()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(len(data)).encode("ascii") + b"\0")
        digest.update(file_sha256.encode("ascii") + b"\n")
        file_count += 1
        total_bytes += len(data)
    return {
        "file_count": file_count,
        "total_bytes": total_bytes,
        "tree_sha256": digest.hexdigest(),
    }


@unittest.skipUnless(
    pages_runtime_ready(),
    "Pages runtime checks require the exact requirements/pages-static.txt environment",
)
class PagesStaticRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="pages-static-tests-")
        cls.run_root = Path(cls.temporary.name)
        cls.first = cls.run_root / "first"
        cls.second = cls.run_root / "second"
        cls._build(cls.first)
        cls._build(cls.second)
        cls.verify_result = cls.first / "verify.json"
        cls._run(
            "src/pages_verify.py",
            "--source-root", ROOT,
            "--site-root", cls.first / "site",
            "--source-manifest", cls.first / "record/source-manifest.json",
            "--build-record", cls.first / "record/build-record.json",
            "--stylesheet", ROOT / "pages/assets/site.css",
            "--contract", ROOT / "config/pages-static.json",
            "--result", cls.verify_result,
        )
        cls.oracle_result = cls.first / "oracle.json"
        cls._run(
            "src/pages_oracle.py",
            "--source-root", ROOT,
            "--site-root", cls.first / "site",
            "--source-manifest", cls.first / "record/source-manifest.json",
            "--build-record", cls.first / "record/build-record.json",
            "--contract", ROOT / "config/pages-static.json",
            "--result", cls.oracle_result,
        )
        cls.server_root = cls.first / "server"
        shutil.copytree(cls.first / "site", cls.server_root / PROJECT_PREFIX)
        cls.http_result = cls.first / "http.json"
        cls._run(
            "src/pages_http_check.py",
            "--server-root", cls.server_root,
            "--project-prefix", f"/{PROJECT_PREFIX}/",
            "--source-site", cls.first / "site",
            "--contract", ROOT / "config/pages-static.json",
            "--result", cls.http_result,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @classmethod
    def _run(cls, script: str, *arguments: object, expected: int = 0) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-B", str(ROOT / script), *map(str, arguments)]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != expected:
            raise AssertionError(
                f"command returned {completed.returncode}, expected {expected}: {command}\n"
                f"stdout:\n{completed.stdout[-4000:]}\nstderr:\n{completed.stderr[-4000:]}"
            )
        return completed

    @classmethod
    def _build(cls, destination: Path) -> None:
        destination.mkdir()
        cls._run(
            "src/pages_build.py",
            "--source-root", ROOT,
            "--contract", ROOT / "config/pages-static.json",
            "--stylesheet", ROOT / "pages/assets/site.css",
            "--output", destination / "site",
            "--record-dir", destination / "record",
        )

    @staticmethod
    def _json(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _rewrite_build_record(record: Path, site: Path) -> None:
        value = json.loads(record.read_text(encoding="utf-8"))
        summary = tree_summary(site)
        value["output_file_count"] = summary["file_count"]
        value["output_total_bytes"] = summary["total_bytes"]
        value["output_tree_sha256"] = summary["tree_sha256"]
        record.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_two_clean_builds_are_byte_deterministic(self):
        first_summary = tree_summary(self.first / "site")
        second_summary = tree_summary(self.second / "site")
        self.assertEqual(first_summary, second_summary)
        first_record = self._json(self.first / "record/build-record.json")
        second_record = self._json(self.second / "record/build-record.json")
        for key, summary_key in (
            ("output_file_count", "file_count"),
            ("output_total_bytes", "total_bytes"),
            ("output_tree_sha256", "tree_sha256"),
        ):
            self.assertEqual(first_record[key], first_summary[summary_key])
            self.assertEqual(second_record[key], second_summary[summary_key])

    def test_static_verifier_reports_separate_denominators(self):
        result = self._json(self.verify_result)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["counts"], {"pass": len(result["checks"])})
        self.assertGreater(result["scope"]["source_public_files"], 0)
        self.assertGreater(result["scope"]["markdown_documents"], 0)
        self.assertGreater(result["scope"]["html_pages"], 0)
        self.assertEqual(result["scope"]["browser_visual_rendering"], "not_performed_by_static_verifier")
        checks = {item["id"]: item for item in result["checks"]}
        self.assertGreater(checks["html:local_href_src_and_fragments"]["detail"]["checked"], 0)
        self.assertGreater(checks["rendered_documents:block_reverse_comparison"]["detail"]["table_cells_compared"], 0)
        self.assertGreater(checks["rendered_documents:image_alt_and_target"]["detail"]["images_compared"], 0)

    def test_independent_oracle_matches_source_bodies(self):
        result = self._json(self.oracle_result)
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["correction_required"])
        self.assertFalse(result["oracle"]["renderer_parser_or_slugger_reused"])
        self.assertEqual(result["oracle"]["dependencies"], {"markdown-it-py": "3.0.0", "mdurl": "0.1.2"})
        expected = result["counts"]["expected"]
        actual = result["counts"]["actual"]
        for key in ("blocks", "table_cells", "code_blocks", "inline_codes", "links", "images", "headings", "task_list_items", "strong_spans"):
            self.assertEqual(expected[key], actual[key], key)
        observations = result["intended_transformations"]["boundary_validated_project_strong_observations"]
        self.assertTrue(observations)
        self.assertTrue(all(item["matched"] for item in observations))

    def test_project_prefix_http_uses_distinct_counts_and_stops_server(self):
        result = self._json(self.http_result)
        self.assertEqual(result["status"], "pass")
        delivery = result["http_file_delivery"]
        references = result["logical_references"]
        self.assertEqual(delivery["responses_succeeded"], delivery["files_expected"])
        self.assertEqual(references["local_reference_http_requests_succeeded"], references["local_references_checked"])
        self.assertEqual(references["external_requests_attempted"], 0)
        self.assertEqual(references["outside_prefix_requests_attempted"], 0)
        self.assertTrue(result["server"]["thread_stopped"])
        self.assertTrue(result["encoded_hangul_fragment_probe"]["passed"])
        self.assertTrue(result["trailing_slash_redirect_probe"]["passed"])

    def test_result_and_build_paths_are_no_clobber(self):
        case_root = self.run_root / "no-clobber"
        case_root.mkdir()
        sentinel_bytes = b'{"preserve":true}\n'
        result_commands = {
            "verify": (
                "src/pages_verify.py",
                (
                    "--source-root", ROOT,
                    "--site-root", self.first / "site",
                    "--source-manifest", self.first / "record/source-manifest.json",
                    "--build-record", self.first / "record/build-record.json",
                    "--stylesheet", ROOT / "pages/assets/site.css",
                    "--contract", ROOT / "config/pages-static.json",
                ),
            ),
            "oracle": (
                "src/pages_oracle.py",
                (
                    "--source-root", ROOT,
                    "--site-root", self.first / "site",
                    "--source-manifest", self.first / "record/source-manifest.json",
                    "--build-record", self.first / "record/build-record.json",
                    "--contract", ROOT / "config/pages-static.json",
                ),
            ),
            "http": (
                "src/pages_http_check.py",
                (
                    "--server-root", self.server_root,
                    "--project-prefix", f"/{PROJECT_PREFIX}/",
                    "--source-site", self.first / "site",
                    "--contract", ROOT / "config/pages-static.json",
                ),
            ),
            "browser": (
                "src/pages_browser_check.py",
                (
                    "--server-root", self.server_root,
                    "--project-prefix", f"/{PROJECT_PREFIX}/",
                    "--contract", ROOT / "config/pages-static.json",
                ),
            ),
        }
        for name, (script, arguments) in result_commands.items():
            sentinel = case_root / f"{name}-sentinel.json"
            sentinel.write_bytes(sentinel_bytes)
            completed = self._run(script, *arguments, "--result", sentinel, expected=3 if name == "oracle" else 2)
            with self.subTest(name=name, kind="existing"):
                self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
                self.assertEqual(completed.stderr, "")
            result_link = case_root / f"{name}-result-link.json"
            result_link.symlink_to(sentinel)
            self._run(script, *arguments, "--result", result_link, expected=3 if name == "oracle" else 2)
            with self.subTest(name=name, kind="symlink"):
                self.assertTrue(result_link.is_symlink())
                self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

        output = case_root / "existing-output"
        output.mkdir()
        output_sentinel = output / "sentinel.json"
        output_sentinel.write_bytes(sentinel_bytes)
        absent_record = case_root / "absent-record"
        self._run(
            "src/pages_build.py",
            "--source-root", ROOT,
            "--contract", ROOT / "config/pages-static.json",
            "--stylesheet", ROOT / "pages/assets/site.css",
            "--output", output,
            "--record-dir", absent_record,
            expected=2,
        )
        self.assertEqual(output_sentinel.read_bytes(), sentinel_bytes)
        self.assertFalse(absent_record.exists())

        existing_record = case_root / "existing-record"
        existing_record.mkdir()
        record_sentinel = existing_record / "sentinel.json"
        record_sentinel.write_bytes(sentinel_bytes)
        absent_output = case_root / "absent-output"
        self._run(
            "src/pages_build.py",
            "--source-root", ROOT,
            "--contract", ROOT / "config/pages-static.json",
            "--stylesheet", ROOT / "pages/assets/site.css",
            "--output", absent_output,
            "--record-dir", existing_record,
            expected=2,
        )
        self.assertEqual(record_sentinel.read_bytes(), sentinel_bytes)
        self.assertFalse(absent_output.exists())

    def test_source_drift_is_rejected_before_semantic_comparison(self):
        source_copy = self.run_root / "source-drift"
        manifest = self._json(self.first / "record/source-manifest.json")
        for row in manifest["files"]:
            relative = row["path"]
            if not relative.endswith(".md"):
                continue
            destination = source_copy / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        with (source_copy / "README.md").open("ab") as output:
            output.write(b"\nsource drift\n")
        result_path = self.run_root / "source-drift-result.json"
        self._run(
            "src/pages_oracle.py",
            "--source-root", source_copy,
            "--site-root", self.first / "site",
            "--source-manifest", self.first / "record/source-manifest.json",
            "--build-record", self.first / "record/build-record.json",
            "--contract", ROOT / "config/pages-static.json",
            "--result", result_path,
            expected=2,
        )
        result = self._json(result_path)
        self.assertEqual(result["status"], "input_error")
        self.assertIn("source pin failures", result["error"]["message"])

    def test_content_mutations_fail_static_and_independent_checks(self):
        case_root = self.run_root / "content-mutations"
        site = case_root / "site"
        shutil.copytree(self.first / "site", site)
        record = case_root / "build-record.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.first / "record/build-record.json", record)

        index_path = site / "index.html"
        index = index_path.read_text(encoding="utf-8")
        self.assertEqual(index.count('href="first-study/index.html">First-study summary'), 1)
        index = index.replace('href="first-study/index.html">First-study summary', 'href="missing/index.html">First-study summary', 1)
        self.assertEqual(index.count(">Need</th>"), 1)
        index = index.replace(">Need</th>", ">Changed Need</th>", 1)
        code_pattern = re.compile(r'(<pre data-source-block-index="\d+" data-source-block-kind="code"><code(?: class="[^"]+")?>)(.)')
        index, code_changes = code_pattern.subn(lambda match: match.group(1) + "X" + match.group(2), index, count=1)
        self.assertEqual(code_changes, 1)
        index_path.write_text(index, encoding="utf-8")

        first_study_path = site / "first-study/index.html"
        first_study = first_study_path.read_text(encoding="utf-8")
        self.assertIn("26과제", first_study)
        first_study = first_study.replace("26과제", "27과제", 1)
        self.assertIn('href="#1차-실험에서-확인한-것"', first_study)
        first_study = first_study.replace('href="#1차-실험에서-확인한-것"', 'href="#missing-fragment"', 1)
        first_study_path.write_text(first_study, encoding="utf-8")

        eda_path = site / "eda/index.html"
        eda = eda_path.read_text(encoding="utf-8")
        eda, image_changes = re.subn(r'(<img [^>]*alt=")[^"]+("[^>]*>)', r'\1Changed alt text\2', eda, count=1)
        self.assertEqual(image_changes, 1)
        eda_path.write_text(eda, encoding="utf-8")
        self._rewrite_build_record(record, site)

        verify_result = case_root / "verify.json"
        self._run(
            "src/pages_verify.py",
            "--source-root", ROOT,
            "--site-root", site,
            "--source-manifest", self.first / "record/source-manifest.json",
            "--build-record", record,
            "--stylesheet", ROOT / "pages/assets/site.css",
            "--contract", ROOT / "config/pages-static.json",
            "--result", verify_result,
            expected=1,
        )
        verify = self._json(verify_result)
        failed = {item["id"] for item in verify["checks"] if item["status"] == "fail"}
        self.assertTrue(
            {
                "html:local_href_src_and_fragments",
                "rendered_documents:block_reverse_comparison",
                "rendered_documents:numeric_tokens",
                "rendered_documents:image_alt_and_target",
            }.issubset(failed)
        )

        oracle_result = case_root / "oracle.json"
        self._run(
            "src/pages_oracle.py",
            "--source-root", ROOT,
            "--site-root", site,
            "--source-manifest", self.first / "record/source-manifest.json",
            "--build-record", record,
            "--contract", ROOT / "config/pages-static.json",
            "--result", oracle_result,
            expected=1,
        )
        oracle = self._json(oracle_result)
        difference_codes = set(oracle["difference_counts"])
        self.assertTrue(
            {
                "visible_block_mismatch",
                "table_cell_mismatch",
                "code_block_mismatch",
                "image_mismatch",
                "link_mismatch",
            }.issubset(difference_codes)
        )

    def test_root_absolute_reference_negative_control_fails_prefix_check(self):
        case_root = self.run_root / "root-absolute-negative"
        site = case_root / "site"
        shutil.copytree(self.first / "site", site)
        index_path = site / "index.html"
        index = index_path.read_text(encoding="utf-8")
        self.assertEqual(index.count('href="assets/site.css"'), 1)
        index_path.write_text(index.replace('href="assets/site.css"', 'href="/assets/site.css"', 1), encoding="utf-8")
        server_root = case_root / "server"
        shutil.copytree(site, server_root / PROJECT_PREFIX)
        result_path = case_root / "http.json"
        self._run(
            "src/pages_http_check.py",
            "--server-root", server_root,
            "--project-prefix", f"/{PROJECT_PREFIX}/",
            "--source-site", site,
            "--contract", ROOT / "config/pages-static.json",
            "--result", result_path,
            expected=1,
        )
        result = self._json(result_path)
        error_codes = {item["code"] for item in result["errors"]}
        self.assertIn("local_reference_outside_prefix", error_codes)
        self.assertEqual(result["logical_references"]["outside_prefix_requests_attempted"], 0)
        self.assertTrue(result["server"]["thread_stopped"])

    def test_independent_oracle_control_fixture_and_mutations(self):
        parser, versions = pages_oracle.load_markdown_parser()
        self.assertEqual(versions, {"markdown-it-py": "3.0.0", "mdurl": "0.1.2"})
        markdown = (ROOT / "tests/fixtures/pages-oracle-control.txt").read_text(encoding="utf-8")
        rendered = (ROOT / "tests/fixtures/pages-oracle-control.html.txt").read_text(encoding="utf-8")
        source_path = "docs/control.md"
        output_path = "documents/docs/control/index.html"
        source_to_output = {source_path: output_path, "docs/guide.md": "documents/docs/guide/index.html"}
        public_paths = {source_path, "docs/guide.md", "figures/example.svg"}

        def compare(html_text: str):
            expected = pages_oracle.parse_markdown_document(parser, source_path, output_path, markdown)
            documents, _ = pages_oracle.parse_rendered_page(output_path, html_text)
            actual = documents[source_path]
            differences, observations = pages_oracle.compare_document(
                expected,
                actual,
                source_to_output,
                public_paths,
                pages_oracle.generated_public_directories(public_paths),
                set(),
            )
            return expected, actual, differences, observations

        expected, actual, differences, observations = compare(rendered)
        self.assertEqual(differences, [])
        self.assertEqual(len(observations), 1)
        self.assertTrue(observations[0]["matched"])
        self.assertEqual(
            [(item.text, item.origin) for item in expected.strong_spans],
            [("강조 문구", "commonmark"), ("강조 문구(예시)", "project_extension")],
        )
        self.assertEqual(
            [(item.text, item.origin) for item in actual.strong_spans],
            [("강조 문구", "rendered_html"), ("강조 문구(예시)", "rendered_html")],
        )
        mutations = (
            ("Backslash *literal*", "Backslash literal", "visible_block_mismatch"),
            ("left | right", "left / right", "table_cell_mismatch"),
            ("code ` delimiter</code>", "code changed</code>", "inline_code_mismatch"),
            ('alt="Diagram"', 'alt="Changed diagram"', "image_mismatch"),
            ("../guide/index.html#target", "../guide/index.html#other", "link_mismatch"),
            ("<strong>강조 문구(예시)</strong>", "강조 문구(예시)", "strong_semantics_mismatch"),
        )
        for original, replacement, expected_code in mutations:
            self.assertEqual(rendered.count(original), 1)
            _, _, found, _ = compare(rendered.replace(original, replacement, 1))
            with self.subTest(expected_code=expected_code):
                self.assertIn(expected_code, {item["code"] for item in found})


class PagesStaticSourceTests(unittest.TestCase):
    def test_record_directory_race_preserves_existing_bytes(self):
        with tempfile.TemporaryDirectory(prefix="pages-static-record-race-") as temporary:
            root = Path(temporary)
            output = root / "output"
            record = root / "record"
            record.mkdir()
            sentinel = record / "sentinel.json"
            sentinel_bytes = b'{"preserve":true}\n'
            sentinel.write_bytes(sentinel_bytes)
            arguments = mock.Mock(
                source_root=ROOT,
                contract=ROOT / "config/pages-static.json",
                stylesheet=ROOT / "pages/assets/site.css",
                output=output,
                record_dir=record,
            )
            real_exists = Path.exists
            first_record_probe = True

            def raced_exists(path: Path) -> bool:
                nonlocal first_record_probe
                if path == record and first_record_probe:
                    first_record_probe = False
                    return False
                return real_exists(path)

            with (
                mock.patch.object(pages_build, "parse_args", return_value=arguments),
                mock.patch.object(Path, "exists", new=raced_exists),
                mock.patch("builtins.print"),
            ):
                self.assertEqual(pages_build.main(), 2)
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
            self.assertEqual([path.name for path in record.iterdir()], ["sentinel.json"])
            self.assertFalse(output.exists())

    def test_contract_preserves_unrecoverable_historical_record(self):
        contract = json.loads((ROOT / "config/pages-static.json").read_text(encoding="utf-8"))
        preserved = contract["preserved_red"]
        self.assertEqual(preserved["known_original_bytes"], 6802)
        self.assertEqual(
            preserved["known_original_sha256"],
            "c50d7f8cb418f1e8857171ec672e5c398f55b6c5c431881226ca89dfc3a34ce6",
        )
        self.assertFalse(preserved["body_recovered"])
        self.assertFalse(preserved["new_execution_is_recovery"])

    def test_pages_workflow_has_no_deploy_or_write_boundary(self):
        workflow = (ROOT / ".github/workflows/pages-static.yml").read_text(encoding="utf-8")
        for forbidden in (
            "actions/deploy-pages",
            "actions/configure-pages",
            "actions/upload-pages-artifact",
            "pages: write",
            "id-token: write",
            "environment:",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("diff -qr", workflow)
        self.assertIn("--require-hashes", workflow)
        self.assertIn("--no-config", workflow)
        self.assertIn("https://pypi.org/simple", workflow)
        self.assertIn("requirements/pages-static.txt", workflow)
        self.assertNotIn("--extra pages", workflow)

        direct = (ROOT / "requirements/pages-static.in").read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            direct,
            ["markdown-it-py==3.0.0", "mdurl==0.1.2", "playwright==1.61.0"],
        )
        locked = (ROOT / "requirements/pages-static.txt").read_text(encoding="utf-8")
        self.assertIn("--only-binary :all:", locked)
        for requirement in (
            "greenlet==3.5.6",
            "markdown-it-py==3.0.0",
            "mdurl==0.1.2",
            "playwright==1.61.0",
            "pyee==13.0.1",
            "typing-extensions==4.16.0",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement + " " + "\\", locked)
        self.assertGreaterEqual(locked.count("--hash=sha256:"), 6)

        root_project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn('pages = ["playwright', root_project)

    def test_public_renderer_sources_do_not_embed_private_runtime_paths(self):
        paths = (
            "config/pages-static.json",
            "pages/assets/site.css",
            "src/pages_build.py",
            "src/pages_verify.py",
            "src/pages_oracle.py",
            "src/pages_http_check.py",
            "src/pages_browser_check.py",
            "tests/test_pages_static.py",
            "requirements/pages-static.in",
            "requirements/pages-static.txt",
            ".github/workflows/pages-static.yml",
            "docs/pages-static.md",
        )
        forbidden = (
            "/tmp/" + "pccb-",
            "/home/" + "dev/",
            ".playwright" + "-cli",
            "signed " + "redirect",
        )
        for relative in paths:
            text = (ROOT / relative).read_text(encoding="utf-8")
            for marker in forbidden:
                with self.subTest(path=relative, marker=marker):
                    self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
