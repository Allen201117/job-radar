"""校招往年时间线 B1 —— 结构化月份抽取（LLM writer 提示 + 纯函数解析器）。

writer 复用 insight_engine 的「每条结论必须在来源原文找到支撑 + 引用片段 + 宁缺毋滥」纪律，
但产出结构化 {season,batch,event,month_start,month_end,value_text,source_idx,quote}，
而非自由文本。parse_cycle_claims 是纯函数（不打网络），做枚举 / 月份 / 证据齐全性硬校验，
非法条一律丢弃（宁缺不编）。
"""

_SEASONS = {"秋招", "春招"}
_BATCHES = {"提前批", "正式批", "补录", "实习转正"}
_EVENTS = {"开放", "截止", "黄金期", "结束"}

# LLM system 提示：只从给定校招时间来源原文抽取结构化批次月份。
WRITER_SYS = (
    "你是校招招聘周期抽取助手，只依据【给定来源原文】抽取某公司的**校招批次时间规律**。"
    "硬约束：①每条结论必须能在某条来源原文里找到支撑，给出来源序号 source_idx（整数）与"
    "一句不超过60字的引用片段 quote；②只抽「往年/历史规律」性质的批次时间，"
    "字段：season(秋招/春招)、batch(提前批/正式批/补录/实习转正)、event(开放/截止/黄金期/结束)、"
    "month_start(1-12整数)、month_end(1-12整数，同月则等于 month_start)、"
    "value_text(展示串，如「约7月」「8-9月」)；③原文没写清月份 / 拿不准 / 与校招无关 → 不要输出该条，"
    "宁缺毋滥；④禁编造原文没有的月份。只输出 JSON：{\"claims\":[{...}]}。"
)


def build_messages(company, sources):
    """拼 chat_json 用的 messages（system + user）。sources: [{text,publisher,...}]。"""
    blocks = []
    for i, s in enumerate(sources or []):
        text = str((s or {}).get("text") or "")[:1500]
        pub = str((s or {}).get("publisher") or "")
        blocks.append(f"[来源 {i}] 出处:{pub}\n{text}")
    user = (
        f"公司：{company}\n\n"
        f"下面是若干公开来源原文，请抽取该公司的校招批次时间规律（往年/历史规律）：\n\n"
        + "\n\n".join(blocks)
    )
    return [
        {"role": "system", "content": WRITER_SYS},
        {"role": "user", "content": user},
    ]


def _int_or_none(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def parse_cycle_claims(llm_out):
    """校验 LLM 输出，返回合法 claim 列表（纯函数）。非法条丢弃、不 raise。
    每条合法 claim：{season,batch,event,month_start,month_end|None,value_text,source_idx,quote}。"""
    if isinstance(llm_out, dict):
        claims = llm_out.get("claims")
    elif isinstance(llm_out, list):
        claims = llm_out
    else:
        claims = None
    out = []
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        if c.get("season") not in _SEASONS:
            continue
        if c.get("batch") not in _BATCHES:
            continue
        if c.get("event") not in _EVENTS:
            continue
        ms = _int_or_none(c.get("month_start"))
        if ms is None or ms < 1 or ms > 12:
            continue
        me_raw = c.get("month_end")
        if me_raw is None:
            me = None
        else:
            me = _int_or_none(me_raw)
            if me is None or me < 1 or me > 12:
                continue
        value_text = str(c.get("value_text") or "").strip()
        if not value_text:
            continue
        # 宁缺不编：证据必须齐全（来源序号 + 引用片段）
        if c.get("source_idx") is None or not str(c.get("quote") or "").strip():
            continue
        out.append({
            "season": c["season"],
            "batch": c["batch"],
            "event": c["event"],
            "month_start": ms,
            "month_end": me,
            "value_text": value_text,
            "source_idx": int(c["source_idx"]) if str(c.get("source_idx")).lstrip("-").isdigit() else c["source_idx"],
            "quote": str(c["quote"]).strip()[:200],
        })
    return out
