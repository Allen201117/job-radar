import json
import unittest

from adapters.sf_express import SfExpressAdapter, _page_numbers


class SfExpressAdapterTest(unittest.TestCase):
    def test_page_numbers_cover_live_total_with_safety_cap(self):
        self.assertEqual(_page_numbers(total_pages=215, max_pages=500)[:3], [1, 2, 3])
        self.assertEqual(_page_numbers(total_pages=215, max_pages=500)[-1], 215)
        self.assertEqual(_page_numbers(total_pages=800, max_pages=500)[-1], 500)

    def test_fetch_page_retries_transient_empty_page(self):
        class FakeResponse:
            def __init__(self, rows):
                self._rows = rows

            def raise_for_status(self):
                return None

            def json(self):
                return {"JobSearchList": {"listObj": self._rows}}

        class FakeClient:
            def __init__(self):
                self.calls = 0

            def post(self, url, json):
                self.calls += 1
                rows = [] if self.calls == 1 else [{"id": n} for n in range(10)]
                return FakeResponse(rows)

        adapter = SfExpressAdapter()
        adapter.PAGE_RETRY_DELAY = 0
        client = FakeClient()

        data = adapter._fetch_page(client, page_number=3, expected_rows=10)

        self.assertEqual(client.calls, 2)
        self.assertEqual(len(data["listObj"]), 10)

    def test_parse_maps_official_social_job_to_detail_url(self):
        payload = {
            "jobs": [{
                "id": 70774,
                "outName": "政企政务行业客户经理",
                "positionType": 3,
                "publishTime": "2026-06-18 23:57:08",
                "mainDuty": "负责行业客户开发与供应链解决方案。",
                "positionReq": "本科及以上学历，5年以上相关经验。",
                "workAddress": "北京市",
                "educationReqTxt": "大学本科",
                "workYearTxt": "5-10年",
                "salaryRangeTxt": "面议",
            }]
        }

        jobs = SfExpressAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "顺丰")
        self.assertEqual(jobs[0].location, "北京市")
        self.assertIn("供应链解决方案", jobs[0].summary)
        self.assertEqual(
            jobs[0].jd_url,
            "https://hr.sf-express.com/JobSearchById/70774,3",
        )

    def test_parse_excludes_taiwan_job(self):
        payload = {
            "jobs": [{
                "id": 1,
                "outName": "运营经理",
                "positionType": 3,
                "workAddress": "台湾省-台北市",
            }]
        }

        self.assertEqual(SfExpressAdapter().parse(json.dumps(payload)), [])


if __name__ == "__main__":
    unittest.main()
