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
            ["google_cse", "tavily", "qianfan", "serper", "exa", "bocha"],
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
        # 逐 provider 给不同用量：一次性额度的源不止 serper 一个（exa 也是），
        # 拿同一个数字喂所有源会让断言分不清「哪个源越线了」。
        used = {"serper": 2100, "exa": 100}
        R.lifetime_used = lambda sb, provider: used.get(provider, 0)
        self.assertEqual(R.lifetime_warnings(None), [("serper", 2100, 2500)])

    def test_google_cse_cap_is_pinned_to_the_trial_credit_window(self):
        """日顶 500 > 免费档 100，超出部分吃试用赠金（2026-12-18 到期）。
        改这个数之前先确认赠金还在，否则是在真花钱。"""
        import search_google_cse
        self.assertEqual(search_google_cse.GoogleCseProvider().default_cap, 500)

    def test_exa_is_tracked_as_a_one_off_quota_too(self):
        """exa 也是一次性额度（注册送 $10 ≈ 1,000 次），必须进耗尽预警 ——
        漏登记它 = 某天它悄悄见底，表现成「入口突然找不到了」，又一次绿灯零产出。"""
        used = {"serper": 0, "exa": 900}
        R.lifetime_used = lambda sb, provider: used.get(provider, 0)
        self.assertEqual(R.lifetime_warnings(None), [("exa", 900, 1000)])

    def test_read_failure_never_breaks_the_caller(self):
        """预警读不到台账时返回 0，绝不抛——预警不能把主任务拖垮。"""
        class _Boom:
            def table(self, *_a, **_k):
                raise RuntimeError("network down")
        self.assertEqual(R.lifetime_used(_Boom(), "serper"), 0)


if __name__ == "__main__":
    unittest.main()
