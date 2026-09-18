from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/experiment/01-preliminary-comparison/metrics.md"
REPORT = (
    ROOT
    / "docs/experiment/01-preliminary-comparison/preliminary-comparison-20260916.md"
)
SUMMARY = ROOT / "docs/experiment/01-preliminary-comparison/README.md"
INDEX = ROOT / "docs/experiment/README.md"

CONDITIONS = {"none", "squeez", "Headroom", "LLMLingua-2"}
DISPLAY_QUANTUM = Decimal("0.001")


def tables(section):
    lines = section.splitlines()
    found = []
    for index, line in enumerate(lines):
        if not line.startswith("| 조건 |"):
            continue
        header = [cell.strip() for cell in line.strip("|").split("|")]
        rows = []
        for row_line in lines[index + 2 :]:
            if not row_line.startswith("|"):
                break
            cells = [cell.strip() for cell in row_line.strip("|").split("|")]
            if cells and cells[0] in CONDITIONS:
                rows.append(dict(zip(header, cells)))
        if len(rows) == 4:
            found.append((header, rows))
    return found


class FirstStudyMetricMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = MATRIX.read_text()
        cls.matrix_flat = " ".join(cls.matrix.split())
        cls.report = REPORT.read_text()
        cls.records, cls.task_order = cls._records()
        cls.expected_changed = cls._changed_rows()
        cls.actual_changed = cls._matrix_rows()

    @classmethod
    def _records(cls):
        matches = list(
            re.finditer(r"^## (?:별도 집단: )?`([^`]+)`\n", cls.report, re.MULTILINE)
        )
        records = {}
        task_order = []
        for index, match in enumerate(matches):
            task = match.group(1)
            task_order.append(task)
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else cls.report.find("\n## 보존 원문 토큰 계산 자료", match.end())
            )
            section = cls.report[match.end() : end]
            task_tables = tables(section)
            quality_rows = next(
                rows
                for header, rows in task_tables
                if any(key.startswith("provider 논리 요청") for key in header)
            )
            cost_rows = next(
                rows for header, rows in task_tables if "provider 계산 비용" in header
            )
            for quality, cost in zip(quality_rows, cost_rows):
                change_key = next(key for key in quality if "실제 변경" in key)
                records[(task, quality["조건"])] = {
                    "quality": quality["품질"],
                    "changed": int(quality[change_key].split("/")[-1].strip()),
                    "cost": Decimal(cost["provider 계산 비용"].lstrip("$")),
                }
        return records, task_order

    @classmethod
    def _changed_rows(cls):
        block = cls.report.split(
            "### 보존 원문으로 계산한 변환 전후 토큰 수", 1
        )[1].split("## 비교 조건과 해석 한계", 1)[0]
        rows = []
        for line in block.splitlines():
            if not line.startswith("| `"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != 6:
                continue
            task = cells[0].strip("`")
            condition = cells[1]
            before, after = [
                int(value.strip().replace(",", "")) for value in cells[4].split("→")
            ]
            compressed = cls.records[(task, condition)]
            baseline = cls.records[(task, "none")]
            rows.append(
                (
                    task,
                    condition,
                    int(cells[2].removesuffix("건")),
                    before,
                    after,
                    cells[5],
                    compressed["quality"],
                    compressed["cost"].quantize(
                        DISPLAY_QUANTUM, rounding=ROUND_HALF_UP
                    ),
                    baseline["quality"],
                    baseline["cost"].quantize(
                        DISPLAY_QUANTUM, rounding=ROUND_HALF_UP
                    ),
                )
            )
        return rows

    @classmethod
    def _matrix_rows(cls):
        rows = []
        for line in cls.matrix.splitlines():
            if not line.startswith("| [`"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            task_match = re.match(r"\[`([^`]+)`\]\(tasks\.md#[^)]+\)", cells[0])
            if task_match is None:
                raise AssertionError(f"Unexpected task link: {cells[0]}")
            rows.append(
                (
                    task_match.group(1),
                    cells[1],
                    int(cells[2]),
                    int(cells[3].replace(",", "")),
                    int(cells[4].replace(",", "")),
                    cells[5],
                    cells[6].strip("`"),
                    Decimal(cells[7].strip("`").lstrip("$")),
                    cells[8].strip("`"),
                    Decimal(cells[9].strip("`").lstrip("$")),
                )
            )
        return rows

    def test_changed_condition_rows_match_the_technical_evidence(self):
        self.assertEqual(len(self.actual_changed), 23)
        self.assertEqual(self.actual_changed, self.expected_changed)
        self.assertEqual(sum(row[2] for row in self.actual_changed), 209)
        self.assertEqual(sum(row[3] for row in self.actual_changed), 97723)
        self.assertEqual(sum(row[4] for row in self.actual_changed), 50824)
        self.assertEqual(
            [task for task in self.task_order if task in {row[0] for row in self.actual_changed}],
            list(dict.fromkeys(row[0] for row in self.actual_changed)),
        )

    def test_unchanged_compression_conditions_stay_separate(self):
        unchanged = [
            record
            for (task, condition), record in self.records.items()
            if condition != "none" and record["changed"] == 0
        ]
        self.assertEqual(len(unchanged), 55)
        self.assertEqual(sum(row["quality"] == "pass" for row in unchanged), 20)
        self.assertEqual(
            sum(row["quality"] == "wrong_answer" for row in unchanged), 35
        )
        cost = sum((row["cost"] for row in unchanged), Decimal("0")).quantize(
            DISPLAY_QUANTUM, rounding=ROUND_HALF_UP
        )
        self.assertEqual(cost, Decimal("12.335"))
        self.assertIn(
            "| squeez·Headroom·LLMLingua-2 중 기록된 변환 문자열 변경이 0건인 조건 | 55 | 20 | 35 | `$12.335` |",
            self.matrix,
        )

    def test_units_claim_limits_and_reading_order_are_visible(self):
        for phrase in (
            "과제 순서는 기존 inventory 순서",
            "변경 구간 로컬 토큰",
            "전체 요청 토큰이나 청구 토큰이 아니다",
            "변경 구간 기준 감소율",
            "`tiktoken 0.14.0`",
            "`o200k_base`",
            "실제 청구서와 대사한 금액은 아니다",
            "조건당 1회",
            "비교 기준인 `none`의 판정과 비용이 여러 행에 반복된다",
            "마지막 두 열은 행별 비교용이며 합계로 더하지 않는다",
            "상관이나 인과가 없다고 일반화하지 않는다",
            "현재 공개 집계로 두 경우를 나누지는 못한다",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.matrix_flat)
        self.assertIn("[과제별 변경 조건 대조표](metrics.md)", SUMMARY.read_text())
        self.assertIn(
            "| **합계** | **23조건** | **209** | **97,723** | **50,824** | **48.0%** | **`pass` 9 · `wrong_answer` 14** | **별도 행 합계** | **`none` 값은 합산하지 않음** | **`none` 값은 합산하지 않음** |",
            self.matrix,
        )
        self.assertIn(
            "01-preliminary-comparison/metrics.md", INDEX.read_text()
        )

    def test_direct_relative_links_resolve(self):
        for target in re.findall(
            r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", self.matrix
        ):
            if re.match(r"[a-z]+://", target):
                continue
            with self.subTest(target=target):
                self.assertTrue((MATRIX.parent / target).resolve().is_file())


if __name__ == "__main__":
    unittest.main()
