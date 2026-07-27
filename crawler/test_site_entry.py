import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import site_entry as se
import wikidata as W


def _str(value):
    return {"mainsnak": {"datavalue": {"value": value}}}


class _Response:
    def __init__(self, url, text="", status_code=200):
        self.url = url
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)


class _Client:
    def __init__(self, routes):
        self.routes = {
            url: list(responses) if isinstance(responses, list) else [responses]
            for url, responses in routes.items()
        }
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        responses = self.routes.get(url)
        if not responses:
            raise RuntimeError("offline fixture has no route for %s" % url)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class WikidataOfficialSiteTest(unittest.TestCase):
    def test_parse_company_facts_extracts_first_p856(self):
        entity = {
            "id": "Q123",
            "labels": {"zh": {"value": "测试公司"}},
            "claims": {
                "P856": [
                    _str("https://www.example.com/"),
                    _str("https://global.example.com/"),
                ],
            },
        }

        facts = W.parse_company_facts(entity, {})

        self.assertEqual(facts["official_site"], "https://www.example.com/")

    def test_resolve_official_site_uses_wikidata_before_sources(self):
        entity = {
            "id": "Q123",
            "labels": {"zh": {"value": "测试公司"}},
            "claims": {"P856": [_str("https://www.example.com/")]},
        }
        with mock.patch.object(se.wikidata, "search_qid", return_value="Q123"), \
             mock.patch.object(
                 se.wikidata,
                 "_get",
                 return_value={"entities": {"Q123": entity}},
             ), \
             mock.patch.object(se.db, "get_supabase") as get_supabase:
            resolved = se.resolve_official_site("测试公司", client=object())

        self.assertEqual(resolved, "https://www.example.com/")
        get_supabase.assert_not_called()

    def test_resolve_official_site_falls_back_to_near_name_source_host(self):
        rows = [{
            "id": "source-1",
            "company": "测试公司股份有限公司",
            "source_url": "https://jobs.example.com/careers/list",
            "enabled": True,
        }]
        with mock.patch.object(se.wikidata, "search_qid", return_value=None), \
             mock.patch.object(se.db, "fetch_all_rows", return_value=rows):
            result = se.resolve_official_site_details(
                "测试公司",
                client=object(),
                supabase=object(),
            )

        self.assertEqual(result, {
            "home_url": "https://jobs.example.com/",
            "entry_channel": "existing_source_host",
        })

    def test_disabled_source_is_not_reused_as_an_official_site(self):
        rows = [{
            "id": "source-disabled",
            "company": "测试公司",
            "source_url": "https://wrong.example.com/jobs",
            "enabled": False,
        }]
        with mock.patch.object(se.wikidata, "search_qid", return_value=None), \
             mock.patch.object(se.db, "fetch_all_rows", return_value=rows):
            result = se.resolve_official_site_details(
                "测试公司",
                client=object(),
                supabase=object(),
            )

        self.assertIsNone(result)


class CareersLinkTest(unittest.TestCase):
    def test_candidates_are_sorted_by_site_relationship_and_ats_bonus(self):
        home = "https://www.example.com/"
        html = """
        <a href="https://outside.example.net/recruit">外部招聘</a>
        <a href="https://boards.greenhouse.io/acme">Open jobs</a>
        <a href="https://acme.mokahr.com/social-recruitment/acme">职位</a>
        <a href="/about/join">加入我们</a>
        <a href="https://careers.example.com/jobs">Careers</a>
        """
        client = _Client({home: _Response(home, html)})

        links = se.find_careers_links("测试公司", home, client=client)

        self.assertEqual(
            [item["url"] for item in links],
            [
                "https://careers.example.com/jobs",
                "https://www.example.com/about/join",
                "https://boards.greenhouse.io/acme",
                "https://acme.mokahr.com/social-recruitment/acme",
                "https://outside.example.net/recruit",
            ],
        )
        self.assertEqual(links[2]["score"], links[3]["score"])
        self.assertGreater(links[3]["score"], links[4]["score"])

    def test_relative_links_are_joined_and_duplicates_removed(self):
        home = "https://www.example.com/about/"
        html = """
        <a href="../join">招聘</a>
        <a href="https://www.example.com/join">加入我们</a>
        <a href="mailto:hr@example.com">HR</a>
        """
        client = _Client({home: _Response(home, html)})

        links = se.find_careers_links("测试公司", home, client=client)

        self.assertEqual(
            [item["url"] for item in links],
            ["https://www.example.com/join"],
        )

    def test_noise_page_returns_only_top_five(self):
        home = "https://www.example.com/"
        html = "".join(
            '<a href="/course/%s">教师招聘课程 %s</a>' % (index, index)
            for index in range(69)
        )
        client = _Client({home: _Response(home, html)})

        links = se.find_careers_links("中公教育", home, client=client)

        self.assertEqual(len(links), 5)
        self.assertEqual(
            [item["url"] for item in links],
            ["https://www.example.com/course/%s" % index for index in range(5)],
        )

    def test_common_path_is_candidate_when_home_has_no_careers_link(self):
        home = "https://www.example.com/"
        careers = "https://www.example.com/careers"
        client = _Client({
            home: _Response(home, "<a href='/products'>产品</a>"),
            careers: _Response(
                careers,
                "<title>测试公司招聘</title><h1>开放岗位</h1>",
            ),
        })

        links = se.find_careers_links("测试公司", home, client=client)

        self.assertEqual(links[0]["url"], careers)
        self.assertEqual([url for url, _kwargs in client.calls], [home, careers])

    def test_common_path_redirected_to_home_does_not_hide_later_real_path(self):
        home = "https://www.example.com/"
        careers = "https://www.example.com/careers"
        join = "https://www.example.com/join"
        client = _Client({
            home: _Response(home, "<a href='/products'>产品</a>"),
            careers: _Response(home, "<a href='/products'>产品</a>"),
            join: _Response(
                join,
                "<title>测试公司人才招聘</title><h1>开放岗位</h1>",
            ),
        })

        links = se.find_careers_links("测试公司", home, client=client)

        self.assertEqual(links[0]["url"], join)
        self.assertEqual(
            [url for url, _kwargs in client.calls],
            [home, careers, join],
        )

    def test_retries_failures_but_never_exceeds_eight_gets(self):
        home = "https://www.example.com/"
        client = _Client({
            home: [RuntimeError("boom"), RuntimeError("boom")],
            "https://www.example.com/careers": [
                RuntimeError("boom"), RuntimeError("boom")
            ],
            "https://www.example.com/join": [
                RuntimeError("boom"), RuntimeError("boom")
            ],
            "https://www.example.com/jobs": [
                RuntimeError("boom"), RuntimeError("boom")
            ],
        })

        links = se.find_careers_links("测试公司", home, client=client)

        self.assertEqual(links, [])
        self.assertEqual(len(client.calls), 8)


if __name__ == "__main__":
    unittest.main()
