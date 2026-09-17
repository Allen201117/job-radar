"""北森「卡片式 CMS 门户」解析单测 —— 内联 HTML 片段，不打真实网络。

对应 adapters/china_ats.py 的 _card_* 纯函数与 BeisenAdapter._httpx_fetch_cards。
HTML 片段按 2026-09-18 live 抓下来的方太集团（fotile.zhiye.com）真实结构裁剪，
保留全部会咬人的细节：<a> 体内整段 JD、<dd> 标题、地点被按宽度截断的三种写法、
注释里的模板占位假岗、越界页仍返 200+骨架、详情页两段式正文。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import adapters.china_ats as china_ats  # noqa: E402
from adapters.china_ats import (  # noqa: E402
    BeisenAdapter,
    _beisen_route_usable,
    _card_board_job_type,
    _card_parse_detail,
    _card_parse_list,
    _cms_parse_list,
    beisen_httpx_ready,
)

ORIGIN = "https://tenant.zhiye.com"
LONG_JD = "负责" + "职责描述文本" * 30      # 足够长，保证「整个 <a> 文本当标题」会被长度门丢掉
SHORT_JD = "负责门店日常运营。"              # 足够短，会**越过**长度门 —— 正是老代码悄悄写垃圾标题的那一类


def _card(job_id, title, meta, jd=LONG_JD, path="/job_show"):
    return (f'<li>\n  <a href="{path}?jobId={job_id}" target="_blank">\n'
            f'    <dd>{title}</dd>\n'
            f'    <ol>{meta}</ol>\n'
            f'    <dl>\n      <p>{jd}</p>\n    </dl>\n'
            f'  </a>\n</li>')


def _pager(current, last):
    links = "".join(f"<li><a href='/social/?PageIndex={p}' >{p}</a></li>"
                    for p in range(1, last + 1) if p != current)
    return (f'<nav><ul class="pagination"><div class="pagination">{links}'
            f"<li><a href='/social/?PageIndex={last}' >末页</a></li></div></ul></nav>")


def _list_html(cards, pager=""):
    return ('<div class="hidden job_r"><ul class="list">\n' + "\n".join(cards) +
            "\n</ul>" + pager + "</div>")


# 越界页：仍是 HTTP 200 + 完整骨架，只是一条卡片都没有 —— 唯一可靠的翻页终止信号。
EMPTY_PAGE_HTML = _list_html([])

DETAIL_HTML = """
<div class="margin hidden width1200 job_show">
<ul>
  <li class="t">品牌经理(J15629)  </li>
  <li class="n">面议</li>
  <li class="n">全职｜  浙江省-宁波市-慈溪市｜  2026-09-15
      <i><a href="javascript:void(0);" class="fx1"></a></i>
  </li>
  <li class="c"><dd>工作职责</dd><dl><p>1、品牌从 0 到 1 建设与规范化运营<br />2、品牌集成与业务变革推动</p></dl></li>
  <li class="c"><dd>任职要求</dd><dl><p>1、本科及以上，2027届毕业生；<br />2、5-10年工作经验。</p></dl></li>
  <li class="f"><button id="apply">立即申请</button></li>
</ul>
</div>
"""


class TestCardParseList(unittest.TestCase):
    def test_title_comes_from_dd_not_whole_anchor(self):
        """标题必须取 <dd>：<a> 里还塞着地点/部门/日期和整段 JD，整体当标题就是一坨垃圾。"""
        rows, _ = _card_parse_list(
            _list_html([_card(1, "市场专员(J13785)", "重庆市-万州区 ｜ 万州办事处 ｜ 2026-01-20")]),
            ORIGIN)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "市场专员(J13785)")
        self.assertEqual(rows[0]["jd_url"], f"{ORIGIN}/job_show?jobId=1")
        self.assertEqual(rows[0]["location"], "重庆市-万州区")
        self.assertEqual(rows[0]["posted_at"], "2026-01-20")

    def test_truncated_location_tail_is_stripped(self):
        """地点被按宽度截断的三种真实写法，都必须剥成稳定值 —— 否则快车道与富化天天互刷 location。"""
        cases = [
            ("浙江省-宁波市-... ｜ 方太集团 ｜ 2026-09-16", "浙江省-宁波市"),
            ("内蒙古自治区,... ｜ 方太集团 ｜ 2026-09-16", "内蒙古自治区"),
            ("广西壮族自治区... ｜ 方太集团 ｜ 2026-09-16", "广西壮族自治区"),
            ("浙江省-宁波市-慈溪市 ｜ 方太集团 ｜ 2026-09-16", "浙江省-宁波市-慈溪市"),
        ]
        for meta, want in cases:
            with self.subTest(meta=meta):
                rows, _ = _card_parse_list(_list_html([_card(7, "测试岗位A", meta)]), ORIGIN)
                self.assertEqual(rows[0]["location"], want)

    def test_nationwide_marker_kept(self):
        rows, _ = _card_parse_list(
            _list_html([_card(8, "测试岗位B", "全国 ｜ 方太集团 ｜ 2026-09-16")]), ORIGIN)
        self.assertEqual(rows[0]["location"], "全国")

    def test_location_truncated_mid_word_is_left_none(self):
        """`新疆维吾尔自治...` 少了末尾的「区」→ 认不出就留 None，**绝不按下标硬取**
        （下标法会把「方太集团」这种部门名写成地点，clean_location 不拦非地名）。
        留 None 之后由 _card_needs_repair 拉详情补，见下面的预算测试。"""
        rows, _ = _card_parse_list(
            _list_html([_card(9, "测试岗位C", "新疆维吾尔自治... ｜ 方太集团 ｜ 2026-09-04")]), ORIGIN)
        self.assertIsNone(rows[0]["location"])
        self.assertEqual(rows[0]["posted_at"], "2026-09-04")

    def test_department_is_not_mistaken_for_location(self):
        rows, _ = _card_parse_list(
            _list_html([_card(10, "测试岗位D", "方太集团 ｜ 文化弘扬部 ｜ 2026-09-15")]), ORIGIN)
        self.assertIsNone(rows[0]["location"])

    def test_commented_out_placeholder_rows_dropped(self):
        html = _list_html([_card(1, "真岗位", "北京市 ｜ 部门 ｜ 2026-09-01")])
        html += "<!--" + _card(2, "模板占位假岗", "北京市 ｜ 部门 ｜ 2026-09-01") + "-->"
        rows, _ = _card_parse_list(html, ORIGIN)
        self.assertEqual([r["title"] for r in rows], ["真岗位"])

    def test_dedupes_by_jd_url(self):
        rows, _ = _card_parse_list(
            _list_html([_card(1, "岗位A", "北京市 ｜ 部门 ｜ 2026-09-01"),
                        _card(1, "岗位A", "北京市 ｜ 部门 ｜ 2026-09-01")]), ORIGIN)
        self.assertEqual(len(rows), 1)

    def test_last_page_from_pager(self):
        rows, last = _card_parse_list(
            _list_html([_card(1, "测试岗位E", "北京市 ｜ 部门 ｜ 2026-09-01")], _pager(1, 20)), ORIGIN)
        self.assertEqual(last, 20)
        rows, last = _card_parse_list(
            _list_html([_card(1, "测试岗位E", "北京市 ｜ 部门 ｜ 2026-09-01")]), ORIGIN)
        self.assertIsNone(last, "没有分页条＝单页租户，交 paginate_all 用空页兜底")

    def test_rows_without_dd_are_not_claimed(self):
        """没有 <dd> = 不是卡片式模板，本解析器一行都不认（原样交回旧分支）。"""
        html = ('<ul class="list"><li><a href="/socialxq?jobId=390609112">'
                '<span>工程支持类</span><span>6S精益管理工程师</span></a></li></ul>')
        rows, _ = _card_parse_list(html, ORIGIN)
        self.assertEqual(rows, [])


class TestBoardJobType(unittest.TestCase):
    def test_board_path_declares_recruitment_type(self):
        """jd_url 是 /job_show?jobId=，**不带任何板块标记** → 不带这个声明，
        /campus /intern 的岗会被 recruitmentCategory 兜底成社招。"""
        self.assertEqual(_card_board_job_type("/campus"), "校园招聘")
        self.assertEqual(_card_board_job_type("/intern"), "实习")
        self.assertEqual(_card_board_job_type("/social"), "社会招聘")

    def test_intern_wins_over_campus(self):
        """`/campus/internship` 两边都命中，实习是更具体的那个（与 sourceDeclaredCategory 同序）。"""
        self.assertEqual(_card_board_job_type("/campus/internship"), "实习")

    def test_unknown_board_declares_nothing(self):
        self.assertIsNone(_card_board_job_type("/jobs"))

    def test_job_type_lands_on_rows(self):
        rows, _ = _card_parse_list(
            _list_html([_card(1, "测试岗位E", "北京市 ｜ 部门 ｜ 2026-09-01")]), ORIGIN, job_type="校园招聘")
        self.assertEqual(rows[0]["job_type"], "校园招聘")


class TestCardParseDetail(unittest.TestCase):
    def test_requirements_section_comes_first(self):
        """存库的 summary 只有 400 字（clean_summary 默认），grad_class 读的就是这 400 字 ——
        职责段动辄几百字，不换序要求段会被整段截掉。"""
        d = _card_parse_detail(DETAIL_HTML)
        self.assertLess(d["summary"].index("【任职要求】"), d["summary"].index("【工作职责】"))
        self.assertIn("2027届", d["summary"])

    def test_detail_fields(self):
        d = _card_parse_detail(DETAIL_HTML)
        self.assertEqual(d["title"], "品牌经理(J15629)")
        self.assertEqual(d["location"], "浙江省-宁波市-慈溪市")
        self.assertEqual(d["posted_at"], "2026-09-15")

    def test_empty_page_yields_nothing(self):
        self.assertEqual(_card_parse_detail("")["summary"], None)
        self.assertEqual(_card_parse_detail("<html><body>404</body></html>")["summary"], None)


class TestCmsParserDeclinesCards(unittest.TestCase):
    """回归：theme2 解析器遇到卡片式行必须弃权，否则会**悄悄**写一批垃圾标题。"""

    def test_short_jd_card_is_not_swallowed_by_cms_parser(self):
        html = _list_html([_card(1, "图像算法实习生(J15473)", "浙江省-杭州市 ｜ 方太 ｜ 2026-08-24",
                                 jd=SHORT_JD)])
        rows, _ = _cms_parse_list(html, ORIGIN)
        self.assertEqual(rows, [],
                         "JD 短的卡片会越过 3~120 字门，被 theme2 兜底当成『整个 <a> 文本是标题』")
        card_rows, _ = _card_parse_list(html, ORIGIN)
        self.assertEqual(card_rows[0]["title"], "图像算法实习生(J15473)")

    def test_real_theme2_row_still_parsed(self):
        """反向不变量：正统 theme2 的行（<span> 字段、无 <dd>）不受这条弃权影响。"""
        html = ('<div class="zwm"><ul><li>'
                '<a href="/socialxq?jobId=390609112&amp;jc=1&amp;c=&amp;p=1^-1&amp;ky=">'
                '<span>工程支持类</span><span>6S精益管理工程师(J11097)</span>'
                '<span>硕士</span><span>上海市-浦东新区</span><span><b>查看职位</b></span>'
                "</a></li></ul></div>")
        rows, _ = _cms_parse_list(html, ORIGIN)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "6S精益管理工程师(J11097)")


class _FakeResp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """按 PageIndex 返回预设页；详情页统一返 DETAIL_HTML。记录请求过的 URL。"""

    def __init__(self, pages, ignore_page_param=False, detail=DETAIL_HTML):
        self.pages = pages
        self.ignore = ignore_page_param
        self.detail = detail
        self.requested = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        self.requested.append(url)
        if "job_show" in url:
            return _FakeResp(self.detail)
        idx = 1
        if "PageIndex=" in url:
            idx = int(url.split("PageIndex=")[1].split("&")[0])
        if self.ignore:
            idx = 1
        return _FakeResp(self.pages.get(idx, EMPTY_PAGE_HTML))


def _patch(client):
    return mock.patch.object(china_ats.httpx, "Client", lambda **kw: client)


def _adapter():
    a = BeisenAdapter()
    a.company_name = "测试公司"
    return a


def _paged_tenant(total=28, per_page=10, last_page=3, jd=LONG_JD):
    pages, made = {}, 0
    for p in range(1, last_page + 1):
        cards = []
        while made < total and len(cards) < per_page:
            made += 1
            cards.append(_card(600000000 + made, f"岗位{made}", f"上海市 ｜ 部门 ｜ 2026-09-0{made % 9 + 1}", jd=jd))
        pages[p] = _list_html(cards, _pager(p, last_page))
    return pages


class TestCardsFetch(unittest.TestCase):
    def test_paginates_to_last_page(self):
        cli = _FakeClient(_paged_tenant(28, 10, 3))
        a = _adapter()
        with _patch(cli), mock.patch.dict(os.environ, {"CRAWL_DETAIL_CAP": "0"}):
            jobs = a.parse(a._httpx_fetch_cards(f"{ORIGIN}/social"))
        self.assertEqual(len(jobs), 28)
        self.assertEqual(a.reported_total, 28)
        self.assertTrue(a.fetch_complete)

    def test_page_size_inferred_not_hardcoded(self):
        cli = _FakeClient(_paged_tenant(36, 15, 3))
        a = _adapter()
        with _patch(cli), mock.patch.dict(os.environ, {"CRAWL_DETAIL_CAP": "0"}):
            jobs = a.parse(a._httpx_fetch_cards(f"{ORIGIN}/social"))
        self.assertEqual(len(jobs), 36)
        self.assertTrue(a.fetch_complete)

    def test_single_page_tenant_is_complete(self):
        cli = _FakeClient({1: _list_html([_card(1, "实习生", "杭州市 ｜ 部门 ｜ 2026-08-24")])})
        a = _adapter()
        with _patch(cli), mock.patch.dict(os.environ, {"CRAWL_DETAIL_CAP": "0"}):
            jobs = a.parse(a._httpx_fetch_cards(f"{ORIGIN}/intern"))
        self.assertEqual(len(jobs), 1)
        self.assertTrue(a.fetch_complete)
        self.assertEqual(a.reported_total, 1)

    def test_pagination_param_ignored_never_claims_complete(self):
        """翻页参数不认账（页页回同一批）→ 只看见了第一页，绝不许自称抓全
        （抓漏 + 自称抓全 = list-absence 误杀在招岗）。"""
        cli = _FakeClient(_paged_tenant(28, 10, 3), ignore_page_param=True)
        a = _adapter()
        with _patch(cli), mock.patch.dict(os.environ, {"CRAWL_DETAIL_CAP": "0"}):
            jobs = a.parse(a._httpx_fetch_cards(f"{ORIGIN}/social"))
        self.assertEqual(len(jobs), 10)
        self.assertFalse(a.fetch_complete)
        self.assertIsNone(a.reported_total)

    def test_short_of_declared_last_page_never_claims_complete(self):
        """分页条自报 5 页，第 3 页起就空了 → 没翻到自报页数，不许自称抓全。"""
        pages = _paged_tenant(20, 10, 2)
        pages[1] = _list_html([_card(600000001 + i, f"岗位{i}", "上海市 ｜ 部门 ｜ 2026-09-01")
                               for i in range(10)], _pager(1, 5))
        cli = _FakeClient(pages)
        a = _adapter()
        with _patch(cli), mock.patch.dict(os.environ, {"CRAWL_DETAIL_CAP": "0"}):
            a.parse(a._httpx_fetch_cards(f"{ORIGIN}/social"))
        self.assertFalse(a.fetch_complete)
        self.assertIsNone(a.reported_total)

    def test_new_spa_tenant_is_not_claimed(self):
        """抽得到 PortalId = 新版 SPA，本分支必须弃权（识别按响应特征，不按域名）。"""
        cli = _FakeClient({1: '<script>var cfg={"PortalId":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}</script>'
                              + _list_html([_card(1, "测试岗位F", "上海市 ｜ 部门 ｜ 2026-09-01")])})
        a = _adapter()
        with _patch(cli):
            self.assertIsNone(a._httpx_fetch_cards(f"{ORIGIN}/social"))

    def test_not_this_portal_returns_none(self):
        cli = _FakeClient({1: "<html><body>不是招聘列表</body></html>"})
        a = _adapter()
        with _patch(cli):
            self.assertIsNone(a._httpx_fetch_cards(f"{ORIGIN}/social"))

    def test_parse_carries_fields_through(self):
        cli = _FakeClient({1: _list_html([_card(1, "岗位A", "上海市-浦东新区 ｜ 部门 ｜ 2026-09-01")])})
        a = _adapter()
        with _patch(cli), mock.patch.dict(os.environ, {"CRAWL_DETAIL_CAP": "0"}):
            jobs = a.parse(a._httpx_fetch_cards(f"{ORIGIN}/campus"))
        self.assertEqual(jobs[0].title, "岗位A")
        self.assertEqual(jobs[0].location, "上海市-浦东新区")
        self.assertEqual(jobs[0].posted_at, "2026-09-01")
        self.assertEqual(jobs[0].job_type, "校园招聘")
        self.assertEqual(jobs[0].jd_url, f"{ORIGIN}/job_show?jobId=1")

    def test_old_ssr_producers_keep_posted_at_none(self):
        """反向不变量：老分支产出的 _ssr_jobs 不带 posted_at key → 行为逐字节不变。"""
        a = _adapter()
        jobs = a.parse('{"_ssr_jobs": [{"title": "旧分支岗位", "jd_url": "https://x/1"}]}')
        self.assertIsNone(jobs[0].posted_at)


class TestDetailRepairBudget(unittest.TestCase):
    """快车道 CRAWL_DETAIL_CAP=0 也必须补「列表值残缺」的行，否则 title/location 天天互刷
    （两者都**不在** jobs_db._PRESERVE_IF_EMPTY 里，非空值会直接覆盖）。"""

    def _run(self, cards, detail_cap):
        cli = _FakeClient({1: _list_html(cards)})
        a = _adapter()
        with _patch(cli), mock.patch.dict(os.environ, {"CRAWL_DETAIL_CAP": str(detail_cap)}):
            jobs = a.parse(a._httpx_fetch_cards(f"{ORIGIN}/social"))
        return jobs, [u for u in cli.requested if "job_show" in u]

    def test_truncated_title_repaired_even_when_enrichment_off(self):
        jobs, details = self._run(
            [_card(1, "中医研发工程师（系统开发）(J154...", "上海市 ｜ 部门 ｜ 2026-09-01"),
             _card(2, "完整标题(J0002)", "上海市 ｜ 部门 ｜ 2026-09-01")], 0)
        self.assertEqual(len(details), 1, "只补残缺那一行，完好的行不多打一次详情")
        by_url = {j.jd_url: j for j in jobs}
        self.assertEqual(by_url[f"{ORIGIN}/job_show?jobId=1"].title, "品牌经理(J15629)")
        self.assertEqual(by_url[f"{ORIGIN}/job_show?jobId=2"].title, "完整标题(J0002)")

    def test_missing_location_repaired_even_when_enrichment_off(self):
        jobs, details = self._run(
            [_card(1, "测试岗位G", "新疆维吾尔自治... ｜ 部门 ｜ 2026-09-04")], 0)
        self.assertEqual(len(details), 1)
        self.assertEqual(jobs[0].location, "浙江省-宁波市-慈溪市")   # 来自 DETAIL_HTML

    def test_list_location_not_overwritten_by_detail(self):
        """列表已经给全的地点不许被详情覆盖：多地岗的详情页会列全部地点，
        让它覆盖就又变成两条车道两个值。"""
        jobs, _ = self._run([_card(1, "测试岗位E", "北京市 ｜ 部门 ｜ 2026-09-01")], 800)
        self.assertEqual(jobs[0].location, "北京市")

    def test_no_repair_needed_means_no_detail_calls_in_fast_lane(self):
        jobs, details = self._run([_card(1, "完整标题(J1)", "上海市 ｜ 部门 ｜ 2026-09-01")], 0)
        self.assertEqual(details, [])
        self.assertIsNone(jobs[0].summary, "快车道不写 summary → 空值被 _PRESERVE_IF_EMPTY 保护")

    def test_enrichment_lane_fills_summary(self):
        jobs, details = self._run([_card(1, "完整标题(J1)", "上海市 ｜ 部门 ｜ 2026-09-01")], 800)
        self.assertEqual(len(details), 1)
        self.assertIn("【任职要求】", jobs[0].summary)


class TestCardsRouteHint(unittest.TestCase):
    def test_route_usable_accepts_cards(self):
        self.assertTrue(_beisen_route_usable({"cards": True}))

    def test_httpx_ready_for_registered_cards_tenant(self):
        host = "cards-ready.zhiye.com"
        china_ats._BEISEN_ROUTE_CACHE[host] = {"cards": True}
        try:
            self.assertTrue(beisen_httpx_ready(f"https://{host}/social"))
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)

    def test_cards_hint_tried_first(self):
        host = "cards-hint.zhiye.com"
        china_ats._BEISEN_ROUTE_CACHE[host] = {"cards": True}
        calls = []
        a = _adapter()
        a._httpx_fetch_cards = lambda url: (calls.append("cards"), '{"_ssr_jobs": []}')[1]
        a._httpx_fetch = lambda url: (calls.append("httpx"), None)[1]
        try:
            self.assertEqual(a.fetch(f"https://{host}/social"), '{"_ssr_jobs": []}')
            self.assertEqual(calls, ["cards"])
            self.assertEqual(china_ats._BEISEN_ROUTE_CACHE.get(host), {"cards": True})
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)

    def test_stale_cards_hint_is_evicted(self):
        """登记过时（租户换模板/升级 SPA）→ 必须把假登记清掉，否则「首见租户」分支会被跳过
        → 详情路由永远探不出来 → 0 岗 + 自称抓全。"""
        host = "stale-cards.zhiye.com"
        china_ats._BEISEN_ROUTE_CACHE[host] = {"cards": True}
        calls = []
        a = _adapter()
        a._httpx_fetch_cards = lambda url: (calls.append("cards"), None)[1]
        a._httpx_fetch = lambda url: (calls.append("httpx"), None)[1]
        a._httpx_fetch_cms = lambda url: (calls.append("cms"), None)[1]
        a._httpx_fetch_ssr_paged = lambda url: (calls.append("ssr"), None)[1]
        # 与 test_beisen_ssr_cms 的同款用例保持一致：浏览器列表抓取抛错 → fetch 走 _fetch_ssr 返回，
        # 这样「缓存里还剩什么」才只反映驱逐本身，不被后面的路由探测回写干扰。
        a._fetch_paginated = lambda url: (calls.append("browser"),
                                          (_ for _ in ()).throw(RuntimeError("no browser")))[1]
        a._fetch_ssr = lambda url: (calls.append("ssr_browser"), "{}")[1]
        try:
            a.fetch(f"https://{host}/social")
            self.assertNotIn(host, china_ats._BEISEN_ROUTE_CACHE)
            self.assertEqual(calls[0], "cards")
            self.assertIn("httpx", calls, "驱逐后必须继续往下试，不能停在 cards 分支")
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)

    def test_cards_runs_after_all_legacy_branches(self):
        """选路纪律：旧分支任何一条能出岗就轮不到 cards —— 既有源的命运一步不变。"""
        host = "legacy-first.zhiye.com"
        calls = []
        a = _adapter()
        a._httpx_fetch = lambda url: (calls.append("httpx"), None)[1]
        a._httpx_fetch_cms = lambda url: (calls.append("cms"), None)[1]
        a._httpx_fetch_ssr_paged = lambda url: (calls.append("ssr"), '{"_ssr_jobs": []}')[1]
        a._httpx_fetch_cards = lambda url: (calls.append("cards"), '{"_ssr_jobs": []}')[1]
        a._discover_detail_route = lambda *x, **k: None
        try:
            a.fetch(f"https://{host}/social")
            self.assertNotIn("cards", calls)
            self.assertEqual(calls, ["httpx", "cms", "ssr"])
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)

    def test_cards_is_last_resort_before_browser(self):
        host = "cards-last.zhiye.com"
        calls = []
        a = _adapter()
        a._httpx_fetch = lambda url: (calls.append("httpx"), None)[1]
        a._httpx_fetch_cms = lambda url: (calls.append("cms"), None)[1]
        a._httpx_fetch_ssr_paged = lambda url: (calls.append("ssr"), None)[1]
        a._httpx_fetch_cards = lambda url: (calls.append("cards"), '{"_ssr_jobs": []}')[1]
        a._fetch_paginated = lambda url: (calls.append("browser"), "{}")[1]
        a._discover_detail_route = lambda *x, **k: None
        try:
            a.fetch(f"https://{host}/social")
            self.assertEqual(calls, ["httpx", "cms", "ssr", "cards"])
            self.assertNotIn("browser", calls, "cards 打通后不该再开浏览器")
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)


class TestFotileRegistered(unittest.TestCase):
    def test_fotile_registered_as_cards_tenant(self):
        """方太登记在 beisen_routes.json 里 = run.py 的 _partition_by_tier 会把它排进
        httpx 并发快车道，而不是白占串行浏览器档的名额。"""
        self.assertEqual(china_ats._BEISEN_ROUTE_CACHE.get("fotile.zhiye.com"), {"cards": True})
        self.assertTrue(beisen_httpx_ready("https://fotile.zhiye.com/campus"))


if __name__ == "__main__":
    unittest.main()
