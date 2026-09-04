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

    def test_xiaohongshu_overlapping_channels_do_not_fake_a_gap(self):
        """三个渠道互相重叠时，完整性必须逐渠道判，不能拿去重后条数比「各渠道 total 之和」。

        2026-09-04 实测：social 858 + campus 406 + intern 302 = 1,566，但 intern 那 302 个
        positionId **全部**已出现在 campus/social 里 → 去重后只有 1,263。旧写法
        `len(seen_ids) >= sum(totals)` 恒为 False，每轮都被记成「漏了 300 个岗」——
        分母重复相加造出来的假缺口，会让抓全率告警长期指着一个根本不存在的洞。
        """
        from adapters import xiaohongshu as xhs_mod

        def _page(total, ids):
            return {"data": {"total": total,
                             "list": [{"positionId": i, "name": f"岗{i}"} for i in ids]}}

        # social 2 条、campus 2 条、intern 2 条但 id 与 campus 完全重复 → 去重后只有 4 条
        posts = [_page(2, [1, 2]), _page(2, [3, 4]), _page(2, [3, 4])]
        adapter = xhs_mod.XiaohongshuAdapter()
        adapter.regions = ["CN"]
        with patch.object(xhs_mod.httpx, "Client", lambda **kw: _FakeClient(posts=posts)):
            raw = adapter.fetch("https://job.xiaohongshu.com/")

        collected = json.loads(raw)["_intercepted"]
        unique = sum(len(b["data"]["list"]) for b in collected)
        self.assertEqual(unique, 4, "跨渠道重复的岗不该重复入库")
        self.assertEqual(adapter.reported_total, 6, "分母仍如实记录各渠道自报之和")
        self.assertTrue(adapter.fetch_complete,
                        "三个渠道各自都抓到了自报总数 = 抓全；不能因为跨渠道去重就判成没抓全")

    def test_xiaohongshu_incomplete_channel_still_marks_not_complete(self):
        """反向断言：某个渠道没抓到自报总数时，必须诚实记「没抓全」。"""
        from adapters import xiaohongshu as xhs_mod

        def _page(total, ids):
            return {"data": {"total": total,
                             "list": [{"positionId": i, "name": f"岗{i}"} for i in ids]}}

        # campus 自报 99 但只回 1 条、下一页空 → 该渠道没抓全
        posts = [_page(1, [1]), _page(99, [2]), {"data": {"total": 99, "list": []}}, _page(1, [3])]
        adapter = xhs_mod.XiaohongshuAdapter()
        adapter.regions = ["CN"]
        with patch.object(xhs_mod.httpx, "Client", lambda **kw: _FakeClient(posts=posts)):
            adapter.fetch("https://job.xiaohongshu.com/")
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


class AmazonHitsCeilingTest(unittest.TestCase):
    """amazon.jobs 的 hits 封顶 10000 = 天花板不是总数，不许当分母。

    live 实测：offset=9900 还有数据、offset=10000 返 0 条，而 hits 恒为 10000。
    把它当分母 → 抓全率告警天天指着 7,000 个并不存在的岗，规则 G 永远消不掉。
    单查中国（CHN）时 hits=291，那是真总数，必须照常上报——否则连真缺口也看不见了。
    """

    def test_ceiling_hits_reported_as_unknown(self):
        from adapters.amazon import _reported_total_from_payload
        self.assertIsNone(_reported_total_from_payload({"hits": 10000}))
        self.assertIsNone(_reported_total_from_payload({"hits": 12345}))

    def test_real_total_below_ceiling_still_reported(self):
        from adapters.amazon import _reported_total_from_payload
        self.assertEqual(_reported_total_from_payload({"hits": 291}), 291)

    def test_missing_total_stays_none(self):
        from adapters.amazon import _reported_total_from_payload
        self.assertIsNone(_reported_total_from_payload({}))
