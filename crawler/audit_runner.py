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
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

SHANGHAI = ZoneInfo("Asia/Shanghai")
CONTRACT_PATH = Path(__file__).with_name("audit_contract.yaml")

LAYERS = ("pipeline", "data", "experience")
SEVERITIES = ("info", "warn", "critical")
DATABASES = ("jobs", "supabase")
REQUIRED_TEXT = ("id", "name", "layer", "db", "owner", "sql", "normal", "severity", "why", "action")
DEFAULT_TIMEOUT_S = 120
ERROR_MESSAGE_MAX = 300

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
        for field in REQUIRED_TEXT:
            if not isinstance(c.get(field), str) or not c[field].strip():
                raise ValueError(f"检查项 {cid!r} 缺字段 {field}")
        if cid in seen:
            raise ValueError(f"检查项 id 重复: {cid}")
        seen.add(cid)
        if c["layer"] not in LAYERS:
            raise ValueError(f"{cid}: layer 只能是 {LAYERS}")
        if c["severity"] not in SEVERITIES:
            raise ValueError(f"{cid}: severity 只能是 {SEVERITIES}")
        if c["db"] not in DATABASES:
            raise ValueError(f"{cid}: db 只能是 {DATABASES}")
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


def _query_scalar(conn, sql, timeout_s):
    cur = conn.cursor()
    try:
        cur.execute("begin transaction read only")
        try:
            cur.execute(f"set local statement_timeout = '{int(timeout_s)}s'")
            cur.execute(sql)
            return cur.fetchone()
        finally:
            cur.execute("rollback")
    finally:
        cur.close()


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
    row["duration_ms"] = int((time.monotonic() - started) * 1000)
    return row


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
   measured_at, error_message, duration_ms)
values
  (%(check_id)s, %(run_date)s, %(layer)s, %(severity)s, %(value)s, %(normal)s, %(verdict)s,
   %(calibrated)s, %(measured_at)s, %(error_message)s, %(duration_ms)s)
on conflict (check_id, run_date) do update set
  layer = excluded.layer, severity = excluded.severity, value = excluded.value,
  normal = excluded.normal, verdict = excluded.verdict, calibrated = excluded.calibrated,
  measured_at = excluded.measured_at, error_message = excluded.error_message,
  duration_ms = excluded.duration_ms
"""


def write_results(conn, results):
    """同一天重跑 = 覆盖当天那行（最后一次测量为准）；一天一行，历史才能直接画趋势。"""
    cur = conn.cursor()
    try:
        for row in results:
            cur.execute(_UPSERT_SQL, row)
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

    checks = load_contract()
    if args.layer:
        checks = [c for c in checks if c["layer"] == args.layer]
    results = run_all(checks, connect)
    print(render(results, checks))
    tally = {v: sum(1 for r in results if r["verdict"] == v) for v in ("ok", "breach", "error")}
    print(f"[audit] checks={len(results)} ok={tally['ok']} breach={tally['breach']} error={tally['error']}")
    if tally["error"]:
        print(f"::warning::audit 有 {tally['error']} 条检查没查到（已按 error 落库，不是 0）")

    if args.dry_run:
        print("[audit] dry-run：未写 audit_results")
        return 0
    written = False
    try:
        ledger = connect("supabase")
        written = write_results(ledger, results) == len(results)
    except Exception as exc:  # noqa: BLE001
        print(f"::error::audit_results 写入失败: {_redact(f'{type(exc).__name__}: {exc}')}")
    return exit_code(written)


if __name__ == "__main__":
    sys.exit(main())
