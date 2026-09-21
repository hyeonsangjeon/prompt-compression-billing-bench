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

from src import pages_build, pages_oracle, pages_verify


ROOT = Path(__file__).resolve().parents[1]
PROJECT_PREFIX = "prompt-compression-billing-bench"
PAGES_RUNTIME_VERSIONS = {
    "markdown-it-py": "3.0.0",
    "mdurl": "0.1.2",
    "playwright": "1.61.0",
}
EXPECTED_SITE_SOURCE_ALLOWLIST = [
    "docs/pages-home.md",
    "docs/pages-static.md",
    "docs/publication.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "third_party/licenses/gsm8k-MIT.txt",
    "third_party/licenses/terminal-bench-2.1-Apache-2.0.txt",
]
EXPECTED_SITE_INVENTORY = {
    "assets/site.css",
    "build-manifest.json",
    "files/LICENSE",
    "files/third_party/index.html",
    "files/third_party/licenses/gsm8k-MIT.txt",
    "files/third_party/licenses/index.html",
    "files/third_party/licenses/terminal-bench-2.1-Apache-2.0.txt",
    "index.html",
    "notices/index.html",
    "publication/index.html",
    "site-contract/index.html",
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
        cls.browser_result = cls.first / "browser.json"
        cls._run(
            "src/pages_browser_check.py",
            "--server-root", cls.server_root,
            "--project-prefix", f"/{PROJECT_PREFIX}/",
            "--contract", ROOT / "config/pages-static.json",
            "--result", cls.browser_result,
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
        self.assertEqual(
            result["scope"]["source_allowlisted_files"],
            len(EXPECTED_SITE_SOURCE_ALLOWLIST),
        )
        self.assertGreater(
            result["scope"]["publication_registry_files"],
            result["scope"]["source_allowlisted_files"],
        )
        self.assertGreater(result["scope"]["markdown_documents"], 0)
        self.assertGreater(result["scope"]["html_pages"], 0)
        self.assertEqual(result["scope"]["browser_visual_rendering"], "not_performed_by_static_verifier")
        checks = {item["id"]: item for item in result["checks"]}
        self.assertGreater(checks["html:local_href_src_and_fragments"]["detail"]["checked"], 0)
        self.assertGreater(checks["rendered_documents:block_reverse_comparison"]["detail"]["table_cells_compared"], 0)
        self.assertEqual(
            checks["rendered_documents:image_alt_and_target"]["detail"]["images_compared"],
            0,
        )
        self.assertEqual(checks["site:svg_static_safety"]["detail"]["checked"], 0)

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
        self.assertIsInstance(observations, list)
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
        self.assertTrue(result["fragment_navigation_probe"]["passed"])
        self.assertTrue(result["trailing_slash_redirect_probe"]["passed"])

    def test_browser_checks_all_public_routes_and_configured_table_route(self):
        result = self._json(self.browser_result)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["route_viewport_checks_total"], 8)
        self.assertEqual(
            result["route_viewport_checks_passed"],
            result["route_viewport_checks_total"],
        )
        self.assertEqual(result["table_keyboard_overflow"]["route"], "/publication/")
        self.assertTrue(result["table_keyboard_overflow"]["passed"])
        self.assertTrue(result["skip_link_keyboard"]["passed"])
        self.assertEqual(
            result["fragment_navigation"]["decoded_hash"],
            "publication-scope",
        )
        self.assertTrue(result["fragment_navigation"]["passed"])

    def test_generated_inventory_contains_only_allowlisted_content(self):
        manifest = self._json(self.first / "record/source-manifest.json")
        self.assertEqual(
            [row["path"] for row in manifest["files"]],
            EXPECTED_SITE_SOURCE_ALLOWLIST,
        )
        self.assertEqual(manifest["source_file_count"], len(EXPECTED_SITE_SOURCE_ALLOWLIST))
        actual_inventory = {
            path.relative_to(self.first / "site").as_posix()
            for path in (self.first / "site").rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual_inventory, EXPECTED_SITE_INVENTORY)
        serialized = "\n".join(sorted(actual_inventory))
        for forbidden in (
            "README.md",
            "STATUS.md",
            "docs/eda/",
            "data/",
            "figures/",
            "docs/experiment/",
            "first-study",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)

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
        with (source_copy / "docs/pages-home.md").open("ab") as output:
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
        scope_link = '<a href="#publication-scope">Jump to the publication scope</a>'
        self.assertEqual(index.count(scope_link), 1)
        index = index.replace(scope_link, '<a href="#missing-scope">Jump to the publication scope</a>', 1)
        index_path.write_text(index, encoding="utf-8")

        publication_path = site / "publication/index.html"
        publication = publication_path.read_text(encoding="utf-8")
        self.assertGreaterEqual(publication.count(">Grade</th>"), 1)
        publication = publication.replace(">Grade</th>", ">Changed Grade</th>", 1)
        publication_path.write_text(publication, encoding="utf-8")

        contract_path = site / "site-contract/index.html"
        contract = contract_path.read_text(encoding="utf-8")
        self.assertEqual(contract.count("Use Python 3.12"), 1)
        contract = contract.replace("Use Python 3.12", "Use Python 3.13", 1)
        code_pattern = re.compile(r'(<pre data-source-block-index="\d+" data-source-block-kind="code"><code(?: class="[^"]+")?>)(.)')
        contract, code_changes = code_pattern.subn(
            lambda match: match.group(1) + "X" + match.group(2),
            contract,
            count=1,
        )
        self.assertEqual(code_changes, 1)
        contract_path.write_text(contract, encoding="utf-8")
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
                "link_mismatch",
            }.issubset(difference_codes)
        )

    def test_ungraded_contract_source_is_rejected_by_builder_and_verifier(self):
        case_root = self.run_root / "ungraded-contract"
        case_root.mkdir()
        contract = self._json(ROOT / "config/pages-static.json")
        contract["source_allowlist"].append("ungraded-site-source.txt")
        mutated = case_root / "pages-static.json"
        mutated.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

        build = self._run(
            "src/pages_build.py",
            "--source-root", ROOT,
            "--contract", mutated,
            "--stylesheet", ROOT / "pages/assets/site.css",
            "--output", case_root / "site",
            "--record-dir", case_root / "record",
            expected=2,
        )
        self.assertIn("not publication-graded", build.stdout)

        verify_result = case_root / "verify.json"
        self._run(
            "src/pages_verify.py",
            "--source-root", ROOT,
            "--site-root", self.first / "site",
            "--source-manifest", self.first / "record/source-manifest.json",
            "--build-record", self.first / "record/build-record.json",
            "--stylesheet", ROOT / "pages/assets/site.css",
            "--contract", mutated,
            "--result", verify_result,
            expected=2,
        )
        verify = self._json(verify_result)
        self.assertIn("not publication-graded", verify["error"])

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
            [("Strong phrase", "commonmark"), ("Strong phrase (example)", "project_extension")],
        )
        self.assertEqual(
            [(item.text, item.origin) for item in actual.strong_spans],
            [("Strong phrase", "rendered_html"), ("Strong phrase (example)", "rendered_html")],
        )
        mutations = (
            ("Backslash *literal*", "Backslash literal", "visible_block_mismatch"),
            ("left | right", "left / right", "table_cell_mismatch"),
            ("code ` delimiter</code>", "code changed</code>", "inline_code_mismatch"),
            ('alt="Diagram"', 'alt="Changed diagram"', "image_mismatch"),
            ("../guide/index.html#target", "../guide/index.html#other", "link_mismatch"),
            ("<strong>Strong phrase (example)</strong>", "Strong phrase (example)", "strong_semantics_mismatch"),
        )
        for original, replacement, expected_code in mutations:
            self.assertEqual(rendered.count(original), 1)
            _, _, found, _ = compare(rendered.replace(original, replacement, 1))
            with self.subTest(expected_code=expected_code):
                self.assertIn(expected_code, {item["code"] for item in found})


class PagesStaticSourceTests(unittest.TestCase):
    def test_contract_has_exact_rights_neutral_allowlist_and_routes(self):
        contract = json.loads((ROOT / "config/pages-static.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["source_allowlist"], EXPECTED_SITE_SOURCE_ALLOWLIST)
        publication_registry = pages_build.extract_public_files(ROOT / "evidence.py")
        self.assertTrue(set(EXPECTED_SITE_SOURCE_ALLOWLIST).issubset(publication_registry))
        self.assertEqual(
            contract["routes"]["primary"],
            {
                "docs/pages-home.md": "/",
                "docs/pages-static.md": "/site-contract/",
                "docs/publication.md": "/publication/",
                "THIRD_PARTY_NOTICES.md": "/notices/",
            },
        )
        self.assertEqual(
            contract["browser_check"]["routes"],
            ["/", "/site-contract/", "/publication/", "/notices/"],
        )
        self.assertEqual(contract["browser_check"]["table_keyboard_route"], "/publication/")
        fragment = contract["probes"]["fragment_navigation"]
        self.assertEqual(fragment["source_file"], "index.html")
        self.assertEqual(fragment["expected_target_file"], "index.html")
        self.assertEqual(fragment["decoded_fragment"], "publication-scope")
        for path in contract["source_allowlist"]:
            with self.subTest(path=path):
                self.assertNotEqual(path, "README.md")
                self.assertNotEqual(path, "STATUS.md")
                self.assertFalse(path.startswith("docs/eda/"))
                self.assertFalse(path.startswith("docs/experiment/"))
                self.assertFalse(path.startswith("data/"))
                self.assertFalse(path.startswith("figures/"))

    def test_homepage_states_scope_and_links_only_to_allowlisted_sources(self):
        homepage = (ROOT / "docs/pages-home.md").read_text(encoding="utf-8")
        self.assertIn("## Publication scope", homepage)
        self.assertIn("](#publication-scope)", homepage)
        for exclusion in (
            "experiment results",
            "exploratory data analysis (EDA)",
            "data files",
            "figures",
            "raw traces",
            "provider artifacts",
            "DeepSWE-derived material",
            "unresolved LLMLingua2 material",
        ):
            with self.subTest(exclusion=exclusion):
                self.assertIn(exclusion, homepage)
        destinations = re.findall(r"\[[^\]]+\]\(([^)]+)\)", homepage)
        self.assertEqual(
            destinations,
            [
                "#publication-scope",
                "pages-static.md",
                "publication.md",
                "../LICENSE",
                "../THIRD_PARTY_NOTICES.md",
                "../third_party/licenses/gsm8k-MIT.txt",
                "../third_party/licenses/terminal-bench-2.1-Apache-2.0.txt",
            ],
        )
        local_targets = {
            pages_build.resolve_source_path("docs/pages-home.md", destination)
            for destination in destinations
            if not destination.startswith("#")
        }
        self.assertTrue(local_targets.issubset(EXPECTED_SITE_SOURCE_ALLOWLIST))

    def test_contract_source_guards_reject_duplicate_unsafe_missing_and_non_regular(self):
        for extractor in (
            pages_build.extract_source_allowlist,
            pages_verify.extract_source_allowlist,
        ):
            error = pages_build.BuildError if extractor is pages_build.extract_source_allowlist else pages_verify.VerificationError
            with self.subTest(extractor=extractor.__module__, kind="duplicate"):
                with self.assertRaises(error):
                    extractor({"source_allowlist": ["docs/site.md", "docs/site.md"]})
            with self.subTest(extractor=extractor.__module__, kind="unsafe"):
                with self.assertRaises(error):
                    extractor({"source_allowlist": ["../site.md"]})

        with tempfile.TemporaryDirectory(prefix="pages-source-guards-") as temporary:
            root = Path(temporary)
            (root / "evidence.py").write_text(
                'PUBLIC_FILES = {"docs/site.md"}\n',
                encoding="utf-8",
            )
            contract = {"source_allowlist": ["docs/site.md"]}

            with self.subTest(kind="missing"):
                with self.assertRaises(FileNotFoundError):
                    pages_build.source_inventory(root, contract)

            docs = root / "docs"
            docs.mkdir()
            target = root / "target.md"
            target.write_text("# target\n", encoding="utf-8")
            site = docs / "site.md"
            site.symlink_to(target)
            with self.subTest(kind="symlink"):
                with self.assertRaises(pages_build.BuildError):
                    pages_build.source_inventory(root, contract)
            site.unlink()

            site.mkdir()
            with self.subTest(kind="non_regular"):
                with self.assertRaises(pages_build.BuildError):
                    pages_build.source_inventory(root, contract)

    def test_primary_route_mutation_is_rejected(self):
        contract = json.loads((ROOT / "config/pages-static.json").read_text(encoding="utf-8"))
        contract["routes"]["primary"]["docs/pages-static.md"] = "/changed/"
        with tempfile.TemporaryDirectory(prefix="pages-route-contract-") as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract) + "\n", encoding="utf-8")
            with self.assertRaises(pages_build.BuildError):
                pages_build.load_contract(path)

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

    def test_pages_workflow_scopes_main_only_deployment_after_checks(self):
        workflow = (ROOT / ".github/workflows/pages-static.yml").read_text(encoding="utf-8")
        header, jobs = workflow.split("jobs:\n", 1)
        build_job, deploy_job = jobs.split("\n  deploy:\n", 1)
        self.assertIn("push:\n    branches:\n      - main", header)
        self.assertIn("pull_request:", header)
        self.assertIn("workflow_dispatch:", header)
        self.assertEqual(header.count("contents: read"), 1)
        self.assertNotIn("pages: write", header)
        self.assertNotIn("id-token: write", header)
        self.assertIn("actions/upload-pages-artifact@v3", build_job)
        self.assertNotIn("actions/deploy-pages", build_job)
        self.assertNotIn("pages: write", build_job)
        self.assertNotIn("id-token: write", build_job)
        self.assertIn("path: ${{ runner.temp }}/pages-static/first/site", build_job)
        self.assertLess(build_job.index("evidence.py audit-files"), build_job.index("actions/upload-pages-artifact"))
        deploy_condition = "if: github.ref == 'refs/heads/main' && github.event_name != 'pull_request'"
        self.assertEqual(workflow.count(deploy_condition), 2)
        self.assertIn("needs: pages-static", deploy_job)
        self.assertIn("pages: write", deploy_job)
        self.assertIn("id-token: write", deploy_job)
        self.assertIn("name: github-pages", deploy_job)
        self.assertIn("actions/deploy-pages@v4", deploy_job)
        self.assertNotIn("actions/checkout", deploy_job)
        self.assertEqual(workflow.count("pages: write"), 1)
        self.assertEqual(workflow.count("id-token: write"), 1)
        self.assertIn("diff -qr", workflow)
        self.assertIn("--require-hashes", workflow)
        self.assertIn("--no-config", workflow)
        self.assertIn("https://pypi.org/simple", workflow)
        self.assertIn("requirements/pages-static.txt", workflow)
        self.assertNotIn("--extra pages", workflow)
        self.assertNotIn('run: "$RUNNER_TEMP', workflow)

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
            "docs/pages-home.md",
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
