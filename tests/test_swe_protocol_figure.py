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
    REPORT_SHA256,
    build_display,
    load_facts,
    main,
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
            font_sizes = [
                int(node.attrib["font-size"])
                for node in roots[language].iter()
                if "font-size" in node.attrib
            ]
            self.assertTrue(font_sizes)
            self.assertGreaterEqual(min(font_sizes), 16)
        self.assertEqual(roots["ko"].attrib["viewBox"], roots["en"].attrib["viewBox"])
        self.assertEqual(len(list(roots["ko"].iter())), len(list(roots["en"].iter())))
        self.assertNotEqual(OUTPUTS["ko"].read_bytes(), OUTPUTS["en"].read_bytes())

    def test_report_mutations_fail_closed(self):
        mutations = {
            "changed count": ("| Runner groups observed | 2 |", "| Runner groups observed | 3 |"),
            "changed unit": ("| Sandbox startup attempts | 2 |", "| Sandbox startup seconds | 2 |"),
            "changed status": ("the runner process exit code is unknown", "the runner process exit code is 0"),
            "wrong source": (
                "| Repository source | Commit `cf8960a6121e91c8ec6a796d470009a27504bf61`; tree `70e0961bf2a3009d9a2c8e36471744be81775daa` |",
                "| Repository source | Commit `df8960a6121e91c8ec6a796d470009a27504bf61`; tree `70e0961bf2a3009d9a2c8e36471744be81775daa` |",
            ),
            "missing non-claim": ("It does not support a candidate pass/fail judgment", "It supports a candidate pass/fail judgment"),
            "invalid to valid": ("| Valid protocol traces | 0 |", "| Valid protocol traces | 1 |"),
            "ungraded to graded": ("must not be quoted as two graded failures", "are two graded failures"),
        }
        for name, (before, after) in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_report(replace_normalized_once(self.report, before, after))

    def test_zero_unknown_and_not_measured_remain_distinct(self):
        self.assertEqual(self.facts["observed"]["provider_model_api_grader_calls"], "0/0/0/0")
        self.assertEqual(self.facts["statuses"]["grader"], "not_run")
        self.assertEqual(self.facts["statuses"]["runner_exit"], "unknown")
        self.assertEqual(self.facts["statuses"]["invoice"], "not_measured")
        self.assertEqual(self.facts["statuses"]["host_cost"], "not_measured")
        self.assertEqual(self.facts["statuses"]["calculated_api_cost"], "USD 0.000000")

    def test_status_and_cost_qualifiers_are_derived_and_wrapped_inside_the_box(self):
        expected = {
            "ko": {
                "status": ("종료 unknown", "품질 not_measured"),
                "cost": ("청구서 not_measured", "호스트 not_measured"),
            },
            "en": {
                "status": ("exit unknown", "quality not_measured"),
                "cost": ("invoice not_measured", "host not_measured"),
            },
        }
        for language, groups in expected.items():
            with self.subTest(language=language):
                display = build_display(self.facts, language)
                self.assertEqual(display["outcomes"][3][2], groups["status"])
                self.assertEqual(display["outcomes"][4][2], groups["cost"])
                content = OUTPUTS[language].read_text(encoding="utf-8")
                for lines in groups.values():
                    self.assertNotIn(" · ".join(lines), content)
                    for line in lines:
                        self.assertIn(f'>{line}</text>', content)
                self.assertEqual(OUTCOME_BOX_WIDTH - 2 * OUTCOME_TEXT_INSET, 264)

    def test_pages_embed_localized_figures_with_complete_text_fallbacks(self):
        expected = {
            KOREAN_PAGE: (
                "../../../../figures/follow-up/swe-protocol-outcome-ko.svg",
                "| 단계·상태 | 계획 | 관측·해석 |",
            ),
            ENGLISH_PAGE: (
                "../../../../figures/follow-up/swe-protocol-outcome-en.svg",
                "| Gate or status | Plan | Observation and interpretation |",
            ),
        }
        for page, (target, table_header) in expected.items():
            content = page.read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertEqual(content.count(target), 2)
                self.assertIn(table_header, content)
                self.assertIn("27/29", content)
                self.assertIn("31/31", content)
                self.assertIn("allow_internet=true", content)
                self.assertIn("disable_internet=true", content)
                self.assertIn("0/0/0/0", content)
                self.assertIn("unknown", content)
                self.assertIn("not_measured", content)
                self.assertIn("not_run", content)
                self.assertTrue((page.parent / target).resolve().is_file())
        korean = KOREAN_PAGE.read_text(encoding="utf-8")
        english = ENGLISH_PAGE.read_text(encoding="utf-8")
        self.assertIn(
            "| 격리 실행 환경 | 고정 실행 1회를 위한 격리 실행 환경 준비 | 시작 시도 2회, 준비 완료 0회, 시작 시간 초과 2회 |",
            korean,
        )
        self.assertNotIn("| 격리 실행 환경 | 시작 시도 2회 |", korean)
        self.assertIn(
            "| Sandbox | Prepare the sandbox for the one fixed execution | 2 startup attempts; 0 ready; 2 startup timeouts |",
            english,
        )
        self.assertNotIn("| Sandbox | 2 startup attempts |", english)

    def test_check_mode_accepts_the_generated_files(self):
        self.assertEqual(main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
