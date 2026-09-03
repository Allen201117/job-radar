"""搜索额度探针的纯函数：口径、阈值、退出条件。不联网、不读库。"""
import unittest

import search_quota_probe as P


ROWS = [
    {"provider": "serper", "day": "2026-06-20", "used": 10},
    {"provider": "serper", "day": "2026-09-03", "used": 40},
    {"provider": "serper", "day": "2026-09-04", "used": 5},
    {"provider": "tavily", "day": "2026-08-31", "used": 800},
    {"provider": "tavily", "day": "2026-09-04", "used": 20},
    {"provider": "qianfan", "day": "2026-09-04", "used": 30},
]


class SummarizeTest(unittest.TestCase):
    def test_splits_lifetime_month_and_today(self):
        s = P.summarize(ROWS, today="2026-09-04", month="2026-09")
        self.assertEqual(s["serper"]["lifetime"], 55)
        self.assertEqual(s["serper"]["month"], 45)   # 只算 9 月
        self.assertEqual(s["serper"]["today"], 5)
        self.assertEqual(s["serper"]["days"], 3)
        self.assertEqual(s["serper"]["first_day"], "2026-06-20")
        # 8 月那 800 不该算进 9 月
        self.assertEqual(s["tavily"]["month"], 20)
        self.assertEqual(s["tavily"]["lifetime"], 820)

    def test_ignores_dirty_rows_without_crashing(self):
        s = P.summarize([{"provider": None, "day": "2026-09-04", "used": 5},
                         {"provider": "serper", "day": None, "used": 5},
                         {"provider": "serper", "day": "2026-09-04", "used": None}],
                        today="2026-09-04")
        self.assertEqual(s["serper"]["today"], 0)


class AssessTest(unittest.TestCase):
    """每家的「用了多少」口径不同：一次性看累计、按月看当月、按天看当天。混了就全错。"""

    def test_each_provider_uses_its_own_reset_cycle(self):
        s = P.summarize(ROWS, today="2026-09-04", month="2026-09")
        by = {i["provider"]: i for i in P.assess(s)}
        self.assertEqual(by["serper"]["used"], 55)    # lifetime
        self.assertEqual(by["tavily"]["used"], 20)    # 当月，不是 820
        self.assertEqual(by["qianfan"]["used"], 30)   # 当天

    def test_paid_source_never_warns(self):
        s = P.summarize([{"provider": "bocha", "day": "2026-09-04", "used": 99999}],
                        today="2026-09-04")
        by = {i["provider"]: i for i in P.assess(s)}
        self.assertEqual(by["bocha"]["level"], "ok")
        self.assertIsNone(by["bocha"]["quota"])

    def test_thresholds(self):
        def level(used):
            s = {"serper": {"lifetime": used, "month": 0, "today": 0, "days": 1}}
            return {i["provider"]: i for i in P.assess(s)}["serper"]["level"]
        self.assertEqual(level(1999), "ok")        # 79.9%
        self.assertEqual(level(2000), "warn")      # 80%
        self.assertEqual(level(2250), "critical")  # 90%

    def test_critical_sorts_first(self):
        s = {"serper": {"lifetime": 2400, "month": 0, "today": 0, "days": 1},
             "tavily": {"lifetime": 0, "month": 10, "today": 0, "days": 1}}
        self.assertEqual(P.assess(s)[0]["provider"], "serper")


class DaysLeftTest(unittest.TestCase):
    def test_estimates_from_average_daily_burn(self):
        s = {"serper": {"lifetime": 1000, "month": 0, "today": 0, "days": 100}}
        item = {"provider": "serper", "kind": "lifetime", "quota": 2500, "used": 1000}
        self.assertEqual(P.days_left(item, s), 150.0)   # 剩 1500 ÷ 10/天

    def test_no_estimate_for_resetting_quotas(self):
        s = {"tavily": {"lifetime": 100, "month": 100, "today": 0, "days": 10}}
        self.assertIsNone(P.days_left({"provider": "tavily", "kind": "monthly",
                                       "quota": 1000, "used": 100}, s))

    def test_no_data_no_guess(self):
        self.assertIsNone(P.days_left({"provider": "serper", "kind": "lifetime",
                                       "quota": 2500, "used": 0}, {}))


if __name__ == "__main__":
    unittest.main()


class TavilyUsageParseTest(unittest.TestCase):
    """只有 Tavily 有官方余额接口（2026-09-04 查证）。形状不认识就返回 None，不猜。"""

    def test_key_shape(self):
        self.assertEqual(P.parse_tavily_usage({"key": {"usage": 123, "limit": 1000}}),
                         {"used": 123, "limit": 1000})

    def test_account_shape(self):
        self.assertEqual(P.parse_tavily_usage({"account": {"plan_usage": 50, "plan_limit": 1000}}),
                         {"used": 50, "limit": 1000})

    def test_unknown_shape_returns_none_instead_of_guessing(self):
        for payload in (None, {}, {"whatever": 1}, "字符串", {"key": {"usage": "多"}}):
            self.assertIsNone(P.parse_tavily_usage(payload), payload)

    def test_zero_limit_is_not_usable(self):
        # limit=0 会让占比除零 / 恒判 critical，宁可回退台账
        self.assertIsNone(P.parse_tavily_usage({"key": {"usage": 1, "limit": 0}}))

    def test_missing_key_skips_the_probe(self):
        self.assertIsNone(P.probe_tavily(""))


class SpecTest(unittest.TestCase):
    def test_only_tavily_claims_an_official_endpoint(self):
        """Serper 与千帆都没有余额 API（查证过），别哪天有人凭印象加上去。"""
        self.assertTrue(P.TAVILY_USAGE_URL.startswith("https://api.tavily.com/"))
        self.assertFalse(hasattr(P, "SERPER_USAGE_URL"))
        self.assertFalse(hasattr(P, "QIANFAN_USAGE_URL"))

    def test_bocha_is_marked_paid_not_free(self):
        self.assertEqual(P.QUOTA_SPEC["bocha"]["kind"], "paid")
        self.assertIsNone(P.QUOTA_SPEC["bocha"]["free"])
