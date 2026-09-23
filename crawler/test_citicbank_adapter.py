import json
import unittest
from unittest import mock

import normalizer
from adapters.base import PageResult
from adapters.citicbank import CiticbankAdapter

DETAIL_HTML = """<html><body><div>分享职位 分享到QQ 收藏职位</div>
<h1>金融市场及同业部产品经理岗(A005309)</h1><p>山东济南市 | 本科及以上 | 全职 | 发布时间： 2026-09-23</p>
<h3>岗位职责</h3><p>1、负责债券业务的市场研究。</p><h3>任职资格</h3><p>1、本科及以上学历。</p>
<div>× 请扫描二维码后点击右上角分享 ×</div><div>提示 您暂时还没有简历，是否去新增?</div>
<script>var x = "岗位职责不该出现在这";</script></body></html>"""


def _row(**over):
    row = {"ID": 5863, "POSTNAME": "金融市场及同业部产品经理岗", "RELEASENAME": "金融市场及同业部产品经理岗(A005309)",
           "CONTENT": "济南分行", "WORKADDR": "山东济南市", "FBZWDATE": "2026-09-23",
           "_detail_body": "岗位职责 1、负责债券业务的市场研究。任职资格 1、本科及以上学历。"}
    row.update(over)
    return row


class CiticbankAdapterTest(unittest.TestCase):
    def test_channel_follows_source_url(self):
        # campus 那条源必须打校招渠道 02，否则两条源抓的是同一批社招岗。
        self.assertEqual(CiticbankAdapter._type_code("https://job.citicbank.com/#/campus"), "02")
        self.assertEqual(CiticbankAdapter._type_code("https://job.citicbank.com/#/social"), "01")

    def test_parse_builds_static_detail_url_and_passes_quality_gate(self):
        jobs = CiticbankAdapter().parse(json.dumps({"type_code": "01", "jobs": [_row()]}, ensure_ascii=False))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.jd_url, "https://job.citicbank.com/static/positionDetail_5863_01.html")
        # 几十个分行都叫「客户经理类」，机构名必须进标题才分得开。
        self.assertEqual(job.title, "金融市场及同业部产品经理岗（济南分行）")
        self.assertEqual((job.location, job.job_type, job.posted_at), ("山东济南市", "社招", "2026-09-23"))
        self.assertTrue(normalizer.validate_job_quality(job, "https://job.citicbank.com/#/social")[0])

    def test_campus_rows_keep_campus_type_code_in_detail_url(self):
        jobs = CiticbankAdapter().parse(json.dumps({"type_code": "02", "jobs": [_row(ID=5781)]}, ensure_ascii=False))
        self.assertEqual(jobs[0].jd_url, "https://job.citicbank.com/static/positionDetail_5781_02.html")
        self.assertEqual(jobs[0].job_type, "校招")

    def test_org_already_in_post_name_is_not_duplicated(self):
        jobs = CiticbankAdapter().parse(json.dumps(
            {"type_code": "01", "jobs": [_row(POSTNAME="济南分行柜员", CONTENT="济南分行")]}, ensure_ascii=False))
        self.assertEqual(jobs[0].title, "济南分行柜员")

    def test_detail_body_cuts_between_section_header_and_popups(self):
        body = CiticbankAdapter._detail_body(DETAIL_HTML)
        self.assertTrue(body.startswith("岗位职责"))
        self.assertIn("任职资格", body)
        self.assertNotIn("请扫描二维码", body)
        self.assertNotIn("不该出现", body)

    def test_detail_body_empty_when_page_has_no_sections(self):
        self.assertEqual(CiticbankAdapter._detail_body("<html><body>系统错误，请联系管理员</body></html>"), "")

    def test_empty_campus_batch_is_not_a_failure_but_empty_list_with_total_is(self):
        a = CiticbankAdapter()
        with mock.patch("adapters.citicbank.paginate_all", return_value=([], 0, True)), \
             mock.patch("adapters.citicbank.resolve_detail_cap", return_value=0):
            self.assertEqual(json.loads(a.fetch("https://job.citicbank.com/#/campus"))["jobs"], [])
        with mock.patch("adapters.citicbank.paginate_all", return_value=([], 752, False)), \
             mock.patch("adapters.citicbank.resolve_detail_cap", return_value=0):
            with self.assertRaises(RuntimeError):
                a.fetch("https://job.citicbank.com/#/social")

    def test_page_count_is_total_rows_not_total_pages(self):
        # 接口顶层 pageCount 实为总条数（社招 751 = 51 页）；当成总页数会翻 751 页。
        a = CiticbankAdapter()
        captured = {}

        def fake_paginate(fetch_page, **kwargs):
            captured["result"] = fetch_page(1)
            return [], 0, True

        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"IsSuc": True, "pageCount": 751,
                                      "tableData": {"rows": [{"itemMap": _row()}]}}
        client = mock.MagicMock()
        client.__enter__.return_value.post.return_value = response
        with mock.patch("adapters.citicbank.httpx.Client", return_value=client), \
             mock.patch("adapters.citicbank.paginate_all", side_effect=fake_paginate), \
             mock.patch("adapters.citicbank.resolve_detail_cap", return_value=0):
            a.fetch("https://job.citicbank.com/#/social")
        result = captured["result"]
        self.assertIsInstance(result, PageResult)
        self.assertEqual((result.total, result.total_pages, len(result.items)), (751, None, 1))


if __name__ == "__main__":
    unittest.main()
