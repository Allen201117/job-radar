"""中文↔英文求职关键词双语扩展 + 匹配（crawler 端）。

这是 lib/china-keyword-expansion.js 同义词组逻辑的 Python 移植，目的是让**发现端**
(discovery.filter_raw_jobs) 的关键词匹配与**前端看板** (jobMatchesChinaKeyword) 同口径：
中文发现关键词（如「算法」）也能命中英文外企岗（"Machine Learning Engineer"），反之亦然。

两边逻辑必须保持一致：改这里时同步 lib/china-keyword-expansion.js（及其单测）。
"""
import re
from typing import List

# 与 lib/china-keyword-expansion.js 的 CHINA_KEYWORD_GROUPS 一一对应（21 组）。
CHINA_KEYWORD_GROUPS: List[List[str]] = [
    ["算法", "机器学习", "深度学习", "人工智能", "AI", "artificial intelligence",
     "machine learning", "deep learning", "algorithm", "ml", "llm", "大模型",
     "nlp", "自然语言处理", "computer vision", "cv", "计算机视觉"],
    ["数据分析", "商业分析", "数据运营", "数据科学", "BI", "SQL", "Python",
     "data analyst", "data scientist", "business analyst", "analytics"],
    ["数据工程", "大数据", "data engineer", "data engineering", "etl", "data platform"],
    ["产品经理", "产品", "AI 产品", "数据产品", "策略产品", "product manager",
     "product", "PM", "AI product", "po"],
    ["前端", "web 前端", "frontend", "front end", "front-end", "react", "vue",
     "javascript", "客户端", "ios", "android", "客户端开发"],
    ["后端", "服务端", "backend", "back end", "back-end", "服务器开发", "java",
     "golang", "go 开发", "全栈", "full stack", "fullstack"],
    ["测试", "质量", "qa", "test engineer", "quality assurance", "测试开发",
     "sdet", "自动化测试"],
    ["运维", "sre", "devops", "site reliability", "基础架构", "infrastructure",
     "平台工程", "platform engineer"],
    ["安全", "信息安全", "网络安全", "security", "cybersecurity", "security engineer"],
    ["设计", "ui", "ux", "交互设计", "视觉设计", "designer", "ui designer",
     "ux designer", "product designer"],
    ["运营", "用户运营", "内容运营", "增长", "operations", "growth", "user operations"],
    ["市场", "营销", "品牌", "marketing", "brand", "growth marketing", "市场营销"],
    ["销售", "商务", "bd", "sales", "business development", "account manager", "客户经理"],
    ["财务", "会计", "审计", "finance", "accounting", "audit", "financial analyst", "财务分析"],
    ["人力", "人力资源", "招聘", "hr", "human resources", "recruiter", "recruiting", "talent"],
    ["法务", "法律", "合规", "legal", "compliance", "counsel"],
    ["供应链", "采购", "物流", "supply chain", "procurement", "logistics", "operations manager"],
    ["硬件", "嵌入式", "芯片", "电子", "hardware", "embedded", "firmware", "chip", "asic", "fpga"],
    ["投研", "行业研究", "股票研究", "固收", "量化", "investment research",
     "equity research", "quant"],
    ["管培生", "管理培训生", "校招", "应届", "graduate program", "campus recruitment",
     "new grad", "graduate"],
    ["实习", "暑期实习", "日常实习", "intern", "internship"],
]

_SPLIT_RE = re.compile(r"[\s,，、/|;；]+")
_SHORT_LATIN_RE = re.compile(r"[a-z0-9.+#-]{1,3}")


def normalize_for_match(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def split_keyword_terms(value) -> List[str]:
    raw = str(value or "").strip()
    parts = [p for p in (t.strip() for t in _SPLIT_RE.split(raw)) if p]
    return [raw, *parts]


def contains_term(haystack, term: str) -> bool:
    """短的纯拉丁缩写（≤3，如 ai/ml/pm/ui/hr）用词边界匹配，避免 maintain→ai、google→go
    这类误匹配；其余（CJK 或较长词）走普通子串包含。haystack 视为已 normalize_for_match。"""
    h = str(haystack or "")
    t = normalize_for_match(term)
    if not t:
        return False
    if _SHORT_LATIN_RE.fullmatch(t):
        escaped = re.escape(t)
        return re.search(rf"(^|[^a-z0-9]){escaped}([^a-z0-9]|$)", h) is not None
    return t in h


def expand_china_keyword_terms(query) -> List[str]:
    """把查询扩展成同义词集合：命中某同义词组则纳入该组全部词（中英双语）。空查询返回 []。"""
    raw = str(query or "").strip()
    if not raw:
        return []
    normalized = normalize_for_match(raw)
    terms = set(split_keyword_terms(raw))
    for group in CHINA_KEYWORD_GROUPS:
        if any(contains_term(normalized, term) for term in group):
            for term in group:
                terms.add(term)
                terms.add(normalize_for_match(term))
    return [t for t in (str(x).strip() for x in terms) if t]


def query_matches(haystack, query) -> bool:
    """haystack（任意可搜索文本）是否命中查询的双语扩展。空查询视为命中。"""
    terms = [normalize_for_match(t) for t in expand_china_keyword_terms(query)]
    if not terms:
        return True
    h = normalize_for_match(haystack)
    return any(contains_term(h, term) for term in terms)
