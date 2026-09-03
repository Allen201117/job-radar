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


if __name__ == "__main__":
    unittest.main()
