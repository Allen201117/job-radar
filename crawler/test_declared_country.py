"""对方 ATS 自报的国家（RawJob.country_code）：只补「地点说不清、原本按 source.regions 猜」的那一类，
且同一个岗每一轮都给同一个答案（不在国内 / 海外两个池子之间来回跳）。

背景（2026-09-23 香港库实测）：workday 在招岗里地点判不出国家、按 regions 兜底判 domestic 的 1,715 个，
路径只写 'Durham' / 'Remote' / 'One Island East'；detail 的 jobRequisitionLocation.country.alpha2Code
问得到的 1,053 个里 US 541 / HK 306 / GB 28 / CN 27 / CA 24 …
"""
import copy
import json
import os
import unittest
from unittest import mock

import httpx

import normalizer
from adapters.base import RawJob
from adapters.workday import WorkdayAdapter, _declared_country

CN_SOURCE = {"CN", "US", "SG", "Remote"}   # 外企源的典型 regions：兜底 = domestic
US_SOURCE = {"US", "SG", "Remote"}         # 纯海外源：兜底 = overseas


def _norm(location, declared=None, regions=CN_SOURCE):
    raw = RawJob(company="x", title="Engineer", location=location,
                 jd_url="https://t.wd5.myworkdayjobs.com/en-US/s/job/x/Engineer_1", country_code=declared)
    job = normalizer.normalize(raw, source_id="s", company="x", regions=regions)
    return job["country_code"], job["job_scope"]


class DeclaredCountryNormalizeTest(unittest.TestCase):
    def test_declared_country_replaces_the_regions_guess(self):
        self.assertEqual(_norm("Durham"), (None, "domestic"))  # 改前：按 regions 猜成国内
        self.assertEqual(_norm("Durham", "US"), ("US", "overseas"))
        self.assertEqual(_norm("One, Island, East", "HK"), ("HK", "domestic"))
        self.assertEqual(_norm("Remote", "GB"), ("GB", "overseas"))

    def test_declared_greater_china_moves_a_pure_overseas_source_row_back_home(self):
        self.assertEqual(_norm("Remote", regions=US_SOURCE), (None, "overseas"))
        self.assertEqual(_norm("Remote", "CN", regions=US_SOURCE), ("CN", "domestic"))

    def test_location_text_still_wins_when_it_names_a_country(self):
        # 地点能说清就以地点为准，自报一个字都不看（与改前逐字相同）
        self.assertEqual(_norm("Shanghai, China", "US"), ("CN", "domestic"))
        self.assertEqual(_norm("Austin, TX", "CN"), ("US", "overseas"))

    def test_location_pinned_overseas_is_not_overridden(self):
        # 'Breda, Netherlands'：geo 没有荷兰的国家码，但已钉在境外，不是 regions 猜的
        self.assertEqual(_norm("Breda, Netherlands"), (None, "overseas"))
        self.assertEqual(_norm("Breda, Netherlands", "CN"), (None, "overseas"))

    def test_malformed_declared_codes_are_ignored(self):
        for bad in ("", "USA", "U", "XX", "12"):
            self.assertEqual(_norm("Durham", bad), (None, "domestic"), bad)
        self.assertEqual(_norm("Durham", " us "), ("US", "overseas"))

    def test_needs_declared_country_matches_what_normalize_will_use(self):
        # adapter 问不问、normalize 用不用，必须是同一个判据
        for loc in ("Durham", "Remote", "One, Island, East", None, "Multiple Locations"):
            self.assertTrue(normalizer.needs_declared_country(loc), loc)
        for loc in ("Shanghai, China", "Austin, TX", "Breda, Netherlands", "United, States, , , Remote",
                    "海外"):
            self.assertFalse(normalizer.needs_declared_country(loc), loc)

    def test_declared_taiwan_is_rejected_only_when_text_is_silent(self):
        def ok(location, declared):
            raw = RawJob(company="x", title="Engineer", location=location,
                         jd_url="https://t.wd5.myworkdayjobs.com/en-US/s/job/x/Engineer_1",
                         country_code=declared)
            return normalizer.validate_job_quality(raw, "https://t.wd5.myworkdayjobs.com/wday/cxs/t/s/jobs")[0]

        self.assertFalse(ok("Remote", "TW"))
        self.assertFalse(ok("Durham", "tw"))
        self.assertTrue(ok("Shanghai, China", "TW"))  # 地点说了是上海，以地点为准
        self.assertTrue(ok("Remote", "US"))
        self.assertTrue(ok("Remote", None))


def _detail(alpha2=None, posting_country=None, location="Remote", addl=None, req_desc=None, jd="<p>JD</p>"):
    req = {"descriptor": req_desc or location}
    if alpha2 is not None:
        req["country"] = {"descriptor": "x", "alpha2Code": alpha2}
    info = {"location": location, "jobRequisitionLocation": req, "jobDescription": jd}
    if posting_country is not None:
        info["country"] = {"descriptor": posting_country}
    if addl is not None:
        info["additionalLocations"] = addl
    return info


class DeclaredCountryExtractTest(unittest.TestCase):
    def test_requisition_alpha2_is_the_source(self):
        self.assertEqual(_declared_country(_detail("US", "United States of America")), "US")
        self.assertEqual(_declared_country(_detail("hk")), "HK")

    def test_posting_country_is_not_trusted_over_the_requisition(self):
        # 赛默飞「Remote, Georgia」：posting 国家写成格鲁吉亚，招聘地点是 US - Atlanta, GA
        info = _detail("US", "Georgia", location="Remote, Georgia", req_desc="US - Atlanta, GA - Remote")
        self.assertEqual(_declared_country(info), "US")

    def test_any_greater_china_location_keeps_the_job_home(self):
        # 恩智浦：招聘主地点曼谷，附加地点里有天津 → 宁可漏判，留在国内
        info = _detail("TH", "Thailand", location="Bangkok",
                       addl=["Kuala Lumpur", "Tianjin (Xinghua)", "Kaohsiung", "Singapore"])
        self.assertEqual(_declared_country(info), "CN")
        self.assertEqual(_declared_country(_detail("US", "China", location="Durham")), "CN")

    def test_missing_or_malformed_alpha2_gives_nothing(self):
        self.assertIsNone(_declared_country(_detail(None, "United States of America", location="Durham")))
        self.assertIsNone(_declared_country(_detail("USA", location="Durham")))
        self.assertIsNone(_declared_country(None))

    def test_taiwan_is_reported_as_is_for_the_quality_gate(self):
        self.assertEqual(_declared_country(_detail("TW", "Taiwan", location="Remote")), "TW")


def _resp(status, payload=None, headers=None):
    r = mock.Mock(status_code=status, headers=headers or {})
    r.json.return_value = payload if payload is not None else {}
    if status >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError("x", request=mock.Mock(), response=r)
    return r


class WorkdayCountryLookupFetchTest(unittest.TestCase):
    SOURCE_URL = "https://tenant.wd5.myworkdayjobs.com/wday/cxs/tenant/site/jobs"
    POSTS = [
        {"title": "CN Role", "externalPath": "/job/China-Shanghai/CN-Role_1"},  # 地点说清了：不问
        {"title": "US Remote", "externalPath": "/job/Remote/US-Remote_2"},
        {"title": "HK Office", "externalPath": "/job/One-Island-East/HK-Office_3"},
        {"title": "Closed", "externalPath": "/job/Durham/Closed_4"},
    ]

    def _fetch(self, detail_side_effect, env=None):
        def post_side_effect(url, json=None, headers=None, timeout=None):
            body = json or {}
            if body.get("limit") == 1:
                return _resp(200, {"facets": [{"facetParameter": "locations", "values": [
                    {"id": "cn", "descriptor": "China"}]}]})
            if body.get("offset", 0) > 0 or body.get("searchText"):
                return _resp(200, {"jobPostings": []})
            return _resp(200, {"jobPostings": copy.deepcopy(self.POSTS)})

        adapter = WorkdayAdapter()
        adapter.regions = frozenset(CN_SOURCE)
        with mock.patch.dict(os.environ, env or {"CRAWL_DETAIL_CAP": "0"}), \
                mock.patch("adapters.workday.httpx.post", side_effect=post_side_effect), \
                mock.patch("adapters.workday.httpx.get", side_effect=detail_side_effect) as get, \
                mock.patch("adapters.workday.time.sleep"):
            html = adapter.fetch(self.SOURCE_URL)
        jobs = {j.title: j for j in adapter.parse(html)}
        return adapter, jobs, [c.args[0] for c in get.call_args_list]

    @staticmethod
    def _by_path(url, headers=None, timeout=None):
        if "US-Remote_2" in url:
            return _resp(200, {"jobPostingInfo": _detail("US")})
        if "HK-Office_3" in url:
            return _resp(200, {"jobPostingInfo": _detail("HK", location="One Island East")})
        if "Closed_4" in url:
            return _resp(403, {"errorCode": "S22", "message": "permission denied"})
        raise AssertionError(f"不该为地点已说清的岗请求 detail：{url}")

    def test_fast_tier_still_asks_for_the_country(self):
        # 快档 CRAWL_DETAIL_CAP=0 不抓正文，但国家照问——否则快档 / 重档对同一个岗给两个答案
        adapter, jobs, urls = self._fetch(self._by_path)
        self.assertEqual(len(urls), 3)
        self.assertEqual(jobs["US Remote"].country_code, "US")
        self.assertEqual(jobs["HK Office"].country_code, "HK")
        self.assertIsNone(jobs["CN Role"].country_code)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(adapter.country_lookup, {"needed": 3, "looked_up": 3, "declared": 2, "unresolved": 0})

    def test_definitive_4xx_falls_back_the_same_way_every_run(self):
        # 403 S22 = 岗位不对外：确定答复，照旧按 regions 兜底，不算没抓全
        _, jobs, _ = self._fetch(self._by_path)
        self.assertIn("Closed", jobs)
        self.assertIsNone(jobs["Closed"].country_code)

    def test_transient_failure_skips_the_row_instead_of_writing_a_guess(self):
        def flaky(url, headers=None, timeout=None):
            if "US-Remote_2" in url:
                raise httpx.ConnectTimeout("timeout")
            if "HK-Office_3" in url:
                return _resp(503)
            return self._by_path(url)

        with self.assertLogs("adapters.workday", level="WARNING"):
            adapter, jobs, urls = self._fetch(flaky)
        # 各重试一次仍失败 → 本轮不写这两行（库里保留上一轮的判定），其余照常
        self.assertNotIn("US Remote", jobs)
        self.assertNotIn("HK Office", jobs)
        self.assertIn("CN Role", jobs)
        self.assertIn("Closed", jobs)
        self.assertEqual(sum("US-Remote_2" in u for u in urls), 2)
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(adapter.country_lookup["unresolved"], 2)

    def test_retry_that_succeeds_is_used(self):
        calls = {"n": 0}

        def once_then_ok(url, headers=None, timeout=None):
            if "US-Remote_2" in url:
                calls["n"] += 1
                if calls["n"] == 1:
                    return _resp(429, headers={"Retry-After": "2"})
            return self._by_path(url)

        adapter, jobs, _ = self._fetch(once_then_ok)
        self.assertEqual(jobs["US Remote"].country_code, "US")
        self.assertTrue(adapter.fetch_complete)

    def test_heavy_tier_reuses_the_description_request(self):
        # 重档逐岗抓正文时已拿到国家，不再为它多请求一次
        adapter, jobs, urls = self._fetch(self._by_path, env={"CRAWL_DETAIL_CAP": "300"})
        self.assertEqual(len([u for u in urls if "US-Remote_2" in u]), 1)
        self.assertEqual(jobs["US Remote"].country_code, "US")
        self.assertEqual(adapter.country_lookup["looked_up"], 1)  # 只剩描述阶段拿 403 的 Closed

    def test_lookup_cap_overflow_is_unresolved_not_guessed(self):
        with self.assertLogs("adapters.workday", level="WARNING"):
            adapter, jobs, urls = self._fetch(self._by_path, env={"CRAWL_DETAIL_CAP": "0",
                                                                  "CRAWL_COUNTRY_LOOKUP_CAP": "1"})
        self.assertEqual(len(urls), 1)
        self.assertEqual(adapter.country_lookup["unresolved"], 2)
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(sorted(jobs), ["CN Role", "US Remote"])

    def test_same_answer_across_tiers(self):
        _, fast, _ = self._fetch(self._by_path)
        _, heavy, _ = self._fetch(self._by_path, env={"CRAWL_DETAIL_CAP": "300"})
        for title in fast:
            self.assertEqual(fast[title].country_code, heavy[title].country_code, title)
        self.assertEqual(sorted(fast), sorted(heavy))


class WorkdayParseDeclaredCountryTest(unittest.TestCase):
    def test_parse_is_pure_over_the_fetched_payload(self):
        payload = {"_host": "https://t.wd5.myworkdayjobs.com", "_site": "s", "text_posts": [],
                   "trusted_posts": [
                       {"title": "A", "externalPath": "/job/Durham/A_1", "_country": "US"},
                       {"title": "B", "externalPath": "/job/Durham/B_2", "_country": None},
                       {"title": "C", "externalPath": "/job/Durham/C_3", "_country_unresolved": True},
                   ]}
        jobs = {j.title: j for j in WorkdayAdapter().parse(json.dumps(payload))}
        self.assertEqual(jobs["A"].country_code, "US")
        self.assertIsNone(jobs["B"].country_code)
        self.assertNotIn("C", jobs)


if __name__ == "__main__":
    unittest.main()
