"""洞察 T2 worker 编排单测（mock supabase + mock wikidata，不打网络/DB）。"""
import unittest

import insight_backlog as B
import wikidata as W


class FakeQuery:
    def __init__(self, store, table):
        self.store, self.table = store, table
        self._op, self._payload, self._filters = None, None, {}

    def select(self, *a, **k):
        self._op = "select"; return self

    def insert(self, row):
        self.store.setdefault(self.table, []).append(("insert", row)); return self

    def update(self, row):
        self._op, self._payload = "update", row; return self

    def upsert(self, row, **k):
        self.store.setdefault(self.table, []).append(("upsert", row)); return self

    def eq(self, c, v):
        self._filters[c] = v; return self

    def lt(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self._op == "update":
            self.store.setdefault(self.table + "_updates", []).append((dict(self._filters), self._payload))
        data = self.store.get("_canned_" + self.table, [])
        return type("R", (), {"data": data})()


class FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeQuery(self.store, name)


FACTS = {
    "qid": "Q1", "label": "测试集团",
    "wikidata_url": "https://www.wikidata.org/wiki/Q1",
    "listed": True, "exchanges": ["港交所"], "ticker": "9988",
    "founded_year": 2014, "employees": 250000, "headcount_band": "10万+",
    "hq": "杭州", "industry": "电商",
}


class TestWorker(unittest.TestCase):
    def setUp(self):
        self._orig = W.get_company_facts

    def tearDown(self):
        W.get_company_facts = self._orig

    def test_enrich_writes_listing_and_profile(self):
        store = {"_canned_insight_items": []}  # 无既有 wikidata listing → 走 insert
        W.get_company_facts = lambda c, a=None: FACTS
        res = B.enrich_company(FakeSB(store), {"id": "c1", "company": "测试集团", "aliases": []})
        self.assertEqual(res, "ok")
        items = store.get("insight_items", [])
        self.assertTrue(any(op == "insert" and r["dimension"] == "listing" and r["origin"] == "wikidata"
                            for op, r in items))
        # 溯源 + 关联各建一条
        self.assertTrue(store.get("insight_sources"))
        self.assertTrue(store.get("insight_item_sources"))
        # 画像回填含 founded_year + insight_checked_at
        ups = store.get("company_profiles_updates", [])
        self.assertTrue(any("founded_year" in p and "insight_checked_at" in p for _, p in ups))

    def test_noface_marks_checked(self):
        store = {}
        W.get_company_facts = lambda c, a=None: None
        res = B.enrich_company(FakeSB(store), {"id": "c2", "company": "查无", "aliases": []})
        self.assertEqual(res, "noface")
        ups = store.get("company_profiles_updates", [])
        self.assertTrue(any("insight_checked_at" in p for _, p in ups))

    def test_update_existing_listing(self):
        store = {"_canned_insight_items": [{"id": "existing-1"}]}  # 已有 → 走 update 不重复 insert
        W.get_company_facts = lambda c, a=None: FACTS
        res = B.enrich_company(FakeSB(store), {"id": "c3", "company": "测试集团", "aliases": []})
        self.assertEqual(res, "ok")
        self.assertFalse(store.get("insight_items"))  # 没有 insert
        item_updates = store.get("insight_items_updates", [])
        self.assertTrue(any(f.get("id") == "existing-1" for f, _ in item_updates))


if __name__ == "__main__":
    unittest.main()
