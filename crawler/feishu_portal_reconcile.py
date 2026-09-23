"""飞书系源「公开门户」存量对账：逐岗核「在它链接所在门户上还在不在线」，下架已下线的、修正走错门户的链接。

为什么需要（2026-09-23，133 个飞书系源逐岗全量核）：
  主门户源（/index/position）过去**不带** `website-path` 头取列表，拿到的是「不带头全集」，其中一大批岗
  在公开门户详情页上显示「该职位已下线」（详情接口带 `website-path:<门户>` 时 channel_online_status=0，
  浏览器实开核对过）。adapter 已改成按公开门户取（adapters/feishu.py `_httpx_fetch_main`），
  但存量里这批死链 list-absence 清不掉：它们往往占该源 50% 以上，撞 `max_expire_fraction` 安全闸被跳过
  （哪吒 1,127 行里公开门户只有 12 个）。另有租户开两个公开门户（莉莉丝 career / index），
  存量链接挂错门户——岗是活的，链接是死的，该改链接而不是下架。

每行在招岗的处置（逐岗，不抽样）：
  in_list & 门户一致   → keep
  in_list & 门户不一致 → relink（原地改 jd_url/apply_url，保留行 id，用户的收藏/投递不丢；
                          新链接已被另一行占用 → 这行是重复，expire_dup）
  不在列表 & 链接门户上 channel_online_status==0 → expire（公开页就是「已下线」）
  不在列表 & ==1 / 读不到 → 不动（宁可漏判不可错杀），单独计数

安全闸：
  · 阳性对照：每个源从当前公开列表里抽 3 个岗查状态，必须都读到 1，才承认本源读到的 0 是真的；
    对照不过 → 本源一个都不下架（接口改了/被限流时 0 也可能是假的）。
  · 公开门户 0 岗的源（海底捞 / 地素时尚：公开首页「开启新的工作（0）」）无从本源对照 → 用本轮全局对照：
    本轮 ≥ RUN_CONTROL_MIN 个源对照通过、且没有任何源对照失败，才下架它们（跑完所有源后统一处理）。
  · 默认 dry-run；--apply 才写库。只动 status='active' 的行。
  · 下架与巡检同口径：status=expired + confirmed_closed_at + CLOSED 事件；purge 删行前会立墓碑。

用法：python3 crawler/feishu_portal_reconcile.py [--source-id <uuid> ...] [--apply] [--out report.json]
"""
import argparse
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
import jobs_db  # noqa: E402
from adapters import feishu as F  # noqa: E402
from adapters.playwright_base import _UA  # noqa: E402

FEISHU_ADAPTERS = {
    "feishu": F.FeishuGenericAdapter, "nio_feishu": F.NioAdapter, "xpeng_feishu": F.XpengAdapter,
    "xiaomi_feishu": F.XiaomiAdapter, "horizon_feishu": F.HorizonAdapter,
}
_URL_RE = re.compile(r"^(https?://[^/]+)/([^/?#]+)/position/(\d+)/detail")
CONTROL_SAMPLE = 3
RUN_CONTROL_MIN = 10
THREADS = int(os.environ.get("RECONCILE_THREADS", "8"))
SOURCE_THREADS = int(os.environ.get("RECONCILE_SOURCE_THREADS", "4"))   # 源间并发（CI 在海外，逐源串行 90 分钟跑不完）


def portal_status(host, jid, portal):
    """该岗在 `portal` 门户上的上线状态 → 1 / 0 / None（接口没给字段）/ "ERR"。
    ⚠️ 必须带 website-path=portal：channel_online_status 按门户算，不带头读 1、带 index 头读 0 实测过。"""
    for attempt in range(4):
        try:
            r = httpx.get(f"https://{host}/api/v1/job/posts/{jid}",
                          params={"portal_type": 6, "with_recommend": "false"}, timeout=20,
                          headers={"User-Agent": _UA, "portal-channel": "saas-career", "portal-platform": "pc",
                                   "Referer": f"https://{host}/{portal}/position/{jid}/detail",
                                   "website-path": portal})
            detail = (r.json().get("data") or {}).get("job_post_detail") or {}
            return detail.get("channel_online_status")
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return "ERR"


def build_adapter(row):
    ad = FEISHU_ADAPTERS[row["adapter_name"]]()
    if hasattr(ad, "_bind_host"):
        ad._bind_host(row["source_url"])
    ad._bind_website_path(row["source_url"])
    return ad


def current_portal_map(ad, host):
    """用线上 adapter 同一套逻辑取公开列表 → ({jid: 门户}, 是否抓全)；没打通 → (None, False)。"""
    rows, total, reached = ad._httpx_fetch(host)
    if not reached:
        return None, False
    default = ad.website_path or (ad.detail_template.split("/")[3] if ad.detail_template else "index")
    mapping = {str(r["id"]): (r.get("_portal") or default) for r in rows if r.get("id")}
    return mapping, (total is not None and len(rows) >= (total or 0))


def plan_source(lib_rows, portal_map, status_fn):
    """纯函数：lib_rows=[(job_id, jd_url)]、portal_map={jid: 门户} 或 None（列表没打通）、
    status_fn(jid, 门户) → 1/0/None/"ERR"。返回 [(action, job_id, jd_url, new_url)]。"""
    actions = []
    for job_id, jd_url in lib_rows:
        m = _URL_RE.match(jd_url or "")
        if not m:
            actions.append(("keep_nonstd_url", job_id, jd_url, None))
            continue
        origin, prefix, jid = m.group(1), m.group(2), m.group(3)
        if portal_map is not None and jid in portal_map:
            want = portal_map[jid]
            if want == prefix:
                actions.append(("keep", job_id, jd_url, None))
            else:
                actions.append(("relink", job_id, jd_url, f"{origin}/{want}/position/{jid}/detail"))
            continue
        st = status_fn(jid, prefix)
        if st == 0:
            actions.append(("expire", job_id, jd_url, None))
        elif st == 1:
            actions.append(("keep_online_unlisted", job_id, jd_url, None))
        else:
            actions.append(("keep_unknown", job_id, jd_url, None))
    return actions


def control_ok(host, portal_map, status_fn, k=CONTROL_SAMPLE, seed=0):
    """阳性对照：公开列表里抽 k 个岗，必须全读到 1。列表为空 → 无从对照，返回 None（调用方按「不许下架」处理）。"""
    if not portal_map:
        return None
    ids = sorted(portal_map)
    random.Random(seed).shuffle(ids)
    return all(status_fn(j, portal_map[j]) == 1 for j in ids[:k])


def run_control_ok(ctrls, min_pass=RUN_CONTROL_MIN):
    """本轮全局对照：通过的源够多、且一个失败的都没有。"""
    ctrls = list(ctrls)
    return sum(1 for c in ctrls if c is True) >= min_pass and not any(c is False for c in ctrls)


def expire_allowed(ctrl, run_ok):
    """本源读到的 0 能不能信：本源对照过 → 信；本源无从对照（公开门户 0 岗）→ 看全局；本源对照失败 → 不信。"""
    if ctrl is True:
        return True
    if ctrl is None:
        return bool(run_ok)
    return False


def apply_actions(conn, source_id, actions):
    """写库：relink 原地改链接（撞唯一约束 = 重复行 → 下架这行）；expire 下架 + CLOSED 事件。"""
    now = jobs_db._now()
    day = jobs_db._day(now)
    expired, relinked, dup = [], 0, []
    with conn.cursor() as cur:
        for action, job_id, _url, new_url in actions:
            if action == "relink":
                cur.execute("select id from jobs where status='active' and id <> %s "
                            "and canonical_jd_url = public.canonicalize_jd_url(%s) limit 1", (job_id, new_url))
                if cur.fetchone():
                    dup.append(job_id)
                    continue
                cur.execute("update jobs set jd_url=%s, apply_url=%s where id=%s and status='active'",
                            (new_url, new_url, job_id))
                relinked += cur.rowcount
            elif action == "expire":
                expired.append(job_id)
        ids = expired + dup
        n_expired = 0
        if ids:
            cur.execute("update jobs set status='expired', confirmed_closed_at=%s, enrich_checked_at=%s "
                        "where id = any(%s::uuid[]) and status='active'", (now, now, ids))
            n_expired = cur.rowcount
    jobs_db.record_job_events(conn, [jobs_db.plan_close_event(j, source_id, day) for j in expired + dup])
    return {"relinked": relinked, "expired": n_expired, "dup_expired": len(dup)}


def process_source(row, i, n, apply):
    """单源：取公开列表 → 逐岗定处置 → 对照 → （对照过且 apply 时）写库。本源对照不为 True 的下架留给全局对照。"""
    conn = jobs_db.get_conn()
    try:
        ad = build_adapter(row)
        host = ad._resolve_host(row["source_url"])
        portal_map, complete = current_portal_map(ad, host)
        with conn.cursor() as cur:
            cur.execute("select id::text, jd_url from jobs where source_id=%s and status='active'", (row["id"],))
            lib = cur.fetchall()

        def status_fn(jid, portal, _host=host):
            return portal_status(_host, jid, portal)

        need = []
        for _jid, url in lib:
            m = _URL_RE.match(url or "")
            if m and (portal_map is None or m.group(3) not in portal_map):
                need.append((m.group(3), m.group(2)))
        with ThreadPoolExecutor(THREADS) as ex:
            fetched = dict(zip(need, ex.map(lambda t: status_fn(*t), need)))
        actions = plan_source(lib, portal_map, lambda j, p: fetched.get((j, p), "ERR"))
        ctrl = control_ok(host, portal_map, status_fn, seed=i)
        counts = {}
        for a in actions:
            counts[a[0]] = counts.get(a[0], 0) + 1
        lib_jids = {m.group(3) for _j, u in lib for m in [_URL_RE.match(u or "")] if m}
        rec = {"source_id": row["id"], "company": row["company"], "source_url": row["source_url"], "host": host,
               "active_before": len(lib), "list": len(portal_map or {}), "list_complete": complete,
               "list_not_in_lib": len(set(portal_map or {}) - lib_jids), "control": ctrl, **counts}
        deferred = []
        if ctrl is not True and counts.get("expire"):
            deferred = [a for a in actions if a[0] == "expire"]
            actions = [a for a in actions if a[0] != "expire"]
        if apply:
            rec.update(apply_actions(conn, row["id"], actions))
        print(f"[{i}/{n}] {row['company'][:16]:16s} {host[:34]:34s} 库{len(lib):5d} 列表{rec['list']:5d} "
              f"保留{counts.get('keep', 0):5d} 改链{counts.get('relink', 0):4d} 下架{counts.get('expire', 0):5d} "
              f"在线未列{counts.get('keep_online_unlisted', 0):3d} 未知{counts.get('keep_unknown', 0):3d} "
              f"待补{rec['list_not_in_lib']:4d} 对照{ctrl}" + (" (下架待全局对照)" if deferred else ""), flush=True)
        return rec, deferred
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source-id", action="append", default=[])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    sb = db.get_supabase()
    sources = [r for r in db.fetch_all_rows(lambda: sb.table("sources").select("id,company,source_url,adapter_name,enabled"))
               if r.get("enabled") and r.get("adapter_name") in FEISHU_ADAPTERS
               and (not args.source_id or r["id"] in args.source_id)]
    n = len(sources)
    print(f"[reconcile] 飞书系 enabled 源 {n} 个 (apply={args.apply})", flush=True)
    with ThreadPoolExecutor(SOURCE_THREADS) as ex:
        results = list(ex.map(lambda t: process_source(t[1], t[0], n, args.apply), enumerate(sources, 1)))

    run_ok = run_control_ok(rec["control"] for rec, _ in results)
    print(f"[reconcile] 全局对照：通过 {sum(1 for r, _ in results if r['control'] is True)} 源、"
          f"失败 {sum(1 for r, _ in results if r['control'] is False)} 源 → {'可信' if run_ok else '不可信'}", flush=True)
    if any(d for _, d in results):
        conn = jobs_db.get_conn()
        try:
            for rec, deferred in results:
                if not deferred:
                    continue
                if expire_allowed(rec["control"], run_ok):
                    rec["expire_via_run_control"] = len(deferred)
                    if args.apply:
                        out = apply_actions(conn, rec["source_id"], deferred)
                        rec["expired"] = rec.get("expired", 0) + out["expired"]
                    print(f"  [全局对照放行] {rec['company'][:16]} 下架 {len(deferred)}", flush=True)
                else:
                    rec["expire_blocked_by_control"] = len(deferred)
                    print(f"  ⚠️ [对照不过拦下] {rec['company'][:16]} {len(deferred)} 个不动", flush=True)
        finally:
            conn.close()

    report, totals = [], {}
    for rec, _deferred in results:
        rec["active_after_planned"] = (rec["active_before"] - rec.get("expire", 0)
                                       + rec.get("expire_blocked_by_control", 0))
        report.append(rec)
        for k, v in rec.items():
            if isinstance(v, int) and not isinstance(v, bool):
                totals[k] = totals.get(k, 0) + v
    print("[reconcile] 合计:", json.dumps(totals, ensure_ascii=False), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"apply": args.apply, "run_control_ok": run_ok, "totals": totals, "sources": report},
                      f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
