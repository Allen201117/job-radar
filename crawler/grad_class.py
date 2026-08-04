"""届别（2027 届 / 2026 届）抽取 —— 写入端纯函数。

与 lib/grad-class.js 是同口径的两份实现（写入端 Python / 展示端 JS），
⚠️ 改规则必须两边同改 + 两边测试同步（同 canonicalize_jd_url 的三处同改约定）。

核心原则：**只认硬信号，抽不出返回 None，绝不靠入库时间或上下文猜。**
8 月抓到的校招岗大概率是 2027 届，但同期也在抓 2026 届的收尾岗——猜错就是把往届岗
标成当季，让用户白投一轮，比留白更伤。留白 ≠ 隐藏：无届别的岗照常展示。
"""

import re
from typing import Optional

MIN_GRAD_YEAR = 2015
MAX_GRAD_YEAR = 2100

# 硬信号：年份必须**紧贴届别语境词**。「2027年12月前入职」「2027 年度预算」只有年份没有
# 届别语境，一律不认——否则任何带年份的 JD 都会被安上一个届别。
_PATTERNS = (
    re.compile(r"(20\d{2})\s*届"),
    re.compile(r"(?:^|[^\d])(\d{2})\s*届"),
    re.compile(r"(20\d{2})\s*年?\s*(?:校招|秋招|春招|校园招聘|校园招募)"),
    # 「2027应届生」「2027实习生」——各家招聘项目名的常见写法，同样是明确的届别标记。
    # 2026-08-04 实测：快手校招项目名就是 `2027应届生`/`2027实习生`/`2026应届生`，
    # 只认「届/校招/秋招」的旧规则会把这 510 个岗的届别全漏成 None。
    re.compile(r"(20\d{2})\s*年?\s*应届"),
    re.compile(r"(20\d{2})\s*年?\s*实习生"),
    re.compile(r"class\s+of\s+(20\d{2})", re.I),
    re.compile(r"(20\d{2})\s+(?:graduate|campus)", re.I),
)


def _normalize_year(raw: str) -> Optional[int]:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    year = 2000 + n if n < 100 else n
    if year < MIN_GRAD_YEAR or year > MAX_GRAD_YEAR:
        return None
    return year


def extract_grad_class(title=None, job_type=None, summary=None) -> Optional[int]:
    """抽届别。命中多个不同届别取**最大**（「2026/2027 届均可」取更晚那届）。无硬信号返回 None。"""
    text = " ".join(str(x) for x in (title, job_type, summary) if x)
    if not text:
        return None
    best = None
    for pattern in _PATTERNS:
        for m in pattern.finditer(text):
            year = _normalize_year(m.group(1))
            if year is not None and (best is None or year > best):
                best = year
    return best
