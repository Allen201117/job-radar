"""Moka 抓全率可观测（reported_total / fetch_complete）。

治的病：2026-09-04 实测，318 个校招/实习板块的源里有 **195 个连分母都没有**，
其中 **190 个是 moka** —— 也就是「这些公司的校招岗抓全了吗」，对六成的源根本答不上来。
Moka 的列表接口是密文、DOM 里也没有「共 N 个职位」（那句只在门户落地页），
**唯一能拿到分母的地方是分页组件的总页数**。

钉死三件事：① 翻到末页=抓全，分母记实际条数（不编造精度）；
② 没翻到末页必须 fetch_complete=False 且给出上界分母，让抓不全告警看得见；
③ 单页租户（不渲染分页器）也算抓全，不能因为「读不到总页数」就集体判不可判定。
"""
import json
import unittest

from adapters.china_ats import MokaAdapter


class _El:
    def __init__(self, text):
        self._t = text

    def inner_text(self):
        return self._t


class _Page:
    """够 _collect_all_pages 用的最小 page 替身。"""

    def __init__(self, pages, page_numbers):
        self.pages = pages                # [[href, ...], ...]
        self.page_numbers = page_numbers  # 分页器上的页码文本
        self.idx = 0
        self.stuck_at = None              # 停在这一页（0 起）：点「下一页」不生效 / 抛 click_error
        self.click_error = None

    def eval_on_selector_all(self, sel, js):
        return [{"href": h, "text": "岗"} for h in self.pages[self.idx]]

    def query_selector_all(self, sel):
        return [_El(t) for t in self.page_numbers]

    def query_selector(self, sel):
        if self.idx >= len(self.pages) - 1:
            return _NextBtn(disabled=True)
        return _NextBtn(disabled=False, page=self)

    def wait_for_timeout(self, _ms):
        pass


class _NextBtn:
    def __init__(self, disabled, page=None):
        self.disabled = disabled
        self.page = page

    def get_attribute(self, name):
        if name == "class":
            return "sd-Pagination-forward disabled" if self.disabled else "sd-Pagination-forward"
        if name == "disabled":
            return "" if self.disabled else None
        return None

    def click(self, timeout=None):
        if self.page is not None:
            if self.page.click_error is not None and self.page.idx == self.page.stuck_at:
                raise self.page.click_error
            if self.page.idx == self.page.stuck_at:
                return   # 点了，但页面没翻过去
            self.page.idx += 1

    def scroll_into_view_if_needed(self, timeout=None):
        pass


def _finish(adapter, cards):
    """fetch 收尾那段（fetch 本体要起浏览器，单测不跑它）——直接调生产端同一个方法，不另抄一份。"""
    adapter._finalize_coverage(cards, "https://app.mokahr.com/social-recruitment/t/1")


class MokaCoverageTest(unittest.TestCase):
    def test_reaching_last_page_counts_as_complete(self):
        a = MokaAdapter()
        page = _Page([[f"#/job/{i}" for i in range(30)], [f"#/job/{30+i}" for i in range(10)]],
                     ["1", "2"])
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertEqual(len(cards), 40)
        self.assertEqual(a.reported_total, 40, "翻到末页时分母就是抓到数，不编造精度")
        self.assertTrue(a.fetch_complete)

    def test_single_page_tenant_without_paginator_is_complete(self):
        a = MokaAdapter()
        page = _Page([[f"#/job/{i}" for i in range(7)]], [])   # 不渲染分页器
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertIsNone(a._last_page)
        self.assertTrue(a.fetch_complete, "单页租户不能因为读不到总页数就判成不可判定")
        self.assertEqual(a.reported_total, 7)

    def test_stopping_before_last_page_is_incomplete_with_upper_bound(self):
        a = MokaAdapter()
        a._page_cap = 2                       # 人为把翻页预算卡在第 2 页
        pages = [[f"#/job/{p}_{i}" for i in range(30)] for p in range(5)]
        page = _Page(pages, ["1", "2", "3", "4", "5"])
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertFalse(a.fetch_complete, "没翻到末页必须如实记，否则 190 个源的缺口永远看不见")
        self.assertEqual(a.reported_total, 5 * a._PAGE_ROWS, "分母用总页数×每页行数的上界估计")
        self.assertGreater(a.reported_total, len(cards))

    def test_zero_cards_reports_no_denominator(self):
        a = MokaAdapter()
        page = _Page([[]], ["1"])
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertEqual(cards, [])
        self.assertIsNone(a.reported_total, "一条都没拿到时别拿 0 当分母")

    def test_read_last_page_picks_max_number(self):
        a = MokaAdapter()
        self.assertEqual(a._read_last_page(_Page([[]], ["1", "2", "3", "4"])), 4)
        self.assertEqual(a._read_last_page(_Page([[]], ["1\n2\n3", "12"])), 12)
        self.assertIsNone(a._read_last_page(_Page([[]], [])))


class MokaStopReasonTest(unittest.TestCase):
    """没翻到末页时，停因必须留下来（写 coverage_stop_reason + warning），否则告警只知道「缺」不知道「为什么」。

    病例（09-24~28 抓不全告警）：百济神州分页器 17 页、每次只入库 30 岗（第 1 页）；
    58同城 16 页、每次 150 岗（第 5 页）。代码里三种停法（点击失败 / 点了没翻 / 撞上限）都不留痕。
    """

    @staticmethod
    def _pages(n):
        return [[f"#/job/{p}_{i}" for i in range(30)] for p in range(n)]

    def test_click_blocked_records_reason_and_playwright_evidence(self):
        a = MokaAdapter()
        page = _Page(self._pages(17), [str(i) for i in range(1, 18)])
        page.stuck_at = 0
        page.click_error = Exception(
            "Timeout 2500ms exceeded.\n  - <div class=\"sd-Modal-drawer\">…</div> intercepts pointer events\n  - retrying")
        with self.assertLogs("adapters.china_ats", level="WARNING") as logs:
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertEqual(len(cards), 30)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.reported_total, 17 * a._PAGE_ROWS)
        self.assertEqual(a.coverage_stop_reason, "page_click_failed")
        self.assertIn("intercepts pointer events", a._stop_detail, "挡住按钮的元素是唯一的现场证据")
        self.assertIn("page_click_failed", "\n".join(logs.output))

    def test_click_that_does_not_advance_is_page_no_new_rows(self):
        a = MokaAdapter()
        page = _Page(self._pages(16), [str(i) for i in range(1, 17)])
        page.stuck_at = 4                     # 58同城：停在第 5 页
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertEqual(len(cards), 150)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.coverage_stop_reason, "page_no_new_rows")

    def test_stuck_one_page_before_the_end_is_not_counted_as_complete(self):
        """旧写法每轮都给 pages_done +1：6 页租户卡在第 5 页会数成 7 页 ≥ 6 → 误判抓全、缺口消失。"""
        a = MokaAdapter()
        page = _Page(self._pages(6), [str(i) for i in range(1, 7)])
        page.stuck_at = 4
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertEqual(len(cards), 150)
        self.assertEqual(a._pages_done, 5)
        self.assertFalse(a.fetch_complete)

    def test_page_cap_records_list_cap(self):
        a = MokaAdapter()
        a._page_cap = 2
        page = _Page(self._pages(5), ["1", "2", "3", "4", "5"])
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.coverage_stop_reason, "list_cap")

    def test_complete_crawl_leaves_no_reason(self):
        a = MokaAdapter()
        page = _Page(self._pages(3), ["1", "2", "3"])
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertTrue(a.fetch_complete)
        self.assertIsNone(a.coverage_stop_reason)


if __name__ == "__main__":
    unittest.main()
