"""爬虫解析 HTML 的唯一入口：selectolax 的 Lexbor 后端。

selectolax 1.0（2026-10-03）删了 Modest 后端（`selectolax.parser`），迁 Lexbor 时逐调用点对拍过，
会改变解析结果的语义差只有两处，在这里抹平，调用点照旧写 `HTMLParser(html)`：

1. 解析器级 `.text()`：Modest 只取 <body>，Lexbor 取整个文档——<head> 里的 <title>/<script>/<style>
   全混进来（校招官网正文 html_to_text 喂给 LLM 的就是它）。→ `HTMLParser.text()` 覆写回只取 body。
   节点级 `.text()` 两个后端一致。⚠️ `clone()` 返回的是基类，会丢掉这条覆写（目前无人调用）。
2. 逗号分组选择器 "A, B, C"：Modest 按选择器先后返回（先全部 A、再全部 B…，同一节点命中多个会重复），
   Lexbor 按文档顺序。`css_first("h3, a")` 在 `<a><h3>标题</h3><span>地点</span></a>` 上 Modest 取 h3、
   Lexbor 取外层 a——标题混进地点。→ 要按优先级取时用 `css_first_in_order` / `css_in_order`。

刻意保留的 Lexbor 行为（与浏览器一致，Modest 那边是旧解析器的偏差）：<template> 内容惰性、不遍历；
`href=""` 读出 ""（Modest 读 None）；重复属性取第一个（Modest 的 .attributes 取最后一个）；NUL 字符丢弃。
test_html_dom.py 钉着两处口径，前三条保留行为作为「后端又变了」的哨兵，并禁止别处直接 import selectolax。
"""
from selectolax.lexbor import LexborHTMLParser


class HTMLParser(LexborHTMLParser):
    """LexborHTMLParser，`.text()` 保持 Modest 口径：只取 <body>。"""

    def text(self, deep=True, separator="", strip=False, skip_empty=False):
        body = self.body
        if body is None:
            return ""
        return body.text(deep=deep, separator=separator, strip=strip, skip_empty=skip_empty)


def css_in_order(node, selectors):
    """按 selectors 的先后拼接各自的命中（= Modest 对分组选择器的返回顺序，含重复）。"""
    found = []
    for selector in selectors:
        found.extend(node.css(selector))
    return found


def css_first_in_order(node, selectors):
    """第一个有命中的选择器的第一个节点（= Modest 的 css_first("A, B, C")）；都没命中返回 None。"""
    for selector in selectors:
        hit = node.css_first(selector)
        if hit is not None:
            return hit
    return None
