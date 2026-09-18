"""晨报：把结构性审计（audit_results）+ 体验走查（ops_runs）+ 老问题清账（gh issue）
拼成一封给创始人看的邮件。

收件人是非技术背景的创始人，只关心「产品是否健康、用户在不在、要不要我今天做点什么」。
三条硬规矩（别改回去）：
  1. 「没查到」永远显示成「没查到」，不许显示成 0（verdict=error 时 value 是 None）。
  2. 昨天没有数据时不显示「较昨天」这一句，不编一个假的变化量。
  3. 绿灯也每天发——绿灯邮件本身就是「产品还活着」的心跳，不能只在出事才发。

发信直接 POST Resend HTTP API（urllib，不装 SDK）；缺 key/收件人就 dry-run 打印到 stdout，
并且要显式打一行「未发送：缺 …」——不允许静默退出。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

try:
    import audit_runner as _audit_runner
except ImportError:  # pragma: no cover - 直接脚本运行时兜底
    _audit_runner = None

try:
    import ops_runs as _ops_runs
except ImportError:  # pragma: no cover
    _ops_runs = None


# ---------------------------------------------------------------------------
# 走查问题类型的人话标签（抄自 scripts/ux-walkthrough/walkthrough.js 的 ISSUE_TYPES，
# 两边各自维护、含义必须逐字对齐——那边改了这边也要改）。
# ---------------------------------------------------------------------------
WALKTHROUGH_ISSUE_LABELS = {
    "zero_shown": "推荐页零岗（非求职范围错配）",
    "scope_mismatch": "求职范围错配：选了海外但城市全国内又没有英文简历",
    "direction_low": "展示岗位方向命中率偏低",
    "role_input_format": "用户填的岗位方向写法没被识别（一栏里塞了多个岗位名）",
    "role_mismatch_high": "候选里因方向不符被拦掉的占比偏高",
    "insight_uncovered": "他会看到的公司里，一家有职业洞察的都没有",
    "campus_channel_broken": "校招/实习用户，所属行业必投公司的校招渠道全不通",
    "api_latency": "接口响应慢或失败",
}

# 各段用到的固定检查项分组（人话分节，不是按 layer/db 机械分节）。
SECTION_USERS = ["exp.dau_yesterday", "exp.wau_7d", "exp.registered_total", "exp.new_users_yesterday"]
SECTION_EXPERIENCE = [
    "exp.job_clicks_yesterday", "exp.job_clicks_7d", "exp.saved_yesterday", "exp.applied_yesterday",
    "exp.search_zero_result_rate_7d", "exp.search_slow_rate_7d", "exp.search_very_slow_rate_7d",
    "exp.ux_walkthrough_zero_shown", "exp.ux_walkthrough_issue_count",
    "exp.ux_walkthrough_direction_ok_avg", "exp.ux_walkthrough_insight_coverage_avg",
    "exp.ux_walkthrough_campus_healthy_ratio_avg",
    "exp.dead_click_signal_freshness_30d", "exp.dead_click_unknown_rate_alltime",
]
SECTION_SUPPLY = ["jobs.active_total", "jobs.valid_active_total", "jobs.new_yesterday", "jobs.closed_yesterday"]
SECTION_FAKE_GREEN = ["exp.fake_green_sources_yesterday", "exp.fake_green_sources_chronic"]

FIXED_DISCLAIMERS = [
    "投递数是用户自己手动标记的，不代表真实投递数量（很多人投了也不点这个按钮）。",
    "「点开是死岗」这项指标目前测不出真实结果（79% 查不出来），先别信它。",
    "在招总量这类库存指标是从 2026-09-18 才开始每天留一个历史点的，之前没有对比基准。",
]


# ---------------------------------------------------------------------------
# 纯函数：格式化
# ---------------------------------------------------------------------------

def format_number(value):
    """大数用「万」，其余原样；None 走别的分支不进这里。"""
    if value is None:
        return "没查到"
    v = float(value)
    if abs(v) >= 10000:
        return f"{v / 10000:.1f}万"
    if v == int(v):
        return str(int(v))
    return f"{v:g}"


def format_percent(value):
    if value is None:
        return "没查到"
    return f"{float(value) * 100:.1f}%"


def is_ratio_check(check_id):
    return "rate" in check_id or check_id.endswith("_avg") or check_id.endswith("_ratio")


def format_value(check_id, value):
    if value is None:
        return "没查到"
    if is_ratio_check(check_id):
        return format_percent(value)
    return format_number(value)


def format_delta(check_id, today_value, yesterday_value):
    """有上一次数据才显示变化；没有就什么都不写（不许编一个假变化）。

    说「较上一次」不说「较昨天」——上一批测量未必发生在昨天（比如检查项刚新增，
    或者中间某天跑漏了）；数字用 format_number 统一走「万」的格式化，避免 ↑7817 这种
    大数直接甩出来。
    """
    if today_value is None or yesterday_value is None:
        return ""
    delta = today_value - yesterday_value
    if is_ratio_check(check_id):
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        return f"（较上一次{arrow}{abs(delta) * 100:.1f}个百分点）"
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    return f"（较上一次{arrow}{format_number(abs(delta))}）"


# ---------------------------------------------------------------------------
# 纯函数：灯色
# ---------------------------------------------------------------------------

def compute_traffic_light(results_by_id):
    """🔴 = 有 critical breach/error；🟡 = 有 warn/critical breach 或 warn/critical 的「没查到」；🟢 = 全 ok。

    severity=info 的 breach/error 绝不染灯——那批检查本来就是「已知不可用/纯记录留痕」
    （如死链探活埋点已停、新增用户数只是记数），天天染黄会让邮件的灯色失去信号价值。
    它们仍会照实出现在正文和⑧段数据完整性声明里，只是不影响主题行的灯色。
    """
    has_critical_bad = any(
        r["severity"] == "critical" and r["verdict"] in ("breach", "error")
        for r in results_by_id.values()
    )
    if has_critical_bad:
        return "🔴"
    has_warn_bad_or_error = any(
        r["severity"] == "warn" and r["verdict"] in ("breach", "error")
        for r in results_by_id.values()
    )
    if has_warn_bad_or_error:
        return "🟡"
    return "🟢"


# ---------------------------------------------------------------------------
# 纯函数：取值辅助（按 check_id 从结果集里拿一条，容忍缺失）
# ---------------------------------------------------------------------------

def pick(results_by_id, check_id):
    return results_by_id.get(check_id)


def section_rows(results_by_id, results_yesterday_by_id, names, check_ids):
    rows = []
    for cid in check_ids:
        r = results_by_id.get(cid)
        if r is None:
            continue
        name = names.get(cid, cid)
        value = r.get("value")
        verdict = r.get("verdict")
        shown = format_value(cid, value)
        delta = format_delta(cid, value, (results_yesterday_by_id.get(cid) or {}).get("value"))
        # ok 的行不带「（待校准）」——每行都吵；只在不达标/没查到时才提醒「这条阈值还没校准过」。
        calibrated_tag = "" if (r.get("calibrated", True) or verdict == "ok") else "（待校准）"
        why = f"　{r.get('why')}" if verdict in ("breach", "error") and r.get("why") else ""
        rows.append({
            "check_id": cid, "name": name, "shown": shown, "delta": delta,
            "verdict": verdict, "calibrated_tag": calibrated_tag, "why": why,
        })
    return rows


def render_rows_text(rows):
    lines = []
    for row in rows:
        icon = {"ok": "✅", "breach": "⚠️", "error": "❓"}.get(row["verdict"], "❓")
        extra = row["why"]
        if row["verdict"] == "error":
            extra = "（今天没查到，不是 0）" + extra
        lines.append(f"{icon} {row['name']}：{row['shown']}{row['delta']}{row['calibrated_tag']}{extra}")
    return lines


# ---------------------------------------------------------------------------
# 走查问题按类型归并
# ---------------------------------------------------------------------------

def summarize_walkthrough_issues(issues_by_type):
    """{type: count} → 按人话标签排好序的列表，过滤掉 0；未知 type 也保留（用原始 key 兜底）。"""
    if not issues_by_type:
        return []
    out = []
    for issue_type, count in issues_by_type.items():
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        label = WALKTHROUGH_ISSUE_LABELS.get(issue_type, issue_type)
        out.append((n, label))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


# ---------------------------------------------------------------------------
# 今天新出的问题 / 建议做的事
# ---------------------------------------------------------------------------

def find_newly_broken(results_today_by_id, results_yesterday_by_id, names):
    """昨天 ok、今天 breach/error 的检查项。"""
    out = []
    for cid, today_row in results_today_by_id.items():
        if today_row["verdict"] not in ("breach", "error"):
            continue
        yest = results_yesterday_by_id.get(cid)
        if yest is not None and yest["verdict"] == "ok":
            out.append({"check_id": cid, "name": names.get(cid, cid), "why": today_row.get("why", "")})
    return out


def _group_key(check):
    """一条检查项归到哪个『层』——老告警桥接条目（source=watchdog）单独算一层，
    不跟它 layer 字段声明的 pipeline/data 混在一起（那只是历史遗留的挂靠）。
    """
    if (check or {}).get("source") == "watchdog":
        return "watchdog"
    return (check or {}).get("layer", "other")


def build_action_items(results_today_by_id, checks_by_id, limit=5, max_per_group=2):
    """从 breach 项的 action 字段取，critical 在前，最多 limit 条；同一层最多占
    max_per_group 条——某一整层（比如链路层集体没跑）时，剩下几条名额要留给别的层，
    不能被一层的 5 条建议占满，创始人才看得出『还有别的事要看』。

    同一句 action 文案常常对应好几个检查项（比如好几条都写「去看走查报告」），
    逐条各占一行只会让创始人觉得啰嗦——按 action 文案去重，命中的名字用「、」并列。
    """
    grouped = {}  # action 文案 -> {"rank": 排序优先级, "names": [name, ...], "group": 层}
    for cid, row in results_today_by_id.items():
        if row["verdict"] not in ("breach", "error"):
            continue
        check = checks_by_id.get(cid) or {}
        action = check.get("action")
        if not action:
            continue
        rank = 0 if row["severity"] == "critical" else 1
        name = check.get("name", cid)
        bucket = grouped.setdefault(action, {"rank": rank, "names": [], "group": _group_key(check)})
        bucket["rank"] = min(bucket["rank"], rank)
        if name not in bucket["names"]:
            bucket["names"].append(name)

    ordered = sorted(grouped.items(), key=lambda kv: (kv[1]["rank"], kv[1]["names"]))
    result = []
    group_counts = {}
    for action, info in ordered:
        if len(result) >= limit:
            break
        group = info["group"]
        if group_counts.get(group, 0) >= max_per_group:
            continue
        group_counts[group] = group_counts.get(group, 0) + 1
        names = info["names"]
        # 名字列表也可能挤成一堵墙（比如一整层集体没跑，几十条检查共用同一句 action 文案）——
        # 同⑧段『没查到』一样，超过 5 个就只列前 5 个 + 剩余数，不逐条念完。
        shown = names[:5]
        label = "、".join(shown)
        if len(names) > 5:
            label += f"等 {len(names)} 项"
        result.append(f"{label}：{action}")
    return result


def order_old_issues(issues, now=None):
    """按未解决天数降序排列 gh issue 列表（每个 issue 需含 createdAt ISO 字符串）。"""
    now = now or datetime.now(timezone.utc)

    def age_days(issue):
        try:
            created = datetime.fromisoformat(str(issue.get("createdAt")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return 0
        return (now - created).total_seconds() / 86400

    return sorted(issues, key=age_days, reverse=True)


# ---------------------------------------------------------------------------
# 主体：从 audit_results 取「今天」「昨天」两批
# ---------------------------------------------------------------------------

def index_results(rows):
    return {r["check_id"]: r for r in rows}


def fetch_audit_results(conn, run_date_str):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            select check_id, layer, severity, value, normal, verdict, calibrated, error_message
            from public.audit_results where run_date = %s
            """,
            (run_date_str,),
        )
        cols = ["check_id", "layer", "severity", "value", "normal", "verdict", "calibrated", "error_message"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def fetch_latest_ops_run(conn, module):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            select metrics, status, finished_at from public.ops_runs
            where module = %s order by finished_at desc limit 1
            """,
            (module,),
        )
        row = cur.fetchone()
        if not row:
            return None
        metrics, status, finished_at = row
        return {"metrics": metrics or {}, "status": status, "finished_at": finished_at}
    finally:
        cur.close()


def pick_latest_sent(rows):
    """rows 是按 finished_at 降序排好的 ops_runs(module='morning_digest') 行（dict，
    含 metrics/status/finished_at），从中挑出**最近一条真正发出去的**（metrics.mode == "sent"）。

    这是本次返工修的真 bug：「上一封晨报是否送达」此前直接读最新一条 ops_runs，而
    dry-run 也会写一行台账（status 甚至可以是 success）——于是天天跑 dry-run 就天天显示
    「已送达」，一封真邮件都没发出去。dry-run 行必须被跳过，往前找最近一条真发的；
    一条都没有就说明还没有真正发出过晨报。
    """
    for row in rows or []:
        metrics = row.get("metrics") or {}
        if metrics.get("mode") == "sent":
            return row
    return None


def fetch_latest_sent_digest(conn, limit=30):
    """拉最近 N 条晨报台账（按时间降序），交给 pick_latest_sent 挑出最近一条真发的。
    不在 SQL 里直接过滤 mode='sent'，是为了让「跳过 dry-run 行往前找」这条逻辑能被
    pick_latest_sent 单独单测覆盖，不必连真库才能验证。
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            select metrics, status, finished_at from public.ops_runs
            where module = 'morning_digest'
            order by finished_at desc limit %s
            """,
            (limit,),
        )
        rows = [
            {"metrics": metrics or {}, "status": status, "finished_at": finished_at}
            for metrics, status, finished_at in cur.fetchall()
        ]
        return pick_latest_sent(rows)
    finally:
        cur.close()


def fetch_open_issues():
    """gh issue list；CI 里靠 GH_TOKEN env，本地没配就返回空列表（不当作失败）。

    `--json comments` 拿到的是每条评论的完整对象列表（id/author/body/…），不是数字——
    直接塞进邮件正文曾把一行撑到 4 万字符、整封 325KB。这里不改字段列表（省一次请求成本，
    也留住 comments 内容供未来别的用途），只在渲染那一层用 comment_count() 转成数量。
    """
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--limit", "100",
             "--json", "number,title,createdAt,comments,labels"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if out.returncode != 0:
            sys.stderr.write(f"[morning-digest] gh issue list 失败（跳过老问题清账）: {out.stderr.strip()[:200]}\n")
            return []
        return json.loads(out.stdout or "[]")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[morning-digest] gh issue list 异常（跳过老问题清账）: {type(exc).__name__}\n")
        return []


def comment_count(issue):
    """`comments` 字段可能是完整评论对象列表（gh issue list 的真实形状），也可能已经是数字
    （比如未来换成 gh api 的计数字段）——统一转成条数，绝不把整个列表塞进邮件正文。
    """
    comments = (issue or {}).get("comments")
    if isinstance(comments, list):
        return len(comments)
    try:
        return int(comments)
    except (TypeError, ValueError):
        return 0


_ISSUE_TITLE_TAG_RE = re.compile(r"^\s*\[[^\]]+\]\s*")
_ISSUE_TITLE_LAST_COLON_RE = re.compile(r"^(.*?)[：:]([^：:]+)$")

# name 通常是「XX 昨天有没有跑出结果」这种检查项问句；塞进 issue 标题读不通
# （「连续零产出：校招官方页面补录昨天有没有跑」）。contract 里的 pipeline 条目应该带一个
# 短名词 `subject`（如「校招官方页面补录」），没带时用这条正则剥掉问句部分兜底——不追求
# 覆盖所有可能写法，宁可剥不干净（原样保留 name）也不许剥错（把不该删的部分删了）。
_QUESTION_SUFFIX_RE = re.compile(r"(?:（[^）]*）)?(?:自己)?(?:昨天|今天|最近)?(?:是否|有没有).*$")


def _check_subject(check):
    subject = check.get("subject")
    if subject:
        return subject
    name = check.get("name") or ""
    stripped = _QUESTION_SUFFIX_RE.sub("", name).strip()
    return stripped or name


def humanize_issue_title(title, names=None):
    """去掉 `[watchdog]` 这类给程序看的前缀标签；冒号后的英文模块名/文件名先原样保留，
    等有人话映射表（names）时按它替换成人话。

    ⚠️ 必须整词精确匹配，不能子串替换——`auto_discover` 是 `auto_discover_overseas` 的
    子串，子串替换会把「auto_discover_overseas」错改成「<auto_discover 的人话>_overseas」
    这种缝合怪（2026-09-19 真库 dry-run 实测过的真 bug）。只在冒号后的整段文本**恰好等于**
    某个 key 时才整段替换；等号两侧多一个字都不行，匹配不到就原样保留英文。
    """
    text = _ISSUE_TITLE_TAG_RE.sub("", str(title or ""))
    if not names:
        return text
    m = _ISSUE_TITLE_LAST_COLON_RE.match(text)
    if m:
        head, tail = m.group(1), m.group(2)
        tail_stripped = tail.strip()
        if tail_stripped in names:
            return f"{head}：{names[tail_stripped]}"
        return text
    if text.strip() in names:
        return names[text.strip()]
    return text


_MODULE_ARRAY_RE = re.compile(r"module\s*=\s*any\s*\(\s*array\s*\[([^\]]+)\]\s*\)", re.I)
_MODULE_EQ_RE = re.compile(r"\bmodule\s*=\s*'([^']+)'", re.I)
_QUOTED_LITERAL_RE = re.compile(r"'([^']+)'")


def build_issue_title_names(checks):
    """从 contract 自动构建 humanize_issue_title 的映射表，不手写——issue 标题冒号后的
    英文（模块名如 auto_discover_overseas、workflow 文件名如 dead-link-audit.yml）
    对应哪条 pipeline 检查项，靠该检查项自己的 owner（workflow 路径）与 sql 里
    `module = '…'` / `module = any(array['…', '…'])` 的字面量来确认，匹配不到就不收录
    （humanize_issue_title 原样保留英文，绝不猜）。

    映射到的人话优先用检查项的 `subject`（短名词，如「校招官方页面补录」）——直接用 `name`
    会把一句问句（「…昨天有没有跑」）塞进 issue 标题读不通；没有 subject 时用
    `_check_subject` 剥掉问句部分兜底。
    """
    names = {}
    for c in checks:
        # source=watchdog 的条目即便 layer=pipeline，也不是「一条 workflow 一条 SQL」那种
        # 真正意义上的链路检查——它没有 module 字面量可抠、owner 也不是 workflow 文件，
        # 收进来只会制造噪音映射，跳过。
        if c.get("layer") != "pipeline" or c.get("source") == "watchdog":
            continue
        subject = _check_subject(c)
        if not subject:
            continue
        owner = c.get("owner") or ""
        basename = os.path.basename(owner)
        if basename:
            names.setdefault(basename, subject)
        sql = c.get("sql") or ""
        for m in _MODULE_ARRAY_RE.finditer(sql):
            for lit in _QUOTED_LITERAL_RE.findall(m.group(1)):
                names.setdefault(lit, subject)
        for m in _MODULE_EQ_RE.finditer(sql):
            names.setdefault(m.group(1), subject)
    return names


# ---------------------------------------------------------------------------
# 邮件正文拼装
# ---------------------------------------------------------------------------

def build_subject(light, results_by_id, checks_by_id):
    today = datetime.now(SHANGHAI)
    date_label = f"{today.month}/{today.day}"
    dau = pick(results_by_id, "exp.dau_yesterday")
    applied = pick(results_by_id, "exp.applied_yesterday")
    active_total = pick(results_by_id, "jobs.active_total")
    open_issue_count_tag = ""  # 具体清账数在 build_digest 里算好后由调用方替换

    dau_txt = format_number(dau["value"]) if dau and dau["value"] is not None else "?"
    applied_txt = format_number(applied["value"]) if applied and applied["value"] is not None else "?"
    active_txt = format_number(active_total["value"]) if active_total and active_total["value"] is not None else "?"
    return f"{light} 职达 {date_label} · 日活{dau_txt}人·{applied_txt}投递 · 在招{active_txt}"


def _format_last_sent_date(finished_at):
    if finished_at is None:
        return None
    dt = finished_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(SHANGHAI)
    return f"{dt.month}/{dt.day}"


def _last_sent_line(last_sent_digest):
    """last_sent_digest 必须已经是「只认 mode=='sent' 那一行」的结果（见 fetch_latest_sent_digest），
    不能直接拿最新一条 ops_runs——否则 dry-run 写的台账会被读成「送达」，这是本次返工的真 bug。
    三种文案，二选一都不许编：没有任何真发行 / 最近一次真发成功 / 最近一次真发失败。
    """
    if not last_sent_digest:
        return "还没有真正发出过晨报，这是第一封。"
    date_label = _format_last_sent_date(last_sent_digest.get("finished_at"))
    date_part = f"（{date_label}）" if date_label else ""
    status = last_sent_digest.get("status")
    if status == "success":
        return f"上一封晨报{date_part}已送达。"
    reason = (last_sent_digest.get("metrics") or {}).get("error") or "原因未知"
    if _audit_runner is not None:
        reason = _audit_runner._redact(reason)  # noqa: SLF001 - 错误信息可能带连接串/host，必须脱敏
    return f"上一封晨报{date_part}发送失败：{reason}"


_GROUP_LABELS = {"pipeline": "链路层", "data": "数据层", "experience": "体验层", "watchdog": "老告警"}
_MISSING_LIST_GROUPING_THRESHOLD = 12  # 超过这个数就不再逐条念名字，改成按层分组
_MISSING_LIST_NAMES_PER_GROUP = 5


def _missing_check_lines(all_checks, error_ids):
    """⑧段『没查到』的渲染：≤12 项逐条一行 bullet；超过 12 项按层分组，某一整层全没查到
    时写成一句话（不逐条念名字），否则该层给出前 5 个名字 + 剩余数。
    每一行返回 build_digest 的调用方，会各自变成一条『  · 』bullet（text）/ <li>（html）。
    """
    if not error_ids:
        return []
    checks_by_id = {c["id"]: c for c in all_checks}
    error_id_set = set(error_ids)
    if len(error_ids) <= _MISSING_LIST_GROUPING_THRESHOLD:
        return [f"没查到：{checks_by_id.get(cid, {}).get('name', cid)}" for cid in error_ids]

    by_group = {}
    group_totals = {}
    for c in all_checks:
        g = _group_key(c)
        group_totals[g] = group_totals.get(g, 0) + 1
        if c["id"] in error_id_set:
            by_group.setdefault(g, []).append(c["name"])

    lines = []
    for group, names in sorted(by_group.items(), key=lambda kv: -len(kv[1])):
        label = _GROUP_LABELS.get(group, group)
        total_in_group = group_totals.get(group, len(names))
        if len(names) == total_in_group:
            lines.append(f"{label}今天还没有运行结果（{total_in_group} 项都没有结果）。")
            continue
        shown = names[:_MISSING_LIST_NAMES_PER_GROUP]
        remaining = len(names) - len(shown)
        line = f"{label}有 {len(names)} 项没查到：{'、'.join(shown)}"
        if remaining > 0:
            line += f"等 {remaining} 项"
        lines.append(line + "。")
    return lines


_MAX_LINE_CHARS = 300


def _cap_line_length(line, limit=_MAX_LINE_CHARS):
    """硬上限兜底：不管上面哪段逻辑没兜住，任何一行超过这个长度都在这里截断，
    绝不让一整个对象/列表被拼进邮件正文（本次返工的诱因就是没有这道硬兜底）。
    """
    text = str(line)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _integrity_lines(all_checks, results_today_by_id, last_sent_digest):
    total = len(all_checks)
    error_ids = [cid for cid, r in results_today_by_id.items() if r["verdict"] == "error"]
    calibrated_false_names = [c["name"] for c in all_checks if not c.get("calibrated", True)]
    lines = [f"今天一共跑了 {total} 项检查，{len(error_ids)} 项没查到。"]
    lines.extend(_missing_check_lines(all_checks, error_ids))
    if calibrated_false_names:
        lines.append(f"有 {len(calibrated_false_names)} 项阈值还是拍的、没有历史数据校准过，标了「待校准」的都是。")
    lines.append(_last_sent_line(last_sent_digest))
    lines.extend(FIXED_DISCLAIMERS)
    return [_cap_line_length(line) for line in lines]


def merge_missing_as_error(checks, results_today_by_id):
    """contract 里有、但今天 audit_results 里没有这一行的检查项（含 source=watchdog 的条目）
    = 今天没查到，不是「跳过不算」。合成一行 verdict='error' 的记录塞进去，这样它会自动被
    ⑧段的『没查到』列表点名，也会按自己的 severity（除了 info）参与灯色——不需要另外写
    一套平行逻辑。真正跑过但查询失败的行已经是 verdict='error'，这里只处理『压根没有这一行』
    的情况，不会覆盖已存在的行（用 setdefault 的写法：cid 已存在就跳过）。
    """
    merged = dict(results_today_by_id)
    for c in checks:
        cid = c["id"]
        if cid in merged:
            continue
        merged[cid] = {
            "check_id": cid,
            "severity": c.get("severity", "warn"),
            "verdict": "error",
            "value": None,
            "calibrated": c.get("calibrated", True),
            "error_message": "contract 里有这条检查，但今天 audit_results 里没有这一行（检查没跑，不是查出来是 0）",
            "why": c.get("why"),
        }
    return merged


def summarize_watchdog_rules(checks, results_today_by_id, checks_by_id):
    """把 16 条老告警规则（source=watchdog）折成⑥段开头一句总述：今天共报了多少项、
    有几条规则没评估成（必须逐条点名，不许折叠成 0——那会把『规则本身跑挂了』悄悄藏起来）。

    ⚠️ 例外：**全部**规则都没评估成时不逐条念 16 个名字——那不是「这几条规则坏了」，
    是「老告警这整层今天压根没跑」，一句话就说清楚，念名单反而埋没了这个更大的信号。
    """
    watchdog_ids = [c["id"] for c in checks if c.get("source") == "watchdog"]
    if not watchdog_ids:
        return None
    total_hits = 0
    failed_names = []
    for cid in watchdog_ids:
        row = results_today_by_id.get(cid)
        if row is None:
            failed_names.append(checks_by_id.get(cid, {}).get("name", cid))
            continue
        if row.get("verdict") == "error":
            failed_names.append(checks_by_id.get(cid, {}).get("name", cid))
            continue
        if row.get("value") is not None:
            total_hits += int(row["value"])
    if len(failed_names) == len(watchdog_ids):
        return f"老告警今天还没有运行结果（{len(watchdog_ids)} 条规则都没有结果）。"
    line = f"老告警 {len(watchdog_ids)} 条规则今天共报 {total_hits} 项，其中 {len(failed_names)} 条规则没评估成"
    if failed_names:
        line += "：" + "、".join(failed_names)
    return line + "。"


def build_digest(checks, results_today, results_yesterday, walkthrough_run, open_issues, last_sent_digest):
    checks_by_id = {c["id"]: c for c in checks}
    names = {c["id"]: c["name"] for c in checks}
    issue_title_names = build_issue_title_names(checks)
    results_today_by_id = index_results(results_today)
    results_yesterday_by_id = index_results(results_yesterday)
    results_today_by_id = merge_missing_as_error(checks, results_today_by_id)

    for cid, row in results_today_by_id.items():
        check = checks_by_id.get(cid)
        if check:
            row.setdefault("why", check.get("why"))

    light = compute_traffic_light(results_today_by_id)
    subject = build_subject(light, results_today_by_id, checks_by_id)

    users_rows = section_rows(results_today_by_id, results_yesterday_by_id, names, SECTION_USERS)
    experience_rows = section_rows(results_today_by_id, results_yesterday_by_id, names, SECTION_EXPERIENCE)
    supply_rows = section_rows(results_today_by_id, results_yesterday_by_id, names, SECTION_SUPPLY)
    fake_green_rows = section_rows(results_today_by_id, results_yesterday_by_id, names, SECTION_FAKE_GREEN)

    walkthrough_metrics = (walkthrough_run or {}).get("metrics") or {}
    issues_by_type = walkthrough_metrics.get("issues_by_type") or {}
    walkthrough_issue_summary = summarize_walkthrough_issues(issues_by_type)

    newly_broken = find_newly_broken(results_today_by_id, results_yesterday_by_id, names)
    recent_issues = [
        i for i in open_issues
        if _issue_age_hours(i) is not None and _issue_age_hours(i) <= 24
    ]

    old_issues_sorted = order_old_issues(open_issues)

    action_items = build_action_items(results_today_by_id, checks_by_id)

    open_issue_count = len(open_issues)
    subject = subject + f" · 待清账{open_issue_count}项"

    integrity_lines = _integrity_lines(checks, results_today_by_id, last_sent_digest)
    watchdog_summary = summarize_watchdog_rules(checks, results_today_by_id, checks_by_id)
    if watchdog_summary:
        watchdog_summary = _cap_line_length(watchdog_summary)

    text_lines = [subject, ""]
    text_lines.append("① 用户")
    text_lines.extend(render_rows_text(users_rows))
    text_lines.append("")
    text_lines.append("② 用户体验")
    text_lines.extend(render_rows_text(experience_rows))
    if walkthrough_issue_summary:
        text_lines.append("走查发现的问题（按人数归并）：")
        for n, label in walkthrough_issue_summary:
            text_lines.append(f"  · {label}：{n} 人")
    text_lines.append("")
    text_lines.append("③ 供给（在招岗位）")
    text_lines.extend(render_rows_text(supply_rows))
    text_lines.append("")
    text_lines.append("④ 假绿体检（报成功但没有真产出的抓取来源）")
    text_lines.extend(render_rows_text(fake_green_rows))
    text_lines.append("")
    text_lines.append("⑤ 今天新出的问题")
    if newly_broken or recent_issues:
        for item in newly_broken:
            text_lines.append(f"  · {item['name']}：昨天还正常，今天不正常了。{item['why']}")
        for issue in recent_issues:
            text_lines.append(f"  · #{issue.get('number')} {humanize_issue_title(issue.get('title'), issue_title_names)}（24 小时内新开）")
    else:
        text_lines.append("  没有。")
    text_lines.append("")
    text_lines.append(f"⑥ 老问题清账（共 {len(old_issues_sorted)} 项，按拖了多久排序，全列不截断）")
    if watchdog_summary:
        text_lines.append(f"  {watchdog_summary}")
    if old_issues_sorted:
        for issue in old_issues_sorted:
            days = _issue_age_hours(issue)
            days_txt = f"{days / 24:.0f}天" if days is not None else "未知天数"
            text_lines.append(f"  · #{issue.get('number')} {humanize_issue_title(issue.get('title'), issue_title_names)}（拖了{days_txt}，{comment_count(issue)}条评论）")
    else:
        text_lines.append("  没有未解决的老问题。")
    text_lines.append("")
    text_lines.append("⑦【今天建议你做的事】")
    if action_items:
        for i, item in enumerate(action_items, 1):
            text_lines.append(f"  {i}. {item}")
    else:
        text_lines.append("  今天没有需要你处理的事。")
    text_lines.append("")
    text_lines.append("⑧ 数据完整性声明")
    text_lines.extend(f"  · {line}" for line in integrity_lines)

    # 最终硬兜底：不管上面哪段忘了处理，任何一行超过 300 字符都在这里截断——
    # 本次返工的诱因就是没有这道兜底，comments 对象列表能一路塞到单行 4 万字符。
    text = "\n".join(_cap_line_length(line) for line in text_lines)
    html = _to_html(subject, users_rows, experience_rows, supply_rows, fake_green_rows,
                     walkthrough_issue_summary, newly_broken, recent_issues, old_issues_sorted,
                     action_items, integrity_lines, watchdog_summary, issue_title_names)
    return {"subject": subject, "text": text, "html": html, "light": light}


def _issue_age_hours(issue):
    try:
        created = datetime.fromisoformat(str(issue.get("createdAt")).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600


def _esc(text):
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _rows_html(rows):
    if not rows:
        return "<p style='color:#888'>没有数据</p>"
    items = []
    for row in rows:
        icon = {"ok": "✅", "breach": "⚠️", "error": "❓"}.get(row["verdict"], "❓")
        why_html = ""
        if row["why"]:
            why_text = _esc(row["why"].strip())
            why_html = f'<br><span style="color:#666;font-size:13px">{why_text}</span>'
        items.append(
            f"<li>{icon} {_esc(row['name'])}：<b>{_esc(row['shown'])}</b>"
            f"{_esc(row['delta'])}{_esc(row['calibrated_tag'])}{why_html}</li>"
        )
    return "<ul style='padding-left:18px;line-height:1.7'>" + "".join(items) + "</ul>"


def _to_html(subject, users_rows, experience_rows, supply_rows, fake_green_rows,
             walkthrough_issue_summary, newly_broken, recent_issues, old_issues_sorted,
             action_items, integrity_lines, watchdog_summary=None, issue_title_names=None):
    walkthrough_html = ""
    if walkthrough_issue_summary:
        walkthrough_html = "<p><b>走查发现的问题：</b></p><ul style='padding-left:18px'>" + "".join(
            f"<li>{_esc(label)}：{n} 人</li>" for n, label in walkthrough_issue_summary
        ) + "</ul>"

    new_html = "<p>没有。</p>"
    if newly_broken or recent_issues:
        li = [f"<li>{_esc(x['name'])}：昨天还正常，今天不正常了。{_esc(x.get('why',''))}</li>" for x in newly_broken]
        li += [f"<li>#{issue.get('number')} {_esc(humanize_issue_title(issue.get('title'), issue_title_names))}（24 小时内新开）</li>" for issue in recent_issues]
        new_html = "<ul style='padding-left:18px'>" + "".join(li) + "</ul>"

    old_html_prefix = f"<p>{_esc(watchdog_summary)}</p>" if watchdog_summary else ""
    old_html = old_html_prefix + "<p>没有未解决的老问题。</p>" if not old_issues_sorted else old_html_prefix
    if old_issues_sorted:
        li = []
        for issue in old_issues_sorted:
            hrs = _issue_age_hours(issue)
            days_txt = f"{hrs/24:.0f}天" if hrs is not None else "未知天数"
            li.append(f"<li>#{issue.get('number')} {_esc(humanize_issue_title(issue.get('title'), issue_title_names))}（拖了{days_txt}，{comment_count(issue)}条评论）</li>")
        old_html += "<ul style='padding-left:18px'>" + "".join(li) + "</ul>"

    action_html = "<p>今天没有需要你处理的事。</p>"
    if action_items:
        action_html = "<ol style='padding-left:18px'>" + "".join(f"<li>{_esc(x)}</li>" for x in action_items) + "</ol>"

    integrity_html = "<ul style='padding-left:18px;color:#666;font-size:13px'>" + "".join(
        f"<li>{_esc(line)}</li>" for line in integrity_lines
    ) + "</ul>"

    return f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,PingFang SC,Microsoft YaHei,sans-serif;color:#222;max-width:640px;margin:0 auto;padding:16px">
<h2 style="font-size:18px">{_esc(subject)}</h2>
<h3>① 用户</h3>{_rows_html(users_rows)}
<h3>② 用户体验</h3>{_rows_html(experience_rows)}{walkthrough_html}
<h3>③ 供给（在招岗位）</h3>{_rows_html(supply_rows)}
<h3>④ 假绿体检</h3>{_rows_html(fake_green_rows)}
<h3>⑤ 今天新出的问题</h3>{new_html}
<h3>⑥ 老问题清账</h3>{old_html}
<h3 style="color:#b25a00">⑦ 今天建议你做的事</h3>{action_html}
<h3>⑧ 数据完整性声明</h3>{integrity_html}
</body></html>"""


# ---------------------------------------------------------------------------
# 发信
# ---------------------------------------------------------------------------

def send_via_resend(api_key, to_addr, subject, text, html):
    payload = json.dumps({
        "from": "职达晨报 <noreply@myjobradar.top>",
        "to": [to_addr],
        "subject": subject,
        "text": text,
        "html": html,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "status": resp.status, "id": body.get("id")}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        return {"ok": False, "status": exc.code, "error": detail}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": None, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    checks = _audit_runner.load_contract()
    conn = _audit_runner.connect("supabase")

    today = datetime.now(SHANGHAI).date()
    yesterday = today - timedelta(days=1)

    results_today = fetch_audit_results(conn, today.isoformat())
    results_yesterday = fetch_audit_results(conn, yesterday.isoformat())
    walkthrough_run = fetch_latest_ops_run(conn, "ux_walkthrough")
    last_sent_digest = fetch_latest_sent_digest(conn)
    open_issues = fetch_open_issues()

    digest = build_digest(checks, results_today, results_yesterday, walkthrough_run, open_issues, last_sent_digest)

    api_key = os.environ.get("RESEND_API_KEY")
    to_addr = os.environ.get("DIGEST_TO")
    dry_run = args.dry_run or not api_key or not to_addr

    started = datetime.now(timezone.utc)
    if dry_run:
        if not api_key:
            print("未发送：缺 RESEND_API_KEY")
        if not to_addr:
            print("未发送：缺 DIGEST_TO")
        print(f"===== 主题 =====\n{digest['subject']}\n")
        print(f"===== 正文 =====\n{digest['text']}")
        send_result = {"ok": True, "status": "dry_run", "id": None}
        run_status = "success"
    else:
        send_result = send_via_resend(api_key, to_addr, digest["subject"], digest["text"], digest["html"])
        run_status = "success" if send_result.get("ok") else "failed"

    if _ops_runs is not None:
        try:
            import supabase as _supabase_pkg  # noqa: F401
            from supabase import create_client
            sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
            # mode 是权威字段——「上一封晨报是否送达」（fetch_latest_sent_digest）只认
            # mode == "sent" 的行，dry-run 写的行 mode 必须是 "dry_run"，绝不能被误读成送达。
            metrics = {
                "mode": "dry_run" if dry_run else "sent",
                "sent": not dry_run,
                "dry_run": dry_run,
                "resend_status": send_result.get("status"),
                "resend_id": send_result.get("id"),
                "light": digest["light"],
            }
            if not dry_run and not send_result.get("ok") and send_result.get("error"):
                metrics["error"] = _audit_runner._redact(str(send_result["error"]))  # noqa: SLF001
            _ops_runs.record_ops_run(
                sb, "morning_digest", metrics,
                status=run_status,
                started_at=started,
                finished_at=datetime.now(timezone.utc),
            )
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[morning-digest] ops_runs 台账写入失败: {type(exc).__name__}\n")

    if not send_result.get("ok"):
        print(f"::error::晨报发送失败: {send_result.get('error')}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
