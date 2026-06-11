"""Wikidata 解析纯逻辑单测（不打网络；HTTP 编排在 CI live 跑）。"""
import unittest

import wikidata as W


def _item(qid):
    return {"mainsnak": {"datavalue": {"value": {"id": qid}}}}


def _str(s):
    return {"mainsnak": {"datavalue": {"value": s}}}


def _time(t):
    return {"mainsnak": {"datavalue": {"value": {"time": t}}}}


def _qty(amount, year=None):
    c = {"mainsnak": {"datavalue": {"value": {"amount": amount}}}}
    if year:
        c["qualifiers"] = {"P585": [{"datavalue": {"value": {"time": f"+{year}-00-00T00:00:00Z"}}}]}
    return c


LISTED_ENTITY = {
    "id": "Q123",
    "labels": {"zh": {"value": "测试集团"}},
    "claims": {
        "P31": [_item("Q891723")],          # public company
        "P414": [_item("Q739514")],         # HKEX → 港交所
        "P249": [_str("9988")],
        "P571": [_time("+2014-04-00T00:00:00Z")],
        "P1128": [_qty("+250000", "2023"), _qty("+100000", "2018")],
        "P159": [_item("Q8686")],
        "P452": [_item("Q9999")],
    },
}
LABEL_MAP = {"Q8686": "上海", "Q9999": "电子商务", "Q739514": "港交所"}

PRIVATE_ENTITY = {
    "id": "Q456",
    "labels": {"zh": {"value": "某未上市公司"}},
    "claims": {"P571": [_time("+2012-00-00T00:00:00Z")]},
}


class TestWikidataParse(unittest.TestCase):
    def test_parse_listed_company(self):
        f = W.parse_company_facts(LISTED_ENTITY, LABEL_MAP)
        self.assertEqual(f["label"], "测试集团")
        self.assertTrue(f["listed"])
        self.assertEqual(f["exchanges"], ["港交所"])
        self.assertEqual(f["ticker"], "9988")
        self.assertEqual(f["founded_year"], 2014)
        self.assertEqual(f["employees"], 250000)        # 取 point-in-time 最新（2023）
        self.assertEqual(f["headcount_band"], "10万+")
        self.assertEqual(f["hq"], "上海")
        self.assertEqual(f["industry"], "电子商务")
        self.assertIn("Q8686", f["_ref_qids"])

    def test_headcount_band(self):
        self.assertEqual(W.headcount_band(250000), "10万+")
        self.assertEqual(W.headcount_band(3000), "1000-5000")
        self.assertEqual(W.headcount_band(80), "1-100")
        self.assertIsNone(W.headcount_band(None))
        self.assertIsNone(W.headcount_band(0))

    def test_facts_to_listing_listed(self):
        f = W.parse_company_facts(LISTED_ENTITY, LABEL_MAP)
        li = W.facts_to_listing(f)
        self.assertEqual(li["dimension"], "listing")
        self.assertEqual(li["grade"], "fact")
        self.assertEqual(li["origin"], "wikidata")
        self.assertEqual(li["payload"]["status"], "listed")
        self.assertIn("已上市", li["content"])
        self.assertIn("港交所", li["content"])
        self.assertIn("9988", li["content"])
        self.assertTrue(li["source_url"].startswith("https://www.wikidata.org/wiki/Q123"))

    def test_facts_to_listing_private(self):
        f = W.parse_company_facts(PRIVATE_ENTITY, {})
        li = W.facts_to_listing(f)
        self.assertEqual(li["payload"]["status"], "private")
        self.assertIn("未", li["content"])

    def test_facts_to_profile(self):
        f = W.parse_company_facts(LISTED_ENTITY, LABEL_MAP)
        p = W.facts_to_profile(f)
        self.assertEqual(p["founded_year"], 2014)
        self.assertEqual(p["headcount_band"], "10万+")
        self.assertEqual(p["hq_location"], "上海")
        self.assertEqual(p["funding_stage"], "已上市")

    def test_no_signal_returns_none(self):
        empty = {"id": "Q0", "labels": {"en": {"value": "Nothing"}}, "claims": {}}
        f = W.parse_company_facts(empty, {})
        self.assertIsNone(W.facts_to_listing(f))


if __name__ == "__main__":
    unittest.main()
