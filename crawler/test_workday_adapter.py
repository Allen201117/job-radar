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


class _FakeWorkday:
    """按 2026-10-12 实测复刻 CXS 列表接口的三个行为（Target / Diageo 等 101 个源逐个真翻过）：
      · 一个查询最多给 cap 条：首页自报的 total 封顶在 cap；
      · offset 翻过末尾（或 >= cap）不回空页，回的是第一页；
      · facets 里每个取值的 count 受其它维度的过滤影响、不受本维度影响，且是准的。
    cap 真实值是 2000，这里缩小到 200 让用例跑得快（adapter 里的同名常量一起缩）。"""

    DIMS = ("Location_Country", "state", "jobFamilyGroup", "workerSubType")
    DESCRIPTORS = {"us": "United States of America", "sg": "Singapore"}

    def __init__(self, jobs, cap=200, dims=None, report_total=True):
        self.jobs = jobs
        self.cap = cap
        self.dims = dims if dims is not None else self.DIMS
        self.report_total = report_total
        self.bodies = []

    @staticmethod
    def _match(job, applied, skip=None):
        return all(job[p] in ids for p, ids in applied.items() if p != skip)

    def rows(self, applied, search=""):
        return [j for j in self.jobs if self._match(j, applied) and search.lower() in j["text"].lower()]

    def post(self, url, json=None, headers=None, timeout=None):
        body = json or {}
        self.bodies.append(body)
        applied = body.get("appliedFacets") or {}
        rows = self.rows(applied, body.get("searchText") or "")
        total = min(len(rows), self.cap)
        offset = body.get("offset", 0)
        if offset >= total:
            offset = 0
        payload = {"jobPostings": [{"title": j["title"], "externalPath": j["path"]}
                                   for j in rows[:self.cap][offset:offset + body.get("limit", 20)]]}
        if offset == 0:
            if self.report_total:
                payload["total"] = total
            payload["facets"] = []
            for dim in self.dims:
                counts = {}
                for j in self.jobs:
                    if self._match(j, applied, skip=dim):
                        counts[j[dim]] = counts.get(j[dim], 0) + 1
                payload["facets"].append({"facetParameter": dim, "values": [
                    {"id": v, "descriptor": self.DESCRIPTORS.get(v, v), "count": n} for v, n in counts.items()]})
        return _response(200, payload)

    def paged_bodies(self):
        return [b for b in self.bodies if b.get("limit") == 20]


def _word(i):
    """把序号写成字母：重复度刹车比的是去掉数字 / 括号之后的标题，带数字的标题在它眼里是同一个。"""
    out = ""
    while True:
        out = "abcdefghijklmnopqrstuvwxyz"[i % 26] + out
        i //= 26
        if not i:
            return out


def _job(i, state="mn", family="corp", sub="regular", title=None, country="us"):
    place = "USA" if country == "us" else "Singapore"
    return {"Location_Country": country, "state": state, "jobFamilyGroup": family, "workerSubType": sub,
            "title": title or f"Role {_word(i)}", "path": f"/job/{place}-{state.upper()}-City/Role_R{i}",
            "text": "United States"}


class _FakeWorkdayCase(unittest.TestCase):
    SOURCE_URL = "https://tenant.wd5.myworkdayjobs.com/wday/cxs/tenant/site/jobs"
    CAP = 200

    def _fetch(self, server, regions=("US",), env=None, adapter=None):
        adapter = adapter or WorkdayAdapter()
        adapter.regions = frozenset(regions)
        adapter.max_pages = self.CAP // 20
        with mock.patch("adapters.workday.httpx.post", side_effect=server.post), \
                mock.patch("adapters.workday.httpx.get", side_effect=RuntimeError("no detail in test")), \
                mock.patch("adapters.workday._QUERY_ROW_CAP", self.CAP), \
                mock.patch("adapters.workday._SPLIT_BLOCK_ROWS", self.CAP * 9 // 10), \
                mock.patch.dict("os.environ", {"CRAWL_REPEAT_STALL_ROWS": "40", **(env or {})}), \
                mock.patch("time.sleep"):
            html = adapter.fetch(self.SOURCE_URL)
        return adapter, {j.jd_url.rsplit("/job/", 1)[1] for j in adapter.parse(html)}

    @staticmethod
    def _paths(jobs):
        return {j["path"].split("/job/", 1)[1] for j in jobs}


class WorkdayWrapAroundTest(_FakeWorkdayCase):
    """翻过末尾时 Workday 回的是第一页，不是空页（2026-10-12 实测）。条数恰好是 20 的整数倍的查询因此
    永远等不到短页 / 空页：旧实现一路翻满 100 页、记「可能未抓全」，同一轮 101 个源里 11 个源 12 个查询
    中招，白翻 964 页（占全部列表请求的两成），而这 12 个查询一个岗都没少。"""

    def test_query_whose_size_is_a_multiple_of_page_size_stops_at_the_wrap(self):
        server = _FakeWorkday([_job(i) for i in range(40)])
        adapter, got = self._fetch(server)
        self.assertEqual(len(got), 40)
        self.assertTrue(adapter.fetch_complete)
        # 第 0、1 页 + 绕回第一页的那一次；候选组有两个（国家 / 无）也不该超过个位数
        self.assertLessEqual(len(server.paged_bodies()), 4)

    def test_wrap_is_detected_without_trusting_reported_total(self):
        # 自报 total 缺席时同样要停：判据是「这一页没有带来新岗」，不是 total
        server = _FakeWorkday([_job(i) for i in range(60)], report_total=False)
        adapter, got = self._fetch(server)
        self.assertEqual(len(got), 60)
        self.assertTrue(adapter.fetch_complete)
        self.assertLessEqual(len(server.paged_bodies()), 5)

    def test_text_fallback_stops_at_the_wrap_too(self):
        # 没有可用的地点 facet（trusted < 25）→ 走 searchText 兜底，同一个绕回行为
        server = _FakeWorkday([_job(i) for i in range(20)], dims=())
        adapter, got = self._fetch(server)
        self.assertEqual(len(got), 20)
        self.assertTrue(adapter.fetch_complete)
        self.assertLessEqual(len(server.paged_bodies()), 2 * 2)   # 'United States' / 'USA' 各两次


    def test_repeated_page_mid_listing_is_not_reported_complete(self):
        # 对方中途把同一页回了两次（缓存 / 抖动）：那一页没有新岗，但还没到它自报的末尾——
        # 不能当成收尾（后面 40 条照拿，旧实现也拿得到），少掉的那一页如实记没抓全
        server = _FakeWorkday([_job(i) for i in range(100)])
        orig_post = server.post

        def post(url, json=None, headers=None, timeout=None):
            body = dict(json or {})
            if body.get("offset") == 40:
                body["offset"] = 20
            return orig_post(url, json=body, headers=headers, timeout=timeout)

        server.post = post
        with self.assertLogs("adapters.workday", level="WARNING"):
            adapter, got = self._fetch(server)
        self.assertEqual(len(got), 80)
        self.assertFalse(adapter.fetch_complete)

    def test_non_dict_item_does_not_make_a_full_page_look_like_the_last_one(self):
        server = _FakeWorkday([_job(i) for i in range(40)])
        orig_post = server.post

        def post(url, json=None, headers=None, timeout=None):
            resp = orig_post(url, json=json, headers=headers, timeout=timeout)
            posts = resp.json.return_value["jobPostings"]
            if len(posts) == 20 and posts[0]["title"] == server.jobs[0]["title"]:
                posts[3] = None   # 第一页（含翻过末尾绕回来的那次）里夹一个坏项
            return resp

        server.post = post
        adapter, got = self._fetch(server)
        self.assertEqual(len(got), 39)   # 第一页 19 条 + 第二页 20 条；旧写法按「19 < 20」当成末页，只剩 19 条
        self.assertTrue(adapter.fetch_complete)

    def test_reused_instance_does_not_carry_the_previous_stop_reason(self):
        adapter = WorkdayAdapter()
        bulk, _hq = WorkdayCapSplitTest()._bulk()
        self._fetch(_FakeWorkday(bulk), adapter=adapter)
        self.assertEqual(adapter.coverage_stop_reason, "repetition_brake")
        adapter, got = self._fetch(_FakeWorkday([_job(i) for i in range(45)]), adapter=adapter)
        self.assertEqual(len(got), 45)
        self.assertIsNone(adapter.coverage_stop_reason)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(adapter.reported_total, 45)


class WorkdayCapSplitTest(_FakeWorkdayCase):
    """一个查询最多给 2000 条（用例里缩成 200）。国家级 facet 超过这个数时，旧实现只拿得到前 2000 条：
    Target 美国岗自报 14,072、每轮只见 2,008，库里另有 2,107 个仍在招的岗再也刷不到（2026-10-12）。"""

    def _diverse(self):
        # 1,000 个美国岗、标题各不相同：一个州 460（自己就超过上限，要再切一层），其余九个州各 60
        jobs, i = [], 0
        for n, state in [(460, "ca")] + [(60, f"s{k}") for k in range(9)]:
            for k in range(n):
                jobs.append(_job(i, state=state, sub=("regular", "seasonal", "intern")[k % 3]))
                i += 1
        return jobs

    def test_capped_country_query_is_split_until_every_block_fits(self):
        jobs = self._diverse()
        server = _FakeWorkday(jobs)
        adapter, got = self._fetch(server)
        self.assertEqual(got, self._paths(jobs))
        self.assertTrue(adapter.fetch_complete)
        self.assertIsNone(adapter.coverage_stop_reason)
        self.assertGreaterEqual(adapter.reported_total, len(jobs))
        # 请求量跟着岗位数走，不是成倍放大：1,000 条 = 50 页，再加每块的首页 / 收尾
        self.assertLess(len(server.paged_bodies()), 50 + 30)
        # 没有任何一块再去翻一个「装不下」的查询的后续页
        for body in server.paged_bodies():
            if body["offset"] > 0:
                self.assertLess(len(server.rows(body["appliedFacets"])), self.CAP)

    def test_split_blocks_never_exceed_the_facet_id_limit(self):
        # 1,000 个岗各在各的「州」：按条数一块能装 180 个取值，但单次 appliedFacets 最多 150 个 id
        jobs = [_job(i, state=f"u{i}") for i in range(1000)]
        server = _FakeWorkday(jobs, dims=("Location_Country", "state"))
        adapter, got = self._fetch(server)
        self.assertEqual(got, self._paths(jobs))
        self.assertTrue(adapter.fetch_complete)
        sizes = [len(b["appliedFacets"]["state"]) for b in server.bodies if "state" in (b.get("appliedFacets") or {})]
        self.assertEqual(max(sizes), 150)

    def test_query_that_fills_the_cap_without_reporting_total_is_split_too(self):
        # 首页不报 total 的租户：翻满上限才知道装不下，同样要切，而且切到底
        jobs = self._diverse()
        adapter, got = self._fetch(_FakeWorkday(jobs, report_total=False))
        self.assertEqual(got, self._paths(jobs))
        self.assertTrue(adapter.fetch_complete)

    def test_failed_block_keeps_the_rest_and_does_not_repage_parent_windows(self):
        # 切出来的某一块第一页就断连：别的块照收、如实记没抓全；中间层（加州）不为此再把自己的前 200 条翻一遍
        jobs = self._diverse()
        server = _FakeWorkday(jobs)
        orig_post = server.post

        def post(url, json=None, headers=None, timeout=None):
            applied = (json or {}).get("appliedFacets") or {}
            if applied.get("workerSubType") == ["seasonal"]:
                raise httpx.RemoteProtocolError("Server disconnected")
            return orig_post(url, json=json, headers=headers, timeout=timeout)

        server.post = post
        with self.assertLogs("adapters.workday", level="WARNING"):
            adapter, got = self._fetch(server)
        self.assertFalse(adapter.fetch_complete)
        lost = {j["path"].split("/job/", 1)[1] for j in jobs
                if j["state"] == "ca" and j["workerSubType"] == "seasonal"}
        self.assertFalse((self._paths(jobs) - lost) - got, "没出事的块一条都不能少")
        ca_window_pages = [b for b in server.bodies if b.get("offset", 0) > 0
                           and b["appliedFacets"] == {"Location_Country": ["us"], "state": ["ca"]}]
        self.assertEqual(ca_window_pages, [])

    def _with_sg(self, us_jobs, n=30, **kw):
        return us_jobs + [_job(9000 + i, state="sgx", country="sg", **kw) for i in range(n)]

    def test_shortfall_is_caught_below_a_multi_country_root_too(self):
        # 多个国家一起提交时，美国那一块是在第二层才单独切的：那里切完明显少于自报数，同样不许记抓全
        us = [_job(i, state=f"s{i % 20}") for i in range(1000)]
        for j in us:
            if j["state"] in ("s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7"):
                j["state"] = None
        jobs = self._with_sg(us)
        server = _FakeWorkday(jobs, dims=("Location_Country", "state"))
        orig_post = server.post

        def post(url, json=None, headers=None, timeout=None):
            resp = orig_post(url, json=json, headers=headers, timeout=timeout)
            for facet in resp.json.return_value.get("facets") or []:
                if facet["facetParameter"] == "state":
                    facet["values"] = [{**v, "count": v["count"] * 2} for v in facet["values"] if v["id"] is not None]
            return resp

        server.post = post
        with self.assertLogs("adapters.workday", level="WARNING"):
            adapter, got = self._fetch(server, regions=("US", "SG"))
        self.assertFalse(adapter.fetch_complete)
        self.assertFalse(self._paths(jobs[:self.CAP]) - got)

    def test_brake_on_the_bulk_country_does_not_drop_the_small_countries(self):
        # 美国那一块是门店批量发布、被刹车叫停；一起提交的新加坡只有 30 个岗（排在前 200 条之外、
        # 职类 / 用工类型与门店岗相同）——它是「已选维度里的小取值」，要单独翻全
        us, hq = self._bulk()
        jobs = self._with_sg(us, family="stores", sub="seasonal")
        adapter, got = self._fetch(_FakeWorkday(jobs), regions=("US", "SG"))
        self.assertEqual(adapter.coverage_stop_reason, "repetition_brake")
        self.assertFalse(self._paths(jobs[-30:]) - got, "新加坡的岗一条都不能少")
        self.assertFalse(self._paths(hq) - got)
        self.assertFalse(self._paths(jobs[:self.CAP]) - got)

    def _bulk(self):
        # 门店批量发布：1,140 个门店岗只有 3 种标题（括号里的店号各不相同）；60 个总部岗标题各不相同，
        # 成两簇夹在列表里——一簇在旧实现够得着的前 200 条之内，一簇在之外。
        stores = [_job(i, state=f"s{i % 12}", family="stores", sub="seasonal",
                       title=("Guest Advocate", "Starbucks Barista", "Inbound")[i % 3] + f" (T{i})")
                  for i in range(1140)]
        hq = [_job(5000 + i, state="s0", family=f"fam{i % 6}", sub="regular") for i in range(60)]
        return stores[:150] + hq[:30] + stores[150:1000] + hq[30:] + stores[1000:], hq

    def test_bulk_store_tenant_keeps_old_window_and_adds_minority_values_only(self):
        jobs, hq = self._bulk()
        server = _FakeWorkday(jobs)
        adapter, got = self._fetch(server)
        window = self._paths(jobs[:self.CAP])
        self.assertFalse(window - got, "改前拿得到的前 200 条，改后一条都不能少")
        self.assertFalse(self._paths(hq) - got, "装得进一个查询的小众取值（非门店职类）要翻全")
        # 同一个岗 × N 家门店不整包拉；刹车前试翻到的那几页门店岗也不留（下一轮未必还够得着）
        self.assertEqual(got, window | self._paths(hq))
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(adapter.coverage_stop_reason, "repetition_brake")
        self.assertEqual(adapter.reported_total, len(jobs))   # 分母如实记对方自报的数
        self.assertLess(len(server.paged_bodies()), 3 * (self.CAP // 20) + 20)

    def test_split_stops_at_the_per_source_list_cap(self):
        jobs = self._diverse()
        server = _FakeWorkday(jobs)
        adapter, got = self._fetch(server, env={"CRAWL_MAX_JOBS": "500"})
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(adapter.coverage_stop_reason, "list_cap")
        self.assertLess(len(got), len(jobs))
        self.assertFalse(self._paths(jobs[:self.CAP]) - got, "撞上限时原来够得着的那一窗也要在")

    def test_query_that_cannot_be_split_falls_back_to_the_old_window(self):
        # 响应里除了已选的国家维度没有别的 facet：切不动 → 退回原做法拿前 200 条，如实记没抓全
        jobs = self._diverse()
        server = _FakeWorkday(jobs, dims=("Location_Country",))
        adapter, got = self._fetch(server)
        self.assertEqual(got, self._paths(jobs[:self.CAP]))
        self.assertFalse(adapter.fetch_complete)

    def test_dimension_that_misses_jobs_is_not_trusted_as_a_partition(self):
        # 「州」这个维度只挂了一部分岗（真实例子：Target 带国家过滤时 locations 只露出 55 个叶子 766 个岗）：
        # 计数和盖不住这一块 → 不拿它当全集的切法；有别的盖得住的维度就用那个
        jobs = [_job(i, state=f"s{i % 20}", family=f"fam{i % 7}") for i in range(1000)]
        for j in jobs[::2]:
            j["state"] = None
        server = _FakeWorkday(jobs)
        orig_post = server.post

        def post(url, json=None, headers=None, timeout=None):
            resp = orig_post(url, json=json, headers=headers, timeout=timeout)
            payload = resp.json.return_value
            for facet in payload.get("facets") or []:
                facet["values"] = [v for v in facet["values"] if v["id"] is not None]
            return resp

        server.post = post
        adapter, got = self._fetch(server)
        self.assertEqual(got, self._paths(jobs))
        self.assertTrue(adapter.fetch_complete)
        self.assertFalse(any("state" in (b.get("appliedFacets") or {}) for b in server.bodies))


    def test_split_that_comes_up_short_of_the_declared_count_is_not_called_complete(self):
        # facet 计数不准的租户（这里：四成的岗没挂「州」，而州的计数被报成两倍，看上去盖得住）：
        # 每一块都能翻完，并集却只有自报数的六成 → 不许记抓全，原来够得着的前 200 条要补上
        jobs = [_job(i, state=f"s{i % 20}") for i in range(1000)]
        for j in jobs:
            if j["state"] in ("s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7"):
                j["state"] = None
        server = _FakeWorkday(jobs, dims=("Location_Country", "state"))
        orig_post = server.post

        def post(url, json=None, headers=None, timeout=None):
            resp = orig_post(url, json=json, headers=headers, timeout=timeout)
            for facet in resp.json.return_value.get("facets") or []:
                if facet["facetParameter"] == "state":
                    facet["values"] = [{**v, "count": v["count"] * 2} for v in facet["values"] if v["id"] is not None]
            return resp

        server.post = post
        with self.assertLogs("adapters.workday", level="WARNING"):
            adapter, got = self._fetch(server)
        self.assertFalse(adapter.fetch_complete)
        self.assertFalse(self._paths(jobs[:self.CAP]) - got)
        self.assertEqual(adapter.reported_total, len(jobs))


class WorkdayPackFacetIdsTest(unittest.TestCase):
    def test_bins_respect_row_capacity_and_id_limit(self):
        from adapters.workday import _FACET_ID_CHUNK, _pack_facet_ids
        pairs = [("big", 2155)] + [(f"v{i}", 7) for i in range(400)]
        bins = _pack_facet_ids(pairs, capacity=1800)
        self.assertEqual(bins[0], ["big"])   # 自己就超过上限的取值单独一块，留给下一层再切
        counts = dict(pairs)
        for b in bins[1:]:
            self.assertLessEqual(sum(counts[i] for i in b), 1800)
            self.assertLessEqual(len(b), _FACET_ID_CHUNK)
        self.assertEqual(sorted(i for b in bins for i in b), sorted(counts))   # 一个 id 都不丢


# ── 同一个帖子换了链接（2026-10-12）──────────────────────────────────────────────
# 例子都是当天库里 / 对方接口上的真实链接：空气产品把主地点从莆田改成晋江，路径的地点段跟着变，
# 两条链接打详情回的是同一个帖子（同一个 id，自报的当前链接是晋江那条）。
_AP = "https://airproducts.wd5.myworkdayjobs.com/en-US/AP0001/job"
_AP_OLD = f"{_AP}/Putian-Fujian/Distribution-Safety-Specialist_JR-2026-20603"
_AP_NEW = f"{_AP}/Jinjiang-CNMB-MUR/Distribution-Safety-Specialist_JR-2026-20603"
_SRC = "11111111-1111-1111-1111-111111111111"


class WorkdayPostingIdentityTest(unittest.TestCase):
    def test_location_segment_is_not_part_of_the_identity(self):
        self.assertIsNotNone(normalizer.posting_identity(_AP_OLD))
        self.assertEqual(normalizer.posting_identity(_AP_OLD), normalizer.posting_identity(_AP_NEW))

    def test_forms_without_location_segment_or_locale(self):
        # 对方没填地点时路径只有一段；腾讯自己的接口给的 Workday 链接不带 locale（库里 626 行）。
        ident = normalizer.posting_identity(_AP_NEW)
        self.assertEqual(normalizer.posting_identity(f"{_AP}/Distribution-Safety-Specialist_JR-2026-20603"), ident)
        self.assertEqual(
            normalizer.posting_identity(
                "https://airproducts.wd5.myworkdayjobs.com/AP0001/job/x/Distribution-Safety-Specialist_JR-2026-20603"),
            ident)
        self.assertEqual(
            normalizer.posting_identity(
                "https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Singapore/Game-Designer_R106214"),
            normalizer.posting_identity(
                "https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Game-Designer_R106214"))

    def test_host_and_site_case_do_not_matter(self):
        # 同一个站点 Visa / visa 两种写法都能开（迁移 225 壳牌那条影子源就是这么来的）。
        a = "https://visa.wd5.myworkdayjobs.com/en-US/Visa/job/Singapore/VP_REF075667W"
        b = "https://VISA.wd5.myworkdayjobs.com/en-US/visa/job/Singapore-Paya-Lebar-Green/VP_REF075667W"
        self.assertEqual(normalizer.posting_identity(a), normalizer.posting_identity(b))

    def test_query_and_trailing_slash_are_ignored(self):
        self.assertEqual(normalizer.posting_identity(_AP_NEW + "/?source=LinkedIn"),
                         normalizer.posting_identity(_AP_NEW))

    def test_same_requisition_number_is_not_enough(self):
        # 库里真有的两行：编号段都是「-1」，是两个帖子（详情回的帖子 id 不同）。按编号认会把它们并成一个。
        base = "https://x.wd3.myworkdayjobs.com/en-US/Careers/job/Shanghai-China"
        self.assertNotEqual(normalizer.posting_identity(f"{base}/Cost-Engineer_-1"),
                            normalizer.posting_identity(f"{base}/Buyer_-1"))
        # 同一个编号下的另一个帖子，对方在末尾加 -1 / -2 区分（详情里的 jobReqId 不带后缀）。
        hp = "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/job/Spring-Texas"
        self.assertNotEqual(normalizer.posting_identity(f"{hp}/Strategist_3159676-1"),
                            normalizer.posting_identity(f"{hp}/Strategist_3159676-2"))
        self.assertNotEqual(normalizer.posting_identity(f"{hp}/Strategist_3159676"),
                            normalizer.posting_identity(f"{hp}/Strategist_3159676-1"))

    def test_other_sites_of_the_same_tenant_are_other_postings(self):
        host = "https://x.wd3.myworkdayjobs.com/en-US"
        self.assertNotEqual(normalizer.posting_identity(f"{host}/Careers/job/A/T_R1"),
                            normalizer.posting_identity(f"{host}/Campus/job/A/T_R1"))

    def test_everything_else_has_no_identity(self):
        for url in (None, "", "   ",
                    "https://boards.greenhouse.io/acme/jobs/123",
                    "https://app.mokahr.com/social-recruitment/acme/1#/job/abc",
                    "https://airproducts.wd5.myworkdayjobs.com/en-US/AP0001",            # 列表页
                    "https://airproducts.wd5.myworkdayjobs.com/en-US/AP0001/details/x",  # 不是 /job/ 路由
                    f"{_AP}/a/b/Distribution-Safety-Specialist_JR-2026-20603",           # 两段地点：对方回 406
                    "https://evil.example/myworkdayjobs.com/en-US/S/job/A/T_R1"):
            self.assertIsNone(normalizer.posting_identity(url), url)


def _sib(row_id, url, first_seen, posted_at=None, source_id=_SRC):
    return {"id": row_id, "source_id": source_id, "canonical_jd_url": url,
            "first_seen_at": first_seen, "posted_at": posted_at}


_NOTHING = {"relink": {}, "retire": {}, "first_seen": {}}
_AP_MID = f"{_AP}/Xiamen/Distribution-Safety-Specialist_JR-2026-20603"


class WorkdayMovedPostingPlanTest(unittest.TestCase):
    def setUp(self):
        import jobs_db
        self.jobs_db = jobs_db
        self.item = (_AP_NEW, {"jd_url": _AP_NEW, "source_id": _SRC})

    def test_old_row_is_relinked_when_the_new_url_has_no_row(self):
        old = _sib("old", _AP_OLD, "2026-08-18")
        plan = self.jobs_db.plan_moved_postings([self.item], {}, [old])
        self.assertEqual(plan, {"relink": {_AP_NEW: old}, "retire": {}, "first_seen": {}})

    def test_earliest_row_survives_when_several_old_links_exist(self):
        # 地点改过两次：库里留着两条旧链接。最早那条顶上，另一条下架。
        plan = self.jobs_db.plan_moved_postings(
            [self.item], {}, [_sib("mid", _AP_MID, "2026-09-01"), _sib("old", _AP_OLD, "2026-08-18")])
        self.assertEqual(plan["relink"][_AP_NEW]["id"], "old")
        self.assertEqual(plan["retire"], {_AP_NEW: ["mid"]})

    def test_old_row_is_retired_when_the_new_url_already_has_a_row(self):
        # 存量就是这个形态：新链接早被当成新岗插过一行。旧行下架，最早的首见时间记到留下的那一行上。
        existing = {_AP_NEW: {"id": "new", "status": "active", "posted_at": None}}
        plan = self.jobs_db.plan_moved_postings([self.item], existing, [_sib("old", _AP_OLD, "2026-08-18")])
        self.assertEqual(plan, {"relink": {}, "retire": {_AP_NEW: ["old"]}, "first_seen": {_AP_NEW: "2026-08-18"}})

    def test_removed_row_at_the_new_url_counts_as_the_survivor(self):
        # 地点改回去：新链接上是之前下架的那一行，upsert 会把它复活；这时在招的另一条才是旧链接。
        existing = {_AP_NEW: {"id": "back", "status": "removed", "posted_at": None}}
        plan = self.jobs_db.plan_moved_postings([self.item], existing, [_sib("old", _AP_OLD, "2026-08-18")])
        self.assertEqual(plan["retire"], {_AP_NEW: ["old"]})

    def test_nothing_is_retired_when_the_new_url_row_is_expired(self):
        # expired 列表重抓不复活；这时再把旧行下架，这个帖子就一行在招的都没有了。
        existing = {_AP_NEW: {"id": "dead", "status": "expired", "posted_at": None}}
        plan = self.jobs_db.plan_moved_postings([self.item], existing, [_sib("old", _AP_OLD, "2026-08-18")])
        self.assertEqual(plan, _NOTHING)

    def test_a_link_still_in_this_batch_is_not_an_old_link(self):
        # 并集查询之间对方正好改了地点：同一个帖子这一轮出现了两个链接。分不出哪个是现在的，这轮不动。
        items = [self.item, (_AP_OLD, {"jd_url": _AP_OLD, "source_id": _SRC})]
        siblings = [_sib("old", _AP_OLD, "2026-08-18"), _sib("new", _AP_NEW, "2026-10-01")]
        existing = {_AP_OLD: {"id": "old", "status": "active"}, _AP_NEW: {"id": "new", "status": "active"}}
        self.assertEqual(self.jobs_db.plan_moved_postings(items, existing, siblings), _NOTHING)

    def test_two_links_in_the_batch_block_a_third_stale_one_too(self):
        items = [self.item, (_AP_OLD, {"jd_url": _AP_OLD, "source_id": _SRC})]
        plan = self.jobs_db.plan_moved_postings(items, {}, [_sib("third", _AP_MID, "2026-07-01")])
        self.assertEqual(plan, _NOTHING)

    def test_the_row_itself_is_not_its_own_old_link(self):
        existing = {_AP_NEW: {"id": "new", "status": "active"}}
        plan = self.jobs_db.plan_moved_postings([self.item], existing, [_sib("new", _AP_NEW, "2026-10-01")])
        self.assertEqual(plan, _NOTHING)

    def test_another_posting_of_the_same_requisition_is_left_alone(self):
        # 粗筛按末段取行，取回来的一定同末段；这里直接喂一条别的帖子，确认身份那道门自己也拦得住。
        other = _sib("other", f"{_AP}/Putian-Fujian/Distribution-Safety-Specialist_JR-2026-20603-1", "2026-08-18")
        self.assertEqual(self.jobs_db.plan_moved_postings([self.item], {}, [other]), _NOTHING)

    def test_same_path_on_another_host_is_not_the_same_posting(self):
        # 库里真有这种行：2026-06 那次 adapter 单例串台，把别家租户的 host 拼到了这条路径前面。
        other_host = _sib("ghost", _AP_OLD.replace("airproducts.wd5", "resmed.wd3"), "2026-06-17")
        self.assertEqual(self.jobs_db.plan_moved_postings([self.item], {}, [other_host]), _NOTHING)

    def test_rows_of_another_source_are_left_alone(self):
        foreign = _sib("foreign", _AP_OLD, "2026-08-18", source_id="22222222-2222-2222-2222-222222222222")
        self.assertEqual(self.jobs_db.plan_moved_postings([self.item], {}, [foreign]), _NOTHING)

    def test_mixed_source_batch_pairs_each_item_with_its_own_source(self):
        other_src = "22222222-2222-2222-2222-222222222222"
        other_new = "https://visa.wd5.myworkdayjobs.com/en-US/Visa/job/Singapore-Paya-Lebar-Green/VP_REF075667W"
        other_old = "https://visa.wd5.myworkdayjobs.com/en-US/Visa/job/Singapore-SingPost/VP_REF075667W"
        items = [self.item, (other_new, {"jd_url": other_new, "source_id": other_src})]
        siblings = [_sib("ap-old", _AP_OLD, "2026-08-18"), _sib("visa-old", other_old, "2026-06-30", source_id=other_src)]
        plan = self.jobs_db.plan_moved_postings(items, {}, siblings)
        self.assertEqual({c: r["id"] for c, r in plan["relink"].items()}, {_AP_NEW: "ap-old", other_new: "visa-old"})

    def test_items_without_a_link_or_a_source_are_ignored(self):
        items = [(None, {"jd_url": None, "source_id": _SRC}), ("", {"jd_url": "", "source_id": _SRC}),
                 (_AP_NEW, {"jd_url": _AP_NEW})]  # 最后一条没有 source_id
        self.assertEqual(self.jobs_db.plan_moved_postings(items, {}, [_sib("old", _AP_OLD, "2026-08-18")]), _NOTHING)

    def test_rows_without_first_seen_never_win_as_earliest(self):
        plan = self.jobs_db.plan_moved_postings(
            [self.item], {}, [_sib("blank", _AP_MID, None), _sib("old", _AP_OLD, "2026-08-18")])
        self.assertEqual(plan["relink"][_AP_NEW]["id"], "old")
        self.assertEqual(plan["retire"], {_AP_NEW: ["blank"]})

    def test_last_segment_prefilter_matches_what_the_identity_looks_at(self):
        # 粗筛（SQL 取末段）漏掉的行，身份函数再严也认不回来：两边对「末段」的理解必须一致。
        seg = "Distribution-Safety-Specialist_JR-2026-20603"
        for url in (_AP_NEW, _AP_NEW + "?source=LinkedIn", f"{_AP}/{seg}",
                    f"https://airproducts.wd5.myworkdayjobs.com/AP0001/job/x/{seg}"):
            self.assertEqual(self.jobs_db._posting_last_segment(normalizer.canonicalize_jd_url(url)), seg, url)


class _FakeCursor:
    """按 SQL 片段回预设结果、记下每一条语句；只够 upsert 这条链用。"""

    def __init__(self, by_canonical=(), siblings=(), fail_on=None, rowcount=1):
        self.by_canonical, self.siblings = list(by_canonical), list(siblings)
        self.fail_on, self.rowcount = fail_on, rowcount  # fail_on = (SQL 片段, 异常)
        self.executed = []
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.executed.append((sql, params))
        if self.fail_on and self.fail_on[0] in sql:
            raise self.fail_on[1]
        if "split_part" in sql:
            self._rows = self.siblings
        elif sql.startswith("select") and "canonical_jd_url" in sql:
            self._rows = self.by_canonical
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def statements(self, needle):
        return [(s, p) for s, p in self.executed if needle in s]

    def order(self, *needles):
        """各片段第一次出现的先后位置（没出现记 -1）。"""
        return [next((i for i, (s, _p) in enumerate(self.executed) if n in s), -1) for n in needles]


_RELINK = "update jobs set jd_url = %s where id = %s"
_RETIRE = "status = 'removed'"
_CARRY = "least(first_seen_at"


class WorkdayMovedPostingWriteTest(unittest.TestCase):
    """写库两条入口（批量 / 单条）都要走同一套旧链接处置。"""

    def setUp(self):
        import jobs_db
        self.jobs_db = jobs_db
        self.job = {"jd_url": _AP_NEW, "apply_url": _AP_NEW, "source_id": _SRC, "company": "空气产品",
                    "title": "Distribution Safety Specialist", "location": "Jinjiang"}
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(jobs_db, "_annotate_recruitment", return_value=None).start()  # 不起 node
        self.events = mock.patch.object(jobs_db, "record_job_events", return_value=0).start()
        self.batch = mock.patch.object(jobs_db.psycopg2.extras, "execute_batch").start()
        self.values = mock.patch.object(jobs_db.psycopg2.extras, "execute_values").start()
        # 整批 UPDATE / INSERT 走的是 psycopg2.extras，不经过 cursor.execute：手动记一笔，才比得出先后。
        self.batch.side_effect = lambda cur, sql, rows, **kw: cur.executed.append(("<<batch update>>", rows))
        self.values.side_effect = lambda cur, sql, rows, **kw: cur.executed.append(("<<batch insert>>", rows))

    def _conn(self, cur):
        conn = mock.Mock()
        conn.cursor = lambda *a, **k: cur
        return conn

    def _old(self):
        return ("old-id", _SRC, _AP_OLD, "2026-08-18", None)

    def test_batch_relinks_the_old_row_in_place_instead_of_inserting(self):
        cur = _FakeCursor(by_canonical=[], siblings=[self._old()])
        created, updated = self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)])
        self.assertEqual((created, updated), (0, 1))
        self.values.assert_not_called()  # 没有新插一行
        (sql, params), = cur.statements(_RELINK)
        self.assertEqual(params, (_AP_NEW, "old-id", _AP_OLD))
        self.assertIn("status = 'active' and canonical_jd_url = %s", sql)  # 行被别人动过就不换
        (_cur, _sql, rows), _kw = self.batch.call_args
        self.assertEqual(rows[0][-1], "old-id")  # 之后按既有行 UPDATE：id / first_seen_at / 用户操作都保住
        self.assertEqual(rows[0][self.jobs_db._UPDATE_COLS.index("jd_url")], _AP_NEW)
        self.assertEqual(cur.statements(_RETIRE), [])
        relink_at, write_at = cur.order(_RELINK, "<<batch update>>")
        self.assertLess(relink_at, write_at)

    def test_relinked_row_is_not_reported_as_a_new_job(self):
        cur = _FakeCursor(by_canonical=[], siblings=[self._old()])
        self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)])
        (_conn, events), _kw = self.events.call_args
        self.assertEqual(events, [])  # 没有 FIRST_SEEN：它不是新岗
        self.assertEqual(cur.statements("job_closures"), [])  # 也不去数「撤过的岗又被当新岗插入」

    def test_batch_retires_the_old_row_after_the_write_when_new_url_exists(self):
        cur = _FakeCursor(by_canonical=[("new-id", _AP_NEW, "active", None)],
                          siblings=[("new-id", _SRC, _AP_NEW, "2026-10-01", None), self._old()])
        created, updated = self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)])
        self.assertEqual((created, updated), (0, 1))
        (sql, params), = cur.statements(_RETIRE)
        self.assertEqual(params, (["old-id"],))
        self.assertIn("status = 'active'", sql)  # 只动在招行
        self.assertEqual(cur.statements(_CARRY)[0][1], ("2026-08-18", "new-id"))
        self.assertEqual(cur.statements(_RELINK), [])
        write_at, carry_at, retire_at = cur.order("<<batch update>>", _CARRY, _RETIRE)
        self.assertTrue(0 <= write_at < carry_at < retire_at, cur.executed)  # 先写、再记首见、最后下架

    def test_old_row_stays_when_the_batch_write_fails(self):
        cur = _FakeCursor(by_canonical=[("new-id", _AP_NEW, "active", None)], siblings=[self._old()])
        self.batch.side_effect = RuntimeError("connection lost")
        with self.assertRaises(RuntimeError):
            self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)])
        self.assertEqual(cur.statements(_RETIRE), [])

    def test_lookup_failure_only_warns_and_ingestion_goes_on(self):
        cur = _FakeCursor(by_canonical=[], siblings=[self._old()], fail_on=("split_part", RuntimeError("timeout")))
        created, updated = self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)])
        self.assertEqual((created, updated), (1, 0))  # 回到改之前：当新岗插入，下一轮再处置旧行
        self.assertEqual(cur.statements(_RELINK) + cur.statements(_RETIRE), [])

    def test_relink_that_hits_the_unique_index_falls_back_to_a_plain_insert(self):
        # 另一轮抓取抢先把新链接插进去了：这一个帖子退回当新岗插入（那条路自带撞键兜底），整批不受影响。
        boom = self.jobs_db.psycopg2.errors.UniqueViolation("jobs_canonical_jd_url_active_uniq")
        cur = _FakeCursor(by_canonical=[], siblings=[self._old(), ("mid-id", _SRC, _AP_MID, "2026-09-01", None)],
                          fail_on=(_RELINK, boom))
        created, updated = self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)])
        self.assertEqual((created, updated), (1, 0))
        self.assertEqual(cur.statements(_RETIRE), [])  # 没换成，这个帖子名下别的旧行也先不动

    def test_relink_is_skipped_when_the_old_row_changed_under_us(self):
        cur = _FakeCursor(by_canonical=[], siblings=[self._old()], rowcount=0)
        created, updated = self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)])
        self.assertEqual((created, updated), (1, 0))

    def test_retire_failure_only_warns(self):
        cur = _FakeCursor(by_canonical=[("new-id", _AP_NEW, "active", None)], siblings=[self._old()],
                          fail_on=(_RETIRE, RuntimeError("blip")))
        self.assertEqual(self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)]), (0, 1))
        self.events.assert_called_once()  # 事件照记，抓取不算失败

    def test_single_upsert_takes_the_same_path(self):
        cur = _FakeCursor(by_canonical=[], siblings=[self._old(), ("mid-id", _SRC, _AP_MID, "2026-09-01", None)])
        self.assertEqual(self.jobs_db.upsert_job(self._conn(cur), dict(self.job)), "updated")
        self.assertEqual(cur.statements(_RELINK)[0][1], (_AP_NEW, "old-id", _AP_OLD))
        full_updates = [p for s, p in cur.executed if s.startswith("update jobs set") and "last_seen_at" in s]
        self.assertEqual(full_updates[0][-1], "old-id")
        self.assertEqual(cur.statements("insert into jobs"), [])
        self.assertEqual(cur.statements(_RETIRE)[0][1], (["mid-id"],))  # 第二条旧链接行下架

    def test_single_upsert_asks_only_when_the_link_is_new(self):
        # 逐岗调用的入口：链接已有行就照常 UPDATE，不为每个岗多问一次库。
        cur = _FakeCursor(by_canonical=[("new-id", "active")], siblings=[self._old()])
        self.assertEqual(self.jobs_db.upsert_job(self._conn(cur), dict(self.job)), "updated")
        self.assertEqual(cur.statements("split_part") + cur.statements(_RETIRE), [])

    def test_batch_fallback_does_not_redo_the_move_per_row(self):
        # 整批 INSERT 撞键后逐行兜底：那时只看得见一条，分不出「这一轮同一个帖子给了两个链接」。
        self.values.side_effect = self.jobs_db.psycopg2.errors.UniqueViolation("dup")
        cur = _FakeCursor(by_canonical=[], siblings=[])
        with mock.patch.object(self.jobs_db, "upsert_job", return_value="created") as single:
            self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)])
        self.assertEqual(single.call_args.kwargs, {"moved_postings": False})

    def test_sources_without_posting_identity_cost_no_extra_query(self):
        job = dict(self.job, jd_url="https://boards.greenhouse.io/acme/jobs/1", apply_url=None)
        cur = _FakeCursor(by_canonical=[], siblings=[("x", _SRC, "y", None, None)])
        self.jobs_db.upsert_jobs_batch(self._conn(cur), [job])
        self.assertEqual(cur.statements("split_part"), [])
        self.values.assert_called_once()

    def test_sibling_lookup_is_scoped_to_active_rows_of_the_same_source(self):
        cur = _FakeCursor(by_canonical=[], siblings=[])
        self.jobs_db.upsert_jobs_batch(self._conn(cur), [dict(self.job)])
        (sql, params), = cur.statements("split_part")
        self.assertIn("status = 'active'", sql)
        self.assertIn("source_id = any(", sql)
        self.assertEqual(params, ([_SRC], ["Distribution-Safety-Specialist_JR-2026-20603"]))

    def test_relink_relies_on_the_normal_update_leaving_identity_columns_alone(self):
        # 原地换链接之后走既有行那条 UPDATE：它必须不动 id / first_seen_at，并把 apply_url 一起写成新的。
        self.assertIn("jd_url", self.jobs_db._UPDATE_COLS)
        self.assertIn("apply_url", self.jobs_db._UPDATE_COLS)
        self.assertNotIn("first_seen_at", self.jobs_db._UPDATE_COLS)
        self.assertNotIn("id", self.jobs_db._UPDATE_COLS)


if __name__ == "__main__":
    unittest.main()
