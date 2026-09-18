import contextlib
import io
import unittest
from unittest import mock
from datetime import date

import json

from announcements.portals import (
    PORTALS_BY_KEY,
    _clean_title,
    detail_text,
    host_in_whitelist,
    parse_list,
    published_from_url,
)
from announcements import harvest


class TestCleanTitle(unittest.TestCase):
    def test_strips_trailing_date(self):
        # 山东列表项文字尾随发布日期，要清掉再当标题
        self.assertEqual(
            _clean_title("《山东商报》社2026年公开招聘人员公告2026-09-11"),
            "《山东商报》社2026年公开招聘人员公告")

    def test_collapses_whitespace(self):
        self.assertEqual(_clean_title("  北京水利医院\n2026年 公开招聘公告 "),
                         "北京水利医院 2026年 公开招聘公告")

    def test_keeps_year_in_title(self):
        # 只去尾随完整日期，不动标题里的年份
        self.assertEqual(_clean_title("2026年公开招聘公告"), "2026年公开招聘公告")


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


class TestScriptJsonList(unittest.TestCase):
    """江西：列表数据不在 <a href> 里，而在 <script>var listData = {articleList:[...]}> JSON 里。"""

    def _html(self, items: list[dict]) -> str:
        # 忠实复刻线上形态：articleList 键未加引号（整块不是合法 JSON），urls 是**字符串化**的 JSON。
        import json
        arr = ",".join(
            '{"title":%s,"pubDate":%s,"urls":%s}' % (
                json.dumps(it["title"], ensure_ascii=False),
                json.dumps(it["pubDate"], ensure_ascii=False),
                json.dumps(json.dumps({"pc": it["pc"]}), ensure_ascii=False),
            )
            for it in items
        )
        return "<script>var listData = { articleList: [%s] };</script>" % arr

    def test_parses_json_and_applies_gates(self):
        jx = PORTALS_BY_KEY["jx_rst"]
        html = self._html([
            {"title": "江西师范大学2026年公开招聘工作人员公告",
             "pubDate": "2026-07-07 16:04",
             "pc": "/jxsrlzyhshbzt/col/col85519/content/content_111.html"},
            {"title": "江西省2026年中小学教师招聘进入面试人员名单公告",  # 名单 → classify 剔除
             "pubDate": "2026-06-24 15:53",
             "pc": "/jxsrlzyhshbzt/col/col85519/content/content_222.html"},
            {"title": "某第三方转载2026年公开招聘公告",  # 非官方域名 → 归属门剔除
             "pubDate": "2026-06-24 00:00",
             "pc": "https://offcn.com/content_333.html"},
        ])
        items = parse_list(jx, jx.list_urls[0], html)
        titles = [it.title for it in items]
        self.assertEqual(titles, ["江西师范大学2026年公开招聘工作人员公告"])
        # pubDate 直接给发布日期（优于 URL 推断）
        self.assertEqual(items[0].published_at, date(2026, 7, 7))
        self.assertTrue(items[0].url.endswith("/content/content_111.html"))

    def test_missing_articlelist_raises(self):
        # 形态变了（找不到 articleList）必须抛错 → 让 harvest 记 list_errors，别静默 0 产出。
        jx = PORTALS_BY_KEY["jx_rst"]
        with self.assertRaises(ValueError):
            parse_list(jx, jx.list_urls[0], "<html><body>无数据</body></html>")


class TestDetailText(unittest.TestCase):
    def test_html_portal_reads_visible_text(self):
        bj = PORTALS_BY_KEY["bj_rsj"]  # 静态源：取可见正文、去掉 script
        html = "<html><body><p>报名时间：2026年9月20日截止</p><script>var x=1</script></body></html>"
        text = detail_text(bj, html)
        self.assertIn("报名时间：2026年9月20日截止", text)
        self.assertNotIn("var x", text)

    def test_script_json_portal_digs_out_embedded_body(self):
        # 江西详情页也是 JS 渲染：正文在 content:{"content":"<html>"} 里，且页面 markup 有 id="content" 干扰项。
        jx = PORTALS_BY_KEY["jx_rst"]
        body_html = "<p>三、报名</p><p>报名时间：即日起至2026年7月21日17:00时止</p>"
        html = (
            '<div id="content">导航噪音不应进正文</div>'
            "<script>var articleContent_1 = [{ content:%s }];</script>"
            % json.dumps({"content": body_html}, ensure_ascii=False)
        )
        text = detail_text(jx, html)
        self.assertIn("报名时间：即日起至2026年7月21日17:00时止", text)
        self.assertNotIn("导航噪音", text)  # 只取嵌入正文，不混入页面 markup
        self.assertNotIn("<p>", text)       # 已去标签

    def test_script_json_portal_no_body_returns_empty(self):
        # 抽不到正文 → 空串（上游走 TTL 兜底，不假装有截止日）。
        jx = PORTALS_BY_KEY["jx_rst"]
        self.assertEqual(detail_text(jx, "<html><body>无 content 块</body></html>"), "")


class TestCdataList(unittest.TestCase):
    def test_cdata_wrapped_list_is_unwrapped(self):
        # 江苏：<li><a> 藏在 <record><![CDATA[…]]> 里，selectolax 不建 DOM → 必须先解包。
        js = PORTALS_BY_KEY["js_hrss"]
        html = (
            "<html><body><record><![CDATA["
            '<li><a href="/art/2026/9/15/art_78506_111.html" target="_blank">'
            '<span class="list_title">南京大学2026年公开招聘工作人员公告</span><i>2026-09-15</i></a></li>'
            '<li><a href="/art/2026/9/10/art_78506_222.html" target="_blank">'
            '<span class="list_title">江苏省某单位2026年拟聘用人员名单公示</span><i>2026-09-10</i></a></li>'
            "]]></record></body></html>"
        )
        items = parse_list(js, js.list_urls[0], html)
        # 招聘公告保留；同栏目混入的「拟聘用人员名单公示」被 classify EXCLUDE 剔除
        self.assertEqual([it.title for it in items], ["南京大学2026年公开招聘工作人员公告"])


class TestJsonFragmentList(unittest.TestCase):
    def test_parses_ajax_fragment_and_filters(self):
        # 浙江：GET AJAX 返回 {"data":{"html":"<li><a>…片段"}}。
        zj = PORTALS_BY_KEY["zj_rlsbt"]
        frag = (
            '<li><a href="/col/col1229743683/art/2026/art_%s.html" '
            'title="浙江省交通运输科学研究院公开招聘人员公告">'
            "浙江省交通运输科学研究院公开招聘人员公告</a></li>"
            '<li><a href="/col/col1229743683/art/2026/art_%s.html" '
            'title="浙江省某单位2026年拟聘用人员公示">浙江省某单位2026年拟聘用人员公示</a></li>'
        ) % ("a" * 32, "b" * 32)
        payload = json.dumps({"success": True, "data": {"html": frag}}, ensure_ascii=False)
        items = parse_list(zj, zj.list_urls[0], payload)
        self.assertEqual([it.title for it in items], ["浙江省交通运输科学研究院公开招聘人员公告"])

    def test_missing_data_html_raises(self):
        # 接口参数失效（无 data.html）→ 抛错让 harvest 记 list_errors，不静默 0。
        zj = PORTALS_BY_KEY["zj_rlsbt"]
        with self.assertRaises(ValueError):
            parse_list(zj, zj.list_urls[0], json.dumps({"success": False}))


class TestJsonApiList(unittest.TestCase):
    def test_parses_structured_json_and_filters(self):
        hlj = PORTALS_BY_KEY["hlj_hrss"]
        payload = json.dumps({"data": {"results": [
            {"title": "XX省2026年事业单位公开招聘工作人员公告",
             "url": "/hrss/c111741/202609/c00_123.shtml",
             "publishedTimeStr": "2026-09-15 15:44:52"},
            {"title": "XX拟聘用人员公示",
             "url": "/hrss/c111741/202609/c00_456.shtml",
             "publishedTimeStr": "2026-09-10 10:00:00"},
        ]}}, ensure_ascii=False)
        items = parse_list(hlj, hlj.list_urls[0], payload)
        self.assertEqual([it.title for it in items], ["XX省2026年事业单位公开招聘工作人员公告"])
        self.assertEqual(items[0].published_at, date(2026, 9, 15))

    def test_missing_results_raises(self):
        hlj = PORTALS_BY_KEY["hlj_hrss"]
        with self.assertRaises(ValueError):
            parse_list(hlj, hlj.list_urls[0], json.dumps({"data": {}}))


class TestAnchorTitleFallback(unittest.TestCase):
    def test_falls_back_to_title_attr(self):
        # 天津那类：<a> 可见文字可能为空，标题只在 title 属性里。
        tj = PORTALS_BY_KEY["tj_rsj"]
        html = ('<ul><li><a href="./202609/t20260911_7372274.html" '
                'title="天津市部分事业单位公开招聘信息"></a></li></ul>')
        items = parse_list(tj, tj.list_urls[0], html)
        self.assertEqual([it.title for it in items], ["天津市部分事业单位公开招聘信息"])
        self.assertEqual(items[0].published_at, date(2026, 9, 11))  # URL t20260911_ 自带发布日


class TestHarvestLedger(unittest.TestCase):
    def test_zero_found_portal_warns_and_is_recorded(self):
        portal = PORTALS_BY_KEY["bj_rsj"]
        zero = {
            "portal": portal.key, "found": 0, "processed": 0, "new": 0, "rejected": 0, "rejected_reasons": {}, "touched": 0,
            "deadline_hit": 0, "list_errors": 0, "detail_errors": 0,
        }
        client = mock.MagicMock()
        client.__enter__.return_value = object()
        with mock.patch.object(harvest, "_client", return_value=client), \
                mock.patch.object(harvest.db, "get_supabase", return_value="SB"), \
                mock.patch.object(harvest, "harvest_portal", return_value=zero), \
                mock.patch.object(harvest.ops_runs, "record_ops_run") as record:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = harvest.run([portal.key], dry_run=False)

        self.assertIn(
            "::warning::[announce] bj_rsj found 0 candidates（形态可能变了）", output.getvalue())
        self.assertEqual(result["metrics"]["zero_found_portals"], ["bj_rsj"])
        self.assertEqual(record.call_args.args[2]["zero_found_portals"], ["bj_rsj"])

    def test_ledger_marks_ci_runner_and_portal_count(self):
        portal = PORTALS_BY_KEY["bj_rsj"]
        metrics = {
            "portal": portal.key, "found": 1, "processed": 1, "new": 0, "rejected": 0, "rejected_reasons": {}, "touched": 1,
            "deadline_hit": 0, "list_errors": 0, "detail_errors": 0,
        }
        client = mock.MagicMock()
        client.__enter__.return_value = object()
        with mock.patch.object(harvest, "_client", return_value=client), \
                mock.patch.object(harvest.db, "get_supabase", return_value="SB"), \
                mock.patch.object(harvest, "harvest_portal", return_value=metrics), \
                mock.patch.object(harvest.ops_runs, "record_ops_run") as record:
            harvest.run([portal.key], dry_run=False)

        ledger = record.call_args.args[2]
        self.assertEqual(ledger["runner"], "ci")
        self.assertEqual(ledger["portals_run"], 1)

    def test_ledger_marks_include_geo_blocked_runner_as_mac(self):
        portal = PORTALS_BY_KEY["bj_rsj"]
        metrics = {
            "portal": portal.key, "found": 1, "processed": 1, "new": 0, "rejected": 0, "rejected_reasons": {}, "touched": 1,
            "deadline_hit": 0, "list_errors": 0, "detail_errors": 0,
        }
        client = mock.MagicMock()
        client.__enter__.return_value = object()
        with mock.patch.object(harvest, "_client", return_value=client), \
                mock.patch.object(harvest.db, "get_supabase", return_value="SB"), \
                mock.patch.object(harvest, "harvest_portal", return_value=metrics), \
                mock.patch.object(harvest.ops_runs, "record_ops_run") as record:
            harvest.run([portal.key], dry_run=False, include_geo_blocked=True)

        self.assertEqual(record.call_args.args[2]["runner"], "mac")


if __name__ == "__main__":
    unittest.main()


class TestListPagination(unittest.TestCase):
    """翻页展开（2026-09-18 加）。页码基数逐省实测，写错只会静默抓回第一页。"""

    def test_expands_pages_next_to_the_first_list_url(self):
        from announcements.portals import Portal, all_list_urls
        p = Portal("x", "X", "某省", ("https://a.gov.cn/col/index.html",), ("a.gov.cn",),
                   page_pattern="index_{}.html", page_indexes=(2, 3))
        self.assertEqual(all_list_urls(p), [
            "https://a.gov.cn/col/index.html",
            "https://a.gov.cn/col/index_2.html",
            "https://a.gov.cn/col/index_3.html",
        ])

    def test_directory_style_url_keeps_its_directory(self):
        from announcements.portals import Portal, all_list_urls
        p = Portal("y", "Y", "某省", ("https://b.gov.cn/col/",), ("b.gov.cn",),
                   page_pattern="index_{}.html", page_indexes=(1,))
        self.assertEqual(all_list_urls(p)[1], "https://b.gov.cn/col/index_1.html")

    def test_no_pagination_configured_is_a_noop(self):
        from announcements.portals import Portal, all_list_urls
        p = Portal("z", "Z", "某省", ("https://c.gov.cn/col/",), ("c.gov.cn",))
        self.assertEqual(all_list_urls(p), ["https://c.gov.cn/col/"])

    def test_paginated_portals_declare_both_fields(self):
        """只填一半（有 pattern 没 indexes）会静默不翻页 —— 钉死不许出现。"""
        from announcements.portals import PORTALS, _GEO_BLOCKED_FROM_CI
        for p in (*PORTALS, *_GEO_BLOCKED_FROM_CI):
            self.assertEqual(bool(p.page_pattern), bool(p.page_indexes), p.key)
