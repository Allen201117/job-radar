"""crawler/jobs_db.py — Phase 1：jobs 热表读写直连自建香港 PostgreSQL（JOBS_DATABASE_URL）。

为何独立于 crawler/db.py：jobs 已从 Supabase(PostgREST) 迁到自建 PG，jobs 的读写改用直连 SQL(psycopg2)。
sources / crawl_runs / discovery_runs 仍留 Supabase，继续用 crawler/db.py（不动）。

canonical_jd_url 由 HK 库的 BEFORE INSERT/UPDATE 触发器自动维护（与 normalizer.canonicalize_jd_url 同口径），
写入端无需带。这里用同口径函数算 canon 来**查既有行**，行为与旧 db.py 完全一致：
  跨状态查 canonical、优先 active、命中即按 **同一行 id** update（复活 removed/expired，保住 job_actions 外键引用）。

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
# update 时不动主键 id 与首见时间 first_seen_at
_UPDATE_COLS = tuple(c for c in _INSERT_COLS if c not in ("id", "first_seen_at"))


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
            sets = ", ".join(f"{c} = %s" for c in _UPDATE_COLS)
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
            sets = ", ".join(f"{c} = %s" for c in _UPDATE_COLS)
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

    with conn.cursor() as cur:
        # ② 一次查全批既有行
        canons = [c for c, _ in items if c is not None]
        existing = {}
        if canons:
            cur.execute("select id, canonical_jd_url, status from jobs where canonical_jd_url = any(%s)", (canons,))
            for jid, canon, status in cur.fetchall():
                if canon not in existing or status == "active":
                    existing[canon] = jid

        to_insert, to_update = [], []
        for canon, job in items:
            jid = existing.get(canon)
            if jid:
                to_update.append(_row_tuple(job, _UPDATE_COLS, last_seen_at=now) + (jid,))
            else:
                to_insert.append(_row_tuple(job, _INSERT_COLS, id=str(uuid.uuid4()),
                                            first_seen_at=now, last_seen_at=now))

        created = updated = 0

        # ③a 既有行批量 UPDATE（execute_batch 合并往返，psycopg2 自动类型适配）
        if to_update:
            sets = ", ".join(f"{c} = %s" for c in _UPDATE_COLS)
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
            except psycopg2.errors.UniqueViolation:
                # 极少见（并发插同一新 canonical / 撞 4 元组唯一键）→ 逐行 upsert_job 兜底（幂等：
                # 已提交的页重查命中转 update，不会重插）。autocommit 下失败语句自身已回滚。
                created = 0
                for _canon, job in items:
                    if existing.get(_canon):
                        continue  # 这些走 UPDATE 分支，已计入 updated
                    if upsert_job(conn, job) == "created":
                        created += 1
                    else:
                        updated += 1

    return (created, updated)
