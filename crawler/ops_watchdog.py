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
import statistics
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
    # H / I 早就在用了，标题一直没登记 —— issue 标题会退化成「[watchdog] H：…」，顺手补上。
    "H": "多个源指向同一门户",
    "I": "抓取没收尾",
    "J": "投递入口该复查了",
    "K": "adapter 产出骤降",
    "L": "源断抓",
    "M": "Mac 公告抓取无记录",
    "N": "抓取台账终态未回写",
    "O": "必投公司校招渠道没接",
    # P 同 H/I：早就在用了，标题一直没登记（2026-09-19 桥接 audit_results 时顺手补上，
    # 不改判定逻辑，只补一个人话标签）。
    "P": "洞察供给停摆",
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
    # 用户体验走查（scripts/ux-walkthrough）：有用户画像可走却一个都没走完 = 零产出。
    "ux_walkthrough": (("users",), ("users",)),
    "campus_official_backlog": (("verified", "draft"), ("companies_processed",)),
    "campus_cycle_backlog": (("verified", "draft"), ("companies_processed",)),
    "campus_lane": (("snapshots",), ("sources",)),
    "bu_extract": (("kept",), ("companies_scanned",)),
    # 有主体可算却一条指标都没产出 = 洞察库页面会空着，属零产出。
    "bu_signals": (("items_written",), ("subjects_scanned",)),
    # 有待判档的条目却一条都没判出来 = 档位筛选会一直空着，属零产出。
    # attempts_exhausted 也算产出：判不出档的条目走到「搁置」同样是队列在前进。
    # 只有「既没判出档、也没有一条走到终态」才是真卡住（2026-09-09~17 空转 9 天正是这一态）。
    "insight_grade_extract": (("graded", "attempts_exhausted"), ("scanned",)),
    # run.py 每轮抓取收尾写的台账（2026-09-03）：有源可抓却一个岗都没拿到 = 零产出。
    "daily_crawl": (("jobs_found_total",), ("sources_total",)),
    # 校招板块批量补源两层（2026-09-18 补台账）：层1 有候选可分诊却一个都没建源、
    # 层2 有待验收候选却一个都没通过验收 = 零产出。
    "campus_board_probe": (("sources_added",), ("candidates_checked",)),
    "campus_board_verify": (("enabled",), ("pending",)),
    # 北森详情路由浏览器逐家探测（2026-09-18 补台账）：有待探租户却一个都没探到路由 = 零产出。
    "harvest_beisen_routes": (("harvested",), ("attempted",)),
    # 企业 logo 抓取（2026-09-18 补台账）：有待处理公司却一张图都没抓到 = 零产出。
    "company_logos": (("found",), ("processed",)),
    # 公告制招聘官方抓取（已有台账，此前不在 MODULE_OUTPUT，2026-09-18 补登记）：
    # 有候选可看却一条新公告都没进库 = 零产出。
    "announcement_harvest": (("total_new",), ("total_found",)),
    "announcement_iguopin": (("kept",), ("fetched",)),
    # 公开讨论「说法」层治理（2026-09-19 补登记，audit_coverage 差集揪出来的）：有活扫却一条
    # 都没治理（重路由/退休/去重/补数值全零）= 治理停了。⚠️ 结构性缺口：本仓库目前没有任何
    # workflow 调用 insight_topic_sweep.py（读 .github/workflows/*.yml 逐个确认过），登记进
    # MODULE_OUTPUT 只是让「模块名有没有声明产出口径」这条差集不再报它，不代表它已经接了线——
    # 接线是单独的活，不在本次任务范围内，如实记在这里别装作已经解决。
    "insight_topic_sweep": (("retired", "reroute", "dedupe", "metric_values"), ("scanned",)),
    # LLM 真实 token 用量记账（insight_engine.record_usage_ops_run）：它只在本进程真的调过
    # LLM 时才写这一行（calls=0 直接不写，见函数内 `if not totals["calls"]: return False`），
    # 所以「写了却是零产出」这件事结构上不可能发生——produced/work 用同一个键只是让它能通过
    # 规则 A 的口径校验，不代表这个键真的会被规则 A 判定异常。
    "llm_usage": (("calls",), ("calls",)),
}

# ⚠️ 周任务在当前规则 A 下几乎不可能被判定为「连续零产出」（2026-09-18 发现，未修，先如实记录）：
# evaluate_zero_output 要求 complete_days(today, days) 窗口内**每一天**都是 module_day_state=="zero"，
# 而每周只跑一次的模块在其余 6 天里 day_bucket 为空 → module_day_state 返回 "no_run"，"no_run" != "zero"，
# `all(state == "zero")` 恒为假 → 规则 A 对这些模块形同虚设（即使连续断更数月也不会触发）。
# audit_hotjob_attribution / ats_tenant_sync / company_logos 三个都是每周一次的任务（cron 分别是
# 周一 22:17 / 周一 05:30 / 周一 04:00）——**台账现在都写了，但规则 A 目前对它们暂时没有真正生效的
# 零产出告警**：前两个是因为它们本身就登记在 NO_OUTPUT_MODULES 里（零产出是好消息，见上面理由），
# company_logos 虽然登记进了 MODULE_OUTPUT（它确有「产出可能归零」的语义，万一真的抓不到图），
# 但一样撞上这个结构性缺口，规则 A 实际上盯不住它。三个都需要下一波再处理（不在本次任务范围）。
# 最小改法（未做，需要额外设计/测试）：window 大小按模块声明的 cron 周期算
# （复用已有的 cron_max_gap_minutes），而不是写死 `days=2` 天；或者把「no_run」在窗口末尾折叠成
# 「按声明周期换算的一个周期」再判零产出，两种做法都会改变 evaluate_zero_output 的调用契约，
# 需要人工确认后再动，先如实记录在这里、不擅自改规则逻辑。

# 规则 F：一个源在回看窗口内「每一轮都失败」才告警。
# 2026-09-03 实测：11 个源一周 28 轮全挂（Workday 站点名错 / 板块改名 / 反爬 403 / 浏览器没装），
# 每轮各自被吞成 crawl_runs 一行 failed，模块级绿灯完全看不见——只有源级视角才抓得到。
DEAD_SOURCE_MIN_RUNS = 8   # 少于这个次数不判（新源、低频源不冤枉）

# 「0 就是正常」的模块：产出为 0 表示没东西可做，不是坏了 → 明确排除在规则 A 之外，
# 也不用在日志里提醒「补口径」。
#   insight_staleness：retired=0 = 当天没有过期洞察
#   purge_expired：deleted=0 = 当天没有确认撤下的死岗
#   ops_watchdog：本模块自己的台账
#   search_quota_probe：它的产出就是「有没有越线」，critical=0 是好事不是零产出
#   backfill_job_function / backfill_recruitment_category：written=0 是常态——触发器只在
#     title/summary 真的变了时才把结论置 NULL，回填稳定后大多数轮次本来就没有需要纠正的行；
#     --check 模式更是设计上从不写库。真正的异常（连不上库、SQL 报错）会让进程整体失败，
#     那条路走的是「运行失败」不是「零产出」。
#   db_report：只读审计报告，没有队列/产出这对语义——它本身就是给别的模块判断依据的数字来源。
#   production_smoke：冒烟测试，ok=true 就是好结果，不是「零产出」。
#   audit_hotjob_attribution：mismatch=0（没查到张冠李戴）是好消息，不是零产出；它是每周一次
#     的存量核对，真正的接口失败已经单独计进 unknown，走的是别的判据。
#   ats_tenant_sync：new_tenants=0 是常态（上游 ATS 租户名单增长很慢，经常一整周都没有新增），
#     而它的「处理量」口径（files=3）恒大于 0，硬塞进规则 A 只会制造天天误报。
#   announcement_verify：expired/dead=0（当天没有该下架的公告）是好消息，不是零产出。
NO_OUTPUT_MODULES = ("insight_staleness", "purge_expired", "ops_watchdog",
                     "search_quota_probe", "backfill_job_function",
                     "backfill_recruitment_category", "db_report", "production_smoke",
                     "audit_hotjob_attribution", "ats_tenant_sync", "announcement_verify")

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


# 规则 I：跑了这么久还没回写终态就当它崩了。必须显著大于一轮抓取耗时，否则会把在跑的源误报。
UNFINISHED_CRAWL_HOURS = 6


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


def evaluate_unfinished_crawls(crawl_rows, sources_by_id, now=None,
                               hours=UNFINISHED_CRAWL_HOURS):
    """规则 I：抓取跑到一半死了 —— crawl_runs 有 started_at 却永远等不到 finished_at。

    为什么必须自动报：`db.create_crawl_run` 先插一行占位、跑完才 update 成终态。进程被
    CI 超时/取消、OOM、kill 掉时，这一行就**再没人回写**。历史上占位符是 'skipped'
    （迁移 234 改成 'running'），于是「跑崩了」和「按设计跳过」在 status 上完全同形，
    而规则 F 只认 status='failed' → 一次 CI 超时吞掉一批源，台账上一点异常都看不见。

    📌 成因**不止 CI 被杀**，两种都实测到过（2026-09-05 逐条核过 GitHub run）：
      · 2026-09-04 19:30 那 3 条 → daily-job-crawl run 33909832797 conclusion=failure、
        crawler 步骤被中断，确实是被杀，规则 B 也看得见；
      · 2026-09-04 09:57~10:46 那 7 条（全 workday）→ enrichment-crawl run 33858818203
        **六个分片全 success、guard 也 success**。CI 全绿照样丢源 —— 所以看到本告警不要
        直奔 workflow 超时，先确认那次 run 到底红没红。
    ⚠️ **迁移 234 注释里举的「09-05 05:06 十个源集体留空」那个例子是错的**：那 10 条
    （华为 / 字节跳动 / 伊利 / 顺丰…）1~3 分钟后全部 success 收尾了，它们只是当时正在飞。
    快照里的空记录不等于崩溃 —— 这正是下面 hours 宽限期存在的理由，别把它调小。

    ⚠️ 判据是 **finished_at 为空**，刻意**不看 status**：status 正是那个已经被证明会骗人的字段，
    而且新旧两种占位符（旧 'skipped' / 新 'running'）都得认得出，只认一种等于修了个寂寞。

    ⚠️ hours 要显著大于一轮抓取的正常耗时，否则**正在跑的源**会被当成崩溃
    （daily-crawl 每 6h 一轮，浏览器源单个 2–5min）。默认 6h：跑了 6 小时还没回写的，
    那一轮早就结束了。

    输出**一条聚合 finding**：这类故障天然成簇（一次超时带走一批），每源一条会把告警刷屏。
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    stuck = []
    for row in crawl_rows or []:
        if (row or {}).get("finished_at"):
            continue
        started = _as_dt(row.get("started_at"))
        if not started or started > cutoff:
            continue
        source = sources_by_id.get(row.get("source_id"))
        if not source or not source.get("enabled", True):
            continue
        stuck.append((started, source))
    if not stuck:
        return []
    stuck.sort(key=lambda item: item[0])
    by_adapter = Counter(str(src.get("adapter_name") or "?") for _, src in stuck)
    # 同一分钟内集体留空 = 整批被掐（CI 超时/取消），比零散崩溃更值得先看。
    by_minute = Counter(started.strftime("%Y-%m-%d %H:%M") for started, _ in stuck)
    worst_minute, worst_n = by_minute.most_common(1)[0]
    return [{
        "rule": "I",
        "subject": "crawl_runs 未收尾",
        "summary": (f"`crawl_runs` 有 {len(stuck)} 条跑了超过 {hours} 小时还没回写终态，"
                    f"= 这些源的抓取半途死了（不是被跳过）。"),
        "evidence": [
            f"按 adapter 分：{dict(by_adapter)}",
            f"最密集的一分钟：{worst_minute} 有 {worst_n} 条同时留空"
            + ("（像一次 CI 超时/取消带走一整批）" if worst_n >= 3 else ""),
        ] + [
            f"{started.isoformat()} {src.get('adapter_name') or '?'} / {src.get('company') or '?'}"
            for started, src in stuck[:10]
        ],
        "next": "去对应 workflow run 看是不是超时/被取消：是就调该档的超时或分片；"
                "不是就查 adapter 有没有卡死在某个请求上。别让它继续每轮静默丢源。",
    }]


# 规则 K 的阈值是拿 2026-08-12~09-13 共 188,765 行 crawl_runs 回测定的
# （模拟 watchdog 在 08-21~09-13 每天 UTC 01:00 各跑一次，共 24 次），改之前先重跑回测，别凭感觉调。
COLLAPSE_BASELINE_DAYS = 7          # 基线 = 最近窗之前的 7 个 24h 窗
COLLAPSE_MIN_BASELINE_WINDOWS = 3   # 源在基线里至少有 3 个窗跑完过才进对照组（新源、低频源不冤枉）
COLLAPSE_MAX_RATIO = 0.3            # 只剩基线的 30% 以下……
COLLAPSE_MIN_DROP = 300             # ……且绝对少了 ≥300 个岗，两个条件缺一不可
COLLAPSE_DURATION_JUMP = 3.0        # 单轮耗时中位数 ×3：只写进依据，不单独告警


def rows_started_since(rows, cutoff):
    """按 started_at 截取回看窗。解析不出时间的行**保留**——与服务端 gte 过滤的旧行为一致，
    免得规则 F/G/I 因为共用了更长的一次取数而悄悄少看几行。"""
    return [r for r in rows or [] if (_as_dt((r or {}).get("started_at")) or cutoff) >= cutoff]


def evaluate_adapter_collapse(crawl_rows, sources_by_id, now=None, recent_days=1,
                              baseline_days=COLLAPSE_BASELINE_DAYS,
                              max_ratio=COLLAPSE_MAX_RATIO, min_drop=COLLAPSE_MIN_DROP,
                              min_baseline_windows=COLLAPSE_MIN_BASELINE_WINDOWS, muted=()):
    """规则 K：某个 adapter 的抓取产出整体塌了，而 status 照样 success。

    为什么必须有它（2026-09-13）：moka（410 源）09-07~09 每天 jobs_found 合计 38,006 / 31,493 / 36,163，
    09-10 起 535 / 642 / 490，几乎每一轮都记 success，单轮耗时中位数 22s → 141s——前端新加的 sentry 主机
    从 runner 连不上，networkidle 永远等不到，超时被 except 吞成 0 岗（修于 f0d900a）。三天零告警：
    规则 A 只看整个模块连续两天为 0，规则 F 只认 status='failed'。

    判据：以 now 为终点切 24h 窗。每个源每窗取**最好的一轮** jobs_found；源的基线 = 它在前 baseline_days
    个窗里的中位数。按 adapter 只加总「最近窗跑完过、且有基线」的那批源（同一批源自己跟自己比），
    最近 ≤ 基线 × max_ratio **且** 少了 ≥ min_drop 才报；recent_days>1 时每个最近窗都要成立。

    ⚠️ 不能直接比「adapter 每天的 jobs_found 合计」（同一份回测实测，别改回去）：朴素日合计 24 次开出
      55 条告警，只有 moka 那 3 条是 adapter 真塌了——08-27 夜档整个没跑，08-28 一天就误报 26 个 adapter
      （bytedance 62,623 vs 276,509）。成因三种：一天跑好几轮的源丢一轮，合计就少一截；夜档漂过日界，
      一天 0 轮、次日 2 轮；手动重跑让合计翻倍。「每源每窗取最好一轮 + 只比同一批源」对三种都免疫：
      没跑的源不进对照组，重跑取 max 不会翻倍。所以窗口用「以 now 为终点的 24h」还是自然日都无所谓。
      同一份数据本判据共报 5 条：moka 3 条（真）；iguopin 08-28 1 条（夜档没跑，只剩白天那几轮本来就是 0 岗，
      当天产出确实归零，只是病根在调度不在 adapter）；microsoft 09-12 1 条（单源一天 700→114、次日自愈，算噪音）。

    ⚠️ 刻意不设「至少 N 个源」门槛：bytedance / bytedance_campus / apple / ccb 都是单源 adapter、每天几千到
      上万岗。设 ≥3 源的门槛，74 个 adapter 只剩 14 个看得见（占总产出 72.9%）；现行阈值看得见 46 个（98.7%）。
      0↔15 那种小 adapter 靠 min_drop 挡。

    ⚠️ 已知盲区，别当它全能：
      · 源一窗里只要有一轮是好的就不报——只塌部分轮次时岗位当天仍刷新过，产品影响小；
      · adapter 整窗一轮都没跑完不归本规则（kuaishou 09-10/11 两天 0 行）——那是「没跑」，不是「跑了没产出」；
      · 基线是中位数：连塌满 4 天后基线自己也塌了，**本规则就不再复报**。issue 不会自动关，但别指望它天天提醒。

    耗时暴涨只写进依据、不单独开 issue：回测按「中位数 ×3 且多 60s」单独报会开 7 条，4 条是 sf_express 在
    09-04 改了翻页重试后的正常变慢（406s vs 88s，产出没掉）。
    """
    now = now or datetime.now(timezone.utc)
    horizon = recent_days + baseline_days
    muted = {str(m).strip() for m in (muted or []) if str(m).strip()}
    best = {}                          # (source_id, 窗号) -> 该源该窗最好的一轮 jobs_found
    adapter_of = {}
    durations = defaultdict(list)      # (adapter, 窗号) -> 每轮耗时（秒）
    statuses = defaultdict(Counter)    # (adapter, 最近窗号) -> status 分布
    for row in crawl_rows or []:
        started = _as_dt((row or {}).get("started_at"))
        finished = _as_dt(row.get("finished_at"))
        if not started or not finished:
            continue   # 没收尾的行 jobs_found 还是默认 0，算进来就是假骤降；它们归规则 I 管
        source = sources_by_id.get(row.get("source_id"))
        if not source or not source.get("enabled", True):
            continue
        adapter = str(source.get("adapter_name") or "")
        if not adapter or adapter in muted:
            continue
        age = (now - started).total_seconds()
        if age < 0 or age >= horizon * 86400:
            continue
        window = int(age // 86400)     # 0 = 离 now 最近的 24h
        sid = row.get("source_id")
        adapter_of[sid] = adapter
        best[(sid, window)] = max(best.get((sid, window), 0), _num(row.get("jobs_found")))
        durations[(adapter, window)].append(max((finished - started).total_seconds(), 0.0))
        if window < recent_days:
            statuses[(adapter, window)][str(row.get("status") or "?")] += 1

    panels = defaultdict(lambda: defaultdict(list))   # adapter -> 最近窗号 -> [(sid, 最近, 基线)]
    for sid, adapter in adapter_of.items():
        history = [best[(sid, w)] for w in range(recent_days, horizon) if (sid, w) in best]
        if len(history) < min_baseline_windows:
            continue
        baseline = statistics.median(history)
        for window in range(recent_days):
            if (sid, window) in best:
                panels[adapter][window].append((sid, best[(sid, window)], baseline))

    findings = []
    for adapter in sorted(panels):
        collapsed = []
        for window in range(recent_days):
            members = panels[adapter].get(window) or []
            recent = sum(m[1] for m in members)
            base = sum(m[2] for m in members)
            if not members or base <= 0 or recent > base * max_ratio or base - recent < min_drop:
                break
            collapsed.append((window, members, recent, base))
        if len(collapsed) < recent_days:
            continue

        evidence = []
        for window, members, recent, base in collapsed:
            dropped = sum(1 for _, r, b in members if b > 0 and r <= b * 0.5)
            span = (f"{(now - timedelta(days=window + 1)):%m-%d %H:%M}~"
                    f"{(now - timedelta(days=window)):%m-%d %H:%M} UTC")
            status_mix = statuses[(adapter, window)]
            evidence.append(
                f"{span}：{len(members)} 个源各取当窗最好的一轮，合计 jobs_found={recent:.0f}；"
                f"同一批源前 {baseline_days} 天的中位数合计 {base:.0f}（只剩 {recent / base:.1%}，"
                f"其中 {dropped} 个源自身掉到一半以下）")
            evidence.append(
                f"{span} 的 status 分布：{dict(status_mix)}"
                + ("——全是成功，异常多半在 adapter 里被吞成了空列表"
                   if set(status_mix) <= {"success", "partial_success"} else ""))

        recent_durations = durations.get((adapter, 0)) or []
        baseline_medians = [statistics.median(durations[(adapter, w)])
                            for w in range(recent_days, horizon) if durations.get((adapter, w))]
        if recent_durations and baseline_medians:
            recent_med = statistics.median(recent_durations)
            base_med = statistics.median(baseline_medians)
            line = f"单轮耗时中位数 {recent_med:.0f}s，前 {baseline_days} 天是 {base_med:.0f}s"
            if base_med > 0 and recent_med >= base_med * COLLAPSE_DURATION_JUMP:
                line += (f"（×{recent_med / base_med:.1f}：产出掉了耗时反而暴涨，"
                         "像是在等一个永远等不到的东西，超时后被当成 0 岗）")
            evidence.append(line)

        _, members, recent, base = collapsed[0]
        worst = sorted(members, key=lambda m: m[1] - m[2])[:5]
        evidence.append("掉得最多的源：" + "；".join(
            f"{(sources_by_id.get(sid) or {}).get('company') or sid} {b:.0f}→{r:.0f}"
            for sid, r, b in worst))
        findings.append({
            "rule": "K",
            "subject": adapter,
            "summary": (f"adapter `{adapter}` 最近 {recent_days * 24} 小时的抓取产出只剩基线的 "
                        f"{recent / base:.1%}（{recent:.0f} vs {base:.0f}），而这些源都还在照常跑。"),
            "evidence": evidence,
            "next": ("先看这个 adapter 最近一轮的抓取日志：status 全 success 却只剩零头 = 异常被吞成了空列表"
                     "（09-10 moka 就是等 networkidle 等到超时）；再真渲染打开一两个掉得最多的源，"
                     "确认官网是不是真撤了岗。修好后回读 crawl_runs，确认 jobs_found 回到基线。"),
        })
    return findings


# 规则 L 的阈值是拿 2026-08-08~09-13 共 211,833 行 crawl_runs 回测定的（模拟 watchdog 在 08-22~09-13
# 每天 UTC 05:40 各跑一次——cron 写的 01:00，GitHub 实际推迟到 05:25~05:43 才开跑），改之前先重跑回测，别凭感觉调。
SILENT_SOURCE_HOURS = 42      # 同一个源相邻两次被抓：夜档全部正常时最长 32.2h（08-27 夜档被推迟 8 小时那次），
                              # 中间夜档有分片被杀时最短 42h —— 两堆之间没有样本，阈值放在空档的上沿
SILENT_BASELINE_DAYS = 7      # 「本来每天都抓」= 断抓之前的 7 个 24h 窗里……
SILENT_MIN_DAYS = 5           # ……至少 5 个窗有行（新源、低频源不冤枉）
SILENT_LOOKBACK_DAYS = 10     # 取数回看。回测里 10 天与 14 天报的完全一样；代价是断抓满 6 天后基线落到窗外、掉出视野


def evaluate_silent_sources(crawl_rows, sources_by_id, now=None, hours=SILENT_SOURCE_HOURS,
                            baseline_days=SILENT_BASELINE_DAYS, min_days=SILENT_MIN_DAYS,
                            muted=()):
    """规则 L：本来每天都被抓的 enabled 源，连一行 crawl_runs 都没有了 —— 不是抓失败，是根本没轮到它。

    为什么必须有它（2026-09-13）：快手 09-09 21:18 之后到 09-12 22:15 一行都没有，京东校招 / 华虹 / 华安基金
    同病。成因是 enrich-crawl 的 enrich (2) 分片 09-08、09-10、09-11、09-12 四晚撞 180 分钟被杀，串行浏览器档
    排在队尾的源一个都没轮到（09-10/11/12 三晚那一片的日志都只列到 146 个源，别的片 226~228 个；09-12 该报的
    27 个源在 09-10、09-11 六个分片的日志里一次都没出现）。快手 09-12 能回来，是 09-11 新加的源让装箱重排、
    把它挪去了另一片——换了另一批源进队尾接着饿。
    规则 B 的「enrich-crawl 被杀」issue 从 08-29 起已追评 13 次，但说不出**哪些源、连续几天**没被抓；
    F 只认 failed 行、I 只认没收尾的行、K 刻意不管整窗没跑的 adapter —— 没有行，谁都看不见。
    同一类还有：`create_crawl_run` 本身写库失败（09-12 两个 moka 源 Supabase 504，日志里 FAILED、库里无行，
    `crawl_run_unrecorded` 也不计它），以及 db.get_sources 注释里实测过的「不分页时尾部 79 个源每天不会被抓」
    —— 这些时候 workflow 全绿。

    判据：源最后一行（任意 status，没收尾的也算——有行就说明轮到过）距 now ≥ hours，且在它最后一行
    所在的 24h 窗往前共 baseline_days 个窗里至少 min_days 个窗有行。

    回测（23 次模拟运行）两个方向都数了：报了 5 天、36 个源次，每一个的断档里都有一晚夜档分片被杀，
    **没有一条报在非故障上**；断档里夜档缺了 ≥2 晚的 31 个全部报到；只缺一晚的 166 个一个不报（设计如此）。
    ⚠️ 基线必须锚在「断抓之前」，不能锚在 now（同一份回测，别改回去）：按「now 之前 7 天里 ≥5 天有行」判，
      夜夜被饿死的源正好因为缺的天数多而**掉出**资格——09-13 华虹 / 华安基金已断抓 3 天多，那种写法不报，
      最该报的时候反而闭嘴。
    ⚠️ hours 别调到 36 以下：32.2h 的正常间隔是 GitHub 把夜档推迟 8 小时造成的，推迟再多几小时就是误报。
      也别为了「只缺一晚的」调到 24h：按 01:00 跑会在 08-28 把 390 个源报成断抓（夜档被推迟到 01:59 才开跑），
      按 05:40 跑能躲过去全靠 watchdog 自己也被推迟，别押这个运气；而且那 9 天 233 个源次全是规则 B 已经在报的
      「分片被杀一晚」。36 / 42 / 48 在这份回测里报的完全一样，选 42 是为了离正常间隔的上限远一点。
    ⚠️ 已知盲区：窗内一行都没有的源不判（新加的、停用后刚重新启用的，都没有「本来每天抓」的依据）；
      断抓满 6 天基线落到取数窗外会掉出视野（issue 不会自动关，但不再追评）；
      源停用几天后重新启用、正好卡在夜档之前被 watchdog 看到，会误报一次（sources 表没有启用时间，判不出）。

    输出**一条聚合 finding**：这类故障天然成簇（一个分片被杀就是一串源），每源一条会刷屏。
    """
    now = now or datetime.now(timezone.utc)
    muted = {str(m).strip() for m in (muted or []) if str(m).strip()}
    last_seen = {}
    windows = defaultdict(set)         # source_id -> 有行的窗号（0 = 离 now 最近的 24h）
    for row in crawl_rows or []:
        sid = (row or {}).get("source_id")
        started = _as_dt(row.get("started_at")) if sid else None
        if not started:
            continue
        if sid not in last_seen or started > last_seen[sid]:
            last_seen[sid] = started
        if started <= now:
            windows[sid].add(int((now - started).total_seconds() // 86400))

    silent = []
    for sid, last in last_seen.items():
        source = sources_by_id.get(sid)
        if not source or not source.get("enabled", True):
            continue
        if str(source.get("adapter_name") or "") in muted:
            continue
        gap_hours = (now - last).total_seconds() / 3600
        if gap_hours < hours:
            continue                   # 也挡住了「晚于 now」的行：库端时钟比 runner 快 = 刚被抓过
        first = int((now - last).total_seconds() // 86400)
        present = sum(1 for w in range(first, first + baseline_days) if w in windows[sid])
        if present < min_days:
            continue
        silent.append((gap_hours, last, source, present))
    if not silent:
        return []

    silent.sort(key=lambda item: (-item[0], str(item[2].get("company") or "")))
    by_adapter = Counter(str(src.get("adapter_name") or "?") for _, _, src, _ in silent)
    by_last_day = Counter(f"{last:%m-%d}" for _, last, _, _ in silent)
    worst_day, worst_n = by_last_day.most_common(1)[0]
    return [{
        "rule": "L",
        "subject": "每天都抓的源没被轮到",
        "summary": (f"{len(silent)} 个本来每天都被抓的 enabled 源，已经 {hours} 小时以上一行 `crawl_runs` 都没有"
                    f"（最久 {silent[0][0]:.0f} 小时）= 它们根本没被轮到，不是抓失败——失败也会留一行。"),
        "evidence": [
            f"按 adapter 分：{dict(by_adapter.most_common())}",
            f"最后一次被抓的日期（UTC）：{dict(sorted(by_last_day.items()))}"
            + (f"——{worst_n} 个停在同一天，像同一轮里排在后面的一截没轮到" if worst_n >= 3 else ""),
        ] + [
            f"{src.get('adapter_name') or '?'} / {src.get('company') or '?'}：最后一次 {last:%m-%d %H:%M} UTC，"
            f"已 {gap:.0f} 小时；断抓前 {baseline_days} 天里 {present} 天抓到过"
            for gap, last, src, present in silent[:15]
        ],
        "next": ("先看最后一次抓到它们之后那几晚的 enrich-crawl：某个分片撞 180 分钟被杀时，串行浏览器档排在队尾的源"
                 "一个都轮不到，而且夜夜是同一批——要拆片 / 减负，别等它自愈（规则 B 的 issue 只说被杀，不说饿死了谁）。"
                 "分片都正常跑完却还是没行：查源有没有被选中（取源分页、分片装箱、分档），"
                 "或 run 日志里有没有 `FAILED: APIError` 却没留行（create_crawl_run 本身写库失败）。"),
    }]


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


# 规则 H：同一个 ATS 门户被登记成多个 enabled 源（公司自有域名 + 厂商域名）。
# portal 身份 = 「租户 slug / portal id」，与域名无关。
# **只登记已经 live 核验过「同身份 = 同一批岗」的平台** —— 判据不是 URL 长得像，
# 而是两边岗位 id/uuid 真的重合（2026-09-04 逐组查过重合率）。
#
# 🚫 **beisen / feishu 刻意不在这里，别手痒加**：它们的板块段在路径里
# （`{t}.zhiye.com/social` vs `/campus`、`{t}.jobs.feishu.cn/index/position` vs `/campus/position`），
# 只按租户名归一会把 72 组**合法的板块对**判成影子，一清就是删在招岗。
# 实测佐证：汇顶 goodix 的 social(64 岗) 与 campus(35 岗) **交集为 0**；飞书的 website-path
# 决定的同样是互不相同的池子（CLAUDE.md 立过碑：index 甚至比不带头更小）。
# 真要加它们，必须让**板块段参与身份**，且先做重合率抽样。
_PORTAL_KEYS = (
    # Moka：{host}/{apply|campus_apply|campus-recruitment|social-recruitment}/{tenant}/{portalId}
    # 身份 = tenant/portalId：portalId 自己就区分校招/社招门户（吉利 78436 校招 vs 96123 社招），
    # 所以路径段**不**参与身份——同一个 portalId 的两种 URL 写法才是真重复。
    # live 实测 10 组 /apply/ vs /social-recruitment/ 确实是同一批岗（特斯拉 1,043 个 uuid 两边都有、
    # 滴滴 832、李宁 326、锐捷 280…），合计约 2,589 行影子。
    re.compile(r"/(?:apply|campus_apply|campus-recruitment|social-recruitment)/([^/?#]+/\d+)", re.I),
    # Workday：{host}/wday/cxs/{tenant}/{site}/jobs，身份 = tenant/site（portal_identity 统一转小写）。
    # 大小写必须归一：它会一路带进 jd_url（/en-US/ShellCareers/job/… vs /en-US/shellcareers/job/…），
    # 而 canonical_jd_url **区分大小写** ⇒ active 唯一索引拦不住 ⇒ 同一个岗安静地存两行。
    # live 实测 Visa：visa/Visa 833 个在招、visa/visa 703 个，其中 703 个两边都有。
    re.compile(r"/wday/cxs/([^/]+/[^/?#]+)", re.I),
    # wt（老版 WinTalent）：身份 = brand code（portal_identity 统一转小写）。
    # 同一个 brand 有两种等价入口，库里两种都在用：
    #   自有子域 `gwm.hotjob.cn/wt/GWM/web/index` ／ 共享 host `www.hotjob.cn/wt/GWM/web/index`
    # live 实测两边 postId **120/120 完全重合**（两边自报 total 都是 2808）＝同一租户同一批岗。
    # brand 大小写不统一（BASF / CT / cifi / feihe / GALAXYCORE 都有），故必须转小写才归得到一起。
    # ⚠️ 当前全库 39 个 wt 源、39 个不同 brand，**0 组重复** —— 这条是**防患**不是清存量。
    # 安全性：brand 后面只有 `/web/index` 一种路径（38/39），**没有校招/社招板块段**，
    # 所以拿 brand 单独当身份不会重蹈 beisen/feishu 那种「板块对被判成影子」的覆辙。
    re.compile(r"/wt/([^/?#]+)", re.I),
)


def portal_identity(source_url: str):
    """从 source_url 抽「与域名无关的门户身份」；抽不出返回 None（不参与本规则）。"""
    for pattern in _PORTAL_KEYS:
        m = pattern.search(source_url or "")
        if m:
            return m.group(1).lower()
    return None


def evaluate_duplicate_portals(sources_by_id):
    """规则 H：同一个门户挂了多个 enabled 源 → 同一个岗在库里存多行，用户看到重复卡片。

    为什么必须自动报：这类重复**不会有任何失败信号**——两个源都 status=success、都抓得好好的，
    只是抓的是同一批岗。2026-09-04 人肉比对 uuid 才发现三处：吉利 campus.geely.com 与
    app.mokahr.com 是同一个 portal(geely/78436)，首页 30 个岗位 uuid 30/30 相同、总页数都是 76；
    连同大疆、58 同城共 **3,366 行纯影子**，其中吉利校招 2,372 行 ——
    「吉利有 2,595 个校招岗」这个数字里 91% 是重复计数。

    自动扩源（auto_discover）按公司猜 slug 探活，完全可能给一家已有自有域名源的公司再插一条
    厂商域名的源 → 这个坑会自己长回来，所以要有常设告警而不是一次性清理。
    """
    groups = {}
    for sid, source in (sources_by_id or {}).items():
        if not source or not source.get("enabled", True):
            continue
        ident = portal_identity(source.get("source_url"))
        if not ident:
            continue
        groups.setdefault(ident, []).append(source)

    dupes = {k: v for k, v in groups.items() if len(v) > 1}
    if not dupes:
        return []

    evidence = []
    for ident, items in sorted(dupes.items(), key=lambda kv: -len(kv[1]))[:8]:
        hosts = "、".join(
            f"{_host_of(i.get('source_url'))}（{i.get('company') or '?'}）" for i in items)
        evidence.append(f"{ident}：{len(items)} 个源指向同一门户 → {hosts}")
    return [{
        "rule": "H",
        "subject": "重复源",
        "summary": f"{len(dupes)} 个 ATS 门户各被登记了多次，同一批岗位在库里存了多份"
                   f"（两边都 success，不会有任何失败信号）。",
        "evidence": evidence,
        "next": "先抽样比对两边岗位 id/uuid 的重合率再动手——URL 形态像不代表是同一批岗。"
                "确认重复后：有自有域名的**保自有域名**（产品原则：点击要跳官网详情）；"
                "同域名不同写法的保**库里占多数**的那种（moka 现有 334 个 /-recruitment/ vs 62 个 /apply/）；"
                "Workday 仅大小写不同的保租户注册的那个大小写。"
                "再把影子行标成 removed（可复活，别用 expired——那个次日会被 purge 永久删）。"
                "只标「在保留域名下确有孪生行」的，只在厂商域名出现的岗不要动。",
    }]


def _host_of(url: str) -> str:
    m = re.search(r"^https?://([^/]+)", url or "")
    return m.group(1) if m else "?"


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


# 规则 O：校招季（秋招 9~11 月、春招 3~4 月，按上海时间）里必投公司没接校招渠道 = 供给缺口。
# 淡季不吵：淡季 missing 是常态，吵了只会让人把 watchdog 静音。
CAMPUS_SEASON_MONTHS = frozenset({3, 4, 9, 10, 11})
CAMPUS_CHANNEL_MIN_MISSING = 5


def evaluate_campus_channel_gap(rows, now=None, min_missing=CAMPUS_CHANNEL_MIN_MISSING):
    """规则 O：校招季里国内必投公司 `campus_channel = missing` 的家数 ≥ 阈值。

    2026-09-17 实测：国内必投 321 家里 46 家只接了社招、89 家没源，合计 135 家在秋招季对用户是隐形的，
    而台账天天报 healthy。这条规则读的是迁移 254 落成的列，不是 evidence 里的散文。
    """
    now = now or datetime.now(timezone.utc)
    if now.astimezone(SHANGHAI).month not in CAMPUS_SEASON_MONTHS:
        return []
    missing = [r for r in rows or [] if (r or {}).get("campus_channel") == "missing"]
    if len(missing) < max(1, int(min_missing)):
        return []
    idle = [r for r in rows or [] if (r or {}).get("campus_channel") == "idle"]
    by_industry = Counter(
        str((r.get("industries") or ["?"])[0]) for r in missing
    )
    names = sorted(str(r.get("company") or "?") for r in missing)
    return [{
        "rule": "O",
        "subject": "must_apply_campus_channel",
        "summary": (f"校招季里国内必投公司有 {len(missing)} 家没接校招渠道"
                    f"（另有 {len(idle)} 家渠道在但近 3 天零校招岗）。"),
        "evidence": [f"按行业分：{dict(by_industry)}"] + [
            f"{name}" for name in names[:40]
        ] + ([f"… 共 {len(names)} 家"] if len(names) > 40 else []),
        "next": "按平台分簇接校招渠道（hotjob/wt/beisen/moka），每家过探活门才入库；"
                "idle 的先查源是否坏了（crawl_runs）再说对方没开。",
    }]


APPLY_PROGRAM_STALE_DAYS = 45
MAC_ANNOUNCEMENT_HARVEST_HOURS = 30


def evaluate_missing_mac_announcement_harvest(rows, now=None,
                                              hours=MAC_ANNOUNCEMENT_HARVEST_HOURS):
    """规则 M：27 省主 runner 的 Mac 超过 hours 没有台账就告警。

    CI 只抓境外可达的 4 省，不能用它的 success 代替 Mac 的 27 省收尾记录。
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    for row in rows or []:
        if (row or {}).get("module") != "announcement_harvest":
            continue
        metrics = row.get("metrics") or {}
        if metrics.get("runner") != "mac":
            continue
        finished = _as_dt(row.get("finished_at") or row.get("created_at"))
        if finished and finished >= cutoff:
            return []
    return [{
        "rule": "M",
        "subject": "announcement_harvest",
        "summary": f"Mac 公告抓取 {hours} 小时无记录：27 省主 runner 可能没有启动。",
        "evidence": [
            "只找到 CI 兜底 runner 不能证明 geo-blocked 省实际抓过；"
            "判据是 announcement_harvest.metrics.runner=mac 的 finished_at/created_at。"
        ],
        "next": "先检查 Mac launchd 是否已加载，以及 plist 里的脚本绝对路径是否仍指向当前仓库。",
    }]


def evaluate_crawl_run_unrecorded(rows, today=None):
    """规则 N：run.py 活着但两次终态回写都失败，不能只留在会被截断的 CI 日志里。"""
    today = str(today or datetime.now(SHANGHAI).date())[:10]
    by_task = Counter()
    for row in rows or []:
        if (row or {}).get("run_date") != today:
            continue
        task = row.get("module")
        if task not in ("daily_crawl", "campus_crawl", "enrich_crawl"):
            continue
        try:
            count = int((row.get("metrics") or {}).get("crawl_run_unrecorded") or 0)
        except (TypeError, ValueError):
            continue
        if count > 0:
            by_task[task] += count
    total = sum(by_task.values())
    if total == 0:
        return []
    return [{
        "rule": "N",
        "subject": "crawl_run_unrecorded",
        "summary": f"当日有 {total} 个 crawl_run 终态两次都未回写，台账状态可能一直是 running。",
        "evidence": [f"{task}: crawl_run_unrecorded={count}"
                     for task, count in sorted(by_task.items())],
        "next": "查对应任务的数据库写入错误；这表示进程仍在运行，但 success/failed 两次收尾都没写成。",
    }]


# 规则 P：洞察库 7 天新增 active 条数。阈值取得保守——2026-09-03~17 实测每天新增 active
# 在 8~682 条之间波动（中位 82），7 天累计从没低过三位数。低于 20 基本只可能是整条链停了
# （LLM 账户欠费 / 搜索 key 失效 / 队列空转），不是「这周没啥可写」。
INSIGHT_WEEKLY_MIN = 20


def evaluate_insight_supply_stall(rows, today=None, minimum=INSIGHT_WEEKLY_MIN):
    """规则 P：洞察库近 7 天新增 active 洞察过少 = 供给停摆。

    为什么规则 A 顶不了这个：规则 A 看的是「模块产出为 0」，而 T3 每晚都会报
    `checked: 5 / companies_enriched: 3`，永远不为 0 —— 它数的是**处理了几家公司**。
    公司照样被处理、判官照样 abstain、库里一条没多，规则 A 全程不响。
    指标为 None（没数出来）**不告警**：拿不到数不等于数是 0，那是两回事。
    """
    today = str(today or datetime.now(SHANGHAI).date())[:10]
    latest = None
    for row in rows or []:
        if (row or {}).get("module") != "insight_backlog":
            continue
        metrics = (row.get("metrics") or {})
        if "active_added_7d" not in metrics:
            continue
        if latest is None or str(row.get("run_date") or "") > str(latest[0] or ""):
            latest = (row.get("run_date"), metrics.get("active_added_7d"))
    if latest is None:
        return []
    run_date, value = latest
    if value is None:
        return []
    try:
        value = int(value)
    except (TypeError, ValueError):
        return []
    if value >= minimum:
        return []
    return [{
        "rule": "P",
        "subject": "insight_supply",
        "summary": f"洞察库近 7 天只新增了 {value} 条 active 洞察（下限 {minimum}），供给可能已停摆。",
        "evidence": [f"最近一次台账 run_date={run_date}，active_added_7d={value}",
                     f"今天={today}"],
        "next": "按顺序查：① SiliconFlow 账户是否欠费（llm_usage 台账 calls 是否归零）；"
                "② 搜索源 key / 日顶（search_usage 各 provider 当天 used）；"
                "③ T3 队列是否被 t3_fail_count 死信掏空。",
    }]


def evaluate_stale_apply_programs(rows, today=None, stale_days=APPLY_PROGRAM_STALE_DAYS):
    """规则 J：/programs 的投递入口该重新人工核实了。

    为什么需要它（2026-09-07）：创始人反馈公告制入口「不是具体的公告页面，不准」，
    修法是把中行 / 邮储 / 中国邮政指到**当期公告全文**——那是最准的形态，
    代价是**它会随报名窗口过期变旧**，而 apply_programs 没有任何自动复查机制
    （gap_census.classify_company 把这类公司钉在 manual_review 且 next_retry_at=None）。
    复查时点原本只写在 notes 里，而 notes 没人读就等于没写。

    两条判据（任一成立就报）：
      · recheck_after 到期 —— 人填的明确到期日（多为报名截止日 +1 天，迁移 243）。
      · verified_at 超过 stale_days 没更新 —— 兜住没填到期日的行；链接烂掉是**慢性**的，
        不给兜底就只有「有人正好点进去」才发现。

    ⚠️ 判据刻意**不解析 window_text**：那一列是原文照抄（迁移 226 的设计，各家写法不一），
       硬解析会在「已经过期」和「还没到期」两个方向上都出错。要机器判就用单独的日期列。
    """
    today = today or datetime.now(SHANGHAI).date()
    if isinstance(today, str):
        today = datetime.fromisoformat(today).date()
    due, stale = [], []
    for row in rows or []:
        if not (row or {}).get("enabled", True):
            continue
        company = row.get("company") or "?"
        recheck = row.get("recheck_after")
        if recheck:
            try:
                if datetime.fromisoformat(str(recheck)).date() <= today:
                    due.append((company, str(recheck), row.get("entry_url") or ""))
                    continue
            except ValueError:
                pass  # 日期写坏了不该拖垮整条规则，交给下面的 verified_at 兜底
        verified = _as_dt(row.get("verified_at"))
        if verified is None:
            continue
        age = (datetime.now(timezone.utc) - verified).days
        if age >= stale_days:
            stale.append((company, age, row.get("entry_url") or ""))
    if not due and not stale:
        return []
    evidence = [f"{c}：到期日 {d} 已到 → {u}" for c, d, u in sorted(due)]
    evidence += [f"{c}：{age} 天没重新核实 → {u}" for c, age, u in sorted(stale, key=lambda x: -x[1])[:10]]
    parts = []
    if due:
        parts.append(f"{len(due)} 条到了明确的复查日")
    if stale:
        parts.append(f"{len(stale)} 条超过 {stale_days} 天没人核实")
    return [{
        "rule": "J",
        "subject": "apply_programs",
        "summary": ("/programs 的投递入口需要人工复查：" + "、".join(parts) +
                    "。指向具体公告的入口会随报名窗口过期，过期后用户点进去就是往期公告。"),
        "evidence": evidence,
        "next": ("逐条真渲染打开：还有在窗公告就把 verified_at / recheck_after 往后推；"
                 "已经过期就改指该栏目的当期公告或公告列表页（判据见 "
                 "lib/apply-programs.needsDeeperAnnouncementLink：必须打开就看得见公告条目）。"),
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


def guarded_evaluate(rule, rule_errored, fn, *args, **kwargs):
    """跑一条规则的 evaluate_*，异常不外传——只打 ::warning:: + 把 rule 记进 rule_errored、
    本轮当作零 findings，让调用方（main()）继续评估其余规则、继续发已经算好的 issue。

    2026-09-19 加：此前 A/C/D/M/N/P 六条规则是裸调用，任一异常会让整个 main() 直接崩溃、
    其余规则（包括已经算好的 F/G/H/I/K/L 等）一个都发不出去；桥接进 audit_results 时也
    没法单独把这一条标成「没评估成」。提出成模块级函数是为了能脱离 main() 单独测——
    真正调用点仍在 main() 里，行为不变，只是抽出来方便写单测。
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 单条规则失败不能拖垮其余规则
        print(f"::warning::[watchdog] 规则 {rule} 本轮没评估成：{type(exc).__name__}: {exc}")
        rule_errored.add(rule)
        return None


def build_audit_bridge_rows(findings, rule_errored, checks, today, now=None):
    """把这一轮的 findings 翻成 audit_results 行——每条 contract 里 source=watchdog 的检查项一行。

    只做翻译，不重新判定：value = 这条规则本轮命中的 finding 数（用 issue_title 里的
    subject 去重前的原始条数，与 GitHub Issue 是否已经开过无关）；rule_errored 里的规则
    这一轮真的没评估成（取数异常/跳过），落 verdict=error、value=None——不能拿「没查」
    充「查到 0」。max 30 条 finding 摘要放进 detail，供排查时不用回头翻 Issue 列表。
    """
    import audit_runner as A
    now = now or datetime.now(timezone.utc)
    by_rule = defaultdict(list)
    for f in findings:
        by_rule[f["rule"]].append(f)

    rows = []
    for c in checks:
        if c.get("source") != "watchdog":
            continue
        rule = c["rule"]
        row = {
            "check_id": c["id"],
            "run_date": today,
            "layer": c["layer"],
            "severity": c["severity"],
            "normal": c["normal"],
            "calibrated": bool(c.get("calibrated", True)),
            "measured_at": now.astimezone(timezone.utc).isoformat(),
            "error_message": None,
            "duration_ms": None,
        }
        if rule in rule_errored:
            row.update(value=None, verdict="error", detail=None,
                       error_message="这一轮该规则的取数/评估失败或被跳过，不是评估出 0 条")
        else:
            matched = by_rule.get(rule, [])
            value = float(len(matched))
            row["value"] = value
            row["verdict"] = "ok" if A.evaluate_normal(value, c["normal"]) else "breach"
            row["detail"] = ({"findings": [
                {"title": issue_title(f), "key": f.get("subject")} for f in matched[:30]
            ]} if matched else None)
        rows.append(row)
    return rows


def publish_audit_bridge(checks, findings, rule_errored, today, now=None):
    """写失败只 ::warning::，绝不影响 watchdog 主流程的退出码——这条桥接是旁路观测。"""
    rows = build_audit_bridge_rows(findings, rule_errored, checks, today, now=now)
    if not rows:
        return 0
    try:
        import audit_runner as A
        conn = A.connect("supabase")
        try:
            written = A.write_results(conn, rows)
        finally:
            conn.close()
        print(f"[watchdog] 已把 {written} 条老告警规则的今日结果写进 audit_results")
        return written
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::[watchdog] 写 audit_results 桥接失败（不影响本轮告警发布）："
              f"{type(exc).__name__}: {exc}")
        return 0


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
    # 规则 K / L 按 adapter 静音：与模块名不是一个命名空间（moka / workday vs daily_crawl），分开配。
    muted_adapters = [m for m in os.environ.get("OPS_WATCHDOG_MUTE_ADAPTERS", "").split(",") if m.strip()]
    now = datetime.now(timezone.utc)
    today = now.astimezone(SHANGHAI).date().isoformat()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    import db  # 延迟导入：单测不需要 supabase 依赖

    sb = db.get_supabase()
    started_at = now
    since_day = (now - timedelta(days=max(args.days + 2, 4))).astimezone(SHANGHAI).date().isoformat()
    ops_rows = db.fetch_all_rows(
        lambda: sb.table("ops_runs").select("module,run_date,status,metrics,finished_at,created_at")
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

    # 哪些规则「这一轮真的没评估成」（取数异常，不是评估出 0 条）——供 audit_results 桥接用
    # （见 build_audit_bridge_rows）。2026-09-19 起 A/C/D/M/N/P 也各自包了一层：此前它们
    # 裸调用、任一抛错就让整个 main() 崩溃、其余规则（含已经算好的 F/G/H/I/K/L 等）一个
    # 都发不出去；现在改成每条单独 try/except，异常只打 ::warning:: + 标记该规则 error、
    # 视为本轮零 findings，其余规则照常评估与发 issue——行为更稳，判定逻辑与阈值一个字都没改。
    rule_errored = set()

    findings = []
    zero, skipped = guarded_evaluate(
        "A", rule_errored, evaluate_zero_output, ops_rows, today, days=args.days, muted=muted,
    ) or ([], [])
    findings += zero
    findings += guarded_evaluate(
        "C", rule_errored, evaluate_stuck_ledger, discovery_rows, now=now, hours=args.stuck_hours,
    ) or []
    findings += guarded_evaluate(
        "D", rule_errored, evaluate_account_errors, event_rows, ops_rows, now=now,
    ) or []
    findings += guarded_evaluate(
        "M", rule_errored, evaluate_missing_mac_announcement_harvest, ops_rows, now=now,
    ) or []
    findings += guarded_evaluate(
        "N", rule_errored, evaluate_crawl_run_unrecorded, ops_rows, today=today,
    ) or []
    findings += guarded_evaluate(
        "P", rule_errored, evaluate_insight_supply_stall, ops_rows, today=today,
    ) or []
    # 规则 O 单独包住：台账几百行的小表，取不到不拖垮别的规则。
    try:
        gap_rows = db.fetch_all_rows(
            lambda: sb.table("must_apply_gap_attempts")
                      .select("company,industries,campus_channel")
                      .eq("scope", "domestic")
        )
        findings += evaluate_campus_channel_gap(gap_rows, now=now)
    except Exception as exc:  # noqa: BLE001
        print(f"[watchdog] 规则 O 取 must_apply_gap_attempts 失败，跳过：{exc}")
        rule_errored.add("O")
    # 规则 J 单独包住：apply_programs 是张十几行的小表，取不到也不该拖垮别的规则。
    try:
        program_rows = db.fetch_all_rows(
            lambda: sb.table("apply_programs")
                      .select("company,program_type,entry_url,enabled,verified_at,recheck_after")
                      .eq("enabled", True)
        )
        findings += evaluate_stale_apply_programs(program_rows, today=now.astimezone(SHANGHAI).date())
    except Exception as exc:  # noqa: BLE001
        print(f"[watchdog] 规则 J 取 apply_programs 失败，跳过：{exc}")
        rule_errored.add("J")
    # 规则 F 单独包住：crawl_runs 是最大的一张表（1,400 源 × 4 轮/天），取不到不能拖垮 A/C/D。
    try:
        # 规则 K 要 1 个最近窗 + 7 天基线、规则 L 要 10 天，一次取够；F/G/I 仍只看自己那 dead_source_days 天
        # （2026-09-13 实测 8 天 51,971 行 / 45s，5 天 30,066 行 / 32s，都远在 job 超时之内；
        #  整个 watchdog job 在 CI 上 1.5~1.8 分钟跑完。本机从国内连同一查询 8 天要 463s，别拿本机耗时当 CI 的）。
        crawl_days = max(args.dead_source_days, 1 + COLLAPSE_BASELINE_DAYS, SILENT_LOOKBACK_DAYS)
        crawl_since = (now - timedelta(days=crawl_days)).isoformat()
        all_crawl_rows = db.fetch_all_rows(
            lambda: sb.table("crawl_runs")
                      .select("source_id,status,error_message,started_at,finished_at,"
                              "reported_total,coverage_complete,jobs_found")
                      .gte("started_at", crawl_since)
        )
        crawl_rows = rows_started_since(all_crawl_rows, now - timedelta(days=args.dead_source_days))
        source_rows = db.fetch_all_rows(
            lambda: sb.table("sources").select("id,adapter_name,company,source_url,enabled")
                      .eq("enabled", True)
        )
        sources_by_id = {r["id"]: r for r in source_rows}
        findings += evaluate_dead_sources(crawl_rows, sources_by_id,
                                          days=args.dead_source_days)
        # 规则 G 复用同一批 crawl_rows / sources（多取三列，不多打一次库）。
        findings += evaluate_coverage_shortfall(crawl_rows, sources_by_id)
        # 规则 I 复用同一批 crawl_rows（多取 finished_at 一列，不多打一次库）。
        findings += evaluate_unfinished_crawls(crawl_rows, sources_by_id, now=now)
        findings += evaluate_duplicate_portals(sources_by_id)
        findings += evaluate_adapter_collapse(all_crawl_rows, sources_by_id, now=now,
                                              muted=muted_adapters)
        findings += evaluate_silent_sources(
            rows_started_since(all_crawl_rows, now - timedelta(days=SILENT_LOOKBACK_DAYS)),
            sources_by_id, now=now, muted=muted_adapters)
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::[watchdog] 规则 F/G/H/I/K/L（源级 / adapter 级抓取告警）本轮没查成："
              f"{type(exc).__name__}: {exc}")
        rule_errored |= {"F", "G", "H", "I", "K", "L"}

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
            rule_errored |= {"B", "E"}
    else:
        print("[watchdog] 识别不到仓库，跳过 workflow 侧规则（B/E）。")
        rule_errored |= {"B", "E"}  # 没跑 = 这一轮真的没评估成，不是评估出「0 条」

    print(f"\n[watchdog] {today} 检查完成：{len(findings)} 条告警"
          f"（ops_runs {len(ops_rows)} 行 / queued {len(discovery_rows)} 行 / events {len(event_rows)} 行）"
          f"{'　※ dry-run，不开 issue' if not apply else ''}")
    for finding in findings:
        print(f"  · [{finding['rule']}] {issue_title(finding)}")
    if skipped:
        print(f"[watchdog] 这些模块在写台账但没声明产出口径（规则 A 跳过，别忘了补）：{', '.join(skipped)}")

    # 桥接进 audit_results：dry-run 与 apply 都写（这是旁路观测台账，不是「真开 issue」那个
    # 有副作用的动作），失败只 ::warning::，不影响本次 watchdog 的退出码。
    try:
        import audit_runner as _audit_runner
        bridge_checks = [c for c in _audit_runner.load_contract() if c.get("source") == "watchdog"]
        publish_audit_bridge(bridge_checks, findings, rule_errored, today, now=now)
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::[watchdog] 读取 audit_contract.yaml 桥接检查项失败：{type(exc).__name__}: {exc}")

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
