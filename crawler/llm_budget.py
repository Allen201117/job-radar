"""llm_usage 表预算守卫：LLM 调用**当日总次数**天花板（跨 CI run 持久），镜像 search_budget。

为什么要有：搜索侧一直有 search_budget 日顶，LLM 侧一个闸门都没有 —— 花多少全看队列多长，
没有上限（线上实测 130~243 次/天，账户欠费三天都没人察觉）。本模块给 LLM 装同款闸：
超日顶后 `check_and_consume()` 返回 False，**调用方跳过这次 LLM 继续跑完主任务**，不抛异常。

四条设计取舍（改之前先读，改了要保住）：

1) 天花板按「全部非豁免 kind 当日之和」判，不是每个 kind 各给一份额度 —— 否则 kind 一多，
   总花费又没上限，等于没装天花板。按 kind 分行存只为**归因**（看钱花在哪条链上）。

2) 豁免 kind（EXEMPT_KINDS）不计数、不受限、不走 DB：简历解析是用户点一下就要出结果的实时
   功能，被日顶挡住 = 用户功能直接坏掉，属于「宁可多花钱也不能坏」的一类；要封的是后台批量
   富化（洞察 T3 那种一晚上几百次的）。
   ⚠️ 现状说明：简历解析当前走 JS 侧 lib/llm.js，根本不经过本模块。这里先把口子和规矩留出来，
   免得以后接线时顺手把实时链路一起锁死。

3) 读/写计数失败一律 **fail-open**（放行 + 打日志），因为这是**成本闸不是安全闸**：Supabase 抖
   一下就让整条洞察链停摆，代价远大于多花一轮 LLM；而且真到 Supabase 挂掉时 T3 也写不进洞察，
   不会闷头空烧。要的是「正常情况下封死失控」，不是「异常情况下宁停勿放」。

4) read-modify-write 不是原子的（PostgREST 不支持 `used = used + 1`），与 search_budget 同口径：
   串行调用精确，并发调用可能少算几次。天花板允许有几次误差，不允许没有。

用法（调用方按这个接：拿不到额度就跳过 LLM，别抛）：
    import llm_budget
    if not llm_budget.check_and_consume(sb, kind="insight_t3"):
        return  # 今日 LLM 额度用尽 → 跳过本次调用，剩余队列留到下轮
    resp = call_llm(...)
"""
import os
import sys
from datetime import datetime, timezone

LLM_USAGE_TABLE = "llm_usage"

# 默认日顶：线上实测 130~243 次/天 → 250 够当前用量，同时把失控封死（远超即说明出事了）。
# 想临时放开就调 env LLM_DAILY_CAP；**不要用 0 表示不限制**——0 与 search_budget 同口径 = 全挡。
DEFAULT_DAILY_CAP = 250
CAP_ENV = "LLM_DAILY_CAP"

# 豁免 kind：实时/用户触发链路，不计数也不受日顶限制（理由见模块 docstring 第 2 条）。
DEFAULT_EXEMPT_KINDS = ("resume_parse",)
EXEMPT_ENV = "LLM_BUDGET_EXEMPT_KINDS"

# 后台富化默认 kind（洞察 T3 = 当前 86% 的 LLM 花费所在）
DEFAULT_KIND = "insight_t3"


def _today():
    return datetime.now(timezone.utc).date().isoformat()


# ---------- 纯函数区（无 DB / 无 env，可直接单测） ----------

def normalize_kind(kind):
    """kind 归一：去空白 + 小写；空值回落默认 kind（绝不产生空字符串主键）。"""
    name = str(kind or "").strip().lower()
    return name or DEFAULT_KIND


def parse_cap(raw, default=DEFAULT_DAILY_CAP):
    """env 字符串 → 日顶整数。非法值回落默认（打错一个字符不该变成 0 = 全挡）。"""
    try:
        cap = int(str(raw).strip())
    except (TypeError, ValueError, AttributeError):
        return default
    return cap if cap >= 0 else default


def parse_kinds(raw, default=DEFAULT_EXEMPT_KINDS):
    """env 字符串 → 豁免 kind 集合；未配置回落默认。显式配空串 = 谁都不豁免。"""
    if raw is None:
        return frozenset(normalize_kind(k) for k in default)
    names = {normalize_kind(c) for c in str(raw).replace("，", ",").split(",") if c.strip()}
    return frozenset(names)


def allows(used_count, cap, n=1):
    """纯判定：当日已用 used_count 的前提下，再花 n 次会不会破顶。cap<=0 一律不放行。"""
    try:
        used_count = max(0, int(used_count or 0))
        cap = int(cap or 0)
        n = max(1, int(n or 1))
    except (TypeError, ValueError):
        return False
    return cap > 0 and used_count + n <= cap


def sum_counted(rows, exempt=()):
    """纯函数：把当日计数行里**非豁免 kind** 的 used 加起来 = 天花板判定用的分母。"""
    exempt = {normalize_kind(k) for k in exempt or ()}
    total = 0
    for row in rows or []:
        row = row or {}
        if normalize_kind(row.get("kind")) in exempt:
            continue
        try:
            total += max(0, int(row.get("used") or 0))
        except (TypeError, ValueError):
            continue
    return total


def used_of(rows, kind):
    """纯函数：取某个 kind 当日已用次数（用于 read-modify-write 的 modify 一步）。"""
    kind = normalize_kind(kind)
    for row in rows or []:
        row = row or {}
        if normalize_kind(row.get("kind")) == kind:
            try:
                return max(0, int(row.get("used") or 0))
            except (TypeError, ValueError):
                return 0
    return 0


# ---------- env 读取 ----------

def daily_cap():
    return parse_cap(os.environ.get(CAP_ENV), DEFAULT_DAILY_CAP)


def exempt_kinds():
    return parse_kinds(os.environ.get(EXEMPT_ENV), DEFAULT_EXEMPT_KINDS)


def is_exempt(kind):
    return normalize_kind(kind) in exempt_kinds()


# ---------- DB 旁路区（失败只打日志，绝不抛给主任务） ----------

def _fetch_rows(sb):
    """读当日全部 kind 计数行。返回 (rows, ok)；ok=False 表示读失败 → 调用方 fail-open。"""
    try:
        data = (sb.table(LLM_USAGE_TABLE).select("kind,used")
                .eq("day", _today()).execute().data) or []
        return list(data), True
    except Exception as exc:  # noqa: BLE001 - 成本闸不得打断主任务
        sys.stderr.write(f"[llm-budget] 读当日计数失败（本次放行）: {type(exc).__name__}\n")
        return [], False


def _write(sb, kind, value):
    """写回某 kind 当日计数。失败返回 False 并吞掉异常（照 ops_runs 旁路台账范式）。"""
    try:
        sb.table(LLM_USAGE_TABLE).upsert(
            {"kind": kind, "day": _today(), "used": int(value),
             "updated_at": datetime.now(timezone.utc).isoformat()},
            on_conflict="kind,day",
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - 计数写不进去不能拖垮主任务
        sys.stderr.write(f"[llm-budget] {kind} 计数写入失败（主任务不受影响）: {type(exc).__name__}\n")
        return False


def used_today(sb, kind=None):
    """当日已用次数。kind=None → 全部非豁免 kind 之和（= 天花板口径）；给 kind → 只看该条链。"""
    rows, _ok = _fetch_rows(sb)
    if kind is None:
        return sum_counted(rows, exempt_kinds())
    return used_of(rows, kind)


def remaining(sb, cap=None):
    """当日剩余额度（供调用方打日志 / 写 ops_runs 的 budget_left）。读失败按满额算。"""
    limit = daily_cap() if cap is None else parse_cap(cap)
    return max(0, limit - used_today(sb))


def check_and_consume(sb, kind=DEFAULT_KIND, n=1, cap=None):
    """要 n 次 LLM 额度：够就记账并返回 True，超日顶返回 False（调用方跳过 LLM，别抛异常）。

    kind 在豁免名单里 → 直接 True，且**零 DB 往返**（实时链路不该为记账多付一次跨洋延迟）。
    读/写计数失败 → True（fail-open，理由见模块 docstring 第 3 条）。
    """
    kind = normalize_kind(kind)
    exempt = exempt_kinds()
    if kind in exempt:
        return True
    limit = daily_cap() if cap is None else parse_cap(cap)
    rows, ok = _fetch_rows(sb)
    if not ok:
        return True
    counted = sum_counted(rows, exempt)
    if not allows(counted, limit, n):
        sys.stderr.write(
            f"[llm-budget] 今日 LLM 额度用尽（已用 {counted}/{limit}，本次请求 {n} 次，kind={kind}）"
            f"→ 跳过本次 LLM 调用；要放开改 env {CAP_ENV}\n")
        return False
    _write(sb, kind, used_of(rows, kind) + max(1, int(n or 1)))
    return True
