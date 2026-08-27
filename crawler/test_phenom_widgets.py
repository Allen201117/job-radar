"""Phenom widgets 分支单测（零网络：内联假 JSON 喂 parse / 纯函数）。

钉三件 live 踩过的坑：
① 总数在 refineSearch.totalHits，不在 data 里 —— 取错位置会让 reported_total 永远为空、抓全率不可测；
② jd_url 模板是 {host}{site}/job/{jobSeqNo}/{slug}，jobSeqNo 不是 reqId/jobId；
③ country facet 字面量必须一字不差（"China" 返 0，"China, People's Republic of" 才返 121），
   且要由 sources.regions 派生、不许写死。
另钉：/api/jobs 分支的解析口径不被 widgets 改动影响（现网 AMD/PepsiCo 源零回归）。
"""
import json
import unittest
from unittest import mock

from adapters.phenom import PhenomAdapter


def _widgets_payload(rows, site="/global/en", host="https://careers.example.com"):
    return json.dumps({"_host": host, "_site": site, "_mode": "widgets", "jobs": rows})


_ROW = {
    "title": "Pricing Analyst 价格分析师",
    "jobSeqNo": "DPDHGLOBALAV365375ENGLOBALEXTERNAL",
    "jobId": "AV-365375",
    "reqId": "AV-365375",
    "city": "Beijing",
    "state": "Beijing",
    "country": "China, People's Republic of",
    "postedDate": "2026-07-22T02:51:08.165+0000",
    "descriptionTeaser": "列表行的完整句子兜底摘要，" * 6,
    "ml_job_parser": {"descriptionTeaser": "We are looking for a Pricing Analyst to support pricing systems in China. " * 2},
    "applyUrl": "https://dpdhlgroup.avature.net/zh_CN/jobs/ApplicationMethods?jobId=365375",
}


class WidgetsParseTest(unittest.TestCase):
    def test_jd_url_uses_job_seq_no_and_site_path(self):
        jobs = PhenomAdapter().parse(_widgets_payload([_ROW]))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(
            jobs[0].jd_url,
            "https://careers.example.com/global/en/job/"
            "DPDHGLOBALAV365375ENGLOBALEXTERNAL/DPDHGLOBALAV365375ENGLOBALEXTERNAL",
        )
        # applyUrl 指向 avature 登录页，违反 jd_url 质量门 —— 绝不能漏进 apply_url。
        self.assertEqual(jobs[0].apply_url, jobs[0].jd_url)
        self.assertNotIn("avature", jobs[0].apply_url)

    def test_site_path_from_payload_is_honored(self):
        jobs = PhenomAdapter().parse(_widgets_payload([_ROW], site="/us/en"))
        self.assertIn("/us/en/job/", jobs[0].jd_url)

    def test_posted_date_coerced_to_iso_date(self):
        jobs = PhenomAdapter().parse(_widgets_payload([_ROW]))
        self.assertEqual(jobs[0].posted_at, "2026-07-22")

    def test_row_without_job_seq_no_is_dropped(self):
        row = dict(_ROW)
        row.pop("jobSeqNo")
        self.assertEqual(PhenomAdapter().parse(_widgets_payload([row])), [])

    def test_out_of_region_row_is_dropped(self):
        row = dict(_ROW, city="Bonn", state="North Rhine-Westphalia", country="Germany",
                   jobSeqNo="DE1")
        adapter = PhenomAdapter()
        adapter.regions = ["CN"]
        self.assertEqual(adapter.parse(_widgets_payload([row])), [])

    def test_duplicate_seq_no_collapses(self):
        jobs = PhenomAdapter().parse(_widgets_payload([_ROW, dict(_ROW)]))
        self.assertEqual(len(jobs), 1)

    def test_summary_prefers_detail_overview_then_full_description(self):
        row = dict(_ROW, _detail={
            "ai_summary": "AI-OVERVIEW",
            "description": "<p>FULL-DESCRIPTION</p>",
            # detail 的 descriptionTeaser 是被截断的 HTML 碎片，过不了 60 字门，不许被选中当唯一正文
            "descriptionTeaser": '<div style="font-family: arial, "',
        })
        summary = PhenomAdapter().parse(_widgets_payload([row]))[0].summary
        self.assertTrue(summary.startswith("AI-OVERVIEW"))
        self.assertIn("FULL-DESCRIPTION", summary)
        self.assertNotIn('font-family: arial', summary)

    def test_summary_falls_back_to_list_row_when_no_detail(self):
        """快档 CRAWL_DETAIL_CAP=0 不跑逐岗 detail，仍要有 ≥60 字正文（否则全是薄卡）。"""
        summary = PhenomAdapter().parse(_widgets_payload([_ROW]))[0].summary
        self.assertGreaterEqual(len(summary), 60)
        self.assertIn("Pricing Analyst", summary)

    def test_api_jobs_payload_still_parsed_by_old_shape(self):
        """widgets 改动不得动 /api/jobs 分支（现网 AMD/PepsiCo 走这条）。"""
        payload = json.dumps({"_host": "https://careers.amd.com", "jobs": [{
            "title": "Component Sales Account Manager",
            "slug": "84222", "city": "Beijing", "country": "China",
            "description": "d" * 80, "posted_date": "2026-06-01",
        }]})
        jobs = PhenomAdapter().parse(payload)
        self.assertEqual(jobs[0].jd_url, "https://careers.amd.com/jobs/84222")


class CountryFacetTest(unittest.TestCase):
    def _facets(self, regions):
        adapter = PhenomAdapter()
        adapter.regions = regions
        return adapter._country_facets_for_regions()

    def test_cn_uses_phenom_standardised_country_name(self):
        facets = self._facets(["CN"])
        # live 实测：facet 只认标准化全名，"China" 单独传返 0 条。
        self.assertEqual(facets[0], "China, People's Republic of")
        self.assertNotIn("Hong Kong, China", facets)

    def test_hk_opt_in_adds_hong_kong_literal(self):
        facets = self._facets(["CN", "HK"])
        self.assertIn("China, People's Republic of", facets)
        self.assertIn("Hong Kong, China", facets)

    def test_overseas_regions_derive_their_own_literals(self):
        facets = self._facets(["US", "SG"])
        self.assertIn("United States of America", facets)  # "United States" 单独传 live 返 0
        self.assertIn("Singapore", facets)
        self.assertNotIn("China, People's Republic of", facets)

    def test_remote_only_falls_back_to_cn(self):
        """Remote 不是国家、widgets 没有对应 facet；派生不出时回退 CN，绝不放空 facet 抓全球。"""
        self.assertEqual(self._facets(["Remote"]), list(PhenomAdapter.country_facets["CN"]))

    def test_regions_string_form_is_accepted(self):
        # sources.regions 从 PG text[] 读出来可能是 '{CN,HK}' 字符串
        self.assertIn("Hong Kong, China", self._facets("{CN,HK}"))


class SitePathTest(unittest.TestCase):
    def test_default_site_path(self):
        self.assertEqual(PhenomAdapter._site_path("https://careers.dhl.com/widgets"), "/global/en")

    def test_site_override_from_query(self):
        self.assertEqual(
            PhenomAdapter._site_path("https://careers.x.com/widgets?site=/us/en"), "/us/en")

    def test_locale_derived_from_site_path(self):
        self.assertEqual(PhenomAdapter._locale_from_site("/global/en"), ("global", "en_global"))
        self.assertEqual(PhenomAdapter._locale_from_site("/us/en"), ("us", "en_us"))


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class WidgetsFetchTest(unittest.TestCase):
    """用假 client 验取数编排：totalHits 位置、翻页请求体、逐岗 detail cap。"""

    def _run_fetch(self, total_hits, page_rows, detail_cap="0"):
        calls = []

        class FakeClient:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def post(self_inner, url, json=None, **kw):
                calls.append(json)
                if json["ddoKey"] == "jobDetail":
                    return _FakeResponse({"jobDetail": {"hits": 1, "data": {"job": {
                        "ai_summary": f"OVERVIEW {json['jobSeqNo']}",
                        "description": "<p>FULL</p>",
                    }}}})
                start = json["from"]
                return _FakeResponse({"refineSearch": {
                    "totalHits": total_hits,
                    "data": {"jobs": page_rows[start:start + json["size"]]},
                }})

        adapter = PhenomAdapter()
        adapter.regions = ["CN"]
        adapter.widgets_page_size = 2
        with mock.patch("adapters.phenom.httpx.Client", return_value=FakeClient()), \
                mock.patch.dict("os.environ", {"CRAWL_DETAIL_CAP": detail_cap}):
            payload = adapter.fetch("https://careers.dhl.com/widgets")
        return adapter, json.loads(payload), calls

    def test_total_hits_read_from_refine_search_not_data(self):
        rows = [dict(_ROW, jobSeqNo=f"SEQ{i}") for i in range(3)]
        adapter, payload, calls = self._run_fetch(3, rows)
        self.assertEqual(adapter.reported_total, 3)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(len(payload["jobs"]), 3)
        self.assertEqual(payload["_mode"], "widgets")
        # 翻页用 from = page * size，且 country facet 由 regions 派生后原样带上
        self.assertEqual([c["from"] for c in calls], [0, 2])
        self.assertEqual(calls[0]["selected_fields"]["country"][0], "China, People's Republic of")
        self.assertEqual(calls[0]["ddoKey"], "refineSearch")
        self.assertEqual(calls[0]["lang"], "en_global")

    def test_incomplete_when_total_hits_exceeds_collected(self):
        rows = [dict(_ROW, jobSeqNo=f"SEQ{i}") for i in range(2)]
        adapter, _, _ = self._run_fetch(99, rows)
        self.assertEqual(adapter.reported_total, 99)
        self.assertFalse(adapter.fetch_complete)

    def test_detail_cap_zero_skips_per_job_requests(self):
        rows = [dict(_ROW, jobSeqNo=f"SEQ{i}") for i in range(2)]
        _, payload, calls = self._run_fetch(2, rows, detail_cap="0")
        self.assertTrue(all(c["ddoKey"] == "refineSearch" for c in calls))
        self.assertNotIn("_detail", payload["jobs"][0])

    def test_detail_cap_fetches_job_detail(self):
        rows = [dict(_ROW, jobSeqNo=f"SEQ{i}") for i in range(2)]
        _, payload, calls = self._run_fetch(2, rows, detail_cap="5")
        detail_calls = [c for c in calls if c["ddoKey"] == "jobDetail"]
        self.assertEqual([c["jobSeqNo"] for c in detail_calls], ["SEQ0", "SEQ1"])
        self.assertEqual(payload["jobs"][0]["_detail"]["ai_summary"], "OVERVIEW SEQ0")

    def test_detail_miss_does_not_blow_up_the_source(self):
        """单岗 detail 失败/岗位已撤（hits=0）→ 正文回落列表行，不炸整源。"""
        rows = [dict(_ROW, jobSeqNo="SEQ0")]
        calls = []

        class FakeClient:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def post(self_inner, url, json=None, **kw):
                calls.append(json)
                if json["ddoKey"] == "jobDetail":
                    return _FakeResponse({"jobDetail": {"hits": 0, "totalHits": 0, "data": {}}})
                return _FakeResponse({"refineSearch": {
                    "totalHits": 1, "data": {"jobs": rows}}})

        adapter = PhenomAdapter()
        adapter.regions = ["CN"]
        with mock.patch("adapters.phenom.httpx.Client", return_value=FakeClient()), \
                mock.patch.dict("os.environ", {"CRAWL_DETAIL_CAP": "5"}):
            payload = json.loads(adapter.fetch("https://careers.dhl.com/widgets"))
        self.assertNotIn("_detail", payload["jobs"][0])
        self.assertGreaterEqual(len(adapter.parse(json.dumps(payload))[0].summary), 60)


class ApiJobsFallbackTest(unittest.TestCase):
    """/api/jobs 不可用时自动回退 widgets —— 按响应特征选路，不按域名白名单。"""

    def test_first_request_failure_falls_back_to_widgets(self):
        adapter = PhenomAdapter()
        adapter.regions = ["CN"]
        with mock.patch.object(PhenomAdapter, "_fetch_api_jobs",
                               side_effect=lambda *a, **k: (_ for _ in ()).throw(
                                   __import__("adapters.phenom", fromlist=["x"])._ApiJobsUnavailable(
                                       RuntimeError("HTTP 500")))), \
                mock.patch.object(PhenomAdapter, "_fetch_widgets",
                                  return_value=_widgets_payload([_ROW])) as widgets:
            payload = adapter.fetch("https://careers.dhl.com/api/jobs")
        widgets.assert_called_once_with("https://careers.dhl.com/widgets", "https://careers.dhl.com")
        self.assertEqual(json.loads(payload)["_mode"], "widgets")

    def test_empty_widgets_reraises_original_error(self):
        """回退也抓不到岗 → 上抛原始错误，别把真故障吞成静默 0 条。"""
        adapter = PhenomAdapter()
        original = RuntimeError("HTTP 500")
        phenom = __import__("adapters.phenom", fromlist=["x"])
        with mock.patch.object(PhenomAdapter, "_fetch_api_jobs",
                               side_effect=phenom._ApiJobsUnavailable(original)), \
                mock.patch.object(PhenomAdapter, "_fetch_widgets",
                                  return_value=_widgets_payload([])):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch("https://careers.dhl.com/api/jobs")
        self.assertIs(ctx.exception, original)

    def test_widgets_url_routes_directly(self):
        adapter = PhenomAdapter()
        with mock.patch.object(PhenomAdapter, "_fetch_api_jobs") as api, \
                mock.patch.object(PhenomAdapter, "_fetch_widgets",
                                  return_value=_widgets_payload([_ROW])):
            adapter.fetch("https://careers.dhl.com/widgets")
        api.assert_not_called()

    def test_api_jobs_error_after_first_page_is_not_swallowed(self):
        """抓到过数据之后的失败沿用旧行为：原样上抛记 failed，不许悄悄换路。"""
        adapter = PhenomAdapter()
        adapter.regions = ["CN"]
        pages = [
            _FakeResponse({"jobs": [{"data": {"slug": str(i), "title": "T",
                                              "country": "China", "description": "d" * 80}}
                                    for i in range(100)], "totalCount": 500}),
            _FakeResponse({}, status_code=500),
        ]
        with mock.patch("adapters.phenom.httpx.get", side_effect=pages), \
                mock.patch.object(PhenomAdapter, "_fetch_widgets") as widgets:
            with self.assertRaises(RuntimeError):
                adapter.fetch("https://careers.amd.com/api/jobs")
        widgets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
