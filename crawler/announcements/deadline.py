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

_DATE = r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})"  # 完整年月日（3 个捕获组）
_MD = r"(\d{1,2})\s*月\s*(\d{1,2})\s*日"                          # 只有月日（2 个捕获组）
# 区间左端只用来定位、不取值 → 必须是**非捕获**版本，否则 extract_deadline 靠组数分辨
# 「年月日 / 只有月日」的判断会被多出来的组带偏（把年份当成月份用）。
_DATE_NC = r"20\d{2}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}"
_MD_NC = r"\d{1,2}\s*月\s*\d{1,2}\s*日"

# 「报名」锚点：紧跟其后的这些字说明它讲的不是报名窗（报名**成功**后…/报名**表**/报名**条件**/
# 报名**人员**/报名**确认**/报名**资格**审核）。挡住「报名成功的应聘人员请于10月8日…」这类误抽。
_REG = r"报名(?![成表条人确资])"
# 区间连接符。有它才说明左右是一个**区间**，右端即截止日 —— 这是最可靠的一类证据。
_SEP = r"(?:[-—－~～﹣]|至|到)"
_GAP = r"[^。；;\n]"

# 顺序有意义：优先匹配「区间的结束端」（报名截止 = 区间右端），再匹配裸「截止」。
_RANGE_END_PATS = [
    # 「报名时间：2026年9月10日…至2026年9月20日…」：完整年月日的区间右端。
    re.compile(r"报名[时實]间" + _GAP + r"{0,50}?至" + _GAP + r"{0,25}?" + _DATE),
    # 「报名截止时间：2026年9月20日」：报名前缀 + 完整年月日。
    re.compile(r"报名" + _GAP + r"{0,40}?截止" + _GAP + r"{0,25}?" + _DATE),
    # 「截止日期：2026年9月20日」：不带报名二字但有明确截止字段。
    re.compile(r"截止" + _GAP + r"{0,12}?(?:时间|日期)?\s*[为：:]{0,3}\s*" + _DATE),
    # 「2026.9.20 截止」：完整日期在前，紧邻明确的截止词。
    re.compile(_DATE + r"\s*截止"),
    # 「报名时间：9月10日…至9月20日…」：年份省略时仍只取区间右端。
    re.compile(r"报名[时實]间" + _GAP + r"{0,50}?至" + _GAP + r"{0,25}?" + _MD),
    # 「截止日期：9月20日」「报名截止时间为9月20日」：明确截止字段 + 月日。
    re.compile(r"(?:报名)?截止(?:时间|日期)?\s*(?:为|：|:)?\s*" + _MD),
    # ── 以下三条补的是「有区间但不写『截止』二字」的写法。2026-09-18 逐条实测：线上 33 条抽不到
    #    截止日的公告里 **27 条正文其实写了**，全栽在这里 —— 江苏/山东/新疆/吉林普遍写成
    #    「报名时间：9月18日9:00-9月24日16:00」，只有连字符没有「至」也没有「截止」。
    #    ⚠️ 必须出现**区间连接符**才取右端；只有孤零零一个日期的（「报名成功后请于X日现场确认」）
    #    一律不取 —— 那是资格审查/确认的日子，当成截止日会把已截止的公告继续挂在页面上。
    # 「报名时间：2026年9月18日9:00-2026年9月24日16:00」：完整年月日区间，取右端。
    re.compile(_REG + _GAP + r"{0,14}?" + _DATE_NC + _GAP + r"{0,12}?" + _SEP + _GAP + r"{0,12}?" + _DATE),
    # 「报名、照片上传：8月31日9:00-9月6日16:00」：月日区间，取右端。
    re.compile(_REG + _GAP + r"{0,14}?" + _MD_NC + _GAP + r"{0,12}?" + _SEP + _GAP + r"{0,12}?" + _MD),
    # 「报名方式（一）自公告发布之日起至2026年9月22日」：既不写「报名时间」也不写「截止」，只有一个「至」。
    re.compile(_REG + _GAP + r"{0,25}?至" + _GAP + r"{0,12}?" + _DATE),
    # 「自公告发布之日（起）至 X」独立成条：它和「报名」常常**跨句**——浙江音乐学院写的是
    # 「1.网上报名。自公告发布之日至9月30日。」，中间那个句号会把带「报名」锚点的正则挡在外面
    # （_GAP 刻意不跨句，跨句匹配太容易串到别的段落去）。这个短语本身指向性已足够强，单独收。
    re.compile(r"自" + _GAP + r"{0,12}?之日(?:起)?至" + _GAP + r"{0,12}?" + _DATE),
    re.compile(r"自" + _GAP + r"{0,12}?之日(?:起)?至" + _GAP + r"{0,12}?" + _MD),
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


# 命中片段里的第一个完整日期 = 报名区间的**左端**。区间右端只写月日时，年份必须跟它走。
_START_DATE_IN_MATCH = re.compile(_DATE)


_PUBLISHED_PAT = re.compile(r"(?:发布|公布|印发)[日时][期间][:：]?\s*" + _DATE)
# 有的站元信息只写「时间：2026-09-09」「信息来源：本网 时间：2026-09-09」，不写「发布」二字
# （广东就是，实测 18 行因此既无发布日也无截止日 → TTL 只能从「今天首见」起算，
#  一条 2026-01-27 发的年度集中招聘公告会被当成新件再挂 45 天）。
# ⚠️ 只认**带横杠的 ISO 写法**、且只在正文开头的元信息区里找：
#    正文里的「报名时间」也含「时间」二字，正则一放宽就会把报名起始日当成发布日。
#    中文正文写报名时间用的是「2026年9月1日」，与 ISO 写法天然分开。
_META_ISO_PAT = re.compile(r"(?:时间|日期)[:：]?\s*(20\d{2})-(\d{1,2})-(\d{1,2})")
_META_WINDOW = 200


def extract_published(text: str) -> date | None:
    """从详情页正文抽发布日期（「发布日期：2026年9月14日」「时间：2026-09-09」）。抽不到返回 None。"""
    norm = normalize(text)
    for pat, scope in ((_PUBLISHED_PAT, norm), (_META_ISO_PAT, norm[:_META_WINDOW])):
        m = pat.search(scope)
        if not m:
            continue
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
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
            else:            # 只有月日 → 年份要推断
                mo, da = int(g[0]), int(g[1])
                # ⚠️ **优先跟区间左端写明的年份走**，而不是今年。
                # 2026-09-18 实测：四川那批公告写的是「报名时间为 **2025年**10月13日至10月17日」，
                # 只取右端的「10月17日」再按今年补，就把一条 2025 年早已截止的公告
                # 算成 2026-10-17「还能报」—— 30 条同一个假日期，全是去年下半年的批次。
                # 这类写法（左端带年、右端省略）在公告里是常态，不是个案。
                head = _START_DATE_IN_MATCH.search(m.group(0))
                if head:
                    try:
                        start = date(int(head.group(1)), int(head.group(2)), int(head.group(3)))
                    except ValueError:
                        start = None
                    if start is not None:
                        y = start.year
                        # 区间跨年（如 12/28 至 1/5）：右端早于左端就进位。
                        if (mo, da) < (start.month, start.day):
                            y += 1
                        return date(y, mo, da), m.group(0)[:60]
                base_year = (published_at or today).year
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
