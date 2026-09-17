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


# ── 写入端接线用（存量治理与新写入必须共用同一套口径）────────────────────────
# T3 查询包的主题名 → metric_key。与迁移 209 的标题映射逐字对应，改一处必须改另一处。
TOPIC_TO_METRIC: Dict[str, str] = {
    "年终奖": "bonus_months",
    "加班文化": "overtime_level",
    "面试难度": "interview_rounds",
    "晋升发展": "promotion_pace",
    "实习体验": "intern_experience",
    "裁员稳定性": "layoff_mention",
}

# metric_key → 该主题该落在哪个维度。转投时**维度必须跟着改**，
# 否则「薪资水平」的内容会留在 path（进入路径）维度下，筛维度时又对不上了。
METRIC_TO_DIMENSION: Dict[str, str] = {
    "bonus_months": "compensation_intensity",
    "pay_level": "compensation_intensity",
    "overtime_level": "culture",
    "intern_experience": "culture",
    "interview_rounds": "hiring",
    "layoff_mention": "hiring",
    "promotion_pace": "path",
}


# ── 说法类型门（2026-09-17 立）──────────────────────────────────────────────
# 为什么还要第二道门：上面的主题词表判的是**说法在讲谁**（实习生 / 加班 / 晋升），
# 判不了**说法在断言什么**（薪资 / 福利 / 门槛 / 强弱体验）。二者不是一回事：
# 「实习生转正后的薪资范围在 5000-12000 元/月」主题词命中「实习/实习生/转正」三个、
# 稳稳留在 intern_experience，而 intern_experience 的 1–5 档说的是「带教好不好、
# 转正难不难」——它根本判不出这句话的档，于是这条从出生就注定进分档队列、
# 每天被重判、永远判不出。2026-09-17 live 实测：3 个档位主题 195 条判不出档的里，
# intern_experience 占 152 条，其中 54 条讲薪资、32 条讲门槛、27 条讲福利，
# 真讲实习体验强弱的只有 23 条（15%）。
#
# 所以写入端在主题门之后再过一道说法类型门：类型对得上量表就路由到对应 metric_key，
# 对不上任何量表（福利 / 门槛）就**不带 metric_key 写入**——照样是可展示的经验条目，
# 只是不进分档队列，不再空烧 LLM。
CLAIM_TYPE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "pay": (
        "薪资", "薪酬", "工资", "月薪", "年薪", "日薪", "时薪", "底薪", "起薪",
        "总包", "年包", "待遇", "涨薪", "调薪", "提成", "薪水", "报酬", "月收入",
        "元/月", "元/天", "k/月", "薪资水平", "白菜价", "面议",
    ),
    "bonus": (
        "年终奖", "年终", "奖金", "十三薪", "13薪", "14薪", "年终分红", "签约奖金",
    ),
    "benefit": (
        "福利", "餐补", "班车", "接驳", "食宿", "住宿", "免费", "健身房", "体检",
        "五险", "六险", "公积金", "补贴", "下午茶", "零食", "团建", "节日",
        "意外险", "医疗保险", "租房", "住房补贴", "津贴", "报销", "生日福利",
    ),
    "requirement": (
        "要求", "需具备", "具备", "需要", "学历", "本科", "硕士", "博士", "专业",
        "应届", "985", "211", "擅长", "抗压", "每周", "至少", "实习期", "门槛",
        "条件", "倾向", "偏好", "适应", "服从", "熟悉", "掌握",
    ),
    "overtime": (
        "加班", "996", "997", "大小周", "单休", "双休", "工时", "工作时长",
        "工作强度", "强度", "节奏", "打卡", "通宵", "轮班", "夜班", "周末上班",
        "弹性工作", "下班", "站立", "体力",
    ),
    "promotion": (
        "晋升", "提拔", "天花板", "上升通道", "上升空间", "发展空间", "职级",
        "培养路径", "职业发展", "内部提拔",
    ),
    "interview": (
        "面试", "笔试", "终面", "群面", "复试", "面试流程", "轮次",
    ),
    "mentoring": (
        "带教", "导师", "转正率", "留用", "打杂", "轮岗", "氛围", "同事关系",
        "融洽", "包容", "友好", "关怀", "指导",
        # ⚠️ 只收「转正」的**修饰搭配**，不收裸「转正」：几乎每句实习薪资都写
        # 「实习生转正后的薪资……」，收裸词等于这道门白装。
        "可转正", "难转正", "转正机会", "转正流程", "转正机制", "转正率高",
        "实际项目", "真实项目", "实践经验",
    ),
}

# 说法类型 → 该落哪个 metric_key。None = 没有对应量表，**不带 metric_key 写入**。
CLAIM_TYPE_TO_METRIC: Dict[str, Optional[str]] = {
    "pay": "pay_level",
    "bonus": "bonus_months",
    "overtime": "overtime_level",
    "promotion": "promotion_pace",
    "interview": "interview_rounds",
    "mentoring": None,      # 见 route_by_claim_type：只有主语是实习才落 intern_experience
    "benefit": None,
    "requirement": None,
}

# 没有 metric_key 时维度也要对：福利归薪酬待遇、门槛归招聘。
CLAIM_TYPE_TO_DIMENSION: Dict[str, str] = {
    "pay": "compensation_intensity",
    "bonus": "compensation_intensity",
    "benefit": "compensation_intensity",
    "requirement": "hiring",
    "interview": "hiring",
    "overtime": "culture",
    "mentoring": "culture",
    "promotion": "path",
}

_INTERN_SUBJECT_MARKERS = ("实习",)

# metric_key → 它自己对应的说法类型。用于「原量表没输就别动它」的让位判断。
METRIC_TO_CLAIM_TYPE: Dict[str, str] = {
    "pay_level": "pay",
    "bonus_months": "bonus",
    "overtime_level": "overtime",
    "promotion_pace": "promotion",
    "interview_rounds": "interview",
    "intern_experience": "mentoring",
}


def claim_type_scores(content: str) -> Dict[str, int]:
    """各说法类型命中的不同词数；同一个词重复出现只计一次（与 topic_scores 同口径）。"""
    text = _as_text(content)
    return {
        key: sum(1 for word in words if word.lower() in text)
        for key, words in CLAIM_TYPE_KEYWORDS.items()
    }


def classify_claim_type(content: str) -> Optional[str]:
    """按命中的不同词数判「这句在断言什么」；并列最高或零命中一律返回 None。

    返回 None 的含义是**判不出，保持调用方原判断**，绝不是「没类型」——
    宁可少改一条，也不要凭一个宽泛词把好条目的 metric_key 改掉。
    """
    if not _as_text(content):
        return None
    scores = claim_type_scores(content)
    highest = max(scores.values(), default=0)
    if highest <= 0:
        return None
    leaders = [key for key, score in scores.items() if score == highest]
    return leaders[0] if len(leaders) == 1 else None


def route_by_claim_type(content: str, metric_key: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """主题门定下 metric_key 之后的纠偏：返回 (metric_key, dimension)。

    两道让位闸，任一成立就原样保留 metric_key——**宁可少改一条，也不要把好条目改坏**：
    ① 原量表的数值抽取器真抽出了值（「年终奖发 3-6 个月」）→ 这是比任何词表都硬的证据；
    ② 原量表自己的说法类型**只要有一个词命中**就留着（不是「得分最高才留」）。
       实测这道闸的松紧直接决定误伤：按「最高分才留」跑全库，
       「弹性工作制，包括双休、节日福利和团建」会因为福利词 3 > 加班词 2 被摘掉 key，
       可它真的在说双休；「要求员工遵循 996」会因为「要求/至少」2 > 「996」1 被判成门槛。
       同一时刻的代码只改这一条闸，全库复算（audit_insight_metric_key.py，3,423 条 active）
       的反向误伤 168 → 119 条，而正向要修的那批一条没少——
       因为本次要修的根本特征是**原量表一个词都没命中**（「实习生薪资 5000-12000 元/月」
       命中的是 pay，mentoring 得 0 分）。
    """
    keep = (metric_key, METRIC_TO_DIMENSION.get(metric_key) if metric_key else None)
    if metric_key and extract_metric_value(metric_key, content) is not None:
        return keep

    own_type = METRIC_TO_CLAIM_TYPE.get(metric_key or "")
    if own_type and claim_type_scores(content).get(own_type, 0) > 0:
        return keep

    claim_type = classify_claim_type(content)
    if claim_type is None:
        return keep

    text = _as_text(content)
    is_intern = any(marker in text for marker in _INTERN_SUBJECT_MARKERS)

    if claim_type in ("mentoring", "promotion"):
        # 「有带教、氛围融洽、有真实项目」这类才是 intern_experience 的 1–5 档说的事。
        # promotion 也并进来：主语是实习生时「有明确培养路径 / 可转正」本就是实习体验档
        # 的第 4、5 档，投到 promotion_pace（讲的是正式员工晋升快慢）会误导筛选。
        # 主语不是实习的 mentoring 说法没有对应量表（work_culture 没有档位口径），不硬塞。
        target = "intern_experience" if is_intern else CLAIM_TYPE_TO_METRIC.get(claim_type)
    elif claim_type == "pay" and is_intern:
        # ⚠️ 实习薪资刻意不落 pay_level：实习给的是日薪 / 津贴（120 元/天、2-4.5K），
        # 与 pay_level 的全职月薪 K 不是一个量纲，混进去会把中位数拉垮，
        # 比「没有数值」更糟。宁可不可筛，也不给错数字。
        target = None
    else:
        target = CLAIM_TYPE_TO_METRIC.get(claim_type)

    if target:
        return target, METRIC_TO_DIMENSION.get(target)
    return None, CLAIM_TYPE_TO_DIMENSION.get(claim_type) or (
        METRIC_TO_DIMENSION.get(metric_key) if metric_key else None
    )


def gate_new_claim(content: str, topic: str) -> Tuple[str, Optional[str], Optional[str]]:
    """写入端的主题门：返回 (动作, metric_key, dimension)。

    为什么写入端也要装这道门（2026-09-04 立）：存量清过一次只解决历史，
    T3 每天还在按「{公司} 晋升 涨薪 职级」这类查询搜，搜回来的多半是招聘页，
    写手照实复述一遍就又是一条答非所问的「晋升发展」——不装门等于今天白清。
    实测存量跑题率 50.9%，其中晋升发展 71.4%。

    动作与 classify_topic 一致：keep / reroute / retire。
    retire 在写入端的含义是**根本不写**（而不是写进去再退役）——
    没写进去就不占额度、不占展示位、也不需要以后再清一遍。
    """
    metric_key = TOPIC_TO_METRIC.get(str(topic or "").strip())
    if not metric_key:
        # 未登记的主题（如「公开讨论」这类兜底包）不参与主题门，原样放行。
        return "keep", None, None
    action, target = classify_topic(content or "", metric_key)
    if action == "retire" or (action == "reroute" and not target):
        return "retire", None, None

    # 主题门定「讲谁」，说法类型门定「断言什么」——后者可以把 metric_key 改掉，
    # 也可以判定它不属于任何量表（返回 None，条目照写但不进分档队列）。
    settled = target if action == "reroute" else metric_key
    routed_key, routed_dim = route_by_claim_type(content or "", settled)
    if routed_key != settled:
        action = "reroute"
    return action, routed_key, routed_dim
