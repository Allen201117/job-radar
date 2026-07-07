import json
import unittest
from unittest.mock import patch

from adapters import china_ats
from adapters.antgroup import AntGroupAdapter
from adapters.china_ats import BeisenAdapter
from adapters.hotjob import HotJobAdapter
from adapters.meituan import MeituanAdapter
from adapters.netease import NeteaseAdapter


class _FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload if payload is not None else {}
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, posts=None, gets=None):
        self._posts = list(posts or [])
        self._gets = list(gets or [])
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if not self._posts:
            raise AssertionError(f"unexpected POST {url}")
        return _FakeResponse(self._posts.pop(0))

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if self._gets:
            return _FakeResponse(self._gets.pop(0))
        return _FakeResponse(text="")


class ReportedTotalTest(unittest.TestCase):
    def test_meituan_reports_total_from_page_metadata_and_marks_complete(self):
        client = _FakeClient(posts=[
            {"data": {"page": {"totalCount": 3}, "list": [{"jobUnionId": "1"}, {"jobUnionId": "2"}]}},
            {"data": {"page": {"totalCount": 3}, "list": [{"jobUnionId": "3"}]}},
        ])
        adapter = MeituanAdapter()
        adapter.PAGE_SIZE = 2

        with patch("adapters.meituan.httpx.Client", return_value=client):
            payload = adapter.fetch("https://zhaopin.meituan.com/web/position")

        self.assertEqual(len(json.loads(payload)["data"]["list"]), 3)
        self.assertEqual(adapter.reported_total, 3)
        self.assertTrue(adapter.fetch_complete)

    def test_netease_reports_data_total_when_max_pages_stops_short(self):
        client = _FakeClient(posts=[
            {"data": {"total": 5, "pages": 3, "list": [{"id": "1"}, {"id": "2"}]}},
            {"data": {"total": 5, "pages": 3, "list": [{"id": "3"}, {"id": "4"}]}},
        ])
        adapter = NeteaseAdapter()
        adapter._PAGE_SIZE = 2
        adapter._MAX_PAGES = 2

        with patch("adapters.netease.httpx.Client", return_value=client):
            adapter.fetch("https://hr.163.com/job-list.html")

        self.assertEqual(adapter.reported_total, 5)
        self.assertFalse(adapter.fetch_complete)

    def test_antgroup_sums_social_and_campus_totals(self):
        client = _FakeClient(posts=[
            {"totalCount": 2, "content": [{"id": "s1"}]},
            {"totalCount": 2, "content": [{"id": "s2"}]},
            {"totalCount": 1, "content": [{"id": "c1"}]},
        ])
        adapter = AntGroupAdapter()
        adapter.PAGE_SIZE = 1

        with patch("adapters.antgroup.httpx.Client", return_value=client):
            payload = adapter.fetch("https://talent.antgroup.com/")

        data = json.loads(payload)
        self.assertEqual(len(data["social"]), 2)
        self.assertEqual(len(data["campus"]), 1)
        self.assertEqual(adapter.reported_total, 3)
        self.assertTrue(adapter.fetch_complete)

    def test_hotjob_reports_total_page_times_page_size_and_exposes_cap(self):
        pages = [
            {"data": {"pageForm": {"totalPage": 12, "pageData": [
                {"postId": f"p{i}", "postName": f"Role {i}"}
            ]}}}
            for i in range(10)
        ]
        adapter = HotJobAdapter()
        client = _FakeClient(posts=pages)

        with patch("adapters.hotjob.httpx.Client", return_value=client):
            with patch.object(adapter, "_enrich_details", return_value=None):
                adapter.fetch("https://wecruit.hotjob.cn/SU123/pb/social.html")

        self.assertEqual(adapter.reported_total, 240)
        self.assertFalse(adapter.fetch_complete)

    def test_beisen_keeps_existing_complete_logic_and_reports_count(self):
        host = "group.zhiye.com"
        sentinel = object()
        old_route = china_ats._BEISEN_ROUTE_CACHE.get(host, sentinel)
        china_ats._BEISEN_ROUTE_CACHE[host] = "https://group.zhiye.com/custom/zwxq"
        try:
            client = _FakeClient(
                gets=[None],
                posts=[
                    {"Count": 2, "Data": [{"Id": "a", "JobAdName": "Role A"}]},
                    {"Count": 2, "Data": [{"Id": "b", "JobAdName": "Role B"}]},
                ],
            )
            adapter = BeisenAdapter()
            adapter._PAGE_SIZE = 1

            with patch("adapters.china_ats.httpx.Client", return_value=client):
                adapter.fetch("https://group.zhiye.com/social")

            self.assertEqual(adapter.reported_total, 2)
            self.assertTrue(adapter.fetch_complete)
        finally:
            if old_route is sentinel:
                china_ats._BEISEN_ROUTE_CACHE.pop(host, None)
            else:
                china_ats._BEISEN_ROUTE_CACHE[host] = old_route


if __name__ == "__main__":
    unittest.main()
