import unittest
from datetime import datetime, timezone

from campus_official_extract import parse_precise_claims

NOW = datetime(2026, 7, 22, tzinfo=timezone.utc)


class ParsePreciseClaims(unittest.TestCase):
    def _one(self, **kw):
        base = {"season": "秋招", "batch": "正式批", "event": "截止",
                "date_start": "2026-09-10", "date_end": None,
                "value_text": "网申9月10日截止", "quote": "网申截止时间：2026年9月10日"}
        base.update(kw)
        return {"claims": [base]}

    def test_valid_precise_date_derives_month(self):
        out = parse_precise_claims(self._one(), NOW)
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual(c["date_start"], "2026-09-10")
        self.assertEqual(c["month_start"], 9)      # 从日期回填 month
        self.assertIsNone(c["month_end"])

    def test_date_range_fills_both_months(self):
        out = parse_precise_claims(
            self._one(date_start="2026-08-15", date_end="2026-09-10",
                      value_text="网申8月15日–9月10日"), NOW)
        self.assertEqual(out[0]["month_start"], 8)
        self.assertEqual(out[0]["month_end"], 9)

    def test_reject_garbage_far_future(self):
        self.assertEqual(parse_precise_claims(self._one(date_start="3000-01-01"), NOW), [])

    def test_reject_past_cycle_date(self):
        self.assertEqual(parse_precise_claims(self._one(date_start="2025-09-10"), NOW), [])

    def test_reject_bad_enum(self):
        self.assertEqual(parse_precise_claims(self._one(batch="社招"), NOW), [])

    def test_reject_missing_quote(self):
        self.assertEqual(parse_precise_claims(self._one(quote=""), NOW), [])

    def test_reject_bad_date_format(self):
        self.assertEqual(parse_precise_claims(self._one(date_start="2026/9/10"), NOW), [])


if __name__ == "__main__":
    unittest.main()
