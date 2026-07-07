import json
import unittest
from unittest.mock import patch

from adapters.jd import JdAdapter


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _row(idx):
    return {
        "requirementId": f"REQ-{idx}",
        "positionNameOpen": f"京东岗位 {idx}",
        "workCity": "北京市",
        "jobType": "研发类",
        "workContent": f"职责 {idx}",
        "qualification": f"要求 {idx}",
    }


class JdFetchTest(unittest.TestCase):
    def test_fetches_until_short_page_and_reports_fetched_total(self):
        pages = [[_row(i) for i in range(100)], [_row(100 + i) for i in range(46)]]
        calls = []

        def fake_post(url, **kwargs):
            data = kwargs["data"]
            page = int(data["pageIndex"])
            calls.append((page, data["pageSize"], data["workCityJson"], data["jobTypeJson"]))
            self.assertEqual(url, JdAdapter.API_URL)
            self.assertEqual(data["pageSize"], "100")
            self.assertEqual(data["workCityJson"], "[]")
            self.assertEqual(data["jobTypeJson"], "[]")
            self.assertEqual(data["jobSearch"], "")
            self.assertEqual(data["depTypeJson"], "[]")
            return _Response(pages[page - 1])

        adapter = JdAdapter()

        with patch("adapters.jd.httpx.post", side_effect=fake_post):
            payload = adapter.fetch("https://zhaopin.jd.com/web/job/job_info_list/3")

        jobs = adapter.parse(payload)
        self.assertEqual([call[0] for call in calls], [1, 2])
        self.assertEqual(len(jobs), 146)
        self.assertEqual(adapter.reported_total, 146)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(
            jobs[0].jd_url,
            "https://zhaopin.jd.com/web/job-info-detail?requementId=REQ-0",
        )
        self.assertIn("职责 0", jobs[0].summary)
        self.assertIn("要求 0", jobs[0].summary)

    def test_stops_on_short_page_before_clamped_duplicate_last_page(self):
        first_page = [_row(i) for i in range(100)]
        last_page = [_row(100 + i) for i in range(46)]
        calls = []

        def fake_post(url, **kwargs):
            page = int(kwargs["data"]["pageIndex"])
            calls.append(page)
            if page == 1:
                return _Response(first_page)
            if page == 2:
                return _Response(last_page)
            return _Response(last_page)

        adapter = JdAdapter()

        with patch("adapters.jd.httpx.post", side_effect=fake_post):
            payload = adapter.fetch("https://zhaopin.jd.com/web/job/job_info_list/3")

        jobs = adapter.parse(payload)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(len(jobs), 146)
        self.assertEqual(adapter.reported_total, 146)
        self.assertTrue(adapter.fetch_complete)


if __name__ == "__main__":
    unittest.main()
