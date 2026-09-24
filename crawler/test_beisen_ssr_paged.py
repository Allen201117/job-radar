"""北森「老版 SSR jobsTable 门户」（路径式详情 /zpdetail/{id}、/job_show/{id}）单测 —— 内联 HTML，不打真网络。

对应 adapters/china_ats.py 的 _ssr_* 纯函数与 BeisenAdapter._httpx_fetch_ssr_paged。
HTML 片段按 2026-09-04 live 抓下来的真实结构裁剪（富瀚微 fullhan / 科伦 kelun），
保留会咬人的细节：**逐租户不同的列序**、**逐租户不同的每页行数**、MvcPager 分页条、注释里的模板占位假岗。

红线（BeisenAdapter 开着 list-absence 撤岗，抓漏 + 自称抓全 = 误杀在招岗，CLAUDE.md §4）：
fetch_complete 只在正面证明抓全时为 True。三道否决各有用例钉死。
"""
import json
import unittest
from unittest import mock

from adapters import china_ats
from adapters.china_ats import BeisenAdapter, _ssr_parse_list, _beisen_route_usable, beisen_httpx_ready

ORIGIN = "https://tenant.zhiye.com"


def _row(job_id, title, jtype, city, date="2026-09-04", page=1):
    """富瀚微列序：职位名称 / 职位类型 / 工作地点 / 发布时间。"""
    # 真实锚点会把**列表当前页号**回传进详情链接（联易融实测），故构造器刻意带上它。
    return (f'<tr><td><a title="{title}" href="/zpdetail/{job_id}?PageIndex={page}" >{title}</a></td>'
            f'<td title="{jtype}">{jtype}</td><td title="{city}">{city}</td><td>{date}</td></tr>')


def _pager(total, cur, last):
    return (f'<div class="pager"><div class="counts">共{total}条记录</div>'
            f'<div class="tablefooter"> 当前第{cur}/{last}页 '
            f'<span class="pitem"><a href=\'/social/?PageIndex={min(cur + 1, last)}\'>下一页</a></span>'
            f'<span class="pitem"><a href=\'/social/?PageIndex={last}\'>尾页</a></span></div></div>')


def _list_html(rows, pager=""):
    return ('<div class="joblist"><table class="jobsTable">'
            '<tr class="title"><td>职位名称</td><td title="职位类型">职位类型</td>'
            '<td>工作地点</td><td>发布时间</td></tr>'
            + "".join(rows) + "</table></div>" + pager)


# 科伦列序不同：职位名称 / 职能 / 公司 / 招聘人数 / 工作地点。
# 「公司」列排在「工作地点」前面 —— 按下标硬取会把「集团总部」写进 location。
KELUN_HTML = (
    '<div class="joblist"><table class="jobsTable">'
    '<tr class="title"><td>职位名称</td><td title="职能">职能</td><td title="公司">公司</td>'
    '<td>招聘人数</td><td>工作地点</td></tr>'
    '<tr><td><a title="科伦总部-采购专员(J12806)" href="/job_show/230861003" >科伦总部-采购专员(J12806)</a></td>'
    '<td title="通用职能类">通用职能类</td><td title="集团总部">集团总部</td>'
    '<td>2</td><td title="四川省-成都市">四川省-成都市</td></tr>'
    "</table></div>" + _pager(28, 1, 3))


class TestSsrParseList(unittest.TestCase):
    def test_parses_rows_with_absolute_jd_url(self):
        rows, total, last = _ssr_parse_list(
            _list_html([_row(621138346, "高级视频防抖算法工程师", "研发/算法", "上海市")], _pager(36, 1, 3)), ORIGIN)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["jd_url"], f"{ORIGIN}/zpdetail/621138346")
        self.assertEqual(rows[0]["title"], "高级视频防抖算法工程师")
        self.assertEqual(rows[0]["location"], "上海市")
        self.assertEqual(rows[0]["job_type"], "研发/算法")
        self.assertEqual((total, last), (36, 3))

    def test_column_order_differs_per_tenant(self):
        """回归：科伦把「公司」列排在「工作地点」前 —— 必须按表头映射，不能按下标硬取。"""
        rows, total, last = _ssr_parse_list(KELUN_HTML, ORIGIN)
        self.assertEqual(rows[0]["location"], "四川省-成都市")   # 不是「集团总部」
        self.assertEqual(rows[0]["job_type"], "通用职能类")
        self.assertEqual(rows[0]["jd_url"], f"{ORIGIN}/job_show/230861003")
        self.assertEqual((total, last), (28, 3))

    def test_no_pager_means_single_page(self):
        rows, total, last = _ssr_parse_list(_list_html([_row(1111111, "测试工程师", "研发", "西安市")]), ORIGIN)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(total)
        self.assertIsNone(last)

    def test_commented_out_placeholder_rows_dropped(self):
        html = _list_html([_row(2222222, "真岗", "研发", "北京市"),
                           "<!--" + _row(3333333, "模板占位假岗", "研发", "北京市") + "-->"])
        rows, _, _ = _ssr_parse_list(html, ORIGIN)
        self.assertEqual([r["title"] for r in rows], ["真岗"])

    def test_title_attribute_wins_over_inner_text(self):
        """列表内文本可能被样式标签切碎；title 属性是全名。"""
        html = _list_html(['<tr><td><a title="设计工艺协同研发工程师（2027届校招）" href="/zpdetail/4444444">'
                           '<span>设计工艺协同研发</span>…</a></td>'
                           '<td title="研发">研发</td><td title="上海市">上海市</td><td>2026-09-04</td></tr>'])
        rows, _, _ = _ssr_parse_list(html, ORIGIN)
        self.assertEqual(rows[0]["title"], "设计工艺协同研发工程师（2027届校招）")

    def test_dedupes_by_jd_url(self):
        r = _row(5555555, "同一个岗", "研发", "深圳市")
        rows, _, _ = _ssr_parse_list(_list_html([r, r]), ORIGIN)
        self.assertEqual(len(rows), 1)

    def test_non_jobstable_page_yields_nothing(self):
        """华安基金那类 JS 渲染列表：raw HTML 里没有表格 → 交回浏览器路径，别硬猜。"""
        rows, _, _ = _ssr_parse_list("<html><body><div>搜索 职位类别 全部</div></body></html>", ORIGIN)
        self.assertEqual(rows, [])


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeClient:
    """按 PageIndex 返回预设页；记录请求过的页号。"""
    def __init__(self, pages, ignore_page_param=False):
        self.pages = pages
        self.ignore = ignore_page_param
        self.requested = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        idx = 1
        if "PageIndex=" in url:
            idx = int(url.split("PageIndex=")[1].split("&")[0])
        self.requested.append(idx)
        if self.ignore:
            idx = 1
        return _FakeResp(self.pages.get(idx, _list_html([])))


def _patch(client):
    return mock.patch.object(china_ats.httpx, "Client", lambda **kw: client)


def _adapter():
    a = BeisenAdapter()
    a.company_name = "测试公司"
    return a


def _paged_tenant(total=36, per_page=15, last_page=3):
    """构造一个 total 条、每页 per_page 条的租户。"""
    pages, made = {}, 0
    for p in range(1, last_page + 1):
        rows = []
        while made < total and len(rows) < per_page:
            made += 1
            rows.append(_row(600000000 + made, f"岗位{made}", "研发", "上海市"))
        pages[p] = _list_html(rows, _pager(total, p, last_page))
    return pages


class TestSsrPagedFetch(unittest.TestCase):
    def test_paginates_to_reported_total(self):
        cli = _FakeClient(_paged_tenant(36, 15, 3))
        a = _adapter()
        with _patch(cli), mock.patch.object(china_ats, "_beisen_ssr_fill_summaries", lambda jobs: None):
            jobs = a.parse(a._httpx_fetch_ssr_paged(f"{ORIGIN}/social"))
        self.assertEqual(len(jobs), 36)
        self.assertEqual(a.reported_total, 36)
        self.assertTrue(a.fetch_complete)
        self.assertEqual(cli.requested, [1, 2, 3])       # 首页只请求一次（复用缓存）

    def test_page_size_inferred_per_tenant(self):
        """科伦每页 10 条、富瀚微 15 条 —— 页长写死会让其中一家判错末页。"""
        cli = _FakeClient(_paged_tenant(28, 10, 3))
        a = _adapter()
        with _patch(cli), mock.patch.object(china_ats, "_beisen_ssr_fill_summaries", lambda jobs: None):
            jobs = a.parse(a._httpx_fetch_ssr_paged(f"{ORIGIN}/campus"))
        self.assertEqual(len(jobs), 28)
        self.assertTrue(a.fetch_complete)

    def test_single_page_tenant_is_complete_and_measurable(self):
        """无分页条 = 只有一页。分母诚实记「看见的全部」，不是 None（否则又回到不可判定）。"""
        cli = _FakeClient({1: _list_html([_row(700000 + i, f"岗{i}", "研发", "北京市") for i in range(14)])})
        a = _adapter()
        with _patch(cli), mock.patch.object(china_ats, "_beisen_ssr_fill_summaries", lambda jobs: None):
            jobs = a.parse(a._httpx_fetch_ssr_paged(f"{ORIGIN}/social"))
        self.assertEqual(len(jobs), 14)
        self.assertEqual(a.reported_total, 14)
        self.assertTrue(a.fetch_complete)

    def test_pagination_param_ignored_never_claims_complete(self):
        """红线①：租户不认 PageIndex（页页回同一批岗）→ 只看见首页，绝不许自称抓全。"""
        cli = _FakeClient(_paged_tenant(36, 15, 3), ignore_page_param=True)
        a = _adapter()
        with _patch(cli), mock.patch.object(china_ats, "_beisen_ssr_fill_summaries", lambda jobs: None):
            jobs = a.parse(a._httpx_fetch_ssr_paged(f"{ORIGIN}/social"))
        self.assertEqual(len(jobs), 15)
        self.assertFalse(a.fetch_complete)
        self.assertEqual(a.reported_total, 36)     # 分母仍诚实报站点自报值 → 缺口可见

    def test_short_of_reported_total_never_claims_complete(self):
        """红线②③：分页条自报 3 页/36 条，第 2 页起空 → 抓漏，绝不许自称抓全。"""
        pages = _paged_tenant(36, 15, 3)
        pages[2] = _list_html([], _pager(36, 2, 3))
        cli = _FakeClient(pages)
        a = _adapter()
        with _patch(cli), mock.patch.object(china_ats, "_beisen_ssr_fill_summaries", lambda jobs: None):
            jobs = a.parse(a._httpx_fetch_ssr_paged(f"{ORIGIN}/social"))
        self.assertEqual(len(jobs), 15)
        self.assertFalse(a.fetch_complete)

    def test_not_this_portal_returns_none(self):
        cli = _FakeClient({1: "<html><body>搜索 职位类别</body></html>"})
        a = _adapter()
        with _patch(cli):
            self.assertIsNone(a._httpx_fetch_ssr_paged(f"{ORIGIN}/social"))

    def test_parse_carries_fields_through(self):
        cli = _FakeClient({1: KELUN_HTML.replace(_pager(28, 1, 3), "")})
        a = _adapter()
        with _patch(cli), mock.patch.object(china_ats, "_beisen_ssr_fill_summaries", lambda jobs: None):
            jobs = a.parse(a._httpx_fetch_ssr_paged(f"{ORIGIN}/campus"))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].location, "四川省-成都市")
        self.assertEqual(jobs[0].job_type, "通用职能类")
        self.assertEqual(jobs[0].jd_url, f"{ORIGIN}/job_show/230861003")



class TestListtableHeaderAndTenantPolicy(unittest.TestCase):
    """百胜中国（yumchina，2026-09-23）：class=listtable、表头 <th>、地点整串在 td 的 title 里。"""

    PAGE = ('<table class="listtable"><thead><tr class="tabletitle">'
            '<th class="tableleft">&nbsp;&nbsp;职位名称</th><th title="品牌">品牌</th>'
            '<th>工作地点</th><th>发布时间</th></tr></thead>'
            '<tr><td><a title="必胜客餐厅储备经理-诸暨" jobAdId="310095098" href="/zpdetail/310095098">必胜客餐厅储备经理-诸暨</a></td>'
            '<td title="必胜客">必胜客</td><td title="浙江省-绍兴市-诸暨市">浙江省-绍兴市-...</td><td> 2022-11-18 </td></tr>'
            '<tr><td><a title="肯德基餐厅储备经理-天津" href="/zpdetail/310300001">肯德基餐厅储备经理-天津</a></td>'
            '<td title="肯德基">肯德基</td><td title="天津市">天津市</td><td>2026-9-16</td></tr>'
            '</table><div class="counts">共2条记录</div>')

    def test_th_header_maps_location_and_posted_at(self):
        rows, total, _last = _ssr_parse_list(self.PAGE, "https://yumchina.zhiye.com")
        self.assertEqual(total, 2)
        # 地点取 td 的 title（整串），不取被截断的「浙江省-绍兴市-...」；品牌列不许被当成地点。
        self.assertEqual([r["location"] for r in rows], ["浙江省-绍兴市-诸暨市", "天津市"])
        self.assertEqual([r["posted_at"] for r in rows], ["2022-11-18", "2026-09-16"])

    def test_policy_drops_missing_location_old_and_undated_rows(self):
        from datetime import date
        policy = {"require_location": True, "max_age_days": 365}
        today = date(2026, 9, 23)
        allow = china_ats._ssr_policy_allows
        self.assertTrue(allow({"location": "天津市", "posted_at": "2026-09-16"}, policy, today))
        self.assertFalse(allow({"location": "", "posted_at": "2026-09-16"}, policy, today))
        self.assertFalse(allow({"location": "浙江省", "posted_at": "2022-11-18"}, policy, today))
        self.assertFalse(allow({"location": "浙江省", "posted_at": None}, policy, today))   # 证明不了是近期
        self.assertTrue(allow({"location": "浙江省", "posted_at": "2025-09-24"}, policy, today))
        self.assertTrue(allow({"location": None, "posted_at": None}, None, today))          # 无口径 = 老行为

    def test_policy_only_applies_to_named_tenant(self):
        jobs = [{"title": "储备经理", "jd_url": "https://yumchina.zhiye.com/zpdetail/1", "location": None,
                 "posted_at": "2020-01-01"},
                {"title": "储备经理", "jd_url": "https://other.zhiye.com/zpdetail/2", "location": None,
                 "posted_at": "2020-01-01"}]
        out = BeisenAdapter().parse(json.dumps({"_ssr_jobs": jobs}, ensure_ascii=False))
        self.assertEqual([j.jd_url for j in out], ["https://other.zhiye.com/zpdetail/2"])


class TestSsrJobUrlNormalize(unittest.TestCase):
    """回归：详情锚点带列表页号 `?PageIndex=N`（联易融 live 实测）。

    不剥掉的话有两个后果，都很贵：
      ① 同一岗从第 1 页和第 3 页抓到 → 两个 canonical_jd_url → 库里同岗多行；
      ② 与库里已有的干净 URL 对不上 → 老行在 list-absence 里变「缺席」→ 撤岗 + 次日 purge 永久删。
    canonicalize_jd_url 只去 utm_ 类参数，挡不住 PageIndex。
    """

    def test_strips_page_index(self):
        self.assertEqual(
            china_ats._ssr_normalize_job_url(ORIGIN, "/zpdetail/390725089?PageIndex=1"),
            f"{ORIGIN}/zpdetail/390725089")

    def test_same_job_from_different_pages_is_one_url(self):
        n = china_ats._ssr_normalize_job_url
        self.assertEqual(n(ORIGIN, "/zpdetail/1?PageIndex=1"), n(ORIGIN, "/zpdetail/1?PageIndex=7"))

    def test_absolute_href_kept(self):
        self.assertEqual(
            china_ats._ssr_normalize_job_url(ORIGIN, "https://x.zhiye.com/job_show/230861003?PageIndex=9"),
            "https://x.zhiye.com/job_show/230861003")

    def test_parse_list_emits_clean_urls(self):
        rows, _, _ = _ssr_parse_list(
            _list_html([_row(390725089, "方案经理", "研发", "深圳市", page=3)]), ORIGIN)
        self.assertEqual(rows[0]["jd_url"], f"{ORIGIN}/zpdetail/390725089")

    def test_same_job_across_pages_dedupes_to_one(self):
        """翻页时同一岗带不同页号出现 → 归一后必须只算一条，否则库里同岗多行。"""
        html = _list_html([_row(111111, "岗A", "研发", "北京市", page=1),
                           _row(111111, "岗A", "研发", "北京市", page=2)])
        rows, _, _ = _ssr_parse_list(html, ORIGIN)
        self.assertEqual(len(rows), 1)


class TestSsrAbsenceLivenessStaysOff(unittest.TestCase):
    """红线：本路径抓全也**不许**开 list-absence 撤岗。

    「板块列表是全集」为真，但库里压着旧浏览器路径（全页 a[href]，含详情页侧栏「热招职位」）
    留下的**跨板块脏行**：联易融 /social 的 2 条缺席里，390854070 是在招的校园招聘岗，
    一旦按缺席撤岗就会 expired → 次日 purge 永久删（CLAUDE.md §4 的误杀在招岗）。
    """

    def test_ssr_path_turns_absence_off_even_when_complete(self):
        cli = _FakeClient(_paged_tenant(36, 15, 3))
        a = _adapter()
        self.assertTrue(BeisenAdapter.supports_absence_liveness, "类默认仍应为 True")
        with _patch(cli), mock.patch.object(china_ats, "_beisen_ssr_fill_summaries", lambda jobs: None):
            a._httpx_fetch_ssr_paged(f"{ORIGIN}/social")
        self.assertTrue(a.fetch_complete, "抓全了就要如实记，抓全率不能因为怕撤岗而说谎")
        self.assertFalse(a.supports_absence_liveness, "但绝不许按缺席撤岗")

    def test_other_beisen_paths_keep_absence_on(self):
        """只降本实例，不动类默认 —— 新版 SPA / theme2 CMS 两条路径行为一字不改。"""
        self.assertTrue(BeisenAdapter().supports_absence_liveness)


class TestSsrRouteHint(unittest.TestCase):
    """2026-09-23 立：这是本次要修的主 bug —— fetch() 首次探测到「老版 SSR jobsTable 租户」时
    从来没登记 {"ssr": true}，harvest_beisen_routes.py 因此把它天天当成「还没探出路由」重探。
    2026-09-23 实测：harvest_beisen_routes.py 待探队列 26 家里 23 家（88%）就是这一类
    ——它们早就能纯 httpx 抓全，压根不需要浏览器点击捕获。"""

    def test_route_usable_accepts_ssr(self):
        self.assertTrue(_beisen_route_usable({"ssr": True}))

    def test_httpx_ready_for_registered_ssr_tenant(self):
        host = "ssr-ready.zhiye.com"
        china_ats._BEISEN_ROUTE_CACHE[host] = {"ssr": True}
        try:
            self.assertTrue(beisen_httpx_ready(f"https://{host}/social"))
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)

    def test_first_seen_tenant_resolved_via_ssr_gets_registered(self):
        host = "ssr-first-seen.zhiye.com"
        calls = []
        a = BeisenAdapter()
        a._httpx_fetch = lambda url: (calls.append("httpx"), None)[1]
        a._httpx_fetch_cms = lambda url: (calls.append("cms"), None)[1]
        a._httpx_fetch_ssr_paged = lambda url: (calls.append("ssr"), '{"_ssr_jobs": [{"jd_url": "x"}]}')[1]
        try:
            out = a.fetch(f"https://{host}/social")
            self.assertEqual(out, '{"_ssr_jobs": [{"jd_url": "x"}]}')
            self.assertEqual(calls, ["httpx", "cms", "ssr"])
            self.assertEqual(china_ats._BEISEN_ROUTE_CACHE.get(host), {"ssr": True},
                              "首次探到 ssr 成功必须登记，否则 harvest 脚本永远读不到这个事实")
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)

    def test_ssr_hint_tried_first(self):
        """反向不变量：登记正确（ssr 抓到了东西）时不能误删或重复探测，否则每次都要
        重跑新版 SPA/CMS 探测，白掉这条本该零成本的快车道。"""
        host = "ssr-hint.zhiye.com"
        china_ats._BEISEN_ROUTE_CACHE[host] = {"ssr": True}
        calls = []
        a = BeisenAdapter()
        a._httpx_fetch_ssr_paged = lambda url: (calls.append("ssr"), '{"_ssr_jobs": []}')[1]
        a._httpx_fetch = lambda url: (calls.append("httpx"), None)[1]
        try:
            self.assertEqual(a.fetch(f"https://{host}/social"), '{"_ssr_jobs": []}')
            self.assertEqual(calls, ["ssr"])
            self.assertEqual(china_ats._BEISEN_ROUTE_CACHE.get(host), {"ssr": True})
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)

    def test_stale_ssr_hint_is_evicted(self):
        """登记过时（租户升级到新版 SPA/CMS）→ 必须把假登记清掉，否则「首见租户」分支
        会因为 host 还在缓存里被跳过 → 0 岗 + 自称抓全（同 cms/cards 的 stale-hint 用例）。"""
        host = "stale-ssr.zhiye.com"
        china_ats._BEISEN_ROUTE_CACHE[host] = {"ssr": True}
        calls = []
        a = BeisenAdapter()
        a._httpx_fetch_ssr_paged = lambda url: (calls.append("ssr"), None)[1]
        a._httpx_fetch = lambda url: (calls.append("httpx"), None)[1]
        a._httpx_fetch_cms = lambda url: (calls.append("cms"), None)[1]
        a._httpx_fetch_cards = lambda url: (calls.append("cards"), None)[1]
        a._fetch_paginated = lambda url: (
            calls.append("browser"), (_ for _ in ()).throw(RuntimeError("no browser")))[1]
        a._fetch_ssr = lambda url: (calls.append("ssr_browser"), "{}")[1]
        try:
            a.fetch(f"https://{host}/social")
            self.assertNotIn(host, china_ats._BEISEN_ROUTE_CACHE,
                             "过时的 ssr 登记必须被清出缓存，否则该租户永远探不出详情路由")
            self.assertEqual(calls[0], "ssr")
            self.assertIn("httpx", calls, "驱逐后必须继续往下试，不能停在 ssr 分支")
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)

    def test_ssr_runs_after_spa_and_cms_but_before_cards(self):
        """选路纪律：新版 SPA / cms 任一条能出岗就轮不到 ssr；ssr 打通了 cards 也不用再试
        （既有源的命运一步不变，同 test_cards_runs_after_all_legacy_branches）。"""
        host = "ssr-order.zhiye.com"
        calls = []
        a = BeisenAdapter()
        a._httpx_fetch = lambda url: (calls.append("httpx"), None)[1]
        a._httpx_fetch_cms = lambda url: (calls.append("cms"), None)[1]
        a._httpx_fetch_ssr_paged = lambda url: (calls.append("ssr"), '{"_ssr_jobs": []}')[1]
        a._httpx_fetch_cards = lambda url: (calls.append("cards"), '{"_ssr_jobs": []}')[1]
        try:
            a.fetch(f"https://{host}/social")
            self.assertEqual(calls, ["httpx", "cms", "ssr"])
            self.assertNotIn("cards", calls)
        finally:
            china_ats._BEISEN_ROUTE_CACHE.pop(host, None)



class TestSsrDetailBodyFooter(unittest.TestCase):
    """老版详情页的正文要截在页脚之前（2026-09-24：22 个租户 522 条 summary 带着备案号与别的岗位名）。"""
    _DUTY = "负责餐厅现场人员管理，订货排班，成本控制，设备维护等营运系统管理工作；"

    def _page(self, tail):
        return ("<html><div class='nav'>品牌 肯德基 必胜客 搜索 招聘动态 更多>> 暂无内容</div>"
                "<h2>海口肯德基餐厅楼面经理</h2><div>工作性质： 全职 工作地点： 海南省-海口市</div>"
                f"<div>岗位职责：{self._DUTY * 3}</div>{tail}</html>")

    def test_cuts_before_apply_buttons_and_other_job_titles(self):
        body = china_ats.beisen_ssr_detail_body(self._page(
            "<a>现在申请</a> <a>返回职位列表</a> 收藏 <h3>热招职位</h3> 更多 >> 西安研究院院长/技术带头人 "
            "<h3>长招职位</h3> 更多 >> 招商地区经理（海口）(J14149) ©2026 百胜中国 京ICP备05051632号-16 隐私政策 Powered by"))
        self.assertEqual(body, (self._DUTY * 3).strip())

    def test_cuts_when_page_has_no_apply_button(self):
        # 启德 / 科兴这类页：正文后直接是「长招职位 更多 >>」列表，没有「现在申请」。
        body = china_ats.beisen_ssr_detail_body(self._page(
            "长招职位 更多 >> 学习顾问2018(J12037) ©2026 启德教育集团 京ICP备05051632号-16"))
        self.assertNotIn("学习顾问", body)
        self.assertNotIn("ICP", body)
        self.assertTrue(body.startswith("负责餐厅现场人员管理"))

    def test_stopped_job_page_yields_no_body(self):
        # 天康：已停用的岗位页只剩「对不起，此职位已停用。」——没有正文标签，不许补出任何东西。
        page = ("<html>搜索 招聘动态 更多>> 暂无内容 2026届校招-财务储备岗(J10576) 对不起，此职位已停用。 返回 "
                "©2026 天康生物股份有限公司 京ICP备05051632号-16</html>")
        self.assertEqual(china_ats.beisen_ssr_detail_body(page), "")

    def test_too_short_after_cut_is_empty(self):
        self.assertEqual(china_ats.beisen_ssr_detail_body(
            "<div>岗位职责：负责门店营运</div> 现在申请 返回职位列表 收藏 ©2026 x 京ICP备05051632号-16 " + "填充" * 40), "")


class TestSsrStubRedirect(unittest.TestCase):
    """华夏基金 / 京博：/zpdetail/{id} 只是跳转壳，按 #v 的招聘类别跳到自有详情模板（2026-09-24 实测页面原样）。"""
    URL = "https://jingbo.zhiye.com/zpdetail/311188751"

    def _stub(self, cate, jid="311188751", tag="hidden"):
        return (f'<body><input type="{tag}" value="{cate}" id="v" /><script type="text/javascript">'
                '$(function () { var cate = $("#v").val();'
                f'  if(cate =="校园招聘"){{ window.location.href="/xiangqing2?jobId="+{jid}; }}'
                f'  else if(cate =="社会招聘"){{ window.location.href="/xiangqing?jobId="+{jid}; }}'
                f'  else{{ window.location.href="/xiangqing3?jobId="+{jid}; }} }});</script></body>')

    def test_follows_branch_matching_category(self):
        self.assertEqual(china_ats.beisen_ssr_stub_target(self._stub("社会招聘"), self.URL),
                         "https://jingbo.zhiye.com/xiangqing?jobId=311188751")
        self.assertEqual(china_ats.beisen_ssr_stub_target(self._stub("校园招聘", tag="text"), self.URL),
                         "https://jingbo.zhiye.com/xiangqing2?jobId=311188751")

    def test_unknown_category_takes_else_branch(self):
        self.assertEqual(china_ats.beisen_ssr_stub_target(self._stub("实习生招聘"), self.URL),
                         "https://jingbo.zhiye.com/xiangqing3?jobId=311188751")

    def test_redirect_to_another_job_id_is_refused(self):
        # 正文宁可取不到，也不能挂到别的岗上
        self.assertIsNone(china_ats.beisen_ssr_stub_target(self._stub("社会招聘", jid="311188000"), self.URL))

    def test_normal_detail_page_is_not_a_stub(self):
        page = "<div>海口肯德基餐厅楼面经理</div><div>工作职责：负责餐厅值班管理</div>"
        self.assertIsNone(china_ats.beisen_ssr_stub_target(page, self.URL))

    def test_fetch_follows_stub_and_cuts_own_footer(self):
        duty = ("1、期现方案制定与执行：结合公司现货头寸及产能，制定并高效执行期现经营与套期保值策略，提升经营稳定性；"
                "2、风险模型构建与管控：建立完善的期现交易风险评估与控制机制。")
        pages = {
            self.URL: (200, self._stub("社会招聘")),
            "https://jingbo.zhiye.com/xiangqing?jobId=311188751":
                (200, f"<h2>苯乙烯期现经理(J19178)</h2><div>岗位职责：</div><p>{duty}</p>"
                      "<a>立即申请</a><a>返回</a><div>版权所有：山东京博控股集团</div>"),
        }
        seen = []
        body = china_ats.beisen_ssr_fetch_detail_body(lambda u: seen.append(u) or pages[u], self.URL)
        self.assertEqual(body, duty)
        self.assertEqual(len(seen), 2)

    def test_fetch_does_not_hop_when_page_already_has_body(self):
        page = "<div>工作职责：" + "负责区域银行渠道营销与客户维护，确保销售目标实现，" * 3 + "</div> 返回列表 分享： 版权所有：华夏基金"
        seen = []
        body = china_ats.beisen_ssr_fetch_detail_body(lambda u: seen.append(u) or (200, page), self.URL)
        self.assertTrue(body.endswith("确保销售目标实现，"))
        self.assertNotIn("版权所有", body)
        self.assertEqual(len(seen), 1)

if __name__ == "__main__":
    unittest.main()
