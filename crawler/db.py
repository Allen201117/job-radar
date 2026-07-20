import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from supabase import create_client, Client
from dotenv import load_dotenv

from normalizer import canonicalize_jd_url


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


# PostgREST 单次 select 的行数硬顶。超过它的表必须分页拉，否则静默只拿到前 1000 行。
_PAGE_SIZE = 1000


def fetch_all_rows(query_factory, page_size: int = _PAGE_SIZE, order_key: str = "id") -> list[dict]:
    """分页拉全量（PostgREST 单次 select 最多 1000 行，超出部分**静默**丢弃，不报错）。

    query_factory 必须每页返回一个**新**的 query builder（builder 有状态，复用会把 range/order 叠加）。
    用法：fetch_all_rows(lambda: sb.table("sources").select("*").eq("enabled", True))

    ⚠️ 每页必须带 .order(order_key)：跨请求翻页时 Postgres 不保证无 ORDER BY 的行序一致
    → 会重复取同一行 + 漏掉另一行（漏的行数对了、内容不对，比截断更难查）。
    """
    out: list[dict] = []
    offset = 0
    while True:
        rows = (query_factory()
                .order(order_key, desc=False)
                .range(offset, offset + page_size - 1)
                .execute().data) or []
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def get_sources(supabase: Client) -> list[dict]:
    """读取所有 enabled 的 sources。

    ⚠️ 必须分页：这是 run.py 每日抓取的源清单来源，enabled 已越过 1000（2026-07-20 实测 1079）
    → 不分页时尾部 79 个源每天根本不会被抓，且无 ORDER BY 时每次漏的还是不同的 79 个。"""
    return fetch_all_rows(
        lambda: supabase.table("sources").select("*").eq("enabled", True))


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
    reported_total: Optional[int] = None,
    coverage_complete: Optional[bool] = None,
):
    """更新抓取日志。reported_total/coverage_complete=抓全率可观测（阶段①），None 时不写该列。"""
    data = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "jobs_found": jobs_found,
        "jobs_created": jobs_created,
        "jobs_updated": jobs_updated,
    }
    if error_message:
        data["error_message"] = error_message[:1000]
    if reported_total is not None:
        data["reported_total"] = reported_total
    if coverage_complete is not None:
        data["coverage_complete"] = coverage_complete

    supabase.table("crawl_runs").update(data).eq("id", run_id).execute()


def _find_existing_id_by_canonical(supabase: Client, canon: str):
    """按 canonical_jd_url 跨状态查既有行 id；多行时优先 active。

    冲突键 = canonical_jd_url（DB 层 active partial unique index 同口径，迁移 144）。跨状态查
    （不加 status 过滤）是为了让重新上架的 removed/expired 岗能命中既有行复活，而非误插新行。
    同 canonical 可能并存一 active + 若干 removed（迁移 dedup 的产物）→ 必须优先返回 active 行，
    否则去 update removed 行复活会撞 active 唯一约束。无既有行返回 None。"""
    resp = (
        supabase.table("jobs")
        .select("id, status")
        .eq("canonical_jd_url", canon)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        return None
    for row in rows:
        if row.get("status") == "active":
            return row["id"]
    return rows[0]["id"]


def upsert_job(supabase: Client, job: dict) -> str:
    """Upsert 岗位，以 canonical_jd_url 为冲突键（迁移 144 起 DB 层有 active 唯一约束）。

    canonical_jd_url 列由 DB 触发器从 jd_url 自动维护，写入端无需带；这里只需用同口径的
    canonicalize_jd_url 算出键来查既有行。返回 "created" 或 "updated"。"""
    canon = canonicalize_jd_url(job["jd_url"])
    existing_id = _find_existing_id_by_canonical(supabase, canon)
    if existing_id:
        supabase.table("jobs").update({
            **job,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", existing_id).execute()
        return "updated"

    job["id"] = str(uuid.uuid4())
    job["first_seen_at"] = datetime.now(timezone.utc).isoformat()
    job["last_seen_at"] = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("jobs").insert(job).execute()
    except Exception as e:
        # 先查后插非原子：并发抓取下两线程/两渠道源同时插同一岗会撞唯一键（23505）。
        # 回退为按 canonical 重查并 update，幂等不上抛。
        msg = str(e)
        if "23505" not in msg and "duplicate key" not in msg:
            raise
        again_id = _find_existing_id_by_canonical(supabase, canon)
        if not again_id:
            raise  # 撞键却查不到（极端情况）→ 如实上抛，由调用方记 failed
        update_payload = {k: v for k, v in job.items() if k not in ("id", "first_seen_at")}
        supabase.table("jobs").update(update_payload).eq("id", again_id).execute()
        return "updated"
    return "created"


# 单次 .in_("canonical_jd_url", …) select 的 URL 累计长度预算。GET 查询串过长会撞 Supabase 网关
# URI 上限（~8KB）→ 整源 select 报 400（明文 Bad Request，非 PostgREST JSON 错）。长 query 串 jd_url
# （wt/hotjob 形如 ?brandCode=1&safe=Y&recruitType=2&postIdsAry=…，编码后约 1.7×）在固定 200 条/块时
# URI 达 ~28KB → 400。3500 原始字符 → 编码后 ~6KB，稳在 8KB 内（短链源仍能打满、不增往返）。
_SELECT_URI_BUDGET_CHARS = 3500


def _chunk_by_uri_budget(values, max_chars: int = _SELECT_URI_BUDGET_CHARS, max_count: int = 200):
    """按 URL 累计长度切块：单块总长 ≤ max_chars 且条数 ≤ max_count。单条超预算时自成一块（绝不丢弃）。
    供 upsert_jobs_batch 的 canonical select 防 GET URI 过长用——按条数固定分块会让长 query 串源撞网关 400。"""
    chunk: list = []
    size = 0
    for v in values:
        vlen = len(v) + 4  # 引号/逗号/编码余量
        if chunk and (size + vlen > max_chars or len(chunk) >= max_count):
            yield chunk
            chunk, size = [], 0
        chunk.append(v)
        size += vlen
    if chunk:
        yield chunk


def upsert_jobs_batch(supabase: Client, jobs: list[dict], chunk_size: int = 200) -> tuple[int, int]:
    """批量 upsert 一批岗位，返回 (created, updated)。

    打回快档 <30min 的核心修法：逐岗 upsert_job 每岗 2 次 REST（先查后写），全量数万岗
    → 6-10 万次往返。本函数把同一批（通常同 source）压成「1 次批量 select + 分块 upsert/insert」。

    冲突键 = canonical_jd_url（迁移 144 起 DB 层有 active partial unique index + jobs_canonical_jd_url_idx）。
    canonical_jd_url 列由 DB 触发器自动维护，故 existing 行用主键 id 做 upsert(on_conflict=id) 批量更新；
    new 行批量 insert，撞唯一键(23505) 退回逐行 upsert_job（已正确处理 23505→按 canonical 重查 update）。

    去重语义：① 冲突键 canonical_jd_url（跨 source/同岗链接变体都收敛到一把键，如 hotjob school/social、
    wt 三渠道、utm 变体）；② 同 canonical 既有多行优先命中 active 行（迁移 dedup 后另存 removed 历史行）；
    ③ 批内同 canonical 去重，last-wins（一次性 select 在所有写之前，必须先显式去重）。"""
    if not jobs:
        return (0, 0)

    # ③ 批内按 canonical 去重，last-wins（一次性 select 在所有写之前，否则同岗链接变体会被重复 insert）。
    deduped: dict = {}
    for job in jobs:
        deduped[canonicalize_jd_url(job.get("jd_url"))] = job
    jobs = list(deduped.values())

    # 1. 一次性批量 select 既有行（按 canonical，按 URL 累计长度分块防 GET URI 撞网关上限）；建 canonical→id（多行优先 active）。
    canons = sorted({canonicalize_jd_url(j.get("jd_url")) for j in jobs if j.get("jd_url")})
    existing_by_canon: dict = {}
    for chunk in _chunk_by_uri_budget(canons):
        resp = supabase.table("jobs").select("id, canonical_jd_url, status").in_("canonical_jd_url", chunk).execute()
        for row in (resp.data or []):
            canon = row.get("canonical_jd_url")
            if not canon:
                continue
            if canon not in existing_by_canon or row.get("status") == "active":
                existing_by_canon[canon] = row.get("id")

    now = datetime.now(timezone.utc).isoformat()
    to_update: list = []  # 命中既有 → 带 id 走主键 upsert
    to_insert: list = []  # 全新 → 批量 insert
    for job in jobs:
        existing_id = existing_by_canon.get(canonicalize_jd_url(job.get("jd_url")))
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


def get_discovery_run(supabase: Client, run_id: str) -> Optional[dict]:
    """按 id 取一条 discovery_runs（用于读 diagnostics.source_ids / filters）。不存在返回 None。"""
    if not run_id:
        return None
    resp = (
        supabase.table("discovery_runs").select("*").eq("id", run_id).limit(1).execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def claim_discovery_run(supabase: Client, run_id: str) -> bool:
    """状态认领守卫：条件更新 queued→running（仅当当前 status='queued'）。
    返回 True=本 worker 成功认领；False=已被其它 worker 认领或非 queued（应直接退出，防双 worker 抢同一 run）。"""
    if not run_id:
        return False
    resp = (
        supabase.table("discovery_runs")
        .update({"status": "running"})
        .eq("id", run_id)
        .eq("status", "queued")
        .execute()
    )
    return bool(resp.data)


def get_sources_by_ids(supabase: Client, ids: list) -> list[dict]:
    """按 id 列表取 sources 行（company_refresh 按 scope 选定的源）。空列表返回 []。"""
    clean = [str(x) for x in (ids or []) if str(x).strip()]
    if not clean:
        return []
    resp = supabase.table("sources").select("*").in_("id", clean).execute()
    return resp.data or []
