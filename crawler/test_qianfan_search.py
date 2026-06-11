"""千帆客户端：额度守卫 + 响应解析 单测（不打网络）。"""
import os
import unittest

import qianfan_search as qf


class FakeQ:
    def __init__(self, store, table):
        self.store, self.table = store, table

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def upsert(self, row, **k):
        self.store.setdefault("upserts", []).append(row)
        return self

    def execute(self):
        return type("R", (), {"data": self.store.get("_canned", [])})()


class FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, n):
        return FakeQ(self.store, n)


class TestBudget(unittest.TestCase):
    def setUp(self):
        qf.DAILY_CAP = 40

    def test_used_remaining(self):
        sb = FakeSB({"_canned": [{"used": 38}]})
        self.assertEqual(qf.budget_used(sb), 38)
        self.assertEqual(qf.budget_remaining(sb), 2)

    def test_empty_day_full_budget(self):
        self.assertEqual(qf.budget_remaining(FakeSB({"_canned": []})), 40)

    def test_consume_increments(self):
        store = {"_canned": [{"used": 10}]}
        qf.budget_consume(FakeSB(store), 1)
        self.assertEqual(store["upserts"][-1]["used"], 11)

    def test_exhausted(self):
        self.assertEqual(qf.budget_remaining(FakeSB({"_canned": [{"used": 99}]})), 0)


class TestParseAndGuards(unittest.TestCase):
    def test_rows_containers(self):
        self.assertEqual(len(qf._rows({"references": [{"a": 1}]})), 1)
        self.assertEqual(len(qf._rows({"data": {"results": [{"a": 1}, {"b": 2}]}})), 2)
        self.assertEqual(qf._rows({"nope": 1}), [])

    def test_first(self):
        self.assertEqual(qf._first({"url": "", "link": "u"}, "url", "link"), "u")
        self.assertEqual(qf._first({}, "x"), "")

    def test_disabled_and_unconfigured(self):
        os.environ["BAIDU_QIANFAN_SEARCH_DISABLED"] = "true"
        self.assertTrue(qf.is_disabled())
        self.assertFalse(qf.is_configured())
        self.assertEqual(qf.search("x"), [])  # 熔断 → 空，且不发请求
        os.environ.pop("BAIDU_QIANFAN_SEARCH_DISABLED")


if __name__ == "__main__":
    unittest.main()
