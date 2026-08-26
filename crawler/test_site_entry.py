import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import site_entry as se
import wikidata as W
import logo_util


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

    def test_resolve_official_site_uses_source_before_wikidata(self):
        rows = [{
            "id": "source-1",
            "company": "测试公司",
            "source_url": "https://jobs.example.com/careers/list",
            "enabled": True,
        }]
        with mock.patch.object(
            se.wikidata, "search_qid", side_effect=AssertionError("sources 应优先")
        ):
            result = se.resolve_official_site_details(
                "测试公司", client=object(), source_rows=rows
            )

        self.assertEqual(result, {
            "home_url": "https://jobs.example.com/",
            "entry_channel": "existing_source_host",
        })

    def test_verified_domain_table_prevents_wikidata_lookup(self):
        with mock.patch.dict(
            logo_util.COMPANY_DOMAIN_OVERRIDES,
            {"测试公司": "verified.example.com"},
            clear=False,
        ), mock.patch.object(
            se.wikidata, "search_qid", side_effect=AssertionError("本地命中不应联网")
        ), mock.patch.object(
            se, "resolve_official_site_by_llm", side_effect=AssertionError("本地命中不应问 LLM")
        ):
            result = se.resolve_official_site_details(
                "  测试公司  ", client=object(), source_rows=[]
            )

        self.assertEqual(result, {
            "home_url": "https://verified.example.com/",
            "entry_channel": "verified_domain_table",
        })

    def test_domain_table_miss_falls_back_to_wikidata_then_llm(self):
        with mock.patch.dict(logo_util.COMPANY_DOMAIN_OVERRIDES, {}, clear=True), \
             mock.patch.object(se.wikidata, "search_qid", return_value=None), \
             mock.patch.object(
                 se, "resolve_official_site_by_llm", return_value="https://llm.example.com/"
             ) as llm:
            result = se.resolve_official_site_details(
                "未收录公司", client=object(), source_rows=[]
            )

        self.assertEqual(result, {
            "home_url": "https://llm.example.com/",
            "entry_channel": "llm_domain",
        })
        llm.assert_called_once_with("未收录公司")

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
    def test_career_entry_candidates_prioritize_subdomains_and_keep_compound_suffix(self):
        candidates = se.career_entry_candidates("https://www.example.com.cn/about")

        self.assertEqual(candidates[0], "https://careers.example.com.cn/")
        self.assertIn("https://joinus.example.com.cn/", candidates)
        self.assertIn("https://www.example.com.cn/recruitment", candidates)
        self.assertEqual(len(candidates), len(set(candidates)))
        self.assertEqual(candidates, se.career_entry_candidates("https://www.example.com.cn/about"))

    def test_career_entry_candidates_rejects_empty_or_invalid_url(self):
        self.assertEqual(se.career_entry_candidates(""), [])
        self.assertEqual(se.career_entry_candidates("example.com"), [])

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
                "<title>测试公司招聘</title><h1>招聘开放职位岗位</h1>",
            ),
        })

        links = se.find_careers_links("测试公司", home, client=client)

        self.assertEqual(links[0]["url"], careers)
        self.assertEqual(client.calls[0][0], home)
        self.assertIn(careers, [url for url, _kwargs in client.calls])

    def test_common_path_redirected_to_home_does_not_hide_later_real_path(self):
        home = "https://www.example.com/"
        careers = "https://www.example.com/careers"
        join = "https://www.example.com/join"
        client = _Client({
            home: _Response(home, "<a href='/products'>产品</a>"),
            careers: _Response(home, "<a href='/products'>产品</a>"),
            join: _Response(
                join,
                "<title>测试公司人才招聘</title><h1>招聘开放职位岗位</h1>",
            ),
        })

        links = se.find_careers_links("测试公司", home, client=client)

        self.assertEqual(links[0]["url"], join)
        self.assertEqual(client.calls[0][0], home)
        self.assertIn(careers, [url for url, _kwargs in client.calls])
        self.assertIn(join, [url for url, _kwargs in client.calls])

    def test_template_spa_html_keywords_are_kept_without_visible_text(self):
        home = "https://www.midea.com/"
        careers = "https://careers.midea.com/"
        client = _Client({
            home: _Response(home, "<html></html>"),
            careers: _Response(
                careers,
                "<script>careers jobs recruit 招聘 职位 岗位</script>",
            ),
        })

        links = se.find_careers_links("美的", home, client=client)

        self.assertIn(careers, [item["url"] for item in links])

    def test_template_careers_final_url_is_kept_with_almost_empty_html(self):
        home = "https://www.citics.com/"
        careers = "https://careers.citics.com/"
        client = _Client({
            home: _Response(home, "<html></html>"),
            careers: _Response(careers, "<script>window.__SPA__={}</script>"),
        })

        links = se.find_careers_links("中信证券", home, client=client)

        self.assertIn(careers, [item["url"] for item in links])

    def test_template_careers_subdomain_redirected_home_without_keywords_is_rejected(self):
        home = "https://www.example.com/"
        careers = "https://careers.example.com/"
        client = _Client({
            home: _Response(home, "<html></html>"),
            careers: _Response(home, "<html><body>集团首页</body></html>"),
        })

        links = se.find_careers_links("测试公司", home, client=client)

        self.assertNotIn(home, [item["url"] for item in links])

    def test_template_page_extracts_nested_careers_link(self):
        home = "https://www.example.com/"
        careers = "https://www.example.com/careers"
        nested = "https://www.example.com/column/16/"
        client = _Client({
            home: _Response(home, "<html></html>"),
            careers: _Response(
                careers,
                "<a href='/column/16/'>社会招聘</a>",
            ),
        })

        links = se.find_careers_links("万华化学", home, client=client)

        self.assertIn(careers, [item["url"] for item in links])
        self.assertIn(nested, [item["url"] for item in links])

    def test_template_fetch_retries_transient_connection_failure(self):
        home = "https://www.example.com/"
        careers = "https://www.example.com/careers"
        client = _Client({
            home: [
                RuntimeError("PoolTimeout"),
                _Response(home, "<a href='/join'>加入我们</a>"),
            ],
        })

        links = se.find_careers_links("测试公司", home, client=client)

        self.assertIn("https://www.example.com/join", [item["url"] for item in links])
        self.assertEqual(
            sum(url == home for url, _kwargs in client.calls),
            2,
        )

    def test_template_probe_never_exceeds_get_budget(self):
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
        self.assertLessEqual(len(client.calls), 24)


if __name__ == "__main__":
    unittest.main()


class LlmDomainFallbackTest(unittest.TestCase):
    """Wikidata + 库内 source 都空时必须用 LLM 补域名，否则整条官网通道形同虚设。

    2026-07-27 台账实锤：只有 Wikidata 一条来源时，一轮 45 家里 34 家掉回搜索通道、
    仅 10 家走官网通道（Wikidata 按中文名查 QID 命中率 ~58%）。
    """

    def setUp(self):
        se._LLM_DOMAIN_CACHE.clear()

    def tearDown(self):
        se._LLM_DOMAIN_CACHE.clear()

    def test_falls_back_to_llm_when_wikidata_and_sources_empty(self):
        with mock.patch.dict(logo_util.COMPANY_DOMAIN_OVERRIDES, {}, clear=True), \
             mock.patch.object(se.wikidata, "search_qid", return_value=None), \
             mock.patch.object(se, "resolve_official_site_by_llm", return_value="https://www.citics.com") as llm:
            out = se.resolve_official_site_details("中信证券", client=mock.Mock(), source_rows=[])
        self.assertEqual(out, {"home_url": "https://www.citics.com", "entry_channel": "llm_domain"})
        llm.assert_called_once_with("中信证券")

    def test_llm_result_is_cached_per_company(self):
        with mock.patch.object(se, "insight_engine", create=True):
            with mock.patch("insight_engine.chat_json", return_value={"site": "https://www.estun.com"}) as chat:
                first = se.resolve_official_site_by_llm("埃斯顿")
                second = se.resolve_official_site_by_llm("埃斯顿")
        self.assertEqual(first, "https://www.estun.com")
        self.assertEqual(second, "https://www.estun.com")
        self.assertEqual(chat.call_count, 1, "同一公司同一轮内只应问一次 LLM")

    def test_llm_disabled_by_env_returns_none(self):
        with mock.patch.dict(se.os.environ, {"GAP_FUNNEL_LLM_DOMAIN": "false"}):
            self.assertIsNone(se.resolve_official_site_by_llm("某公司"))

    def test_llm_failure_is_silent(self):
        with mock.patch("insight_engine.chat_json", side_effect=RuntimeError("no key")):
            self.assertIsNone(se.resolve_official_site_by_llm("某公司"))
