"""P4 并发提速：源分档（httpx 并发 / 浏览器串行）+ 单源处理抽取的单测。

不打真实网络：fake adapter + monkeypatch db/robots。重点验证三件事：
  1. _is_httpx_safe 用白名单 fail-safe 分类（未知/浏览器 adapter 一律落串行档，杜绝 Playwright 并发跑崩）。
  2. _partition_by_tier 正确把源拆成 (并发档, 串行档) 且保序（本土优先排序不被打乱）。
  3. _process_one_source 抽取后行为不变：质量门通过的岗位被 upsert，返回聚合计数。
"""
import unittest

import run
from adapters.base import RawJob


class IsHttpxSafeTest(unittest.TestCase):
    def test_httpx_adapters_true(self):
        for a in ("greenhouse", "lever", "workday", "oracle", "hotjob", "wt",
                  "tencent", "baidu", "jd", "apple", "amazon", "microsoft"):
            self.assertTrue(run._is_httpx_safe(a), a)

    def test_browser_and_unknown_false(self):
        # 浏览器 adapter（Playwright，非线程安全）+ 未知/空 → 必须落串行档（fail-safe）
        for a in ("moka", "beisen", "company_spa", "feishu", "nio_feishu",
                  "bytedance", "bytedance_campus", "google", "", "未来新增的源", None):
            self.assertFalse(run._is_httpx_safe(a), a)

    def test_every_known_browser_adapter_is_serial(self):
        # 兜底铁律：凡 fetch 路径会起 sync_playwright 的 adapter，绝不能进并发档。
        for a in ("moka", "beisen", "company_spa", "feishu", "nio_feishu",
                  "xpeng_feishu", "horizon_feishu", "xiaomi_feishu",
                  "bytedance", "bytedance_campus", "google"):
            self.assertNotIn(a, run._HTTPX_SAFE_ADAPTERS, a)


class PartitionByTierTest(unittest.TestCase):
    def test_split_and_order_preserved(self):
        sources = [
            {"adapter_name": "baidu", "id": "1"},      # 并发
            {"adapter_name": "moka", "id": "2"},       # 串行
            {"adapter_name": "workday", "id": "3"},    # 并发
            {"adapter_name": "beisen", "id": "4"},     # 串行
            {"adapter_name": "feishu", "id": "5"},     # 串行
            {"adapter_name": "hotjob", "id": "6"},     # 并发（PlaywrightAdapter 子类但 httpx fetch）
        ]
        concurrent, serial = run._partition_by_tier(sources)
        self.assertEqual([s["id"] for s in concurrent], ["1", "3", "6"])
        self.assertEqual([s["id"] for s in serial], ["2", "4", "5"])


class _FakeAdapter:
    """质量门可通过的假 adapter：parse 出一个在华后端岗。"""

    def should_skip(self, url):
        return None

    def fetch(self, url):
        return "<html>ok</html>"

    def parse(self, html):
        return [RawJob(
            company="测试公司", title="后端工程师", location="上海",
            job_type=None, summary="负责后端服务开发",
            jd_url="https://example.com/job/123",
            apply_url="https://example.com/job/123", posted_at=None,
        )]


class ProcessOneSourceTest(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "create": run.db.create_crawl_run,
            "update": run.db.update_crawl_run,
            "upsert": run.db.upsert_job,
            "ts": run.db.update_source_timestamp,
            "robots": run.check_robots,
        }
        run.db.create_crawl_run = lambda sb, sid: "run-1"
        run.db.update_crawl_run = lambda *a, **k: None
        run.db.upsert_job = lambda sb, data: "created"
        run.db.update_source_timestamp = lambda sb, sid: None
        run.check_robots = lambda url: {"allowed": True, "reason": ""}
        run.ADAPTERS["_fake_httpx"] = _FakeAdapter()

    def tearDown(self):
        run.db.create_crawl_run = self._orig["create"]
        run.db.update_crawl_run = self._orig["update"]
        run.db.upsert_job = self._orig["upsert"]
        run.db.update_source_timestamp = self._orig["ts"]
        run.check_robots = self._orig["robots"]
        run.ADAPTERS.pop("_fake_httpx", None)

    def test_returns_created_count(self):
        source = {"adapter_name": "_fake_httpx", "company": "测试公司",
                  "source_url": "https://example.com/list", "id": "s1"}
        result = run._process_one_source(source, supabase=None)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertIn(result["status"], ("success", "partial_success"))

    def test_unknown_adapter_returns_failed_not_raise(self):
        source = {"adapter_name": "does_not_exist", "company": "X",
                  "source_url": "https://x.com/list", "id": "s2"}
        result = run._process_one_source(source, supabase=None)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["created"], 0)


class _FakeBrowserAdapter(_FakeAdapter):
    """串行档假 adapter：parse 出一个不同 jd_url 的岗（区分并发档）。"""

    def parse(self, html):
        return [RawJob(
            company="浏览器公司", title="前端工程师", location="北京",
            job_type=None, summary="负责前端开发",
            jd_url="https://browser.example.com/job/9",
            apply_url="https://browser.example.com/job/9", posted_at=None,
        )]


class RunCrawlIntegrationTest(unittest.TestCase):
    """端到端跑 run_crawl：并发档(ThreadPoolExecutor) + 串行档 都处理、计数正确聚合。"""

    def setUp(self):
        self._orig_safe = set(run._HTTPX_SAFE_ADAPTERS)
        self._orig = {
            "get_sb": run.db.get_supabase, "get_src": run.db.get_sources,
            "create": run.db.create_crawl_run, "update": run.db.update_crawl_run,
            "upsert": run.db.upsert_job, "ts": run.db.update_source_timestamp,
            "robots": run.check_robots,
        }
        run._HTTPX_SAFE_ADAPTERS.add("_fake_httpx")  # 让假 httpx 源进并发档
        run.db.get_supabase = lambda: "SB"
        run.db.get_sources = lambda sb: [
            {"adapter_name": "_fake_httpx", "company": "A", "source_url": "https://a.com/list", "id": "a"},
            {"adapter_name": "_fake_httpx", "company": "B", "source_url": "https://b.com/list", "id": "b"},
            {"adapter_name": "_fake_browser", "company": "C", "source_url": "https://c.com/list", "id": "c"},
        ]
        run.db.create_crawl_run = lambda sb, sid: f"run-{sid}"
        run.db.update_crawl_run = lambda *a, **k: None
        run.db.upsert_job = lambda sb, data: "created"
        run.db.update_source_timestamp = lambda sb, sid: None
        run.check_robots = lambda url: {"allowed": True, "reason": ""}
        run.ADAPTERS["_fake_httpx"] = _FakeAdapter()
        run.ADAPTERS["_fake_browser"] = _FakeBrowserAdapter()

    def tearDown(self):
        run._HTTPX_SAFE_ADAPTERS.clear()
        run._HTTPX_SAFE_ADAPTERS.update(self._orig_safe)
        run.db.get_supabase = self._orig["get_sb"]
        run.db.get_sources = self._orig["get_src"]
        run.db.create_crawl_run = self._orig["create"]
        run.db.update_crawl_run = self._orig["update"]
        run.db.upsert_job = self._orig["upsert"]
        run.db.update_source_timestamp = self._orig["ts"]
        run.check_robots = self._orig["robots"]
        run.ADAPTERS.pop("_fake_httpx", None)
        run.ADAPTERS.pop("_fake_browser", None)

    def test_both_tiers_processed_and_counted(self):
        summary = run.run_crawl()
        # 3 个源各 upsert 1 岗 → created=3、success=3、failed=0（并发档 2 + 串行档 1 全聚合）
        self.assertEqual(summary["created"], 3)
        self.assertEqual(summary["success"], 3)
        self.assertEqual(summary["failed"], 0)


if __name__ == "__main__":
    unittest.main()
