import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from robots import _parse_robots


class TestParseRobots(unittest.TestCase):
    def test_allow_overrides_broad_disallow_longest_match(self):
        # Microsoft 形态：Disallow: / 但显式 Allow: /api/pcsx → 更长的 Allow 生效。
        txt = (
            "User-agent: *\n"
            "Disallow: /\n"
            "Allow: /$\n"
            "Allow: /careers\n"
            "Allow: /api/pcsx\n"
        )
        self.assertTrue(_parse_robots(txt, "/api/pcsx/search")["allowed"])
        self.assertTrue(_parse_robots(txt, "/careers")["allowed"])
        # 未被任何 Allow 覆盖的路径仍被 Disallow: / 拦下
        self.assertFalse(_parse_robots(txt, "/secret/admin")["allowed"])

    def test_disallow_all(self):
        txt = "User-agent: *\nDisallow: /\n"
        self.assertFalse(_parse_robots(txt, "/anything")["allowed"])
        self.assertFalse(_parse_robots(txt, "/")["allowed"])

    def test_specific_disallow(self):
        txt = "User-agent: *\nDisallow: /private\n"
        self.assertFalse(_parse_robots(txt, "/private/x")["allowed"])
        self.assertTrue(_parse_robots(txt, "/public/jobs")["allowed"])

    def test_dollar_anchor_exact(self):
        # Allow: /$ 只精确匹配根路径，不覆盖子路径。
        txt = "User-agent: *\nDisallow: /\nAllow: /$\n"
        self.assertTrue(_parse_robots(txt, "/")["allowed"])
        self.assertFalse(_parse_robots(txt, "/jobs")["allowed"])

    def test_empty_disallow_means_allow_all(self):
        txt = "User-agent: *\nDisallow:\n"
        self.assertTrue(_parse_robots(txt, "/anything")["allowed"])

    def test_no_rules_allow(self):
        self.assertTrue(_parse_robots("# just a comment\n", "/x")["allowed"])

    def test_named_group_takes_precedence_over_star(self):
        # 具名 JobRadarBot 组存在时只用该组（这里具名组放行根下全部）。
        txt = (
            "User-agent: *\n"
            "Disallow: /\n"
            "\n"
            "User-agent: JobRadarBot\n"
            "Disallow: /admin\n"
        )
        self.assertTrue(_parse_robots(txt, "/jobs")["allowed"])
        self.assertFalse(_parse_robots(txt, "/admin/x")["allowed"])

    def test_equal_length_allow_wins(self):
        txt = "User-agent: *\nDisallow: /api\nAllow: /api\n"
        self.assertTrue(_parse_robots(txt, "/api/x")["allowed"])


class PublicApiAllowlistTest(unittest.TestCase):
    """厂商文档公开 API 白名单：不发网络请求即放行，且不得外溢到其它 host/路径。"""

    def test_smartrecruiters_posting_api_allowed_without_network(self):
        from robots import check_robots
        result = check_robots("https://api.smartrecruiters.com/v1/companies/grab/postings?limit=100")
        self.assertTrue(result["allowed"])
        self.assertIn("public API", result["reason"])

    def test_allowlist_does_not_leak_to_other_paths_or_hosts(self):
        from robots import _public_api_allowed
        self.assertFalse(_public_api_allowed("api.smartrecruiters.com", "/v2/other"))
        self.assertFalse(_public_api_allowed("www.smartrecruiters.com", "/v1/companies/x"))


class RobotsCacheTest(unittest.TestCase):
    def test_same_host_different_paths_fetches_robots_once(self):
        import robots

        robots._ROBOTS_CACHE.clear()
        response = mock.Mock(status_code=200, text="User-agent: *\nDisallow:\n")
        with mock.patch.object(robots.httpx, "get", return_value=response) as get:
            self.assertTrue(robots.check_robots("https://careers.example/jobs")["allowed"])
            self.assertTrue(robots.check_robots("https://careers.example/campus")["allowed"])

        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class TestWildcardAndQuery(unittest.TestCase):
    """F6 回归：`*` 通配与 query 参与匹配。

    修复前 `*` 被当普通字符字面比较，`Disallow: /*.pdf$` 退化成「路径恰好等于 /*.pdf」→
    永远匹配不上 → `/jobs/cv.pdf` 被错误放行。方向上这次改动只会「多拦」不会「少拦」。
    """

    def test_wildcard_suffix_anchor_blocks_pdf(self):
        txt = "User-agent: *\nDisallow: /*.pdf$\n"
        self.assertFalse(_parse_robots(txt, "/jobs/cv.pdf")["allowed"])
        self.assertTrue(_parse_robots(txt, "/jobs/cv.html")["allowed"])

    def test_wildcard_anchor_does_not_block_when_suffix_differs(self):
        txt = "User-agent: *\nDisallow: /*.pdf$\n"
        self.assertTrue(_parse_robots(txt, "/jobs/cv.pdf.html")["allowed"])

    def test_wildcard_in_middle(self):
        txt = "User-agent: *\nDisallow: /admin/*/secret\n"
        self.assertFalse(_parse_robots(txt, "/admin/a/secret")["allowed"])
        self.assertFalse(_parse_robots(txt, "/admin/a/b/secret/x")["allowed"])
        self.assertTrue(_parse_robots(txt, "/admin/secret")["allowed"])

    def test_query_participates_in_match(self):
        txt = "User-agent: *\nDisallow: /*?sort=\n"
        self.assertFalse(_parse_robots(txt, "/jobs", "sort=date")["allowed"])
        self.assertTrue(_parse_robots(txt, "/jobs", "page=2")["allowed"])

    def test_anchored_rule_still_blocks_when_query_present(self):
        # 刻意比规范保守：规范只匹配 path+query 会放行 /private?x=1，这里仍拦。
        txt = "User-agent: *\nDisallow: /private$\n"
        self.assertFalse(_parse_robots(txt, "/private", "x=1")["allowed"])

    def test_allow_longer_wildcard_rule_wins(self):
        txt = "User-agent: *\nDisallow: /\nAllow: /api/*/search\n"
        self.assertTrue(_parse_robots(txt, "/api/pcsx/search")["allowed"])
        self.assertFalse(_parse_robots(txt, "/api/pcsx/list")["allowed"])
