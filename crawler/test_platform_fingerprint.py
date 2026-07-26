import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import platform_fingerprint as pf


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

    def test_detects_pdf_only_notice(self):
        html = '<h1>招聘公告</h1><a href="/notice.pdf">岗位附件 PDF</a>'
        self.assertEqual(pf.detect_page_state(200, html), "no_stable_jd")


if __name__ == "__main__":
    unittest.main()
