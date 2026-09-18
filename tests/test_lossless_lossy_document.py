import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs/experiment/lossless-lossy-compression-20260919.md"
INDEX = ROOT / "docs/experiment/README.md"
SUMMARY = ROOT / "data/experiment/preliminary-comparison-summary.json"
STATIC_REPORT = ROOT / "docs/experiment/compressors.md"


class LosslessLossyDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOCUMENT.read_text(encoding="utf-8")
        cls.summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        cls.static_report = STATIC_REPORT.read_text(encoding="utf-8")

    def test_definitions_and_distinct_boundaries_are_explicit(self):
        required = (
            "무손실 압축",
            "원문과 정확히 같은 바이트",
            "손실 압축",
            "원문과 같은 바이트로 복원된다고 보장할 수 없는",
            "전송 압축",
            "캐시",
            "prompt 내용 축약",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_four_conditions_keep_the_implemented_classification(self):
        expected = (
            "`none`은 입력 문자열을 그대로 돌려준다",
            "`squeez 1.48.4`",
            "분류:** 손실 압축",
            "`Headroom 0.36.5`",
            "경로 전용 제한 설정에서 무손실 압축",
            "`LLMLingua-2 0.2.2`",
            "`rate=0.5`",
        )
        for phrase in expected:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        self.assertGreaterEqual(self.text.count("분류:** 손실 압축"), 2)

    def test_published_change_counts_match_the_aggregate(self):
        by_condition = self.summary["changes"]["by_condition"]
        for condition, display in (
            ("squeez", "squeez"),
            ("Headroom", "Headroom"),
            ("LLMLingua-2", "LLMLingua-2"),
        ):
            values = by_condition[condition]
            section = self.text.split(f"### `{display}`", 1)[1].split("\n### ", 1)[0]
            expected = f"{values['changed_conditions']}조건의 {values['changed_spans']}구간"
            with self.subTest(condition=condition):
                self.assertIn(expected, section)
        self.assertIn("23조건의 209구간", self.text)
        self.assertIn("조건당 1회", self.text)

    def test_static_scope_matches_the_published_measurement(self):
        source_and_document = (
            ("18/107·6/27", "107출현 가운데 18출현, 27고유 입력 가운데 6개"),
            ("10/107·3/27", "10출현·3고유 입력"),
            ("107/107·27/27", "107출현·27고유 입력이 모두 바뀜"),
        )
        for source_phrase, document_phrase in source_and_document:
            with self.subTest(source_phrase=source_phrase):
                self.assertIn(source_phrase, self.static_report)
                self.assertIn(document_phrase, self.text)
        self.assertIn("107/107출현을 역변환했을 때 원문과 byte 단위로 같았고", self.static_report)
        self.assertIn("후보 107출현 모두 복원 일치", self.text)

    def test_units_quality_and_claim_limits_are_not_merged(self):
        for phrase in (
            "로컬 변경 구간 token",
            "전체 API 사용량(usage)",
            "계산 비용",
            "실제 청구서",
            "품질",
            "제품 도입",
            "압축기 순위",
            "품질 비열등성",
            "모집단 비용 절감률",
            "캐시·요청 수·실행 경로·동시성 미통제",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        self.assertEqual(len(re.findall(r"^\| (?:[1-9]|10) \|", self.text, re.MULTILINE)), 10)

    def test_direct_relative_links_resolve(self):
        for document in (INDEX, DOCUMENT):
            text = document.read_text(encoding="utf-8")
            for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", text):
                if re.match(r"[a-z]+://", target):
                    continue
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / target).resolve().is_file())

    def test_document_contains_no_resource_or_private_path_value(self):
        self.assertNotRegex(
            self.text,
            r"https?://|/Users/|/home/|/ai-work/|/tmp/|\.internal\b|"
            r"(?:credential|endpoint|tenant)[_-]?(?:id|url)?\s*[:=]\s*[^`\s]+",
        )


if __name__ == "__main__":
    unittest.main()
