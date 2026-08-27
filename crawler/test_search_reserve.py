"""搜索额度「校招预留」——防 T3 把共享额度吃到 0 饿死校招链。纯函数/桩，零网络。

背景（2026-08-28 实测立碑）：搜索额度全局共享，T3 洞察 drain 一路吃到 0
（cap = remaining，队列多长吃多久）；校招时间线链 cron 排在它后面 45 分钟，
于是每天开跑时 remaining 恒为 0、第一家就 break —— ops_runs 连续 7 天
companies_processed=0，却因为不抛异常一直报 success。
**这不是逻辑 bug 是资源饿死**，靠调 cron 先后只会把饿死的换成另一条。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import search_router as R  # noqa: E402


class _StubProvider:
    def __init__(self, left):
        self._left = left

    def is_configured(self):
        return True

    def remaining(self, sb):
        return self._left


def _router(*lefts):
    r = R.SearchRouter.__new__(R.SearchRouter)
    r.providers = [_StubProvider(n) for n in lefts]
    return r


class CampusReserveTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("SEARCH_RESERVE_CAMPUS")
        os.environ.pop("SEARCH_RESERVE_CAMPUS", None)

    def tearDown(self):
        os.environ.pop("SEARCH_RESERVE_CAMPUS", None)
        if self._saved is not None:
            os.environ["SEARCH_RESERVE_CAMPUS"] = self._saved

    def test_default_and_env_override(self):
        self.assertEqual(R.campus_reserve(), 25)
        os.environ["SEARCH_RESERVE_CAMPUS"] = "10"
        self.assertEqual(R.campus_reserve(), 10)

    def test_zero_disables_reserve_back_to_old_behaviour(self):
        os.environ["SEARCH_RESERVE_CAMPUS"] = "0"
        self.assertEqual(R.campus_reserve(), 0)
        self.assertEqual(_router(30).remaining_above_reserve(None), 30)

    def test_illegal_value_falls_back_to_default(self):
        os.environ["SEARCH_RESERVE_CAMPUS"] = "abc"
        self.assertEqual(R.campus_reserve(), 25)

    def test_greedy_consumer_stops_at_the_reserve_line(self):
        """T3 看到的可用额度 = 总额 − 预留；总额跌到预留线以下时它必须看到 0。"""
        os.environ["SEARCH_RESERVE_CAMPUS"] = "25"
        self.assertEqual(_router(60, 40).remaining(None), 100)
        self.assertEqual(_router(60, 40).remaining_above_reserve(None), 75)
        self.assertEqual(_router(20).remaining_above_reserve(None), 0)   # 20 < 25 → 贪心方看到 0
        self.assertEqual(_router(25).remaining_above_reserve(None), 0)   # 恰好等于预留 → 0

    def test_reserved_slice_is_still_visible_to_campus_chain(self):
        """关键不变量：校招链调的是 remaining()，预留的那份它必须能真的用到，
        否则只是把额度锁死、两边都跑不成。"""
        os.environ["SEARCH_RESERVE_CAMPUS"] = "25"
        r = _router(20)
        self.assertEqual(r.remaining_above_reserve(None), 0)   # T3 停手
        self.assertEqual(r.remaining(None), 20)                 # 校招链仍有 20 次可用

    def test_never_negative(self):
        os.environ["SEARCH_RESERVE_CAMPUS"] = "25"
        self.assertEqual(_router(0).remaining_above_reserve(None), 0)


if __name__ == "__main__":
    unittest.main()
