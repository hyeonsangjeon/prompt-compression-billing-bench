import hashlib
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ElementTree

from src.cache_execution_figure import (
    COPY,
    FACTS,
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
KOREAN_PAGE = ROOT / "docs/experiment/02-follow-up/cache-reuse/README.md"
ENGLISH_PAGE = ROOT / "docs_en/experiment/02-follow-up/cache-reuse/README.md"
CONTRACT = ROOT / "docs/cache-reuse.md"


def replace_normalized_once(value: str, before: str, after: str) -> str:
    pattern = r"\s+".join(re.escape(part) for part in before.split())
    result, count = re.subn(pattern, after, value, count=1)
    if count != 1:
        raise AssertionError(f"expected one normalized match for {before!r}, got {count}")
    return result


class CacheExecutionFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.facts = load_facts()

    def test_canonical_report_and_accepted_facts_are_bound(self):
        self.assertEqual(hashlib.sha256(REPORT.read_bytes()).hexdigest(), REPORT_SHA256)
        self.assertEqual(self.facts, FACTS)
        self.assertEqual(self.facts["plan"], {"cycles": 10, "bundles": 60, "task_trials": 300})
        self.assertEqual(
            self.facts["observed"],
            {
                "cycles_attempted": 1,
                "cycles_valid": 0,
                "cycles_invalid": 1,
                "replacement": 0,
                "bundles_started": 2,
                "bundles_complete": 1,
                "bundles_incomplete": 1,
                "task_trials_started": 6,
                "task_trials_complete": 5,
                "task_trials_incomplete": 1,
            },
        )
        self.assertEqual(self.facts["stop"]["ordinal"], 3)
        self.assertEqual(self.facts["stop"]["predecessor_requests"], 2)
        self.assertEqual(self.facts["terminal_status"], "stopped_invalid_cycle")

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
            "changed count": ("| Cycles | 10 initially | 1 | 0 | 1 | 0 |", "| Cycles | 11 initially | 1 | 0 | 1 | 0 |"),
            "changed unit": (
                "10 valid cycles; 60 useful bundles; 300 task trials",
                "10 valid cycles; 60 useful cycles; 300 task trials",
            ),
            "changed status": ("three `not_applicable`", "three `0`"),
            "wrong source": (
                "| Source | Commit `e78a32edca9d5ce4f991700e3a299d72164e94be`; tree `63f969519c93a58faf800ed91cc464f9b955fe2b` |",
                "| Source | Commit `f78a32edca9d5ce4f991700e3a299d72164e94be`; tree `63f969519c93a58faf800ed91cc464f9b955fe2b` |",
            ),
            "missing non-claim": ("the run cannot support a cache comparison", "the run supports a cache comparison"),
            "additive cached input": ("not a Cache-effect estimate or miss rate", "an additive cached-input total"),
            "invalid to valid": ("`stopped_invalid_cycle`", "`ready_valid_cycle`"),
        }
        for name, (before, after) in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_report(replace_normalized_once(self.report, before, after))

    def test_prefix_definition_matches_the_serialized_content_contract(self):
        contract = " ".join(CONTRACT.read_text(encoding="utf-8").split())
        for clause in (
            "stable serialized-prefix byte boundary",
            "common message-content prefix",
            "task ID, logical request ordinal",
            "separately hashes the actual namespaced provider prefix for predecessor equality",
        ):
            self.assertIn(clause, contract)
        korean = " ".join(KOREAN_PAGE.read_text(encoding="utf-8").split())
        english = " ".join(ENGLISH_PAGE.read_text(encoding="utf-8").split())
        self.assertIn("개별 요청의 직렬화된 메시지 내용 안에서 앞부터 비교하는 부분", korean)
        self.assertIn("요청들의 열 자체가 접두부는 아니다", korean)
        self.assertIn("leading compared portion within one request's serialized message content", english)
        self.assertIn("the sequence of requests is not itself the prefix", english)
        self.assertIn("No prefix difference or prefix length was measured for that absent pair", english)

    def test_task_strata_are_wrapped_without_merging_eligible_and_not_applicable(self):
        expected = {
            "ko": ("대상 2", "not_applicable 3"),
            "en": ("2 eligible", "3 not_applicable"),
        }
        for language, lines in expected.items():
            with self.subTest(language=language):
                display = build_display(self.facts, language)
                self.assertEqual(display["context"][2][1], lines)
                content = OUTPUTS[language].read_text(encoding="utf-8")
                self.assertNotIn(" · ".join(lines), content)
                for line in lines:
                    self.assertIn(f'>{line}</text>', content)

    def test_pages_embed_localized_figures_with_complete_text_fallbacks(self):
        expected = {
            KOREAN_PAGE: (
                "../../../../figures/follow-up/cache-execution-denominators-ko.svg",
                "| 단위 | 계획 | 관측·해석 |",
                ("| 사이클 | 유효 10개 |", "| 실행 묶음 | 60개 |", "| 과제 실행 | 300개 |"),
            ),
            ENGLISH_PAGE: (
                "../../../../figures/follow-up/cache-execution-denominators-en.svg",
                "| Unit | Plan | Observation and interpretation |",
                ("| Cycles | 10 valid |", "| Bundles | 60 |", "| Task trials | 300 |"),
            ),
        }
        for page, (target, table_header, denominator_rows) in expected.items():
            content = page.read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertEqual(content.count(target), 2)
                self.assertIn(table_header, content)
                for row in denominator_rows:
                    self.assertIn(row, content)
                self.assertIn("18", content)
                self.assertIn("3/5", content)
                self.assertIn("not_applicable", content)
                self.assertIn("cached input", content)
                self.assertIn("ordinal", content)
                self.assertTrue((page.parent / target).resolve().is_file())

    def test_check_mode_accepts_the_generated_files(self):
        self.assertEqual(main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
