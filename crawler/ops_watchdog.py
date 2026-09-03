#!/usr/bin/env python3
"""后台任务真产出告警（watchdog）：每天扫一遍台账 + workflow 历史，把「静默坏掉」变成 GitHub Issue。

为什么要有它（2026-08-27 实测）：本项目历次重大故障的共同点是**静默**——不是没坏，是坏了很久没人知道。
  · db-report / production-smoke 各自 47 天没跑，因为它俩压根没有 schedule；
  · discovery_runs(mode='insight_enrich') 8 条卡在 queued，最早的 52 天没被回写过；
  · dead-link-audit 某次 run 级是 cancelled，job 级却是 success/cancelled 混着——**只看 run 级会漏**；
  · 29 个 workflow 零告警出口，谁都不会主动叫。
所以判据只问「跑没跑」不够，必须问「产出了什么」，而且必须有一个会主动叫的出口。

五条规则（方案见 docs/superpowers/specs/2026-08-27-observability-and-ux-plan.md §2.2）：
  A 连续零产出：某模块连续 N 天（默认 2）**有处理量却零产出**，或当天所有 run 全失败。
    ⚠️ 空队列（处理量=0）产出 0 是正常的，一律不告——否则天天喊狼来了，等于没有告警。
  B 被中途杀掉：**按 job 级判**（run 级会骗人）——① job cancelled 且时长 ≥ 声明 timeout 的 95%
    （板上钉钉的超时杀）；② 同一 workflow 反复出现 cancelled job（手动取消是偶发一次，天天被杀必有原因）。
  C 台账不回写：discovery_runs 里 queued 超过 6 小时的行。
  D 账户级错误：401/402/403，或 429 且正文含 quota/insufficient——欠费返 **402**，只认 401/403 会漏。
  E 关键任务超期未跑：cron 声明周期 ×2（下限 24h，容忍 GitHub 偶尔丢触发）仍无运行记录。

出口 = 本仓库 GitHub Issue。防刷屏：每类告警标题固定，已有同标题的 open issue 就**追评论、不新开**。
默认 dry-run（只打印会开什么 issue，零写入）；--apply / OPS_WATCHDOG_APPLY=true 才真开。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
_TRUE = ("1", "true", "yes", "on")

ISSUE_PREFIX = "[watchdog]"
RULE_TITLES = {
    "A": "连续零产出",
    "B": "任务被中途杀掉",
    "C": "台账卡住未回写",
    "D": "账户级错误",
    "E": "关键任务超期未跑",
    "F": "源连续失败",
    "G": "源抓不全",
}

# ── 规则 A：每个模块的「产出口径」与「处理量口径」────────────────────────────
# produced = 这轮真的产出了什么（不是「跑了几次」）；work = 这轮有没有活干（判空队列）。
# 只有「有活干却零产出」才算异常。没在表里的模块 = 口径未声明 → 跳过，不猜（跑起来会打印出来，
# 提醒把新模块补进来），绝不拿猜的口径去告警。
MODULE_OUTPUT = {
    # 模块: (产出计数键, 处理量计数键)
    "auto_discover": (("produced",), ("checked",)),
    "auto_discover_browser": (("produced",), ("checked",)),
    "auto_discover_overseas": (("produced",), ("checked",)),
    "enrich_backlog": (("enriched",), ("checked",)),
    "liveness_sweep": (("checked",), ("checked",)),
    "dead_link_audit": (("checked",), ("checked",)),
    "insight_backlog": (("companies_enriched",), ("checked",)),
    "annual_report": (("written",), ("checked",)),
    "gap_funnel": (("sources_added",), ("processed",)),
    "gap_funnel_browser": (("sources_added",), ("processed",)),
    "campus_official_backlog": (("verified", "draft"), ("companies_processed",)),
    "campus_cycle_backlog": (("verified", "draft"), ("companies_processed",)),
    "campus_lane": (("snapshots",), ("sources",)),
    "bu_extract": (("kept",), ("companies_scanned",)),
    # 有主体可算却一条指标都没产出 = 洞察库页面会空着，属零产出。
    "bu_signals": (("items_written",), ("subjects_scanned",)),
    # 有待判档的条目却一条都没判出来 = 档位筛选会一直空着，属零产出。
    "insight_grade_extract": (("graded",), ("scanned",)),
    # run.py 每轮抓取收尾写的台账（2026-09-03）：有源可抓却一个岗都没拿到 = 零产出。
    "daily_crawl": (("jobs_found_total",), ("sources_total",)),
}

# 规则 F：一个源在回看窗口内「每一轮都失败」才告警。
# 2026-09-03 实测：11 个源一周 28 轮全挂（Workday 站点名错 / 板块改名 / 反爬 403 / 浏览器没装），
# 每轮各自被吞成 crawl_runs 一行 failed，模块级绿灯完全看不见——只有源级视角才抓得到。
DEAD_SOURCE_MIN_RUNS = 8   # 少于这个次数不判（新源、低频源不冤枉）

# 「0 就是正常」的模块：产出为 0 表示没东西可做，不是坏了 → 明确排除在规则 A 之外，
# 也不用在日志里提醒「补口径」。
#   insight_staleness：retired=0 = 当天没有过期洞察
#   purge_expired：deleted=0 = 当天没有确认撤下的死岗
#   ops_watchdog：本模块自己的台账
NO_OUTPUT_MODULES = ("insight_staleness", "purge_expired", "ops_watchdog")

# 规则 D：已落库的账户级错误信号。lib/track.ts 把 402/余额不足归一成 llm_insufficient_balance、
# 把 401/403 归一成 llm_auth_error，写进 events.payload.diagnostics.error_code——用户侧真实踩到的欠费。
ACCOUNT_ERROR_CODES = ("llm_insufficient_balance", "llm_auth_error")

DEFAULT_JOB_TIMEOUT_MIN = 360   # GitHub Actions job 默认超时
TIMEOUT_KILL_RATIO = 0.95       # 时长 ≥ 声明 timeout 的 95% + 被 cancel = 基本可判定是超时杀的
# 规则 E 的下限。本 watchdog 本身就是每天跑一次，比一天更细的分辨率没有意义；
# 而 GitHub 会丢 schedule 触发（本项目实测丢过 2/3），把下限设成小时级会天天误报高频任务。
# 24h 一次都没跑 = 真死了，这个判据不会冤枉谁。
OVERDUE_FLOOR_MIN = 1440

# 规则 G：抓全率。ratio 低于此值 + 缺口绝对量够大，才算「真的漏了」——两个条件缺一不可，
# 否则 700 个源里天天有几十个因为四舍五入进榜，告警就没人看了。
COVERAGE_RATIO_FLOOR = 0.9
COVERAGE_MIN_GAP = 200      # 单源少抓这么多才值得开口（约等于「一个源整整少了 4 页」）
COVERAGE_TOTAL_GAP = 2000   # 全站累计缺口低于这个数就先不吵（正常抖动区间）


# ══════════════════ 纯函数层（可单测、不打网络）══════════════════

def is_account_level_error(status_code, body=""):
    """账户级错误 = 这把 key / 这个账号本身不可用，重试多少次都一样。

    402 是欠费的标准返回，历史上判据只认 401/403 → CI 全绿地空烧了两天额度。
    429 只有在正文点名额度时才算账户级；否则是瞬时限流，退避重试即可，不该惊动人。
    """
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        code = 0
    if code in (401, 402, 403):
        return True
    text = str(body or "").casefold()
    if code == 429 and ("quota" in text or "insufficient" in text or "额度" in text):
        return True
    return ("balance" in text and "insufficient" in text) or "余额不足" in text


def _cron_field(field, lo, hi):
    """cron 单字段 → 取值集合；支持 * / */N / a-b / 逗号列表。解析不了返回 None。"""
    out = set()
    for part in str(field).split(","):
        part = part.strip()
        if not part:
            return None
        step = 1
        if "/" in part:
            part, _, raw_step = part.partition("/")
            if not raw_step.isdigit() or int(raw_step) <= 0:
                return None
            step = int(raw_step)
            part = part.strip() or "*"
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, _, b = part.partition("-")
            if not (a.strip().isdigit() and b.strip().isdigit()):
                return None
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
        else:
            return None
        if start < lo or end > hi or start > end:
            return None
        out.update(range(start, end + 1, step))
    return out or None


def cron_max_gap_minutes(expr):
    """一周内相邻两次触发的**最大**间隔（分钟）；解析不了返回 None。

    取最大而不是平均：`0 1,7,13,17 * * *` 的平均间隔是 6h、真实最大是 8h，
    用平均会把正常的 8h 空档判成「超期未跑」。
    """
    fields = str(expr or "").split()
    if len(fields) != 5:
        return None
    minutes = _cron_field(fields[0], 0, 59)
    hours = _cron_field(fields[1], 0, 23)
    if minutes is None or hours is None:
        return None
    if fields[2].strip() != "*":     # 按「每月几号」触发的不猜周期（本仓库没有）
        return None
    dows = _cron_field(fields[4], 0, 7)
    if dows is None:
        return None
    dows = {0 if d == 7 else d for d in dows}   # cron 里 7 和 0 都是周日
    fires = sorted(d * 1440 + h * 60 + m for d in dows for h in hours for m in minutes)
    if not fires:
        return None
    gaps = [b - a for a, b in zip(fires, fires[1:])]
    gaps.append(fires[0] + 7 * 1440 - fires[-1])
    return max(gaps)


_CRON_LINE = re.compile(r'^-\s*cron:\s*(?:"([^"]*)"|\'([^\']*)\'|([^#]*))')


def parse_workflow_meta(text):
    """从 workflow yml 文本里抠出 cron 与各 job 的 timeout-minutes（不引 PyYAML 依赖）。

    注释掉的 cron 不算声明——本仓库 6 个 LLM workflow 就是靠注释 cron 停掉的，
    把它们当「该跑没跑」会天天误报。
    """
    crons, jobs = [], []
    in_jobs, cur = False, None
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        m = _CRON_LINE.match(stripped)
        if m:
            value = next((g for g in m.groups() if g is not None), "").strip()
            if value:
                crons.append(value)
            continue
        if re.match(r"^jobs:\s*$", line):
            in_jobs, cur = True, None
            continue
        if in_jobs:
            if line and not line[0].isspace():
                in_jobs, cur = False, None
                continue
            m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
            if m:
                cur = {"key": m.group(1), "name": None, "timeout": None}
                jobs.append(cur)
                continue
            if cur is not None:
                m = re.match(r"^    name:\s*(.+?)\s*$", line)
                if m:
                    cur["name"] = m.group(1).strip("\"'")
                m = re.match(r"^    timeout-minutes:\s*(\d+)", line)   # 4 空格=job 级；8 空格是 step 级
                if m:
                    cur["timeout"] = int(m.group(1))
    declared = [j["timeout"] for j in jobs if j["timeout"]]
    return {
        "crons": crons,
        "jobs": jobs,
        "max_timeout": max(declared) if declared else None,
        "max_gap_minutes": max(
            (g for g in (cron_max_gap_minutes(c) for c in crons) if g), default=None
        ),
    }


def timeout_for_job(meta, job_name):
    """GitHub 上的 job 名 → yml 里声明的 timeout-minutes。矩阵 job 名是 `key (值)`，按前缀认。"""
    name = str(job_name or "")
    for job in (meta or {}).get("jobs", []):
        for label in (job.get("name"), job.get("key")):
            if not label:
                continue
            if name == label or name.startswith(label + " ("):
                return job.get("timeout") or (meta.get("max_timeout") or DEFAULT_JOB_TIMEOUT_MIN)
    return (meta or {}).get("max_timeout") or DEFAULT_JOB_TIMEOUT_MIN


def _as_dt(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def aggregate_ops_runs(rows):
    """ops_runs 行 → {module: {run_date: {runs, failed, metrics}}}。"""
    agg = defaultdict(lambda: defaultdict(lambda: {"runs": 0, "failed": 0, "metrics": Counter()}))
    for row in rows or []:
        module = str((row or {}).get("module") or "")
        day = str((row or {}).get("run_date") or "")
        if not module or not day:
            continue
        bucket = agg[module][day]
        bucket["runs"] += 1
        if (row.get("status") or "") == "failed":
            bucket["failed"] += 1
        for key, value in (row.get("metrics") or {}).items():
            bucket["metrics"][key] += _num(value)
    return agg


def module_day_state(day_bucket, spec):
    """一个模块某一天的状态：ok / zero / idle / no_run。

    zero 有两种成因，都算「今天什么也没产出」：所有 run 全失败，或有活干但产出为 0。
    """
    if not day_bucket or day_bucket["runs"] <= 0:
        return "no_run", "当天无运行记录"
    produced_keys, work_keys = spec
    metrics = day_bucket["metrics"]
    if day_bucket["failed"] >= day_bucket["runs"]:
        return "zero", f"{day_bucket['runs']} 次运行全部失败"
    work = sum(metrics.get(k, 0) for k in work_keys)
    produced = sum(metrics.get(k, 0) for k in produced_keys)
    detail = (f"处理 {'+'.join(work_keys)}={work:g}，"
              f"产出 {'+'.join(produced_keys)}={produced:g}，"
              f"运行 {day_bucket['runs']} 次（失败 {day_bucket['failed']} 次）")
    if work <= 0:
        return "idle", detail + "；队列是空的，0 产出正常"
    if produced <= 0:
        return "zero", detail
    return "ok", detail


def complete_days(today, count):
    """取 today（Asia/Shanghai 日期）之前的 count 个完整日。

    今天故意不算：watchdog 跑在 UTC 01:00，很多任务当天还没跑完，
    把半天的数据当一整天判会误报。
    """
    base = datetime.strptime(str(today), "%Y-%m-%d").date()
    return [(base - timedelta(days=i)).isoformat() for i in range(count, 0, -1)]


def evaluate_zero_output(rows, today, days=2, muted=()):
    """规则 A：连续 days 天「什么也没产出」→ 告警。"""
    agg = aggregate_ops_runs(rows)
    window = complete_days(today, days)
    muted = {str(m).strip() for m in (muted or []) if str(m).strip()}
    findings, skipped = [], []
    for module in sorted(set(agg) | set(MODULE_OUTPUT)):
        if module in muted or module in NO_OUTPUT_MODULES:
            continue
        spec = MODULE_OUTPUT.get(module)
        if not spec:
            skipped.append(module)
            continue
        states = [module_day_state(agg.get(module, {}).get(day), spec) for day in window]
        if not states or not all(state == "zero" for state, _ in states):
            continue
        findings.append({
            "rule": "A",
            "subject": module,
            "summary": f"模块 `{module}` 连续 {days} 天没有任何产出。",
            "evidence": [f"{day}：{detail}" for day, (_, detail) in zip(window, states)],
            "next": "先看该模块最近一次 workflow 日志：是队列取空了、平台变了，还是 key / 额度没了。",
        })
    return findings, skipped


def evaluate_dead_sources(crawl_rows, sources_by_id, days=5, min_runs=DEAD_SOURCE_MIN_RUNS):
    """规则 F：某个 enabled 源在近 days 天内跑了 ≥ min_runs 次且**全部** failed → 告警。

    每个源一个 finding（标题稳定 = 同源去重）；evidence 带最常见的错误首行，看一眼就知道是
    站点名错 / 板块改名 / 反爬 / 环境缺件，直接决定「改 URL / 停用 / 修 adapter」。
    只看 status=='failed'：partial_success / 空产出不算（那是规则 A 的口径）。"""
    by_source = defaultdict(lambda: {"n": 0, "failed": 0, "errors": Counter()})
    for row in crawl_rows or []:
        sid = row.get("source_id")
        if not sid:
            continue
        agg = by_source[sid]
        agg["n"] += 1
        if row.get("status") == "failed":
            agg["failed"] += 1
            agg["errors"][str(row.get("error_message") or "")[:100]] += 1
    findings = []
    for sid, agg in sorted(by_source.items()):
        source = sources_by_id.get(sid)
        if not source or not source.get("enabled", True):
            continue
        if agg["n"] < min_runs or agg["failed"] != agg["n"]:
            continue
        top_error = agg["errors"].most_common(1)[0][0] if agg["errors"] else "(无错误信息)"
        label = f"{source.get('adapter_name') or '?'} / {source.get('company') or sid}"
        findings.append({
            "rule": "F",
            "subject": label,
            "summary": f"源 `{label}` 近 {days} 天 {agg['n']} 轮抓取全部失败，一个岗都没进库。",
            "evidence": [f"最常见错误：{top_error}",
                         f"source_url：{source.get('source_url') or '?'}"],
            "next": "按错误类型处置：4xx 站点名/板块名错 → 改 source_url；403/反爬 → 停用（不绕）；"
                    "环境缺件（浏览器不存在等）→ 修 workflow；其它 → 修 adapter。别让它继续每轮白跑。",
        })
    return findings


def evaluate_coverage_shortfall(crawl_rows, sources_by_id,
                                ratio_floor=COVERAGE_RATIO_FLOOR,
                                min_gap=COVERAGE_MIN_GAP,
                                total_gap=COVERAGE_TOTAL_GAP):
    """规则 G：源「跑绿了但没抓全」——官网自报 N 个岗，我们只入库了远少于 N 个。

    为什么必须自动报：这类源 status 全是 success，模块级绿灯、源级也不失败，唯一的痕迹是
    crawl_runs.coverage_complete=false。2026-09-04 人肉跑 SQL 才发现 32 个源在这么漏，
    累计 10.7 万个岗，其中 74% 是必投清单公司——**没有告警的指标等于没有指标**。

    ⚠️ 只认 coverage_complete **is False**，不看 true。true 且 found<reported 的那批
    （smartrecruiters / successfactors 等外企 ATS）不是抓不全，是**分母口径**问题：
    它们的 reported_total 取的是接口全球总数，而我们抓完还按 sources.regions 做了地区后置过滤，
    自然 found≪reported。把它们算进来只会让这条规则天天喊狼来了。

    输出**一条聚合 finding**（不是每源一条）：subject 固定，标题稳定可去重；正文按缺口排序
    列出最该看的几个，直接决定「调 CRAWL_MAX_JOBS 档位 / 修 adapter 分页 / 这源本来就该停」。
    """
    # ⚠️ 先按源挑出**最后一轮**，再判这一轮抓没抓全。顺序反过来（先滤掉 complete=true 再挑最新）
    # 会让「早上没抓全、晚上抓全了」的源继续被报——最后一轮才是当下的真实状态。
    latest = {}
    for row in crawl_rows or []:
        sid = row.get("source_id")
        if not sid or row.get("reported_total") in (None, ""):
            continue   # 没有分母的轮次不参与判定，也不该顶掉有分母的轮次
        started = _as_dt(row.get("started_at"))
        prev = latest.get(sid)
        if prev is None or prev[0] is None or (started and started > prev[0]):
            latest[sid] = (started, row)

    shortfalls = []
    for sid, (_started, row) in latest.items():
        source = sources_by_id.get(sid)
        if not source or not source.get("enabled", True):
            continue
        if row.get("coverage_complete") is not False:   # None（不可判定）和 True 都不算
            continue
        reported = _num(row.get("reported_total")) or 0
        found = _num(row.get("jobs_found")) or 0
        gap = int(reported - found)
        if reported <= 0 or gap < min_gap or found >= reported * ratio_floor:
            continue
        shortfalls.append({
            "company": source.get("company") or sid,
            "adapter": source.get("adapter_name") or "?",
            "reported": int(reported), "found": int(found), "gap": gap,
        })

    if not shortfalls:
        return []
    shortfalls.sort(key=lambda x: -x["gap"])
    grand = sum(x["gap"] for x in shortfalls)
    if grand < total_gap:
        return []

    by_adapter = Counter()
    for item in shortfalls:
        by_adapter[item["adapter"]] += item["gap"]
    evidence = [
        f"{item['company']}（{item['adapter']}）：官网自报 {item['reported']}，只入库 {item['found']}，"
        f"少 {item['gap']}"
        for item in shortfalls[:8]
    ]
    if len(shortfalls) > 8:
        evidence.append(f"…还有 {len(shortfalls) - 8} 个源没列出来")
    evidence.append("按 adapter 汇总缺口：" + "、".join(
        f"{name} {gap}" for name, gap in by_adapter.most_common(5)))
    return [{
        "rule": "G",
        "subject": "抓取覆盖",
        "summary": f"{len(shortfalls)} 个源本轮没抓全，累计少入库 {grand} 个岗位"
                   f"（官网自报的都拿得到，是我们自己停在半路）。",
        "evidence": evidence,
        "next": "先看缺口最大的那个 adapter：撞条数上限 → 调 CRAWL_MAX_JOBS / "
                "CRAWL_MAX_JOBS_MUST_APPLY 档位；翻页在中途报错 → 修 adapter 分页；"
                "这源本来就不该抓那么多 → 停用或降档。别让它继续每轮漏同一批岗。",
    }]


def evaluate_timeout_kills(runs, jobs_by_run, meta_by_path, ratio=TIMEOUT_KILL_RATIO, min_repeats=2):
    """规则 B：按 **job 级** 判「任务被中途杀掉」。

    为什么必须看 job 级：run 级状态会骗人——dead-link-audit 有过 run 级 cancelled、job 级却是
    success,success,cancelled,success,success,cancelled,skipped 的实例。只看 run 级，要么以为
    「有人手动取消了一次」，要么整条漏掉。

    两条判据（都基于 job 级，issue 正文里会写明是哪条命中）：
      ① 撞上声明 timeout：job cancelled 且时长 ≥ 声明 timeout 的 95% → 板上钉钉是超时杀。
      ② 反复被杀：同一 workflow 在回看窗口里 ≥ min_repeats 次 run 出现 cancelled job。
         手动取消是偶发一次，天天被杀一定有系统性原因。
         ⚠️ 判据 ② 不是补充、是必需：2026-08-27 实测 dead-link-audit 22:00 那档的 6 个分片
         每晚都在**第 90 分钟整**被杀，而它声明的 timeout 是 150 分钟——仓库里也搜不到任何
         cancel-in-progress / 手动取消。只按判据 ① 判，这件天天发生的事永远告不出来。
    """
    hits = defaultdict(lambda: {"lines": [], "runs": set(), "timeout_hit": False})
    for run in runs or []:
        run_id = run.get("id")
        meta = meta_by_path.get(run.get("path") or "", {})
        for job in jobs_by_run.get(run_id, []) or []:
            if (job.get("conclusion") or "") != "cancelled":
                continue
            started, done = _as_dt(job.get("started_at")), _as_dt(job.get("completed_at"))
            if not started or not done:
                continue
            minutes = (done - started).total_seconds() / 60.0
            limit = timeout_for_job(meta, job.get("name"))
            bucket = hits[run.get("path") or "?"]
            bucket["runs"].add(run_id)
            if minutes >= limit * ratio:
                bucket["timeout_hit"] = True
            bucket["lines"].append(
                f"{run.get('created_at', '?')} run #{run.get('run_number', '?')} "
                f"的 job「{job.get('name')}」跑了 {minutes:.0f} 分钟被杀，"
                f"声明上限 {limit} 分钟"
                f"{'（已撞到 timeout）' if minutes >= limit * ratio else '（没到 timeout，另有原因）'}"
                f"，run 级结论是 {run.get('conclusion')}"
            )
    findings = []
    for path, bucket in sorted(hits.items()):
        repeats = len(bucket["runs"])
        if not bucket["timeout_hit"] and repeats < min_repeats:
            continue      # 只被杀过一次又没撞 timeout = 大概率有人手动点了取消，不惊动人
        name = path.rsplit("/", 1)[-1]
        why = ("有 job 撞到声明的 timeout 被杀" if bucket["timeout_hit"]
               else f"{repeats} 次运行都有 job 被中途杀掉，但都没撞到声明的 timeout（说明另有原因）")
        findings.append({
            "rule": "B",
            "subject": name,
            "summary": f"`{name}` {why}，不是正常跑完（共 {len(bucket['lines'])} 个 job 被杀）。",
            "evidence": bucket["lines"][:10],
            "next": ("撞 timeout 的：拆片 / 降量 / 调 timeout-minutes。"
                     "没撞 timeout 却每次都被杀的：先确认是谁杀的（并发取消、runner 被回收、外部 cancel），"
                     "别让它天天跑一半还显示绿灯。"),
        })
    return findings


def evaluate_stuck_ledger(rows, now=None, hours=6):
    """规则 C：discovery_runs 里 queued 超过 hours 小时 = 派单出去没人回写。"""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    stuck = []
    for row in rows or []:
        if (row or {}).get("status") != "queued":
            continue
        created = _as_dt(row.get("created_at"))
        if created and created <= cutoff:
            stuck.append((created, row))
    if not stuck:
        return []
    stuck.sort(key=lambda item: item[0])
    modes = Counter(str((row.get("mode") or "?")) for _, row in stuck)
    oldest_days = (now - stuck[0][0]).total_seconds() / 86400.0
    return [{
        "rule": "C",
        "subject": "discovery_runs",
        "summary": (f"`discovery_runs` 有 {len(stuck)} 条派单卡在 queued 超过 {hours} 小时，"
                    f"最久的一条已经 {oldest_days:.0f} 天没被回写。"),
        "evidence": [f"按 mode 分：{dict(modes)}"] + [
            f"{created.isoformat()} mode={row.get('mode')} "
            f"公司/查询={row.get('company') or row.get('query') or '-'}"
            for created, row in stuck[:10]
        ],
        "next": "查对应 workflow 有没有被真的 dispatch 出去；跑完必须回写终态，否则台账永远是脏的。",
    }]


def evaluate_account_errors(events, ops_rows, now=None, hours=48):
    """规则 D：已落库的账户级错误信号（欠费 / key 失效），一条都不该被绿灯盖住。"""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    by_code = defaultdict(list)
    for row in events or []:
        created = _as_dt((row or {}).get("created_at"))
        if not created or created < cutoff:
            continue
        code = (((row.get("payload") or {}).get("diagnostics") or {}).get("error_code") or "")
        if code in ACCOUNT_ERROR_CODES:
            by_code[code].append(f"{created.isoformat()} 事件 {row.get('event')}")
    for row in ops_rows or []:
        metrics = (row or {}).get("metrics") or {}
        for key, value in metrics.items():
            if "account_error" in str(key) and value:
                by_code["ops_runs.account_error"].append(
                    f"{row.get('run_date')} 模块 {row.get('module')} 台账标了 {key}={value}"
                )
    findings = []
    for code, lines in sorted(by_code.items()):
        findings.append({
            "rule": "D",
            "subject": code,
            "summary": (f"近 {hours} 小时有 {len(lines)} 条记录带账户级错误码 `{code}`"
                        f"（欠费 / key 失效这类，重试多少次都一样；同一次操作会连带写多条埋点，"
                        f"条数不等于故障次数）。"),
            "evidence": lines[:10],
            "next": "先查账户余额与 key 是否还有效；这类错误期间的产出全是降级结果，别当正常数据用。",
        })
    return findings


def evaluate_overdue(workflow_states, now=None, multiplier=2, floor_minutes=OVERDUE_FLOOR_MIN):
    """规则 E：声明了 cron 却超过「周期 × multiplier」还没跑。

    下限 floor_minutes 是给 GitHub 兜底的——它会丢 schedule 触发（本项目实测丢过 2/3），
    高频任务不设下限会天天误报。
    """
    now = now or datetime.now(timezone.utc)
    findings = []
    for state in workflow_states or []:
        gap = state.get("max_gap_minutes")
        if not gap:
            continue
        threshold = max(gap * multiplier, floor_minutes)
        last = _as_dt(state.get("last_run_at"))
        if last is None:
            # 刚加进仓库、还没到第一次触发点的 workflow 不算「该跑没跑」——否则新加一个周任务，
            # 当天就会被告一次（2026-08-27 dry-run 实测 ats-tenant-sync 正是这种情况）。
            changed = _as_dt(state.get("file_changed_at"))
            if changed and (now - changed).total_seconds() / 60.0 < threshold:
                continue
            findings.append({
                "rule": "E",
                "subject": state.get("name") or "?",
                "summary": f"`{state.get('name')}` 声明了定时（{'、'.join(state.get('crons') or [])}）但一次都没跑过。",
                "evidence": [f"声明周期最大间隔 {gap} 分钟；GitHub 上查不到任何运行记录"],
                "next": "确认 workflow 是不是被 GitHub 停用了（长期无提交会自动停调度）。",
                "silent_minutes": None,
            })
            continue
        silent = (now - last).total_seconds() / 60.0
        if silent > threshold:
            findings.append({
                "rule": "E",
                "subject": state.get("name") or "?",
                "summary": (f"`{state.get('name')}` 已经 {silent / 1440:.1f} 天没跑了，"
                            f"但它声明的是每 {gap / 60:.1f} 小时一次。"),
                "evidence": [
                    f"最后一次运行：{last.isoformat()}",
                    f"声明 cron：{'、'.join(state.get('crons') or [])}",
                    f"判据：静默 {silent:.0f} 分钟 > 阈值 {threshold:.0f} 分钟（周期 ×{multiplier}，下限 {floor_minutes}）",
                ],
                "next": "看 workflow 是被停用、cron 被注释，还是根本没有 schedule。",
                "silent_minutes": silent,
            })
    return findings


def issue_title(finding):
    """标题必须稳定：同一类同一对象永远同一个标题，才能靠「已有同标题 open issue」去重。"""
    return f"{ISSUE_PREFIX} {RULE_TITLES.get(finding['rule'], finding['rule'])}：{finding['subject']}"


def render_issue_body(finding, now=None):
    now = now or datetime.now(timezone.utc)
    lines = [
        finding["summary"],
        "",
        "**依据**",
    ]
    lines += [f"- {line}" for line in finding.get("evidence", [])]
    if finding.get("next"):
        lines += ["", "**建议先看**", f"- {finding['next']}"]
    lines += [
        "",
        f"_由 `crawler/ops_watchdog.py` 自动开出（规则 {finding['rule']}），"
        f"检查时间 {now.astimezone(timezone.utc).isoformat(timespec='seconds')}。"
        "同一问题只会开这一个 issue，后续复发会追加评论；修好后手动关掉即可。_",
    ]
    return "\n".join(lines)


# ══════════════════ IO 层（GitHub / Supabase）══════════════════

def _gh(args, attempts=4, timeout=60):
    """跑一次 gh；GitHub API 偶发 EOF（本机实测 ~50 次调用里断 2-3 次），失败退避重试。

    重试次数别再往下调：某个 workflow 的运行历史取不回来，规则 E 对它这一轮就是瞎的——
    失败会打印出来，但静默漏检正是本模块要治的病。
    """
    last = None
    for attempt in range(attempts):
        try:
            proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            last = f"超过 {timeout}s 未返回"
        else:
            if proc.returncode == 0:
                return proc.stdout
            last = (proc.stderr or proc.stdout or "").strip()[:300]
        if attempt < attempts - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"gh {' '.join(args[:2])} 失败: {last}")


def _gh_json(args, attempts=3):
    out = _gh(args, attempts=attempts)
    return json.loads(out or "null")


def detect_repo():
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if repo:
        return repo
    return (_gh_json(["repo", "view", "--json", "nameWithOwner"]) or {}).get("nameWithOwner", "")


def load_workflow_meta(root):
    """本地 .github/workflows/*.yml → {path: meta}。用本地文件而不是 API，才能读到 timeout 与注释状态。"""
    out = {}
    wf_dir = os.path.join(root, ".github", "workflows")
    for name in sorted(os.listdir(wf_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(wf_dir, name), "r", encoding="utf-8") as fh:
            out[f".github/workflows/{name}"] = dict(parse_workflow_meta(fh.read()), name=name)
    return out


def fetch_recent_runs(repo, since_date, pages=6):
    """近期运行列表。某页取不回来就用已取到的部分继续——
    半份数据能查出的问题，好过因为一次网络抖动整轮告警都不发。"""
    runs = []
    for page in range(1, pages + 1):
        try:
            data = _gh_json(
                ["api", f"repos/{repo}/actions/runs?per_page=100&created=%3E%3D{since_date}&page={page}"])
        except RuntimeError as exc:
            print(f"  [watchdog] 运行列表第 {page} 页取不回来，就按已取到的 {len(runs)} 条判：{exc}")
            break
        batch = (data or {}).get("workflow_runs") or []
        runs.extend(batch)
        if len(batch) < 100:
            break
    return runs


def fetch_jobs(repo, run_id):
    data = _gh_json(["api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"])
    return (data or {}).get("jobs") or []


def fetch_file_changed_at(repo, path):
    """文件最后一次被改动的时间。用 API 而不是本地 git log：CI 的 checkout 是 depth=1，
    本地 git 只看得到当次提交，会把老文件误判成「刚加的」→ 反而把真告警吞掉。"""
    try:
        data = _gh_json(["api", f"repos/{repo}/commits?path={path}&per_page=1"]) or []
    except RuntimeError:
        return None
    if not data:
        return None
    return (((data[0] or {}).get("commit") or {}).get("committer") or {}).get("date")


def fetch_last_runs(repo, meta_by_path, recent_runs=()):
    """每个「声明了 cron」的 workflow 取最近一次运行时间（规则 E 用）。

    先吃已经拉回来的近期 run 列表（规则 B 那一次请求的副产品），只有在列表里一次都没出现的
    workflow 才单独查一次——那才是真正可疑的少数。省掉每个 workflow 一次 API 的开销。
    """
    seen = {}
    for run in recent_runs or []:
        path, created = run.get("path") or "", run.get("created_at")
        if path and created and created > seen.get(path, ""):
            seen[path] = created
    states = []
    for path, meta in sorted(meta_by_path.items()):
        if not meta.get("max_gap_minutes"):
            continue
        last_run_at = seen.get(path)
        if not last_run_at:
            try:
                data = _gh_json(["api", f"repos/{repo}/actions/workflows/{meta['name']}/runs?per_page=1"])
            except RuntimeError as exc:
                print(f"  [watchdog] 取 {meta['name']} 运行历史失败，跳过：{exc}")
                continue
            runs = (data or {}).get("workflow_runs") or []
            last_run_at = runs[0].get("created_at") if runs else None
        states.append({
            "name": meta["name"],
            "crons": meta.get("crons"),
            "max_gap_minutes": meta.get("max_gap_minutes"),
            "last_run_at": last_run_at,
            "file_changed_at": fetch_file_changed_at(repo, path) if not last_run_at else None,
        })
    return states


def pick_job_fetch_targets(runs, meta_by_path, limit=40):
    """挑「值得掏 job 级详情」的 run：结论异常的，或时长已经贴着声明 timeout 的。

    全量掏太慢（每 run 一次 API）；这两类之外的 run 不可能藏着超时杀。
    """
    picked = []
    for run in runs or []:
        conclusion = run.get("conclusion") or ""
        meta = meta_by_path.get(run.get("path") or "", {})
        limit_min = meta.get("max_timeout") or DEFAULT_JOB_TIMEOUT_MIN
        started, done = _as_dt(run.get("run_started_at")), _as_dt(run.get("updated_at"))
        long_run = bool(
            started and done and (done - started).total_seconds() / 60.0 >= limit_min * 0.9
        )
        if conclusion in ("cancelled", "failure", "timed_out") or long_run:
            picked.append(run)
    return picked[:limit]


def find_open_issue(repo, title):
    data = _gh_json(["issue", "list", "--repo", repo, "--state", "open",
                     "--limit", "100", "--json", "number,title"]) or []
    for issue in data:
        if (issue.get("title") or "") == title:
            return issue.get("number")
    return None


def publish(repo, findings, apply=False, now=None):
    """开 issue / 追评论。dry-run 只打印，零写入。"""
    opened, commented = 0, 0
    if apply and not repo:
        print("[watchdog] 识别不到仓库，无处开 issue；本轮结果只留在日志里。")
        apply = False
    for finding in findings:
        title = issue_title(finding)
        body = render_issue_body(finding, now=now)
        if not apply:
            print(f"\n──── 会开 issue ────\n标题：{title}\n{body}")
            continue
        existing = find_open_issue(repo, title)
        if existing:
            _gh(["issue", "comment", str(existing), "--repo", repo, "--body", body])
            commented += 1
            print(f"[watchdog] 已有 open issue #{existing}，追加评论：{title}")
        else:
            out = _gh(["issue", "create", "--repo", repo, "--title", title, "--body", body])
            opened += 1
            print(f"[watchdog] 新开 issue：{title} → {out.strip().splitlines()[-1] if out.strip() else ''}")
    return opened, commented


def main():
    parser = argparse.ArgumentParser(description="后台任务真产出告警")
    parser.add_argument("--days", type=int, default=2, help="规则 A：连续几天零产出才告警")
    parser.add_argument("--stuck-hours", type=int, default=6, help="规则 C：queued 超过几小时算卡住")
    parser.add_argument("--lookback-days", type=int, default=5,
                        help="规则 B：回看几天的 workflow 运行（太短会漏掉几天才犯一次的；太长会在修好后多念叨几天）")
    parser.add_argument("--dead-source-days", type=int, default=5,
                        help="规则 F：回看几天内某源每一轮都失败才告警")
    parser.add_argument("--apply", action="store_true", help="真开 issue（默认 dry-run 只打印）")
    parser.add_argument("--repo", default="", help="owner/name，默认自动识别")
    args = parser.parse_args()

    apply = args.apply or os.environ.get("OPS_WATCHDOG_APPLY", "").strip().lower() in _TRUE
    muted = [m for m in os.environ.get("OPS_WATCHDOG_MUTE_MODULES", "").split(",") if m.strip()]
    now = datetime.now(timezone.utc)
    today = now.astimezone(SHANGHAI).date().isoformat()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    import db  # 延迟导入：单测不需要 supabase 依赖

    sb = db.get_supabase()
    started_at = now
    since_day = (now - timedelta(days=max(args.days + 2, 4))).astimezone(SHANGHAI).date().isoformat()
    ops_rows = db.fetch_all_rows(
        lambda: sb.table("ops_runs").select("module,run_date,status,metrics")
                  .gte("run_date", since_day)
    )
    discovery_rows = db.fetch_all_rows(
        lambda: sb.table("discovery_runs").select("id,mode,status,created_at,query,company")
                  .eq("status", "queued")
    )
    event_rows = db.fetch_all_rows(
        lambda: sb.table("events").select("id,event,payload,created_at")
                  .gte("created_at", (now - timedelta(hours=48)).isoformat())
    )

    findings = []
    zero, skipped = evaluate_zero_output(ops_rows, today, days=args.days, muted=muted)
    findings += zero
    findings += evaluate_stuck_ledger(discovery_rows, now=now, hours=args.stuck_hours)
    findings += evaluate_account_errors(event_rows, ops_rows, now=now)
    # 规则 F 单独包住：crawl_runs 是最大的一张表（1,400 源 × 4 轮/天），取不到不能拖垮 A/C/D。
    try:
        dead_since = (now - timedelta(days=args.dead_source_days)).isoformat()
        crawl_rows = db.fetch_all_rows(
            lambda: sb.table("crawl_runs")
                      .select("source_id,status,error_message,started_at,"
                              "reported_total,coverage_complete,jobs_found")
                      .gte("started_at", dead_since)
        )
        source_rows = db.fetch_all_rows(
            lambda: sb.table("sources").select("id,adapter_name,company,source_url,enabled")
                      .eq("enabled", True)
        )
        sources_by_id = {r["id"]: r for r in source_rows}
        findings += evaluate_dead_sources(crawl_rows, sources_by_id,
                                          days=args.dead_source_days)
        # 规则 G 复用同一批 crawl_rows / sources（多取三列，不多打一次库）。
        findings += evaluate_coverage_shortfall(crawl_rows, sources_by_id)
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::[watchdog] 规则 F/G（源连续失败 / 抓不全）本轮没查成："
              f"{type(exc).__name__}: {exc}")

    meta_by_path = load_workflow_meta(root)
    repo = args.repo or detect_repo()
    if repo:
        # GitHub 侧整块包住：网络抖一下不能把已经算好的台账告警（A/C/D）一起带走——
        # 一个告警系统因为自己挂了而什么都不说，正是本模块要治的病。
        try:
            since_date = (now - timedelta(days=args.lookback_days)).date().isoformat()
            runs = fetch_recent_runs(repo, since_date)
            targets = pick_job_fetch_targets(runs, meta_by_path)
            print(f"[watchdog] 近 {args.lookback_days} 天 {len(runs)} 次运行，"
                  f"其中 {len(targets)} 次需要掏 job 级详情")
            jobs_by_run = {}
            for run in targets:
                try:
                    jobs_by_run[run["id"]] = fetch_jobs(repo, run["id"])
                except RuntimeError as exc:
                    print(f"  [watchdog] 取 run {run.get('id')} 的 job 详情失败，跳过：{exc}")
            findings += evaluate_timeout_kills(targets, jobs_by_run, meta_by_path)
            findings += evaluate_overdue(fetch_last_runs(repo, meta_by_path, runs), now=now)
        except Exception as exc:  # noqa: BLE001 - GitHub 侧失败只降级，不吞掉台账侧告警
            print(f"::warning::[watchdog] workflow 侧规则（B/E）本轮没查成：{type(exc).__name__}: {exc}")
    else:
        print("[watchdog] 识别不到仓库，跳过 workflow 侧规则（B/E）。")

    print(f"\n[watchdog] {today} 检查完成：{len(findings)} 条告警"
          f"（ops_runs {len(ops_rows)} 行 / queued {len(discovery_rows)} 行 / events {len(event_rows)} 行）"
          f"{'　※ dry-run，不开 issue' if not apply else ''}")
    for finding in findings:
        print(f"  · [{finding['rule']}] {issue_title(finding)}")
    if skipped:
        print(f"[watchdog] 这些模块在写台账但没声明产出口径（规则 A 跳过，别忘了补）：{', '.join(skipped)}")

    opened, commented = publish(repo, findings, apply=apply, now=now)
    if apply:
        import ops_runs
        ops_runs.record_ops_run(
            sb,
            "ops_watchdog",
            {"findings": len(findings), "issues_opened": opened, "comments": commented,
             "by_rule": dict(Counter(f["rule"] for f in findings))},
            status="success",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
