"""公开讨论「说法」层的主题质量门。

本模块只做可复核的词表与正则判断，不联网、不读数据库，也不调用 LLM。宁可退役模糊
说法，也不能把答非所问的内容换一个主题继续展示给用户。
"""
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


# 同一内容可能同时命中多个主题（如「实习转正」）。因此只记录每个不同词命中过没有，
# 交给 classify_topic 比较总分，而不能按词表里的第一个命中词决定主题。
TOPIC_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "bonus_months": (
        "年终奖", "年终奖金", "年终", "奖金", "绩效奖", "绩效奖金", "年奖",
        "十三薪", "13薪", "14薪", "调薪", "调薪幅度", "激励金", "年终分红",
    ),
    "overtime_level": (
        "加班", "996", "997", "大小周", "单休", "双休", "工作时长", "工时",
        "下班", "晚下班", "强度", "工作强度", "节奏", "工作节奏", "弹性上班",
        "弹性工作", "作息", "通宵", "熬夜", "周末上班", "夜班", "加点",
    ),
    "interview_rounds": (
        "面试", "笔试", "面试官", "复试", "终面", "群面", "hr面", "技术面",
        "业务面", "交叉面", "主管面", "面试流程", "面试轮次", "offer", "测评",
    ),
    "promotion_pace": (
        "晋升", "晋升机制", "晋升路径", "职级", "涨薪", "提拔", "天花板",
        "发展空间", "职业发展", "上升空间", "上升通道", "转正", "职涯", "培养路径",
    ),
    "intern_experience": (
        "实习", "实习生", "实习期", "带教", "导师", "日薪", "实习工资",
        "转正", "留用", "转正率", "校招实习", "暑期实习", "实习项目",
    ),
    "pay_level": (
        "薪酬", "薪资", "工资", "月薪", "年薪", "年包", "总包", "base", "底薪",
        "时薪", "起薪", "薪酬范围", "薪资范围", "薪酬待遇", "薪资待遇", "k范围", "k/月",
    ),
}


def _as_text(content) -> str:
    """非文本按空内容处理，治理脚本不应因一条脏数据中断。"""
    return content.strip().lower() if isinstance(content, str) else ""


def topic_scores(content: str) -> Dict[str, int]:
    """返回各主题命中的不同词数；同一个词重复出现只计一次。"""
    text = _as_text(content)
    return {
        key: sum(1 for word in words if word.lower() in text)
        for key, words in TOPIC_KEYWORDS.items()
    }


def classify_topic(content: str, current_key: str) -> Tuple[str, Optional[str]]:
    """按主题词得分决定保留、严格转投或退役。

    keep 只要求原主题不输给其它主题：真实说法可以同时谈到福利与晋升。
    reroute 则要求原主题零命中、目标唯一最高且至少两个不同词命中；这是比 keep 更严的
    门槛，避免只凭一个含义宽泛的词把错误内容投进另一个会误导用户的主题。
    """
    scores = topic_scores(content)
    current_score = scores.get(current_key, 0)
    highest = max(scores.values(), default=0)

    if current_score > 0 and current_score == highest:
        return "keep", None

    leaders = [key for key, score in scores.items() if score == highest]
    if current_score == 0 and highest >= 2 and len(leaders) == 1:
        return "reroute", leaders[0]
    return "retire", None


_MONTH_RANGE_RE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:[-~～至到—–]\s*(?P<high>\d+(?:\.\d+)?))?\s*(?:个\s*)?月"
)
_ROUND_RANGE_RE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:[-~～至到—–]\s*(?P<high>\d+(?:\.\d+)?))?\s*轮"
)
_K_RANGE_RE = re.compile(
    r"(?<![\d.])(?P<low>\d+(?:\.\d+)?)\s*(?:[-~～至到—–]\s*(?P<high>\d+(?:\.\d+)?))?\s*k(?![a-z])"
)
_YUAN_RANGE_RE = re.compile(
    r"(?<!\d)(?P<low>\d{4,6})\s*(?:[-~～至到—–]\s*)(?P<high>\d{4,6})(?!\d)"
)
_BONUS_MARKERS = ("年终奖", "年终奖金", "奖金", "绩效奖", "十三薪", "13薪", "14薪")
_NON_BONUS_CONTEXT = ("试用期", "入职", "转正", "毕业", "工龄")
_NON_INTERVIEW_CONTEXT = ("融资", "投资", "天使轮", "a轮", "b轮", "c轮", "d轮", "e轮")
_CLAUSE_SEPARATORS = "。；;！!？?\n"


def _midpoint(match) -> float:
    low = float(match.group("low"))
    high = float(match.group("high")) if match.group("high") else low
    return (low + high) / 2


def _clause(text: str, start: int, end: int) -> str:
    """取同一句/分号内的上下文，避免把相邻句的主题词借给数字。"""
    left = max(text.rfind(separator, 0, start) for separator in _CLAUSE_SEPARATORS) + 1
    right_candidates = [text.find(separator, end) for separator in _CLAUSE_SEPARATORS]
    right = min((position for position in right_candidates if position >= 0), default=len(text))
    return text[left:right]


def _extract_bonus_months(text: str) -> Optional[float]:
    for match in _MONTH_RANGE_RE.finditer(text):
        local = text[max(0, match.start() - 12):match.end() + 12]
        if any(marker in local for marker in _NON_BONUS_CONTEXT):
            continue
        clause = _clause(text, match.start(), match.end())
        before = text[max(0, match.start() - 8):match.start()]
        # 主题门已确认这是年终奖条目时，「3-6 个月」本身就是可复核的范围表达；
        # 单值月数仍要求年终奖/发放语境，才不会把「入职 3 个月」误当成奖金。
        if (
            match.group("high")
            or any(marker in clause for marker in _BONUS_MARKERS)
            or re.search(r"发(?:放)?\s*$", before)
        ):
            return _midpoint(match)
    return None


def _extract_interview_rounds(text: str) -> Optional[float]:
    for match in _ROUND_RANGE_RE.finditer(text):
        clause = _clause(text, match.start(), match.end())
        if any(marker in clause for marker in _NON_INTERVIEW_CONTEXT):
            continue
        return _midpoint(match)
    return None


def _extract_pay_level(text: str) -> Optional[float]:
    for match in _K_RANGE_RE.finditer(text):
        return _midpoint(match)
    for match in _YUAN_RANGE_RE.finditer(text):
        suffix = text[match.end():match.end() + 1]
        # 「万」没有年/月单位，不能擅自换算成月薪 K。
        if suffix == "万":
            continue
        return _midpoint(match) / 1000
    return None


def extract_metric_value(metric_key: str, content: str) -> Optional[float]:
    """从明确的数值表达抽值；档位类主题不做臆测映射。"""
    text = _as_text(content)
    if not text:
        return None
    if metric_key == "bonus_months":
        return _extract_bonus_months(text)
    if metric_key == "interview_rounds":
        return _extract_interview_rounds(text)
    if metric_key == "pay_level":
        return _extract_pay_level(text)
    return None


def dedupe_plan(rows: List[dict]) -> List[str]:
    """同公司、去首尾空白后正文相同的说法，只保留 created_at 最早的一条。"""
    grouped = defaultdict(list)
    for index, row in enumerate(rows or []):
        content = row.get("content") if isinstance(row, dict) else None
        normalized = content.strip() if isinstance(content, str) else ""
        company_id = row.get("company_id") if isinstance(row, dict) else None
        grouped[(company_id, normalized)].append((index, row))

    retire_ids = []
    for group in grouped.values():
        if len(group) < 2:
            continue
        # created_at 通常是 ISO-8601，可按字典序比较；缺失时间放最后，避免一条脏行抢走留存位。
        ordered = sorted(
            group,
            key=lambda item: (
                not bool(item[1].get("created_at")),
                str(item[1].get("created_at") or ""),
                item[0],
            ),
        )
        retire_ids.extend(str(row["id"]) for _index, row in ordered[1:] if row.get("id") is not None)
    return retire_ids
