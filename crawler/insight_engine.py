"""验证引擎 — 接地 → 抽取 → 判官 → 共识，用机器验证替代人审（设计 §7）。

- LLM 出口 = SiliconFlow，与 lib/llm.js 同口径（base/model/auth/json_object 兜底）。
- 纯决策逻辑（decide_status / consensus_ok / final_status / parse_json_loose）无网络、可单测。
- writer/judge 为 LLM I/O，live 由 SiliconFlow 真调验证。

用于 T3 经验层与 T2 官方页 grounded 抽取；T2 Wikidata 结构化事实不过判官（源本身即真值）。
"""
import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import urlparse
from typing import Optional

import httpx

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
# 主模型（2026-08-27 换）：本项目的 LLM 活儿只有「结构化 JSON 抽取 + 事实判定」，不需要顶级推理，
# 后面还有纯函数校验 + 判官阈值 0.6 + ≥2 源共识三道硬门兜底 → 挑便宜够用的。
# ¥0.7/M 输入、¥2.8/M 输出（旧 Pro/deepseek-ai/DeepSeek-V3.1 是 ¥4/¥12，省 ~80%）。
# ⚠️ 不带 `Pro/` 前缀：`Pro/` 不是更好的档，只是**只能扣充值余额**；非 Pro 同名模型还能吃赠费余额。
# live 实测（2026-08-27，同一 JSON 抽取 prompt）：in=43 / out=14，返回 JSON 完全正确、无思考前缀。
DEFAULT_MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
# 备用模型：主模型被 SiliconFlow 服务端限流（429 code 50609「System is too busy now」）时降级。
# 刻意选**不同厂商**（智谱 GLM vs 阿里 Qwen）——2026-07-31 起 DeepSeek-V3 整个系列被挤爆、
# 持续 3 天 100% 429，同厂系兜底救不了；退避重试同样救不了（服务端容量问题会持续数天）。
# ⚠️ 降级模型**必须是非思考模式**：思考模型会先吐一大段推理再给 JSON，把 max_tokens 撑爆导致
# JSON 被截断（本项目在扩源链踩过 max_tokens 截断的坑，commit 7073224）。
# live 实测（2026-08-27，同一 prompt）：GLM-4-32B-0414 out=15、reasoning_content 为空 → 非思考；
# 作为反例，tencent/Hunyuan-A13B-Instruct out=159 + 244 字符 reasoning、Qwen/Qwen3-8B out=269 → 一律不用。
# 注：GLM-4-32B-0414 上下文 32K；judge 一次喂整包来源（每条截断 1500 字符），
# 若日后放大 per-source 截断或来源条数，先复核这条上下文余量。
DEFAULT_FALLBACK_MODEL = "THUDM/GLM-4-32B-0414"
TIMEOUT = 40

# 判官放行阈值：entailment 且置信 ≥ 此值 → 候选 active；[0.4, 此值) → pending_review；其余 drop
JUDGE_CONFIDENCE_MIN = 0.6
JUDGE_REVIEW_FLOOR = 0.4
EXPERIENCE_MIN_PUBLISHERS = 2

# 不引入公共后缀库的最小实现：T3 来源集中在常见中英文站点，覆盖常见二级公共后缀即可。
_COMPOUND_PUBLIC_SUFFIXES = {"com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "co.uk", "org.uk", "ac.uk"}


def registrable_host(url: str) -> str:
    """URL → 统一 publisher 域名；子域 / www / m. 归到同一站点。"""
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    host = (parsed.hostname or "").casefold().strip(".")
    if not host:
        return ""
    while host.startswith(("www.", "m.")):
        host = host.split(".", 1)[1]
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    suffix = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if suffix in _COMPOUND_PUBLIC_SUFFIXES else suffix

# writer 喂多少条来源（省 token 大头：judge 只跑一次而 writer 输入随来源线性涨）。
# ⚠️ 必须是**前 N 条前缀截断**：writer 返回的 source_idx 要能直接索引调用方的完整 sources 列表。
# 展示门（lib/insight-verification.ts）要的 sample_size 来自**判官**从原文识别的样本量、
# judge 仍看整包来源 → 截 writer 输入不影响 `sample_size >= 5` 与 ≥2 publisher 两道门。
WRITER_MAX_SOURCES = 8


def llm_config() -> dict:
    key = os.environ.get("SILICONFLOW_API_KEY", "")
    return {
        "api_key": key,
        "base_url": os.environ.get("SILICONFLOW_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "model": os.environ.get("SILICONFLOW_MODEL", DEFAULT_MODEL),
        "fallback_model": os.environ.get("SILICONFLOW_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL),
        "configured": bool(key),
    }


# ---------- LLM 运行健康信号 ----------
# 背景（2026-07-21）：LLM cron 都写了「单条失败就跳过、不崩」的兜底，导致 SiliconFlow 账户
# 欠费(403 balance insufficient)时整轮空转、workflow 仍报 success，故障被绿灯盖住、无人发现。
# 这里在共享调用点 chat_content 记录每轮 LLM 成败；cron main() 据此判「LLM 整体失败」→ exit(1)
# 让 workflow 真实标红。判据 = 出现账户级错误(401/402/403 或余额不足提示)，或有调用但全部失败。
_LLM_RUN_HEALTH = {"ok": 0, "fail": 0, "account_error": False}


def _record_llm(ok: bool, account_error: bool = False) -> None:
    _LLM_RUN_HEALTH["ok" if ok else "fail"] += 1
    if account_error:
        _LLM_RUN_HEALTH["account_error"] = True


def reset_llm_health() -> None:
    _LLM_RUN_HEALTH.update(ok=0, fail=0, account_error=False)


def forget_llm_probe() -> None:
    """把预探活那一次调用从成败计数里抹掉，只留 account_error 标记。

    探活成功不是真实产出。若把它记成 ok，「有调用但一次没成」(fail>0 and ok==0)
    这条判据就再也不成立——真实调用全网络失败时 workflow 反而绿灯，正是本模块
    要治的「故障被绿灯盖住」。探活发生在整轮最开头，此时计数只可能来自它自己。
    """
    _LLM_RUN_HEALTH.update(ok=0, fail=0)


def llm_run_health() -> dict:
    return dict(_LLM_RUN_HEALTH)


def llm_run_unhealthy() -> bool:
    """本进程 LLM 是否整体失败：账户级错误(401/402/403 欠费/鉴权)，或有调用但一次没成。
    0 次调用（无目标/额度用尽）不算不健康——不会误报红。"""
    h = _LLM_RUN_HEALTH
    return bool(h["account_error"] or (h["fail"] > 0 and h["ok"] == 0))


def is_account_error(status_code: int, message: str = "") -> bool:
    """SiliconFlow 账户不可用：鉴权、欠费 HTTP 或余额不足正文。"""
    if status_code in (401, 402, 403):
        return True
    text = str(message or "").casefold()
    return (("balance" in text and "insufficient" in text) or "余额不足" in text)


# ---------- LLM 用量台账（2026-08-27 加） ----------
# 背景：以前代码里**没有任何地方读 API 返回的 usage**，花费只能按字符数瞎估，账户欠费都要事后才发现。
# 这里在唯一调用点 chat_content 把真实 token 数记下来：
#   ① 每次调用打一行 `[llm-usage] …`，CI 日志可直接 grep 聚合；
#   ② 进程内累计 `llm_usage_totals()`，cron 收尾可打总账 / 写 ops_runs 旁路台账。
# 记账**永远不能阻断主任务**：所有解析与写库都吞异常。
_LLM_USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "by_model": {}}


def _record_usage(model: str, usage: Optional[dict], tag: str = "") -> None:
    try:
        u = usage if isinstance(usage, dict) else {}
        prompt = int(u.get("prompt_tokens") or 0)
        completion = int(u.get("completion_tokens") or 0)
        _LLM_USAGE["calls"] += 1
        _LLM_USAGE["prompt_tokens"] += prompt
        _LLM_USAGE["completion_tokens"] += completion
        per = _LLM_USAGE["by_model"].setdefault(
            model, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
        per["calls"] += 1
        per["prompt_tokens"] += prompt
        per["completion_tokens"] += completion
        # 单行、字段固定 → CI 日志 `grep '\[llm-usage\]'` 即可聚合
        print(f"[llm-usage] model={model} tag={tag or '-'} in={prompt} out={completion}")
    except Exception as exc:  # noqa: BLE001 - 记账不能打断主任务
        sys.stderr.write(f"[llm-usage] 记账失败（主任务不受影响）: {type(exc).__name__}\n")


def llm_usage_totals() -> dict:
    """本进程累计 LLM 用量（真实 token，不是字符数估算）。"""
    return {"calls": _LLM_USAGE["calls"],
            "prompt_tokens": _LLM_USAGE["prompt_tokens"],
            "completion_tokens": _LLM_USAGE["completion_tokens"],
            "by_model": {m: dict(v) for m, v in _LLM_USAGE["by_model"].items()}}


def reset_llm_usage() -> None:
    _LLM_USAGE.update(calls=0, prompt_tokens=0, completion_tokens=0, by_model={})


def record_usage_ops_run(supabase, module: str = "llm_usage", started_at=None) -> bool:
    """把本进程累计用量写一条 ops_runs 旁路台账（复用 crawler/ops_runs.py 范式）。
    调用方在 cron 收尾时调；失败只告警、返回 False，绝不抛。"""
    try:
        import ops_runs  # 延迟导入：insight_engine 本身不依赖 supabase 栈
        totals = llm_usage_totals()
        if not totals["calls"]:
            return False  # 本轮没调过 LLM → 不写空账
        return ops_runs.record_ops_run(supabase, module, totals,
                                       status="success", started_at=started_at)
    except Exception as exc:  # noqa: BLE001 - 旁路台账不能打断主任务
        sys.stderr.write(f"[llm-usage] ops_runs 台账写入失败（主任务不受影响）: {type(exc).__name__}\n")
        return False


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


def chat_content(messages: list, temperature: float = 0.1, max_tokens: int = 1024,
                 client: Optional[httpx.Client] = None, timeout: float = TIMEOUT,
                 tag: str = "") -> str:
    """单次 SiliconFlow chat completion，返回**原始 content 字符串**（未解析）。
    未配置 / 网络 / HTTP 错误均抛异常。给需要自定义 / 容错解析（如 generate_targets 的截断兜底）的调用方用。"""
    cfg = llm_config()
    if not cfg["configured"]:
        raise RuntimeError("llm_not_configured")
    own = client or httpx.Client()

    def call(use_json_format: bool, model: str):
        body = {"model": model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        if use_json_format:
            body["response_format"] = {"type": "json_object"}
        return own.post(f"{cfg['base_url']}/chat/completions", json=body,
                        headers={"Authorization": f"Bearer {cfg['api_key']}"}, timeout=timeout)

    models = [cfg["model"]]
    if cfg["fallback_model"] and cfg["fallback_model"] != cfg["model"]:
        models.append(cfg["fallback_model"])

    try:
        for mi, model in enumerate(models):
            for attempt in range(3):
                resp = call(True, model)
                if resp.status_code == 400:  # 部分模型不支持 json_object → 去掉重试一次
                    resp = call(False, model)
                # 429 限流 / 503 过载 → 退避后重试（cron 少量串行调用不该被瞬时限流打死）
                if resp.status_code in (429, 503) and attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                break
            # 该模型退避用尽仍被限流 → 换备用模型重来（整个模型被服务端挤爆会持续数天）
            if resp.status_code in (429, 503) and mi < len(models) - 1:
                continue
            resp.raise_for_status()  # 非 2xx（含全部模型都重试用尽的 429/503）→ 抛
            data = resp.json()
            content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
            _record_usage(model, data.get("usage") if isinstance(data, dict) else None, tag)
            _record_llm(True)
            return content
    except httpx.HTTPStatusError as e:
        # 401/402/403 或余额不足 = 账户级（欠费 / 鉴权失效）→ 标记整轮不健康，让 cron 标红
        code = e.response.status_code if e.response is not None else 0
        message = e.response.text if e.response is not None else str(e)
        _record_llm(False, account_error=is_account_error(code, message))
        raise
    except Exception:
        _record_llm(False)
        raise
    finally:
        if client is None:
            own.close()


def chat_json(messages: list, temperature: float = 0.1, max_tokens: int = 1024,
              client: Optional[httpx.Client] = None, timeout: float = TIMEOUT,
              tag: str = "") -> dict:
    """单次 SiliconFlow chat completion，返回解析后的 JSON。未配置 / 网络 / HTTP 错误均抛异常。
    tag 只用于用量日志归类（如 t3-writer / t3-judge），不影响请求本身。"""
    return parse_json_loose(chat_content(messages, temperature=temperature,
                                         max_tokens=max_tokens, client=client, timeout=timeout,
                                         tag=tag))


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


# ---------- 引文预筛（judge 之前的零成本纯函数门） ----------
# writer 每条 claim 都要给一句出自来源原文的 quote。如果这句话**根本不在任何来源正文里**，
# 那它就是编的，本来就该丢——这一步用字符串匹配就能判，不必花一次判官调用（省 ~12% 调用）。
# ⚠️ 刻意做得宽松，宁可放行给判官也不误杀：
#   ① 归一后再比（NFKC 抹平全/半角、casefold、去掉全部空白与常见标点）；
#   ② 引文里的省略号按片段拆开，每段都要能在**同一条**来源里找到（拼接多源 = 编造）；
#   ③ 引文缺失 / 归一后过短 / 来源没有正文 → 不做判断，一律放行。
_QUOTE_ELLIPSIS = re.compile(r"\.{2,}|。{2,}|…+|、{2,}")
_QUOTE_NOISE = re.compile(
    r"[\s　]+|[，。、；：！？「」『』“”‘’\"'()\[\]{}【】《》〈〉…—–\-_·~`,.;:!?/\\|]+")
QUOTE_MIN_CHARS = 4  # 归一后短于此的片段信息量不足，不拿来判真伪


def _normalize_quote_text(value: str) -> str:
    """归一到「只剩实义字符」：全角→半角、大小写、空白与标点全去掉。"""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return _QUOTE_NOISE.sub("", text)


def quote_supported(quote: Optional[str], texts: list) -> bool:
    """引文是否真出自某条来源正文（容忍空白 / 标点 / 全半角差异）。拿不准一律 True（放行）。"""
    fragments = [f for f in (_normalize_quote_text(part)
                             for part in _QUOTE_ELLIPSIS.split(str(quote or "")))
                 if len(f) >= QUOTE_MIN_CHARS]
    if not fragments:
        return True  # 没给引文 / 引文过短 → 不可判定，交给判官
    haystacks = [h for h in (_normalize_quote_text(t) for t in (texts or [])) if h]
    if not haystacks:
        return True  # 来源没有正文可比 → 不可判定
    return any(all(f in h for f in fragments) for h in haystacks)


def final_status(verdict: str, confidence: float, grade: str, n_publishers: int,
                 company_relevant: bool = True, dimension_relevant: bool = True) -> str:
    """判官 + 共识 合议出落库状态。共识不足 → abstain(drop)，与设计 §13 一致。"""
    if not company_relevant or not dimension_relevant:
        return "drop"
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
    "hiring": "招聘 / 面试流程、轮次、难度与体验。grade=fact 或 experience。",
}

_WRITER_SYS = (
    "你是职业洞察抽取助手，只依据【给定来源原文】抽取关于某公司某维度的群体性结论。"
    "硬约束：①每条结论必须能在某条来源原文里找到支撑，给出来源序号 source_idx 与一句不超过60字的引用片段 quote；"
    "②只用归因式表述（如「据公开讨论」「据报道」），禁用产品口吻断言（不得出现「我们认为/认定」「毫无疑问」）；"
    "③禁编造来源里没有的具体数字（薪资 / 涨跌幅 / 市值）；④不指向任何具体自然人，保持去标识；"
    "⑤原文不支持 / 拿不准就不要输出该条，宁缺毋滥。只输出 JSON。"
)

_JUDGE_SYS = (
    "你是事实核查判官。判断【来源原文包】是否支持【结论】。从严：原文没有明确支持就不要给 entailment。"
    "同时判断结论是否真的在说目标公司，以及是否属于指定维度；行业泛化、其他公司、或维度错配一律为 false。"
    "只输出 JSON：{\"verdict\":\"entailment|contradiction|neutral\",\"confidence\":0到1的小数,\"reason\":\"一句话\","
    "\"company_relevant\":true或false,\"dimension_relevant\":true或false,\"supported_source_idxs\":[明确支持结论的来源序号],"
    "\"sample_size\":来源原文明确给出的样本人数/评价数整数或null,"
    "\"evidence_kind\":\"direct|indirect|generic|listing\"}。"
    "entailment=至少一条原文明确支持结论；contradiction=原文与结论矛盾；neutral=原文未提及或不足以支持。"
    "置信度：0.9-1.0 仅用于来源直接、具体陈述该公司该主题（有数字或具体做法）；0.6-0.8 用于提到该公司但陈述笼统或间接；"
    "<0.5 用于泛行业内容、同名歧义或只是岗位列表页。evidence_kind 分别填 direct、indirect、generic、listing。"
    "supported_source_idxs 只能列明确支持的来源，不能为凑数列无关来源；sample_size 只能抄原文明确样本量，不能用搜索结果条数推断。"
)


def writer_max_sources() -> int:
    """writer 单次最多喂几条来源（env INSIGHT_WRITER_MAX_SOURCES 可覆盖；非法值回默认）。"""
    try:
        n = int(os.environ.get("INSIGHT_WRITER_MAX_SOURCES", "") or WRITER_MAX_SOURCES)
    except (TypeError, ValueError):
        return WRITER_MAX_SOURCES
    return n if n > 0 else WRITER_MAX_SOURCES


def extract_claims(company: str, dimension: str, sources: list,
                   client: Optional[httpx.Client] = None) -> list:
    """writer：从 sources（[{url,publisher,text}]）抽取候选 claim 列表（每条绑 source_idx + quote）。

    只喂**前 N 条**（默认 8）：搜索路由一次能出 18-20 条，writer 输入随条数线性涨钱，
    而排序靠前的结果相关性最高。前缀截断保证 source_idx 仍能索引调用方的完整 sources。
    """
    guide = _DIM_GUIDE.get(dimension, "")
    blocks = []
    for i, s in enumerate((sources or [])[:writer_max_sources()]):
        text = (s.get("text") or "")[:1500]
        blocks.append(f"[来源{i}] publisher={s.get('publisher') or '未知'}\n{text}")
    user = (
        f"公司：{company}\n维度：{dimension}（{guide}）\n\n来源原文：\n" + "\n\n".join(blocks) +
        "\n\n请输出 JSON：{\"claims\":[{\"content\":\"归因式正文1-2句\",\"grade\":\"fact|experience\","
        "\"source_idx\":来源序号整数,\"quote\":\"引用片段\",\"time_window\":\"如 2025-2026观察\","
        "\"sample_size\":\"experience给整数否则空\"}]}"
    )
    out = chat_json([{"role": "system", "content": _WRITER_SYS},
                     {"role": "user", "content": user}], temperature=0.2, max_tokens=900,
                    client=client, tag="t3-writer")
    claims = out.get("claims") if isinstance(out, dict) else None
    if not (isinstance(claims, list) and claims):  # 排查 writer 抽空：打印模型原始返回
        print(f"  [t3-writer] {company}/{dimension}: 0 claims; out={str(out)[:260]}")
    return claims if isinstance(claims, list) else []


def judge_claim(company: str, dimension: str, claim_content: Optional[str] = None, sources: Optional[list] = None,
                client: Optional[httpx.Client] = None) -> dict:
    """judge：一次判整包来源，返回判词、相关性、支持来源和可证实的样本量。

    兼容既有两参数调用 ``judge_claim(claim, source_text)``；职业洞察主链使用完整四参数形态。
    """
    if claim_content is None and sources is None:
        claim_content, source_text = company, dimension
        company, dimension, sources = "", "", [{"text": source_text}]
    guide = _DIM_GUIDE.get(dimension, dimension)
    blocks = []
    for i, source in enumerate(sources or []):
        blocks.append(f"[来源{i}] publisher={source.get('publisher') or '未知'}\n{(source.get('text') or '')[:1500]}")
    user = (
        f"【目标公司】{company}\n【目标维度】{dimension}（{guide}）\n【结论】{claim_content}"
        f"\n\n【来源原文包】\n" + "\n\n".join(blocks)
    )
    out = chat_json([{"role": "system", "content": _JUDGE_SYS},
                     {"role": "user", "content": user}], temperature=0.0, max_tokens=200,
                    client=client, tag="t3-judge")
    verdict = str(out.get("verdict", "neutral")).strip().lower() if isinstance(out, dict) else "neutral"
    if verdict not in ("entailment", "contradiction", "neutral"):
        verdict = "neutral"
    try:
        conf = float(out.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    support = []
    raw_support = out.get("supported_source_idxs") if isinstance(out, dict) else None
    if isinstance(raw_support, list):
        for raw_idx in raw_support:
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if str(raw_idx).strip() != str(idx) or not (0 <= idx < len(sources or [])) or idx in support:
                continue
            support.append(idx)
    try:
        sample_size = int(out.get("sample_size")) if isinstance(out, dict) and out.get("sample_size") is not None else None
    except (TypeError, ValueError):
        sample_size = None
    if sample_size is not None and sample_size <= 0:
        sample_size = None
    if sample_size is not None:
        literal = re.compile(rf"(?<!\d){re.escape(str(sample_size))}(?!\d)")
        supported_texts = [
            f"{source.get('excerpt') or ''}\n{source.get('text') or ''}"
            for i, source in enumerate(sources or []) if i in support
        ]
        if not any(literal.search(text) for text in supported_texts):
            sample_size = None
    evidence_kind = str(out.get("evidence_kind", "generic")).strip().lower() if isinstance(out, dict) else "generic"
    if evidence_kind not in ("direct", "indirect", "generic", "listing"):
        evidence_kind = "generic"
    confidence = max(0.0, min(1.0, conf))
    if evidence_kind in ("generic", "listing"):
        confidence = min(confidence, 0.4)
    elif evidence_kind == "indirect":
        confidence = min(confidence, 0.8)
    return {"verdict": verdict, "confidence": confidence,
            "reason": str(out.get("reason", ""))[:200] if isinstance(out, dict) else "",
            "company_relevant": out.get("company_relevant") is True if isinstance(out, dict) else False,
            "dimension_relevant": out.get("dimension_relevant") is True if isinstance(out, dict) else False,
            "supported_source_idxs": support,
            "sample_size": sample_size,
            "evidence_kind": evidence_kind}


def run_pipeline(company: str, dimension: str, sources: list,
                 client: Optional[httpx.Client] = None) -> list:
    """T3 经验层完整决策流水线：接地的 sources → 抽取(writer) → 引文预筛 → 逐 claim 判官 → 共识 → 定状态。
    返回 [{claim, judge, status}]；DB 落库由调用方按 status 处理
    （active=展示 / pending_review=边缘队列 / drop=abstain 丢弃）。

    v1 千帆检索延后（用户定）→ sources 由调用方提供（官方披露 / 公开聚合）。本流水线不依赖具体
    retrieval，可用 mock sources 单测；retrieval 接入即生效。
    """
    claims = extract_claims(company, dimension, sources, client=client)
    out = []
    for c in claims:
        idx = c.get("source_idx")
        src = sources[idx] if isinstance(idx, int) and 0 <= idx < len(sources or []) else None
        if not src:
            out.append({"claim": c, "judge": None, "status": "drop"})  # 无可追溯来源 → abstain
            continue
        # 判官之前的零成本预筛：引文不在任何来源正文里 = 编的，直接丢，省一次 LLM 调用
        if not quote_supported(c.get("quote"), [s.get("text") for s in (sources or [])]):
            print(f"  [t3-quote] {company}/{dimension}: 引文不在来源原文里 → drop（未调判官）"
                  f" quote={str(c.get('quote'))[:40]}")
            out.append({"claim": c, "judge": None, "status": "drop"})
            continue
        j = judge_claim(company, dimension, c.get("content", ""), sources, client=client)
        verified = [sources[i] for i in j["supported_source_idxs"]]
        n_pub = len({registrable_host(s.get("url")) for s in verified if registrable_host(s.get("url"))})
        status = final_status(j["verdict"], j["confidence"], c.get("grade", "experience"), n_pub,
                              j["company_relevant"], j["dimension_relevant"])
        claim = dict(c)
        # 样本量只信判官从原文明确识别出的证据，绝不沿用 writer 或检索条数的猜测。
        claim["sample_size"] = j["sample_size"]
        out.append({"claim": claim, "judge": j, "status": status})
    return out
