"""Moka 抓全率可观测（reported_total / fetch_complete）。

治的病：2026-09-04 实测，318 个校招/实习板块的源里有 **195 个连分母都没有**，
其中 **190 个是 moka** —— 也就是「这些公司的校招岗抓全了吗」，对六成的源根本答不上来。

2026-10-11 再治一次：当时以为「唯一能拿到分母的地方是分页组件的总页数」，于是「没找到下一页按钮」
直接等于「单页抓全」。老版门户的翻页器是另一套 class，43 条源每晚只入库第 1 页的 15 个岗却记抓全
（祖龙门户自报 86、万科 1,312、移远 730）。分母其实在页面内嵌数据里（jobStats.total）。

钉死的事：① 两套翻页器都认；② 分母优先用门户自报总数，抓到的数明显少于它就不算抓全，
不管页面上有没有下一页按钮；③ 读不到门户总数时退回旧口径（翻到末页=抓全，没翻到给上界分母）；
④ 等「下一页渲染回来」而不是固定睡一会儿，等不到要留停因；⑤ 门店批量岗由重复度刹车收住。
"""
import json
import unittest

from adapters.base import RepetitionBrake
from adapters.china_ats import MokaAdapter, _moka_portal_total

SOURCE = "https://app.mokahr.com/social-recruitment/t/1"


class _El:
    def __init__(self, text):
        self._t = text

    def inner_text(self):
        return self._t


class _Timeout(Exception):
    """模拟 playwright TimeoutError（adapter 只按 Exception 处理，不依赖具体类型）。"""


class _Page:
    """够 _collect_all_pages 用的最小 page 替身。按选择器分派，和真页面一样：问哪套翻页器就答哪套。"""

    def __init__(self, pages, page_numbers, legacy=False, pager=True, titles=None):
        self.pages = pages                # [[href, ...], ...]
        self.page_numbers = page_numbers  # 分页器上的页码文本
        self.legacy = legacy              # True = 老版门户的 .theme-pagination 那一套
        self.pager = pager                # False = 页面上没有我们认识的翻页器
        self.titles = titles or {}        # href → 标题（默认「岗」+ href，各不相同）
        self.idx = 0
        self.stuck_at = None              # 停在这一页（0 起）：点「下一页」不生效 / 抛 click_error
        self.click_error = None
        self.click_errors_left = None     # 只让前 N 次点击抛 click_error（None = 每次都抛）
        self.blank_after_click_at = None  # 在这一页点了「下一页」之后，列表和翻页器再也没渲染回来
        self.blank = False
        self.pager_gone_from = None       # 翻到这一页（0 起）之后页面上不再有翻页器，但列表照常渲染
        self.wait_error = None            # 等翻页时抛这个（不是超时）
        self.turn_waits = []              # 每次等翻页时传进来的参数
        self.first_page_waits = []        # 开读前等首屏列表时传进来的参数
        self.list_late = False            # 首屏列表还没到：页面上只有前 8 张推荐岗、没有翻页器，等一下才渲染出来
        self.sleeps = []                  # wait_for_timeout 的毫秒数
        self.clicks = 0

    def _pager_present(self):
        if not self.pager or self.blank or self.list_late:
            return False
        return self.pager_gone_from is None or self.idx < self.pager_gone_from

    def eval_on_selector_all(self, sel, js):
        if self.blank:
            return []
        hrefs = self.pages[self.idx][:8] if self.list_late else self.pages[self.idx]
        return [{"href": h, "text": self.titles.get(h, f"岗{h}")} for h in hrefs]

    def query_selector_all(self, sel):
        return [_El(t) for t in self.page_numbers]

    def query_selector(self, sel):
        if sel == MokaAdapter._COOKIE_ACCEPT_SEL:
            return None
        if sel == MokaAdapter._legacy_pager_sel:
            return _El("") if (self.legacy and self._pager_present()) else None
        if not self._pager_present():
            return None
        if sel == MokaAdapter._active_page_sel:
            return _El(str(self.idx + 1))
        assert sel == MokaAdapter._next_sel, sel
        return _NextBtn(self, disabled=self.idx >= len(self.pages) - 1)

    def wait_for_function(self, js, arg=None, timeout=None, polling=None):
        if js == MokaAdapter._FIRST_PAGE_JS:
            self.first_page_waits.append(arg)
            self.list_late = False        # 等到了：列表和翻页器渲染出来
            return
        assert js == MokaAdapter._TURNED_JS
        self.turn_waits.append(arg)
        if self.wait_error is not None:
            raise self.wait_error
        if not self._pager_present() or self.idx == self.stuck_at:
            raise _Timeout("wait_for_function timed out")

    def wait_for_timeout(self, ms):
        self.sleeps.append(ms)


class _NextBtn:
    def __init__(self, page, disabled):
        self.page = page
        self.disabled = disabled

    def get_attribute(self, name):
        if self.page.legacy:
            # 老版：末页只多一个 disabled-<hash> 的 class，没有 disabled 属性（2026-10-11 祖龙第 6 页实读）
            if name == "class":
                return ("pagination-item next-page-1ksQAFhCzQ disabled-1N_lD40T5F" if self.disabled
                        else "pagination-item next-page-1ksQAFhCzQ")
            return None
        if name == "class":
            return "sd-Pagination-item-4J_pS sd-Pagination-forward-2Dk1n"
        if name == "disabled":
            return "" if self.disabled else None
        return None

    def click(self, timeout=None):
        page = self.page
        page.clicks += 1
        if page.click_error is not None and page.idx == page.stuck_at:
            if page.click_errors_left is None:
                raise page.click_error
            if page.click_errors_left > 0:
                page.click_errors_left -= 1
                raise page.click_error
            page.stuck_at = None   # 挡住按钮的东西清掉了，这一次点得动
        if page.idx == page.stuck_at:
            return   # 点了，但页面没翻过去
        if page.idx == page.blank_after_click_at:
            page.blank = True
            return
        page.idx += 1

    def scroll_into_view_if_needed(self, timeout=None):
        pass


def _finish(adapter, cards):
    """fetch 收尾那段（fetch 本体要起浏览器，单测不跑它）——直接调生产端同一个方法，不另抄一份。"""
    adapter._finalize_coverage(cards, SOURCE)


def _pages(n, rows=30):
    return [[f"#/job/{p}_{i}" for i in range(rows)] for p in range(n)]


class MokaCoverageTest(unittest.TestCase):
    def test_reaching_last_page_counts_as_complete(self):
        a = MokaAdapter()
        page = _Page([[f"#/job/{i}" for i in range(30)], [f"#/job/{30+i}" for i in range(10)]],
                     ["1", "2"])
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertEqual(len(cards), 40)
        self.assertEqual(a.reported_total, 40, "读不到门户自报总数时，分母就是抓到数，不编造精度")
        self.assertTrue(a.fetch_complete)

    def test_single_page_tenant_without_paginator_is_complete(self):
        a = MokaAdapter()
        page = _Page([[f"#/job/{i}" for i in range(7)]], [], pager=False)   # 不渲染分页器
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertIsNone(a._last_page)
        self.assertTrue(a.fetch_complete, "单页租户不能因为读不到总页数就判成不可判定")
        self.assertEqual(a.reported_total, 7)

    def test_stopping_before_last_page_is_incomplete_with_upper_bound(self):
        a = MokaAdapter()
        a._page_cap = 2                       # 人为把翻页预算卡在第 2 页
        page = _Page(_pages(5), ["1", "2", "3", "4", "5"])
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertFalse(a.fetch_complete, "没翻到末页必须如实记，否则 190 个源的缺口永远看不见")
        self.assertEqual(a.reported_total, 5 * a._PAGE_ROWS, "读不到门户总数时，分母用总页数×每页行数的上界估计")
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
        # 老版翻页器：上一页 / 下一页按钮没有文字，中间省略时只剩头几页和末页（麦当劳实读「1 2 3 4 5 3880」）
        self.assertEqual(a._read_last_page(_Page([[]], ["", "1", "2", "3", "4", "5", "3880", ""])), 3880)


class MokaLegacyPaginatorTest(unittest.TestCase):
    """老版门户（页面内嵌数据 websiteVersion=1）的翻页器是另一套 class，2026-10-11 前完全不认。"""

    def test_selectors_cover_both_paginators(self):
        # 选择器是在真页面上读的，不是猜的；这里只钉「两套都在」，防有人删掉一套。
        self.assertIn("button[class*='sd-Pagination-forward']", MokaAdapter._next_sel)
        self.assertIn(".theme-pagination .pagination-item[class*='next-page-']", MokaAdapter._next_sel)
        self.assertIn("sd-Pagination-item", MokaAdapter._page_no_sel)
        self.assertIn(".theme-pagination .pagination-item", MokaAdapter._page_no_sel)

    def test_legacy_portal_is_walked_to_the_last_page(self):
        """祖龙：6 页、每页 15 行、共 86 岗。末页的「下一页」只多一个 disabled class。"""
        a = MokaAdapter()
        a._portal_total = 86
        pages = _pages(5, rows=15) + [[f"#/job/5_{i}" for i in range(11)]]
        page = _Page(pages, ["", "1", "2", "3", "4", "5", "6", ""], legacy=True)
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertEqual(len(cards), 86)
        self.assertEqual(a._pages_done, 6)
        self.assertTrue(a.fetch_complete)
        self.assertEqual(a.reported_total, 86)
        self.assertIsNone(a.coverage_stop_reason)

    def test_legacy_upper_bound_uses_15_rows_per_page(self):
        a = MokaAdapter()
        a._page_cap = 2
        page = _Page(_pages(6, rows=15), ["", "1", "2", "3", "4", "5", "6", ""], legacy=True)
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.reported_total, 6 * a._PAGE_ROWS_LEGACY)


class MokaPortalTotalTest(unittest.TestCase):
    """分母优先用门户自报总数：「页面上没有下一页按钮」不等于「单页抓全」。"""

    def test_no_next_button_but_portal_reports_more_is_incomplete(self):
        """改前的现场：祖龙首屏 15 张卡、没认出翻页器 → reported_total=15、fetch_complete=True。"""
        a = MokaAdapter()
        a._portal_total = 86
        page = _Page([[f"#/job/{i}" for i in range(15)]], [], pager=False)
        with self.assertLogs("adapters.china_ats", level="WARNING") as logs:
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertEqual(len(cards), 15)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.reported_total, 86, "分母用门户自报的数")
        self.assertEqual(a.coverage_stop_reason, "paginator_not_found")
        self.assertIn("门户自报 86", "\n".join(logs.output))

    def test_single_page_tenant_matching_portal_total_is_complete(self):
        a = MokaAdapter()
        a._portal_total = 7
        page = _Page([[f"#/job/{i}" for i in range(7)]], [], pager=False)
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertTrue(a.fetch_complete)
        self.assertEqual(a.reported_total, 7)
        self.assertIsNone(a.coverage_stop_reason)

    def test_sidebar_links_do_not_count_as_a_second_page(self):
        """右栏「最新职位」和列表是同一批岗的第二个链接：12 个岗的单页门户不能数成 17 个 / 两页。"""
        a = MokaAdapter()
        a._portal_total = 12
        listing = [f"#/job/{i}" for i in range(12)]
        page = _Page([listing + listing[:5]], [], pager=False)
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertEqual(len(cards), 12)
        self.assertEqual(a._pages_done, 1)
        self.assertTrue(a.fetch_complete)
        self.assertEqual(a.reported_total, 12)

    def test_small_drift_against_portal_total_is_still_complete(self):
        """门户总数是打开页面那一刻读的，翻完要几分钟，其间有上下架：差一两个不算没抓全。"""
        # (1312, 1307) 是万科的实测：87 整页 + 末页 2 张都读到了，门户总数自己多 5
        for portal_total, got in ((100, 98), (5, 4), (1600, 1597), (40, 41), (1312, 1307)):
            a = MokaAdapter()
            a._portal_total = portal_total
            a._last_page, a._pages_done, a._pager_seen = 4, 4, True
            _finish(a, [{"href": f"#/job/{i}"} for i in range(got)])
            self.assertTrue(a.fetch_complete, (portal_total, got))
            self.assertEqual(a.reported_total, max(portal_total, got))

    def test_walked_to_the_end_but_clearly_short_is_incomplete(self):
        # (637, 615) 是滴滴的实测：第 1 页只读到 8 张就翻页了，漏 22 个
        for portal_total, got in ((100, 90), (18, 15), (1312, 900), (637, 615)):
            a = MokaAdapter()
            a._portal_total = portal_total
            a._last_page, a._pages_done, a._pager_seen = 4, 4, True
            with self.assertLogs("adapters.china_ats", level="WARNING"):
                _finish(a, [{"href": f"#/job/{i}"} for i in range(got)])
            self.assertFalse(a.fetch_complete, (portal_total, got))
            self.assertEqual(a.reported_total, portal_total)
            self.assertEqual(a.coverage_stop_reason, "short_of_portal_total")

    def test_stopped_midway_uses_portal_total_as_denominator(self):
        a = MokaAdapter()
        a._portal_total = 481                 # 百济神州：分页器 17 页，上界估计会给 510
        page = _Page(_pages(17), [str(i) for i in range(1, 18)])
        page.stuck_at = 0
        page.click_error = Exception("Timeout 2500ms exceeded.")
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.reported_total, 481)
        self.assertEqual(a.coverage_stop_reason, "page_click_failed")

    def test_everything_the_portal_reports_beats_a_page_count_that_looks_short(self):
        """页码会少数：某一页整页都是早先见过的岗（万科末页 7 张里 5 张是右栏那几个）。门户说 86、手里就有 86，算抓全。"""
        a = MokaAdapter()
        a._portal_total = 86
        a._last_page, a._pages_done, a._pager_seen = 6, 5, True
        _finish(a, [{"href": f"#/job/{i}"} for i in range(86)])
        self.assertTrue(a.fetch_complete)
        self.assertEqual(a.reported_total, 86)

    def test_page_count_short_without_everything_is_still_incomplete(self):
        a = MokaAdapter()
        a._portal_total = 86
        a._last_page, a._pages_done, a._pager_seen = 6, 5, True
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            _finish(a, [{"href": f"#/job/{i}"} for i in range(84)])   # 差 2 个在容差内，但页数没翻够
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.reported_total, 86)

    def test_zero_cards_while_portal_reports_jobs_is_incomplete(self):
        a = MokaAdapter()
        a._portal_total = 39
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            _finish(a, [])
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.reported_total, 39, "门户说有 39 个岗、我们一个没拿到，这不是「没有分母」")
        self.assertEqual(a.coverage_stop_reason, "short_of_portal_total", "一张卡都没有，谈不上「没认出翻页器」")

    def test_zero_cards_and_portal_reports_zero_has_no_denominator(self):
        a = MokaAdapter()
        a._portal_total = 0
        _finish(a, [])
        self.assertIsNone(a.reported_total)
        self.assertFalse(a.fetch_complete)


class MokaPortalTotalParseTest(unittest.TestCase):
    @staticmethod
    def _doc(payload, attrs='id="init-data" type="hidden"', value_first=False):
        value = json.dumps(payload, ensure_ascii=False).replace("&", "&amp;").replace('"', "&quot;")
        if value_first:
            return f'<html><body><input type="hidden" value="{value}" id="init-data"></body></html>'
        return f'<html><body><input {attrs} value="{value}"><div id="root"></div></body></html>'

    def test_reads_job_stats_total(self):
        doc = self._doc({"jobStats": {"orgId": "zulong", "total": 86}, "websiteVersion": 1, "jobs": [{}] * 15})
        self.assertEqual(_moka_portal_total(doc), 86)
        self.assertEqual(_moka_portal_total(self._doc({"jobStats": {"total": 0}})), 0)
        self.assertEqual(_moka_portal_total(self._doc({"jobStats": {"total": 86}}, value_first=True)), 86)

    def test_unreadable_documents_give_none(self):
        self.assertIsNone(_moka_portal_total(""))
        self.assertIsNone(_moka_portal_total(None))
        self.assertIsNone(_moka_portal_total("<html><body>当前网页已关停</body></html>"))
        # 门户报错页也带 init-data，但里面没有 jobStats（2026-10-11 实读：keys = cdnPublicPath / isBizError / message）
        self.assertIsNone(_moka_portal_total(self._doc({"isBizError": True, "message": "x"})))
        self.assertIsNone(_moka_portal_total('<input id="init-data" value="{not json">'))
        for bad in ("86", -1, True, None, 3.5):
            self.assertIsNone(_moka_portal_total(self._doc({"jobStats": {"total": bad}})), bad)


class _Resp:
    def __init__(self, body=None, error=None):
        self._body, self._error = body, error

    def text(self):
        if self._error:
            raise self._error
        return self._body


class MokaPortalTotalCaptureTest(unittest.TestCase):
    DOC = '<input id="init-data" value="{&quot;jobStats&quot;:{&quot;total&quot;:86}}">'

    def _adapter(self):
        a = MokaAdapter()
        a._own_base = SOURCE
        return a

    def test_reads_from_the_sources_own_document(self):
        a = self._adapter()
        a._note_portal_total(_Resp(self.DOC), SOURCE + "#/jobs")
        self.assertEqual(a._portal_total, 86)

    def test_hash_only_navigation_keeps_the_first_value(self):
        a = self._adapter()
        a._note_portal_total(_Resp(self.DOC), SOURCE + "#/jobs")
        a._note_portal_total(None, SOURCE + "#/campus/jobs")   # 同文档导航，goto 返回 None
        self.assertEqual(a._portal_total, 86)

    def test_other_portals_document_is_ignored(self):
        """校招换期检查会在同一个浏览器里打开别名门户，那边的总数不是这条源的分母。"""
        a = self._adapter()
        a._note_portal_total(_Resp(self.DOC), "https://app.mokahr.com/campus_apply/t/999#/jobs")
        self.assertIsNone(a._portal_total)

    def test_unreadable_body_never_raises(self):
        a = self._adapter()
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            a._note_portal_total(_Resp(error=RuntimeError("No resource with given identifier")), SOURCE)
        self.assertIsNone(a._portal_total)


class MokaPageTurnWaitTest(unittest.TestCase):
    """点完「下一页」要等列表渲染回来，不能固定睡一会儿就读。"""

    def test_waits_for_the_next_page_to_render(self):
        a = MokaAdapter()
        page = _Page(_pages(3), ["1", "2", "3"])
        cards = a._collect_all_pages(page)
        self.assertEqual(len(cards), 90)
        self.assertEqual(len(page.turn_waits), 2, "每点一次下一页等一次")
        next_sel, active_sel, prev_cards, prev_active = page.turn_waits[0]
        self.assertEqual((next_sel, active_sel), (MokaAdapter._next_sel, MokaAdapter._active_page_sel))
        self.assertEqual(prev_cards, "|".join(f"#/job/0_{i}" for i in range(30)))
        self.assertEqual(prev_active, "1")

    def test_first_page_waits_for_the_list_before_reading(self):
        """滴滴（门户自报 637）：开读那一刻页面上只有 8 张推荐岗、翻页器还没出来，随后列表才到。
        不等的话第 1 页另外 22 个岗读不到（接着就点下一页了），总页数也读成「没有」。"""
        a = MokaAdapter()
        a._portal_total = 90
        page = _Page(_pages(3), ["1", "2", "3"])
        page.list_late = True
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertEqual(len(page.first_page_waits), 1)
        next_sel, enough = page.first_page_waits[0]
        self.assertEqual(next_sel, MokaAdapter._next_sel)
        self.assertEqual(enough, 90 - MokaAdapter._PORTAL_SHORT_MIN)
        self.assertEqual(len(cards), 90, "第 1 页的 30 张要读全")
        self.assertEqual(a._last_page, 3)
        self.assertTrue(a.fetch_complete)

    def test_first_page_is_not_waited_for_without_a_portal_total(self):
        a = MokaAdapter()
        page = _Page(_pages(2), ["1", "2"])
        a._collect_all_pages(page)
        self.assertEqual(page.first_page_waits, [], "没有门户总数就没有「够不够」的判据，不白等")

    def test_next_page_never_rendering_is_not_a_single_page_tenant(self):
        """麦当劳本机实测翻一页要 2.6s，其间列表和翻页器都不在页面上。等不回来必须留停因，
        不能读成「没有下一页按钮 = 单页抓全」（吉利 / 百济神州 / 58同城 / 太古的抓不全记录停因都是空的）。"""
        a = MokaAdapter()
        page = _Page(_pages(5), ["1", "2", "3", "4", "5"])
        page.blank_after_click_at = 1          # 第 2 页点完之后再也没渲染回来
        with self.assertLogs("adapters.china_ats", level="WARNING") as logs:
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertEqual(len(cards), 60)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.coverage_stop_reason, "page_render_timeout")
        self.assertIn("page_render_timeout", "\n".join(logs.output))

    def test_page_that_turned_but_lost_its_paginator_keeps_its_rows(self):
        """没等到「翻页器回来」不等于这一页没翻过去：停之前再读一次，读到新卡就照收。"""
        a = MokaAdapter()
        a._portal_total = 90
        page = _Page(_pages(3), ["1", "2", "3"])
        page.pager_gone_from = 1               # 第 2 页起页面上没有翻页器了，列表照常渲染
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertEqual(len(cards), 60, "第 2 页的 30 张不能丢")
        self.assertFalse(a.fetch_complete, "门户自报 90、只拿到 60")
        self.assertEqual(a.coverage_stop_reason, "short_of_portal_total")

    def test_predicate_failure_falls_back_to_the_old_fixed_wait(self):
        """等翻页的判据自己报错（不是超时）时，按超时处理等于立刻回去读——退回旧的固定等待，并留一条日志。"""
        a = MokaAdapter()
        page = _Page(_pages(2), ["1", "2"])
        page.wait_error = RuntimeError("Execution context was destroyed")
        with self.assertLogs("adapters.china_ats", level="WARNING") as logs:
            cards = a._collect_all_pages(page)
        self.assertEqual(len(cards), 60)
        self.assertIn(MokaAdapter._TURN_FALLBACK_MS, page.sleeps)
        self.assertIn("判据没跑成", "\n".join(logs.output))

    def test_turn_predicate_does_not_wait_forever_when_active_page_is_unreadable(self):
        """当前页码读不到（空串）时只看卡片换没换；判据里漏了这一支，每翻一页都会白等满时限。"""
        self.assertIn("!prevActive ||", MokaAdapter._TURNED_JS)

    def test_last_allowed_page_is_not_followed_by_a_wasted_click(self):
        """页数预算用完就停，别再点一次没人读的下一页（探活快模式 _page_cap=1 每个候选都会白等一次）。"""
        a = MokaAdapter()
        a._page_cap = 1
        page = _Page(_pages(5), ["1", "2", "3", "4", "5"])
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertEqual(len(cards), 30)
        self.assertEqual(page.clicks, 0)
        self.assertEqual(page.turn_waits, [])
        self.assertEqual(a.coverage_stop_reason, "list_cap")

    def test_click_that_succeeds_on_retry_keeps_walking(self):
        a = MokaAdapter()
        page = _Page(_pages(3), ["1", "2", "3"])
        page.stuck_at = 0
        page.click_error = Exception("Timeout 2500ms exceeded.\n  - <div> intercepts pointer events")
        page.click_errors_left = 1             # cookies 抽屉晚弹出来：第一次点被挡，清掉后重试点得动
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertEqual(len(cards), 90)
        self.assertTrue(a.fetch_complete)
        self.assertIsNone(a.coverage_stop_reason)


class MokaRepetitionBrakeTest(unittest.TestCase):
    """门店批量岗（麦当劳社招门户自报 58,187 个，98.5% 是门店类）不能一口气灌进来。"""

    def test_bulk_store_postings_are_braked(self):
        a = MokaAdapter()
        a._portal_total = 58187
        pages = _pages(200, rows=15)
        titles = {h: "餐厅员工" for row in pages for h in row}
        page = _Page(pages, ["", "1", "2", "3", "4", "5", "3880", ""], legacy=True, titles=titles)
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        stall = RepetitionBrake().stall_rows
        self.assertLessEqual(len(cards), stall + 2 * 15, "连续 stall_rows 条没有新角色就该停")
        self.assertFalse(a.fetch_complete, "刹停 = 没抓全")
        self.assertEqual(a.coverage_stop_reason, "repetition_brake")
        self.assertEqual(a.reported_total, 58187)

    def test_varied_titles_are_never_braked(self):
        a = MokaAdapter()
        pages = _pages(40)
        # 1,200 个各不相同的岗位角色（刹车按「去数字去括号后的标题」判重，只差编号的标题算同一个角色）
        fields = ("研发 测试 产品 运营 设计 市场 销售 财务 法务 人事 行政 采购 物流 客服 数据 算法 硬件 嵌入式 前端 后端 "
                  "运维 安全 质量 工艺 结构 电气 机械 光学 射频 芯片 固件 驱动 系统 架构 项目 商务 投资 审计 税务 培训").split()
        ranks = ("工程师 经理 专员 主管 总监 助理 顾问 分析师 架构师 负责人 实习生 管培生 专家 组长 科长 "
                 "部长 主任 代表 策划 督导 讲师 编辑 文案 翻译 研究员 技术员 操作员 调度 质检 巡检").split()
        roles = [f + r for f in fields for r in ranks]
        titles = {h: roles[p * 30 + i] for p, row in enumerate(pages) for i, h in enumerate(row)}
        self.assertEqual(len(set(titles.values())), 1200)
        page = _Page(pages, [str(i) for i in range(1, 41)], titles=titles)
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertEqual(len(cards), 1200)
        self.assertTrue(a.fetch_complete)
        self.assertIsNone(a.coverage_stop_reason)

    def test_moka_never_retires_jobs_by_list_absence(self):
        """刹停 / 抓不全都会让列表缺一截。Moka 没开「列表缺席即撤岗」，这条不变量别动。"""
        self.assertFalse(getattr(MokaAdapter, "supports_absence_liveness", False))


class MokaStopReasonTest(unittest.TestCase):
    """没翻到末页时，停因必须留下来（写 coverage_stop_reason + warning），否则告警只知道「缺」不知道「为什么」。

    病例（09-24~28 抓不全告警）：百济神州分页器 17 页、每次只入库 30 岗（第 1 页）；
    58同城 16 页、每次 150 岗（第 5 页）。代码里三种停法（点击失败 / 点了没翻 / 撞上限）都不留痕。
    """

    def test_click_blocked_records_reason_and_playwright_evidence(self):
        a = MokaAdapter()
        page = _Page(_pages(17), [str(i) for i in range(1, 18)])
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
        page = _Page(_pages(16), [str(i) for i in range(1, 17)])
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
        page = _Page(_pages(6), [str(i) for i in range(1, 7)])
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
        page = _Page(_pages(5), ["1", "2", "3", "4", "5"])
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.coverage_stop_reason, "list_cap")

    def test_interrupted_walk_is_never_complete_even_when_page_numbers_are_unreadable(self):
        """总页数读不到时不能反推「翻完了」：循环是被点击失败打断的，就不算抓全，停因照实写。"""
        a = MokaAdapter()
        page = _Page(_pages(5), [])            # 翻页器在、页码一个都没读到
        page.stuck_at = 1
        page.click_error = Exception("Timeout 2500ms exceeded.")
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertIsNone(a._last_page)
        self.assertEqual(len(cards), 60)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.coverage_stop_reason, "page_click_failed")

    def test_brake_reason_survives_when_portal_total_says_short(self):
        """刹停时抓到的数必然远少于门户自报——停因要留「按设计刹停」，不能被改写成「比门户自报少」。"""
        a = MokaAdapter()
        a._portal_total = 58187
        pages = _pages(60, rows=15)
        page = _Page(pages, [], legacy=True, titles={h: "餐厅员工" for row in pages for h in row})
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            cards = a._collect_all_pages(page)
            _finish(a, cards)
        self.assertIsNone(a._last_page)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.coverage_stop_reason, "repetition_brake")

    def test_complete_crawl_leaves_no_reason(self):
        a = MokaAdapter()
        page = _Page(_pages(3), ["1", "2", "3"])
        cards = a._collect_all_pages(page)
        _finish(a, cards)
        self.assertTrue(a.fetch_complete)
        self.assertIsNone(a.coverage_stop_reason)

    def test_every_stop_reason_moka_writes_has_a_label_or_is_by_design(self):
        """adapter 写的停因在告警那头要么有人话标签，要么是按设计单列的那一种；加取值两边一起加。"""
        import ops_watchdog
        written = {"list_cap", "page_click_failed", "page_no_new_rows", "page_render_timeout",
                   "paginator_not_found", "short_of_portal_total"}
        self.assertLessEqual(written, set(ops_watchdog.COVERAGE_STOP_LABELS))
        self.assertNotIn("repetition_brake", ops_watchdog.COVERAGE_STOP_LABELS, "刹车是按设计停，规则 G 单列")


if __name__ == "__main__":
    unittest.main()
