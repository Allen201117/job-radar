"""中国本土 ATS / 企业官网 SPA 通用 adapter 单测 — 用构造的接口响应 fixture，不打真实网络。"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import normalizer
from adapters.base import RawJob
from adapters.china_ats import (
    MokaAdapter,
    BeisenAdapter,
    CompanySpaAdapter,
    _BEISEN_SSR_ANCHOR_JS,
    _parse_moka_card,
)

# Moka 渲染后 DOM 岗位卡（接口加密，只能解析渲染后 a[href*='#/job/{uuid}']）。
# cards = [{href, text}]，text 是岗位卡 innerText（含换行），各租户排版样本见下。
MOKA_CARDS = {
    "_base": "https://app.mokahr.com/apply/shein/2933",
    "cards": [
        # SHEIN：角标「急」单独成行 → 标题取次行；城市在带「市」的短行
        {"href": "#/job/aaa", "text": "急\n全栈开发工程师\n发布于 2026-06-05\n全职\n|\n信息技术类\n|\n上海市\n立即投递"},
        # 雪球：角标「急」粘连标题；城市「上海市·黄浦区」
        {"href": "#/job/bbb", "text": "急上市公司服务-客户总监（华东）\n商业化部销售类\n上海市·黄浦区\n发布时间：2023-07-21"},
        # 非岗位链接（筛选）→ 丢弃
        {"href": "#/jobs?zhineng=1", "text": "职位筛选"},
        # 空文本 → 丢弃
        {"href": "#/job/ccc", "text": "   "},
        # 重复 url → 去重
        {"href": "#/job/aaa", "text": "急\n全栈开发工程师\n发布于 2026-06-05"},
    ],
}

# 北森常见响应形态（host 不可预测 → 必须接口自带链接）
BEISEN_SAMPLE = {
    "data": {
        "records": [
            {"positionId": "P1", "positionName": "财务分析师", "workPlace": "北京",
             "positionUrl": "https://group.zhiye.com/job/P1"},
            {"positionId": "P2", "positionName": "无链接岗（北森无模板，应丢）", "workPlace": "成都"},
        ]
    }
}


class TestMokaCardParse(unittest.TestCase):
    """_parse_moka_card：从各租户岗位卡 innerText 解析 (location, title)。"""

    def test_flag_on_own_line(self):  # SHEIN
        loc, title = _parse_moka_card("急\n全栈开发工程师\n发布于 2026-06-05\n全职\n|\n上海市\n立即投递")
        self.assertEqual(title, "全栈开发工程师")
        self.assertEqual(loc, "上海市")

    def test_glued_flag(self):  # 雪球
        loc, title = _parse_moka_card("急上市公司服务-客户总监（华东）\n商业化部销售类\n上海市·黄浦区\n发布时间：2023-07-21")
        self.assertEqual(title, "上市公司服务-客户总监（华东）")
        self.assertEqual(loc, "上海市·黄浦区")

    def test_glued_flag_wps(self):  # WPS
        loc, title = _parse_moka_card("急客户端c++研发\n全职技术类\n广东·珠海市\n发布时间：2026-05-20")
        self.assertEqual(title, "客户端c++研发")
        self.assertEqual(loc, "广东·珠海市")

    def test_hot_recruit_flag(self):  # 好未来
        loc, title = _parse_moka_card("火热招聘\n中学学习教练(C)-北京分校-26校招\n教师\n|\n北京市")
        self.assertEqual(title, "中学学习教练(C)-北京分校-26校招")
        self.assertEqual(loc, "北京市")

    def test_empty(self):
        self.assertEqual(_parse_moka_card(""), (None, ""))


class TestMokaAdapter(unittest.TestCase):
    def _parse(self, payload):
        return MokaAdapter().parse(json.dumps(payload))

    def test_parses_cards_builds_hash_route_url(self):
        jobs = self._parse(MOKA_CARDS)
        # 5 cards：筛选链接丢、空文本丢、重复 url 去重 → 2 条
        self.assertEqual(len(jobs), 2)
        by_title = {j.title: j for j in jobs}
        self.assertEqual(by_title["全栈开发工程师"].jd_url,
                         "https://app.mokahr.com/apply/shein/2933#/job/aaa")
        self.assertEqual(by_title["全栈开发工程师"].location, "上海市")
        self.assertEqual(by_title["全栈开发工程师"].company, "")  # 由 sources.company 兜底
        self.assertIn("上市公司服务-客户总监（华东）", by_title)

    def test_quality_gate_passes(self):
        for j in self._parse(MOKA_CARDS):
            j.company = "示例公司"
            ok, reason = normalizer.validate_job_quality(j, "https://app.mokahr.com/apply/x/1")
            self.assertTrue(ok, f"{j.title} 被质量门拒: {reason}")

    def test_empty_inputs(self):
        self.assertEqual(self._parse({"_base": "https://x", "cards": []}), [])
        self.assertEqual(MokaAdapter().parse("not json"), [])


class TestBeisenAdapter(unittest.TestCase):
    def setUp(self):
        self.a = BeisenAdapter()
        self.a._origin = "https://group.zhiye.com"
        self.a._host = "group.zhiye.com"

    def test_interface_url_still_preferred(self):
        jobs = self.a.parse(json.dumps({"_intercepted": [BEISEN_SAMPLE]}))
        # 接口自带 per-job 链接的行仍优先用该链接
        kept = {j.title: j for j in jobs}
        self.assertEqual(kept["财务分析师"].jd_url, "https://group.zhiye.com/job/P1")
        self.assertEqual(kept["财务分析师"].location, "北京")

    def test_jobad_pagelist_builds_detail_url(self):
        # 北森真实 GetJobAdPageList 形态：顶层 Data 列表，JobAdName/Id/LocNames，无 per-job URL。
        # 详情路由 query 恒为 ?jobAdId={Id}，path 由 fetch 时逐租户探测得到（此处模拟已探测结果）。
        self.a._detail_route = "https://group.zhiye.com/custom/zwxq"
        sample = {"Code": 0, "Data": [
            {"Id": "uuid-a", "JobAdId": 270940723, "JobAdName": "综合管理实习生", "LocNames": "上海市"},
            {"Id": "uuid-b", "JobAdName": "财务实习生", "LocNames": "黑龙江省·哈尔滨市"},
        ]}
        jobs = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertEqual(len(jobs), 2)
        by = {j.title: j for j in jobs}
        self.assertEqual(by["综合管理实习生"].jd_url,
                         "https://group.zhiye.com/custom/zwxq?jobAdId=uuid-a")
        self.assertEqual(by["综合管理实习生"].location, "上海市")
        self.assertEqual(by["财务实习生"].jd_url,
                         "https://group.zhiye.com/custom/zwxq?jobAdId=uuid-b")

    def test_beisen_category_becomes_job_type(self):
        """北森列表自报的 `Category`（"校园招聘"/"社会招聘"/"实习"）必须进 job_type。

        它是租户自己声明的招聘类别，比标题/URL 猜权威得多；漏掉它，校招岗只能被兜底成社招 ——
        2026-09-17 live 逐租户问北森自己，252 个租户自报 22,862 个校招岗，而奇瑞这类
        标题里一个校招令牌都没有的（"生产操作工"）在库里全是社招。
        """
        self.a._detail_route = "https://group.zhiye.com/custom/zwxq"
        sample = {"Data": [
            {"Id": "c1", "JobAdName": "生产操作工", "LocNames": "芜湖",
             "Category": "校园招聘", "Kind": "全职"},
            {"Id": "s1", "JobAdName": "销售代表", "LocNames": "上海",
             "Category": "社会招聘", "Kind": "全职"},
        ]}
        by = {j.title: j for j in self.a.parse(json.dumps({"_intercepted": [sample]}))}
        self.assertEqual(by["生产操作工"].job_type, "校园招聘")
        self.assertEqual(by["销售代表"].job_type, "社会招聘")

    def test_beisen_kind_is_never_used_as_job_type(self):
        """`Kind`（全职/兼职）绝不能当 job_type —— "全职" 会被裁决成「社招」，把校招岗按死。"""
        self.a._detail_route = "https://group.zhiye.com/custom/zwxq"
        sample = {"Data": [{"Id": "k1", "JobAdName": "某岗", "LocNames": "上海", "Kind": "全职"}]}
        [job] = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertIsNone(job.job_type)

    def test_other_tenant_detail_route(self):
        # 不同租户详情页名不同（如横店 /campus/detail）：用探测到的 _detail_base 拼。
        self.a._detail_route = "https://group.zhiye.com/campus/detail"
        sample = {"Data": [{"Id": "x9", "JobAdName": "投行分析师", "LocNames": "北京"}]}
        jobs = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].jd_url, "https://group.zhiye.com/campus/detail?jobAdId=x9")

    def test_no_detail_route_raises_instead_of_reporting_zero_jobs(self):
        # 探不到详情路由（_detail_route=None）→ 仍然不拼坏链；但「有行却一条都映射不出来」
        # **不许**静默返回 0 岗 —— 那会被下游读成「对方没岗了」。实测复星医药就这么连着
        # success + 0 岗 33 次（北森自报 161 个岗），必须抛错记 failed 让人看见。
        self.a._detail_route = None
        sample = {"Data": [{"Id": "x9", "JobAdName": "投行分析师", "LocNames": "北京"}]}
        with self.assertRaises(RuntimeError):
            self.a.parse(json.dumps({"_intercepted": [sample]}))

    def test_empty_list_is_still_an_honest_zero(self):
        # 对方真的没岗 → 照常返回 []，不许被上面那道闸误伤成 failed。
        self.a._detail_route = None
        self.assertEqual(self.a.parse(json.dumps({"_intercepted": [{"Data": []}]})), [])

    def test_click_captured_dict_route(self):
        # 点击捕获式路由 {template, idfield}：按 idfield 取值填模板（适配 jobId/jobAdId × Id/JobAdId）。
        self.a._detail_route = {
            "template": "https://group.zhiye.com/social/detail?jobAdId={id}", "idfield": "Id"}
        sample = {"Data": [{"Id": "uuid-z", "JobAdId": 999, "JobAdName": "算法专家", "LocNames": "深圳"}]}
        jobs = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].jd_url, "https://group.zhiye.com/social/detail?jobAdId=uuid-z")

    def test_click_captured_dict_route_numeric_jobid(self):
        # 另一约定：?jobId={JobAdId 数字}。idfield=JobAdId。
        self.a._detail_route = {
            "template": "https://x.zhiye.com/campusxq?jobId={id}", "idfield": "JobAdId"}
        sample = {"Data": [{"Id": "uuid-q", "JobAdId": 230859284, "JobAdName": "运营", "LocNames": "北京"}]}
        jobs = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertEqual(jobs[0].jd_url, "https://x.zhiye.com/campusxq?jobId=230859284")

    def test_duty_require_salary_mapped(self):
        # 北森 GetJobAdPageList 行自带 JD 正文：Duty(职责)/Require(要求)/Salary（live 实测 2026-06-10，
        # 欣旺达 451 岗全有 Duty）。此前 _map 只认小写 duty/requirement → 大小写不匹配，10.4k 岗 summary 全空。
        self.a._detail_route = "https://group.zhiye.com/custom/zwxq"
        sample = {"Data": [{
            "Id": "uuid-d", "JobAdName": "项目经理", "LocNames": "深圳",
            "Duty": "1、项目团队建立以及项目进度跟进；2、FATP工厂对接。",
            "Require": "1、本科及以上；2、3年项目管理经验。",
            "Salary": "15-25K",
        }]}
        jobs = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertEqual(len(jobs), 1)
        self.assertIn("项目团队建立", jobs[0].summary)
        self.assertIn("任职要求", jobs[0].summary)
        self.assertIn("本科及以上", jobs[0].summary)
        self.assertEqual(jobs[0].salary_text, "15-25K")

    def test_duty_only_no_require(self):
        # 只有 Duty 没有 Require：summary 取 Duty，不拼空的要求段。
        self.a._detail_route = "https://group.zhiye.com/custom/zwxq"
        sample = {"Data": [{"Id": "u1", "JobAdName": "运营", "LocNames": "北京",
                            "Duty": "负责社群运营与活动策划。"}]}
        jobs = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertEqual(jobs[0].summary, "负责社群运营与活动策划。")
        self.assertNotIn("任职要求", jobs[0].summary)


class TestBeisenSsrParse(unittest.TestCase):
    """老版 SSR（C 型，如中核 cnnc）：列表页 HTML 直出 jobId 锚点，_fetch_ssr 产出 _ssr_jobs 信封。
    parse 把信封转 RawJob（jd_url 已在 fetch 拼好），按 jd_url 去重，缺 title/jd_url 丢弃。"""

    def setUp(self):
        self.a = BeisenAdapter()
        self.a.company_name = "中核集团"

    def test_ssr_envelope_builds_jobs(self):
        env = {"_ssr_jobs": [
            {"title": "品牌推广岗(J28524)", "jd_url": "https://cnnc.zhiye.com/szxq?jobId=561260654",
             "location": None},
            {"title": "渠道与运营支持岗(J28527)", "jd_url": "https://cnnc.zhiye.com/szxq?jobId=561260650"},
            {"title": "品牌推广岗(J28524)", "jd_url": "https://cnnc.zhiye.com/szxq?jobId=561260654"},  # 重复 → 去重
            {"title": "", "jd_url": "https://cnnc.zhiye.com/szxq?jobId=1"},  # 缺标题 → 丢
            {"title": "缺链接岗", "jd_url": ""},  # 缺链接 → 丢
        ]}
        jobs = self.a.parse(json.dumps(env))
        self.assertEqual(len(jobs), 2)
        urls = {j.jd_url for j in jobs}
        self.assertIn("https://cnnc.zhiye.com/szxq?jobId=561260654", urls)
        self.assertIn("https://cnnc.zhiye.com/szxq?jobId=561260650", urls)
        self.assertEqual(jobs[0].company, "中核集团")  # 由 sources.company 兜底

    def test_ssr_jobs_pass_quality_gate(self):
        env = {"_ssr_jobs": [
            {"title": "市场营销中心专员(J29221)",
             "jd_url": "https://cnnc.zhiye.com/szxq?jobId=561260569"}]}
        for j in self.a.parse(json.dumps(env)):
            ok, reason = normalizer.validate_job_quality(j, "https://cnnc.zhiye.com/social/jobs")
            self.assertTrue(ok, f"{j.title} 被质量门拒: {reason}")

    def test_ssr_route_dict_distinct_from_clickcapture(self):
        # SSR 缓存形态 {ssr_path, ssr_param} 不应被新版 _resolve_url 误用（无 template → 返回空）。
        self.a._detail_route = {"ssr_path": "szxq", "ssr_param": "jobId"}
        sample = {"Data": [{"Id": "x", "JobAdName": "岗", "LocNames": "北京"}]}
        # 走新版 _intercepted 路径时，SSR dict 不含 template → 该行无 jd_url，绝不产坏链
        # （2026-09-17 真渲染实测：新版 uuid 拼进 SSR 路由渲染出来是门户首页）。
        # 但也不许静默 0 岗：抛错记 failed，等浏览器档重探路由。
        with self.assertRaises(RuntimeError):
            self.a.parse(json.dumps({"_intercepted": [sample]}))

    def test_ssr_shaped_route_is_not_httpx_ready(self):
        """`{ssr_path, ssr_param}` 配不了新版 uuid → 不能算「零浏览器可抓」，必须留浏览器档重探路由。

        它曾被当成「已缓存」→ 排进 httpx 快车道 → 每行 jd_url 空串 → success + 0 岗永久静默：
        复星医药（北森自报 161 岗 / 71 校招）、中核集团（自报 854 校招、库里 0）、京东方（必投）三家同病。
        """
        from adapters.china_ats import _BEISEN_ROUTE_CACHE, beisen_httpx_ready
        host = "unit-test-tenant.zhiye.com"
        try:
            _BEISEN_ROUTE_CACHE[host] = {"ssr_path": "szxq", "ssr_param": "jobId"}
            self.assertFalse(beisen_httpx_ready(f"https://{host}/social"))
            _BEISEN_ROUTE_CACHE[host] = {"template": "https://x/d?jobAdId={id}", "idfield": "Id"}
            self.assertTrue(beisen_httpx_ready(f"https://{host}/social"))
            _BEISEN_ROUTE_CACHE[host] = "https://x/custom/zwxq"
            self.assertTrue(beisen_httpx_ready(f"https://{host}/social"))
            _BEISEN_ROUTE_CACHE[host] = {"cms": True}
            self.assertTrue(beisen_httpx_ready(f"https://{host}/social"))
        finally:
            _BEISEN_ROUTE_CACHE.pop(host, None)

    def test_ssr_anchor_js_keeps_guid_adid_anchors(self):
        # BOE / 中国建筑这类老校招 SSR 使用 details2021?adId={GUID}，不能只接收数字 jobId。
        script = f"""
const fn = eval({json.dumps(_BEISEN_SSR_ANCHOR_JS)});
const anchors = [
  {{
    getAttribute: () => '/social/details2021?adId=7f8c4f7a-8858-4df9-a8f8-31bbad6dbf28',
    innerText: '研发工程师(J12345)',
    textContent: '研发工程师(J12345)'
  }},
  {{
    getAttribute: () => '/social/details2021?adId=7f8c4f7a-8858-4df9-a8f8-31bbad6dbf28',
    innerText: '研发工程师(J12345)',
    textContent: '研发工程师(J12345)'
  }}
];
global.document = {{ querySelectorAll: () => anchors }};
process.stdout.write(JSON.stringify(fn()));
"""
        result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), [{
            "id": "7f8c4f7a-8858-4df9-a8f8-31bbad6dbf28",
            "name": "研发工程师(J12345)",
        }])


class TestCompanySpaAdapter(unittest.TestCase):
    """通用企业官网：拦截所有 JSON，仅放行带真实 per-job 链接的行，绝不拼/猜 URL。"""

    def setUp(self):
        self.a = CompanySpaAdapter()
        self.a._origin = "https://careers.example-corp.com"
        self.a._host = "careers.example-corp.com"

    def test_drops_rows_without_url(self):
        sample = {"result": {"items": [
            {"id": "1", "title": "有链接岗", "jobUrl": "/position/1"},
            {"id": "2", "title": "无链接岗（应丢）"},
        ]}}
        jobs = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].jd_url, "https://careers.example-corp.com/position/1")

    def test_no_template_guess(self):
        self.assertEqual(self.a.detail_template, "")
        self.assertEqual(self.a.intercept_matches, ())  # 拦截所有 JSON


class FeishuGenericTest(unittest.TestCase):
    """飞书泛化适配器：host 从 source_url 解析（不再每家硬编码子类）。"""

    def test_host_bound_from_source_url(self):
        from adapters.feishu import FeishuGenericAdapter
        a = FeishuGenericAdapter()
        self.assertEqual(a.detail_template, "")  # init 不固定 host
        host = a._bind_host("https://lixiang.jobs.feishu.cn/index/position")
        self.assertEqual(host, "lixiang.jobs.feishu.cn")
        self.assertEqual(a.official_hosts, ("lixiang.jobs.feishu.cn",))
        self.assertEqual(
            a.detail_template, "https://lixiang.jobs.feishu.cn/index/position/{id}/detail")
        self.assertIn("https://lixiang.jobs.feishu.cn/index/position", a.list_urls)

    def test_portal_slug_bound_from_source_url(self):
        from adapters.feishu import FeishuGenericAdapter
        a = FeishuGenericAdapter()
        host = a._bind_host("https://ponyai.jobs.feishu.cn/ponyai")
        self.assertEqual(host, "ponyai.jobs.feishu.cn")
        self.assertEqual(
            a.detail_template, "https://ponyai.jobs.feishu.cn/ponyai/position/{id}/detail")
        self.assertEqual(a.list_urls[0], "https://ponyai.jobs.feishu.cn/ponyai")
        self.assertIn("https://ponyai.jobs.feishu.cn/index/position", a.list_urls)

    def test_map_uses_bound_template(self):
        from adapters.feishu import FeishuGenericAdapter
        a = FeishuGenericAdapter()
        a._bind_host("https://dewu.jobs.feishu.cn/index/position")
        job = a._map({"id": "777", "title": "算法工程师",
                      "city_info": {"name": "上海"}, "job_category": {"name": "技术"}})
        self.assertEqual(job.title, "算法工程师")
        self.assertEqual(job.location, "上海")
        self.assertEqual(job.company, "")  # 由 sources.company 兜底
        self.assertEqual(
            job.jd_url, "https://dewu.jobs.feishu.cn/index/position/777/detail")

    def test_map_uses_portal_slug_template(self):
        from adapters.feishu import FeishuGenericAdapter
        a = FeishuGenericAdapter()
        a._bind_host("https://momenta.jobs.feishu.cn/talent")
        job = a._map({"id": "888", "title": "感知算法工程师",
                      "city_info": {"name": "苏州"}, "job_category": {"name": "研发"}})
        self.assertEqual(
            job.jd_url, "https://momenta.jobs.feishu.cn/talent/position/888/detail")


if __name__ == "__main__":
    unittest.main()
