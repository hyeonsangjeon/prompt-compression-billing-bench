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
        if not line.startswith("| Condition |"):
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
            re.finditer(r"^## (?:Separate Cohort: )?`([^`]+)`\n", cls.report, re.MULTILINE)
        )
        records = {}
        task_order = []
        for index, match in enumerate(matches):
            task = match.group(1)
            task_order.append(task)
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else cls.report.find("\n## Preserved-Source Token Calculation Evidence", match.end())
            )
            section = cls.report[match.end() : end]
            task_tables = tables(section)
            quality_rows = next(
                rows
                for header, rows in task_tables
                if any(key.startswith("Provider logical requests") for key in header)
            )
            cost_rows = next(
                rows for header, rows in task_tables if "Calculated provider cost" in header
            )
            for quality, cost in zip(quality_rows, cost_rows):
                change_key = next(key for key in quality if "actual changes" in key.lower())
                records[(task, quality["Condition"])] = {
                    "quality": quality["Quality"],
                    "changed": int(quality[change_key].split("/")[-1].strip()),
                    "cost": Decimal(cost["Calculated provider cost"].lstrip("$")),
                }
        return records, task_order

    @classmethod
    def _changed_rows(cls):
        block = cls.report.split(
            "### Before-and-After Token Counts from Preserved Source Text", 1
        )[1].split("## Comparison Conditions and Interpretation Limits", 1)[0]
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
                    int(cells[2].removesuffix(" occurrences")),
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
            "| Conditions among squeez, Headroom, and LLMLingua-2 with zero recorded transformed-string changes | 55 | 20 | 35 | `$12.335` |",
            self.matrix,
        )

    def test_cumulative_pair_accounting_keeps_missing_source_outside_calculable_pairs(self):
        expected = [
            (189, 58, 131),
            (204, 65, 139),
            (213, 71, 142),
            (270, 80, 190),
            (319, 90, 229),
            (394, 107, 287),
            (398, 111, 287),
            (416, 115, 301),
            (441, 121, 320),
            (475, 135, 340),
            (559, 188, 371),
            (621, 201, 420),
            (664, 201, 463),
            (738, 209, 529),
        ]
        observed = [
            tuple(map(int, match))
            for match in re.findall(
                r"The aggregate contained (\d+) calculable input-output pairs: "
                r"(\d+) changed and (\d+) remained identical\. "
                r"A further 166 lacked source pairs\.",
                self.report,
            )
        ]
        self.assertEqual(observed, expected)
        for calculable, changed, identical in observed:
            self.assertEqual(calculable, changed + identical)
        self.assertNotRegex(self.report, r"calculable[^.]*166 lacked source pairs")

    def test_units_claim_limits_and_reading_order_are_visible(self):
        for phrase in (
            "Tasks remain in inventory order",
            "Local tokens in changed spans",
            "not full-request or billed tokens",
            "reduction in changed spans",
            "tiktoken `0.14.0`",
            "`o200k_base`",
            "not reconciled to an actual invoice",
            "ran once",
            "`none` judgment and cost repeat across rows",
            "final two columns are row-level references and must not be summed",
            "do not establish that correlation or causation is absent in general",
            "current public aggregate cannot distinguish them",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.matrix_flat)
        self.assertIn("[task-level changed-condition comparison](metrics.md)", SUMMARY.read_text())
        self.assertIn(
            "| **Total** | **23 conditions** | **209** | **97,723** | **50,824** | **48.0%** | **`pass` 9; `wrong_answer` 14** | **Sum rows separately** | **Do not sum repeated `none` values** | **Do not sum repeated `none` values** |",
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
