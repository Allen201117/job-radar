"""北森「老版 SSR CMS Portal 门户」（theme2）解析单测 —— 内联 HTML 片段，不打真实网络。

对应 adapters/china_ats.py 的 _cms_* 纯函数与 BeisenAdapter._httpx_fetch_cms。
HTML 片段按 2026-08-27 live 抓下来的中芯国际（smics.zhiye.com）真实结构裁剪，
保留全部会咬人的细节：筛选态回传参数、注释里的模板占位假岗、25 字截断标题、中英双版详情页。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import adapters.china_ats as china_ats  # noqa: E402
from adapters.china_ats import (  # noqa: E402
    BeisenAdapter,
    _BEISEN_SSR_DETAIL_PATHS,
    _cms_education,
    _cms_normalize_job_url,
    _cms_parse_detail,
    _cms_parse_list,
)

ORIGIN = "https://tenant.zhiye.com"

# 列表页：表头 + 三个板块各一行 + 一条藏在 HTML 注释里的模板占位假岗 + 分页条。
LIST_HTML = """
<div class="zwt"><table><tr class="one">
  <th align="center" width="15%">职位分类</th>
  <th align="center" width="37%">职位名称</th>
  <th align="center" width="13%">职位学历</th>
  <th align="center" width="20%">工作地点</th>
  <th align="center" width="15%">操作</th>
</tr></table></div>
<div class="zwm"><ul>
  <li><a href="/socialxq?jobId=390609112&amp;jc=1&amp;c=&amp;p=1^-1,3^-1&amp;ky=" class="flex-between align-center">
    <span style="width: 15%;">工程支持类</span>
    <span style="width: 37%;">6S精益管理工程师(J11097)</span>
    <span style="width: 13%;">硕士</span>
    <span style="width: 20%;">上海市-浦东新区</span>
    <span style="width: 15%;"><b>查看职位</b></span>
  </a></li>
  <li><a href="/campusxq?jobId=390852209&jc=2&c=&p=1^-1,3^-1&ky=" class="flex-between align-center">
    <span style="width: 15%;">技术研发类</span>
    <span style="width: 37%;">设计工艺协同研发工程师-张江（2027届校招）(J133...</span>
    <span style="width: 13%;">硕士、博士</span>
    <span style="width: 20%;">上海市</span>
    <span style="width: 15%;"><b>查看职位</b></span>
  </a></li>
  <li><a href="/overseasxq?jobId=390472652&jc=3&c=&p=1^-1,3^-1&ky=" class="flex-between align-center">
    <span style="width: 15%;">职能支持类</span>
    <span style="width: 37%;">精装修工程师(J10954)</span>
    <span style="width: 13%;">社招</span>
    <span style="width: 20%;">北京市</span>
    <span style="width: 15%;"><b>查看职位</b></span>
  </a></li>
  <!--<li><a href="" class="flex-between align-center">
    <span style="width: 15%;">技术研发类</span>
    <span style="width: 37%;">光罩OPC(光学临近效应修正)工程师</span>
    <span style="width: 13%;">大专</span>
    <span style="width: 20%;">北京市海淀区</span>
    <span style="width: 15%;"><b>查看职位</b></span>
  </a></li>-->
</ul></div>
<div class="page pt50"><a href="#" class="now">1</a><a href='/social/?PageIndex=2' >2</a>
<a href='/social/?PageIndex=6' >...</a><a href='/social/?PageIndex=30' >30</a></div>
"""

# 越界页：仍是 HTTP 200 + 完整骨架，只是一条岗位锚点都没有 —— 唯一可靠的翻页终止信号。
EMPTY_PAGE_HTML = """
<div class="zwt"><table><tr class="one">
  <th>职位分类</th><th>职位名称</th><th>职位学历</th><th>工作地点</th><th>操作</th>
</tr></table></div>
<div class="zwm"><!--无数据--><ul></ul></div>
<div class="page pt50"><a href='/social/?PageIndex=1' >1</a></div>
"""

# 科伦式老版 CMS：主列表是 <table><tr><td>（路径式 /job_show/{id}），
# 只有右侧「热招职位」侧栏是裸 <a href="…?jobId=…">。行正则必须锚在 <li> 上才不会误采侧栏。
KELUN_LIKE_HTML = """
<div class="joblist"><table class="jobsTable">
  <tr class="title"><td>职位名称</td><td>职能</td><td>工作地点</td></tr>
  <tr><td><a title="科伦岳阳-HRBP(J13312)" href="/job_show/230910610">科伦岳阳-HRBP(J13312)</a></td>
      <td>通用职能类</td><td title="湖南省">湖南省</td></tr>
</table></div>
<div class="rzzw"><div class="con">
  <a href="/social_show?jobId=230910610" title="科伦岳阳-HRBP(J13312)">科伦岳阳-HRBP(J13312)</a>
  <a href="/social_show?jobId=230906625" title="科伦岳阳-质量总监(J13276)">科伦岳阳-质量总监(J13276)</a>
</div></div>
"""

# 详情页（中文版，社招/校招板块）：<h2> 全名 + 结构化字段 + 两段 xqm 正文，
# 正文后面紧跟几千字《职位申请知情同意书》—— 正文抽取绝不能把它带进来。
DETAIL_ZH_HTML = """
<div class="xqbox">
  <div class="xqtitle pr flex-between align-center">
    <h2 class=" col26 b f20 lh30">设计工艺协同研发工程师-张江（2027届校招）(J13378)</h2>
    <div class="share"><span class="f14">分享：</span></div>
  </div>
  <div class="xqt pt25 pb30 mb35">
    <ul><li><span>工作类型：</span><b class="col333">全职</b></li>
        <li><span>职位类别：</span><b class="col333">技术研发类</b></li>
        <li><span>职位学历：</span><b class="col333">硕士、博士</b></li>
        <li><span>招聘人数：</span><b class="col333">1</b></li></ul>
    <ul><li><span>更新时间：</span><b class="col333">2026.04.10</b></li>
        <li><span>工作地点：</span><b class="col333">上海市-浦东新区</b></li></ul>
  </div>
  <h3 class="f16 col333 b lh26 pb10">职位描述</h3>
  <div class="xqm">1. 负责设计工艺协同(DTCO)方法学开发与落地；<br />2. 负责标准单元库特征化与优化；<br />3. 支持先进制程 PPA 评估与迭代。</div>
  <h3 class="f16 col333 b lh26 pb10 pt35">职位要求</h3>
  <div class="xqm">1. 硕士及以上学历，微电子/电子工程相关专业；<br />2. 熟悉数字后端流程与器件物理；<br />3. 有良好的沟通与推动能力。</div>
  <div class="flex-center align-center pt40"><a href="javascript:void(0);" class="wysq">我要申请</a></div>
</div>
<div class="tsbox"><h4>职位申请知情同意书</h4>
  <p>本同意书概述我们（即本公司）如何透过我们网域网页上的线上招聘系统收集求职者的信息，
  以及我们如何「处理」该等信息。「求职者」指任何透过该网页申请加入本公司的个人。
  「处理」包括收集、存储、使用、加工、传输、提供、公开、删除个人信息。</p></div>
"""

# 详情页（英文版，海外板块）：同一套模板，只有 label 换成英文 —— 抽取必须按结构而不是按中文关键词。
DETAIL_EN_HTML = """
<div class="xqbox">
  <div class="xqtitle pr flex-between align-center">
    <h2 class=" col26 b f20 lh30">Equipment Engineer(J10442)</h2>
    <div class="bshare-custom"><a class="fxtxt">Share</a></div>
  </div>
  <div class="xqt pt25 pb30 mb35">
    <ul><li><span>Job type:</span><b class="col333">全职</b></li>
        <li><span>Job category:</span><b class="col333">Operation</b></li>
        <li><span>Education:</span><b class="col333">Bachelor</b></li>
        <li><span>Number of recruits:</span><b class="col333">若干</b></li></ul>
    <ul><li><span>Last Updated:</span><b class="col333">2022.05.09</b></li>
        <li><span>Location:</span><b class="col333">北京市</b></li></ul>
  </div>
  <h3 class="f16 col333 b lh26 pb10">job description</h3>
  <div class="xqm">1. Through troubleshooting and maintenance, ensure the normal operation of the equipment to meet production needs.<br />2. Maintain the stability of the equipment and increase the yield.</div>
  <h3 class="f16 col333 b lh26 pb10 pt35">Job requirements</h3>
  <div class="xqm">1. Bachelor's degree or above.<br />2. More than 10 years of relevant work experience in fab factory.</div>
  <div class="flex-center align-center pt40"><a href="javascript:void(0);" class="wysq">I want to apply for</a></div>
</div>
"""

# 伪 jobId：站点仍返 HTTP 200，但只有导航骨架 —— 没有 <h2>、没有 xqm 正文。
DETAIL_FAKE_HTML = """
<div class="head"><a href="/">首页</a><a href="/social/">社会招聘</a></div>
<div class="xqbox"></div>
<div class="footer">© 2023 版权所有</div>
"""


class TestCmsUrlNormalize(unittest.TestCase):
    """列表锚点尾部的筛选态回传参数（c/p/ky）必须剥掉，只留 jobId(+jc) 身份参数。
    不剥的话同一岗在不同筛选态下算出不同 canonical_jd_url → 库里同岗多行。"""

    def test_strips_filter_state_params(self):
        self.assertEqual(
            _cms_normalize_job_url(ORIGIN, "/socialxq?jobId=390609112&jc=1&c=&p=1^-1,3^-1&ky="),
            "https://tenant.zhiye.com/socialxq?jobId=390609112&jc=1")

    def test_stable_across_filter_states(self):
        a = _cms_normalize_job_url(ORIGIN, "/campusxq?jobId=1&jc=2&c=&p=1^-1,3^-1&ky=")
        b = _cms_normalize_job_url(ORIGIN, "/campusxq?jobId=1&jc=2&c=3100&p=1^5,3^-1&ky=工程师")
        self.assertEqual(a, b)

    def test_html_entities_in_href(self):
        self.assertEqual(
            _cms_normalize_job_url(ORIGIN, "/overseasxq?jobId=42&amp;jc=3&amp;c=&amp;ky="),
            "https://tenant.zhiye.com/overseasxq?jobId=42&jc=3")

    def test_absolute_href_kept(self):
        self.assertEqual(
            _cms_normalize_job_url(ORIGIN, "https://other.zhiye.com/socialxq?jobId=9&jc=1&c="),
            "https://other.zhiye.com/socialxq?jobId=9&jc=1")

    def test_no_jc_param(self):
        self.assertEqual(_cms_normalize_job_url(ORIGIN, "/xq?jobAdId=abc-123"),
                         "https://tenant.zhiye.com/xq?jobAdId=abc-123")

    def test_no_job_id_returns_empty(self):
        self.assertEqual(_cms_normalize_job_url(ORIGIN, "/social/?PageIndex=2"), "")


class TestCmsParseList(unittest.TestCase):
    def setUp(self):
        self.rows, self.last_page = _cms_parse_list(LIST_HTML, ORIGIN)
        self.by_title = {r["title"]: r for r in self.rows}

    def test_three_boards_all_yield_jd_url(self):
        """社招 socialxq / 校招 campusxq / 海外 overseasxq 三个板块都要抽得出逐岗链接。"""
        self.assertEqual([r["jd_url"] for r in self.rows], [
            "https://tenant.zhiye.com/socialxq?jobId=390609112&jc=1",
            "https://tenant.zhiye.com/campusxq?jobId=390852209&jc=2",
            "https://tenant.zhiye.com/overseasxq?jobId=390472652&jc=3",
        ])

    def test_fields_mapped_by_table_header(self):
        row = self.by_title["6S精益管理工程师(J11097)"]
        self.assertEqual(row["location"], "上海市-浦东新区")
        self.assertEqual(row["education"], "硕士")
        self.assertFalse(row["title_truncated"])

    def test_category_column_not_mistaken_for_title(self):
        """表头「职位分类」也含「职位」二字，不能被当成标题列。"""
        self.assertNotIn("工程支持类", self.by_title)

    def test_truncated_title_flagged(self):
        row = self.by_title["设计工艺协同研发工程师-张江（2027届校招）(J133..."]
        self.assertTrue(row["title_truncated"])

    def test_multi_level_education_takes_lowest(self):
        """「硕士、博士」= 硕士及以上，门槛是下限 → 取最低档，别把符合条件的人筛掉。"""
        self.assertEqual(self.by_title["设计工艺协同研发工程师-张江（2027届校招）(J133..."]["education"],
                         "硕士")

    def test_recruit_type_in_education_column(self):
        """租户把「社招」误填进学历列：不能当学历，但可以当招聘类型用。"""
        row = self.by_title["精装修工程师(J10954)"]
        self.assertIsNone(row["education"])
        self.assertEqual(row["job_type"], "社招")

    def test_commented_out_placeholder_rows_dropped(self):
        """模板占位假岗藏在 HTML 注释里（href=""），解析前必须先剥注释。"""
        self.assertNotIn("光罩OPC(光学临近效应修正)工程师", self.by_title)
        self.assertEqual(len(self.rows), 3)

    def test_last_page_from_pager(self):
        self.assertEqual(self.last_page, 30)

    def test_empty_page_is_the_termination_signal(self):
        """翻页越界仍返 200 + 完整骨架（表头、分页条都在）→ 只能靠「页内锚点数 0」判末页。"""
        rows, _ = _cms_parse_list(EMPTY_PAGE_HTML, ORIGIN)
        self.assertEqual(rows, [])

    def test_ignores_sidebar_anchors_outside_li(self):
        """科伦式租户：主列表是 <table>，只有侧栏「热招职位」是裸 <a ?jobId=>。
        误采侧栏 = 只拿到 10 条却自称抓全 → list-absence 会误杀在招岗。"""
        rows, _ = _cms_parse_list(KELUN_LIKE_HTML, ORIGIN)
        self.assertEqual(rows, [])

    def test_dedupes_by_jd_url(self):
        rows, _ = _cms_parse_list(LIST_HTML + LIST_HTML, ORIGIN)
        self.assertEqual(len(rows), 3)


class TestCmsParseDetail(unittest.TestCase):
    def test_chinese_detail(self):
        d = _cms_parse_detail(DETAIL_ZH_HTML)
        self.assertEqual(d["title"], "设计工艺协同研发工程师-张江（2027届校招）(J13378)")
        self.assertEqual(d["education"], "硕士")
        self.assertEqual(d["location"], "上海市-浦东新区")
        self.assertEqual(d["job_type"], "全职")
        self.assertIn("【职位描述】", d["summary"])
        self.assertIn("【职位要求】", d["summary"])
        self.assertIn("DTCO", d["summary"])

    def test_privacy_boilerplate_excluded(self):
        """正文只取 <h3>+<div class="xqm"> 结构块；整页切片会把《职位申请知情同意书》当岗位正文。"""
        summary = _cms_parse_detail(DETAIL_ZH_HTML)["summary"]
        self.assertNotIn("知情同意书", summary)
        self.assertNotIn("敏感个人信息", summary)
        self.assertNotIn("我要申请", summary)

    def test_english_detail_same_template(self):
        """海外板块是同一套模板的英文版：label 全换成英文，仍要抽得出正文与字段。"""
        d = _cms_parse_detail(DETAIL_EN_HTML)
        self.assertEqual(d["title"], "Equipment Engineer(J10442)")
        self.assertEqual(d["education"], "本科")     # Bachelor → 归一到 normalizer 口径
        self.assertEqual(d["location"], "北京市")
        self.assertIn("job description", d["summary"])
        self.assertIn("fab factory", d["summary"])

    def test_fake_job_id_page_yields_nothing(self):
        """伪 jobId 仍返 200（不能靠状态码判死）；但没有 <h2>、没有 xqm → 抽不出东西，保留列表值。"""
        d = _cms_parse_detail(DETAIL_FAKE_HTML)
        self.assertEqual(d["title"], "")
        self.assertIsNone(d["summary"])

    def test_terse_but_real_jd_is_kept(self):
        """结构块里取的短正文是真内容不是噪声（中芯 6 个环保安全岗 JD 本来就 50 来字）→ 存下来。
        「够不够 60 字算有效在招」由 count_valid_active_jobs 在读时把关，不在抓取层砍。"""
        html = ('<div class="xqtitle"><h2>环保安全工程师</h2></div>'
                '<h3>职位描述</h3><div class="xqm">1、负责消防系统运行和维护；2、负责安全、健康和环境管理工作。</div>'
                '<h3>职位要求</h3><div class="xqm">安全工程、环境工程专业</div>')
        summary = _cms_parse_detail(html)["summary"]
        self.assertIn("消防系统", summary)
        self.assertLess(len(summary), 60)

    def test_noise_length_body_not_stored_as_summary(self):
        html = ('<div class="xqtitle"><h2>测试岗</h2></div>'
                '<h3>职位描述</h3><div class="xqm">略。</div>')
        self.assertIsNone(_cms_parse_detail(html)["summary"])


class TestCmsEducation(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(_cms_education("硕士"), "硕士")
        self.assertEqual(_cms_education("硕士、博士"), "硕士")
        self.assertEqual(_cms_education("本科/硕士/博士"), "本科")
        self.assertEqual(_cms_education("Bachelor"), "本科")
        self.assertEqual(_cms_education("Master"), "硕士")

    def test_non_education_values(self):
        self.assertIsNone(_cms_education("社招"))
        self.assertIsNone(_cms_education(""))
        self.assertIsNone(_cms_education(None))


class TestCmsPageUrl(unittest.TestCase):
    """翻页 URL：替换而不是追加 PageIndex，且保留 source_url 自带的其它 query。"""

    def _u(self, url, page):
        from urllib.parse import urlparse
        return BeisenAdapter._cms_page_url(urlparse(url), page)

    def test_appends_page_index(self):
        self.assertEqual(self._u("https://tenant.zhiye.com/social/", 3),
                         "https://tenant.zhiye.com/social/?PageIndex=3")

    def test_replaces_existing_page_index(self):
        self.assertEqual(self._u("https://tenant.zhiye.com/social/?PageIndex=1", 7),
                         "https://tenant.zhiye.com/social/?PageIndex=7")


class TestSsrDetailPathsCoverBoards(unittest.TestCase):
    """浏览器兜底路径的路由候选表要覆盖社招/海外板块，否则这类租户只有校招抽得出 jd_url。"""

    def test_social_and_overseas_present(self):
        for path in ("socialxq", "campusxq", "overseasxq"):
            self.assertIn(path, _BEISEN_SSR_DETAIL_PATHS)


class TestBeisenParseSsrPayload(unittest.TestCase):
    """_httpx_fetch_cms 产物（{"_ssr_jobs":[…]}）经 parse() → RawJob，字段不丢。"""

    def test_parse_carries_cms_fields(self):
        import json
        a = BeisenAdapter()
        a.company_name = "示例公司"
        payload = {"_ssr_jobs": [
            {"title": "工艺工程师", "jd_url": "https://tenant.zhiye.com/socialxq?jobId=1&jc=1",
             "location": "上海市", "education": "硕士", "job_type": "社招", "summary": "职责若干"},
            {"title": "重复岗", "jd_url": "https://tenant.zhiye.com/socialxq?jobId=1&jc=1"},
            {"title": "无链接岗（应丢）", "jd_url": ""},
        ]}
        jobs = a.parse(json.dumps(payload))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "示例公司")
        self.assertEqual(jobs[0].education, "硕士")
        self.assertEqual(jobs[0].job_type, "社招")
        self.assertEqual(jobs[0].apply_url, jobs[0].jd_url)

    def test_legacy_payload_without_new_fields(self):
        """老的浏览器 SSR 路径不带 education/job_type → 仍要能解析（向后兼容）。"""
        import json
        a = BeisenAdapter()
        jobs = a.parse(json.dumps({"_ssr_jobs": [
            {"title": "老路径岗", "jd_url": "https://tenant.zhiye.com/job_show/123"}]}))
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(jobs[0].education)
        self.assertIsNone(jobs[0].job_type)


class StaleCmsHintTest(unittest.TestCase):
    """beisen_routes.json 里 {"cms": true} 过时（租户已升级到新版 SPA）时的自愈。

    不修的后果不是「少抓几个岗」，而是 **0 岗 + 自称抓全**：
    假登记让 host 命中路由缓存 → 「首见租户」分支被跳过 → 详情路由永远探不出来 →
    jd_url 全空 → 整源解析 0 岗，而浏览器路径又把 fetch_complete 置 True。
    fetch_complete=True 会开启 list-absence 撤岗 —— 抓漏 + 自称抓全 = 误杀在招岗，
    正是 CLAUDE.md「核心产品原则 §4」立碑警告的组合（华为 460 个在招岗差点被这么删掉）。
    """

    def setUp(self):
        self._saved = dict(china_ats._BEISEN_ROUTE_CACHE)

    def tearDown(self):
        china_ats._BEISEN_ROUTE_CACHE.clear()
        china_ats._BEISEN_ROUTE_CACHE.update(self._saved)

    def test_stale_cms_hint_is_evicted_so_tenant_can_be_reprobed(self):
        host = "stale-tenant.zhiye.com"
        china_ats._BEISEN_ROUTE_CACHE[host] = {"cms": True}
        calls = []

        adapter = BeisenAdapter()
        # 老版 CMS 抓取返回 None = 该租户其实不是老版 CMS（登记过时）。
        adapter._httpx_fetch_cms = lambda source_url: (calls.append("cms"), None)[1]
        # 把**所有会联网的下游**都摁住（单测不打真实网络）。注意 fetch 内部对它们是
        # try/except 兜底的，抛异常会被吞掉，所以这里返回 None / 抛 RuntimeError 让它自然走完。
        adapter._httpx_fetch = lambda source_url: (calls.append("httpx"), None)[1]
        adapter._fetch_paginated = lambda source_url: (
            calls.append("browser"), (_ for _ in ()).throw(RuntimeError("no browser")))[1]
        adapter._fetch_ssr = lambda source_url: (calls.append("ssr"), "{}")[1]

        adapter.fetch(f"https://{host}/social")

        self.assertNotIn(host, china_ats._BEISEN_ROUTE_CACHE,
                         "过时的 cms 登记必须被清出缓存，否则该租户永远探不出详情路由（0 岗+自称抓全）")
        # 光看缓存还不够：得证明确实**往下走了**新版探测，而不是在 CMS 分支就返回了。
        self.assertEqual(calls[0], "cms")
        self.assertIn("httpx", calls, "驱逐后必须继续尝试新版 httpx 列表抓取")

    def test_valid_cms_hint_is_kept(self):
        """反向不变量：登记正确（CMS 抓到了东西）时不能误删，否则每次都要重探、白掉慢车道。"""
        host = "real-cms.zhiye.com"
        china_ats._BEISEN_ROUTE_CACHE[host] = {"cms": True}

        adapter = BeisenAdapter()
        adapter._httpx_fetch_cms = lambda source_url: '{"_ssr_jobs": []}'

        self.assertEqual(adapter.fetch(f"https://{host}/social"), '{"_ssr_jobs": []}')
        self.assertEqual(china_ats._BEISEN_ROUTE_CACHE.get(host), {"cms": True})


if __name__ == "__main__":
    unittest.main()
