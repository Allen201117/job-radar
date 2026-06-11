"""CompanyRefreshRecipe 单测（不打网络）：httpx-first 排序 / 跨源去重 / 增量心跳 / 状态判定。"""
import unittest
from unittest import mock

import discovery
from adapters.base import RawJob


def _raw(jd_url, title="工程师", company="X"):
    return RawJob(company=company, title=title, location="北京", jd_url=jd_url)


class FakeAdapter:
    def __init__(self, jobs, raise_exc=None):
        self._jobs = jobs
        self._raise = raise_exc

    def fetch(self, url):
        if self._raise:
            raise self._raise
        return "html"

    def parse(self, html):
        return list(self._jobs)


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
        p3 = mock.patch.object(
            discovery.normalizer, "validate_job_quality", return_value=(True, ""),
        )
        p3.start(); self.addCleanup(p3.stop)

    def _run(self, rows, adapters):
        import run as runmod
        with mock.patch.object(discovery.db, "get_sources_by_ids", return_value=rows), \
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


if __name__ == "__main__":
    unittest.main()
