"""列表抓取上限（治「绿灯但没抓全」）。

2026-09-04 实测背景：旧的 600 硬顶让 32 个源每轮只抓前 600 条、累计漏 10.7 万个岗，
且 status 全是 success —— 典型的「绿灯但没产出」。这里钉死两件事：
① 上限要够高，把量过的那批源真正抓全（45 个截断源里 43 个 ≤8000）；
② adapter 声明的基准档要能**往下**压，否则「撞上限 → 不算抓全」那类断言会静默失效。
"""
import os
import unittest

from adapters.base import DEFAULT_LIST_CAP, resolve_list_cap


class ResolveListCapTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("CRAWL_MAX_JOBS", None)

    def test_default_is_the_adapter_declared_cap(self):
        self.assertEqual(resolve_list_cap(DEFAULT_LIST_CAP), DEFAULT_LIST_CAP)

    def test_cap_covers_the_sources_measured_as_truncated(self):
        """量过的官网自报总数：来伊份 7204 / 奇瑞 5643 / 喜茶 5078 / 新东方 4273 / 中国交建 2565
        / 中国人保 2367 / 蔚来 2055 / 长城 3420。上限低于其中任何一个都等于这条线白做。"""
        for reported in (7204, 5643, 5078, 4273, 3420, 2565, 2367, 2055):
            self.assertGreaterEqual(DEFAULT_LIST_CAP, reported)

    def test_adapter_default_can_be_lowered(self):
        """不许对 default 取 max —— 单测靠把 _MAX_JOBS 压到 2 来验「撞上限不算抓全」。"""
        self.assertEqual(resolve_list_cap(2), 2)

    def test_env_overrides_the_cap(self):
        """出事时改 repo variable 就能降档，不用改代码重新部署。"""
        os.environ["CRAWL_MAX_JOBS"] = "111"
        self.assertEqual(resolve_list_cap(DEFAULT_LIST_CAP), 111)

    def test_bad_env_falls_back_to_default(self):
        os.environ["CRAWL_MAX_JOBS"] = "abc"
        self.assertEqual(resolve_list_cap(DEFAULT_LIST_CAP), DEFAULT_LIST_CAP)

    def test_negative_env_is_clamped_not_crashing(self):
        os.environ["CRAWL_MAX_JOBS"] = "-5"
        self.assertEqual(resolve_list_cap(DEFAULT_LIST_CAP), 0)


class AdapterCapWiringTest(unittest.TestCase):
    """接线检查：改了 base 的档位，三个 adapter 必须跟着走，别再各留各的硬编码。"""

    def test_beisen_feishu_wt_all_use_the_shared_cap(self):
        from adapters.china_ats import BeisenAdapter, MokaAdapter
        from adapters.feishu import FeishuRecruitAdapter, XiaomiAdapter
        from adapters.wt import WtAdapter
        for cls in (BeisenAdapter, MokaAdapter, FeishuRecruitAdapter, XiaomiAdapter, WtAdapter):
            self.assertEqual(cls._MAX_JOBS, DEFAULT_LIST_CAP, cls.__name__)

    def test_moka_page_cap_follows_the_shared_knob(self):
        """moka 是**页数**记账（浏览器点「下一页」），必须由 CRAWL_MAX_JOBS 换算，别再写死。
        回归：写死 60 页时吉利控股自报 86 页只抓到 60 页（1,800/2,580）。"""
        from adapters.base import resolve_page_cap
        from adapters.china_ats import MokaAdapter
        self.assertGreaterEqual(
            resolve_page_cap(MokaAdapter._PAGE_ROWS, MokaAdapter._MAX_JOBS), 86)
        os.environ["CRAWL_MAX_JOBS"] = "900"
        try:
            self.assertEqual(resolve_page_cap(MokaAdapter._PAGE_ROWS, MokaAdapter._MAX_JOBS), 30)
        finally:
            os.environ.pop("CRAWL_MAX_JOBS", None)


if __name__ == "__main__":
    unittest.main()
