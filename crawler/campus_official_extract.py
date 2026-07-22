"""校招今年精确日期抽取（快路② P3b）—— LLM writer 提示 + 纯函数解析。

数据源是单一「公司官方校招页」文本（唯一来源），故不需 source_idx。writer 只抽页面里
**明确写出精确日期**的批次网申/截止时间；parse_precise_claims 纯函数做枚举/日期格式/
日期区间合理性硬校验（滤 3000-01-01 垃圾 + 往年过期日期），并从日期回填 month（兼容
现成 campusTimelineSummary 的月份口径）。宁缺不编：拿不准/无精确日期的条一律丢。
"""
import re
from datetime import datetime, timedelta

_SEASONS = {"秋招", "春招"}
_BATCHES = {"提前批", "正式批", "补录", "实习转正"}
_EVENTS = {"开放", "截止", "黄金期", "结束"}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

WRITER_SYS = (
    "你是校招网申日期抽取助手，只依据【给定的公司官方校招页原文】抽取该公司**今年当季校招**"
    "各批次的**精确网申/截止日期**。硬约束：①每条结论必须能在原文找到明确日期支撑，给出不超过"
    "60字的引用片段 quote；②字段：season(秋招/春招)、batch(提前批/正式批/补录/实习转正)、"
    "event(开放/截止/黄金期/结束)、date_start(YYYY-MM-DD)、date_end(YYYY-MM-DD，无区间则为 null)、"
    "value_text(展示串，如「网申9月10日截止」)；③原文没写明确到日的日期 / 是往年的 / 拿不准 → 不要"
    "输出该条，宁缺毋滥；④禁编造原文没有的日期。只输出 JSON：{\"claims\":[{...}]}。"
)


def build_official_messages(company, page_text):
    """拼 chat_json 用 messages。page_text: 官方校招页正文（已 HTML→text 截断）。"""
    user = (
        f"公司：{company}\n\n"
        f"下面是该公司官方校招页原文，请抽取今年当季校招各批次的精确网申/截止日期：\n\n"
        f"{str(page_text or '')[:6000]}"
    )
    return [
        {"role": "system", "content": WRITER_SYS},
        {"role": "user", "content": user},
    ]


def _valid_iso_in_window(s, now):
    if not isinstance(s, str) or not _ISO.match(s):
        return None
    try:
        d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=now.tzinfo)
    except ValueError:
        return None
    if d < now - timedelta(days=60) or d > now + timedelta(days=550):
        return None  # 滤 3000-01-01 垃圾 + 往年过期日期
    return d


def parse_precise_claims(llm_out, now):
    """校验 LLM 输出，返回合法精确日期 claim（纯函数，不打网络）。非法条丢弃、不 raise。"""
    claims = llm_out.get("claims") if isinstance(llm_out, dict) else (
        llm_out if isinstance(llm_out, list) else None)
    out = []
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        if c.get("season") not in _SEASONS or c.get("batch") not in _BATCHES or c.get("event") not in _EVENTS:
            continue
        ds = _valid_iso_in_window(c.get("date_start"), now)
        if ds is None:
            continue
        de_raw = c.get("date_end")
        if de_raw in (None, "", ds.strftime("%Y-%m-%d")):
            de = None
        else:
            de_d = _valid_iso_in_window(de_raw, now)
            if de_d is None:
                continue
            de = de_raw
        value_text = str(c.get("value_text") or "").strip()
        quote = str(c.get("quote") or "").strip()
        if not value_text or not quote:
            continue  # 宁缺不编：展示串 + 引用片段必须齐全
        out.append({
            "season": c["season"], "batch": c["batch"], "event": c["event"],
            "date_start": ds.strftime("%Y-%m-%d"),
            "date_end": de,
            "month_start": ds.month,
            "month_end": (int(de[5:7]) if de else None),
            "value_text": value_text,
            "quote": quote[:200],
        })
    return out
