"""中国本土 ATS / 企业官网 SPA 通用 adapter 单测 — 用构造的接口响应 fixture，不打真实网络。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import normalizer
from adapters.base import RawJob
from adapters.china_ats import MokaAdapter, BeisenAdapter, CompanySpaAdapter, _parse_moka_card

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
        self.a._detail_base = "https://group.zhiye.com/custom/zwxq"
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

    def test_other_tenant_detail_route(self):
        # 不同租户详情页名不同（如横店 /campus/detail）：用探测到的 _detail_base 拼。
        self.a._detail_base = "https://group.zhiye.com/campus/detail"
        sample = {"Data": [{"Id": "x9", "JobAdName": "投行分析师", "LocNames": "北京"}]}
        jobs = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].jd_url, "https://group.zhiye.com/campus/detail?jobAdId=x9")

    def test_no_detail_route_drops_jobs(self):
        # 探不到详情路由（_detail_base=None）→ 不拼坏链，丢弃无接口链接的行。
        self.a._detail_base = None
        sample = {"Data": [{"Id": "x9", "JobAdName": "投行分析师", "LocNames": "北京"}]}
        jobs = self.a.parse(json.dumps({"_intercepted": [sample]}))
        self.assertEqual(jobs, [])


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


if __name__ == "__main__":
    unittest.main()
