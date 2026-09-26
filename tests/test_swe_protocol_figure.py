import hashlib
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ElementTree

from src.swe_protocol_figure import (
    COPY,
    FACTS,
    OUTCOME_BOX_WIDTH,
    OUTCOME_TEXT_INSET,
    OUTPUTS,
    REPORT,
    REPORT_RECORD,
    REPORT_SHA256,
    SVG_HEIGHT,
    SVG_WIDTH,
    build_display,
    load_facts,
    main,
    parse_report_record,
    render_all,
    validate_report,
)


ROOT = Path(__file__).resolve().parents[1]
KOREAN_PAGE = ROOT / "docs/experiment/02-follow-up/swe-lancer/README.md"
ENGLISH_PAGE = ROOT / "docs_en/experiment/02-follow-up/swe-lancer/README.md"


def replace_normalized_once(value: str, before: str, after: str) -> str:
    pattern = r"\s+".join(re.escape(part) for part in before.split())
    result, count = re.subn(pattern, after, value, count=1)
    if count != 1:
        raise AssertionError(f"expected one normalized match for {before!r}, got {count}")
    return result


class SweProtocolFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.facts = load_facts()

    def test_canonical_report_and_accepted_facts_are_bound(self):
        self.assertEqual(hashlib.sha256(REPORT.read_bytes()).hexdigest(), REPORT_SHA256)
        self.assertEqual(parse_report_record(self.report), REPORT_RECORD)
        self.assertEqual(self.facts, FACTS)
        self.assertEqual(self.facts["plan"]["fixed_executions"], 1)
        self.assertEqual(self.facts["observed"]["initial_checks"], "27/29")
        self.assertEqual(self.facts["observed"]["final_checks"], "31/31")
        self.assertEqual(self.facts["observed"]["runner_groups"], 2)
        self.assertEqual(self.facts["observed"]["valid_protocol_traces"], 0)
        self.assertEqual(self.facts["statuses"]["runner_exit"], "unknown")
        self.assertEqual(self.facts["statuses"]["task_quality"], "not_measured")

    def test_generation_is_exact_and_deterministic(self):
        first = render_all(self.facts)
        second = render_all(load_facts())
        self.assertEqual(first, second)
        self.assertEqual(set(first), set(OUTPUTS))
        for language, content in first.items():
            with self.subTest(language=language):
                self.assertEqual(OUTPUTS[language].read_text(encoding="utf-8"), content)
                self.assertIn(f'<title id="title">{COPY[language]["title"]}</title>', content)
                self.assertIn(f"source-report-sha256:{REPORT_SHA256}", content)

    def test_svg_geometry_accessibility_and_active_content(self):
        roots = {}
        for language, output in OUTPUTS.items():
            content = output.read_text(encoding="utf-8")
            roots[language] = ElementTree.fromstring(content)
            without_namespace = content.replace("http://www.w3.org/2000/svg", "")
            for forbidden in (
                "<script",
                "<foreignObject",
                "<image",
                "href=",
                "url(",
                "http://",
                "https://",
                "<!DOCTYPE",
                "<!ENTITY",
            ):
                with self.subTest(language=language, forbidden=forbidden):
                    self.assertNotIn(forbidden, without_namespace)
            self.assertEqual(roots[language].attrib["role"], "img")
            self.assertEqual(roots[language].attrib["aria-labelledby"], "title desc")
            self.assertEqual(roots[language].attrib["width"], str(SVG_WIDTH))
            self.assertEqual(roots[language].attrib["height"], str(SVG_HEIGHT))
            self.assertEqual(
                roots[language].attrib["viewBox"],
                f"0 0 {SVG_WIDTH} {SVG_HEIGHT}",
            )
            font_sizes = [
                int(node.attrib["font-size"])
                for node in roots[language].iter()
                if "font-size" in node.attrib
            ]
            self.assertTrue(font_sizes)
            self.assertGreaterEqual(min(font_sizes), 17)
            for node in roots[language].iter():
                tag = node.tag.rsplit("}", 1)[-1]
                if tag == "rect":
                    x = int(node.attrib.get("x", 0))
                    y = int(node.attrib.get("y", 0))
                    width = int(node.attrib["width"])
                    height = int(node.attrib["height"])
                    self.assertLessEqual(x + width, SVG_WIDTH)
                    self.assertLessEqual(y + height, SVG_HEIGHT)
                elif tag == "text":
                    self.assertGreaterEqual(int(node.attrib["x"]), 0)
                    self.assertLessEqual(int(node.attrib["x"]), SVG_WIDTH)
            self.assertLessEqual(SVG_WIDTH, 390)
        self.assertEqual(roots["ko"].attrib["viewBox"], roots["en"].attrib["viewBox"])
        self.assertEqual(len(list(roots["ko"].iter())), len(list(roots["en"].iter())))
        self.assertNotEqual(OUTPUTS["ko"].read_bytes(), OUTPUTS["en"].read_bytes())

    def test_report_mutations_fail_closed(self):
        mutations = {
            "changed fact-record count": ("| `runner_groups` | `2` |", "| `runner_groups` | `3` |"),
            "changed visible count": ("| Runner groups observed | 2 |", "| Runner groups observed | 3 |"),
            "changed unit": ("| `sandbox_startup_attempts` | `2` |", "| `sandbox_startup_seconds` | `2` |"),
            "changed status": ("| `runner_exit_status` | `unknown` |", "| `runner_exit_status` | `0` |"),
            "wrong source": (
                "| `source_commit` | `cf8960a6121e91c8ec6a796d470009a27504bf61` |",
                "| `source_commit` | `df8960a6121e91c8ec6a796d470009a27504bf61` |",
            ),
            "missing non-claim": (
                "It does not support a candidate pass/fail judgment",
                "It supports a candidate pass/fail judgment",
            ),
            "invalid to valid": (
                "| `terminal_status` | `invalid_protocol_trace` |",
                "| `terminal_status` | `valid_protocol_trace` |",
            ),
            "ungraded to graded": (
                "The two `correct=False` rows are startup-error placeholders, not graded failures",
                "The two `correct=False` rows are graded failures",
            ),
            "causal uncertainty to attribution": (
                "The evidence did not isolate whether image startup, runtime wiring, container health, network handling, or another mechanism produced the timeouts.",
                "The evidence established that network handling caused the timeouts.",
            ),
            "configured versus observed reversal": (
                "The command configured `disable_internet=true`; the guarded start observed `allow_internet=true`",
                "The command configured `allow_internet=true`; the guarded start observed `disable_internet=true`",
            ),
            "unknown exit to success": (
                "the runner process exit code is unknown",
                "the runner process exit code is 0",
            ),
        }
        for name, (before, after) in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_report(replace_normalized_once(self.report, before, after))

    def test_explanatory_copy_is_not_a_fact_record_lock(self):
        revised = self.report.replace(
            "A software-task benchmark needs more than a model answer.",
            "A software-task benchmark requires more than a model answer.",
            1,
        )
        self.assertNotEqual(revised, self.report)
        validate_report(revised)

        causal_rephrasing = replace_normalized_once(
            self.report,
            "The evidence did not isolate whether image startup, runtime wiring, container health, network handling, or another mechanism produced the timeouts.",
            "The record could not identify which startup-stage mechanism produced the timeouts.",
        )
        validate_report(causal_rephrasing)

    def test_contradictory_causal_promotion_is_rejected_with_limit_retained(self):
        promoted = self.report.replace(
            "## Measurement terms",
            "The evidence established that network handling caused the timeouts.\n\n"
            "## Measurement terms",
            1,
        )
        self.assertNotEqual(promoted, self.report)
        with self.assertRaisesRegex(ValueError, "causal promotion"):
            validate_report(promoted)

    def test_zero_unknown_and_not_measured_remain_distinct(self):
        self.assertEqual(self.facts["observed"]["provider_model_api_grader_calls"], "0/0/0/0")
        self.assertEqual(self.facts["statuses"]["grader"], "not_run")
        self.assertEqual(self.facts["statuses"]["runner_exit"], "unknown")
        self.assertEqual(self.facts["statuses"]["invoice"], "not_measured")
        self.assertEqual(self.facts["statuses"]["host_cost"], "not_measured")
        self.assertEqual(self.facts["statuses"]["calculated_api_cost"], "USD 0.000000")

    def test_visible_statuses_are_derived_and_wrapped_inside_the_box(self):
        expected = {
            "ko": ("채점기 not_run", "종료 unknown", "품질 not_measured"),
            "en": ("grader not_run", "exit unknown", "quality not_measured"),
        }
        for language, lines in expected.items():
            with self.subTest(language=language):
                display = build_display(self.facts, language)
                self.assertEqual(display["outcomes"][3][1], lines)
                content = OUTPUTS[language].read_text(encoding="utf-8")
                self.assertNotIn(" · ".join(lines), content)
                for line in lines:
                    self.assertIn(f'>{line}</text>', content)
                self.assertEqual(OUTCOME_BOX_WIDTH - 2 * OUTCOME_TEXT_INSET, 322)

    def test_pages_embed_localized_figures_with_complete_text_fallbacks(self):
        expected = {
            KOREAN_PAGE: (
                "../../../../figures/follow-up/swe-protocol-outcome-ko.svg",
                "### 그림의 전체 텍스트 대안",
            ),
            ENGLISH_PAGE: (
                "../../../../figures/follow-up/swe-protocol-outcome-en.svg",
                "### Complete text alternative",
            ),
        }
        for page, (target, alternative_heading) in expected.items():
            content = page.read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertEqual(content.count(target), 2)
                self.assertIn(alternative_heading, content)
                self.assertIn("27/29", content)
                self.assertIn("31/31", content)
                self.assertIn("allow_internet=true", content)
                self.assertIn("disable_internet=true", content)
                self.assertIn("0/0/0/0", content)
                self.assertIn("unknown", content)
                self.assertIn("not_measured", content)
                self.assertIn("not_run", content)
                self.assertTrue((page.parent / target).resolve().is_file())
                alt_match = re.search(r"\[!\[(.*?)\]\(" + re.escape(target), content)
                self.assertIsNotNone(alt_match)
                self.assertLessEqual(len(alt_match.group(1)), 220)
        korean = KOREAN_PAGE.read_text(encoding="utf-8")
        english = ENGLISH_PAGE.read_text(encoding="utf-8")
        self.assertIn(
            "**격리 실행 환경.** 고정 실행 `1`회를 위해 환경을 준비하려 했다. 시작 시도는",
            korean,
        )
        self.assertIn(
            "**Sandbox.** The plan was to prepare the sandbox for the one fixed execution.",
            english,
        )
        self.assertNotIn("## 실행 기록", korean)
        self.assertNotIn("## Execution record", english)

    def test_check_mode_accepts_the_generated_files(self):
        self.assertEqual(main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
