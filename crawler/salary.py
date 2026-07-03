"""薪资提取（海外岗）。两条路：
① Ashby：接口 includeCompensation=true 返回结构化 compensationTierSummary（已是 "$185K – $325K • Offers Equity" 格式）→ 直接用。
② Greenhouse/Lever 等自由文本：从 JD 正文里**关键词锚定**抽薪资区间——必须有 salary/pay/compensation 类词紧邻 $ 区间，
   否则会把 "Sign On Bonus $2500"、"company revenues of $500,000 to $4 million" 这类误当薪资（实测真库全是这种噪音）。
纯函数、可单测、不打网络。"""
import html
import re

# 薪资上下文关键词（区间前 ~90 字内出现才认，防 bonus/revenue 误命中）
_SALARY_CONTEXT = (
    r"(?:salary range|pay range|base pay range|compensation range|base salary range|"
    r"salary of|base pay|base salary|annual salary|expected salary|target salary|"
    r"pay scale|compensation is|total compensation|on-target earnings|\bOTE\b)"
)
# $ 区间：$120,000 - $180,000 / $120K–$180K / $120,000 to $180,000
_RANGE = r"\$\s?([\d][\d,]{2,})\s?([kK])?\s?(?:-|–|—|to)\s?\$?\s?([\d][\d,]{2,})\s?([kK])?"

_SALARY_RE = re.compile(_SALARY_CONTEXT + r"[^\$]{0,90}?" + _RANGE, re.I | re.S)


def _fmt_num(num: str, k: str) -> str:
    return f"${num}{'K' if k else ''}"


def extract_salary_text(text):
    """从自由文本 JD 里抽「关键词锚定」的薪资区间；抽不到返 None。
    只认 salary/pay/compensation 类词紧邻的 $ 区间，拒 bonus/revenue 噪音。"""
    if not text:
        return None
    # 兼容 HTML 正文（greenhouse content 是 HTML）：去标签 + 反转义，让「关键词紧邻 $ 区间」的邻近判断不被标签打断
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    m = _SALARY_RE.search(text)
    if not m:
        return None
    lo, lo_k, hi, hi_k = m.group(1), m.group(2), m.group(3), m.group(4)
    # 合理性门：无 K 时下界至少 4 位数（≥1000），挡掉 "$10 - $20" 这类
    def big_enough(n, k):
        digits = n.replace(",", "")
        return bool(k) or len(digits) >= 4
    if not (big_enough(lo, lo_k) and big_enough(hi, hi_k)):
        return None
    return f"{_fmt_num(lo, lo_k)} – {_fmt_num(hi, hi_k)}"


def salary_from_ashby(comp):
    """Ashby 结构化薪资 → salary_text。优先 compensationTierSummary（已格式化），否则拼 summaryComponents。"""
    if not isinstance(comp, dict):
        return None
    summary = comp.get("compensationTierSummary")
    if isinstance(summary, str) and "$" in summary:
        return summary.strip()[:120]
    # 兜底：从 summaryComponents 拼一个区间
    comps = comp.get("summaryComponents") or []
    for c in comps:
        if isinstance(c, dict) and c.get("compensationType") == "Salary":
            lbl = c.get("label")
            if isinstance(lbl, str) and "$" in lbl:
                return lbl.strip()[:120]
    return None
