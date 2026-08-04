import unittest

from campus_lane import (
    coverage_ratio,
    detect_surge,
    is_campus_season,
    is_undercrawled,
    select_campus_sources,
)


class TestCampusSeason(unittest.TestCase):
    def test_autumn_and_spring_are_seasons(self):
        for m in (8, 9, 10, 11):
            self.assertTrue(is_campus_season(m), f"{m} 月属秋招季")
        for m in (2, 3, 4):
            self.assertTrue(is_campus_season(m), f"{m} 月属春招季")

    def test_off_season_returns_false(self):
        # 淡季不跑高频车道：避免全年无谓打目标站点（车道靠判月份早退，而非删 cron，便于手动触发）
        for m in (1, 5, 6, 7, 12):
            self.assertFalse(is_campus_season(m), f"{m} 月是淡季")

    def test_invalid_month_is_not_season(self):
        for m in (0, 13, -1, None):
            self.assertFalse(is_campus_season(m))


class TestSelectCampusSources(unittest.TestCase):
    def setUp(self):
        self.sources = [
            {"id": "s1", "company": "腾讯", "board": "mixed", "enabled": True},
            {"id": "s2", "company": "字节跳动", "board": "campus", "enabled": True},
            {"id": "s3", "company": "美团 Meituan", "board": "social", "enabled": True},
            # 自建门户：board 判不出来，但实际在产校招岗（比亚迪 2053 岗即此形态）
            {"id": "s4", "company": "比亚迪 BYD", "board": "social", "enabled": True},
            {"id": "s5", "company": "某不在必投清单的小公司", "board": "campus", "enabled": True},
            {"id": "s6", "company": "腾讯", "board": "campus", "enabled": False},
        ]
        self.must_apply = lambda name: "不在必投清单" not in (name or "")

    def test_picks_campus_and_mixed_boards(self):
        got = select_campus_sources(self.sources, set(), self.must_apply)
        self.assertEqual({s["id"] for s in got}, {"s1", "s2"})

    def test_union_with_actual_producers_catches_selfbuilt_portals(self):
        # 核心不变量：board 是静态分类，会漏掉把校招社招混在一个列表里的自建门户。
        # live 实测 430 个真产校招岗的源里 board 只覆盖 281 个，漏的 149 个必须靠产出并集补回来，
        # 否则比亚迪/小红书/华为/蚂蚁这类大户全部掉出高频车道。
        got = select_campus_sources(self.sources, {"s4"}, self.must_apply)
        self.assertIn("s4", {s["id"] for s in got})

    def test_excludes_disabled_sources(self):
        got = select_campus_sources(self.sources, {"s6"}, self.must_apply)
        self.assertNotIn("s6", {s["id"] for s in got})

    def test_excludes_companies_outside_must_apply_list(self):
        # 车道是「加密轮次」不是「全库提频」：只覆盖必投清单，避免打爆无关站点
        got = select_campus_sources(self.sources, {"s5"}, self.must_apply)
        self.assertNotIn("s5", {s["id"] for s in got})

    def test_no_must_apply_filter_keeps_everything_enabled(self):
        got = select_campus_sources(self.sources, set(), None)
        self.assertEqual({s["id"] for s in got}, {"s1", "s2", "s5"})

    def test_result_is_deduped_and_stable(self):
        # s1 同时命中 board 与产出两条路径，不能出现两次
        got = select_campus_sources(self.sources, {"s1", "s4"}, self.must_apply)
        ids = [s["id"] for s in got]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids, key=lambda x: [s["id"] for s in self.sources].index(x)))


class TestDetectSurge(unittest.TestCase):
    def test_multiple_rule_catches_big_bang(self):
        # 腾讯 17 → 800 这种「正式批开闸」形态
        self.assertTrue(detect_surge(17, 800))

    def test_delta_rule_catches_zero_baseline(self):
        # 0 → 60：倍数规则对 0 基线失效（0×3=0 恒成立会误报），靠增量规则兜
        self.assertTrue(detect_surge(0, 60))

    def test_small_growth_is_not_surge(self):
        self.assertFalse(detect_surge(0, 10))
        self.assertFalse(detect_surge(100, 140))   # 既不到 3 倍也不足 +50？140-100=40 <50
        self.assertFalse(detect_surge(200, 240))

    def test_first_snapshot_has_no_baseline_so_no_surge(self):
        # 没有上一条快照时不判开闸——否则接入新源当天必然误报一次
        self.assertFalse(detect_surge(None, 5000))

    def test_shrink_is_never_surge(self):
        self.assertFalse(detect_surge(800, 17))

    def test_thresholds_are_configurable(self):
        self.assertTrue(detect_surge(10, 25, multiple=2, delta=1000))
        self.assertTrue(detect_surge(10, 30, multiple=1000, delta=20))


class TestCoverage(unittest.TestCase):
    def test_ratio_and_undercrawled(self):
        self.assertAlmostEqual(coverage_ratio(90, 100), 0.9)
        self.assertFalse(is_undercrawled(90, 100))     # 恰好到线不算未抓全
        self.assertTrue(is_undercrawled(50, 100))

    def test_missing_reported_total_returns_none_not_zero(self):
        # ⚠️ 诚实红线：adapter 没自报官网总数时必须返回「测不了」，
        # 绝不能当成 0/未抓全 —— 那会把「无法校验」伪装成「已校验」，指标失真。
        self.assertIsNone(coverage_ratio(50, None))
        self.assertIsNone(is_undercrawled(50, None))
        self.assertIsNone(coverage_ratio(50, 0))
        self.assertIsNone(is_undercrawled(50, 0))

    def test_overshoot_is_capped_and_not_undercrawled(self):
        # 入库数可能略超自报总数（翻页期间新岗上架），不该判未抓全
        self.assertFalse(is_undercrawled(120, 100))


if __name__ == "__main__":
    unittest.main()
