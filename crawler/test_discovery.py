"""按需发现编排的纯函数 + 生命周期单测（不打网络、不连 DB、不起浏览器）。"""
import unittest

import discovery
from adapters.base import RawJob


def _job(title="算法工程师", location="北京", job_type="社招", summary="负责推荐算法",
         jd_url="https://jobs.bytedance.com/experienced/position/123/detail"):
    return RawJob(company="字节跳动", title=title, location=location, job_type=job_type,
                  summary=summary, jd_url=jd_url, apply_url=jd_url)


class ParseDiscoveryEnvTest(unittest.TestCase):
    def test_non_discovery_mode_returns_none(self):
        self.assertIsNone(discovery.parse_discovery_env({}))
        self.assertIsNone(discovery.parse_discovery_env({"DISCOVERY_MODE": "discovery"}))
        self.assertIsNone(
            discovery.parse_discovery_env(
                {"DISCOVERY_RUN_ID": "r1", "DISCOVERY_QUERY": "算法"}  # 缺 mode
            )
        )

    def test_full_discovery_env(self):
        params = discovery.parse_discovery_env(
            {
                "DISCOVERY_MODE": "discovery",
                "DISCOVERY_RUN_ID": "run-1",
                "DISCOVERY_QUERY": "  算法  ",
                "DISCOVERY_CITY": " 北京 ",
                "DISCOVERY_JOB_TYPE": " 工程 ",
                "DISCOVERY_LIMIT": "100",
            }
        )
        self.assertEqual(params["run_id"], "run-1")
        self.assertEqual(params["query"], "算法")
        self.assertEqual(params["city"], "北京")
        self.assertEqual(params["limit"], 60)  # clamp 到 60

    def test_limit_defaults_and_clamps(self):
        base = {"DISCOVERY_MODE": "discovery", "DISCOVERY_RUN_ID": "r", "DISCOVERY_QUERY": "x"}
        self.assertEqual(discovery.parse_discovery_env(base)["limit"], 30)
        self.assertEqual(discovery.parse_discovery_env({**base, "DISCOVERY_LIMIT": "nope"})["limit"], 30)
        self.assertEqual(discovery.parse_discovery_env({**base, "DISCOVERY_LIMIT": "0"})["limit"], 1)


class ResolveRecipeTest(unittest.TestCase):
    def test_seed_recipe_matches_any_query(self):
        self.assertIn("spa_keyword", discovery.RECIPES)
        self.assertEqual(discovery.resolve_recipe("算法", "北京"), "spa_keyword")

    def test_empty_query_matches_nothing(self):
        self.assertIsNone(discovery.resolve_recipe(""))


class KeywordUrlTest(unittest.TestCase):
    def test_bytedance_builds_keyword_url(self):
        urls = discovery.build_keyword_list_urls("bytedance", "算法")
        self.assertEqual(len(urls), 1)
        self.assertIn("keyword=", urls[0])
        self.assertTrue(urls[0].startswith("https://jobs.bytedance.com/experienced/position"))

    def test_feishu_returns_none(self):
        self.assertIsNone(discovery.build_keyword_list_urls("nio_feishu", "算法"))

    def test_empty_query_returns_none(self):
        self.assertIsNone(discovery.build_keyword_list_urls("bytedance", ""))


class FilterRawJobsTest(unittest.TestCase):
    def test_query_match_on_title_summary_type(self):
        self.assertTrue(discovery.job_matches_query(_job(title="后端工程师", summary="x", job_type="社招"), "后端"))
        self.assertTrue(discovery.job_matches_query(_job(title="x", summary="负责算法", job_type="社招"), "算法"))
        self.assertFalse(discovery.job_matches_query(_job(title="财务", summary="报表", job_type="社招"), "算法"))
        self.assertTrue(discovery.job_matches_query(_job(), ""))  # 空 query 全命中

    def test_city_match(self):
        self.assertTrue(discovery.job_matches_city(_job(location="北京市"), "北京"))
        self.assertFalse(discovery.job_matches_city(_job(location="上海"), "北京"))
        self.assertTrue(discovery.job_matches_city(_job(location="上海"), ""))  # 空 city 全命中
        self.assertFalse(discovery.job_matches_city(_job(location=None), "北京"))  # 无地点不命中具体城市

    def test_filter_combines_query_and_city(self):
        jobs = [
            _job(title="算法工程师", location="北京", summary="推荐方向"),
            _job(title="算法工程师", location="上海", summary="推荐方向"),  # 命中词但城市不符
            _job(title="财务", location="北京", summary="报表核算"),        # 城市符但不命中词
        ]
        out = discovery.filter_raw_jobs(jobs, "算法", "北京")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].location, "北京")
        self.assertEqual(out[0].title, "算法工程师")


class RunDiscoveryLifecycleTest(unittest.TestCase):
    def _capture_updates(self):
        calls = []
        original = discovery.db.update_discovery_run
        discovery.db.update_discovery_run = lambda supabase, run_id, **f: calls.append((run_id, f))
        return calls, original

    def test_recipe_path_runs_and_writes_terminal(self):
        """命中配方时：running → 配方产出 → 终态 + diagnostics.produced_jd_urls。"""
        calls, original = self._capture_updates()
        recipe = discovery.RECIPES["spa_keyword"]
        original_run = recipe.run
        recipe.run = lambda supabase, params: {
            "status": "success",
            "failure_reason": None,
            "error_message": None,
            "jobs_created": 3,
            "jobs_updated": 1,
            "candidates_found": 4,
            "produced_jd_urls": ["https://jobs.bytedance.com/experienced/position/1/detail"],
        }
        try:
            summary = discovery.run_discovery(
                {"run_id": "run-5", "query": "算法", "city": "", "job_type": "", "limit": 30},
                supabase=object(),
            )
        finally:
            recipe.run = original_run
            discovery.db.update_discovery_run = original

        self.assertEqual(summary["status"], "success")
        self.assertEqual(calls[0][1].get("status"), "running")
        last = calls[-1][1]
        self.assertEqual(last.get("status"), "success")
        self.assertEqual(last.get("jobs_created"), 3)
        self.assertEqual(
            last.get("diagnostics", {}).get("produced_jd_urls"),
            ["https://jobs.bytedance.com/experienced/position/1/detail"],
        )
        self.assertIn("finished_at", last)

    def test_no_recipe_path_writes_failed(self):
        """注册表为空时：running → failed(no_recipe_matched)，不写岗位。"""
        calls, original = self._capture_updates()
        original_recipes = discovery.RECIPES
        discovery.RECIPES = {}
        try:
            summary = discovery.run_discovery(
                {"run_id": "run-6", "query": "算法", "city": "", "job_type": "", "limit": 30},
                supabase=object(),
            )
        finally:
            discovery.RECIPES = original_recipes
            discovery.db.update_discovery_run = original

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failure_reason"], "no_recipe_matched")
        self.assertEqual(calls[0][1].get("status"), "running")
        self.assertEqual(calls[-1][1].get("status"), "failed")


if __name__ == "__main__":
    unittest.main()
