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
            self.page.idx += 1

    def scroll_into_view_if_needed(self, timeout=None):
        pass


def _finish(adapter, cards):
    """复刻 fetch 收尾那段的判定（fetch 本体要起浏览器，单测不跑它）。"""
    last_page = getattr(adapter, "_last_page", None)
    pages_done = getattr(adapter, "_pages_done", 0)
    if not cards:
        adapter.reported_total = None
    elif not last_page or pages_done >= last_page:
        adapter.reported_total = len(cards)
        adapter.fetch_complete = True
    else:
        adapter.reported_total = max(len(cards), last_page * adapter._PAGE_ROWS)
        adapter.fetch_complete = False


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


if __name__ == "__main__":
    unittest.main()
