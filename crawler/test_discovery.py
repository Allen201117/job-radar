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

    def test_max_pages_defaults_and_clamps(self):
        base = {"DISCOVERY_MODE": "discovery", "DISCOVERY_RUN_ID": "r", "DISCOVERY_QUERY": "x"}
        self.assertEqual(discovery.parse_discovery_env(base)["max_pages"],
                         discovery.DEFAULT_DISCOVERY_MAX_PAGES)  # 缺省 = 默认 4
        self.assertEqual(discovery.parse_discovery_env({**base, "DISCOVERY_MAX_PAGES": "7"})["max_pages"], 7)
        self.assertEqual(discovery.parse_discovery_env({**base, "DISCOVERY_MAX_PAGES": "nope"})["max_pages"],
                         discovery.DEFAULT_DISCOVERY_MAX_PAGES)  # 非数字 → 默认
        self.assertEqual(discovery.parse_discovery_env({**base, "DISCOVERY_MAX_PAGES": "0"})["max_pages"], 1)  # 下限
        self.assertEqual(discovery.parse_discovery_env({**base, "DISCOVERY_MAX_PAGES": "999"})["max_pages"],
                         discovery.MAX_DISCOVERY_MAX_PAGES)  # 上限钳制


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


class _FakeAdapter:
    pass


class KeywordInjectionTest(unittest.TestCase):
    def test_bytedance_sets_list_urls(self):
        a = _FakeAdapter()
        discovery.apply_keyword_to_adapter(a, "bytedance", "算法")
        self.assertTrue(getattr(a, "list_urls", None))
        self.assertIn("keyword=", a.list_urls[0])
        self.assertFalse(hasattr(a, "discovery_keyword"))

    def test_tencent_sets_discovery_keyword(self):
        a = _FakeAdapter()
        discovery.apply_keyword_to_adapter(a, "tencent", "算法")
        self.assertEqual(a.discovery_keyword, "算法")
        self.assertFalse(hasattr(a, "list_urls"))

    def test_feishu_no_injection(self):
        a = _FakeAdapter()
        discovery.apply_keyword_to_adapter(a, "nio_feishu", "算法")
        self.assertFalse(hasattr(a, "list_urls"))
        self.assertFalse(hasattr(a, "discovery_keyword"))

    def test_empty_query_noop(self):
        a = _FakeAdapter()
        discovery.apply_keyword_to_adapter(a, "tencent", "")
        self.assertFalse(hasattr(a, "discovery_keyword"))


class SourceSelectionTest(unittest.TestCase):
    def test_tencent_in_allowlist(self):
        self.assertIn("tencent", discovery.SpaKeywordRecipe.DISCOVERY_ADAPTERS)

    def test_select_targets_filters_and_keeps_multi_company(self):
        allow = discovery.SpaKeywordRecipe.DISCOVERY_ADAPTERS
        sources = [
            {"adapter_name": "bytedance", "id": "1"},
            {"adapter_name": "greenhouse", "id": "2"},   # 外企 ATS,在白名单
            {"adapter_name": "apple", "id": "3"},        # 静态源,不在发现白名单
            {"adapter_name": "baidu", "id": "4"},        # 静态源,不在发现白名单
            {"adapter_name": "bytedance", "id": "5"},     # 同 adapter 第二家,应保留
        ]
        targets = discovery.select_discovery_targets(sources, allow)
        ids = {t["id"] for t in targets}
        self.assertEqual(ids, {"1", "2", "5"})

    def test_select_targets_empty(self):
        self.assertEqual(discovery.select_discovery_targets([], {"tencent": object}), [])
        self.assertEqual(discovery.select_discovery_targets(None, {"tencent": object}), [])


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


def _en_job(title="Machine Learning Engineer", location="Beijing, China",
            summary="Build recommendation models", company="Airbnb"):
    return RawJob(company=company, title=title, location=location, job_type="Full Time",
                  summary=summary, jd_url="https://boards.greenhouse.io/airbnb/jobs/1",
                  apply_url="https://boards.greenhouse.io/airbnb/jobs/1")


class BilingualKeywordMatchTest(unittest.TestCase):
    """发现端关键词匹配与前端看板同口径：中文发现词命中英文外企岗（核心 #4）。"""

    def test_chinese_query_matches_english_job(self):
        self.assertTrue(discovery.job_matches_query(_en_job(title="Machine Learning Engineer"), "算法"))
        self.assertTrue(discovery.job_matches_query(_en_job(title="Product Manager, Growth"), "产品"))

    def test_english_query_matches_chinese_job(self):
        self.assertTrue(discovery.job_matches_query(_job(title="后端工程师", summary="服务端开发"), "backend"))

    def test_no_false_positive_via_short_abbrev(self):
        # 「算法」扩展含 "ai"，但 maintain/maintenance 不应被命中
        self.assertFalse(discovery.job_matches_query(
            _en_job(title="Maintenance Technician", summary="maintain systems"), "算法"))

    def test_filter_keeps_english_job_in_target_city(self):
        jobs = [
            _en_job(title="Machine Learning Engineer", location="Beijing, China"),
            _en_job(title="Machine Learning Engineer", location="San Francisco"),  # 命中词但城市不符
        ]
        out = discovery.filter_raw_jobs(jobs, "算法", "北京")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].location, "Beijing, China")


class JobTypeStrictnessTest(unittest.TestCase):
    """按页面所选「岗位类型」严格爬取：板块选择 + 三桶分类后置过滤（修「一味爬社招」）。"""

    def test_recruitment_category_buckets(self):
        # 标题/摘要带信号
        self.assertEqual(discovery.recruitment_category(_job(title="算法实习生", summary="日常实习")), "实习")
        self.assertEqual(discovery.recruitment_category(_job(title="后端开发（应届）", summary="校招")), "校招")
        # 标题无信号时落到 raw.job_type 字段（关键：板块来的岗位 job_type 已标实习/校招）
        self.assertEqual(discovery.recruitment_category(_job(title="产品经理", summary="", job_type="实习")), "实习")
        self.assertEqual(discovery.recruitment_category(_job(title="产品经理", summary="", job_type="校招")), "校招")
        # 默认社招
        self.assertEqual(discovery.recruitment_category(_job(title="算法工程师", summary="推荐", job_type="社招")), "社招")
        self.assertEqual(discovery.recruitment_category(_job(title="算法工程师", summary="推荐", job_type="")), "社招")

    def test_job_matches_type(self):
        intern = _job(title="数据分析实习生", job_type="实习")
        social = _job(title="数据分析师", job_type="社招")
        self.assertTrue(discovery.job_matches_type(intern, ""))      # 空 = 不过滤
        self.assertTrue(discovery.job_matches_type(social, ""))
        self.assertTrue(discovery.job_matches_type(intern, "实习"))
        self.assertFalse(discovery.job_matches_type(social, "实习"))  # 社招岗位在「实习」下被排除
        self.assertTrue(discovery.job_matches_type(social, "社招"))
        self.assertTrue(discovery.job_matches_type(social, "未知类型"))  # 未知类型不过滤

    def test_bytedance_board_follows_job_type(self):
        for jt in ("实习", "校招"):
            urls = discovery.build_keyword_list_urls("bytedance", "产品", jt)
            self.assertTrue(urls[0].startswith("https://jobs.bytedance.com/campus/position"), jt)
        for jt in ("社招", ""):
            urls = discovery.build_keyword_list_urls("bytedance", "产品", jt)
            self.assertTrue(urls[0].startswith("https://jobs.bytedance.com/experienced/position"), jt)

    def test_apply_keyword_switches_campus_detail_template(self):
        a = _FakeAdapter()
        discovery.apply_keyword_to_adapter(a, "bytedance", "产品", "实习")
        self.assertIn("/campus/position", a.list_urls[0])
        self.assertEqual(a.detail_template, "https://jobs.bytedance.com/campus/position/{id}/detail")
        b = _FakeAdapter()
        discovery.apply_keyword_to_adapter(b, "bytedance", "产品", "社招")
        self.assertIn("/experienced/position", b.list_urls[0])
        self.assertFalse(hasattr(b, "detail_template"))  # 社招不覆盖

    def test_filter_excludes_wrong_type(self):
        jobs = [
            _job(title="算法实习生", location="北京", summary="日常实习", job_type="实习"),
            _job(title="算法工程师", location="北京", summary="推荐方向", job_type="社招"),
        ]
        out = discovery.filter_raw_jobs(jobs, "算法", "北京", "实习")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "算法实习生")


class PreferenceExcludeTest(unittest.TestCase):
    """偏好底层逻辑：排除词命中即丢 + 入参解析（JSON / 逗号）。"""

    def test_parse_str_list(self):
        self.assertEqual(discovery._parse_str_list('["外包","驻场"]'), ["外包", "驻场"])
        self.assertEqual(discovery._parse_str_list("外包, 驻场 ,"), ["外包", "驻场"])
        self.assertEqual(discovery._parse_str_list(""), [])
        self.assertEqual(discovery._parse_str_list(None), [])

    def test_job_excluded(self):
        j = _job(title="算法外包岗", summary="驻场开发")
        self.assertFalse(discovery.job_excluded(j, []))
        self.assertTrue(discovery.job_excluded(j, ["外包"]))
        self.assertTrue(discovery.job_excluded(j, ["驻场"]))
        self.assertFalse(discovery.job_excluded(_job(title="算法工程师"), ["外包"]))

    def test_filter_drops_excluded(self):
        jobs = [
            _job(title="算法工程师", location="北京", summary="推荐"),
            _job(title="算法外包", location="北京", summary="驻场"),
        ]
        out = discovery.filter_raw_jobs(jobs, "算法", "北京", "", ["外包"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "算法工程师")

    def test_parse_env_reads_exclude(self):
        params = discovery.parse_discovery_env({
            "DISCOVERY_MODE": "discovery", "DISCOVERY_RUN_ID": "r",
            "DISCOVERY_QUERY": "算法", "DISCOVERY_EXCLUDE": '["外包","实习"]',
        })
        self.assertEqual(params["exclude"], ["外包", "实习"])


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


class DiscoveryMaxPagesWiringTest(unittest.TestCase):
    """run() 用 params["max_pages"] 钳制每源翻页（#6 发现产出量可调），不打网络。"""

    def test_run_caps_adapter_max_pages_from_params(self):
        captured = []

        class _CapAdapter:
            max_pages = 99  # adapter 自带的高默认，应被发现配方钳到 params 值

            def fetch(self, url):
                captured.append(self.max_pages)  # fetch 在钳制之后调用
                return "{}"

            def parse(self, html):
                return []

        recipe = discovery.SpaKeywordRecipe()
        recipe.DISCOVERY_ADAPTERS = {"greenhouse": _CapAdapter}
        orig_get_sources = discovery.db.get_sources
        discovery.db.get_sources = lambda supabase: [
            {"adapter_name": "greenhouse", "id": "1", "company": "X",
             "source_url": "https://example.com/api"}
        ]
        try:
            recipe.run(supabase=object(),
                       params={"query": "算法", "city": "", "max_pages": 2})
        finally:
            discovery.db.get_sources = orig_get_sources

        self.assertEqual(captured, [2])  # 99 -> 钳到 2

    def test_run_falls_back_to_default_when_no_param(self):
        captured = []

        class _CapAdapter:
            max_pages = 99

            def fetch(self, url):
                captured.append(self.max_pages)
                return "{}"

            def parse(self, html):
                return []

        recipe = discovery.SpaKeywordRecipe()
        recipe.DISCOVERY_ADAPTERS = {"greenhouse": _CapAdapter}
        orig_get_sources = discovery.db.get_sources
        discovery.db.get_sources = lambda supabase: [
            {"adapter_name": "greenhouse", "id": "1", "company": "X",
             "source_url": "https://example.com/api"}
        ]
        try:
            recipe.run(supabase=object(), params={"query": "算法", "city": ""})  # 无 max_pages
        finally:
            discovery.db.get_sources = orig_get_sources

        self.assertEqual(captured, [discovery.DEFAULT_DISCOVERY_MAX_PAGES])  # 回退默认 4


if __name__ == "__main__":
    unittest.main()
