import json
import os
import sys
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))

from adapters.amazon import AmazonAdapter
from adapters.greenhouse import GreenhouseAdapter
from adapters.workday import WorkdayAdapter


def _with_regions(adapter, regions):
    adapter.regions = set(regions)
    return adapter


class AdapterRegionsTest(unittest.TestCase):
    def test_greenhouse_parse_filters_by_regions(self):
        payload = json.dumps({"jobs": [
            {"title": "CN SWE", "absolute_url": "https://boards.greenhouse.io/x/jobs/1",
             "location": {"name": "Beijing, China"}},
            {"title": "US SWE", "absolute_url": "https://boards.greenhouse.io/x/jobs/2",
             "location": {"name": "New York, United States"}},
            {"title": "SG SWE", "absolute_url": "https://boards.greenhouse.io/x/jobs/3",
             "location": {"name": "Singapore"}},
        ]})

        self.assertEqual(
            {j.title for j in _with_regions(GreenhouseAdapter(), {"CN"}).parse(payload)},
            {"CN SWE"},
        )
        self.assertEqual(
            {j.title for j in _with_regions(GreenhouseAdapter(), {"US", "SG"}).parse(payload)},
            {"US SWE", "SG SWE"},
        )
        self.assertEqual(
            {j.title for j in _with_regions(GreenhouseAdapter(), {"CN", "US", "SG"}).parse(payload)},
            {"CN SWE", "US SWE", "SG SWE"},
        )

    def test_amazon_parse_filters_by_regions(self):
        payload = json.dumps({"jobs": [
            {"title": "CN SWE", "normalized_location": "Shenzhen, CHN", "job_path": "/en/jobs/1/cn"},
            {"title": "HK PM", "normalized_location": "Hong Kong, HKG", "job_path": "/en/jobs/2/hk"},
            {"title": "US SWE", "normalized_location": "Seattle, USA", "job_path": "/en/jobs/3/us"},
            {"title": "SG SWE", "normalized_location": "Singapore, SGP", "job_path": "/en/jobs/4/sg"},
        ]})

        self.assertEqual(
            {j.title for j in _with_regions(AmazonAdapter(), {"CN"}).parse(payload)},
            {"CN SWE", "HK PM"},
        )
        self.assertEqual(
            {j.title for j in _with_regions(AmazonAdapter(), {"US", "SG"}).parse(payload)},
            {"US SWE", "SG SWE"},
        )
        self.assertEqual(
            {j.title for j in _with_regions(AmazonAdapter(), {"CN", "US", "SG"}).parse(payload)},
            {"CN SWE", "HK PM", "US SWE", "SG SWE"},
        )

    def test_amazon_fetch_country_params_follow_regions(self):
        captured_urls = []

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"jobs": []}

        def fake_get(url, **kwargs):
            captured_urls.append(url)
            return Response()

        adapter = _with_regions(AmazonAdapter(), {"US", "SG"})
        with mock.patch("adapters.amazon.httpx.get", side_effect=fake_get):
            adapter.fetch("https://www.amazon.jobs/en/search.json?normalized_country_code[]=CHN&result_limit=100")

        query = parse_qs(urlparse(captured_urls[0]).query)
        self.assertEqual(sorted(query.get("normalized_country_code[]", [])), ["SGP", "USA"])
        self.assertNotIn("CHN", query.get("normalized_country_code[]", []))

    def test_workday_facet_candidates_follow_regions(self):
        facets = [{"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locationHierarchy1", "descriptor": "Locations", "values": [
                {"id": "cn-id", "descriptor": "China"},
                {"id": "hk-id", "descriptor": "Hong Kong"},
                {"id": "us-id", "descriptor": "United States"},
                {"id": "sg-id", "descriptor": "Singapore"},
                {"id": "tw-id", "descriptor": "Taiwan"},
            ]},
        ]}]

        self.assertEqual(
            WorkdayAdapter._facet_candidates_for_regions(facets, {"CN"}),
            {"locationHierarchy1": ["cn-id", "hk-id"]},
        )
        self.assertEqual(
            WorkdayAdapter._facet_candidates_for_regions(facets, {"US", "SG"}),
            {"locationHierarchy1": ["us-id", "sg-id"]},
        )

    def test_workday_text_posts_filter_by_regions(self):
        payload = json.dumps({
            "_host": "https://x.wd1.myworkdayjobs.com",
            "_site": "S",
            "trusted_posts": [],
            "text_posts": [
                {"title": "CN Role", "externalPath": "/job/China-Beijing/CN-Role_JR1"},
                {"title": "US Role", "externalPath": "/job/United-States-New-York/US-Role_JR2"},
                {"title": "SG Role", "externalPath": "/job/Singapore/SG-Role_JR3"},
            ],
        })

        self.assertEqual(
            {j.title for j in _with_regions(WorkdayAdapter(), {"CN"}).parse(payload)},
            {"CN Role"},
        )
        self.assertEqual(
            {j.title for j in _with_regions(WorkdayAdapter(), {"US", "SG"}).parse(payload)},
            {"US Role", "SG Role"},
        )
        self.assertEqual(
            {j.title for j in _with_regions(WorkdayAdapter(), {"CN", "US", "SG"}).parse(payload)},
            {"CN Role", "US Role", "SG Role"},
        )


if __name__ == "__main__":
    unittest.main()
