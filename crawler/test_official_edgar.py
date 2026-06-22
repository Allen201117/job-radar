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


class TestFinancials(unittest.TestCase):
    FACTS = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    {"end": "2023-12-31", "val": 1000, "fy": 2023, "fp": "FY", "form": "10-K"},
                    {"end": "2024-12-31", "val": 1200, "fy": 2024, "fp": "FY", "form": "10-K"},
                ]}},
                "NetIncomeLoss": {"units": {"USD": [
                    {"end": "2024-12-31", "val": 150, "fy": 2024, "fp": "FY", "form": "10-K"},
                ]}},
            },
            "dei": {"EntityNumberOfEmployees": {"units": {"pure": [
                {"end": "2024-12-31", "val": 5000, "fy": 2024, "fp": "FY", "form": "10-K"},
            ]}}},
        },
    }

    def test_extracts_latest_annual_with_yoy(self):
        fin = E.financials_from_companyfacts(self.FACTS)
        self.assertEqual(fin["fy"], 2024)
        self.assertEqual(fin["revenue"], 1200)        # 取最新财年
        self.assertEqual(fin["net_income"], 150)
        self.assertEqual(fin["revenue_yoy_pct"], 20)  # (1200-1000)/1000
        self.assertEqual(fin["employees"], 5000)

    def test_alt_revenue_concept(self):
        facts = {"facts": {"us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            {"end": "2024-12-31", "val": 999, "fy": 2024, "fp": "FY", "form": "10-K"}]}}}}}
        self.assertEqual(E.financials_from_companyfacts(facts)["revenue"], 999)

    def test_empty_or_no_annual_returns_none(self):
        self.assertIsNone(E.financials_from_companyfacts({}))
        self.assertIsNone(E.financials_from_companyfacts(None))
        self.assertIsNone(E.financials_from_companyfacts({"facts": {"us-gaap": {}}}))

    def test_sentence_formats_human(self):
        s = E.financials_sentence({"fy": 2024, "revenue": 1_200_000_000, "net_income": 150_000_000,
                                   "revenue_yoy_pct": 20, "employees": 5000})
        self.assertIn("营收", s)
        self.assertIn("同比", s)
        self.assertIn("员工", s)
        self.assertIn("FY2024", s)


if __name__ == "__main__":
    unittest.main()
