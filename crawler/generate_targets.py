"""crawler/generate_targets.py — LLM 定期生成「库里没有的」目标公司候选，喂给 auto_discover 的安全验证流水线。

为何：静态清单会烧完（targets_tech_consumer.json 149 家几天探完就没了）；要「持续保速度」必须**持续产新候选**。
本工具用已配的 SiliconFlow（复用 insight_engine.chat_content）**每天生成一批真实存在、正在招聘的中国科技/新经济/
消费公司**（含 slug 猜测），按行业主题按日轮转，覆盖面滚动铺开。

红线不变（安全全靠下游，本工具不入库、不绕验证门）：
  · 生成的候选只是**探测输入**，一律走 discover_domestic 的 sweep → to_passed（探活通过 + 真有在招岗 +
    标题核验防张冠李戴）才入库；LLM 若编造公司/猜错 slug → 探活不过 → 自动丢弃，绝不污染库。
  · 排除已在库公司（不重复劳动）。
  · env `AUTO_DISCOVER_LLM` 默认关；无 SILICONFLOW_API_KEY 直接返回 []（回退纯静态清单，安全）。

诚实边界：LLM 的「真实公司」宇宙有限（几千家量级），能把库从 ~900 持续喂到几千、撑很久，但不是无限高速；
主题轮转 + 排除已有维持新鲜度，失败候选可能偶尔重复生成（探测廉价，可接受；持久化台账留后期）。
"""
import datetime
import json
import os
import re
import time

import httpx

# n≈50 家公司的 JSON ~2500 tokens；给足余量避免撞上限被截断。旧值 2000 每天都 finish_reason=length
# 截断 → parse 失败 → 喂料返回 [] → 静态清单榨干、扩源停摆（本次修复的根因）。截断仍由 loads_companies 兜底。
GEN_MAX_TOKENS = 4096

# 行业主题（按日轮转，覆盖目标用户关心的全部方向；配合 targets_tech_consumer.json 的分类口径）
_THEMES = [
    ("互联网/生活服务", "本地生活、社区内容、电商、出行、在线旅游、招聘、社交等互联网公司"),
    ("人工智能/大模型", "大模型、AIGC、机器视觉、语音、AI 基础设施、AI 应用公司"),
    ("游戏", "游戏研发与发行公司（端游 / 手游 / 出海）"),
    ("新消费/品牌", "新茶饮、餐饮连锁、美妆个护、食品饮料、潮玩、服饰鞋包、零售品牌"),
    ("智能硬件/机器人", "消费电子、智能家居、清洁电器、可穿戴、无人机、服务机器人公司"),
    ("新能源/智能车", "新能源整车、动力电池、充换电、汽车芯片、激光雷达、智能驾驶 Tier1"),
    ("企业服务/SaaS", "CRM、HR、财税、协同办公、数据分析、低代码、网络安全等 To B 软件公司"),
    ("金融科技/物流", "支付、券商、保险科技、消费金融、快递、供应链、跨境物流公司"),
    ("半导体/硬科技", "芯片设计、半导体设备 / 材料、光电显示、通信设备公司"),
    ("医疗健康/生物", "创新药、医疗器械、CXO、互联网医疗、基因与生命科学公司"),
]

_SYS = (
    "你是中国招聘市场数据专家。只输出**真实存在**的中国公司（含在华外企），严禁编造公司名。"
    "只输出 JSON，格式：{\"companies\":[{\"company\":\"常用名\",\"cn\":\"常用名\","
    "\"slugs\":[\"英文或拼音slug\"],\"industry\":\"行业\"}]}。"
    "company/cn 用公司**常用品牌名 / 简称**（如「迈瑞医疗」而非「深圳迈瑞生物医疗电子股份有限公司」），便于去重与展示。"
    "slugs 给该公司招聘门户最可能用的英文品牌名 / 拼音（2-4 个，全小写、无空格），"
    "用于探测 feishu/moka/beisen/hotjob 的公司子域，例如小红书=[\"xiaohongshu\",\"xhs\"]。"
)


def theme_for(date):
    """按日期轮转主题，覆盖各行业不重样。"""
    return _THEMES[date.toordinal() % len(_THEMES)]


_COMPANY_SUFFIXES = (
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "控股集团",
    "集团控股",
    "集团股份",
    "控股",
    "集团",
    "科技",
    "公司",
    "中国",
)


def norm_company(name):
    """公司名去重规范化：只做括号/空白/大小写与常见后缀归一，不做子串匹配。"""
    s = str(name or "").strip().lower()
    s = re.sub(r"[（(][^（）()]*[）)]", "", s)
    s = re.sub(r"\s+", "", s)
    prev = None
    while s and s != prev:
        prev = s
        for suffix in _COMPANY_SUFFIXES:
            if s.endswith(suffix) and len(s) > len(suffix):
                s = s[:-len(suffix)]
                break
    return s


def build_messages(theme_name, theme_desc, exclude_names, n):
    ex = "、".join(list(exclude_names)[:250])
    user = (
        f"列出 {n} 家【{theme_name}】领域、真实存在且当前在招聘的中国公司（{theme_desc}）。"
        f"优先中大型 / 知名 / 在招岗位多的公司。**必须排除以下已收录公司**：{ex}。只输出 JSON。"
    )
    return [{"role": "system", "content": _SYS}, {"role": "user", "content": user}]


def _salvage_truncated_json(text):
    """纯函数：把**截断的** JSON（LLM 撞 max_tokens）截到最后一个完整的 } / ]，补齐未闭合括号后再 parse。
    只在严格 parse 失败时兜底——不改变正常响应的解析，只把「截断=0 产出」救成「部分产出」（完整对象留、半截丢）。
    做法：扫描时忽略字符串内字符，栈追踪未闭合括号；截到最后一次闭合括号处，逆序补上剩余闭合符。"""
    s = str(text or "")
    stack, in_str, esc = [], False, False
    last_close, stack_at_close = -1, None
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack:
                return None            # 括号不平衡（多了闭合符）→ 放弃
            stack.pop()
            last_close, stack_at_close = i, list(stack)
    if last_close < 0 or not stack_at_close:
        return None                    # 无可截点，或本就闭合（那样第一次严格 parse 就成功了）
    candidate = s[:last_close + 1] + "".join(reversed(stack_at_close))
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def loads_companies(content):
    """纯函数：解析 LLM 生成的公司 JSON。先严格 parse，截断时用 _salvage_truncated_json 救回完整对象。
    总返回 dict（无法解析 → {}，交给 parse_generated 产出 []，安全回退静态清单）。"""
    s = str(content or "").strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        salvaged = _salvage_truncated_json(s)
        return salvaged if isinstance(salvaged, dict) else {}


def parse_generated(data, existing_names):
    """纯函数：从 LLM 返回的（已解析）JSON dict 提取合法候选。
    去重（库里已有 / 批内重复）、清洗 slug（去空、去带空格的）、标 _priority/_llm。"""
    existing = {str(x).strip() for x in (existing_names or set())}
    existing_norm = {norm_company(x) for x in existing if norm_company(x)}
    out, seen, seen_norm = [], set(), set()
    for c in ((data or {}).get("companies") or []):
        if not isinstance(c, dict):
            continue
        name = (c.get("company") or "").strip()
        cn = (c.get("cn") or name).strip()
        slugs = [str(s).strip() for s in (c.get("slugs") or [])
                 if str(s).strip() and " " not in str(s).strip()]
        industry = (c.get("industry") or "").strip()
        if not name or not slugs:
            continue
        nname = norm_company(name)
        is_duplicate = (
            name in existing or name in seen or
            (nname and nname in existing_norm) or
            (nname and nname in seen_norm)
        )
        if is_duplicate:
            continue
        seen.add(name)
        if nname:
            seen_norm.add(nname)
        out.append({"company": name, "cn": cn, "slugs": slugs[:4],
                    "industry": industry, "_priority": True, "_llm": True})
    return out


def llm_generate(existing_names, n=50, date=None):
    """网络：调 LLM 生成一批「库里没有的」目标公司候选。无 key / 失败 → 返回 []（安全回退）。"""
    if not os.environ.get("SILICONFLOW_API_KEY"):
        return []
    date = date or datetime.datetime.now(datetime.timezone.utc).date()
    tname, tdesc = theme_for(date)
    try:
        import insight_engine as ie  # 复用现成 SiliconFlow 客户端（config + json_object 兜底）
        messages = build_messages(tname, tdesc, existing_names, n)
        content = ""
        for attempt in range(2):
            try:
                # 取原始 content 自己解析 → 撞 max_tokens 截断也能救回完整公司（loads_companies），
                # 而不是像旧 chat_json 那样整段 parse 失败返回 []（截断=每天 0 产出的根因）。
                content = ie.chat_content(messages, temperature=0.5,
                                          max_tokens=GEN_MAX_TOKENS, timeout=90)
                break
            except httpx.TimeoutException:
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise
        data = loads_companies(content)
    except Exception as e:
        print(f"[generate_targets] LLM 失败，跳过（回退静态清单）: {type(e).__name__}: {str(e)[:80]}")
        return []
    cands = parse_generated(data, existing_names)
    print(f"[generate_targets] 主题【{tname}】LLM 生成 {len(cands)} 家「库里没有的」新候选")
    return cands
