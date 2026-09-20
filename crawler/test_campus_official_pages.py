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


class FetchFirstWithSignalGate(unittest.TestCase):
    """门必须判在「模型真正会看到的那份文本」上，不是原始 HTML（2026-09-20 修的真 bug）。

    现象：SPA 空壳的日期信号只藏在内联 JSON / 表单占位符里，`.text()` 会把 script 丢掉，
    于是门放行、正文里一个日期都没有 → LLM 每天空转一次、每天 0 条 claim，
    而且这种候选排在前面还会把后面真正有公告正文的候选挡掉。
    """

    # 长度门 min_len=4000，所以壳要够大；日期信号只出现在 <script> 里。
    SPA_SHELL = ("<html><head><script>var i18n={\"placeholder\":\"请输入截止日期\"};"
                 + "var pad='" + "x" * 5000 + "';</script></head>"
                 + "<body><div id=app>You need to enable JavaScript to run this app.</div></body></html>")
    REAL_PAGE = ("<html><body><h1>2027 届校园招聘</h1><p>网申截止时间：9月30日</p>"
                 + "<p>" + "正文" * 2000 + "</p></body></html>")

    def _patched(self, pages):
        """把 httpx.get 换成按 url 取 (status, html) 的假实现；不打真实网络。"""
        import campus_official_pages as mod

        class _Resp:
            def __init__(self, status, text):
                self.status_code, self.text = status, text

        def fake_get(url, **_kw):
            status, html = pages[url]
            return _Resp(status, html)

        return mod, fake_get

    def test_skips_candidate_whose_date_only_lives_in_script(self):
        mod, fake_get = self._patched({
            "https://a.example/campus": (200, self.SPA_SHELL),
            "https://b.example/campus": (200, self.REAL_PAGE),
        })
        real_get = mod.httpx.get
        mod.httpx.get = fake_get
        try:
            url, text = mod.fetch_first_with_signal(
                ["https://a.example/campus", "https://b.example/campus"])
        finally:
            mod.httpx.get = real_get
        self.assertEqual(url, "https://b.example/campus",
                         "空壳候选必须让位给真正有正文日期的候选，不能当场 return")
        self.assertIn("9月30日", text)

    def test_all_candidates_script_only_returns_nothing(self):
        mod, fake_get = self._patched({"https://a.example/campus": (200, self.SPA_SHELL)})
        real_get = mod.httpx.get
        mod.httpx.get = fake_get
        try:
            url, text = mod.fetch_first_with_signal(["https://a.example/campus"])
        finally:
            mod.httpx.get = real_get
        self.assertIsNone(url, "正文里没有日期就不该交给 LLM 去空转")
        self.assertEqual(text, "")

    def test_raw_html_gate_still_short_circuits_tiny_shells(self):
        # 小壳连长度门都过不了，压根不该走到解析正文这一步（保持原有廉价预筛行为）。
        self.assertFalse(has_date_signal("<html>网申 9月10日</html>"))


if __name__ == "__main__":
    unittest.main()
