"""验证引擎 — 接地 → 抽取 → 判官 → 共识，用机器验证替代人审（设计 §7）。

- LLM 出口 = SiliconFlow，与 lib/llm.js 同口径（base/model/auth/json_object 兜底）。
- 纯决策逻辑（decide_status / consensus_ok / final_status / parse_json_loose）无网络、可单测。
- writer/judge 为 LLM I/O，live 由 SiliconFlow 真调验证。

用于 T3 经验层与 T2 官方页 grounded 抽取；T2 Wikidata 结构化事实不过判官（源本身即真值）。
"""
import json
import os
import re
from typing import Optional

import httpx

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "Pro/deepseek-ai/DeepSeek-V3"
TIMEOUT = 40

# 判官放行阈值：entailment 且置信 ≥ 此值 → 候选 active；[0.4, 此值) → pending_review；其余 drop
JUDGE_CONFIDENCE_MIN = 0.6
JUDGE_REVIEW_FLOOR = 0.4
EXPERIENCE_MIN_PUBLISHERS = 2


def llm_config() -> dict:
    key = os.environ.get("SILICONFLOW_API_KEY", "")
    return {
        "api_key": key,
        "base_url": os.environ.get("SILICONFLOW_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "model": os.environ.get("SILICONFLOW_MODEL", DEFAULT_MODEL),
        "configured": bool(key),
    }


def parse_json_loose(text: str) -> dict:
    """先直接 parse，失败再抠第一个 {...} 块（与 lib/llm.js parseJsonLoose 同行为）。"""
    s = str(text or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            return json.loads(m.group(0))
    raise ValueError(f"llm_bad_json: {s[:200]}")


def chat_json(messages: list, temperature: float = 0.1, max_tokens: int = 1024,
              client: Optional[httpx.Client] = None) -> dict:
    """单次 SiliconFlow chat completion，返回解析后的 JSON。未配置 / 网络 / HTTP 错误均抛异常。"""
    cfg = llm_config()
    if not cfg["configured"]:
        raise RuntimeError("llm_not_configured")
    own = client or httpx.Client()

    def call(use_json_format: bool):
        body = {"model": cfg["model"], "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        if use_json_format:
            body["response_format"] = {"type": "json_object"}
        return own.post(f"{cfg['base_url']}/chat/completions", json=body,
                        headers={"Authorization": f"Bearer {cfg['api_key']}"}, timeout=TIMEOUT)

    try:
        resp = call(True)
        if resp.status_code == 400:  # 部分模型不支持 json_object → 去掉重试一次
            resp = call(False)
        resp.raise_for_status()
        data = resp.json()
        content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        return parse_json_loose(content)
    finally:
        if client is None:
            own.close()


# ---------- 纯决策逻辑（单测覆盖；这是「机器验证替代人审」的闸门核心） ----------

def decide_status(verdict: str, confidence: float) -> str:
    """单条判官结论 → 'active' | 'pending_review' | 'drop'（宁缺毋滥）。"""
    conf = confidence if isinstance(confidence, (int, float)) else 0.0
    if verdict == "entailment" and conf >= JUDGE_CONFIDENCE_MIN:
        return "active"
    if verdict == "entailment" and conf >= JUDGE_REVIEW_FLOOR:
        return "pending_review"  # 差一口气，留人瞄一眼，不直接丢
    return "drop"  # contradiction / neutral / 极低置信 → 丢弃（abstain）


def consensus_ok(grade: str, n_publishers: int) -> bool:
    """共识门：fact ≥1 源；experience 须 ≥2 个不同 publisher。"""
    if grade == "experience":
        return (n_publishers or 0) >= EXPERIENCE_MIN_PUBLISHERS
    return (n_publishers or 0) >= 1


def final_status(verdict: str, confidence: float, grade: str, n_publishers: int) -> str:
    """判官 + 共识 合议出落库状态。共识不足 → abstain(drop)，与设计 §13 一致。"""
    s = decide_status(verdict, confidence)
    if s in ("active", "pending_review") and not consensus_ok(grade, n_publishers):
        return "drop"
    return s


# ---------- LLM I/O：抽取（writer）与验证（judge） ----------

_DIM_GUIDE = {
    "compensation_intensity": "薪资 / 工作强度的群体性印象（带样本归因，非定性）。grade=experience。",
    "path": "常见进入路径 / 跳槽链路的公开观察。grade 视证据 fact 或 experience。",
    "culture": "公司文化 / 节奏的群体性印象，措辞中性、温馨提示口吻。grade=experience。",
    "timing": "校招 / 社招节奏与月份窗口。grade=fact。",
    "listing": "上市状态 / 交易所 / 代码（禁编造股价）。grade=fact。",
}

_WRITER_SYS = (
    "你是职业洞察抽取助手，只依据【给定来源原文】抽取关于某公司某维度的群体性结论。"
    "硬约束：①每条结论必须能在某条来源原文里找到支撑，给出来源序号 source_idx 与一句不超过60字的引用片段 quote；"
    "②只用归因式表述（如「据公开讨论」「据报道」），禁用产品口吻断言（不得出现「我们认为/认定」「毫无疑问」）；"
    "③禁编造来源里没有的具体数字（薪资 / 涨跌幅 / 市值）；④不指向任何具体自然人，保持去标识；"
    "⑤原文不支持 / 拿不准就不要输出该条，宁缺毋滥。只输出 JSON。"
)

_JUDGE_SYS = (
    "你是事实核查判官。判断【来源原文】是否支持【结论】。从严：原文没有明确支持就不要给 entailment。"
    "只输出 JSON：{\"verdict\":\"entailment|contradiction|neutral\",\"confidence\":0到1的小数,\"reason\":\"一句话\"}。"
    "entailment=原文明确支持结论；contradiction=原文与结论矛盾；neutral=原文未提及或不足以支持。"
)


def extract_claims(company: str, dimension: str, sources: list,
                   client: Optional[httpx.Client] = None) -> list:
    """writer：从 sources（[{url,publisher,text}]）抽取候选 claim 列表（每条绑 source_idx + quote）。"""
    guide = _DIM_GUIDE.get(dimension, "")
    blocks = []
    for i, s in enumerate(sources or []):
        text = (s.get("text") or "")[:1500]
        blocks.append(f"[来源{i}] publisher={s.get('publisher') or '未知'}\n{text}")
    user = (
        f"公司：{company}\n维度：{dimension}（{guide}）\n\n来源原文：\n" + "\n\n".join(blocks) +
        "\n\n请输出 JSON：{\"claims\":[{\"content\":\"归因式正文1-2句\",\"grade\":\"fact|experience\","
        "\"source_idx\":来源序号整数,\"quote\":\"引用片段\",\"time_window\":\"如 2025-2026观察\","
        "\"sample_size\":\"experience给整数否则空\"}]}"
    )
    out = chat_json([{"role": "system", "content": _WRITER_SYS},
                     {"role": "user", "content": user}], temperature=0.2, max_tokens=900, client=client)
    claims = out.get("claims") if isinstance(out, dict) else None
    return claims if isinstance(claims, list) else []


def judge_claim(claim_content: str, source_text: str,
                client: Optional[httpx.Client] = None) -> dict:
    """judge：判来源原文是否支持结论。返回 {verdict, confidence, reason}。"""
    user = f"【结论】{claim_content}\n\n【来源原文】{(source_text or '')[:1500]}"
    out = chat_json([{"role": "system", "content": _JUDGE_SYS},
                     {"role": "user", "content": user}], temperature=0.0, max_tokens=200, client=client)
    verdict = str(out.get("verdict", "neutral")).strip().lower() if isinstance(out, dict) else "neutral"
    if verdict not in ("entailment", "contradiction", "neutral"):
        verdict = "neutral"
    try:
        conf = float(out.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return {"verdict": verdict, "confidence": max(0.0, min(1.0, conf)),
            "reason": str(out.get("reason", ""))[:200] if isinstance(out, dict) else ""}


def run_pipeline(company: str, dimension: str, sources: list,
                 client: Optional[httpx.Client] = None) -> list:
    """T3 经验层完整决策流水线：接地的 sources → 抽取(writer) → 逐 claim 判官 → 共识 → 定状态。
    返回 [{claim, judge, status}]；DB 落库由调用方按 status 处理
    （active=展示 / pending_review=边缘队列 / drop=abstain 丢弃）。

    v1 千帆检索延后（用户定）→ sources 由调用方提供（官方披露 / 公开聚合）。本流水线不依赖具体
    retrieval，可用 mock sources 单测；retrieval 接入即生效。
    """
    claims = extract_claims(company, dimension, sources, client=client)
    publishers = {s.get("publisher") for s in (sources or []) if s.get("publisher")}
    n_pub = len(publishers)
    out = []
    for c in claims:
        idx = c.get("source_idx")
        src = sources[idx] if isinstance(idx, int) and 0 <= idx < len(sources or []) else None
        if not src:
            out.append({"claim": c, "judge": None, "status": "drop"})  # 无可追溯来源 → abstain
            continue
        j = judge_claim(c.get("content", ""), src.get("text", ""), client=client)
        status = final_status(j["verdict"], j["confidence"], c.get("grade", "experience"), n_pub)
        out.append({"claim": c, "judge": j, "status": status})
    return out
