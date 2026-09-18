"""公司名 → ATS 子域 slug 候选变体（车道 1「猜 slug」的燃料）。

为什么要有它：本土五大 ATS 的域名套路是**固定**的（`{slug}.zhiye.com` / `{slug}.hotjob.cn` /
`{slug}.jobs.feishu.cn` / `app.mokahr.com/social-recruitment/{slug}` / `{slug}.wintalent.cn`），
discover_domestic 早就有确定性探活 oracle —— 猜不中不是因为套路难猜，**是因为 slug 变体太少**
（targets 文件里一家常只有 1~2 个）。一次 LLM 调用能给出 ≤10 个变体（全拼 / 首字母 / 英文名 /
常见缩写 / 去「集团 股份 有限公司」），成本几分钱，且**不吃全局共享的搜索额度**
（见 CLAUDE.md「搜索额度是全局共享的」）。

三条安全边界（都在下游，本模块不负责）：
  · LLM 编出来的 slug 打不开 → discover_domestic 的 oracle 直接 None，不入库；
  · slug 撞上别家真实租户 → discover_domestic 的 title-verify / 自报 company 核验拒掉
    （CLAUDE.md「归属准确性没有旁路」）；
  · 真入库还要过 probe 探活 + 真抓回读健康岗。
所以这里**宁可多给几个变体**，不要在这一层做保守裁剪。

预算：走 llm_budget（kind=slug_variants）。拿不到额度就只返回确定性变体，不抛异常。
env `SLUG_VARIANT_LLM=false` 一关即回退纯确定性变体。
"""
import os
import re

import llm_budget


MAX_VARIANTS = 10
_LLM_ENV = "SLUG_VARIANT_LLM"
_BUDGET_KIND = "slug_variants"

# 去掉这些后缀/前缀词再拼 slug；顺序按长度降序（先剥长的，否则「有限公司」会被「公司」吃掉半截）。
_CN_NOISE = tuple(sorted((
    "股份有限公司", "有限责任公司", "集团股份", "控股集团", "集团公司",
    "有限公司", "科技有限", "控股", "集团", "股份", "公司", "有限",
), key=len, reverse=True))
_EN_NOISE = (
    "corporation", "technologies", "technology", "international", "holdings",
    "holding", "company", "limited", "group", "corp", "inc", "ltd", "co",
)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")


def normalize_slug(value):
    """归一成合法子域片段；不合法返回 None（绝不把带点/带空格的串当 slug 去拼域名）。

    ⚠️ 含 `. / : 空白` 的一律**整条拒掉**，不做「删掉非法字符再用」——
    LLM 偶尔会把整个域名当 slug 返回（`acme.hotjob.cn/x`），硬洗成 `acmehotjobcnx`
    只会拿一个必然打不中的串去白探五个平台，还把真变体挤出 10 个名额。
    """
    raw = str(value or "").strip().lower()
    if re.search(r"[\s./:@]", raw):
        return None
    slug = re.sub(r"[^a-z0-9-]+", "", raw)
    slug = slug.strip("-")
    return slug if _SLUG_RE.match(slug) else None


def deterministic_variants(company, seeds=()):
    """零成本变体：已有 seeds + 英文名去噪 + 常见招聘后缀。不联网、不调 LLM。

    刻意**不做中文转拼音**：本仓库没有拼音依赖，硬编一张表只会覆盖头部公司，
    而头部公司的 slug 本来就已经在 targets 文件里了。中文名交给 LLM 那一步。
    """
    out = []
    for seed in list(seeds or []):
        slug = normalize_slug(seed)
        if slug:
            out.append(slug)
    latin = " ".join(re.findall(r"[A-Za-z0-9]+", str(company or "")))
    if latin:
        words = [w.lower() for w in latin.split() if w.lower() not in _EN_NOISE]
        if words:
            for candidate in ("".join(words), words[0]):
                slug = normalize_slug(candidate)
                if slug:
                    out.append(slug)
    # 招聘站常见后缀变体：只给**第一个**基础变体加，避免 10 个名额被后缀刷满。
    base = out[0] if out else None
    if base:
        out.extend(f"{base}{suffix}" for suffix in ("hr", "recruit", "campus"))
    return _dedupe(out)


def _dedupe(values):
    seen, out = set(), []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def strip_company_noise(company):
    """去掉「集团/股份/有限公司」等噪音词，供 prompt 与人读日志使用。"""
    name = str(company or "").strip()
    for noise in _CN_NOISE:
        name = name.replace(noise, "")
    return name.strip() or str(company or "").strip()


def build_messages(company):
    """LLM 消息体（纯函数，单测直接断言它，不打网络）。"""
    core = strip_company_noise(company)
    return [
        {"role": "system", "content": "你是企业招聘域名助手，只输出 JSON，不解释。"},
        {"role": "user", "content":
            "这家公司在中国主流招聘系统（北森 zhiye.com、hotjob.cn、飞书 jobs.feishu.cn、"
            "Moka、WinTalent）上的**子域 slug** 可能是什么？请给出最多 10 个候选，"
            "覆盖：拼音全拼 / 拼音首字母 / 英文名 / 常见英文缩写 / 去掉「集团 股份 有限公司」后的短名。"
            "只要小写字母数字和连字符，不要域名后缀、不要解释、不确定也要给出你最可能的猜测。"
            "只输出 {\"slugs\": [\"...\"]}。\n"
            f"公司：{company}（核心名：{core}）"},
    ]


def parse_llm_slugs(data):
    """LLM 返回 → 合法 slug 列表。纯函数；形状不对一律返回 []（绝不抛）。"""
    if not isinstance(data, dict):
        return []
    raw = data.get("slugs")
    if not isinstance(raw, list):
        return []
    return _dedupe([slug for slug in (normalize_slug(item) for item in raw) if slug])


def _llm_enabled():
    return str(os.environ.get(_LLM_ENV, "true")).strip().lower() not in ("0", "false", "no", "off")


def variants(company, *, seeds=(), supabase=None, max_variants=MAX_VARIANTS,
             chat=None, budget=None):
    """确定性变体 + （有额度时）一次 LLM 补充，合并去重后截断到 max_variants。

    chat/budget 可注入，单测据此完全离线。LLM 任何失败都静默回落确定性变体 ——
    这是**成本/产出优化**不是安全门，挂了不该拖垮整条漏斗。
    """
    out = deterministic_variants(company, seeds)
    if not _llm_enabled() or len(out) >= max_variants:
        return out[:max_variants]
    gate = budget if budget is not None else llm_budget.check_and_consume
    try:
        if not gate(supabase, kind=_BUDGET_KIND):
            return out[:max_variants]
    except Exception:  # noqa: BLE001 —— 成本闸读不到一律 fail-open，与 llm_budget 同口径
        pass
    caller = chat
    if caller is None:
        try:
            import insight_engine

            caller = lambda messages: insight_engine.chat_json(  # noqa: E731
                messages, max_tokens=300, tag="slug-variants")
        except Exception:  # noqa: BLE001
            return out[:max_variants]
    try:
        data = caller(build_messages(company))
    except Exception:  # noqa: BLE001
        return out[:max_variants]
    return _dedupe(out + parse_llm_slugs(data))[:max_variants]
