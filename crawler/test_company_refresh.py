"""CompanyRefreshRecipe 单测（不打网络）：httpx-first 排序 / 跨源去重 / 增量心跳 / 状态判定。"""
import unittest
from unittest import mock

import discovery
from adapters.base import RawJob


def _raw(jd_url, title="工程师", company="X"):
    return RawJob(company=company, title=title, location="北京", jd_url=jd_url)


def FakeAdapter(jobs, raise_exc=None):
    """Mock adapter 工厂：数据存类属性，使生产代码每源 type(adapter)() 重建实例时仍能复现
    （并发档对每个源新建独立实例隔离状态，见 discovery.py CompanyRefreshRecipe._fetch_one）。"""
    class _FA:
        _jobs = list(jobs)
        _raise = raise_exc

        def fetch(self, url):
            if type(self)._raise:
                raise type(self)._raise
            return "html"

        def parse(self, html):
            return list(type(self)._jobs)

    return _FA()


class CompanyRefreshRecipeTests(unittest.TestCase):
    def setUp(self):
        self.updates = []  # 记录 update_discovery_run 的 fields
        p1 = mock.patch.object(
            discovery.db, "update_discovery_run",
            side_effect=lambda sb, rid, **f: self.updates.append(f),
        )
        p1.start(); self.addCleanup(p1.stop)
        p2 = mock.patch.object(discovery.db, "upsert_job", return_value="created")
        p2.start(); self.addCleanup(p2.stop)
        # Phase 1：CompanyRefreshRecipe 写入已 gated 到自建香港库（discovery.py:380 jobs_db.upsert_job）。
        # 单测须 hermetic：jobs_db._load_env() 会读 .env.local，本机有 JOBS_DATABASE_URL 时 enabled()=True
        # → 连真库（fake source_id 触发 uuid 错）。强制 enabled=False 走上面已 mock 的 db.upsert_job 分支
        # （与 test_run_concurrency.py 同款做法）。
        p2b = mock.patch.object(discovery.jobs_db, "enabled", return_value=False)
        p2b.start(); self.addCleanup(p2b.stop)
        p3 = mock.patch.object(
            discovery.normalizer, "validate_job_quality", return_value=(True, ""),
        )
        p3.start(); self.addCleanup(p3.stop)

    def _run(self, rows, adapters):
        import run as runmod
        with mock.patch.object(discovery.db, "get_sources_by_ids", return_value=rows), \
                mock.patch.object(runmod, "_get_thread_supabase", return_value=None), \
                mock.patch.dict(runmod.ADAPTERS, adapters, clear=False):
            recipe = discovery.CompanyRefreshRecipe()
            return recipe.run(
                supabase=None, run_id="r1",
                source_ids=[r["id"] for r in rows],
                filters={}, base_diag={"source_ids": [r["id"] for r in rows]},
            )

    def test_httpx_first_and_dedup_and_heartbeats(self):
        rows = [
            {"id": "sa", "adapter_name": "beisen", "company": "北森A", "source_url": "https://a.zhiye.com/j"},
            {"id": "sb", "adapter_name": "workday", "company": "WD-B", "source_url": "https://b.wd.com/j"},
        ]
        adapters = {
            "beisen": FakeAdapter([_raw("https://a.zhiye.com/job/1"), _raw("https://shared/job/x")]),
            "workday": FakeAdapter([_raw("https://b.wd.com/job/1"), _raw("https://shared/job/x")]),
        }
        result = self._run(rows, adapters)

        # httpx(workday) 先于 browser(beisen)：produced 首个来自 workday
        self.assertEqual(result["produced_jd_urls"][0], "https://b.wd.com/job/1")
        # 跨源去重：shared/job/x 只出现一次
        self.assertEqual(result["produced_jd_urls"],
                         ["https://b.wd.com/job/1", "https://shared/job/x", "https://a.zhiye.com/job/1"])
        self.assertEqual(result["status"], "success")
        # 去重只作用于「流式 produced 列表」（避免同一 jd_url 重复成卡片）；jobs_created 按各源独立 upsert
        # 计数（本测 mock 一律返回 created）→ workday 2 + beisen 2 = 4。真实库里 shared 会是 1 created + 1 updated。
        self.assertEqual(result["jobs_created"], 4)

        # 增量心跳：每源一次 running 写入，progress.done 递增
        running = [u for u in self.updates if u.get("status") == "running"]
        self.assertEqual(len(running), 2)
        self.assertEqual([u["diagnostics"]["progress"]["done"] for u in running], [1, 2])
        self.assertTrue(all(u["diagnostics"]["progress"]["total"] == 2 for u in running))
        self.assertTrue(all("last_update_at" in u["diagnostics"] for u in running))

    def test_single_source_failure_is_partial(self):
        rows = [
            {"id": "sa", "adapter_name": "workday", "company": "好源", "source_url": "https://ok.wd.com/j"},
            {"id": "sb", "adapter_name": "beisen", "company": "坏源", "source_url": "https://bad.zhiye.com/j"},
        ]
        adapters = {
            "workday": FakeAdapter([_raw("https://ok.wd.com/job/1")]),
            "beisen": FakeAdapter([], raise_exc=RuntimeError("boom")),
        }
        result = self._run(rows, adapters)
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["produced_jd_urls"], ["https://ok.wd.com/job/1"])
        self.assertIn("beisen", result["error_message"])

    def test_no_new_jobs_is_success_not_failed(self):
        rows = [{"id": "sa", "adapter_name": "workday", "company": "空源", "source_url": "https://e.wd.com/j"}]
        adapters = {"workday": FakeAdapter([])}
        result = self._run(rows, adapters)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["produced_jd_urls"], [])

    def test_all_sources_fail_is_failed(self):
        rows = [{"id": "sa", "adapter_name": "workday", "company": "坏", "source_url": "https://x.wd.com/j"}]
        adapters = {"workday": FakeAdapter([], raise_exc=RuntimeError("down"))}
        result = self._run(rows, adapters)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "all_sources_failed")

    def test_httpx_sources_concurrent_all_fetched_and_deduped(self):
        import run as runmod
        rows = [
            {"id": "s1", "adapter_name": "workday", "company": "A", "source_url": "https://a.wd.com/j"},
            {"id": "s2", "adapter_name": "greenhouse", "company": "B", "source_url": "https://b.gh.io/j"},
            {"id": "s3", "adapter_name": "lever", "company": "C", "source_url": "https://c.lever.co/j"},
        ]
        adapters = {
            "workday": FakeAdapter([_raw("https://a/1"), _raw("https://dup/x")]),
            "greenhouse": FakeAdapter([_raw("https://b/1"), _raw("https://dup/x")]),
            "lever": FakeAdapter([_raw("https://c/1")]),
        }
        # 强制三源都走 httpx 并发档（不依赖真实白名单），验证并发抓取：全抓到 + 跨源去重 + 心跳 done 递增。
        with mock.patch.object(runmod, "_is_httpx_safe", side_effect=lambda n: True):
            result = self._run(rows, adapters)
        self.assertEqual(result["status"], "success")
        self.assertEqual(
            set(result["produced_jd_urls"]),
            {"https://a/1", "https://b/1", "https://c/1", "https://dup/x"},
        )
        self.assertEqual(len(result["produced_jd_urls"]), 4)  # dup/x 跨源去重只一次
        self.assertEqual(result["jobs_created"], 5)  # 2+2+1，各源独立 upsert 计数
        running = [u for u in self.updates if u.get("status") == "running"]
        self.assertEqual(len(running), 3)
        self.assertEqual(sorted(u["diagnostics"]["progress"]["done"] for u in running), [1, 2, 3])

    def test_produced_only_includes_created_not_updated(self):
        # 「刷新对口公司」只把【真新增(created)】岗位算进「带回」(produced)，重抓到的旧岗位(updated)不充数
        # ——治用户痛点：等半天「带回 199」、实际真新增才 2。
        rows = [{"id": "s1", "adapter_name": "workday", "company": "A", "source_url": "https://a.wd.com/j"}]
        adapters = {"workday": FakeAdapter([_raw("https://new/1"), _raw("https://old/1")])}

        def fake_upsert(_sb, job):
            return "created" if "new" in (job.get("jd_url") or "") else "updated"

        with mock.patch.object(discovery.db, "upsert_job", side_effect=fake_upsert):
            result = self._run(rows, adapters)
        # produced 只含真新增 new/1，不含重抓的 old/1
        self.assertEqual(result["produced_jd_urls"], ["https://new/1"])
        self.assertEqual(result["jobs_created"], 1)
        self.assertEqual(result["jobs_updated"], 1)


if __name__ == "__main__":
    unittest.main()
