import unittest
from datetime import date

from announcements.portals import (
    PORTALS_BY_KEY,
    host_in_whitelist,
    parse_list,
    published_from_url,
)


class TestHostWhitelist(unittest.TestCase):
    def setUp(self):
        self.bj = PORTALS_BY_KEY["bj_rsj"]

    def test_official_host_ok(self):
        self.assertTrue(host_in_whitelist(
            self.bj, "https://rsj.beijing.gov.cn/xxgk/gkzp/202609/t20260914_1.html"))

    def test_foreign_host_rejected(self):
        # 归属门：非官方域名一律拒（防张冠李戴）
        self.assertFalse(host_in_whitelist(self.bj, "https://offcn.com/beijing/1.html"))

    def test_lookalike_subdomain_rejected(self):
        # rsj.beijing.gov.cn.evil.com 不是官方域名
        self.assertFalse(host_in_whitelist(
            self.bj, "https://rsj.beijing.gov.cn.evil.com/x.html"))


class TestPublishedFromUrl(unittest.TestCase):
    def test_beijing_url_has_date(self):
        self.assertEqual(
            published_from_url("https://rsj.beijing.gov.cn/xxgk/gkzp/202609/t20260914_4863253.html"),
            date(2026, 9, 14))

    def test_guangdong_url_no_date(self):
        self.assertIsNone(
            published_from_url("https://hrss.gd.gov.cn/zwgk/sydwzp/zpgg/content/post_4848983.html"))


class TestParseList(unittest.TestCase):
    def test_filters_by_host_and_content(self):
        bj = PORTALS_BY_KEY["bj_rsj"]
        html = """
        <ul>
          <li><a href="./202609/t20260914_1.html">北京水利医院2026年公开招聘工作人员公告</a></li>
          <li><a href="./202609/t20260914_2.html">某单位2026年公开招聘笔试成绩公告</a></li>
          <li><a href="https://offcn.com/x.html">北京事业单位招聘公告（第三方转载）</a></li>
          <li><a href="/index.html">首页</a></li>
          <li><a href="./202609/t20260914_3.html">首都医科大学2026年人才引进公告</a></li>
        </ul>
        """
        items = parse_list(bj, bj.list_urls[0], html)
        titles = [it.title for it in items]
        # 只保留：官方域名 + 可报名公告；剔除成绩公告、第三方域名、导航链接
        self.assertIn("北京水利医院2026年公开招聘工作人员公告", titles)
        self.assertIn("首都医科大学2026年人才引进公告", titles)
        self.assertNotIn("某单位2026年公开招聘笔试成绩公告", titles)
        self.assertNotIn("北京事业单位招聘公告（第三方转载）", titles)
        self.assertEqual(len(items), 2)
        # 北京 URL 自带发布日期
        self.assertEqual(items[0].published_at, date(2026, 9, 14))


if __name__ == "__main__":
    unittest.main()
