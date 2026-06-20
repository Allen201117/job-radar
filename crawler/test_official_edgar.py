"""SEC EDGAR 官方披露源解析单测（纯函数，不打网络）。

EDGAR = T2 铁事实：ticker → CIK → submissions → listing 官方确认 + 最新申报新鲜度。
"""
import unittest

import official_edgar as E


class TestFindCik(unittest.TestCase):
    TICKERS = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1577552, "ticker": "BABA", "title": "Alibaba Group Holding Ltd"},
    }

    def test_finds_cik_case_insensitive_zero_padded(self):
        self.assertEqual(E.find_cik(self.TICKERS, "baba"), "0001577552")

    def test_strips_exchange_prefix(self):
        self.assertEqual(E.find_cik(self.TICKERS, "NYSE:BABA"), "0001577552")

    def test_missing_ticker_returns_none(self):
        self.assertIsNone(E.find_cik(self.TICKERS, "ZZZZ"))
        self.assertIsNone(E.find_cik(self.TICKERS, ""))
        self.assertIsNone(E.find_cik({}, "AAPL"))


class TestSubmissionsToListing(unittest.TestCase):
    SUBS = {
        "cik": "1577552", "name": "Alibaba Group Holding Ltd",
        "tickers": ["BABA"], "exchanges": ["NYSE"],
        "filings": {"recent": {"form": ["20-F", "6-K"], "filingDate": ["2025-07-15", "2026-03-20"]}},
    }

    def test_builds_listed_fact_with_latest_filing(self):
        li = E.submissions_to_listing(self.SUBS, "BABA")
        self.assertEqual(li["dimension"], "listing")
        self.assertEqual(li["grade"], "fact")
        self.assertEqual(li["origin"], "official")
        self.assertEqual(li["source_publisher"], "SEC EDGAR")
        self.assertEqual(li["payload"]["status"], "listed")
        self.assertEqual(li["payload"]["exchange"], "NYSE")
        self.assertEqual(li["payload"]["ticker"], "BABA")
        self.assertEqual(li["payload"]["latest_filing_date"], "2026-03-20")  # 取最新日期那条
        self.assertEqual(li["payload"]["latest_form"], "6-K")
        self.assertIn("Alibaba", li["content"])
        self.assertIn("sec.gov", li["source_url"])

    def test_no_exchange_returns_none(self):
        subs = {"name": "X Fund", "tickers": ["XF"], "exchanges": [],
                "filings": {"recent": {"form": ["N-1A"], "filingDate": ["2026-01-01"]}}}
        self.assertIsNone(E.submissions_to_listing(subs, "XF"))  # 无交易所 → 不妄称上市

    def test_listed_without_filings_still_emits(self):
        subs = {"name": "Foo Inc", "tickers": ["FOO"], "exchanges": ["NASDAQ"], "filings": {"recent": {}}}
        li = E.submissions_to_listing(subs, "FOO")
        self.assertEqual(li["payload"]["exchange"], "NASDAQ")
        self.assertIsNone(li["payload"].get("latest_filing_date"))

    def test_empty_or_malformed_returns_none(self):
        self.assertIsNone(E.submissions_to_listing({}, "X"))
        self.assertIsNone(E.submissions_to_listing(None, "X"))


if __name__ == "__main__":
    unittest.main()
