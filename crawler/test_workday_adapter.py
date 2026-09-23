import json
import unittest
from unittest import mock

import httpx
from adapters.workday import WorkdayAdapter


class WorkdayAdapterUrlTest(unittest.TestCase):
    def test_public_jd_url_uses_locale_site_and_full_external_path(self):
        adapter = WorkdayAdapter()
        payload = {
            "_host": "https://workday.wd5.myworkdayjobs.com",
            "_site": "Workday",
            "trusted_posts": [
                {
                    "title": "Senior Cybersecurity Data Engineer",
                    "externalPath": "/job/Hong-Kong/Senior-Cybersecurity-Data-Engineer_JR-0107814",
                    "locationsText": "Hong Kong",
                }
            ],
            "text_posts": [],
        }

        jobs = adapter.parse(json.dumps(payload))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(
            jobs[0].jd_url,
            "https://workday.wd5.myworkdayjobs.com/en-US/Workday/job/Hong-Kong/Senior-Cybersecurity-Data-Engineer_JR-0107814",
        )
        self.assertEqual(jobs[0].apply_url, jobs[0].jd_url)


def _response(status_code, payload=None, retry_after=None):
    response = mock.Mock(status_code=status_code, headers={})
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    response.json.return_value = payload or {"facets": []}
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "rate limited", request=mock.Mock(), response=response,
        )
    return response


class WorkdayAdapterRateLimitTest(unittest.TestCase):
    SOURCE_URL = "https://tenant.wd5.myworkdayjobs.com/wday/cxs/tenant/site/jobs"

    def test_retries_once_after_429_and_uses_second_response(self):
        adapter = WorkdayAdapter()
        with mock.patch("adapters.workday.httpx.post", side_effect=[
            _response(429, retry_after="2"), _response(200),
        ]) as post, \
                mock.patch("time.sleep") as sleep, \
                mock.patch("adapters.workday._search_texts_for_regions", return_value=()):
            adapter.fetch(self.SOURCE_URL)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_raises_when_single_retry_is_also_rate_limited(self):
        adapter = WorkdayAdapter()
        with mock.patch("adapters.workday.httpx.post", side_effect=[
            _response(429), _response(429),
        ]) as post, \
                mock.patch("time.sleep") as sleep:
            with self.assertRaises(httpx.HTTPStatusError):
                adapter.fetch(self.SOURCE_URL)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(5)


class WorkdayAdapterFacetChunkTest(unittest.TestCase):
    """400/500 根因（2026-09-14~18 ThermoFisher/Mondelez 连续 failed 实锤）：appliedFacets[param]
    塞太多 id 会被租户后端拒绝（ThermoFisher 300 个 400 / Mondelez 904 个 500，单 id 恒 200）。
    fetch() 必须把大 id 列表分块提交、按块翻页并集，不能一次性把整组 id 塞进一次请求。"""

    SOURCE_URL = "https://tenant.wd5.myworkdayjobs.com/wday/cxs/tenant/site/jobs"

    def test_large_facet_group_is_chunked_and_still_succeeds(self):
        ids = [f"id-{i}" for i in range(300)]  # 超过单次上限的一组 id

        def post_side_effect(url, json=None, headers=None, timeout=None):
            body = json or {}
            applied = body.get("appliedFacets") or {}
            if not applied:
                return _response(200, {"facets": []})
            chunk = applied.get("locations", [])
            if len(chunk) > 150:
                # 复刻真实租户对超大 appliedFacets 的拒绝
                return _response(400, {"error": "too many facet values"})
            if body.get("offset", 0) == 0:
                return _response(200, {"jobPostings": [
                    {"title": f"Role {chunk[0]}", "externalPath": f"/job/China-Beijing/Role_{chunk[0]}"},
                ]})
            return _response(200, {"jobPostings": []})

        adapter = WorkdayAdapter()
        with mock.patch.object(
            WorkdayAdapter, "_facet_candidates_for_regions", return_value={"locations": ids},
        ), mock.patch("adapters.workday.httpx.post", side_effect=post_side_effect) as post, \
                mock.patch("adapters.workday._search_texts_for_regions", return_value=()):
            html = adapter.fetch(self.SOURCE_URL)

        jobs = adapter.parse(html)
        # 300 个 id 按 150 一块 = 2 块，每块各拿到 1 条（示例数据），去重后应有 2 条，且没有异常上抛。
        self.assertEqual(len(jobs), 2)
        applied_calls = [
            c.kwargs["json"]["appliedFacets"].get("locations", [])
            for c in post.call_args_list
            if c.kwargs.get("json", {}).get("appliedFacets")
        ]
        self.assertTrue(applied_calls, "应至少有一次带 appliedFacets 的请求")
        self.assertTrue(all(len(c) <= 150 for c in applied_calls), "任何单次请求的 id 数不得超过分块上限")


def _location_facets(values, extra=None):
    """Workday facets 的真实形状：locationMainGroup 下挂 locations 叶子。"""
    groups = [{"facetParameter": "locationMainGroup", "values": [
        {"facetParameter": "locations", "descriptor": "Locations", "values": [
            {"id": f"id-{i}", "descriptor": d, "count": 1} for i, d in enumerate(values)
        ]},
    ]}]
    return groups + (extra or [])


class WorkdayLooseUsFacetTest(unittest.TestCase):
    """城市级 US 叶子（2026-09-23 实测 98 个 US workday 源里 22 个靠它补美国岗；
    Micron/阿斯利康 原本各只抓到 1 个、Nike 0 个）。字面关键词认不出，交给 geo 认。"""

    REGIONS = {"CN", "US", "SG", "Remote"}

    def test_city_level_us_leaves_are_picked_up(self):
        facets = _location_facets([
            "San Francisco, CA, US",   # Postman：州缩写 + 结尾 US
            "US, Oregon, Hillsboro",   # Intel：US 在开头
            "Beaverton, Oregon",       # Nike：不带国家，只有州全称
            "Boise, ID - Main Site",   # Micron：州缩写 + 厂区后缀
        ])
        got = WorkdayAdapter._loose_us_facet_candidates(facets, self.REGIONS)
        self.assertEqual(got, {"locations": ["id-0", "id-1", "id-2", "id-3"]})

    def test_non_us_and_already_matched_leaves_are_left_alone(self):
        facets = _location_facets([
            "Bangalore, India", "Montreal, QC, ca", "Tbilisi, Georgia", "London, Ontario",
            "Taiwan, Taipei", "Shanghai, China Mainland",
            "Remote - United States",  # 字面关键词已认出 → 走原 trusted 通道，不重复进宽松通道
        ])
        self.assertEqual(WorkdayAdapter._loose_us_facet_candidates(facets, self.REGIONS), {})

    def test_regions_without_us_get_nothing(self):
        facets = _location_facets(["Beaverton, Oregon"])
        self.assertEqual(WorkdayAdapter._loose_us_facet_candidates(facets, {"CN"}), {})

    def test_non_location_param_is_ignored(self):
        facets = [{"facetParameter": "jobFamilyGroup", "values": [
            {"id": "jf", "descriptor": "New York Sales"},
        ]}]
        self.assertEqual(WorkdayAdapter._loose_us_facet_candidates(facets, self.REGIONS), {})

    def test_country_level_us_facet_disables_loose_channel(self):
        # 有国家级聚合项 = 一次就能拿全美国岗，宽松通道只会白加请求（68 源实测抓到/自报 ≈1.00）
        country = [{"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locationCountry", "descriptor": "Location Country", "values": [
                {"id": "us-country", "descriptor": "United States of America", "count": 500},
            ]},
        ]}]
        facets = _location_facets(["Beaverton, Oregon"], extra=country)
        self.assertTrue(WorkdayAdapter._has_us_country_facet(facets))
        self.assertEqual(WorkdayAdapter._loose_us_facet_candidates(facets, self.REGIONS), {})

    def test_country_named_leaf_under_locations_is_not_country_level(self):
        # 罗氏：locations 下有个叫「United States of America」的叶子，只挂 4 个岗，不是国家聚合
        facets = _location_facets(["United States of America", "South San Francisco, California"])
        self.assertFalse(WorkdayAdapter._has_us_country_facet(facets))
        self.assertEqual(
            WorkdayAdapter._loose_us_facet_candidates(facets, self.REGIONS), {"locations": ["id-1"]},
        )


class WorkdayLooseUsFetchTest(unittest.TestCase):
    SOURCE_URL = "https://tenant.wd5.myworkdayjobs.com/wday/cxs/tenant/site/jobs"

    def _run(self, cn_count, us_leaf_error=None):
        facets = _location_facets(
            [f"Shanghai {i}, China" for i in range(cn_count)] + ["Austin, TX, US"],
        )
        us_leaf = f"id-{cn_count}"
        searched = []

        def post_side_effect(url, json=None, headers=None, timeout=None):
            body = json or {}
            applied = (body.get("appliedFacets") or {}).get("locations")
            if body.get("limit") == 1:
                return _response(200, {"facets": facets})
            if body.get("offset", 0) > 0:
                return _response(200, {"jobPostings": []})
            if body.get("searchText"):
                searched.append(body["searchText"])
                return _response(200, {"jobPostings": []})
            if applied == [us_leaf] and us_leaf_error is not None:
                raise us_leaf_error
            if applied == [us_leaf]:
                # 叶子是 geo 猜的：同一个 facet 里混进一个非美国岗，必须被逐岗过滤掉
                return _response(200, {"jobPostings": [
                    {"title": "US Role", "externalPath": "/job/Austin-TX-US/US-Role_1"},
                    {"title": "Leak Role", "externalPath": "/job/Bangalore-India/Leak-Role_2"},
                ]})
            return _response(200, {"jobPostings": [
                {"title": f"CN Role {i}", "externalPath": f"/job/China-Shanghai/CN-Role_{i}"}
                for i in range(len(applied or []))
            ]})

        adapter = WorkdayAdapter()
        adapter.regions = frozenset({"CN", "US", "SG", "Remote"})
        with mock.patch("adapters.workday.httpx.post", side_effect=post_side_effect), \
                mock.patch("adapters.workday.httpx.get", side_effect=RuntimeError("no detail in test")):
            html = adapter.fetch(self.SOURCE_URL)
        data = json.loads(html)
        self.adapter = adapter
        return adapter.parse(html), data, searched

    def test_loose_pass_failure_keeps_trusted_posts_and_marks_incomplete(self):
        # 补充召回断连不许把整源扔掉：在华岗照交，fetch_complete 如实记 False
        with self.assertLogs("adapters.workday", level="WARNING"):
            jobs, _, _ = self._run(
                cn_count=30, us_leaf_error=httpx.RemoteProtocolError("Server disconnected"),
            )
        self.assertEqual(sum(1 for j in jobs if j.title.startswith("CN Role")), 30)
        self.assertFalse(self.adapter.fetch_complete)

    def test_loose_posts_are_filtered_per_job_not_trusted(self):
        jobs, data, _ = self._run(cn_count=30)
        titles = {j.title for j in jobs}
        self.assertIn("US Role", titles)
        self.assertNotIn("Leak Role", titles)
        self.assertNotIn("US Role", {p["title"] for p in data["trusted_posts"]})

    def test_text_fallback_threshold_counts_trusted_only(self):
        # trusted（在华）只有 3 个 < 25：原来会跑文本兜底，加了宽松通道之后必须照旧跑
        _, _, searched = self._run(cn_count=3)
        self.assertIn("United States", searched)


if __name__ == "__main__":
    unittest.main()
