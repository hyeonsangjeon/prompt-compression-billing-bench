import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
BRIEFING = ROOT / "docs/experiment/experiment-briefing-20260919.md"
DATA_GUIDE = ROOT / "docs/experiment/data-connection-guide-20260919.md"


class ExperimentBriefingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = BRIEFING.read_text()

    def test_protected_facts_and_denominators_are_present(self):
        required = (
            "5과제·15실행·56요청",
            "0.48%~35.29%",
            "전체 15.42%",
            "후보 전부 삭제 가정 22.83%",
            "5과제 × 20회 = 100",
            "26과제 × 4조건 = 104조건",
            "`pass` 40조건, `wrong_answer` 64조건",
            "23조건의 209구간",
            "`97,723 → 50,824`",
            "각각 1,027회",
            "`$22.3333885`",
            "`$87.771254`",
            "`$0.1294175`",
        )
        for fact in required:
            with self.subTest(fact=fact):
                self.assertIn(fact, self.text)

    def test_claim_limits_and_design_gaps_stay_next_to_results(self):
        for phrase in (
            "조건당 1회",
            "캐시, 요청 수, 모델이 밟은 실행 경로, 조건 간 동시성은 통제하지 못했다",
            "`temperature=0`도 같은 답을 보장하지 않는다",
            "채점기의 거짓 실패 사례",
            "압축의 인과 효과",
            "압축기 순위",
            "품질 비열등성",
            "전체 모집단 절감률",
            "사후 종료",
            "품질 미확정",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        self.assertEqual(len(re.findall(r"^\| [0-9]+\.", self.text, re.MULTILINE)), 10)

    def test_figures_have_alt_text_captions_and_hash_bound_lineage(self):
        self.assertIn("**그림 1 대체 텍스트.**", self.text)
        self.assertIn("```mermaid", self.text)
        self.assertIn("*그림 1.", self.text)
        self.assertIn("**그림 2 대체 텍스트.**", self.text)
        self.assertIn("*그림 2.", self.text)
        figure = ROOT / "docs/eda/figures/round2/02-candidate-share-by-type.svg"
        actual = hashlib.sha256(figure.read_bytes()).hexdigest()
        manifest = json.loads((ROOT / "docs/eda/manifest.json").read_bytes())
        entry = next(item for item in manifest["figures"] if item["path"].endswith("02-candidate-share-by-type.svg"))
        self.assertEqual(actual, entry["sha256"])
        self.assertIn(actual, self.text)
        for fact in ("5과제", "15실행", "56요청", "UTF-8"):
            self.assertIn(fact, entry["alt"])
        self.assertIn("NOT API token share", figure.read_text())

    def test_direct_relative_links_resolve(self):
        documents = (ROOT / "README.md", ROOT / "docs/experiment/README.md", BRIEFING, DATA_GUIDE)
        for document in documents:
            text = document.read_text()
            for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", text):
                if re.match(r"[a-z]+://", target):
                    continue
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / target).resolve().exists())
            for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / target).resolve().is_file())


class DataConnectionGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DATA_GUIDE.read_text()

    def test_sha256_is_defined_before_first_use(self):
        definition = "**파일 지문(SHA-256 해시)**"
        self.assertIn(definition, self.text)
        self.assertEqual(
            self.text.index("SHA-256"),
            self.text.index(definition) + definition.index("SHA-256"),
        )

    def test_existing_single_task_contract_is_reused(self):
        for phrase in (
            "examples/experiment/benchmark.yaml",
            "src/benchmark_run.py",
            "src/screening_run.py",
            "schemas/experiment-result.schema.json",
            "screening_run --diagnose-task",
            "새 실행기나 우회 경로를 만들지 않는다",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_no_call_and_quality_boundaries_are_explicit(self):
        for phrase in (
            "무호출 확인(preflight)",
            "status = checked",
            "outcome = preflight_passed",
            "technical_incomplete",
            "오답으로 바꾸지 않음",
            "quality.status=wrong_answer",
            "quality.status=wrong_format",
            "--execute",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_private_values_and_measurement_units_stay_separate(self):
        for phrase in (
            "고객 데이터 반출 금지",
            "실제 변경 구간 토큰",
            "전체 API usage",
            "계산 비용",
            "실제 청구서",
            "cost.invoice_reconciled=false",
            "관측되지 않은 usage를 0으로 바꾸지 않는다",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        for environment_name in (
            "FOUNDRY_ENDPOINT",
            "SCREENING_OPERATIONAL_LEDGER",
            "TERMINAL_BENCH_ROOT",
            "SCREENING_INVENTORY",
        ):
            self.assertIn(environment_name, self.text)
        self.assertNotRegex(self.text, r"https?://|/Users/|/home/|/ai-work/|/tmp/")

    def test_fixed_benchmark_scope_is_not_presented_as_arbitrary_customer_data(self):
        for phrase in (
            "임의의 고객 데이터 형식을 받는 범용 실행기가 아니다",
            "공개 과제 색인에 없는 과제는 무호출 확인에서 거부된다",
            "별도 검토 필요",
            "반복 없이 조건 간 순위나 비열등성을 말할 수 없다",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
