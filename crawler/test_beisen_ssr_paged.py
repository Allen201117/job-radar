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
from adapters.china_ats import BeisenAdapter, _ssr_parse_list

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


if __name__ == "__main__":
    unittest.main()
