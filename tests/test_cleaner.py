import unittest

from pipeline.cleaner import (
    cast_values,
    clean,
    drop_duplicates,
    normalize_headers,
    validate,
)
from pipeline.errors import ValidationError


class CleanerTests(unittest.TestCase):
    def test_normalize_headers(self):
        rows = [{"Order ID ": "1", "Total Amount": "10"}]
        self.assertEqual(normalize_headers(rows), [{"order_id": "1", "total_amount": "10"}])

    def test_cast_values(self):
        rows = [{"n": "1 200,5", "flag": "yes", "d": "2026-01-05"}]
        result = cast_values(rows, {"n": "float", "flag": "bool", "d": "date"})
        self.assertEqual(result[0]["n"], 1200.5)
        self.assertTrue(result[0]["flag"])
        self.assertEqual(result[0]["d"], "2026-01-05")

    def test_cast_bad_value_raises(self):
        with self.assertRaises(ValidationError):
            cast_values([{"n": "abc"}], {"n": "int"})

    def test_drop_duplicates_by_key(self):
        rows = [{"id": 1, "v": "a"}, {"id": 1, "v": "b"}, {"id": 2, "v": "c"}]
        self.assertEqual(drop_duplicates(rows, ["id"]), [rows[0], rows[2]])

    def test_full_clean_pipeline(self):
        rows = [
            {"Order ID": " 1 ", "Amount": " 10 ", "Status": "paid"},
            {"Order ID": "1", "Amount": " 10 ", "Status": "paid"},
            {"Order ID": "2", "Amount": "", "Status": "cancelled"},
        ]
        cfg = {
            "cast": {"order_id": "int", "amount": "float"},
            "fill": {"amount": 0},
            "filters": [{"field": "status", "op": "ne", "value": "cancelled"}],
            "drop_duplicates": ["order_id"],
        }
        result = clean(rows, cfg)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], {"order_id": 1, "amount": 10.0, "status": "paid"})

    def test_validate_required(self):
        with self.assertRaises(ValidationError) as ctx:
            validate([{"id": 1}], {"required": ["id", "name"]})
        self.assertIn("name", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
