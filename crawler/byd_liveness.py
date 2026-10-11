"""比亚迪撤岗核验：官网全量列表 + 逐岗详情接口双条件判死，顺带修「// 被压成 /」的坏链接。

为什么单独一条链（2026-10-11，库里 7,481 个在招岗逐个核过）：
  · 比亚迪撤岗后的详情页是**空壳**：没有岗位名、没有正文，也没有任何「已下线 / 停止招聘」文案
    （页面自己发的 queryDetail 回 code=0 + 字段全空的骨架）。浏览器巡检按文案判死，这种页面只能落
    suspect——375 个真渲染样本里 300 个已撤岗全部判 suspect、0 个判 dead。所以它每天巡、从不下架，
    库里攒了 5,429 个已撤岗（最早 6 月的），占比亚迪在招行数的 73%。
  · 详情链接里的岗位 id 是前端 AES 加密的，光有链接问不了详情接口；官方页面的路由能解，
    一次页面加载解完全部（adapters/byd.decode_detail_urls）。

每行在招岗的处置（逐岗，不抽样）：
  链接解不出 id                    → 不动（keep_undecodable）
  id 在本轮全量列表里               → 在招。链接是老的坏链接 → relink（原地改 jd_url/apply_url，保留行 id；
                                     新链接已被另一行在招岗占用 → 这行是重复，下架）；否则 keep
  id 不在列表 & 详情两轮都读到空骨架 → expire
  id 不在列表 & 详情读到在招 / 判不了 → 不动（宁可漏判不可错杀），单独计数

安全闸（任何一道不过，本轮一行都不下架，进程退出码 2 → workflow 变红）：
  · 源必须存在；列表必须抓全（自报总数 > 0 且对得上；adapter 同一套取数）。
  · 链接解得出 id 的比例 ≥ MIN_DECODED_FRACTION（实测 7,481/7,481）——官方路由变了时不许安静地「0 个要下架」。
  · 近 RECENT_HOURS 小时还被抓到过的行（= 上一两轮的官网列表）这一轮缺席的比例 ≤ MAX_RECENT_ABSENT_FRACTION。
    「自报总数对得上」证明不了列表是全集（两个数出自同一个响应），这道闸拿的是我们自己上一轮的记录。
    113 天抓取史上连续三天撤岗合计最高 11.6%。清存量时放宽的是占比闸，这道不放。
  · 阳性对照：列表里抽 CONTROL_SAMPLE 个在招岗必须全读到在招；阴性对照：不存在的 id 必须读到空骨架。
    逐岗探之前、每探 PROBE_CHUNK 个之后都过一遍——接口中途退化时它对在招岗也可能回空骨架。
  · 「不在列表却读到在招」的行 ≤ MAX_LIVE_UNLISTED_FRACTION（全集对拍时是 0）：多了说明列表不是全集。
  · 判死占比：本轮拟下架 > 在招行数 × --max-expire-fraction（默认 0.3）就不下架；清存量那一次由人显式放宽。
    只被这一道拦下时，在招行的改链接与盖核验时间照做（那是给在招岗修东西），重复行留着不下架。
  · 下架语句自带 last_seen_at < 本轮开始时刻：核验期间又被抓取刷新过的行不动。
  · 默认 dry-run；--apply 才写库。只动 status='active' 的行。
  · 下架与巡检同口径：status=expired + confirmed_closed_at + CLOSED 事件；purge 删行前会立墓碑。

全集对拍（2026-10-11）：不在列表 5,429 行 → 空骨架 5,429；在列表 2,052 行 → 在招 2,052；两个方向反例都是 0。
300 个伪 id 全是空骨架（唯一有值的字段是 collectionStatus）；列表 2,078 个 id 全在招（有值字段 10~13 个，
回带的 id 与所问一致）。

用法：python3 crawler/byd_liveness.py [--apply] [--max-expire-fraction 0.3] [--out report.json]
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
import jobs_db  # noqa: E402
import ops_runs  # noqa: E402
from adapters.byd import DETAIL_URL_PREFIX, BydAdapter, detail_state  # noqa: E402

MODULE = "byd_liveness"
CONTROL_SAMPLE = 8
PROBE_CHUNK = 500
DEFAULT_MAX_EXPIRE_FRACTION = 0.3
MIN_DECODED_FRACTION = 0.95
RECENT_HOURS = 72
MAX_RECENT_ABSENT_FRACTION = 0.2
MAX_LIVE_UNLISTED_FRACTION = 0.01
THREADS = int(os.environ.get("BYD_LIVENESS_THREADS", "8"))
EXIT_BLOCKED = 2


def probe(client, job_id):
    """问一次详情接口 → 'live' / 'gone' / 'unknown'。网络错误和判不了的回答各重试，仍不行 = unknown。"""
    for attempt in range(3):
        try:
            r = client.post(BydAdapter.DETAIL_API, json={"id": job_id, "pageSize": 4})
            try:
                body = r.json()
            except ValueError:
                body = None
            state = detail_state(r.status_code, body, job_id)
            if state != "unknown":
                return state
        except httpx.HTTPError:
            pass
        time.sleep(1.5 * (attempt + 1))
    return "unknown"


def probe_many(probe_fn, job_ids):
    ids = sorted(set(job_ids))
    with ThreadPoolExecutor(THREADS) as ex:
        return dict(zip(ids, ex.map(probe_fn, ids)))


def probe_with_sentinels(job_ids, probe_fn, control_fn, chunk=PROBE_CHUNK):
    """分块探；开头过一遍对照，每块探完再过一遍。任何一遍不过 → (已探到的, False)，这一轮读到的都不算数。"""
    ids = sorted(set(job_ids))
    states = {}
    if not control_fn():
        return states, False
    for start in range(0, len(ids), chunk):
        states.update(probe_many(probe_fn, ids[start:start + chunk]))
        if not control_fn():
            return states, False
    return states, True


def settle_states(first, second):
    """两轮都读到 gone 才是 gone；第一轮读到 live 就是 live；其余一律判不了。"""
    out = {}
    for job_id, state in first.items():
        if state == "live":
            out[job_id] = "live"
        elif state == "gone" and second.get(job_id) == "gone":
            out[job_id] = "gone"
        else:
            out[job_id] = "unknown"
    return out


def plan(rows, decoded, list_ids, states):
    """纯函数。rows=[(行 id, jd_url)]；decoded={jd_url: (岗位 id, 修好的链接或 None)}；
    list_ids=本轮官网全量列表的岗位 id；states={岗位 id: 'gone'/'live'/'unknown'}（只含不在列表的）。
    返回 [(action, 行 id, jd_url, new_url)]。"""
    actions = []
    for row_id, jd_url in rows:
        hit = decoded.get(jd_url)
        if not hit:
            actions.append(("keep_undecodable", row_id, jd_url, None))
            continue
        job_id, fixed_url = hit
        if job_id in list_ids:
            if fixed_url:
                actions.append(("relink", row_id, jd_url, fixed_url))
            else:
                actions.append(("keep", row_id, jd_url, None))
            continue
        state = states.get(job_id, "unknown")
        if state == "gone":
            actions.append(("expire", row_id, jd_url, None))
        elif state == "live":
            actions.append(("keep_live_unlisted", row_id, jd_url, None))
        else:
            actions.append(("keep_unknown", row_id, jd_url, None))
    return actions


def positive_control_ok(list_ids, probe_fn, k=CONTROL_SAMPLE, seed=0):
    """阳性对照：列表里抽 k 个在招岗，必须全读到 live。列表为空 → 无从对照 → False。"""
    ids = sorted(list_ids)
    if not ids:
        return False
    random.Random(seed).shuffle(ids)
    return all(probe_fn(job_id) == "live" for job_id in ids[:k])


def negative_control_ok(list_ids, probe_fn):
    """阴性对照：不存在的 id 必须读到 gone。取 "1" 和「列表最大 id + 1」（与真 id 同位数）。"""
    fakes = ["1"]
    if list_ids:
        fakes.append(str(max(int(i) for i in list_ids) + 1))
    return all(probe_fn(job_id) == "gone" for job_id in fakes)


def decode_blocked_reason(urls, decoded):
    """链接解不出 id 的比例过高 = 官方路由变了 / 页面没起来，这一轮什么都判不了。"""
    ours = [u for u in urls if (u or "").startswith(DETAIL_URL_PREFIX)]
    n = sum(1 for u in ours if u in decoded)
    if urls and n < max(1, len(ours) * MIN_DECODED_FRACTION):
        return f"decode_degraded:{n}/{len(urls)}"
    return None


def recent_absent_blocked_reason(recent_job_ids, list_ids):
    """recent_job_ids = 近 RECENT_HOURS 小时还被抓到过的行解出的岗位 id（上一两轮的官网列表）。
    一个都没有 → 没有参照，不许下架；这一轮缺席的太多 → 这一轮拿到的列表不是全集。"""
    recent = list(recent_job_ids)
    if not recent:
        return "no_recent_reference"
    missing = sum(1 for job_id in recent if job_id not in list_ids)
    if missing > len(recent) * MAX_RECENT_ABSENT_FRACTION:
        return f"recent_absent_too_many:{missing}/{len(recent)}"
    return None


def live_unlisted_blocked_reason(n_live_unlisted, n_rows):
    if n_live_unlisted > n_rows * MAX_LIVE_UNLISTED_FRACTION:
        return f"list_not_full_set:{n_live_unlisted}/{n_rows}"
    return None


def expire_blocked_reason(n_expire, n_active, max_fraction):
    """判死占比闸：超了返回原因，没超返回 None。"""
    if n_expire > 0 and n_expire > n_active * max_fraction:
        return f"too_many:{n_expire}/{n_active}>{max_fraction}"
    return None


def _expire(cur, ids, now, extra_sql="", extra_params=()):
    cur.execute("update jobs set status='expired', confirmed_closed_at=%s, enrich_checked_at=%s "
                "where id = any(%s::uuid[]) and status='active'" + extra_sql + " returning id::text",
                (now, now, ids, *extra_params))
    return [r[0] for r in cur.fetchall()]


def apply_actions(conn, source_id, actions, *, not_seen_since, expire_dups=True):
    """写库：relink 原地改链接（新链接已被另一行在招岗占用 = 这行是重复 → 下架这行）；expire 下架 + CLOSED 事件；
    核实在招的行（keep / relink 成功）盖核验时间。not_seen_since 之后又被抓取刷新过的行不下架。"""
    now = jobs_db._now()
    day = jobs_db._day(now)
    to_expire, dup, verified, closed = [], [], [], []
    relinked = conflicts = n_expired = n_dup = 0
    with conn.cursor() as cur:
        for action, row_id, _url, new_url in actions:
            if action == "relink":
                cur.execute("select id from jobs where status='active' and id <> %s "
                            "and canonical_jd_url = public.canonicalize_jd_url(%s) limit 1", (row_id, new_url))
                if cur.fetchone():
                    dup.append(row_id)
                    continue
                try:
                    cur.execute("update jobs set jd_url=%s, apply_url=%s where id=%s and status='active'",
                                (new_url, new_url, row_id))
                except psycopg2.errors.UniqueViolation:
                    # (company, title, location, jd_url) 的唯一约束不分状态：新链接被一行已下架的旧行占着。
                    # 这一行留着不动、记数；不许让一条改链接把整批下架挡住（autocommit，失败的语句自己回滚）。
                    conflicts += 1
                    continue
                relinked += cur.rowcount
                verified.append(row_id)
            elif action == "expire":
                to_expire.append(row_id)
            elif action == "keep":
                verified.append(row_id)
        if to_expire:
            gone = _expire(cur, to_expire, now, " and last_seen_at < %s", (not_seen_since,))
            n_expired = len(gone)
            closed += gone
        if dup and expire_dups:
            gone = _expire(cur, dup, now)
            n_dup = len(gone)
            closed += gone
        if verified:
            cur.execute("update jobs set enrich_checked_at=%s where id = any(%s::uuid[]) and status='active'",
                        (now, verified))
    jobs_db.record_job_events(conn, [jobs_db.plan_close_event(j, source_id, day) for j in closed])
    return {"relinked": relinked, "expired": n_expired, "dup_expired": n_dup,
            "dup_kept": len(dup) - n_dup, "relink_conflict": conflicts}


def exit_code(report, *, apply):
    """没被拦 → 0。被拦 → 2（CI 变红，要人看）；唯一例外：dry-run 里只被占比闸拦——那只是报数，不算失败。"""
    reasons = [f"{r.get('company')}={r['blocked']}" for r in report if r.get("blocked")]
    if not report:
        reasons = ["没有 enabled 的 byd 源"]
    if not reasons:
        return 0
    print(f"::warning::[byd-liveness] 本轮被安全闸拦下，没有下架任何岗：{'; '.join(reasons)}", flush=True)
    only_ratio = bool(report) and all(str(r["blocked"]).startswith("too_many") for r in report if r.get("blocked"))
    return 0 if (only_ratio and not apply) else EXIT_BLOCKED


def load_active_rows(conn, source_id):
    """[(行 id, jd_url, 近 RECENT_HOURS 小时内是否还被列表抓到过)]"""
    with conn.cursor() as cur:
        cur.execute("select id::text, jd_url, coalesce(last_seen_at >= now() - make_interval(hours => %s), false) "
                    "from jobs where source_id=%s and status='active'", (RECENT_HOURS, source_id))
        return cur.fetchall()


def _with_conn(fn):
    """库连接用完即关：解 id + 逐岗探要十几分钟，连接不留着空等（留着会被对端掐掉）。"""
    conn = jobs_db.get_conn()
    try:
        return fn(conn)
    finally:
        conn.close()


def reconcile_source(source, *, apply, max_fraction):
    """单源：全量列表 → 解 id → 逐岗探 → 过闸 → （都过且 apply 时）写库。返回 (报告, 是否被闸拦下)。"""
    adapter = BydAdapter()
    started = jobs_db._now()
    rows = _with_conn(lambda conn: load_active_rows(conn, source["id"]))
    rec = {"source_id": source["id"], "company": source.get("company"), "active_before": len(rows)}

    def blocked(reason):
        rec["blocked"] = reason
        return rec, True

    with httpx.Client(timeout=adapter.timeout, follow_redirects=True, headers=adapter._headers()) as client:
        list_rows = adapter._fetch_list_rows(client)
        list_ids = {str(r.get("id")) for r in list_rows if r.get("id")}
        rec["list"] = len(list_ids)
        rec["list_complete"] = bool(adapter.reported_total) and len(list_ids) >= adapter.reported_total
        if not rec["list_complete"]:
            return blocked("list_incomplete")

        urls = [u for _i, u, _recent in rows]
        decoded = adapter.decode_detail_urls(source["source_url"], urls)
        rec["decoded"] = sum(1 for u in urls if u in decoded)
        reason = (decode_blocked_reason(urls, decoded)
                  or recent_absent_blocked_reason(
                      [decoded[u][0] for _i, u, recent in rows if recent and u in decoded], list_ids))
        if rows and reason:
            return blocked(reason)
        absent = {job_id for job_id, _fixed in decoded.values() if job_id not in list_ids}
        rec["absent"] = len(absent)
        rec["list_not_in_lib"] = len(list_ids - {job_id for job_id, _fixed in decoded.values()})

        def probe_fn(job_id):
            return probe(client, job_id)

        seeds = iter(range(1, 10 ** 6))

        def control():
            return (positive_control_ok(list_ids, probe_fn, seed=next(seeds))
                    and negative_control_ok(list_ids, probe_fn))

        first, ok = probe_with_sentinels(absent, probe_fn, control)
        second = {}
        if ok:
            second, ok = probe_with_sentinels([j for j, s in first.items() if s == "gone"], probe_fn, control)
    rec["control"] = ok
    if not ok:
        return blocked("control_failed")

    actions = plan([(i, u) for i, u, _recent in rows], decoded, list_ids, settle_states(first, second))
    counts = {}
    for action in actions:
        counts[action[0]] = counts.get(action[0], 0) + 1
    rec.update(counts)

    reason = live_unlisted_blocked_reason(counts.get("keep_live_unlisted", 0), len(rows))
    if reason:
        return blocked(reason)
    reason = expire_blocked_reason(counts.get("expire", 0), len(rows), max_fraction)
    if reason:
        if apply:   # 占比闸只拦下架：在招行的改链接与盖戳照做，重复行留着不下架
            rec.update(_with_conn(lambda conn: apply_actions(
                conn, source["id"], [a for a in actions if a[0] != "expire"],
                not_seen_since=started, expire_dups=False)))
        return blocked(reason)
    if apply:
        rec.update(_with_conn(lambda conn: apply_actions(conn, source["id"], actions, not_seen_since=started)))
    return rec, False


def _fraction(text):
    value = float(text)
    if not 0 <= value <= 1:   # nan 也过不了这个比较
        raise argparse.ArgumentTypeError("必须在 0~1 之间")
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-expire-fraction", type=_fraction, default=DEFAULT_MAX_EXPIRE_FRACTION)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    started_at = jobs_db._now()

    sb = db.get_supabase()
    sources = [r for r in db.fetch_all_rows(
        lambda: sb.table("sources").select("id,company,source_url,adapter_name,enabled").eq("adapter_name", "byd"))
        if r.get("enabled")]
    print(f"[byd-liveness] enabled 源 {len(sources)} 个 (apply={args.apply}, "
          f"max_expire_fraction={args.max_expire_fraction})", flush=True)

    report, blocked_any = [], not sources
    for source in sources:
        try:
            rec, blocked = reconcile_source(source, apply=args.apply, max_fraction=args.max_expire_fraction)
        except Exception as exc:  # noqa: BLE001 - 取数 / 浏览器 / 库任何一步挂了都算本轮没核成
            rec, blocked = {"source_id": source["id"], "company": source.get("company"),
                            "blocked": f"error:{type(exc).__name__}"}, True
            sys.stderr.write(f"[byd-liveness] 核验失败：{type(exc).__name__}: "
                             f"{jobs_db.redact_conn_error(exc)!s:.200}\n")
        blocked_any = blocked_any or blocked
        report.append(rec)
        print(f"  {rec.get('company')}: " + json.dumps(
            {k: v for k, v in rec.items() if k not in ("source_id", "company")}, ensure_ascii=False), flush=True)

    totals = {}
    for rec in report:
        for k, v in rec.items():
            if isinstance(v, int) and not isinstance(v, bool):
                totals[k] = totals.get(k, 0) + v
    print("[byd-liveness] 合计:", json.dumps(totals, ensure_ascii=False), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"apply": args.apply, "max_expire_fraction": args.max_expire_fraction,
                       "blocked": blocked_any, "totals": totals, "sources": report}, f, ensure_ascii=False, indent=1)
    if args.apply:
        metrics = dict(totals)
        metrics["blocked"] = ",".join(sorted({str(r["blocked"]) for r in report if r.get("blocked")}))
        if not ops_runs.record_ops_run(sb, MODULE, metrics, status="failed" if blocked_any else "success",
                                       started_at=started_at, finished_at=jobs_db._now()):
            print("::warning::[byd-liveness] 台账没写成（库已按上面的数字改过）", flush=True)
    return exit_code(report, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
