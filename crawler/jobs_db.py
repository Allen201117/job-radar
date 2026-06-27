"""crawler/jobs_db.py — Phase 1：jobs 热表读写直连自建香港 PostgreSQL（JOBS_DATABASE_URL）。

为何独立于 crawler/db.py：jobs 已从 Supabase(PostgREST) 迁到自建 PG，jobs 的读写改用直连 SQL(psycopg2)。
sources / crawl_runs / discovery_runs 仍留 Supabase，继续用 crawler/db.py（不动）。

canonical_jd_url 由 HK 库的 BEFORE INSERT/UPDATE 触发器自动维护（与 normalizer.canonicalize_jd_url 同口径），
写入端无需带。这里用同口径函数算 canon 来**查既有行**，行为与旧 db.py 完全一致：
  跨状态查 canonical、优先 active、命中即按 **同一行 id** update（复活 removed 漏看岗、保住 job_actions 外键引用；
  但 expired=detail 探活确认撤岗的强信号，列表重抓不复活它 → 见 _update_set_clause 的 status CASE）。

性能：直连 SQL 没有 PostgREST 的 URI 长度限制 → 一次 `WHERE canonical = ANY(%s)` 查全批；
  写入 INSERT 用 execute_values、UPDATE 用 execute_batch，均按 page 合并往返（爬虫在 GitHub Actions
  跨境连香港库，最小化往返是关键）。psycopg2 自动做 Python→PG 类型适配，无需手写 cast。
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from normalizer import canonicalize_jd_url

# jobs 可写列（与 jobs-db/schema.sql 对齐）。canonical_jd_url 由触发器维护、search_doc v1 不填 → 都不在写入列。
_INSERT_COLS = (
    "id", "source_id", "company", "title", "location", "job_type", "summary", "jd_url",
    "apply_url", "salary_text", "posted_at", "first_seen_at", "last_seen_at", "status",
    "content_hash", "experience", "education", "deadline", "enrich_fail_count", "enrich_checked_at",
)
# update 时不动：主键 id / 首见时间 first_seen_at / enrich 子系统独占的 enrich_checked_at·enrich_fail_count。
# 后两者由 enrich_backlog 死活巡检+富化**直接 UPDATE**（非本 upsert）：列表重抓若把 enrich_checked_at 抹回
# NULL，而巡检按 enrich_checked_at nulls first 轮转 → 被抹的岗反复插队、sweep 永远追不上（81% never-checked 真因）。
_UPDATE_COLS = tuple(
    c for c in _INSERT_COLS
    if c not in ("id", "first_seen_at", "enrich_checked_at", "enrich_fail_count")
)

# 富化/抽取得到、但「列表重抓」常缺的内容字段：UPDATE 时新值为空则**保留旧值**，杜绝
# 「浏览器逐岗富化补好的 summary 被下一次列表重抓的空值抹掉」——moka 1% 覆盖根因（2026-06-20 查实：
# 每晚 backfill 补 ~8800 条，次日列表重爬 summary=None 全抹回 NULL，count_valid_active_jobs 永远上不去）。
# 仅当新值非空才覆盖（fresh 数据仍优先，如 beisen 列表自带 Duty/Require、httpx 大厂内联正文）。
_PRESERVE_IF_EMPTY = ("summary", "job_type", "experience", "education", "deadline")


def _update_set_clause(cols=_UPDATE_COLS) -> str:
    """构造 UPDATE 的 SET 子句。每列恰好消费一个 %s，占位符顺序与 _row_tuple(job, cols) 一致。
    - status：detail 探活确认撤岗（expired）的岗**黏住不复活**——wt~52%/hotjob~71% 的列表仍夹带已关闭岗
      （除身份字段外与在招岗无异），裸 status=%s 会把 sweep 判死的岗每天刷回 active（点开 404/已下线）。
      expired 留 expired、其余（removed/active）走 ELSE 仍刷 active（复活漏看岗、保 job_actions 外键）；
      ELSE 仍占一个 %s，故占位符总数不变。
    - 保留型富化字段：COALESCE(NULLIF(%s,''), 列) 防空值抹掉既有内容。其余字段：直接 %s 覆盖。"""
    def _one(c):
        if c == "status":
            return "status = CASE WHEN jobs.status = 'expired' THEN 'expired' ELSE %s END"
        if c in _PRESERVE_IF_EMPTY:
            return f"{c} = COALESCE(NULLIF(%s, ''), {c})"
        return f"{c} = %s"
    return ", ".join(_one(c) for c in cols)


def _load_env():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env.local", override=False)
    load_dotenv(root / ".env", override=False)


def get_conn():
    """直连自建香港 jobs 库。autocommit=True（与 supabase-py 每请求即提交语义一致；爬虫多为单条/批写）。"""
    _load_env()
    dsn = os.environ.get("JOBS_DATABASE_URL")
    if not dsn:
        raise RuntimeError("JOBS_DATABASE_URL 未配置（自建香港 jobs 库连接串）。")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    return conn


def enabled() -> bool:
    """配了 JOBS_DATABASE_URL 即用自建香港库；否则各 consumer 回退 Supabase。"""
    _load_env()
    return bool(os.environ.get("JOBS_DATABASE_URL"))


def fetch_all(conn, sql, params=None) -> list:
    """只读查询 → dict 行列表（供爬虫各 consumer 写自己的 jobs SQL；sources/crawl_runs 仍走 Supabase）。"""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]


def execute(conn, sql, params=None) -> int:
    """写语句 → 受影响行数。"""
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def _now():
    return datetime.now(timezone.utc)


# ── 岗位生命周期事件（job_events，02 spec §5）──────────────────────────────
# append-only 里程碑：只记关键转折，不记心跳。事件 best-effort——写失败只 warning，绝不影响 jobs upsert。
# event_key 幂等去重（FIRST_SEEN/OFFICIAL_POSTED 一辈子一条；CONFIRMED_OPEN/CLOSED/REAPPEARED 按天）。

def _day(now=None):
    return (now or _now()).date().isoformat()


def plan_upsert_events(*, job_id, source_id, old_status, old_posted_at, new_status, new_posted_at, day):
    """纯函数：据 list upsert 前后状态算应记的里程碑（FIRST_SEEN/OFFICIAL_POSTED/REAPPEARED）。
    old_status=None ⇒ 本次是 insert（新岗）。返回 [(event_key, event_type, job_id, source_id, payload)]。
    规则（02 spec §5.1）：
      · insert → FIRST_SEEN（一辈子一条）；若已拿到官方发布时间 → OFFICIAL_POSTED。
      · update 且旧无 posted_at、新有 → OFFICIAL_POSTED（一辈子一条）。
      · update 且 old_status=='removed' 且 new_status=='active' → REAPPEARED（按天）。
        ⚠️ old_status=='expired' 一律不产生 REAPPEARED（保 expired sticky 不变量）。"""
    events = []
    if old_status is None:
        events.append((f"FIRST_SEEN:{job_id}", "FIRST_SEEN", job_id, source_id, {}))
        if new_posted_at:
            events.append((f"OFFICIAL_POSTED:{job_id}", "OFFICIAL_POSTED", job_id, source_id, {}))
        return events
    if (not old_posted_at) and new_posted_at:
        events.append((f"OFFICIAL_POSTED:{job_id}", "OFFICIAL_POSTED", job_id, source_id, {}))
    if old_status == "removed" and new_status == "active":
        events.append((f"REAPPEARED:{job_id}:{day}", "REAPPEARED", job_id, source_id, {}))
    return events


def plan_close_event(job_id, source_id, day):
    """探活/巡检确认撤岗 → CLOSED（按天，一次下架一条）。"""
    return (f"CLOSED:{job_id}:{day}", "CLOSED", job_id, source_id, {})


def plan_confirm_event(job_id, source_id, day):
    """逐岗核验确认仍在招 → CONFIRMED_OPEN（按天去重，不每次心跳都写）。"""
    return (f"CONFIRMED_OPEN:{job_id}:{day}", "CONFIRMED_OPEN", job_id, source_id, {})


# ── list-absence 探活（02 spec / 2026-06-28 编排改造 §4 A2）────────────────────
# 思路：某源本次**抓全**(adapter.fetch_complete=True)后，仍 active 但 last_seen_at < 本次开抓时刻 cutoff
# 的岗 = 本次全量列表里没出现 = 已下架。比逐岗 detail 探活省（一次列表抓取顺带探活），但**只对返全量
# 在招岗、且确实翻到底的源安全**（截断/夹带已关闭岗的源会误杀 → 见 §5 不变量1、记忆 job-radar-job-
# expiry-closed-detection「通用 staleness sweep 不可行」）。故双闸：① adapter 显式 supports_absence_
# liveness 且 fetch_complete ② 占比安全闸（plan_absence_sweep）③ env LIVENESS_ABSENCE_APPLY 默认 dry-run。

def plan_absence_sweep(active_count, candidate_count, *, apply, max_expire_fraction=0.5, min_active_floor=8):
    """纯函数：据「本源 active 总数 / 拟下架(列表缺席)数 / 是否落库」决定这轮怎么走。
    返回 (action, reason)，action ∈ {'noop','skip','dry_run','apply'}。
    安全闸：拟下架占比 > max_expire_fraction 且 active 可观(≥min_active_floor) → 'skip'
    （防 httpx 偶发空/半量数据把整源误判下架；宁可这轮不动，下次抓全再说）。"""
    if candidate_count <= 0:
        return ("noop", "no_absent")
    if active_count >= min_active_floor and candidate_count > active_count * max_expire_fraction:
        return ("skip", f"too_many:{candidate_count}/{active_count}")
    return (("apply" if apply else "dry_run"), "ok")


def sweep_absent_jobs(conn, source_id, cutoff, *, apply=True, max_expire_fraction=0.5):
    """list-absence 探活：active 且 last_seen_at < cutoff（本源开抓前时刻）的岗 → expired + CLOSED 事件。
    本次 upsert 把所有再见到的岗 last_seen_at 刷成 > cutoff，故 < cutoff 的即「本次列表缺席」。
    仅 run.py 在 adapter.fetch_complete 时调用；apply=False 为 dry-run（只数不改）。
    返回 {'active','candidates','expired','action'}。"""
    sid = str(source_id)
    with conn.cursor() as cur:
        cur.execute("select count(*) from jobs where source_id = %s and status = 'active'", (sid,))
        active = cur.fetchone()[0]
        cur.execute(
            "select id from jobs where source_id = %s and status = 'active' and last_seen_at < %s",
            (sid, cutoff))
        cand_ids = [str(r[0]) for r in cur.fetchall()]
    action, _reason = plan_absence_sweep(
        active, len(cand_ids), apply=apply, max_expire_fraction=max_expire_fraction)
    result = {"active": active, "candidates": len(cand_ids), "expired": 0, "action": action}
    if action != "apply":
        return result
    now = _now()
    day = _day(now)
    with conn.cursor() as cur:
        cur.execute(
            "update jobs set status = 'expired', confirmed_closed_at = %s "
            "where id = any(%s::uuid[]) and status = 'active'", (now, cand_ids))
        result["expired"] = cur.rowcount
    record_job_events(conn, [plan_close_event(jid, source_id, day) for jid in cand_ids])
    return result


def record_job_events(conn, events) -> int:
    """best-effort 批量插 job_events（event_key 幂等 → on conflict do nothing）。
    写失败只 warning、返回 0，**绝不抛**（事件失败不许影响 jobs upsert，02 spec §5.3）。"""
    if not events:
        return 0
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "insert into job_events (event_key, event_type, job_id, source_id, payload) values %s "
                "on conflict (event_key) do nothing",
                [(k, t, jid, sid, psycopg2.extras.Json(p or {})) for (k, t, jid, sid, p) in events],
            )
        return len(events)
    except Exception as e:  # noqa: BLE001 — 事件 best-effort，任何错都不许炸穿 upsert
        print(f"  [job_events] 写入失败(忽略,不影响 upsert): {e}")
        return 0


def _find_existing_id_by_canonical(cur, canon):
    """按 canonical_jd_url 跨状态查既有行 id；多行优先 active（同旧 db.py，保复活语义）。"""
    cur.execute("select id, status from jobs where canonical_jd_url = %s", (canon,))
    rows = cur.fetchall()
    if not rows:
        return None
    for jid, status in rows:
        if status == "active":
            return jid
    return rows[0][0]


def _row_tuple(job: dict, cols, **overrides):
    """把 job dict 投影成 cols 顺序的元组（缺列补默认）；overrides 覆盖具体列值。"""
    d = dict(job)
    d.setdefault("status", "active")
    d.setdefault("enrich_fail_count", 0)
    d.update(overrides)
    return tuple(d.get(c) for c in cols)


def upsert_job(conn, job: dict) -> str:
    """单条 upsert，冲突键 canonical_jd_url；返回 'created' | 'updated'。"""
    canon = canonicalize_jd_url(job.get("jd_url"))
    now = _now()
    with conn.cursor() as cur:
        existing_id = _find_existing_id_by_canonical(cur, canon)
        if existing_id:
            sets = _update_set_clause()
            vals = _row_tuple(job, _UPDATE_COLS, last_seen_at=now)
            cur.execute(f"update jobs set {sets} where id = %s", (*vals, existing_id))
            return "updated"
        jid = str(uuid.uuid4())
        cols = ", ".join(_INSERT_COLS)
        ph = ", ".join(["%s"] * len(_INSERT_COLS))
        vals = _row_tuple(job, _INSERT_COLS, id=jid, first_seen_at=now, last_seen_at=now)
        try:
            cur.execute(f"insert into jobs ({cols}) values ({ph})", vals)
            return "created"
        except psycopg2.errors.UniqueViolation:
            # 并发下撞 4 元组/active-canonical 唯一键 → 按 canonical 重查 update（幂等兜底）
            again = _find_existing_id_by_canonical(cur, canon)
            if not again:
                raise
            sets = _update_set_clause()
            vals = _row_tuple(job, _UPDATE_COLS, last_seen_at=now)
            cur.execute(f"update jobs set {sets} where id = %s", (*vals, again))
            return "updated"


def upsert_jobs_batch(conn, jobs: list, page_size: int = 500) -> tuple:
    """批量 upsert，返回 (created, updated)。冲突键 canonical_jd_url，复活语义同 upsert_job。

    ① 批内按 canonical 去重 last-wins；② 一次 ANY() 查全批既有行（canonical→id，多行优先 active）；
    ③ 命中→批量 UPDATE（execute_batch）、未命中→批量 INSERT（execute_values）；撞唯一键退回逐行 upsert_job。"""
    if not jobs:
        return (0, 0)

    # ① 批内去重
    deduped = {}
    for job in jobs:
        deduped[canonicalize_jd_url(job.get("jd_url"))] = job
    items = list(deduped.items())  # [(canon, job)]
    now = _now()

    day = _day(now)
    update_events, insert_events = [], []

    with conn.cursor() as cur:
        # ② 一次查全批既有行（带 status/posted_at 供事件判定：REAPPEARED 看 status、OFFICIAL_POSTED 看旧 posted_at）
        canons = [c for c, _ in items if c is not None]
        existing = {}
        if canons:
            cur.execute(
                "select id, canonical_jd_url, status, posted_at from jobs where canonical_jd_url = any(%s)", (canons,))
            for jid, canon, status, posted_at in cur.fetchall():
                if canon not in existing or status == "active":
                    existing[canon] = {"id": jid, "status": status, "posted_at": posted_at}

        to_insert, to_update = [], []
        for canon, job in items:
            ex = existing.get(canon)
            if ex:
                jid = ex["id"]
                to_update.append(_row_tuple(job, _UPDATE_COLS, last_seen_at=now) + (jid,))
                # 有效新状态：expired 黏住（不复活）、其余刷 active——与 _update_set_clause 同口径。
                eff_status = "expired" if ex["status"] == "expired" else "active"
                update_events += plan_upsert_events(
                    job_id=jid, source_id=job.get("source_id"),
                    old_status=ex["status"], old_posted_at=ex.get("posted_at"),
                    new_status=eff_status, new_posted_at=job.get("posted_at"), day=day)
            else:
                jid = str(uuid.uuid4())
                to_insert.append(_row_tuple(job, _INSERT_COLS, id=jid, first_seen_at=now, last_seen_at=now))
                insert_events += plan_upsert_events(
                    job_id=jid, source_id=job.get("source_id"),
                    old_status=None, old_posted_at=None,
                    new_status="active", new_posted_at=job.get("posted_at"), day=day)

        created = updated = 0
        insert_ok = False

        # ③a 既有行批量 UPDATE（execute_batch 合并往返，psycopg2 自动类型适配）
        if to_update:
            sets = _update_set_clause()
            psycopg2.extras.execute_batch(
                cur, f"update jobs set {sets} where id = %s", to_update, page_size=page_size)
            updated = len(to_update)

        # ③b 新行批量 INSERT；撞唯一键 → 退回逐行 upsert_job（含按 canonical 重查 update 的兜底）
        if to_insert:
            cols = ", ".join(_INSERT_COLS)
            try:
                psycopg2.extras.execute_values(
                    cur, f"insert into jobs ({cols}) values %s", to_insert, page_size=page_size)
                created = len(to_insert)
                insert_ok = True
            except psycopg2.errors.UniqueViolation:
                # 极少见（并发插同一新 canonical / 撞 4 元组唯一键）→ 逐行 upsert_job 兜底（幂等：
                # 已提交的页重查命中转 update，不会重插）。autocommit 下失败语句自身已回滚。
                # 此分支生成的新 uuid 未真正落库 → 丢弃 insert_events（避免 FK 违例；事件 best-effort 可缺）。
                created = 0
                insert_events = []
                for _canon, job in items:
                    if existing.get(_canon):
                        continue  # 这些走 UPDATE 分支，已计入 updated
                    if upsert_job(conn, job) == "created":
                        created += 1
                    else:
                        updated += 1

    # 事件 best-effort 落库（jobs 已 autocommit 提交；事件失败只 warning，不影响计数/返回）。
    # 仅记 job_id 确实已落库的事件：update_events（既有 id）+ insert_events（仅 bulk insert 成功时）。
    events = list(update_events)
    if insert_ok:
        events += insert_events
    record_job_events(conn, events)

    return (created, updated)
