import unittest
from pathlib import Path

from pipeline.pipeline import run
from pipeline.transform import group_by


ROOT = Path(__file__).resolve().parents[1]


class TransformTests(unittest.TestCase):
    def test_group_by(self):
        rows = [
            {"status": "paid", "amount": 10, "id": 1},
            {"status": "paid", "amount": 20, "id": 2},
            {"status": "new", "amount": 5, "id": 3},
        ]
        result = group_by(rows, {"by": ["status"], "aggs": {"amount": "sum", "id": "count"}})
        paid = next(r for r in result if r["status"] == "paid")
        self.assertEqual(paid["amount_sum"], 30)
        self.assertEqual(paid["id_count"], 2)


class IntegrationTests(unittest.TestCase):
    def test_dry_run_example_config(self):
        summary = run(ROOT / "examples" / "config.json", dry_run=True)
        self.assertEqual(summary["rows_out"], 2)
        self.assertEqual(summary["sources"], 1)
        self.assertIn("dry-run", summary["output"])


if __name__ == "__main__":
    unittest.main()
