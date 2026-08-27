import json
import unittest

from adapters.avature import AvatureAdapter
from adapters.siemens import SiemensAdapter


class AvatureAdapterTest(unittest.TestCase):
    def test_siemens_regression_keeps_company_search_and_six_card_contract(self):
        html = """
        <article class="article--result"><h3><a href="/en_US/externaljobs/JobDetail/123">研发工程师</a></h3>
        <span class="list-item-jobCity">Shanghai</span><span class="list-item-jobCountry">China</span>
        <span class="list-item-family">Engineering</span></article>
        """
        adapter = SiemensAdapter()
        jobs = adapter.parse(html)

        self.assertEqual(adapter.PAGE_SIZE, 6)
        self.assertEqual(adapter._search_terms(), ["China"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "Siemens")
        self.assertEqual(jobs[0].jd_url, "https://jobs.siemens.com/en_US/externaljobs/JobDetail/123")
        self.assertIn("search=China", adapter._with_page_params(adapter.SEARCH_URL, 12, "China"))

    def test_generic_loreal_card_uses_its_actual_jobdetail_href(self):
        html = """
        <article class="article--result"><h3><a href="https://careers.loreal.com/zh_CN/jobs/JobDetail/Jr-Product-Manager-Kiehl-s/246614">Jr Product Manager</a></h3>
        <div class="article__header__text__subtitle"><span>Shanghai</span><span>已发送 11-Jun-2026</span></div></article>
        """
        jobs = AvatureAdapter().parse(html)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "")
        self.assertEqual(jobs[0].location, "Shanghai")
        self.assertEqual(jobs[0].jd_url, "https://careers.loreal.com/zh_CN/jobs/JobDetail/Jr-Product-Manager-Kiehl-s/246614")

    def test_facet_source_keeps_unknown_location_but_siemens_drops_it(self):
        html = """
        <article class="article--result"><h3><a href="/zh_CN/jobs/JobDetail/sales/1">Sales Supervisor</a></h3>
        <div class="article__header__text__subtitle"><span> </span><span>已发送 18-Aug-2026</span></div>
        <div class="article__content">&lt;p&gt;岗位职责：服务客户&lt;/p&gt;</div></article>
        """
        loreal = AvatureAdapter()
        siemens = SiemensAdapter()

        loreal_jobs = loreal.parse(html)
        siemens_jobs = siemens.parse(html)

        self.assertEqual(len(loreal_jobs), 1)
        self.assertIsNone(loreal_jobs[0].location)
        self.assertEqual(loreal_jobs[0].summary, "岗位职责：服务客户")
        self.assertEqual(siemens_jobs, [])

    def test_facet_source_keeps_unrecognized_chinese_city_but_drops_proven_foreign(self):
        """认不出国家的城市 = 证据不足（保留）；能确证的外国 = 证据相反（丢弃）。

        2026-08-27 live：欧莱雅中国 facet 347 个岗里有 43 个落在 乌鲁木齐/金华/常德 等
        国家词表没收录的中国城市上，旧口径把它们当「不在中国」丢掉（占该源 12%）。
        """
        def card(city, job_id):
            return (f'<article class="article--result"><h3>'
                    f'<a href="https://careers.loreal.com/zh_CN/jobs/JobDetail/x/{job_id}">岗位{job_id}</a></h3>'
                    f'<div class="article__header__text__subtitle"><span>{city}</span></div></article>')

        html = card("Ürümqi", 1) + card("Jinhua", 2) + card("Shanghai", 3) + card("Singapore", 4)

        loreal_locations = [j.location for j in AvatureAdapter().parse(html)]
        siemens_locations = [j.location for j in SiemensAdapter().parse(html)]

        self.assertEqual(loreal_locations, ["Ürümqi", "Jinhua", "Shanghai"])
        # Siemens 的关键词收窄不可信 → 只留能确证在中国的。
        self.assertEqual(siemens_locations, ["Shanghai"])

    def test_fetch_envelope_keeps_page_base_for_relative_jobdetail_href(self):
        card = ('<article class="article--result" data-total="1"><h3>'
                '<a href="/zh_CN/jobs/JobDetail/relative/1">相对链接岗位</a></h3>'
                '<div class="article__header__text__subtitle"><span>Shanghai</span></div></article>')

        class Response:
            status_code = 200

            def __init__(self, text, url):
                self.text = text
                self.url = url

            def raise_for_status(self):
                return None

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def get(self, url):
                return Response(card if "offset=0" in url else "", url)

        adapter = AvatureAdapter()
        adapter._client = lambda **_kwargs: Client()
        payload = adapter.fetch("https://careers.example/zh_CN/jobs/SearchJobs?facet=cn")
        jobs = adapter.parse(payload)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].jd_url, "https://careers.example/zh_CN/jobs/JobDetail/relative/1")
        self.assertEqual(adapter.reported_total, 1)
        self.assertTrue(adapter.fetch_complete)

    def test_results_total_prefers_card_data_total(self):
        from adapters.avature import _results_total
        html = '<article class="article--result" data-total="347"></article>numberResults: "999"'
        self.assertEqual(_results_total(html), 347)


if __name__ == "__main__":
    unittest.main()
