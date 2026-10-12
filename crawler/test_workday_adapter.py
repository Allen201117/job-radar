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
