"""报名截止日抽取（纯函数，不联网）。

设计取舍（见 docs/superpowers/specs/2026-09-15-announcement-recruitment-supply-design.md §决策②）：
- **规则优先，抽不到就返回 None，绝不瞎猜** —— 抽不到的走 TTL 兜底过期，不丢件。
- 只有高置信写结构化 date；始终把匹配到的原文一并返回（deadline_text），供兜底展示与人工复核。
- 「能抽到未来截止日」本身就是「这是一条可报名公告」的强信号（Phase 0 实测：成绩/公示类天然抽不到）。
"""
from __future__ import annotations

import re
from datetime import date, timedelta

# 全角数字/冒号/括号 → 半角，避免「２０２６」「：」这类写法漏抽。年月日不翻。
_FULLWIDTH = str.maketrans("０１２３４５６７８９：（）／　", "0123456789:()/ ")

_DATE = r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})"  # 完整年月日
_MD = r"(\d{1,2})\s*月\s*(\d{1,2})\s*日"                          # 只有月日

# 顺序有意义：优先匹配「区间的结束端」（报名截止 = 区间右端），再匹配裸「截止」。
_RANGE_END_PATS = [
    # 「报名时间：2026年9月10日…至2026年9月20日…」：完整年月日的区间右端。
    re.compile(r"报名[时實]间[^。；;\n]{0,50}?至[^。；;\n]{0,25}?" + _DATE),
    # 「报名截止时间：2026年9月20日」：报名前缀 + 完整年月日。
    re.compile(r"报名[^。；;\n]{0,40}?截止[^。；;\n]{0,25}?" + _DATE),
    # 「截止日期：2026年9月20日」：不带报名二字但有明确截止字段。
    re.compile(r"截止[^。；;\n]{0,12}?(?:时间|日期)?\s*[为：:]{0,3}\s*" + _DATE),
    # 「2026.9.20 截止」：完整日期在前，紧邻明确的截止词。
    re.compile(_DATE + r"\s*截止"),
    # 「报名时间：9月10日…至9月20日…」：年份省略时仍只取区间右端。
    re.compile(r"报名[时實]间[^。；;\n]{0,50}?至[^。；;\n]{0,25}?" + _MD),
    # 「截止日期：9月20日」「报名截止时间为9月20日」：明确截止字段 + 月日。
    re.compile(r"(?:报名)?截止(?:时间|日期)?\s*(?:为|：|:)?\s*" + _MD),
]
_WORKDAYS_PAT = re.compile(r"自(?:本)?公告(?:发布|公布|印发)之日起(\d{1,2})个?工作日")

# 月日省略年份时，最多容忍 60 天的列表页/正文日期错位；超过说明已跨年。
# 这个窗口覆盖同季公告的正常差异，又不会把 12 月发布、1 月截止直接判成已过期。
_CROSS_YEAR_TOLERANCE_DAYS = 60


def normalize(text: str) -> str:
    """压缩空白 + 全角转半角，供正则匹配（不改变语义字符）。"""
    if not text:
        return ""
    return re.sub(r"\s+", "", text.translate(_FULLWIDTH))


def _add_business_days(start: date, n: int) -> date:
    """start 起第 n 个工作日（跳过周六日）。用于「自发布之日起 N 个工作日」。"""
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # 0=周一 … 4=周五
            added += 1
    return d


_PUBLISHED_PAT = re.compile(r"(?:发布|公布|印发)[日时][期间][:：]?\s*" + _DATE)


def extract_published(text: str) -> date | None:
    """从详情页正文抽发布日期（「发布日期：2026年9月14日」一类）。抽不到返回 None。"""
    norm = normalize(text)
    m = _PUBLISHED_PAT.search(norm)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def extract_deadline(
    text: str,
    published_at: date | None = None,
    today: date | None = None,
) -> tuple[date | None, str | None]:
    """返回 (结构化截止日 or None, 命中原文片段 or None)。

    抽不到结构化日期时 date 为 None；只要命中了某个「截止/报名时间」表述就带回原文片段。
    """
    today = today or date.today()
    norm = normalize(text)
    if not norm:
        return None, None

    for pat in _RANGE_END_PATS:
        m = pat.search(norm)
        if not m:
            continue
        g = m.groups()
        try:
            if len(g) == 3:  # 年月日齐全
                y, mo, da = int(g[0]), int(g[1]), int(g[2])
            else:            # 只有月日 → 年份用发布年/今年推断
                base_year = (published_at or today).year
                mo, da = int(g[0]), int(g[1])
                y = base_year
                inferred = date(y, mo, da)
                if (published_at is not None
                        and inferred < published_at - timedelta(days=_CROSS_YEAR_TOLERANCE_DAYS)):
                    y += 1
            return date(y, mo, da), m.group(0)[:60]
        except ValueError:
            # 月/日越界（如误匹配到「13月」）→ 当作没抽到，继续找下一条更可靠的
            continue

    m = _WORKDAYS_PAT.search(norm)
    if m:
        n = int(m.group(1))
        if published_at is not None:
            return _add_business_days(published_at, n), m.group(0)[:60]
        return None, m.group(0)[:60]  # 不知道发布日 → 存原文兜底，date 留空走 TTL

    return None, None
