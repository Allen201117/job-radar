import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from supabase import create_client, Client
from dotenv import load_dotenv


def load_environment(project_root: Optional[Path] = None):
    """Load root .env.local so local crawler commands work without inline env."""
    root = project_root or Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env.local", override=False)
    load_dotenv(root / ".env", override=False)


def get_supabase() -> Client:
    """使用 service_role key 连接 Supabase（写入 jobs/sources/crawl_runs）。"""
    load_environment()
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_sources(supabase: Client) -> list[dict]:
    """读取所有 enabled 的 sources。"""
    resp = supabase.table("sources").select("*").eq("enabled", True).execute()
    return resp.data or []


def create_crawl_run(supabase: Client, source_id: str) -> str:
    """创建抓取日志，返回 run_id。"""
    run_id = str(uuid.uuid4())
    supabase.table("crawl_runs").insert({
        "id": run_id,
        "source_id": source_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "skipped",
    }).execute()
    return run_id


def update_crawl_run(
    supabase: Client,
    run_id: str,
    status: str,
    jobs_found: int = 0,
    jobs_created: int = 0,
    jobs_updated: int = 0,
    error_message: Optional[str] = None,
):
    """更新抓取日志。"""
    data = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "jobs_found": jobs_found,
        "jobs_created": jobs_created,
        "jobs_updated": jobs_updated,
    }
    if error_message:
        data["error_message"] = error_message[:1000]

    supabase.table("crawl_runs").update(data).eq("id", run_id).execute()


def upsert_job(supabase: Client, job: dict) -> str:
    """
    Upsert 岗位。
    使用 (source_id, jd_url) 作为稳定键，避免 location 为 NULL 时重复插入。
    返回 "created" 或 "updated"。
    """
    # 先按唯一键查找
    existing = (
        supabase.table("jobs")
        .select("id")
        .eq("source_id", job["source_id"])
        .eq("jd_url", job["jd_url"])
        .execute()
    )

    if existing.data:
        # 更新
        job_id = existing.data[0]["id"]
        supabase.table("jobs").update({
            **job,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()
        return "updated"
    else:
        # 新增
        job["id"] = str(uuid.uuid4())
        job["first_seen_at"] = datetime.now(timezone.utc).isoformat()
        job["last_seen_at"] = datetime.now(timezone.utc).isoformat()
        try:
            supabase.table("jobs").insert(job).execute()
        except Exception as e:
            # 先查后插非原子：并发抓取下两线程/两渠道源同时插同一岗会撞唯一键（23505）。
            # 回退为按 jd_url 重查（撞键行可能挂在别的 source_id 下）并 update，幂等不上抛。
            msg = str(e)
            if "23505" not in msg and "duplicate key" not in msg:
                raise
            again = (
                supabase.table("jobs")
                .select("id")
                .eq("jd_url", job["jd_url"])
                .limit(1)
                .execute()
            )
            if not again.data:
                raise  # 撞键却查不到（极端情况）→ 如实上抛，由调用方记 failed
            update_payload = {k: v for k, v in job.items() if k not in ("id", "first_seen_at")}
            supabase.table("jobs").update(update_payload).eq("id", again.data[0]["id"]).execute()
            return "updated"
        return "created"


def upsert_jobs_batch(supabase: Client, jobs: list[dict], chunk_size: int = 200) -> tuple[int, int]:
    """批量 upsert 一批岗位，返回 (created, updated)。

    打回快档 <30min 的核心修法：逐岗 upsert_job 每岗 2 次 REST（先查后写），全量数万岗
    → 6-10 万次往返。本函数把同一批（通常同 source）压成「1 次批量 select + 分块 upsert/insert」。

    为何不用 PostgREST 的 on_conflict=(source_id,jd_url)：jobs 表唯一约束只有
    unique(company,title,location,jd_url)（001_init.sql），且 location 可空（Postgres 里
    NULL≠NULL，该约束对空 location 不去重）——这正是原 upsert_job 走应用层 select
    (source_id,jd_url) 而非靠 DB 约束的原因。没有可直接 on_conflict 的 (source_id,jd_url)/jd_url
    唯一索引，故：existing 行用主键 id 做 upsert(on_conflict=id) 批量更新；new 行批量 insert，
    撞 4 元组唯一键(23505)时退回逐行 upsert_job（已正确处理 23505→按 jd_url 重查 update）。

    去重语义与原逐行一致：① 主键 (source_id, jd_url)；② 跨 source 撞 jd_url（同一岗挂在别的
    source_id 下，如 hotjob school/social、wt 三渠道）回退按 jd_url 命中既有行 update；
    ③ 批内同 (source_id, jd_url) 去重，last-wins（镜像顺序 select-then-write）。"""
    if not jobs:
        return (0, 0)

    # ③ 批内按 (source_id, jd_url) 去重，last-wins（原逐行靠「插入 A 后 A' select 命中 A」隐式去重，
    #    本函数一次性 select 在所有写之前，故必须先显式去重，否则空 location 的同岗会被重复 insert）。
    deduped: dict = {}
    for job in jobs:
        deduped[(job.get("source_id"), job.get("jd_url"))] = job
    jobs = list(deduped.values())

    # 1. 一次性批量 select 既有行（按 jd_url，分块防 URL 过长）；建 (source_id,jd_url)→id 与 jd_url→id 两张表
    jd_urls = sorted({j["jd_url"] for j in jobs if j.get("jd_url")})
    existing_by_src: dict = {}
    existing_by_jd: dict = {}
    for i in range(0, len(jd_urls), chunk_size):
        chunk = jd_urls[i:i + chunk_size]
        resp = supabase.table("jobs").select("id, source_id, jd_url").in_("jd_url", chunk).execute()
        for row in (resp.data or []):
            key = (row.get("source_id"), row.get("jd_url"))
            existing_by_src.setdefault(key, row.get("id"))
            existing_by_jd.setdefault(row.get("jd_url"), row.get("id"))

    now = datetime.now(timezone.utc).isoformat()
    to_update: list = []  # 命中既有 → 带 id 走主键 upsert
    to_insert: list = []  # 全新 → 批量 insert
    for job in jobs:
        existing_id = existing_by_src.get((job.get("source_id"), job.get("jd_url"))) \
            or existing_by_jd.get(job.get("jd_url"))
        if existing_id:
            payload = {k: v for k, v in job.items() if k not in ("id", "first_seen_at")}
            payload["id"] = existing_id
            payload["last_seen_at"] = now
            to_update.append(payload)
        else:
            row = dict(job)
            row["id"] = str(uuid.uuid4())
            row["first_seen_at"] = now
            row["last_seen_at"] = now
            to_insert.append(row)

    created = 0
    updated = 0

    # 2. 既有行：按主键 id 批量 upsert（on_conflict=id 必命中 → 批量 update，一次 REST 一块）
    for i in range(0, len(to_update), chunk_size):
        block = to_update[i:i + chunk_size]
        supabase.table("jobs").upsert(block, on_conflict="id").execute()
        updated += len(block)

    # 3. 新行：批量 insert；撞 4 元组唯一键(23505) → 退回逐行 upsert_job（含按 jd_url 重查 update 的正确兜底）
    for i in range(0, len(to_insert), chunk_size):
        block = to_insert[i:i + chunk_size]
        try:
            supabase.table("jobs").insert(block).execute()
            created += len(block)
        except Exception as e:
            msg = str(e)
            if "23505" not in msg and "duplicate key" not in msg:
                raise
            for row in block:
                single = {k: v for k, v in row.items()
                          if k not in ("id", "first_seen_at", "last_seen_at")}
                if upsert_job(supabase, single) == "created":
                    created += 1
                else:
                    updated += 1

    return (created, updated)


def update_source_timestamp(supabase: Client, source_id: str):
    """更新 source 的 last_checked_at。"""
    supabase.table("sources").update({
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", source_id).execute()


def get_discovery_run(supabase: Client, run_id: str) -> Optional[dict]:
    """读取一条 discovery_runs（按需浏览器发现）。"""
    resp = (
        supabase.table("discovery_runs")
        .select("*")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def update_discovery_run(supabase: Client, run_id: str, **fields):
    """更新一条 discovery_runs（按需浏览器发现的生命周期）。空 run_id 时跳过。"""
    if not run_id:
        return
    if not fields:
        return
    supabase.table("discovery_runs").update(dict(fields)).eq("id", run_id).execute()
