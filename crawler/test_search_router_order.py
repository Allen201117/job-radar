"""搜索源顺序与日顶的不变量：只测纯装配，不联网。"""
import unittest

import search_router as R


class ProviderOrderTest(unittest.TestCase):
    """顺序 = 额度可持续性优先。search() 是「按顺序试、够 5 条就停」，排前面的先被消耗。

    2026-09-04 台账实测（search_usage 自 2026-06-20 起 68 天）：
    Serper 的 2,500 **一次性**额度已用掉 1,299（52%），按每月约 570 次两个月见底；
    而千帆每天 50 次免费额度天天没用完。原顺序把一次性的排在每天回血的前面，正好是反的。
    """

    def _providers(self):
        return [getattr(p, "name", "?") for p in R.default_router().providers]

    def _caps(self):
        return {
            getattr(p, "name", "?"): getattr(p, "default_cap", None)
            for p in R.default_router().providers
        }

    def test_order_is_by_refill_cycle(self):
        self.assertEqual(
            self._providers(),
            ["tavily", "qianfan", "serper", "bocha"],
            "顺序必须是「每月回血 → 每天回血 → 一次性 → 付费」；"
            "把 serper（2500 一次性）或 bocha（付费）往前挪之前，先算一遍余额",
        )

    def test_finite_quota_source_has_the_smallest_daily_cap(self):
        caps = self._caps()
        self.assertLess(
            caps["serper"], caps["tavily"],
            "一次性额度的源，日顶必须小于按月回血的源",
        )

    def test_tavily_daily_cap_stays_under_the_monthly_free_tier(self):
        caps = self._caps()
        self.assertLessEqual(
            caps["tavily"] * 31, 1000,
            "Tavily 免费额度 1000/月，日顶 × 31 天不能超（超了月底会硬断）",
        )

    def test_lifetime_quota_table_covers_the_finite_source(self):
        self.assertIn("serper", R.LIFETIME_QUOTA)
        self.assertEqual(R.LIFETIME_QUOTA["serper"], 2500)


class LifetimeWarningTest(unittest.TestCase):
    """一次性额度用完是**静默**的：表现为「T3 突然不产出」。必须能提前叫。"""

    def setUp(self):
        # monkeypatch 必须还原：同进程跑的其它测试还要用真的 lifetime_used
        self._real = R.lifetime_used

    def tearDown(self):
        R.lifetime_used = self._real

    def test_below_threshold_is_silent(self):
        R.lifetime_used = lambda sb, provider: 100
        self.assertEqual(R.lifetime_warnings(None), [])

    def test_crossing_eighty_percent_warns(self):
        R.lifetime_used = lambda sb, provider: 2100
        self.assertEqual(R.lifetime_warnings(None), [("serper", 2100, 2500)])

    def test_read_failure_never_breaks_the_caller(self):
        """预警读不到台账时返回 0，绝不抛——预警不能把主任务拖垮。"""
        class _Boom:
            def table(self, *_a, **_k):
                raise RuntimeError("network down")
        self.assertEqual(R.lifetime_used(_Boom(), "serper"), 0)


if __name__ == "__main__":
    unittest.main()
