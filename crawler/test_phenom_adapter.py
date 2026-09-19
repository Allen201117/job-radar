import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import httpx

from adapters.phenom import PhenomAdapter


def _wrap(jobs):
    return json.dumps({"_host": "https://careers.amd.com", "jobs": jobs})


class TestPhenomAdapter(unittest.TestCase):
    def test_china_filter_jdurl_and_slug_fallback(self):
        payload = _wrap([
            {"slug": "86295", "title": "BD Manager", "city": "Beijing", "state": "Beijing", "country": "China"},
            {"slug": "99", "title": "US Role", "city": "Austin", "state": "Texas", "country": "United States"},
            {"slug": "100", "title": "HK Role", "city": "Central", "country": "Hong Kong"},
            {"slug": "", "req_id": "77", "title": "Slug from req_id", "city": "Shanghai", "country": "China"},
        ])
        jobs = PhenomAdapter().parse(payload)
        urls = {j.jd_url for j in jobs}
        # jd_url = {host}/jobs/{slug}，公开详情页（非 icims apply_url）
        self.assertIn("https://careers.amd.com/jobs/86295", urls)
        self.assertIn("https://careers.amd.com/jobs/100", urls)   # HK 保留
        self.assertIn("https://careers.amd.com/jobs/77", urls)    # slug 缺则用 req_id
        self.assertNotIn("https://careers.amd.com/jobs/99", urls)  # 非华岗丢弃
        self.assertEqual(len(jobs), 3)

    def test_skip_missing_title_or_slug(self):
        payload = _wrap([
            {"slug": "1", "title": "", "country": "China"},
            {"slug": "", "req_id": "", "title": "No id", "country": "China"},
        ])
        self.assertEqual(PhenomAdapter().parse(payload), [])

    def test_parse_garbage_returns_empty(self):
        self.assertEqual(PhenomAdapter().parse("not json"), [])

    def test_summary_populated_from_list_description(self):
        # /api/jobs 列表 data 自带完整 JD 正文（live 验证）→ summary 非空，治 0% 覆盖薄卡。
        payload = _wrap([{
            "slug": "86972", "title": "BD Senior Manager", "city": "Shanghai", "country": "China",
            "description": "WHAT YOU DO AT AMD CHANGES EVERYTHING. Build great products.",
            "responsibilities": "THE ROLE: work with ODMs to develop business.",
            "qualifications": "10+ years of relevant experience.",
        }])
        job = PhenomAdapter().parse(payload)[0]
        self.assertIsNotNone(job.summary)
        self.assertIn("CHANGES EVERYTHING", job.summary)
        self.assertIn("ODMs", job.summary)

    def test_summary_none_when_list_has_no_description(self):
        payload = _wrap([{"slug": "1", "title": "Role", "city": "Beijing", "country": "China"}])
        self.assertIsNone(PhenomAdapter().parse(payload)[0].summary)


def _resp(payload=None, status_code=200):
    request = httpx.Request("GET", "https://careers.example.com/api/jobs")
    response = httpx.Response(status_code, json=payload or {}, request=request)
    return response


class ApiJobsLocationSkipTest(unittest.TestCase):
    """根因实锤（2026-09-14~18，AMD/PepsiCo 连续 25 次 failed）：regions 派生出的
    "Remote" 地点字面量该租户的 /api/jobs 恒返 422（China/United States/Singapore 都 200），
    而旧逻辑对「非首个地点」的任何异常一律原样上抛 → 一个不支持的地点拖垮整源。
    422 必须只跳过该地点，其余地点继续抓、不许整源失败。"""

    SOURCE_URL = "https://careers.amd.com/api/jobs"

    def test_422_on_non_first_location_is_skipped_not_fatal(self):
        china_jobs = {
            "jobs": [{"data": {"slug": "1", "title": "T", "country": "China",
                                "description": "d" * 80}}],
            "totalCount": 1,
        }

        def get_side_effect(url, params=None, headers=None, timeout=None):
            loc = params.get("location")
            if loc == "Remote":
                return _resp(status_code=422)
            return _resp(china_jobs)

        adapter = PhenomAdapter()
        adapter.regions = ["CN", "US", "SG", "Remote"]
        with mock.patch("adapters.phenom.httpx.get", side_effect=get_side_effect):
            payload = adapter.fetch(self.SOURCE_URL)
        jobs = adapter.parse(payload)
        # China/Hong Kong/Singapore/United States 都应正常抓到，只有 Remote 被跳过。
        self.assertGreater(len(jobs), 0)

    def test_422_on_first_location_still_falls_back_to_widgets(self):
        """首个地点就 422（整条 API 都不通）时仍走既有回退路径，不受本次改动影响。"""
        adapter = PhenomAdapter()
        adapter.regions = ["CN"]
        with mock.patch("adapters.phenom.httpx.get",
                         side_effect=lambda *a, **k: _resp(status_code=422)), \
                mock.patch.object(PhenomAdapter, "_fetch_widgets",
                                  return_value=json.dumps({
                                      "_host": "https://careers.example.com",
                                      "_site": "/global/en", "_mode": "widgets", "jobs": [],
                                  })):
            with self.assertRaises(httpx.HTTPStatusError):
                adapter.fetch(self.SOURCE_URL)

    def test_non_422_error_on_non_first_location_still_raises(self):
        """500 等其它错误码不是「地点不支持」的信号，必须继续原样上抛记 failed。"""
        def get_side_effect(url, params=None, headers=None, timeout=None):
            loc = params.get("location")
            if loc == "Remote":
                return _resp(status_code=500)
            return _resp({"jobs": [{"data": {"slug": "1", "title": "T", "country": "China",
                                              "description": "d" * 80}}], "totalCount": 1})

        adapter = PhenomAdapter()
        adapter.regions = ["CN", "US", "SG", "Remote"]
        with mock.patch("adapters.phenom.httpx.get", side_effect=get_side_effect):
            with self.assertRaises(httpx.HTTPStatusError):
                adapter.fetch(self.SOURCE_URL)


if __name__ == "__main__":
    unittest.main()
