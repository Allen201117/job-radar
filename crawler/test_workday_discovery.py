"""Workday 租户/站点发现器单测（纯 mock，不打真网络）。

核心是**状态码信号的方向**：live 校准（2026-07-14，用确定不存在的租户反向验证）得到
  422 = 租户不存在 / 404 = 租户存在但 site 名错 / 200+total>0 = 命中。
写反了（把 422 当「租户存在」）会让发现器对不存在的租户狂枚举 site、对真租户直接跳过 —— 全盘失效
且不会报错。所以这两个方向都必须有测试钉住。
"""
import unittest

import workday_discovery as wd


def _fake_probe(table):
    """table: {url: (status, total)}；未列出的 URL 视为 422（租户不存在）。"""
    def probe(url, timeout):
        return table.get(url, (422, 0))
    return probe


class DiscoverTest(unittest.TestCase):
    def test_finds_tenant_and_site(self):
        dummy = wd.cxs_url("salesforce", "wd12", "ZzNoSuchSite")
        good = wd.cxs_url("salesforce", "wd12", "External_Career_Site")
        table = {dummy: (404, 0), good: (200, 1454)}   # 404=租户在；正确 site → 200
        out = wd.discover("Salesforce", ["salesforce"], probe_fn=_fake_probe(table))
        self.assertIsNotNone(out)
        self.assertEqual(out["tenant"], "salesforce")
        self.assertEqual(out["wd"], "wd12")
        self.assertEqual(out["site"], "External_Career_Site")
        self.assertEqual(out["total"], 1454)
        self.assertEqual(out["url"], good)

    def test_422_means_tenant_missing_and_sites_are_not_enumerated(self):
        """422（租户不存在）必须**跳过**该租户，不能去枚举 site。
        方向写反 = 对不存在的租户白跑十几个请求，且真租户永远探不到。"""
        calls = []

        def probe(url, timeout):
            calls.append(url)
            return (422, 0)   # 全 422 = 租户不存在

        out = wd.discover("Nope Inc", ["nopeinc"], probe_fn=probe)
        self.assertIsNone(out)
        # 只应对每个 wd 编号探一次 dummy site，绝不进入 site 枚举
        self.assertEqual(len(calls), len(wd.WD_NUMBERS))
        for url in calls:
            self.assertIn("ZzNoSuchSite", url)

    def test_404_tenant_exists_but_no_site_matches(self):
        """租户存在（404）但所有 site 候选都不对 → 诚实返回 None，不硬塞。"""
        def probe(url, timeout):
            return (404, 0)   # 租户在，但 site 全错
        out = wd.discover("Weird Co", ["weirdco"], probe_fn=probe)
        self.assertIsNone(out)

    def test_zero_total_is_not_a_hit(self):
        """200 但 total=0（空站点）不算命中——入库了也是零产出源。"""
        dummy = wd.cxs_url("empty", "wd1", "ZzNoSuchSite")
        site = wd.cxs_url("empty", "wd1", "External")
        out = wd.discover("Empty", ["empty"], probe_fn=_fake_probe({dummy: (404, 0), site: (200, 0)}))
        self.assertIsNone(out)

    def test_network_error_treated_as_missing_tenant(self):
        out = wd.discover("Boom", ["boom"], probe_fn=lambda url, timeout: ("ERR", 0))
        self.assertIsNone(out)

    def test_site_candidates_cover_known_naming_patterns(self):
        """site 名无规律，候选表从库里已有 workday 源归纳（External / {Co}Careers / {Co}_Careers / tenant…）。"""
        cands = wd.site_candidates("diageo", "Diageo")
        for expected in ("External", "Careers", "Diageo_Careers", "DiageoCareers", "diageo"):
            self.assertIn(expected, cands)
        self.assertEqual(len(cands), len(set(cands)))   # 不重复浪费请求


class BuildWorkdayCandidatesTest(unittest.TestCase):
    def test_skips_companies_already_covered_by_ats_templates(self):
        import auto_discover_overseas as ao
        targets = [{"company": "Airbnb", "slugs": ["airbnb"]}, {"company": "Visa", "slugs": ["visa"]}]
        seen = []

        def fake_discover(company, slugs):
            seen.append(company)
            return {"tenant": "visa", "wd": "wd5", "site": "visa", "total": 925,
                    "url": "https://visa.wd5.myworkdayjobs.com/wday/cxs/visa/visa/jobs"}

        out = ao.build_workday_candidates(targets, covered_companies={"Airbnb"}, discover_fn=fake_discover)
        self.assertEqual(seen, ["Visa"])          # 已被 greenhouse 探到的 Airbnb 不再浪费 workday 预算
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["adapter"], "workday")
        self.assertEqual(out[0]["company"], "Visa")

    def test_discovery_failure_does_not_break_the_run(self):
        import auto_discover_overseas as ao

        def boom(company, slugs):
            raise RuntimeError("network down")

        out = ao.build_workday_candidates([{"company": "X", "slugs": ["x"]}], set(), discover_fn=boom)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()


class WorkdayCapTest(unittest.TestCase):
    """发现一家最多 6×13 次 httpx——不设 cap 的话 80 家目标会把 CI 跑超时。"""

    def test_caps_how_many_companies_are_probed_per_run(self):
        import auto_discover_overseas as ao
        targets = [{"company": f"C{i}", "slugs": [f"c{i}"]} for i in range(10)]
        tried = []

        def fake_discover(company, slugs):
            tried.append(company)
            return None

        ao.build_workday_candidates(targets, set(), discover_fn=fake_discover, cap=3)
        self.assertEqual(len(tried), 3)


class FilterUncoveredTest(unittest.TestCase):
    """库里公司名常是中英混写（「武田制药 Takeda」），拿展示名精确比对会漏判「已覆盖」→
    白跑一整轮 workday 租户发现（每家最多 6×13 次 httpx），最后发现的源又被 URL 去重挡掉。
    必须按必投清单的 ILIKE 模式匹配。"""

    def test_matches_mixed_language_company_names_in_db(self):
        import auto_discover_overseas as ao
        targets = [{"company": "Takeda"}, {"company": "Salesforce"}]
        pmap = {"Takeda": "%Takeda%", "Salesforce": "%Salesforce%"}
        out = ao.filter_uncovered(targets, ["武田制药 Takeda"], pattern_map=pmap)
        self.assertEqual([t["company"] for t in out], ["Salesforce"])

    def test_keeps_targets_with_no_source(self):
        import auto_discover_overseas as ao
        targets = [{"company": "Visa"}]
        out = ao.filter_uncovered(targets, ["完全无关公司"], pattern_map={"Visa": "%Visa Inc%"})
        self.assertEqual(len(out), 1)
