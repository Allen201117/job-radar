"""公告分类纯函数：是不是「可报名招聘公告」、面向应届/社会、用人单位粗类型。

Phase 0 实测（见 spec §8.5）：人社厅栏目里混着成绩/公示/政策类非报名通知，
必须过滤，否则用户点开是「笔试成绩」而不是「可投的岗」。
"""
from __future__ import annotations

import re

# 是招聘/引进/招募类公告（正向）。
# ⚠️ 刻意不含「遴选」：公开遴选多为体制内在职人员流动（非对外招聘），对求职者是噪音（重庆实测一片遴选报名统计）。
_INCLUDE = re.compile(r"(招聘|引进|招募|选聘|聘用|录用)")
# 不是「报名」类的过程/结果/统计/政策通知（负向）——命中即剔除。
# ⚠️「统计」用「报名统计」而非裸「统计」，否则误杀「XX统计局招聘公告」；政策类用「印发/暂行办法」等具体词，别用裸「办法/通知」。
_EXCLUDE = re.compile(
    r"(成绩|分数线|合格线|公示|拟聘|拟录|录用名单|名单|递补|政策法规|"
    r"资格复审|资格审查结果|资格确认|面试资格|(?:笔试|面试)(?:有关事项|通知)|体检|考察|准考证|加分|证书|取消|延期|"
    r"更正|补充公告|补充说明|操作说明|问题说明|情况说明|问答|通知公告栏|政策解读|计划表|"
    r"报名统计|温馨提示|印发|违纪违规|操作办法|暂行办法|实施办法|参考目录|设置参考|处理规定|工作规程)"
)

# 应届 / 社会 信号
_FRESH = re.compile(r"(应届|高校毕业生|校园招聘|校招|毕业生|应届生|择业期)")
_EXPERIENCED = re.compile(r"(社会人员|社会招聘|社招|工作经历|工作经验|在职)")

_EMPLOYER_RULES = [
    (re.compile(r"(军队|文职)"), "军队文职"),
    (re.compile(r"(大学|学院|高校|研究生院|学校)"), "高校"),
    (re.compile(r"(医院|卫生|疾控|妇幼|中医)"), "医疗卫生"),
    (re.compile(r"(科学院|研究院|研究所|科研)"), "科研院所"),
    (re.compile(r"(集团|公司|银行|央企|国企)"), "央国企"),
]


def is_recruitment_announcement(title: str) -> bool:
    """标题是否为「可报名招聘公告」（正向命中且未被负向剔除）。"""
    if not title:
        return False
    if _EXCLUDE.search(title):
        return False
    return bool(_INCLUDE.search(title))


def detect_audience(text: str) -> str:
    """应届 / 社会 / 两者皆可 / 未知。text 传标题 + 正文（越全越准）。"""
    text = text or ""
    fresh = bool(_FRESH.search(text))
    exp = bool(_EXPERIENCED.search(text))
    if fresh and exp:
        return "both"
    if fresh:
        return "fresh_grad"
    if exp:
        return "experienced"
    return "unknown"


def detect_employer_type(title: str) -> str | None:
    """用人单位粗类型（可空）。只看标题，够用即可。"""
    title = title or ""
    for pat, label in _EMPLOYER_RULES:
        if pat.search(title):
            return label
    return "事业单位" if _INCLUDE.search(title) else None
