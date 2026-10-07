import json
import unittest

import httpx

from adapters.radancy import RadancyAdapter, is_candidate, job_url_parts, parse_detail, sitemap_job_urls

SITEMAP = "https://careers.loreal.com/en/sitemap.xml"
BASE = "https://careers.loreal.com/en/job"

CN_CITY = f"{BASE}/shanghai/%e7%be%8e%e5%ae%b9%e9%a1%be%e9%97%ae-%e5%85%b0%e8%94%bb/3456/1"   # 美容顾问-兰蔻
CN_CJK = f"{BASE}/changji/%e7%be%8e%e5%ae%b9%e9%a1%be%e9%97%ae/3456/2"                       # 城市不在词表，标题是汉字
TW_CITY = f"{BASE}/taipei/%e7%be%8e%e5%ae%b9%e9%a1%be%e5%95%8f/3456/3"                       # 台湾：城市就判出 TW
TW_HIDDEN = f"{BASE}/xinyi/%e7%be%8e%e5%ae%b9%e9%a1%be%e5%95%8f/3456/4"                      # 城市认不出 + 汉字标题，详情页说台湾
US_CITY = f"{BASE}/new-york/brand-manager/3456/5"
UNKNOWN_EN = f"{BASE}/libramont/technicien/3456/6"


def _sitemap(urls):
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return ('<?xml version="1.0" encoding="utf-8"?><urlset><url><loc>https://careers.loreal.com</loc></url>'
            f'<url><loc>https://careers.loreal.com/en/category/retail-jobs/3456/1/1</loc></url>{body}</urlset>')


def _detail(title, city, region, country, description="<p>岗位职责 &amp; 要求</p>"):
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": title,
          "description": description, "datePosted": "2026-10-01",
          "jobLocation": [{"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": city,
                                                         "addressRegion": region, "addressCountry": country}}]}
    return (f'<html><script type="application/ld+json">{{"@type":"Organization"}}</script>'
            f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script></html>')


class FakeClient:
    """按完整 URL 返回预置响应：str = 200 正文，int = 状态码，异常实例则抛出。"""
    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        self.requested.append(url)
        body = self.routes.get(url, 404)
        if isinstance(body, Exception):
            raise body
        request = httpx.Request("GET", url)
        if isinstance(body, int):
            return httpx.Response(body, text="", request=request)
        return httpx.Response(200, text=body, request=request)


def _adapter(routes, regions=("CN",)):
    ad = RadancyAdapter()
    ad.timeout = 5
    ad.regions = list(regions)
    client = FakeClient(routes)
    ad._client = lambda **kw: client
    ad._fake = client
    return ad


class RadancyPureTest(unittest.TestCase):
    def test_job_url_parts_decodes_city_and_title(self):
        self.assertEqual(job_url_parts(CN_CITY), ("shanghai", "美容顾问-兰蔻"))
        self.assertIsNone(job_url_parts("https://careers.loreal.com/en/category/retail-jobs/3456/1/1"))

    def test_sitemap_keeps_only_job_urls_deduped(self):
        urls = sitemap_job_urls(_sitemap([CN_CITY, US_CITY, CN_CITY]))
        self.assertEqual(urls, [CN_CITY, US_CITY])

    def test_candidate_filter_both_directions(self):
        self.assertTrue(is_candidate(CN_CITY, ["CN"]))
        self.assertTrue(is_candidate(CN_CJK, ["CN"]))       # 城市不在词表的中国岗靠汉字标题兜住
        self.assertFalse(is_candidate(TW_CITY, ["CN"]))     # 台湾城市直接排除，不开页
        self.assertFalse(is_candidate(US_CITY, ["CN"]))
        self.assertFalse(is_candidate(UNKNOWN_EN, ["CN"]))
        self.assertTrue(is_candidate(US_CITY, ["US"]))
        self.assertFalse(is_candidate(CN_CJK, ["US"]))      # 汉字兜底只给要 CN 的源

    def test_parse_detail_reads_json_ld(self):
        info = parse_detail(_detail("美容顾问-兰蔻", "Shanghai", "Shanghai Shi", "China"))
        self.assertEqual(info["title"], "美容顾问-兰蔻")
        self.assertEqual(info["location"], "Shanghai, Shanghai Shi, China")
        self.assertEqual(info["summary"], "岗位职责 & 要求")
        self.assertEqual(info["country_code"], "CN")
        self.assertEqual(info["posted_at"], "2026-10-01")
        self.assertIsNone(parse_detail("<html>no ld</html>"))


class RadancyFetchTest(unittest.TestCase):
    def _routes(self, **overrides):
        routes = {
            SITEMAP: _sitemap([CN_CITY, CN_CJK, TW_CITY, TW_HIDDEN, US_CITY, UNKNOWN_EN]),
            CN_CITY: _detail("美容顾问-兰蔻", "Shanghai", "Shanghai Shi", "China"),
            CN_CJK: _detail("美容顾问", "Changji", "Xinjiang", "China"),
            TW_HIDDEN: _detail("美容顧問", "Taipei", "Taipei City", "Taiwan"),
        }
        routes.update(overrides)
        return routes

    def test_end_to_end_keeps_only_confirmed_china_jobs(self):
        ad = _adapter(self._routes())
        jobs = ad.parse(ad.fetch(SITEMAP))
        self.assertEqual(sorted(j.jd_url for j in jobs), sorted([CN_CITY, CN_CJK]))
        self.assertTrue(ad.fetch_complete)
        self.assertIsNone(ad.reported_total)   # 站点地图不给分地区总数：诚实盲区
        opened = set(ad._fake.requested) - {SITEMAP}
        self.assertEqual(opened, {CN_CITY, CN_CJK, TW_HIDDEN})   # 美国 / 英文标题的未知城市不开页
        job = next(j for j in jobs if j.jd_url == CN_CITY)
        self.assertEqual(job.location, "Shanghai, Shanghai Shi, China")
        self.assertEqual(job.summary, "岗位职责 & 要求")

    def test_never_requests_robots_disallowed_search_pages(self):
        ad = _adapter(self._routes())
        ad.parse(ad.fetch(SITEMAP))
        self.assertFalse([u for u in ad._fake.requested if "/search-jobs" in u])

    def test_detail_failure_skips_job_and_marks_incomplete(self):
        ad = _adapter(self._routes(**{CN_CJK: httpx.ConnectTimeout("boom")}))
        jobs = ad.parse(ad.fetch(SITEMAP))
        self.assertEqual([j.jd_url for j in jobs], [CN_CITY])
        self.assertFalse(ad.fetch_complete)

    def test_detail_404_is_gone_not_incomplete(self):
        ad = _adapter(self._routes(**{CN_CJK: 404}))
        jobs = ad.parse(ad.fetch(SITEMAP))
        self.assertEqual([j.jd_url for j in jobs], [CN_CITY])
        self.assertTrue(ad.fetch_complete)

    def test_sitemap_without_jobs_raises(self):
        ad = _adapter({SITEMAP: _sitemap([])})
        with self.assertRaises(RuntimeError):
            ad.fetch(SITEMAP)

    def test_all_details_failing_raises(self):
        ad = _adapter(self._routes(**{CN_CITY: 500, CN_CJK: 500, TW_HIDDEN: 500}))
        with self.assertRaises(RuntimeError):
            ad.fetch(SITEMAP)

    def test_candidates_over_list_cap_mark_incomplete(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"CRAWL_MAX_JOBS": "1"}):
            ad = _adapter(self._routes())
            jobs = ad.parse(ad.fetch(SITEMAP))
        self.assertEqual(len(jobs), 1)
        self.assertFalse(ad.fetch_complete)


if __name__ == "__main__":
    unittest.main()
