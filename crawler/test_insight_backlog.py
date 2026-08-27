"""洞察 T2 worker 编排单测（mock supabase + mock wikidata，不打网络/DB）。"""
import unittest
from unittest import mock

import insight_backlog as B
import official_cninfo as CN
import official_edgar as OE
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
        self._orig_edgar = OE.get_listing_by_ticker
        self._orig_cn_enabled = CN.enabled
        self._orig_cn_get = CN.get_listing_by_name
        OE.get_listing_by_ticker = lambda t, **k: None  # 默认不命中 EDGAR
        CN.enabled = lambda: False                       # 默认关巨潮 → 测 Wikidata 路径

    def tearDown(self):
        W.get_company_facts = self._orig
        OE.get_listing_by_ticker = self._orig_edgar
        CN.enabled = self._orig_cn_enabled
        CN.get_listing_by_name = self._orig_cn_get

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

    def test_edgar_listing_preferred_over_wikidata(self):
        store = {"_canned_insight_items": []}  # 无既有 listing → insert
        W.get_company_facts = lambda c, a=None: FACTS  # facts 带 ticker → 触发 EDGAR
        OE.get_listing_by_ticker = lambda t, **k: {
            "dimension": "listing", "grade": "fact", "title": "上市状态 · SEC 官方披露",
            "content": "据 SEC EDGAR 官方披露，测试集团 持续申报…", "origin": "official",
            "payload": {"status": "listed", "ticker": t, "latest_filing_date": "2026-03-20"},
            "source_url": "https://www.sec.gov/x", "source_publisher": "SEC EDGAR",
        }
        res = B.enrich_company(FakeSB(store), {"id": "c9", "company": "测试集团", "aliases": []})
        self.assertEqual(res, "ok")
        items = store.get("insight_items", [])
        self.assertTrue(any(op == "insert" and r["dimension"] == "listing" and r["origin"] == "official"
                            for op, r in items))  # 官方源覆盖，origin=official
        self.assertTrue(any(r.get("publisher") == "SEC EDGAR"
                            for op, r in store.get("insight_sources", [])))  # 溯源记 SEC EDGAR

    def test_edgar_financial_employees_override_profile_headcount_band(self):
        store = {"_canned_insight_items": []}
        W.get_company_facts = lambda c, a=None: FACTS  # Wikidata 规模档是 10万+
        OE.get_listing_by_ticker = lambda t, **k: {
            "dimension": "listing", "grade": "fact", "title": "上市状态 · SEC 官方披露",
            "content": "据 SEC EDGAR 官方披露，测试集团 持续申报…", "origin": "official",
            "payload": {
                "status": "listed",
                "ticker": t,
                "financials": {"fy": 2025, "employees": 4200},
            },
            "source_url": "https://www.sec.gov/x", "source_publisher": "SEC EDGAR",
        }
        res = B.enrich_company(FakeSB(store), {"id": "c9", "company": "测试集团", "aliases": []})
        self.assertEqual(res, "ok")
        ups = store.get("company_profiles_updates", [])
        self.assertTrue(
            any(p.get("headcount_band") == "1000-5000" for _, p in ups),
            f"官方员工数应覆盖 Wikidata 规模档，实际 updates={ups}",
        )

    def test_cninfo_listing_when_enabled_and_edgar_misses(self):
        store = {"_canned_insight_items": []}
        # facts 无 ticker → 不触发 EDGAR；巨潮启用 → 走巨潮官方源
        W.get_company_facts = lambda c, a=None: {
            "label": "比亚迪", "ticker": None, "founded_year": 1995, "listed": True, "exchanges": []}
        CN.enabled = lambda: True
        CN.get_listing_by_name = lambda name, aliases=None, **k: {
            "dimension": "listing", "grade": "fact", "title": "上市状态 · 巨潮资讯（官方披露）",
            "content": "据巨潮资讯网，比亚迪 为 A 股上市公司，股票代码 002594（深交所）。",
            "payload": {"status": "listed", "exchange": "深交所", "ticker": "002594"},
            "origin": "official", "source_url": "http://www.cninfo.com.cn/x?stockCode=002594",
            "source_publisher": "巨潮资讯",
        }
        res = B.enrich_company(FakeSB(store), {"id": "cn1", "company": "比亚迪", "aliases": []})
        self.assertEqual(res, "ok")
        items = store.get("insight_items", [])
        self.assertTrue(any(op == "insert" and r["dimension"] == "listing" and r["origin"] == "official"
                            for op, r in items))
        self.assertTrue(any(r.get("publisher") == "巨潮资讯"
                            for op, r in store.get("insight_sources", [])))

    def test_a_share_wikidata_exchange_is_blank_when_cninfo_disabled(self):
        store = {"_canned_insight_items": []}
        W.get_company_facts = lambda c, a=None: {
            **FACTS, "exchanges": ["深交所"], "ticker": "000333",
        }
        res = B.enrich_company(FakeSB(store), {"id": "a1", "company": "美的", "aliases": ["美的集团"]})
        self.assertEqual(res, "ok")
        row = next(r for op, r in store["insight_items"] if op == "insert")
        self.assertIsNone(row["payload"]["exchange"])
        self.assertNotIn("深交所", row["content"])

    def test_a_share_exchange_is_blank_when_wikidata_and_cninfo_disagree(self):
        store = {"_canned_insight_items": []}
        W.get_company_facts = lambda c, a=None: {
            **FACTS, "exchanges": ["上交所"], "ticker": "000333",
        }
        CN.enabled = lambda: True
        CN.get_listing_by_name = lambda *a, **k: {
            "dimension": "listing", "grade": "fact", "title": "上市状态 · 巨潮资讯（官方披露）",
            "content": "据巨潮资讯网，美的集团 为 A 股上市公司，股票代码 000333（深交所）。",
            "payload": {"status": "listed", "exchange": "深交所", "ticker": "000333"},
            "origin": "official", "source_url": "http://www.cninfo.com.cn/x?stockCode=000333",
            "source_publisher": "巨潮资讯",
        }
        res = B.enrich_company(FakeSB(store), {"id": "a2", "company": "美的", "aliases": ["美的集团"]})
        self.assertEqual(res, "ok")
        row = next(r for op, r in store["insight_items"] if op == "insert")
        self.assertIsNone(row["payload"]["exchange"])
        self.assertNotIn("上交所", row["content"])
        self.assertNotIn("深交所", row["content"])

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


import insight_engine as E


class _FakeRouter:
    """替换 B._ROUTER：mock 多源检索结果，隔离 LLM pipeline 与 DB（不打网络）。"""

    def __init__(self, results):
        self._results = results

    def search(self, sb, query, top_k=8, client=None):
        return list(self._results)

    def remaining(self, sb):
        return 999  # 充足额度，让查询包跑满


class TestT3(unittest.TestCase):
    def setUp(self):
        self._orig_router, self._pipeline = B._ROUTER, E.run_pipeline

    def tearDown(self):
        B._ROUTER, E.run_pipeline = self._orig_router, self._pipeline

    def test_enrich_company_t3_writes_culture(self):
        B._ROUTER = _FakeRouter([
            {"title": "t1", "url": "https://a.com/1", "snippet": "加班偏多", "text": "加班偏多", "publisher": "a.com"},
            {"title": "t2", "url": "https://b.com/2", "snippet": "氛围不错", "text": "氛围不错", "publisher": "b.com"},
        ])
        E.run_pipeline = lambda c, d, s, client=None: [{
            "claim": {"content": "据公开讨论该公司强度偏大", "grade": "experience",
                      "source_idx": 0, "sample_size": "6", "quote": "加班偏多"},
            "judge": {"verdict": "entailment", "confidence": 0.8, "supported_source_idxs": [0, 1]}, "status": "active",
        }]
        store = {}
        res = B.enrich_company_t3(FakeSB(store), {"id": "c1", "company": "X", "aliases": []})
        self.assertEqual(res, "wrote")
        items = store.get("insight_items", [])
        self.assertTrue(any(op == "insert" and r["dimension"] == "culture" and r["origin"] == "public_web"
                            for op, r in items))
        # 多维查询包：当前生效的每个主题都该写到它自己的维度（主题清单可由 INSIGHT_T3_TOPICS 调，
        # 所以这里从 T3_QUERY_PACK 现取期望维度，别再写死一组字面量）
        dims = {r["dimension"] for op, r in items if op == "insert"}
        expected_dims = {p["dimension"] for p in B.T3_QUERY_PACK}
        self.assertTrue(expected_dims <= dims, f"应覆盖多维 {expected_dims}，实得 {dims}")
        self.assertTrue(any(op == "insert" and r.get("valid_until") for op, r in items))  # 带过期日(保鲜)
        self.assertTrue(store.get("insight_sources"))   # 多来源已附（过共识门）
        self.assertTrue(any(p.get("status") == "retired"
                            for _f, p in store.get("insight_items_updates", [])))  # 替换旧代退役
        self.assertTrue(any("t3_checked_at" in p for _, p in store.get("company_profiles_updates", [])))

    def test_enrich_company_t3_empty_search(self):
        B._ROUTER = _FakeRouter([])
        store = {}
        res = B.enrich_company_t3(FakeSB(store), {"id": "c2", "company": "Y", "aliases": []})
        self.assertEqual(res, "empty")
        self.assertTrue(any("t3_checked_at" in p for _, p in store.get("company_profiles_updates", [])))

    def test_pick_sources_never_fills_with_unverified_results(self):
        results = [
            {"url": "https://a.example/1", "publisher": "a.example"},
            {"url": "https://b.example/2", "publisher": "b.example"},
        ]
        picked = B._pick_sources(results, {"supported_source_idxs": [0]})
        self.assertEqual(picked, [results[0]])

    def test_t3_does_not_backfill_sample_size_from_search_result_count(self):
        B._ROUTER = _FakeRouter([
            {"url": "https://a.example/1", "publisher": "a.example", "text": "t1"},
            {"url": "https://b.example/2", "publisher": "b.example", "text": "t2"},
        ])
        E.run_pipeline = lambda *a, **k: [{
            "claim": {"content": "据公开讨论…", "grade": "experience", "sample_size": None},
            "judge": {"supported_source_idxs": [0, 1]}, "status": "active",
        }]
        store = {}
        self.assertEqual(B.enrich_company_t3(FakeSB(store), {"id": "c3", "company": "Z", "aliases": []}), "wrote")
        self.assertTrue(store["insight_items"])
        self.assertTrue(all(row["sample_size"] is None for op, row in store["insight_items"] if op == "insert"))

    def test_t3_does_not_write_active_entry_without_enough_judge_sources(self):
        B._ROUTER = _FakeRouter([
            {"url": "https://a.example/1", "publisher": "a.example", "text": "t1"},
            {"url": "https://b.example/2", "publisher": "b.example", "text": "无关"},
        ])
        E.run_pipeline = lambda *a, **k: [{
            "claim": {"content": "据公开讨论…", "grade": "experience", "sample_size": 8},
            "judge": {"supported_source_idxs": [0]}, "status": "active",
        }]
        store = {}
        self.assertEqual(B.enrich_company_t3(FakeSB(store), {"id": "c4", "company": "W", "aliases": []}), "empty")
        self.assertFalse(store.get("insight_items"))

    def test_account_preflight_stops_before_any_search(self):
        search = mock.Mock()
        router = type("Router", (), {
            "is_configured": lambda _self: True,
            "remaining": lambda _self, _sb: 10,
            "search": search,
        })()
        B._ROUTER = router
        E.reset_llm_health()

        def account_failure(*_args, **_kwargs):
            E._record_llm(False, account_error=True)
            raise RuntimeError("HTTP 402 balance insufficient")

        with mock.patch.object(E, "chat_content", side_effect=account_failure):
            with self.assertRaisesRegex(RuntimeError, "搜索前中止"):
                B.drain_t3(FakeSB({}), limit=1)
        search.assert_not_called()

    def test_preflight_success_does_not_mask_all_failing_real_calls(self):
        """探活成功不得计入健康分，否则真实调用全失败时 workflow 反而绿灯。"""
        B._ROUTER = type("Router", (), {
            "is_configured": lambda _self: False,
            "remaining": lambda _self, _sb: 0,
            "search": mock.Mock(),
        })()
        E.reset_llm_health()

        def probe_ok(*_args, **_kwargs):
            E._record_llm(True)      # 真实 chat_content 成功时的内部行为
            return "ok"

        with mock.patch.object(E, "chat_content", side_effect=probe_ok):
            B.drain_t3(FakeSB({}), limit=1)
        self.assertEqual(E.llm_run_health()["ok"], 0, "探活不该留下 ok 计数")

        E._record_llm(False)         # 探活之后的真实调用全部失败（非账户级）
        self.assertTrue(
            E.llm_run_unhealthy(),
            "探活成功 + 真实调用全失败，健康门必须触发，否则故障被绿灯掩盖",
        )


if __name__ == "__main__":
    unittest.main()
