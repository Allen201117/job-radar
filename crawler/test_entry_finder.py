import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entry_finder as ef


class CandidateClassificationTest(unittest.TestCase):
    def test_rejects_third_party_and_content_sites(self):
        for url in (
            "https://www.zhaopin.com/job/1",
            "https://www.liepin.com/job/2",
            "https://www.linkedin.com/jobs/view/1",
            "https://www.nowcoder.com/jobs/1",
            "https://mp.weixin.qq.com/s/abc",
            "https://job.ncss.cn/jobs/1",
            "https://baike.baidu.com/item/acme",
            "https://www.zhihu.com/question/1",
            "https://news.163.com/article/1.html",
        ):
            with self.subTest(url=url):
                verdict, score, _ = ef.classify_candidate_url(url, "Acme")
                self.assertEqual(verdict, "reject")
                self.assertLess(score, 0)

    def test_rejects_company_registry_sites(self):
        """企业工商信息站不是招聘入口（华谊兄弟/柠萌影业/正午阳光曾被判到爱企查上）。"""
        for url in (
            "https://aiqicha.baidu.com/details/rankList?query=abc&type=20",
            "https://aiqicha.baidu.com/details/ugknowledge?id=abc",
            "https://www.qcc.com/firm/abc.html",
            "https://www.tianyancha.com/company/123",
            "https://www.qixin.com/company/abc",
            # 牛企招聘：赛力斯/福耀玻璃曾被判到这里
            "https://jobs.niuqizp.com/job-vyY5NzZM5.html",
        ):
            with self.subTest(url=url):
                verdict, score, reason = ef.classify_candidate_url(url, "华谊兄弟")
                self.assertEqual(verdict, "reject")
                self.assertLess(score, 0)
                self.assertIn(reason, ("content_site", "third_party_job_platform"))

    def test_rejects_institutional_aggregator_and_government_hosts(self):
        cases = {
            "https://job.mju.edu.cn/campus/view/id/976181": "institutional_host",
            "https://careers.example.edu/jobs/1": "institutional_host",
            "https://m.nj.bendibao.com/job/179796.shtm": "aggregator_site",
            "https://www.gaoxiaojob.com/announcement/1": "aggregator_site",
            "https://rsj.example.gov.cn/recruit/1": "government_notice",
        }
        for url, expected_reason in cases.items():
            with self.subTest(url=url):
                verdict, score, reason = ef.classify_candidate_url(url, "甲公司")
                self.assertEqual(verdict, "reject")
                self.assertLess(score, 0)
                self.assertEqual(reason, expected_reason)

    def test_iguopin_only_accepts_company_scoped_job_page(self):
        accepted = ef.classify_candidate_url(
            "https://www.iguopin.com/job?company=视觉中国", "视觉中国"
        )
        rejected = ef.classify_candidate_url(
            "https://www.iguopin.com/job/list?keyword=视觉设计", "视觉中国"
        )
        self.assertEqual(accepted[0], "trusted_ats")
        self.assertEqual(rejected, ("reject", -100, "iguopin_search_page"))

    def test_known_ats_and_iguopin_are_trusted(self):
        for url in (
            "https://acme.jobs.mokahr.com/social-recruitment/acme/1",
            "https://acme.wd5.myworkdayjobs.com/en-US/jobs",
            "https://www.iguopin.com/job?company=国家电网",
        ):
            with self.subTest(url=url):
                verdict, score, _ = ef.classify_candidate_url(url, "Acme")
                self.assertEqual(verdict, "trusted_ats")
                self.assertGreaterEqual(score, 90)

    def test_job_path_is_likely_official(self):
        verdict, score, _ = ef.classify_candidate_url(
            "https://www.acme.com/careers/jobs", "Acme"
        )
        self.assertEqual(verdict, "likely_official")
        self.assertGreater(score, 0)

    def test_ats_name_inside_unrelated_host_is_not_trusted(self):
        verdict, _score, _reason = ef.classify_candidate_url(
            "https://mokahr.com.evil.example/jobs", "Acme"
        )
        self.assertNotEqual(verdict, "trusted_ats")


class _Provider:
    def __init__(self, name, responses, remaining=10):
        self.name = name
        self.responses = list(responses)
        self.left = remaining
        self.calls = []
        self.consumed = 0

    def is_configured(self):
        return True

    def remaining(self, _sb):
        return self.left

    def consume(self, _sb, n=1):
        self.consumed += n

    def search(self, query, top_k=8, client=None):
        self.calls.append((query, top_k, client))
        response = self.responses.pop(0) if self.responses else []
        if isinstance(response, Exception):
            raise response
        return response


class _Router:
    def __init__(self, providers):
        self.providers = providers


class CascadeSearchTest(unittest.TestCase):
    def test_first_trusted_result_stops_before_second_provider(self):
        qianfan = _Provider(
            "qianfan",
            [[{"url": "https://acme.mokahr.com/social-recruitment/acme/1"}]],
        )
        serper = _Provider("serper", [[{"url": "https://www.acme.com/careers"}]])
        result = ef.find_official_entry("Acme", object(), router=_Router([serper, qianfan]))
        self.assertTrue(result["found"])
        self.assertEqual(len(qianfan.calls), 1)
        self.assertEqual(len(serper.calls), 0)
        self.assertEqual(result["search_used"], 1)
        self.assertEqual(
            [item["url"] for item in result["candidates"]],
            ["https://acme.mokahr.com/social-recruitment/acme/1"],
        )

    def test_never_uses_more_than_two_searches(self):
        qianfan = _Provider("qianfan", [[]])
        serper = _Provider("serper", [[], [{"url": "https://unused.example/jobs"}]])
        result = ef.find_official_entry("Acme", object(), router=_Router([serper, qianfan]))
        self.assertFalse(result["found"])
        self.assertEqual(len(qianfan.calls) + len(serper.calls), 2)
        self.assertEqual(result["search_used"], 2)
        self.assertEqual(qianfan.calls[0][0], "Acme 招聘 官网")
        self.assertEqual(serper.calls[0][0], "Acme 社会招聘 职位")

    def test_no_result_increments_rounds_and_promotes_governance(self):
        provider = _Provider("qianfan", [[]])
        fallback = _Provider("serper", [[]])
        first = ef.find_official_entry(
            "Acme", object(), router=_Router([provider, fallback]),
            prev_row={"rounds_no_entry": 0},
        )
        self.assertEqual(first["state"], "no_official_entry")
        self.assertEqual(first["rounds_no_entry"], 1)

        provider2 = _Provider("qianfan", [[]])
        fallback2 = _Provider("tavily", [[]])
        second = ef.find_official_entry(
            "Acme", object(), router=_Router([provider2, fallback2]), prev_row=first
        )
        self.assertEqual(second["state"], "governance_candidate")
        self.assertEqual(second["rounds_no_entry"], 2)
        self.assertIsNone(second["next_retry_at"])

    def test_no_available_provider_does_not_count_as_no_entry_round(self):
        result = ef.find_official_entry(
            "Acme", object(), router=_Router([]), prev_row={"rounds_no_entry": 1}
        )
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["rounds_no_entry"], 1)
        self.assertEqual(result["search_used"], 0)

    def test_successful_search_consumes_provider_usage_by_default(self):
        provider = _Provider(
            "qianfan",
            [[{"url": "https://acme.mokahr.com/social-recruitment/acme/1"}]],
        )
        result = ef.find_official_entry(
            "Acme", object(), router=_Router([provider])
        )
        self.assertTrue(result["found"])
        self.assertEqual(provider.consumed, 1)
        self.assertEqual(result["search_used"], 1)

    def test_failed_search_does_not_consume_provider_usage(self):
        provider = _Provider("qianfan", [RuntimeError("provider unavailable")])
        result = ef.find_official_entry(
            "Acme", object(), router=_Router([provider]), max_searches=1
        )
        self.assertFalse(result["found"])
        self.assertEqual(provider.consumed, 0)
        self.assertEqual(result["search_used"], 0)
        self.assertIn("provider unavailable", result["evidence"]["search_errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()


class CareerSubdomainSignalTest(unittest.TestCase):
    """招聘子域本身算官方信号——不然中文名公司的官方招聘站会被误杀。

    2026-07-26 实测：careers.midea.com（美的官方招聘站）路径是根「/」、公司名「美的集团」
    又切不出 latin 词 → 老逻辑判 insufficient_official_signal 直接丢掉。真正判「这页是不是
    这家公司」的是 fingerprint 里的页面身份门，这一层放宽是安全的。
    """

    def test_career_subdomain_accepted_for_chinese_named_company(self):
        for url, company in [
            ("https://careers.midea.com", "美的集团"),
            ("https://hr.zto.com", "中通"),
            ("https://job.icbc.com.cn", "工商银行"),
            ("https://zhaopin.jd.com", "京东"),
        ]:
            verdict, score, reason = ef.classify_candidate_url(url, company)
            self.assertEqual(verdict, "likely_official", url)
            self.assertGreater(score, 0, url)
            self.assertIn("career_subdomain", reason, url)

    def test_blacklists_still_win_over_career_subdomain(self):
        # host 前缀像招聘站，但属于高校就业网 / 资讯聚合站 / 第三方平台 → 仍然拒
        for url, company in [
            ("http://job.mju.edu.cn/campus/view/id/1", "利欧集团"),
            ("https://m.nj.bendibao.com/job/179796.shtm", "凤凰传媒"),
            ("https://job.zhaopin.com/x", "某公司"),
        ]:
            self.assertEqual(ef.classify_candidate_url(url, company)[0], "reject", url)
