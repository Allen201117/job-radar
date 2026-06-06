"""中国本土 ATS / 企业官网 SPA 通用 adapter 单测 — 用构造的接口响应 fixture，不打真实网络。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import normalizer
from adapters.base import RawJob
from adapters.china_ats import MokaAdapter, BeisenAdapter, CompanySpaAdapter

# Moka 常见响应形态（字段名做了多样化，验证启发式抽取的鲁棒性）
MOKA_SAMPLE = {
    "data": {
        "list": [
            {"id": "10086", "name": "高级前端工程师", "cityName": "深圳",
             "categoryName": "研发", "description": "负责 C 端页面"},
            {"jobId": "10087", "title": "品牌市场经理",
             "city": {"name": "上海"}, "detailUrl": "/jobs/10087"},
            {"id": "10088", "title": "供应链管培生", "workCity": "杭州",
             "url": "https://demo.mokahr.com/social/position/10088"},
            {"id": "", "title": "无 id 但有真实链接", "link": "https://demo.mokahr.com/jobs/x1"},
            {"id": "10090", "name": ""},  # 无 title 丢弃
        ]
    }
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


class TestMokaAdapter(unittest.TestCase):
    def setUp(self):
        self.a = MokaAdapter()
        # fetch() 通常设置 _origin/_host；单测里手动设置（模拟 demo.mokahr.com 租户）
        self.a._origin = "https://demo.mokahr.com"
        self.a._host = "demo.mokahr.com"

    def _parse(self, *responses):
        return self.a.parse(json.dumps({"_intercepted": list(responses)}))

    def test_heuristic_extraction_and_template_fallback(self):
        jobs = self._parse(MOKA_SAMPLE)
        # 5 条：无 title 丢 1 条 → 4 条
        self.assertEqual(len(jobs), 4)
        by_title = {j.title: j for j in jobs}

        # 无链接 → 用模板 https://{host}/jobs/{id}
        self.assertEqual(by_title["高级前端工程师"].jd_url, "https://demo.mokahr.com/jobs/10086")
        self.assertEqual(by_title["高级前端工程师"].location, "深圳")
        self.assertEqual(by_title["高级前端工程师"].job_type, "研发")
        # 相对链接 → 拼 origin
        self.assertEqual(by_title["品牌市场经理"].jd_url, "https://demo.mokahr.com/jobs/10087")
        self.assertEqual(by_title["品牌市场经理"].location, "上海")
        # 绝对链接 → 原样
        self.assertEqual(by_title["供应链管培生"].jd_url, "https://demo.mokahr.com/social/position/10088")
        # 无 id 但接口自带真实链接 → 仍放行
        self.assertEqual(by_title["无 id 但有真实链接"].jd_url, "https://demo.mokahr.com/jobs/x1")

    def test_company_filled_from_source(self):
        jobs = self._parse(MOKA_SAMPLE)
        # adapter 留空 company，由 run.py 用 sources.company 兜底
        self.assertTrue(all(j.company == "" for j in jobs))

    def test_quality_gate_passes(self):
        jobs = self._parse(MOKA_SAMPLE)
        for j in jobs:
            j.company = "示例公司"
            ok, reason = normalizer.validate_job_quality(j, "https://demo.mokahr.com/social/home")
            self.assertTrue(ok, f"{j.title} 被质量门拒: {reason}")

    def test_empty_inputs(self):
        self.assertEqual(self.a.parse(json.dumps({"_intercepted": []})), [])
        self.assertEqual(self.a.parse("not json"), [])


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
