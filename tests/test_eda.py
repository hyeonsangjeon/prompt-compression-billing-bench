import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.eda import load_aggregates, render


ROOT = Path(__file__).resolve().parents[1]


class AggregateFigureTests(unittest.TestCase):
    def test_figure_is_generated_from_reviewed_byte_counts(self):
        rows, lineage = load_aggregates(ROOT / "data/eda/task-candidate-share.csv", ROOT / "data/eda/lineage.json")
        self.assertEqual(render(rows, lineage), (ROOT / "figures/task-candidate-share.svg").read_text())
        self.assertEqual(sum(row["successful_http_requests"] for row in rows), 56)
        self.assertEqual(sum(row["round2_candidate_utf8_bytes"] for row in rows), 127114)
        shares = [100 * row["round2_candidate_utf8_bytes"] / row["message_content_utf8_bytes"] for row in rows]
        self.assertEqual((round(min(shares), 2), round(max(shares), 2)), (0.48, 35.29))

    def test_aggregate_drift_is_blocked_in_both_directions(self):
        original = (ROOT / "data/eda/task-candidate-share.csv").read_bytes()
        lineage = json.loads((ROOT / "data/eda/lineage.json").read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            table, metadata = Path(temporary) / "table.csv", Path(temporary) / "lineage.json"
            table.write_bytes(original)
            for difference in (-1, 1):
                changed = copy.deepcopy(lineage)
                changed["expected_totals"]["round2_candidate_utf8_bytes"] += difference
                metadata.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "either direction"):
                    load_aggregates(table, metadata)


if __name__ == "__main__":
    unittest.main()
