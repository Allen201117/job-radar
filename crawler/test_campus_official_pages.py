import unittest

from campus_official_pages import official_campus_urls, has_date_signal, html_to_text


class OfficialCampusUrls(unittest.TestCase):
    def test_prefers_source_url_then_host_variants(self):
        rows = [{"source_url": "https://jobs.bytedance.com/campus/position"}]
        hosts = {"jobs.bytedance.com"}
        urls = official_campus_urls(rows, hosts, cap=5)
        self.assertEqual(urls[0], "https://jobs.bytedance.com/campus/position")
        self.assertIn("https://jobs.bytedance.com/campus", urls)
        self.assertLessEqual(len(urls), 5)

    def test_dedup_and_cap(self):
        rows = [{"source_url": "https://jobs.bytedance.com/campus"}]
        urls = official_campus_urls(rows, {"jobs.bytedance.com"}, cap=3)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertLessEqual(len(urls), 3)

    def test_no_hosts_empty(self):
        self.assertEqual(official_campus_urls([], set()), [])


class HasDateSignal(unittest.TestCase):
    def test_spa_shell_rejected_by_length(self):
        self.assertFalse(has_date_signal("<html>网申 9月10日</html>", min_len=4000))

    def test_ssr_page_with_date_accepted(self):
        html = "x" * 5000 + "网申截止时间 2026年9月10日"
        self.assertTrue(has_date_signal(html, min_len=4000))

    def test_long_page_without_date_rejected(self):
        self.assertFalse(has_date_signal("y" * 5000, min_len=4000))


class HtmlToText(unittest.TestCase):
    def test_strips_tags_and_blank_lines(self):
        t = html_to_text("<div>网申时间</div>\n\n<p>9月10日</p>", cap=6000)
        self.assertIn("网申时间", t)
        self.assertIn("9月10日", t)
        self.assertNotIn("<div>", t)


if __name__ == "__main__":
    unittest.main()
