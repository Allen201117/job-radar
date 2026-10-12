import json
import unittest
from unittest import mock

import httpx

import normalizer
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


class WorkdayLocationSourceTest(unittest.TestCase):
    """地点用对方自己写的原文（locationsText），路径 slug 只当兜底（2026-10-12）。

    ❌ 此前一律从 externalPath 的地点段还原：slug 把空白换成连字符、把逗号等标点删掉，还原时只能把每个
       连字符都换成逗号。2026-10-11 香港库 54,099 个在招 workday 岗：10,657 个地点带空段（"US, , , California"）、
       4,683 个以门牌号开头（Target "1000, Nicollet, Mall, MinneapolisMN, 55403, 2542"）；
       「Hong, Kong」「New, York」「San, Jose」对不上城市筛选的 "hong kong" / "new york" / "san jose"，
       香港 546、纽约 2,198、圣何塞 837、旧金山 677 个岗筛不出来。
    用例里的 locationsText / externalPath 都是 2026-10-12 各租户列表接口的真实返回。
    """

    @staticmethod
    def _post(seg, text):
        return {"title": "T", "externalPath": f"/job/{seg}/T_1", "locationsText": text}

    def test_own_text_wins_over_the_path_slug(self):
        loc = WorkdayAdapter._post_location
        self.assertEqual(loc(self._post("New-York-NY-USA", "New York, NY, USA")), "New York, NY, USA")
        self.assertEqual(loc(self._post("Hong-Kong", "Hong Kong")), "Hong Kong")
        self.assertEqual(loc(self._post("Spring-Texas-United-States-of-America",
                                        "Spring, Texas, United States of America")),
                         "Spring, Texas, United States of America")
        # 逗号后面没空格的补上（Target "Fridley,MN"、马士基 "…America,Arizona,Mesa,85212"）
        self.assertEqual(loc(self._post("1090-73rd-Ave-NE-FridleyMN-55432-3407",
                                        "1090 73rd Ave NE, Fridley,MN 55432-3407")),
                         "1090 73rd Ave NE, Fridley, MN 55432-3407")

    def test_spaced_dash_is_a_level_separator(self):
        loc = WorkdayAdapter._post_location
        self.assertEqual(loc(self._post("US---Austin-TX", "US - Austin, TX")), "US, Austin, TX")
        self.assertEqual(loc(self._post("USA---California--Irvine", "USA - California – Irvine")),
                         "USA, California, Irvine")
        # 词内的连字符不是分隔
        self.assertEqual(loc(self._post("Mrfelden-Walldorf-Germany", "Mörfelden-Walldorf, Germany")),
                         "Mörfelden-Walldorf, Germany")

    def test_leading_country_code_still_resolves_after_dash_normalisation(self):
        # Visa "JM - Remote - Jamaica"：不把短横换成逗号，geo 的「开头国别码 + 逗号」就认不出，
        # 这个岗会按 source.regions 兜底判成国内。
        raw = WorkdayAdapter().parse(json.dumps({
            "_host": "https://visa.wd5.myworkdayjobs.com", "_site": "Visa",
            "trusted_posts": [self._post("JM---Remote---Jamaica", "JM - Remote - Jamaica")], "text_posts": [],
        }))[0]
        job = normalizer.normalize(raw, source_id="s", company="Visa", regions={"CN", "US", "SG", "Remote"})
        self.assertEqual((job["country_code"], job["job_scope"]), ("JM", "overseas"))

    def test_country_codes_are_expanded_in_own_text_too(self):
        loc = WorkdayAdapter._post_location
        self.assertEqual(loc(self._post("Xiamen-CHN", "Xiamen, CHN")), "Xiamen, China")
        self.assertEqual(loc(self._post("London-GBR", "London, GBR")), "London, United Kingdom")

    def test_multi_location_post_borrows_text_from_a_sibling_with_the_same_slug(self):
        posts = [
            self._post("3655-N-1st-St-San-Jose-CA-USA", "2 Locations"),
            self._post("3655-N-1st-St-San-Jose-CA-USA", "3655 N 1st St, San Jose, CA, USA"),
            self._post("Budapest-Hungary", "3 Locations"),       # 这一批里没有别的岗自报过这个地点
        ]
        WorkdayAdapter._fill_primary_locations(posts)
        loc = WorkdayAdapter._post_location
        self.assertEqual(loc(posts[0]), "3655 N 1st St, San Jose, CA, USA")
        self.assertEqual(loc(posts[1]), "3655 N 1st St, San Jose, CA, USA")
        self.assertEqual(loc(posts[2]), "Budapest, Hungary")     # 借不到 → 回到路径还原

    def test_sibling_choice_is_stable_when_spellings_differ(self):
        def posts(order):
            return [self._post("Fridley-MN", "2 Locations")] + [self._post("Fridley-MN", t) for t in order]
        a, b = posts(["Fridley,MN", "Fridley, MN"]), posts(["Fridley, MN", "Fridley,MN"])
        WorkdayAdapter._fill_primary_locations(a)
        WorkdayAdapter._fill_primary_locations(b)
        self.assertEqual(a[0]["_primary_location"], b[0]["_primary_location"])

    def test_malformed_posts_do_not_break_the_fill(self):
        # 列表里混进非对象 / 非字符串字段时，同文件其它步骤都是跳过，这里也不能把整源抓取炸掉
        ok = self._post("Austin-TX", "2 Locations")
        posts = [None, "junk", {"title": "T", "externalPath": None, "locationsText": 7}, ok,
                 self._post("Austin-TX", "Austin, TX")]
        WorkdayAdapter._fill_primary_locations(posts)
        self.assertEqual(ok["_primary_location"], "Austin, TX")
        self.assertEqual(WorkdayAdapter._post_location({"externalPath": "/job/Austin-TX/T_1", "locationsText": 7}), "7")

    def test_count_placeholder_never_becomes_the_location(self):
        self.assertEqual(WorkdayAdapter._post_location(self._post("China-Beijing", "2 Locations")), "China, Beijing")
        self.assertEqual(WorkdayAdapter._post_location(self._post("China-Beijing", "1 Location")), "China, Beijing")
        self.assertEqual(WorkdayAdapter._post_location(self._post("China-Beijing", "")), "China, Beijing")

    def test_store_address_ends_up_as_city_and_state(self):
        raw = WorkdayAdapter().parse(json.dumps({
            "_host": "https://target.wd5.myworkdayjobs.com", "_site": "targetcareers",
            "trusted_posts": [self._post("1000-Nicollet-Mall-MinneapolisMN-55403-2542",
                                         "1000 Nicollet Mall, Minneapolis,MN 55403-2542")],
            "text_posts": [],
        }))[0]
        job = normalizer.normalize(raw, source_id="s", company="Target Corporation", regions={"CN", "US"})
        self.assertEqual(job["location"], "Minneapolis, MN")
        self.assertEqual((job["country_code"], job["job_scope"]), ("US", "overseas"))

    def test_fetch_fills_primary_location_before_parse(self):
        # fetch 里问国家 / 按地区过滤与 parse 必须看到同一个地点：补主地点要在 fetch 里做完并随 payload 带出去。
        listing = [
            self._post("12100-Samsung-Blvd-Austin-TX-USA", "2 Locations"),
            {"title": "Other", "externalPath": "/job/12100-Samsung-Blvd-Austin-TX-USA/Other_2",
             "locationsText": "12100 Samsung Blvd, Austin, TX, USA"},
        ]

        def post_side_effect(url, json=None, headers=None, timeout=None):
            body = json or {}
            if body.get("limit") == 1:
                return _response(200, {"facets": [{"facetParameter": "locations", "values": [
                    {"id": "us", "descriptor": "United States of America"}]}]})
            if body.get("offset", 0) > 0 or body.get("searchText"):
                return _response(200, {"jobPostings": []})
            return _response(200, {"jobPostings": [dict(p) for p in listing]})

        adapter = WorkdayAdapter()
        adapter.regions = {"CN", "US"}
        with mock.patch.dict("os.environ", {"CRAWL_DETAIL_CAP": "0"}),                 mock.patch("adapters.workday.httpx.post", side_effect=post_side_effect),                 mock.patch("adapters.workday.httpx.get", side_effect=AssertionError("地点已说清，不该问 detail")),                 mock.patch("adapters.workday.time.sleep"):
            html = adapter.fetch("https://sec.wd3.myworkdayjobs.com/wday/cxs/sec/Samsung_Careers/jobs")
        self.assertEqual({j.location for j in adapter.parse(html)}, {"12100 Samsung Blvd, Austin, TX, USA"})


if __name__ == "__main__":
    unittest.main()
