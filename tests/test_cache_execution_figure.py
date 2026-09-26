import hashlib
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ElementTree

from src.cache_execution_figure import (
    CARD_WIDTH,
    CARD_X,
    COPY,
    FACTS,
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
        self.assertEqual(parse_report_record(self.report), REPORT_RECORD)
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
            self.assertEqual(CARD_X + CARD_WIDTH, SVG_WIDTH - CARD_X)
        self.assertEqual(roots["ko"].attrib["viewBox"], roots["en"].attrib["viewBox"])
        self.assertEqual(len(list(roots["ko"].iter())), len(list(roots["en"].iter())))
        self.assertNotEqual(OUTPUTS["ko"].read_bytes(), OUTPUTS["en"].read_bytes())

    def test_report_mutations_fail_closed(self):
        mutations = {
            "changed fact-record count": (
                "| `cycles_valid` | `0` |",
                "| `cycles_valid` | `999` |",
            ),
            "changed visible count": (
                "| Cycles | 10 initially | 1 | 0 | 1 | 0 |",
                "| Cycles | 11 initially | 1 | 0 | 1 | 0 |",
            ),
            "changed unit": ("| `initial_bundles` | `60` |", "| `initial_cycles` | `60` |"),
            "changed status": ("| `not_applicable_tasks` | `3` |", "| `not_applicable_tasks` | `0` |"),
            "wrong source": (
                "| `source_commit` | `e78a32edca9d5ce4f991700e3a299d72164e94be` |",
                "| `source_commit` | `f78a32edca9d5ce4f991700e3a299d72164e94be` |",
            ),
            "missing non-claim": (
                "no Cache-effect comparison was computed",
                "a Cache-effect comparison was computed",
            ),
            "additive cached input": (
                "not additive, not a Cache-effect estimate, and not a miss rate",
                "an additive cached-input total and a Cache-effect estimate",
            ),
            "invalid to valid": (
                "| `terminal_status` | `stopped_invalid_cycle` |",
                "| `terminal_status` | `ready_valid_cycle` |",
            ),
            "causal uncertainty to compression attribution": (
                "The evidence did not isolate whether the request-count difference came from the model, task, transport, namespace, compression, or another mechanism.",
                "The evidence established that compression caused the request-count difference.",
            ),
        }
        for name, (before, after) in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_report(replace_normalized_once(self.report, before, after))

    def test_explanatory_copy_is_not_a_fact_record_lock(self):
        revised = self.report.replace(
            "This run asked whether a provider could reuse work on repeated leading input",
            "This run examined whether a provider could reuse work on repeated leading input",
            1,
        )
        self.assertNotEqual(revised, self.report)
        validate_report(revised)

        causal_rephrasing = replace_normalized_once(
            self.report,
            "The evidence did not isolate whether the request-count difference came from the model, task, transport, namespace, compression, or another mechanism.",
            "The record could not determine which mechanism produced the request-count difference.",
        )
        validate_report(causal_rephrasing)

    def test_contradictory_causal_promotion_is_rejected_with_limit_retained(self):
        promoted = self.report.replace(
            "## Measurement terms",
            "The evidence established that compression caused the request-count difference.\n\n"
            "## Measurement terms",
            1,
        )
        self.assertNotEqual(promoted, self.report)
        with self.assertRaisesRegex(ValueError, "causal promotion"):
            validate_report(promoted)

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
        self.assertIn("여러 요청을 앞에서부터 늘어놓은 열이 아니다", korean)
        self.assertRegex(
            english,
            r"leading compared portion within one (?:individual )?request's serialized message content",
        )
        self.assertIn("not the leading part of a sequence of whole requests", english)
        self.assertIn("No differing prefix or prefix length was measured for the absent pair", english)

    def test_figure_focuses_on_the_comparison_stop_without_losing_reference_facts(self):
        for language, output in OUTPUTS.items():
            content = output.read_text(encoding="utf-8")
            with self.subTest(language=language):
                self.assertIn("18", content)
                self.assertIn("3/5", content)
                self.assertNotIn("not_applicable", content)
                self.assertNotIn("cached input", content)

        korean = KOREAN_PAGE.read_text(encoding="utf-8")
        english = ENGLISH_PAGE.read_text(encoding="utf-8")
        self.assertIn("주 캐시 분석 대상은 `2`과제였고", korean)
        self.assertIn("`3`과제는 `not_applicable`", korean)
        self.assertIn("Two were in the primary", english)
        self.assertIn("three were `not_applicable`", english)
        self.assertIn("`cached input`", korean)
        self.assertIn("`cached input`", english)

    def test_pages_embed_localized_figures_with_complete_text_fallbacks(self):
        expected = {
            KOREAN_PAGE: (
                "../../../../figures/follow-up/cache-execution-denominators-ko.svg",
                "### 그림의 전체 텍스트 대안",
                ("**사이클.** 계획은 유효 `10`개", "**실행 묶음.** 계획은 `60`개", "**과제 실행.** 계획은 `300`개"),
            ),
            ENGLISH_PAGE: (
                "../../../../figures/follow-up/cache-execution-denominators-en.svg",
                "### Complete text alternative",
                ("**Cycles.** The plan called for `10`", "**Bundles.** The plan called for `60`", "**Task trials.** The plan called for `300`"),
            ),
        }
        for page, (target, alternative_heading, denominator_rows) in expected.items():
            content = page.read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertEqual(content.count(target), 2)
                self.assertIn(alternative_heading, content)
                for row in denominator_rows:
                    self.assertIn(row, content)
                self.assertIn("18", content)
                self.assertIn("3/5", content)
                self.assertIn("not_applicable", content)
                self.assertIn("cached input", content)
                self.assertIn("ordinal", content)
                self.assertTrue((page.parent / target).resolve().is_file())
                alt_match = re.search(r"\[!\[(.*?)\]\(" + re.escape(target), content)
                self.assertIsNotNone(alt_match)
                self.assertLessEqual(len(alt_match.group(1)), 220)
        self.assertNotIn("## 상세 분모와 관측값", KOREAN_PAGE.read_text(encoding="utf-8"))
        self.assertNotIn("## Detailed denominators and observations", ENGLISH_PAGE.read_text(encoding="utf-8"))

    def test_check_mode_accepts_the_generated_files(self):
        self.assertEqual(main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
