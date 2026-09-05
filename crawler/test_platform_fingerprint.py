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

    def test_normal_page_without_job_data_is_never_anti_bot(self):
        """页面正常打开、只是这一页没有岗位数据 —— 那是**我们站错了页**，不是对方拒了我们。

        2026-09-04 台账里 21 家必投公司被标 anti_bot，逐个核查全部只是漏斗停在
        「公司官网的招聘介绍页」上；2026-09-05 复测其中 8 家入口全是 HTTP 200 零拦截信号。
        这个标签把排查方向带去了「怎么绕反爬」，巴斯夫、壳牌各空撞 30 次。
        """
        intro = "<title>某集团招聘</title><h1>加入我们</h1><p>人才理念与招聘流程介绍</p>"
        self.assertIsNone(pf.detect_block_signal(200, intro))
        self.assertNotEqual(pf.detect_page_state(200, intro), "anti_bot")

    def test_job_content_mentioning_akamai_denied_is_not_anti_bot(self):
        """裸子串判据的实测假阳性：greenhouse 的 hasbro job board（HTTP 200 的正常岗位 JSON）
        因为岗位正文提到 Akamai、条款里出现 denied 被判反爬（2026-09-05，105 个健康页面里 1 个）。"""
        board = (
            '{"jobs":[{"title":"Senior Engineer","content":"Experience with '
            'Akamai CDN required. Requests may be denied at the edge."}]}'
        )
        self.assertIsNone(pf.detect_block_signal(200, board))

    def test_login_form_captcha_wording_is_not_anti_bot(self):
        """『验证码』在 41/105（39%）健康线上页面里出现——北森/Moka 门户的登录框本来就带短信验证码。
        所以它永远不能单独作为反爬判据。"""
        portal = (
            "<title>某公司社会招聘</title><h1>在招职位</h1>"
            "<form><input name='code' placeholder='请输入短信验证码'></form>"
        )
        self.assertIsNone(pf.detect_block_signal(200, portal))

    def test_spa_noscript_notice_is_spa_not_anti_bot(self):
        """<noscript> 的『请开启 JavaScript』是所有 SPA 的兜底文案，是「这页要 JS」不是「对方拒了我们」。"""
        shell = (
            '<html><body><noscript>请开启JavaScript后继续</noscript>'
            '<div id="app"></div></body></html>'
        )
        self.assertIsNone(pf.detect_block_signal(200, shell))
        self.assertEqual(pf.detect_page_state(200, shell), "unknown_spa")

    def test_real_block_pages_still_detected(self):
        self.assertEqual(
            pf.detect_block_signal(200, "<title>Access Denied</title>"
                                        "<p>You don't have permission to access this resource.</p>"),
            "anti_bot",
        )
        self.assertEqual(
            pf.detect_block_signal(
                200, '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1"></script>'
            ),
            "anti_bot",
        )
        for status in (403, 412, 503):
            self.assertEqual(pf.detect_block_signal(status, "<html></html>"), "anti_bot")

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


class ResolveSourceUrlPriorityTest(unittest.TestCase):
    """final_url 必须优先于 HTML 里扫出来的同域 URL。

    实测（2026-08-26）万泰生物的 moka 源地址被解析成
    sentry-fe.mokahr.com/api/107/store/ —— 前端错误监控 SDK 的上报地址，
    host 恰好含 mokahr.com 就被当成了招聘列表地址，P2 拿它抓到 0 个岗。
    第三方 SDK / CDN / 静态资源普遍挂在主域下，这类污染是常态而非个例。
    """

    def test_final_url_wins_over_same_domain_sdk_noise(self):
        html = (
            '<script src="https://sentry-fe.mokahr.com/api/107/store/'
            '?sentry_version=7&sentry_client=raven-js"></script>'
        )
        self.assertEqual(
            pf.resolve_source_url(
                "moka",
                "https://app.mokahr.com/social-recruitment/ystwt/97880",
                html,
            ),
            "https://app.mokahr.com/social-recruitment/ystwt/97880",
        )

    def test_html_still_used_when_final_url_is_not_the_platform(self):
        """final_url 判不出平台时，仍从 HTML 里找——原有兜底行为不能退化。"""
        html = '<a href="https://acme.zhiye.com/social/jobs">招聘</a>'
        self.assertEqual(
            pf.resolve_source_url(
                "beisen", "https://www.acme.com/careers", html
            ),
            "https://acme.zhiye.com/social/jobs",
        )


if __name__ == "__main__":
    unittest.main()


class _MultiClient:
    """按 URL 返回不同响应，用于测「再跳一跳」。"""

    def __init__(self, by_url):
        self.by_url = by_url
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(url)
        for key, resp in self.by_url.items():
            if url.startswith(key):
                return resp
        return _Response(url, "", status_code=404)


class CareersSubdomainHopTest(unittest.TestCase):
    """公司官网的招聘栏目页 ≠ 岗位所在地。

    2026-09-04 台账实证：no_stable_jd 52 家里 51 家判 unknown_spa，其中 5 家当天被人工接通，
    形态一致 —— 漏斗停在介绍页上等岗位数据，而岗位在自家招聘子域上，
    由那个子域的 302 落到真正的 ATS（掌阅 jobs.zhangyue.com→飞书、壳牌 jobs.shell.com→Workday）。
    巴斯夫与壳牌各因此空撞 30 次，还被误标成 anti_bot。
    """

    def test_picks_own_careers_subdomain(self):
        html = '<a href="https://jobs.zhangyue.com/list">社会招聘</a>'
        self.assertEqual(
            pf.find_careers_subdomain_hops(html, "http://www.zhangyue.com/careers"),
            ["https://jobs.zhangyue.com/"],
        )

    def test_handles_two_level_tld(self):
        """campus.10jqka.com.cn 与 job.10jqka.com.cn 是同一主域，别被 .com.cn 骗了。"""
        html = '<a href="https://campus.10jqka.com.cn/job/list">校园招聘</a>'
        self.assertEqual(
            pf.find_careers_subdomain_hops(html, "https://job.10jqka.com.cn/"),
            ["https://campus.10jqka.com.cn/"],
        )

    def test_ignores_self_other_domains_and_non_careers_subdomains(self):
        html = (
            '<a href="https://www.acme.com/about">关于我们</a>'
            '<a href="https://news.acme.com/2026">新闻</a>'
            '<a href="https://jobs.other.com/x">别家的职位</a>'
            '<a href="https://careers.acme.com/list">职位</a>'
        )
        self.assertEqual(
            pf.find_careers_subdomain_hops(html, "https://www.acme.com/careers"),
            ["https://careers.acme.com/"],
        )

    def test_fingerprint_follows_subdomain_hop_that_redirects_to_ats(self):
        """子域本身不是已知 ATS，价值全在跟过去、让它的 302 把我们带到 ATS。"""
        entry = _Response(
            "http://www.zhangyue.com/careers",
            '招聘 职位 <a href="https://jobs.zhangyue.com/">社会招聘</a>',
        )
        # 跟过去后落在飞书租户上（httpx follow_redirects 后 final_url 已是飞书）
        hopped = _Response("https://q7w8vltyes.jobs.feishu.cn/index/position", "<html></html>")
        client = _MultiClient({
            "http://www.zhangyue.com": entry,
            "https://jobs.zhangyue.com": hopped,
        })
        out = pf.fingerprint("http://www.zhangyue.com/careers", company="掌阅科技", client=client)
        self.assertEqual(out["platform"], "feishu")
        self.assertEqual(out["adapter"], "feishu")
        self.assertTrue(str(out["reason"]).startswith("careers_subdomain_hop_from:"))

    def test_hop_never_runs_when_platform_already_recognized(self):
        """已认出 ATS 的页面不该再跳 —— 这一步只许把 unknown 变成已知，不许反向。"""
        resp = _Response(
            "https://acme.mokahr.com/jobs", '<a href="https://careers.acme.com/x">职位</a>'
        )
        client = _MultiClient({"https://acme.mokahr.com": resp})
        out = pf.fingerprint("https://acme.mokahr.com/jobs", company="Acme", client=client)
        self.assertEqual(out["platform"], "moka")
        self.assertEqual(client.calls, ["https://acme.mokahr.com/jobs"])

    def test_hop_does_not_recurse_beyond_one_level(self):
        """跳一次就够；再跳下去会把「介绍页互相链接」变成爬全站。"""
        page = _Response(
            "https://a.example.com/careers",
            '招聘 职位 <a href="https://careers.example.com/x">职位</a>',
        )
        client = _MultiClient({"https://": page})
        pf.fingerprint("https://a.example.com/careers", company="Example", client=client)
        self.assertLessEqual(len(client.calls), 5)
