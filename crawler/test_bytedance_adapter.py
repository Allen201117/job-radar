"""字节 SPA adapter 单测 — 用录制的接口响应 fixture，不打真实网络。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import normalizer
from adapters.base import RawJob
from adapters.bytedance import BytedanceAdapter

# 录制的字节 /api/v1/search/job/posts 响应片段（结构真实，内容删减）
SAMPLE = {
    "data": {
        "job_post_list": [
            {"id": "7644436900522248453", "title": "大语言模型可解释性研究员-Seed",
             "city_info": {"name": "上海"}, "job_category": {"name": "研发"}},
            {"id": "7641852190756407605", "title": "内容生态运营-短剧内容",
             "city_list": [{"name": "北京"}]},
            {"id": "", "title": "无 id 应被丢弃"},
            {"id": "999", "title": ""},  # 无 title 应被丢弃
        ]
    }
}


class TestBytedanceAdapter(unittest.TestCase):
    def setUp(self):
        self.a = BytedanceAdapter()

    def _parse(self, *responses):
        return self.a.parse(json.dumps({"_intercepted": list(responses)}))

    def test_parse_maps_real_jobs(self):
        jobs = self._parse(SAMPLE)
        self.assertEqual(len(jobs), 2)  # 无 id / 无 title 两条被丢
        j = jobs[0]
        self.assertEqual(j.company, "字节跳动")
        self.assertIn("大语言模型", j.title)
        self.assertEqual(j.location, "上海")
        self.assertEqual(j.job_type, "研发")
        self.assertEqual(j.jd_url, "https://jobs.bytedance.com/experienced/position/7644436900522248453/detail")

    def test_city_from_city_list_fallback(self):
        jobs = self._parse(SAMPLE)
        self.assertEqual(jobs[1].location, "北京")

    def test_dedup_same_jd_url(self):
        jobs = self._parse(SAMPLE, SAMPLE)  # 同响应出现两次
        self.assertEqual(len(jobs), 2)

    def test_empty_when_no_intercepted(self):
        self.assertEqual(self.a.parse(json.dumps({"_intercepted": []})), [])
        self.assertEqual(self.a.parse("not json"), [])

    def test_host_filter_drops_non_official(self):
        class FakeHost(BytedanceAdapter):
            detail_template = "https://evil.example.com/position/{id}"
        jobs = FakeHost().parse(json.dumps({"_intercepted": [SAMPLE]}))
        self.assertEqual(len(jobs), 0)  # jd_url host 不在 official_hosts → 丢弃

    def test_quality_gate_accepts_detail_rejects_homepage(self):
        src = "https://jobs.bytedance.com/experienced/position"
        ok, _ = normalizer.validate_job_quality(
            RawJob(company="字节跳动", title="算法工程师",
                   jd_url="https://jobs.bytedance.com/experienced/position/7644436900522248453"), src)
        self.assertTrue(ok)
        bad, _ = normalizer.validate_job_quality(
            RawJob(company="字节跳动", title="算法工程师", jd_url="https://jobs.bytedance.com/"), src)
        self.assertFalse(bad)  # 首页被拒


if __name__ == "__main__":
    unittest.main()
