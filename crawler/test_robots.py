import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
