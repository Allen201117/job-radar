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
                  "tencent", "baidu", "jd", "apple", "amazon", "microsoft",
                  "netease", "oppo"):  # netease/oppo: PlaywrightAdapter 子类但自带 httpx fetch（同 hotjob/wt）
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


class ThreadLocalSupabaseTest(unittest.TestCase):
    """并发档每线程独立 supabase 客户端。根因（2026-06-10 实锤，traceback 指向
    httpcore/_sync/http2.py + postgrest）：supabase-py 客户端走 HTTP/2 单连接多路复用，
    被 4 个 worker 线程共享时并发读同一 socket → Errno 35 大面积失败（89/102 源）。"""

    def test_same_thread_same_client_diff_thread_diff_client(self):
        import threading
        created = []
        orig = run.db.get_supabase
        run.db.get_supabase = lambda: created.append(object()) or created[-1]
        try:
            run._TLS.__dict__.clear()  # 清线程局部缓存，避免别的测试污染
            a1 = run._get_thread_supabase()
            a2 = run._get_thread_supabase()
            self.assertIs(a1, a2)  # 同线程复用同一客户端

            box = {}
            def worker():
                box["b"] = run._get_thread_supabase()
            t = threading.Thread(target=worker)
            t.start(); t.join()
            self.assertIsNot(box["b"], a1)  # 不同线程各自独立客户端
            self.assertEqual(len(created), 2)
        finally:
            run.db.get_supabase = orig
            run._TLS.__dict__.clear()


class GroupByHostTest(unittest.TestCase):
    """并发档按主机分队：同主机串行（礼貌爬取，防单服务器被并发打爆——2026-06-10 实锤
    wecruit.hotjob.cn 上 102 源被 4 并发轰出 Errno 35 限流），跨主机并行。"""

    def test_same_host_one_queue_order_kept(self):
        sources = [
            {"id": "1", "source_url": "https://wecruit.hotjob.cn/SU1/pb/social.html"},
            {"id": "2", "source_url": "https://atl.hotjob.cn/SU2/pb/social.html"},
            {"id": "3", "source_url": "https://wecruit.hotjob.cn/SU3/pb/school.html"},
            {"id": "4", "source_url": "https://boards-api.greenhouse.io/v1/boards/x/jobs"},
        ]
        queues = run._group_by_host(sources)
        self.assertEqual(len(queues), 3)  # wecruit / atl / greenhouse 三台主机
        self.assertEqual([s["id"] for s in queues[0]], ["1", "3"])  # 同主机进同队、保序
        self.assertEqual([s["id"] for s in queues[1]], ["2"])
        self.assertEqual([s["id"] for s in queues[2]], ["4"])

    def test_bad_url_gets_own_queue(self):
        queues = run._group_by_host([{"id": "x", "source_url": "not a url"}])
        self.assertEqual(len(queues), 1)


class UpsertRaceTest(unittest.TestCase):
    """db.upsert_job 先查后插非原子：并发下两线程同时插同一岗 → 23505 唯一键冲突。
    修法：insert 撞唯一键时回退为按 canonical_jd_url 重查并 update（幂等），不再向上抛。"""

    def _fake_sb(self, select_rounds, insert_raises):
        """极简 supabase 假件：select 按轮次返回 select_rounds 的下一项；insert 可抛 23505。"""
        calls = {"updates": 0}

        class R:  # execute() 结果
            def __init__(self, data):
                self.data = data

        class Q:
            def __init__(self, mode):
                self.mode = mode

            def select(self, *a):
                return self

            def eq(self, *a):
                return self

            def limit(self, *a):
                return self

            def update(self, *a):
                self.mode = "update"
                return self

            def insert(self, *a):
                self.mode = "insert"
                return self

            def execute(self):
                if self.mode == "select":
                    return R(select_rounds.pop(0) if select_rounds else [])
                if self.mode == "insert":
                    if insert_raises:
                        raise Exception(
                            'duplicate key value violates unique constraint '
                            '"jobs_company_title_location_jd_url_key" (23505)')
                    return R([])
                calls["updates"] += 1
                return R([])

        class SB:
            def table(self, name):
                return Q("select")

        return SB(), calls

    def test_insert_conflict_falls_back_to_update(self):
        import db as dbmod
        # 第一轮 select（按 canonical_jd_url）查不到 → 走 insert → 撞 23505 →
        # 重查（按 canonical_jd_url）查到别的线程刚插的行 → update。
        sb, calls = self._fake_sb(select_rounds=[[], [{"id": "j1"}]], insert_raises=True)
        result = dbmod.upsert_job(sb, {"source_id": "s", "jd_url": "https://x/1", "title": "t"})
        self.assertEqual(result, "updated")
        self.assertEqual(calls["updates"], 1)

    def test_non_duplicate_insert_error_still_raises(self):
        import db as dbmod

        class SB:
            def table(self, name):
                class Q:
                    def select(self, *a):
                        return self

                    def eq(self, *a):
                        return self

                    def insert(self, *a):
                        self.mode = "insert"
                        return self

                    def execute(self):
                        if getattr(self, "mode", "") == "insert":
                            raise Exception("network down")

                        class R:
                            data = []

                        return R()

                return Q()

        with self.assertRaises(Exception):
            dbmod.upsert_job(SB(), {"source_id": "s", "jd_url": "https://x/2", "title": "t"})


class BatchUpsertTest(unittest.TestCase):
    """db.upsert_jobs_batch：批量 upsert 打回快档 <30min（替代逐岗 2 次 REST）。
    验证 created/updated 计数、既有走主键 upsert、批内去重 last-wins、23505 退回逐行兜底。"""

    def _sb(self, select_rounds, insert_raises=False):
        rec = {"inserted": [], "upserted": [], "updated": 0}

        class R:
            def __init__(self, data):
                self.data = data

        class Q:
            def __init__(self):
                self.mode = None
                self.payload = None

            def select(self, *a):
                self.mode = "select"
                return self

            def in_(self, *a):
                return self

            def eq(self, *a):
                return self

            def limit(self, *a):
                return self

            def insert(self, payload):
                self.mode = "insert"
                self.payload = payload
                return self

            def upsert(self, payload, on_conflict=None):
                self.mode = "upsert"
                self.payload = payload
                return self

            def update(self, payload):
                self.mode = "update"
                self.payload = payload
                return self

            def execute(self):
                if self.mode == "select":
                    return R(select_rounds.pop(0) if select_rounds else [])
                if self.mode == "insert":
                    if insert_raises:
                        raise Exception('duplicate key value violates unique constraint '
                                        '"jobs_company_title_location_jd_url_key" (23505)')
                    rec["inserted"].append(self.payload)
                    return R([])
                if self.mode == "upsert":
                    rec["upserted"].append(self.payload)
                    return R([])
                rec["updated"] += 1
                return R([])

        class SB:
            def table(self, name):
                return Q()

        return SB(), rec

    def test_all_new_batch_inserted(self):
        import db as dbmod
        sb, rec = self._sb(select_rounds=[[]])  # 批量 select 查不到 → 全 new
        jobs = [
            {"source_id": "s", "jd_url": "https://x/1", "company": "C", "title": "t1"},
            {"source_id": "s", "jd_url": "https://x/2", "company": "C", "title": "t2"},
        ]
        created, updated = dbmod.upsert_jobs_batch(sb, jobs)
        self.assertEqual((created, updated), (2, 0))
        self.assertEqual(len(rec["inserted"]), 1)     # 一次批量 insert（非逐行）
        self.assertEqual(len(rec["inserted"][0]), 2)  # 含 2 行
        self.assertEqual(rec["upserted"], [])

    def test_existing_go_through_pk_upsert(self):
        import db as dbmod
        sb, rec = self._sb(select_rounds=[[
            {"id": "j1", "canonical_jd_url": "https://x/1", "status": "active"},
            {"id": "j2", "canonical_jd_url": "https://x/2", "status": "active"},
        ]])
        jobs = [
            {"source_id": "s", "jd_url": "https://x/1", "company": "C", "title": "t1"},
            {"source_id": "s", "jd_url": "https://x/2", "company": "C", "title": "t2"},
        ]
        created, updated = dbmod.upsert_jobs_batch(sb, jobs)
        self.assertEqual((created, updated), (0, 2))
        self.assertEqual(len(rec["upserted"]), 1)            # 一次批量 upsert
        self.assertEqual(rec["upserted"][0][0]["id"], "j1")  # 带既有主键 id
        self.assertEqual(rec["inserted"], [])

    def test_matches_existing_by_canonical_not_raw_jd_url(self):
        import db as dbmod
        # 既有行 canonical 是干净链接；新抓到的同岗带了 utm tracking 参数。
        # 冲突键 = canonical_jd_url（非原样 jd_url）→ 归一后命中既有行 → update，不会误插成新岗。
        sb, rec = self._sb(select_rounds=[[
            {"id": "j1", "canonical_jd_url": "https://x/1", "status": "active"},
        ]])
        jobs = [{"source_id": "s", "jd_url": "https://x/1?utm_source=li", "company": "C", "title": "t"}]
        created, updated = dbmod.upsert_jobs_batch(sb, jobs)
        self.assertEqual((created, updated), (0, 1))
        self.assertEqual(rec["upserted"][0][0]["id"], "j1")
        self.assertEqual(rec["inserted"], [])

    def test_prefers_active_row_among_same_canonical(self):
        import db as dbmod
        # 同 canonical 既有 active + removed 历史行（迁移 dedup 的产物）→ 命中 active 那行 update，
        # 不去复活 removed 行（否则会撞 active partial unique index）。
        sb, rec = self._sb(select_rounds=[[
            {"id": "old_removed", "canonical_jd_url": "https://x/1", "status": "removed"},
            {"id": "live", "canonical_jd_url": "https://x/1", "status": "active"},
        ]])
        jobs = [{"source_id": "s", "jd_url": "https://x/1", "company": "C", "title": "t"}]
        created, updated = dbmod.upsert_jobs_batch(sb, jobs)
        self.assertEqual((created, updated), (0, 1))
        self.assertEqual(rec["upserted"][0][0]["id"], "live")

    def test_intra_batch_dedup_last_wins(self):
        import db as dbmod
        sb, rec = self._sb(select_rounds=[[]])
        jobs = [  # 同 (source_id, jd_url) 两次 → 去重成 1 行，last-wins
            {"source_id": "s", "jd_url": "https://x/1", "company": "C", "title": "旧"},
            {"source_id": "s", "jd_url": "https://x/1", "company": "C", "title": "新"},
            {"source_id": "s", "jd_url": "https://x/2", "company": "C", "title": "t2"},
        ]
        created, updated = dbmod.upsert_jobs_batch(sb, jobs)
        self.assertEqual((created, updated), (2, 0))
        self.assertEqual(len(rec["inserted"][0]), 2)
        titles = {r["title"] for r in rec["inserted"][0]}
        self.assertIn("新", titles)
        self.assertNotIn("旧", titles)

    def test_insert_23505_falls_back_to_rowwise(self):
        import db as dbmod
        # 批量 insert 撞 23505 → 退回逐行 upsert_job：其按 jd_url 重查命中别 worker 刚插的行 → update。
        sb, rec = self._sb(select_rounds=[[], [{"id": "jX"}]], insert_raises=True)
        jobs = [{"source_id": "s", "jd_url": "https://x/1", "company": "C", "title": "t1"}]
        created, updated = dbmod.upsert_jobs_batch(sb, jobs)
        self.assertEqual((created, updated), (0, 1))  # 兜底走 update


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
            "upsert_batch": run.db.upsert_jobs_batch,
            "ts": run.db.update_source_timestamp,
            "robots": run.check_robots,
        }
        run.db.create_crawl_run = lambda sb, sid: "run-1"
        run.db.update_crawl_run = lambda *a, **k: None
        run.db.upsert_jobs_batch = lambda sb, jobs: (len(jobs), 0)
        run.db.update_source_timestamp = lambda sb, sid: None
        run.check_robots = lambda url: {"allowed": True, "reason": ""}
        run.ADAPTERS["_fake_httpx"] = _FakeAdapter()

    def tearDown(self):
        run.db.create_crawl_run = self._orig["create"]
        run.db.update_crawl_run = self._orig["update"]
        run.db.upsert_jobs_batch = self._orig["upsert_batch"]
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

    def test_db_create_crawl_run_raises_not_propagate(self):
        # 高负载实锤 bug（2026-06-10 hotjob 全量并发跑崩）：db.create_crawl_run 在 try 外，
        # Supabase 瞬时错误(Errno 35)抛穿「永不抛异常」约定 → ex.map 炸整批。必须吞掉返回 failed。
        def boom(sb, sid):
            raise OSError(35, "Resource temporarily unavailable")
        run.db.create_crawl_run = boom
        source = {"adapter_name": "_fake_httpx", "company": "测试公司",
                  "source_url": "https://example.com/list", "id": "s3"}
        result = run._process_one_source(source, supabase=None)
        self.assertEqual(result["status"], "failed")

    def test_db_update_crawl_run_raises_in_failure_path_not_propagate(self):
        # 失败路径里 update_crawl_run 自己也可能抛（同样的瞬时 DB 错误）→ 也不能炸穿。
        class _BoomAdapter(_FakeAdapter):
            def fetch(self, url):
                raise RuntimeError("fetch 炸了")
        def boom_update(*a, **k):
            raise OSError(35, "Resource temporarily unavailable")
        run.ADAPTERS["_fake_boom"] = _BoomAdapter()
        run.db.update_crawl_run = boom_update
        try:
            source = {"adapter_name": "_fake_boom", "company": "X",
                      "source_url": "https://x.com/list", "id": "s4"}
            result = run._process_one_source(source, supabase=None)
            self.assertEqual(result["status"], "failed")
        finally:
            run.ADAPTERS.pop("_fake_boom", None)


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
            "upsert_batch": run.db.upsert_jobs_batch, "ts": run.db.update_source_timestamp,
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
        run.db.upsert_jobs_batch = lambda sb, jobs: (len(jobs), 0)
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
        run.db.upsert_jobs_batch = self._orig["upsert_batch"]
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

    def test_tier_httpx_runs_only_concurrent(self):
        # 快档 daily：tier=httpx 只跑并发档(2 个 _fake_httpx)，浏览器串行档被跳过。
        summary = run.run_crawl(tier="httpx")
        self.assertEqual(summary["created"], 2)
        self.assertEqual(summary["success"], 2)
        self.assertEqual(summary["failed"], 0)

    def test_tier_browser_runs_only_serial(self):
        # 重档 browser：只跑串行浏览器档(1 个 _fake_browser)，httpx 并发档被跳过。
        summary = run.run_crawl(tier="browser")
        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["success"], 1)
        self.assertEqual(summary["failed"], 0)

    def test_shard_round_robin_covers_all_without_overlap(self):
        # 源分片轮转 1/2：片 0 = 并发[0::2]=[a] + 串行[0::2]=[c] → 2 源；片 1 = 并发[1::2]=[b] + 串行[]→ 1 源。
        # 两片并集 = 全量 3 源（无重复、无遗漏），即 1/shard_count 轮转一周覆盖全量。
        s0 = run.run_crawl(shard_index=0, shard_count=2)
        s1 = run.run_crawl(shard_index=1, shard_count=2)
        self.assertEqual(s0["created"], 2)
        self.assertEqual(s1["created"], 1)
        self.assertEqual(s0["created"] + s1["created"], 3)

    def test_shard_index_wraps_modulo_count(self):
        # shard_index 越界(=shard_count)按模回绕到 0，不至于取到空片（重档按星期几 %w 传 0-6，配 7 片不越界，此为兜底）。
        wrapped = run.run_crawl(shard_index=2, shard_count=2)   # 2 % 2 == 0 → 同片 0
        self.assertEqual(wrapped["created"], 2)


if __name__ == "__main__":
    unittest.main()
