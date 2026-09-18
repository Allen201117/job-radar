"""详情页正文切割：把公告本体从导航 / 面包屑 / 侧栏 / 页脚里切出来。

为什么必须有这一步（2026-09-18 实测立的碑）：
`portals.detail_text` 取的是整个 <body> 文本，导航栏、相关链接、友情链接、页脚一并在内。
下游两处都被它污染：
- `deadline.extract_deadline` 会把侧栏某条**别的公告**的日期当成本公告的截止日；
- 任何「正文里有没有 X」的判断都会被导航词命中（人社厅页面侧栏常年挂着「公示」「成绩查询」）。

切法：**标题锚点 + 页脚切断**。标题一定在正文头部出现（面包屑之后、发布时间之前），
页脚有一批高度稳定的中文标记（【打印本页】/ 分享到 / 主办单位 / ICP备）。
两端都找不到时**返回原文**而不是空串 —— 宁可退回旧行为，也不要静默丢正文。
"""
from __future__ import annotations

import re

# 页脚起点标记（按出现即截断）。只收「正文绝不会写、页脚几乎必写」的词。
_FOOTER_MARKERS = (
    "【打印本页】", "【关闭窗口】", "【打印页面】", "【关闭页面】", "【打印】", "【关闭】",
    "打印本页", "关闭本页", "打印本文", "关闭窗口", "分享到：", "分享到:",
    "主办单位：", "主办单位:", "网站标识码", "政府网站标识码", "公网安备", "ICP备",
    "上一篇：", "下一篇：", "相关链接", "相关文档", "扫一扫在手机打开",
)

# 正文开头常见的元信息词——标题锚点命中后，从标题往后切即可，这些词只用来兜底定位。
_LEAD_MARKERS = ("发布时间", "发布日期", "来源：", "来源:", "字体：", "字号：", "点击量")


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _title_key(title: str) -> str:
    """标题的比对键：去掉全部空白与常见标点，规避页面里标题被拆行/夹空格。"""
    return re.sub(r"[\s　·・,，.。、:：;；()（）\[\]【】《》\"'“”‘’]+", "", title or "")


def extract_body(page_text: str, title: str = "") -> str:
    """整页文本 → 公告正文段。切不出来就返回压缩后的原文（不静默丢内容）。"""
    text = _squeeze(page_text)
    if not text:
        return ""

    start = 0
    key = _title_key(title)
    if len(key) >= 8:
        # 页面里的标题可能夹着空格 → 在「去标点去空白」的投影串上找，再映射回原串下标。
        proj, idx_map = [], []
        for i, ch in enumerate(text):
            if not re.match(r"[\s　·・,，.。、:：;；()（）\[\]【】《》\"'“”‘’]", ch):
                proj.append(ch)
                idx_map.append(i)
        hit = "".join(proj).find(key)
        if hit >= 0:
            # 从标题**结尾**往后切：标题本身不算正文（它已单独存在 title 列里）。
            end_proj = min(hit + len(key), len(idx_map) - 1)
            start = idx_map[end_proj]

    if start == 0:
        # 标题没锚上 → 退而求其次，从第一个正文元信息词切（面包屑一般在它之前）。
        for m in _LEAD_MARKERS:
            p = text.find(m)
            if p > 0:
                start = p
                break

    body = text[start:]
    cut = len(body)
    for m in _FOOTER_MARKERS:
        p = body.find(m)
        if 0 < p < cut:
            cut = p
    body = body[:cut].strip()

    # 切完只剩一点点 = 锚点选错了（如标题在页脚「相关推荐」里才出现）→ 退回原文。
    return body if len(body) >= 120 else text
