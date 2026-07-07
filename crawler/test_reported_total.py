import json
import unittest
from unittest.mock import patch

from adapters import china_ats
from adapters.antgroup import AntGroupAdapter
from adapters.china_ats import BeisenAdapter
from adapters.eightfold import EightfoldAdapter
from adapters.hotjob import HotJobAdapter
from adapters.meituan import MeituanAdapter
from adapters.netease import NeteaseAdapter
from adapters.wt import WtAdapter


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

    def test_hotjob_ignores_total_page_product_and_completes_on_short_page(self):
        pages = [
            {"data": {"pageForm": {"totalPage": 1, "pageData": [
                {"postId": "p1", "postName": "Role 1"}
            ]}}}
        ]
        adapter = HotJobAdapter()
        client = _FakeClient(posts=pages)

        with patch("adapters.hotjob.httpx.Client", return_value=client):
            with patch.object(adapter, "_enrich_details", return_value=None):
                adapter.fetch("https://wecruit.hotjob.cn/SU123/pb/social.html")

        self.assertEqual(adapter.reported_total, 1)
        self.assertTrue(adapter.fetch_complete)

    def test_hotjob_total_pages_prevents_short_page_from_early_completion(self):
        pages = [
            {"data": {"pageForm": {"totalPage": 4, "pageData": [
                {"postId": f"p1-{i}", "postName": f"Role 1-{i}"} for i in range(15)
            ]}}},
            {"data": {"pageForm": {"totalPage": 4, "pageData": [
                {"postId": f"p2-{i}", "postName": f"Role 2-{i}"} for i in range(20)
            ]}}},
            {"data": {"pageForm": {"totalPage": 4, "pageData": [
                {"postId": f"p3-{i}", "postName": f"Role 3-{i}"} for i in range(20)
            ]}}},
            {"data": {"pageForm": {"totalPage": 4, "pageData": [
                {"postId": f"p4-{i}", "postName": f"Role 4-{i}"} for i in range(18)
            ]}}},
        ]
        adapter = HotJobAdapter()
        client = _FakeClient(posts=pages)

        with patch("adapters.hotjob.httpx.Client", return_value=client):
            with patch.object(adapter, "_enrich_details", return_value=None):
                adapter.fetch("https://wecruit.hotjob.cn/SU123/pb/social.html")

        self.assertEqual(len(client.calls), 4)
        self.assertEqual(adapter.reported_total, 73)
        self.assertTrue(adapter.fetch_complete)

    def test_hotjob_unknown_total_stays_none_when_capped(self):
        pages = [
            {"data": {"pageForm": {"totalPage": 4, "pageData": [
                {"postId": f"p1-{i}", "postName": f"Role 1-{i}"} for i in range(20)
            ]}}},
            {"data": {"pageForm": {"totalPage": 4, "pageData": [
                {"postId": f"p2-{i}", "postName": f"Role 2-{i}"} for i in range(20)
            ]}}},
        ]
        adapter = HotJobAdapter()
        adapter.api_max_pages = 2
        client = _FakeClient(posts=pages)

        with patch("adapters.hotjob.httpx.Client", return_value=client):
            with patch.object(adapter, "_enrich_details", return_value=None):
                adapter.fetch("https://wecruit.hotjob.cn/SU123/pb/social.html")

        self.assertIsNone(adapter.reported_total)
        self.assertFalse(adapter.fetch_complete)

    def test_eightfold_keeps_multiple_positions_with_missing_ids(self):
        def fake_get(url, params=None, **kwargs):
            location = (params or {}).get("location")
            if location == "China":
                return _FakeResponse({
                    "total": 3,
                    "positions": [
                        {"id": None, "name": "Role A", "location": "China"},
                        {"id": None, "name": "Role B", "location": "China"},
                        {"id": "c", "name": "Role C", "location": "China"},
                    ],
                })
            return _FakeResponse({"total": 0, "positions": []})

        adapter = EightfoldAdapter()
        with patch("adapters.eightfold.httpx.get", side_effect=fake_get):
            with patch.object(adapter, "_enrich_descriptions", return_value=None):
                payload = adapter.fetch(
                    "https://acme.eightfold.ai/api/apply/v2/jobs?domain=acme.com"
                )

        self.assertEqual(len(json.loads(payload)["positions"]), 3)

    def test_wt_total_budget_stops_after_recruit_type_and_marks_incomplete(self):
        class _WtClient:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, url, params=None, **kwargs):
                rt = int((params or {}).get("recruitType"))
                page = int((params or {}).get("page"))
                rows = [
                    {"postId": f"{rt}-1", "postName": "Role 1"},
                    {"postId": f"{rt}-2", "postName": "Role 2"},
                ] if page == 1 else []
                return _FakeResponse({
                    "postList": rows,
                    "rowCount": 2,
                    "pageCount": 1,
                    "rowSize": 10,
                })

        adapter = WtAdapter()
        adapter._MAX_JOBS = 2
        client = _WtClient()
        with patch("adapters.wt.httpx.Client", return_value=client):
            payload = adapter.fetch("https://wanda.hotjob.cn/wt/wanda/web/index")

        self.assertEqual(len(json.loads(payload)["_intercepted"]), 1)
        self.assertEqual(adapter.reported_total, 2)
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
