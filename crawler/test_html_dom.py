"""html_dom：Lexbor 后端上保持 Modest 口径的两处语义 + 刻意保留的 HTML5 行为 + 唯一入口契约。

背景见 html_dom.py 文件头（selectolax 1.0 删了 Modest，2026-10-04 迁 Lexbor，逐调用点对拍）。
"""
import pathlib
import re
import unittest

import campus_official_pages
from adapters.jd import JdAdapter
from html_dom import HTMLParser, css_first_in_order, css_in_order

CRAWLER = pathlib.Path(__file__).resolve().parent
PAGE = ("<html><head><title>页面标题</title><script>var s = 1;</script><style>p { color: red }</style></head>"
        "<body><p>正文第一段</p><script>var b = 2;</script></body></html>")


class ParserTextIsBodyOnlyTest(unittest.TestCase):
    """Lexbor 的解析器级 .text() 取整个文档；这里必须仍只取 <body>（Modest 口径）。"""

    def test_parser_text_excludes_head(self):
        # <head> 的 title/script/style 都不进来；body 里的 script 两个后端都算文本
        self.assertEqual(HTMLParser(PAGE).text(), "正文第一段var b = 2;")

    def test_text_options_pass_through(self):
        html = "<body><p> a </p><p> b </p></body>"
        self.assertEqual(HTMLParser(html).text(separator="|", strip=True), "a|b")
        no_body = HTMLParser("<p>x</p>")
        no_body.body.decompose()
        self.assertEqual(no_body.text(), "")

    def test_campus_text_fed_to_llm_has_no_head_noise(self):
        self.assertEqual(campus_official_pages.html_to_text(PAGE), "正文第一段\nvar b = 2;")


class GroupSelectorPriorityTest(unittest.TestCase):
    """逗号分组选择器：按列表先后取（Modest 口径），不按文档顺序（Lexbor 原生）。"""

    DOC = ("<div id=c><a id=a1 href=/x><h3 id=h>标题<span>北京</span></h3></a>"
           "<li class=x id=l1>li</li><div class=title id=t>tt</div></div>")

    def test_first_in_order_prefers_earlier_selector(self):
        node = HTMLParser(self.DOC).css_first("#c")
        self.assertEqual(css_first_in_order(node, (".title", "h3", "a")).attributes["id"], "t")
        self.assertEqual(css_first_in_order(node, ("h3", "a")).attributes["id"], "h")
        self.assertIsNone(css_first_in_order(node, (".nope", "table")))

    def test_in_order_concatenates_with_duplicates(self):
        node = HTMLParser(self.DOC).css_first("#c")
        ids = [n.attributes["id"] for n in css_in_order(node, (".x", "li", "a"))]
        self.assertEqual(ids, ["l1", "l1", "a1"])

    def test_jd_html_fallback_title_not_polluted_by_wrapping_link(self):
        html = ('<ul><li><a href="/job/1"><h3>Java 开发工程师</h3><span class="loc">北京</span></a></li></ul>')
        jobs = JdAdapter().parse(html)
        self.assertEqual([j.title for j in jobs], ["Java 开发工程师"])
        self.assertEqual(jobs[0].jd_url, "https://zhaopin.jd.com/job/1")


class IntentionalHtml5BehaviourTest(unittest.TestCase):
    """迁移时刻意保留的 Lexbor 行为（与浏览器一致）。改了说明后端又变了，先重新对拍再改这里。"""

    def test_template_content_is_inert(self):
        tree = HTMLParser("<body><template><a href=/hidden>隐藏</a></template><a href=/shown>可见</a></body>")
        self.assertEqual([a.attributes["href"] for a in tree.css("a")], ["/shown"])
        self.assertEqual(tree.text(), "可见")

    def test_empty_attribute_value_is_empty_string(self):
        a = HTMLParser('<a href="">x</a><a href>y</a>').css("a")
        self.assertEqual([n.attributes.get("href") for n in a], ["", None])

    def test_duplicate_attribute_first_wins(self):
        a = HTMLParser('<a href="/1" href="/2">x</a>').css_first("a")
        self.assertEqual(a.attributes.get("href"), "/1")


class SingleEntryContractTest(unittest.TestCase):
    """selectolax 只许经 html_dom 进：直接 import 会绕开上面两处口径修正（Modest 已不存在，parser 一 import 就炸）。"""

    def test_no_direct_selectolax_import_outside_html_dom(self):
        pattern = re.compile(r"^\s*(?:from|import)\s+selectolax\b", re.M)
        offenders = []
        for root in (CRAWLER, CRAWLER.parent / "scripts"):
            for path in root.rglob("*.py"):
                skip_dirs = {"node_modules", "site-packages", "__pycache__"}
                if path.name == "html_dom.py" or any(p in skip_dirs or p.startswith(".") for p in path.parts[len(root.parts):]):
                    continue
                if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                    offenders.append(str(path.relative_to(CRAWLER.parent)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
