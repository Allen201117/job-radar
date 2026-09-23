"""结构性审计执行器：把 audit_contract.yaml 里声明的「正常长什么样」每天量一遍，逐条写进 audit_results。

三条硬规矩（别改回去）：
  1. 查询失败 → verdict='error'、value=None。不是跳过，不是 0。「真的是 0」和「没查到」必须分得开。
  2. 每天每条都写，ok 也写 —— 这张表本身就是历史（在招总量此前一天历史都没有，阈值因此定不出来）。
  3. 台账写不进去 → 进程非零退出。查得再好、没落库 = 没查。

检查项 SQL 一律只读：每条跑在 `begin transaction read only` 里并且无条件 rollback。
"""
import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

SHANGHAI = ZoneInfo("Asia/Shanghai")
CONTRACT_PATH = Path(__file__).with_name("audit_contract.yaml")

LAYERS = ("pipeline", "data", "experience")
SEVERITIES = ("info", "warn", "critical")
DATABASES = ("jobs", "supabase")
SOURCES = ("sql", "watchdog")
# source=sql（默认，老检查项不用写这个字段）：本文件真的跑 SQL 去量。
# source=watchdog：这条检查的「测量」发生在 crawler/ops_watchdog.py 里（老告警规则本来就在跑，
#   只是结果此前只落 GitHub Issue、没进 audit_results 这张趋势表）——本文件**不执行**它，
#   只负责校验它声明得对不对；`rule` 是 ops_watchdog.RULE_TITLES 里的字母。
REQUIRED_TEXT_SQL = ("id", "name", "layer", "db", "owner", "sql", "normal", "severity", "why", "action")
REQUIRED_TEXT_WATCHDOG = ("id", "name", "layer", "owner", "rule", "normal", "severity", "why", "action")
DEFAULT_TIMEOUT_S = 120
ERROR_MESSAGE_MAX = 300
# detail_sql（可选，只给 source=sql）：数值之外再取「具体是哪几处」，返回 title / key 两列、每行一处，
# 落进 detail.findings——与 ops_watchdog 桥接行同形，晨报与 repair_queue 共用一套读法。条数上限同桥接。
DETAIL_MAX_FINDINGS = 30
DETAIL_TITLE_MAX = 200

# 外部心跳（Healthchecks.io）：执行器自己也可能没跑起来（CI 挂了 / cron 没触发），
# 那种情况只靠台账查不出来——台账本身就没被写。这套心跳独立于台账，是「进程还活着吗」的旁路信号。
_HEARTBEAT_SUFFIX = {"start": "/start", "success": "", "fail": "/fail"}
_HEARTBEAT_TIMEOUT_S = 10
_HEARTBEAT_MAX_ATTEMPTS = 3  # 首次 + 最多重试 2 次
_HEARTBEAT_BODY_MAX = 200

_NUM = r"-?\d+(?:\.\d+)?"
_CMP_RE = re.compile(rf"^(<=|>=|==|!=|<|>)\s*({_NUM})$")
_BETWEEN_RE = re.compile(rf"^between\s+({_NUM})\s+and\s+({_NUM})$", re.I)
_OPS = {
    "<=": lambda v, x: v <= x, "<": lambda v, x: v < x,
    ">=": lambda v, x: v >= x, ">": lambda v, x: v > x,
    "==": lambda v, x: v == x, "!=": lambda v, x: v != x,
}
# 错误信息会落库、进邮件，而仓库与 issue 是公开的：连接串 / IP / 主机一律抹掉。
_REDACTIONS = (
    (re.compile(r"postgres(?:ql)?://\S+", re.I), "<dsn>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b(?::\d+)?"), "<host>"),
    (re.compile(r'host\s*"?[^",\s]+"?', re.I), "host <host>"),
)


def parse_normal(expr):
    """`<= 0.10` / `== 0` / `between 5 and 9` → 判定函数。认不出来就抛错：宁可红，也不许默默放行。"""
    text = str(expr or "").strip()
    m = _CMP_RE.match(text)
    if m:
        op, bound = _OPS[m.group(1)], float(m.group(2))
        return lambda value: op(value, bound)
    m = _BETWEEN_RE.match(text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return lambda value: lo <= value <= hi
    raise ValueError(f"看不懂的 normal 表达式: {text!r}")


def evaluate_normal(value, expr):
    return bool(parse_normal(expr)(float(value)))


def validate_contract(checks):
    seen = set()
    for c in checks:
        cid = c.get("id")
        source = c.get("source", "sql")
        if source not in SOURCES:
            raise ValueError(f"{cid}: source 只能是 {SOURCES}")
        required = REQUIRED_TEXT_WATCHDOG if source == "watchdog" else REQUIRED_TEXT_SQL
        for field in required:
            if not isinstance(c.get(field), str) or not c[field].strip():
                raise ValueError(f"检查项 {cid!r} 缺字段 {field}")
        if cid in seen:
            raise ValueError(f"检查项 id 重复: {cid}")
        seen.add(cid)
        if c["layer"] not in LAYERS:
            raise ValueError(f"{cid}: layer 只能是 {LAYERS}")
        if c["severity"] not in SEVERITIES:
            raise ValueError(f"{cid}: severity 只能是 {SEVERITIES}")
        if source == "sql" and c["db"] not in DATABASES:
            raise ValueError(f"{cid}: db 只能是 {DATABASES}")
        if "detail_sql" in c:
            if source != "sql":
                raise ValueError(f"{cid}: 只有 source=sql 的检查项能带 detail_sql")
            if not isinstance(c["detail_sql"], str) or not c["detail_sql"].strip():
                raise ValueError(f"{cid}: detail_sql 必须是非空字符串")
        parse_normal(c["normal"])
    return checks


def load_contract(path=CONTRACT_PATH):
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return validate_contract(list(doc.get("checks") or []))


def _redact(message):
    text = " ".join(str(message).split())
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text[:ERROR_MESSAGE_MAX]


def _default_opener(request, timeout):
    return urllib.request.urlopen(request, timeout=timeout)


def ping_heartbeat(outcome, url=None, opener=None, body=None):
    """给 Healthchecks.io 发一次心跳。outcome ∈ start/success/fail。

    url 缺失只是「没配」，不是错误——打印一行说明后跳过（返回 "skipped"），
    但绝不能一声不响地什么都不做。发送失败只记 warning、绝不影响进程退出码
    （它是旁路信号，不是台账本身）；异常信息只打类名，ping URL 本身等同密钥、
    一律不许出现在任何日志里。
    """
    if outcome not in _HEARTBEAT_SUFFIX:
        raise ValueError(f"未知的心跳 outcome: {outcome!r}")
    if url is None:
        url = os.environ.get("HEALTHCHECKS_PING_URL")
    if not url:
        print("[audit] 未配置 HEALTHCHECKS_PING_URL，已跳过外部心跳")
        return "skipped"

    target = url.rstrip("/") + _HEARTBEAT_SUFFIX[outcome]
    opener = opener or _default_opener
    data = None
    if outcome == "fail" and body:
        data = _redact(body)[:_HEARTBEAT_BODY_MAX].encode("utf-8")

    last_exc = None
    for _ in range(_HEARTBEAT_MAX_ATTEMPTS):
        try:
            request = urllib.request.Request(target, data=data, method="POST" if data else "GET")
            opener(request, timeout=_HEARTBEAT_TIMEOUT_S)
            return "sent"
        except Exception as exc:  # noqa: BLE001 - 心跳失败绝不能让审计本身跟着炸
            last_exc = exc
    print(f"::warning::外部心跳发送失败: {type(last_exc).__name__}")
    return "failed"


def _query_read_only(conn, sql, timeout_s, fetch):
    cur = conn.cursor()
    try:
        cur.execute("begin transaction read only")
        try:
            cur.execute(f"set local statement_timeout = '{int(timeout_s)}s'")
            cur.execute(sql)
            return fetch(cur)
        finally:
            cur.execute("rollback")
    finally:
        cur.close()


def _query_scalar(conn, sql, timeout_s):
    return _query_read_only(conn, sql, timeout_s, lambda cur: cur.fetchone())


def _query_findings(conn, sql, timeout_s):
    """detail_sql → [{"title", "key"}]。列按名字取（不按位置），少了 title/key 直接抛错——
    明细列写错时宁可记一条取明细失败，也不许把错位的列当成人话念进邮件。"""
    def fetch(cur):
        cols = [d[0] for d in (cur.description or [])]
        missing = {"title", "key"} - set(cols)
        if missing:
            raise ValueError(f"detail_sql 缺列: {sorted(missing)}")
        ti, ki = cols.index("title"), cols.index("key")
        rows = cur.fetchmany(DETAIL_MAX_FINDINGS)
        return [{"title": str(r[ti])[:DETAIL_TITLE_MAX], "key": None if r[ki] is None else str(r[ki])}
                for r in rows]
    return _query_read_only(conn, sql, timeout_s, fetch)


def run_check(check, get_conn, now=None):
    measured = now or datetime.now(timezone.utc)
    row = {
        "check_id": check["id"],
        "run_date": measured.astimezone(SHANGHAI).date().isoformat(),
        "layer": check["layer"],
        "severity": check["severity"],
        "value": None,
        "normal": check["normal"],
        "verdict": "error",
        "calibrated": bool(check.get("calibrated", True)),
        "measured_at": measured.astimezone(timezone.utc).isoformat(),
        "error_message": None,
        "duration_ms": None,
        "detail": None,  # 没带 detail_sql 的 SQL 类检查恒为 None：数值本身就是全部信息
    }
    started = time.monotonic()
    try:
        conn = get_conn(check["db"])
        fetched = _query_scalar(conn, check["sql"], check.get("timeout_s", DEFAULT_TIMEOUT_S))
        if fetched is None or fetched[0] is None:
            raise ValueError("查询没有返回数值（空结果不等于 0）")
        value = float(fetched[0])
        row["value"] = value
        row["verdict"] = "ok" if evaluate_normal(value, check["normal"]) else "breach"
    except Exception as exc:  # noqa: BLE001 - 失败要变成一行 error 台账，而不是中断其余检查
        row["value"] = None
        row["error_message"] = _redact(f"{type(exc).__name__}: {exc}")
    if check.get("detail_sql") and row["value"] is not None:
        row["detail"] = _collect_detail(check, conn)
    row["duration_ms"] = int((time.monotonic() - started) * 1000)
    return row


def _collect_detail(check, conn):
    """明细是数值的附件，不是数值本身：取明细失败**不改** value / verdict（那样会把一个量到了的数
    记成「没查到」），但也不许静默——失败原因落在 detail.error 里，晨报/排查看得见。"""
    try:
        findings = _query_findings(conn, check["detail_sql"], check.get("timeout_s", DEFAULT_TIMEOUT_S))
    except Exception as exc:  # noqa: BLE001
        return {"error": _redact(f"{type(exc).__name__}: {exc}")}
    return {"findings": findings} if findings else None


def sql_checks(checks):
    """source=watchdog 的检查项不由本文件执行——它们的「测量」发生在 ops_watchdog.py，
    本文件跑起来时如果混进这些检查项去执行 SQL 会直接因为没有 `sql`/`db` 字段而崩。
    main() 只让本函数返回的子集真正跑 _query_scalar。"""
    return [c for c in checks if c.get("source", "sql") == "sql"]


def run_all(checks, connect):
    """每个库只建一次连接；建连失败也缓存，该库的每条检查各自落一行 error。"""
    cache = {}

    def get_conn(db):
        if db not in cache:
            try:
                cache[db] = connect(db)
            except Exception as exc:  # noqa: BLE001
                cache[db] = exc
        cached = cache[db]
        if isinstance(cached, Exception):
            raise cached
        if getattr(cached, "closed", 0):
            cache.pop(db)
            return get_conn(db)
        return cached

    return [run_check(c, get_conn) for c in checks]


_UPSERT_SQL = """
insert into public.audit_results
  (check_id, run_date, layer, severity, value, normal, verdict, calibrated,
   measured_at, error_message, duration_ms, detail)
values
  (%(check_id)s, %(run_date)s, %(layer)s, %(severity)s, %(value)s, %(normal)s, %(verdict)s,
   %(calibrated)s, %(measured_at)s, %(error_message)s, %(duration_ms)s, %(detail)s)
on conflict (check_id, run_date) do update set
  layer = excluded.layer, severity = excluded.severity, value = excluded.value,
  normal = excluded.normal, verdict = excluded.verdict, calibrated = excluded.calibrated,
  measured_at = excluded.measured_at, error_message = excluded.error_message,
  duration_ms = excluded.duration_ms, detail = excluded.detail
"""


def write_results(conn, results):
    """同一天重跑 = 覆盖当天那行（最后一次测量为准）；一天一行，历史才能直接画趋势。"""
    import psycopg2.extras
    cur = conn.cursor()
    try:
        for row in results:
            payload = dict(row)
            if payload.get("detail") is not None:
                payload["detail"] = psycopg2.extras.Json(payload["detail"])
            cur.execute(_UPSERT_SQL, payload)
    finally:
        cur.close()
    return len(results)


def exit_code(written):
    # breach / error 是「发现」，由邮件与告警消费，不让 CI 红 —— 否则又多一个天天红、没人看的 workflow。
    return 0 if written else 1


def connect(db):
    import psycopg2
    if db == "jobs":
        import jobs_db
        return jobs_db.get_conn()
    dsn = os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        raise RuntimeError("SUPABASE_DB_URL 未配置")
    conn = psycopg2.connect(dsn, connect_timeout=15)
    conn.autocommit = True
    return conn


def render(results, checks):
    names = {c["id"]: c["name"] for c in checks}
    icon = {"ok": "✅", "breach": "🟡", "error": "❓"}
    lines = []
    for r in results:
        shown = "没查到" if r["value"] is None else f"{r['value']:g}"
        tail = f"  ← {r['error_message']}" if r["error_message"] else ""
        mark = "" if r["calibrated"] else "（待校准）"
        lines.append(f"{icon[r['verdict']]} {names[r['check_id']]}: {shown}  [正常 {r['normal']}]{mark}{tail}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只量不落库")
    parser.add_argument("--layer", choices=LAYERS)
    args = parser.parse_args(argv)

    force_fail = os.environ.get("AUDIT_FORCE_FAIL") == "1"

    if args.dry_run:
        print("[audit] dry-run：不发外部心跳")
    else:
        ping_heartbeat("start")

    try:
        checks = load_contract()
        if args.layer:
            checks = [c for c in checks if c["layer"] == args.layer]
        checks = sql_checks(checks)  # source=watchdog 的检查项由 ops_watchdog.py 自己写，本文件不跑它们
        results = run_all(checks, connect)
        print(render(results, checks))
        tally = {v: sum(1 for r in results if r["verdict"] == v) for v in ("ok", "breach", "error")}
        print(f"[audit] checks={len(results)} ok={tally['ok']} breach={tally['breach']} error={tally['error']}")
        if tally["error"]:
            print(f"::warning::audit 有 {tally['error']} 条检查没查到（已按 error 落库，不是 0）")
        for r in results:
            if (r.get("detail") or {}).get("error"):
                print(f"::warning::audit {r['check_id']} 数值已量到，但明细没取到：{r['detail']['error']}")

        if args.dry_run:
            print("[audit] dry-run：未写 audit_results")
            return 0

        if force_fail:
            print("[audit] 故障演练：AUDIT_FORCE_FAIL=1，本次故意失败（跳过写台账）")
            ping_heartbeat("fail", body="故障演练：AUDIT_FORCE_FAIL=1")
            return exit_code(written=False)

        written = False
        try:
            ledger = connect("supabase")
            written = write_results(ledger, results) == len(results)
        except Exception as exc:  # noqa: BLE001
            print(f"::error::audit_results 写入失败: {_redact(f'{type(exc).__name__}: {exc}')}")

        if written:
            ping_heartbeat("success")
        else:
            ping_heartbeat("fail", body="audit_results 写入失败")
        return exit_code(written)
    except Exception:
        # 走到这里说明上面某处有未捕获异常（不是台账写失败、也不是查询失败——那两类各自已经
        # 被内层 try 收敛成 error 行/written=False）。心跳照实发一次 fail，异常本身必须 re-raise，
        # 不能吞掉——否则退出码会被这层 except 悄悄改成「正常返回」。
        if not args.dry_run:
            ping_heartbeat("fail", body="audit_runner 主流程抛出未捕获异常")
        raise


if __name__ == "__main__":
    sys.exit(main())
