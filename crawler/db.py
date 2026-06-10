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
