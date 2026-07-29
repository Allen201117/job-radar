import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import platform_fingerprint as pf


class _Response:
    def __init__(self, url, html, status_code=200):
        self.url = url
        self.text = html
        self.status_code = status_code


class _Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        return self.response


class DetectPlatformTest(unittest.TestCase):
    def test_detects_known_platforms_from_url_or_html(self):
        cases = [
            ("https://acme.mokahr.com/jobs", "", ("moka", "moka")),
            ("https://careers.acme.com", '<script src="https://acme.zhiye.com/app.js"></script>',
             ("beisen", "beisen")),
            ("https://careers.acme.com", '"https://acme.wd5.myworkdayjobs.com/jobs"',
             ("workday", "workday")),
            ("https://boards.greenhouse.io/acme", "", ("greenhouse", "greenhouse")),
            ("https://acme.italent.cn/career", "", ("beisen", "beisen")),
            ("https://www.iguopin.com/job?id=1", "", ("iguopin", "iguopin")),
        ]
        for url, html, expected in cases:
            with self.subTest(url=url, html=html):
                self.assertEqual(pf.detect_platform(url, html), expected)

    def test_detects_known_interface_path(self):
        html = '<script>fetch("/api/v1/search/job/posts")</script>'
        self.assertEqual(pf.detect_platform("https://jobs.acme.com", html), ("feishu", "feishu"))

    def test_does_not_trust_ats_name_inside_unrelated_host(self):
        self.assertEqual(
            pf.detect_platform("https://greenhouse.io.evil.example/jobs", ""),
            ("unknown", None),
        )

    def test_resolves_public_ats_pages_to_adapter_api_urls(self):
        cases = [
            (
                "greenhouse",
                "https://boards.greenhouse.io/acme/jobs/123",
                "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
            ),
            (
                "lever",
                "https://jobs.lever.co/acme/123",
                "https://api.lever.co/v0/postings/acme?mode=json",
            ),
            (
                "ashby",
                "https://jobs.ashbyhq.com/acme/123",
                "https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=true",
            ),
            (
                "smartrecruiters",
                "https://jobs.smartrecruiters.com/Acme/123-engineer",
                "https://api.smartrecruiters.com/v1/companies/Acme/postings?limit=100",
            ),
            (
                "workday",
                "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Shanghai/Engineer_1",
                "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External/jobs",
            ),
        ]
        for platform, public_url, expected in cases:
            with self.subTest(platform=platform):
                self.assertEqual(
                    pf.resolve_source_url(platform, public_url, ""), expected
                )

    def test_rejects_adapter_urls_missing_required_tenant_parameters(self):
        self.assertIsNone(
            pf.resolve_source_url(
                "oracle", "https://acme.fa.oraclecloud.com/hcmUI/CandidateExperience", ""
            )
        )
        self.assertIsNone(
            pf.resolve_source_url(
                "eightfold", "https://acme.eightfold.ai/careers", ""
            )
        )
        self.assertIsNone(
            pf.resolve_source_url("iguopin", "https://www.iguopin.com/job", "")
        )
        self.assertIsNone(
            pf.resolve_source_url("hotjob", "https://gimc.hotjob.cn", "")
        )

    def test_hotjob_requires_or_derives_a_suite_path(self):
        self.assertEqual(
            pf.resolve_source_url(
                "hotjob",
                "https://gimc.hotjob.cn/GIMC/pb/social.html",
                "",
            ),
            "https://gimc.hotjob.cn/GIMC/pb/social.html",
        )
        self.assertEqual(
            pf.resolve_source_url(
                "hotjob",
                "https://gimc.hotjob.cn",
                '<script>fetch("/wecruit/positionInfo/listPosition/GIMC")</script>',
            ),
            "https://gimc.hotjob.cn/GIMC/pb/social.html",
        )
        self.assertEqual(
            pf.resolve_source_url(
                "hotjob",
                "https://gimc.hotjob.cn/GIMC/pb/school.html",
                '<script>fetch("/wecruit/positionInfo/listPosition/GIMC")</script>',
            ),
            "https://gimc.hotjob.cn/GIMC/pb/school.html",
        )
        self.assertEqual(
            pf.resolve_source_url(
                "hotjob",
                "https://gimc.hotjob.cn/GIMC/pb/interns.html",
                '<script src="https://gimc.hotjob.cn/wecruit/positionInfo/listPosition/GIMC"></script>',
            ),
            "https://gimc.hotjob.cn/GIMC/pb/interns.html",
        )


class IdentityTest(unittest.TestCase):
    def test_identity_accepts_exact_name_and_safe_core_variant(self):
        exact = pf.verify_page_identity(
            "华策影视",
            "https://jobs.example.com",
            "<title>华策影视招聘</title><main>欢迎加入</main>",
        )
        core = pf.verify_page_identity(
            "利欧集团",
            "https://jobs.example.com",
            "<title>利欧招聘</title><main>社会招聘职位</main>",
        )
        self.assertTrue(exact[0])
        self.assertTrue(core[0])

    def test_identity_rejects_wrong_tenant_host_only_and_too_short_core(self):
        wrong = pf.verify_page_identity(
            "博纳影业",
            "https://gimc.hotjob.cn/GIMC/pb/social.html",
            "<title>省广集团 GIMC 招聘</title>",
        )
        host_only = pf.verify_page_identity(
            "华谊兄弟",
            "https://huayimedia.example.com/recruit",
            "<title>社会招聘</title><main>开放岗位</main>",
        )
        short_core = pf.verify_page_identity(
            "甲公司",
            "https://jobs.example.com",
            "<title>甲招聘</title>",
        )
        self.assertFalse(wrong[0])
        self.assertFalse(host_only[0])
        self.assertFalse(short_core[0])

    def test_fingerprint_reuses_its_single_get_for_identity(self):
        url = "https://acme.mokahr.com/social-recruitment/acme/1"
        client = _Client(_Response(url, "<title>Acme 招聘</title>"))
        result = pf.fingerprint(url, company="Acme", client=client)
        self.assertTrue(result["identity_ok"])
        self.assertIn("page_company_match", result["identity_reason"])
        self.assertEqual(len(client.calls), 1)

    def test_fingerprint_marks_wrong_company_page(self):
        url = "https://gimc.hotjob.cn/GIMC/pb/social.html"
        client = _Client(_Response(url, "<title>省广集团招聘</title>"))
        result = pf.fingerprint(url, company="博纳影业", client=client)
        self.assertFalse(result["identity_ok"])
        self.assertEqual(result["identity_reason"], "page_company_not_found")


class SpecialStateTest(unittest.TestCase):
    def test_detects_waf(self):
        self.assertEqual(
            pf.detect_page_state(403, "<html>Access Denied</html>"), "anti_bot"
        )
        self.assertEqual(
            pf.detect_page_state(200, "<title>Cloudflare challenge</title>"), "anti_bot"
        )

    def test_detects_login_wall(self):
        html = '<form><input type="password" name="password"><button>登录</button></form>'
        self.assertEqual(pf.detect_page_state(200, html), "login_wall")

    def test_detects_unknown_spa(self):
        self.assertEqual(
            pf.detect_page_state(200, '<html><div id="app"></div></html>'), "unknown_spa"
        )

    def test_identity_matched_recruiting_page_without_known_ats_is_unknown_spa(self):
        url = "https://careers.example.com/jobs"
        html = """
        <title>甲公司人才招聘</title>
        <main>
          <h1>社会招聘</h1>
          <div class="job-list"><a href="/job-detail/1">工程师职位详情</a></div>
        </main>
        """

        result = pf.fingerprint(
            url,
            company="甲公司",
            client=_Client(_Response(url, html)),
        )

        self.assertTrue(result["identity_ok"])
        self.assertEqual(result["platform"], "unknown_spa")
        self.assertIsNone(result["adapter"])
        self.assertEqual(result["source_url"], url)

    def test_detects_pdf_only_notice(self):
        html = '<h1>招聘公告</h1><a href="/notice.pdf">岗位附件 PDF</a>'
        self.assertEqual(pf.detect_page_state(200, html), "no_stable_jd")


if __name__ == "__main__":
    unittest.main()
