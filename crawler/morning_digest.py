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
    "exp.job_clicks_yesterday", "exp.saved_yesterday", "exp.applied_yesterday",
    "exp.search_zero_result_rate_7d", "exp.search_slow_rate_7d",
    "exp.ux_walkthrough_zero_shown", "exp.ux_walkthrough_issue_count",
    "exp.ux_walkthrough_direction_ok_avg", "exp.ux_walkthrough_insight_coverage_avg",
    "exp.ux_walkthrough_campus_healthy_ratio_avg", "exp.dead_click_unknown_rate",
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
    """有昨天数据才显示变化；没有就什么都不写（不许编一个假变化）。"""
    if today_value is None or yesterday_value is None:
        return ""
    delta = today_value - yesterday_value
    if is_ratio_check(check_id):
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        return f"（较昨天{arrow}{abs(delta) * 100:.1f}个百分点）"
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    return f"（较昨天{arrow}{format_number(abs(delta))}）"


# ---------------------------------------------------------------------------
# 纯函数：灯色
# ---------------------------------------------------------------------------

def compute_traffic_light(results_by_id):
    """🔴 = 有 critical breach/error；🟡 = 有 warn breach 或有「没查到」；🟢 = 全 ok。"""
    has_critical_bad = any(
        r["severity"] == "critical" and r["verdict"] in ("breach", "error")
        for r in results_by_id.values()
    )
    if has_critical_bad:
        return "🔴"
    has_warn_bad_or_error = any(
        r["verdict"] == "error" or (r["verdict"] == "breach" and r["severity"] == "warn")
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
        calibrated_tag = "" if r.get("calibrated", True) else "（待校准）"
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


def build_action_items(results_today_by_id, checks_by_id, limit=5):
    """从 breach 项的 action 字段取，critical 在前，最多 limit 条。"""
    items = []
    for cid, row in results_today_by_id.items():
        if row["verdict"] not in ("breach", "error"):
            continue
        check = checks_by_id.get(cid) or {}
        action = check.get("action")
        if not action:
            continue
        items.append((0 if row["severity"] == "critical" else 1, check.get("name", cid), action))
    items.sort(key=lambda x: x[0])
    return [f"{name}：{action}" for _sev, name, action in items[:limit]]


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


def fetch_open_issues():
    """gh issue list；CI 里靠 GH_TOKEN env，本地没配就返回空列表（不当作失败）。"""
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


def _integrity_lines(all_checks, results_today_by_id, last_digest):
    total = len(all_checks)
    error_ids = [cid for cid, r in results_today_by_id.items() if r["verdict"] == "error"]
    calibrated_false_names = [c["name"] for c in all_checks if not c.get("calibrated", True)]
    lines = [f"今天一共跑了 {total} 项检查，{len(error_ids)} 项没查到。"]
    if error_ids:
        names = {c["id"]: c["name"] for c in all_checks}
        lines.append("没查到的是：" + "、".join(names.get(cid, cid) for cid in error_ids))
    if calibrated_false_names:
        lines.append(f"有 {len(calibrated_false_names)} 项阈值还是拍的、没有历史数据校准过，标了「待校准」的都是。")
    if last_digest:
        status = last_digest.get("status")
        sent_ok = isinstance(status, str) and status == "success"
        lines.append("上一封晨报" + ("已送达。" if sent_ok else f"状态是「{status}」，可能没送达，留意一下有没有收到重复提醒。"))
    else:
        lines.append("上一封晨报没有台账记录（可能是第一次发，或者查询失败）。")
    lines.extend(FIXED_DISCLAIMERS)
    return lines


def build_digest(checks, results_today, results_yesterday, walkthrough_run, open_issues, last_digest):
    checks_by_id = {c["id"]: c for c in checks}
    names = {c["id"]: c["name"] for c in checks}
    results_today_by_id = index_results(results_today)
    results_yesterday_by_id = index_results(results_yesterday)

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

    integrity_lines = _integrity_lines(checks, results_today_by_id, last_digest)

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
            text_lines.append(f"  · #{issue.get('number')} {issue.get('title')}（24 小时内新开）")
    else:
        text_lines.append("  没有。")
    text_lines.append("")
    text_lines.append(f"⑥ 老问题清账（共 {len(old_issues_sorted)} 项，按拖了多久排序，全列不截断）")
    if old_issues_sorted:
        for issue in old_issues_sorted:
            days = _issue_age_hours(issue)
            days_txt = f"{days / 24:.0f}天" if days is not None else "未知天数"
            text_lines.append(f"  · #{issue.get('number')} {issue.get('title')}（拖了{days_txt}，{issue.get('comments', 0)}条评论）")
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

    text = "\n".join(text_lines)
    html = _to_html(subject, users_rows, experience_rows, supply_rows, fake_green_rows,
                     walkthrough_issue_summary, newly_broken, recent_issues, old_issues_sorted,
                     action_items, integrity_lines)
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
             action_items, integrity_lines):
    walkthrough_html = ""
    if walkthrough_issue_summary:
        walkthrough_html = "<p><b>走查发现的问题：</b></p><ul style='padding-left:18px'>" + "".join(
            f"<li>{_esc(label)}：{n} 人</li>" for n, label in walkthrough_issue_summary
        ) + "</ul>"

    new_html = "<p>没有。</p>"
    if newly_broken or recent_issues:
        li = [f"<li>{_esc(x['name'])}：昨天还正常，今天不正常了。{_esc(x.get('why',''))}</li>" for x in newly_broken]
        li += [f"<li>#{issue.get('number')} {_esc(issue.get('title'))}（24 小时内新开）</li>" for issue in recent_issues]
        new_html = "<ul style='padding-left:18px'>" + "".join(li) + "</ul>"

    old_html = "<p>没有未解决的老问题。</p>"
    if old_issues_sorted:
        li = []
        for issue in old_issues_sorted:
            hrs = _issue_age_hours(issue)
            days_txt = f"{hrs/24:.0f}天" if hrs is not None else "未知天数"
            li.append(f"<li>#{issue.get('number')} {_esc(issue.get('title'))}（拖了{days_txt}，{issue.get('comments',0)}条评论）</li>")
        old_html = "<ul style='padding-left:18px'>" + "".join(li) + "</ul>"

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
    last_digest = fetch_latest_ops_run(conn, "morning_digest")
    open_issues = fetch_open_issues()

    digest = build_digest(checks, results_today, results_yesterday, walkthrough_run, open_issues, last_digest)

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
            _ops_runs.record_ops_run(
                sb, "morning_digest",
                {
                    "sent": not dry_run,
                    "dry_run": dry_run,
                    "resend_status": send_result.get("status"),
                    "resend_id": send_result.get("id"),
                    "light": digest["light"],
                },
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
