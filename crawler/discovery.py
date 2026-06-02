"""
按需「浏览器发现」编排（Tier-2 复用 Playwright 拦截层）。

由 GitHub Actions workflow_dispatch 触发（见 .github/workflows/daily-crawl.yml），通过环境变量传参：
    DISCOVERY_MODE=discovery
    DISCOVERY_RUN_ID=<discovery_runs.id（API 端已 insert 的 queued 行）>
    DISCOVERY_QUERY / DISCOVERY_CITY / DISCOVERY_JOB_TYPE / DISCOVERY_LIMIT

生命周期：API 端写 'queued' → 本编排把行推进 'running' → 解析平台配方(resolve_recipe)跑浏览器
拦截入库 → 写终态('success'/'partial_success'/'failed') + 产出 jd_url 列表到 diagnostics。

可靠性思路：发现 = 对**已知官方 SPA 源**按关键词做浏览器拦截抓取（和每日全量抓 500 条同一套
Playwright 机制），再按 query/city 过滤 + 质量门校验 + 入共享 jobs 库。不去硬刚通用网搜。
"""
import os
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote

import db
import normalizer
from adapters.base import RawJob
from adapters.bytedance import BytedanceAdapter
from adapters.feishu import NioAdapter, XpengAdapter, HorizonAdapter, XiaomiAdapter


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 入参解析（纯函数）
# ---------------------------------------------------------------------------
def parse_discovery_env(env: dict) -> Optional[dict]:
    """从环境变量解析发现入参。非发现模式（缺 mode/run_id/query）返回 None，让 run.py 走全量抓取。"""
    mode = str(env.get("DISCOVERY_MODE") or "").strip().lower()
    run_id = str(env.get("DISCOVERY_RUN_ID") or "").strip()
    query = str(env.get("DISCOVERY_QUERY") or "").strip()
    if mode != "discovery" or not run_id or not query:
        return None

    limit_raw = str(env.get("DISCOVERY_LIMIT") or "").strip()
    try:
        limit = int(limit_raw) if limit_raw else 30
    except ValueError:
        limit = 30
    limit = max(1, min(limit, 60))

    return {
        "run_id": run_id,
        "query": query,
        "city": str(env.get("DISCOVERY_CITY") or "").strip(),
        "job_type": str(env.get("DISCOVERY_JOB_TYPE") or "").strip(),
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# 关键词匹配 / URL 构造（纯函数，可单测）
# ---------------------------------------------------------------------------
def build_keyword_list_urls(adapter_name: str, query: str) -> Optional[List[str]]:
    """为支持关键词检索的源构造关键词专用列表 URL；不支持则返回 None（用适配器默认 list_urls 再后置过滤）。"""
    term = (query or "").strip()
    if not term:
        return None
    if adapter_name == "bytedance":
        return [f"https://jobs.bytedance.com/experienced/position?keyword={quote(term)}"]
    # 飞书系列表页的关键词参数不稳定，走默认 list_urls + 后置过滤，避免猜错参数。
    return None


def job_matches_query(raw: RawJob, query: str) -> bool:
    """岗位是否命中关键词（标题/摘要/类型任一包含，大小写不敏感）。空 query 视为命中。"""
    term = (query or "").strip().lower()
    if not term:
        return True
    haystack = " ".join(
        filter(None, [raw.title, raw.summary, raw.job_type])
    ).lower()
    return term in haystack


def job_matches_city(raw: RawJob, city: str) -> bool:
    """岗位是否命中城市。空 city 视为命中；否则按归一化后的城市做包含匹配。"""
    want = (city or "").strip()
    if not want:
        return True
    if not raw.location:
        return False
    want_norm = normalizer.normalize_city(want)
    loc_norm = normalizer.normalize_city(raw.location)
    return want_norm in loc_norm or want in (raw.location or "")


def filter_raw_jobs(raw_jobs: List[RawJob], query: str, city: str) -> List[RawJob]:
    """按关键词 + 城市过滤抓到的岗位（纯函数）。"""
    return [
        raw
        for raw in raw_jobs
        if job_matches_query(raw, query) and job_matches_city(raw, city)
    ]


# ---------------------------------------------------------------------------
# 平台配方
# ---------------------------------------------------------------------------
class SpaKeywordRecipe:
    """对已知官方 SPA 源（字节 + 飞书系）按关键词做浏览器拦截抓取并入库。"""

    key = "spa_keyword"
    # adapter_name -> Adapter 类（与 run.py ADAPTERS / sources.adapter_name 对齐）
    adapters = {
        "bytedance": BytedanceAdapter,
        "nio_feishu": NioAdapter,
        "xpeng_feishu": XpengAdapter,
        "horizon_feishu": HorizonAdapter,
        "xiaomi_feishu": XiaomiAdapter,
    }
    discovery_max_pages = 2  # 发现限页，控制 5min 预算

    def matches(self, query: str, city: str = "", company: str = "") -> bool:
        # 目前是唯一的种子配方：有关键词即适用。
        return bool((query or "").strip())

    def run(self, supabase, params: dict) -> dict:
        query = params["query"]
        city = params.get("city", "")

        sources = db.get_sources(supabase)
        by_adapter = {s.get("adapter_name"): s for s in sources}

        produced: List[str] = []
        created = updated = 0
        crawled_any = False
        errors: List[str] = []

        for adapter_name, adapter_cls in self.adapters.items():
            source = by_adapter.get(adapter_name)
            if not source:
                continue  # 该源未入 sources 表（需 migration 010），跳过
            crawled_any = True
            try:
                adapter = adapter_cls()
                adapter.max_pages = min(getattr(adapter, "max_pages", 2), self.discovery_max_pages)
                kw_urls = build_keyword_list_urls(adapter_name, query)
                if kw_urls:
                    adapter.list_urls = kw_urls

                html = adapter.fetch(source["source_url"])
                raw_jobs = adapter.parse(html)
                matched = filter_raw_jobs(raw_jobs, query, city)
                c, u, urls = _upsert_raw_jobs(
                    supabase, source["id"], source["company"], source["source_url"], matched
                )
                created += c
                updated += u
                produced.extend(urls)
                print(f"[discovery]   {adapter_name}: parsed={len(raw_jobs)} "
                      f"matched={len(matched)} created={c} updated={u}")
            except Exception as e:
                errors.append(f"{adapter_name}: {type(e).__name__}: {e}")
                print(f"[discovery]   {adapter_name}: FAILED {type(e).__name__}: {e}")
                continue

        if not crawled_any:
            return {
                "status": "failed",
                "failure_reason": "no_spa_sources_in_db",
                "error_message": "No SPA source rows found; apply migration 010_seed_spa_sources.sql.",
                "jobs_created": 0,
                "jobs_updated": 0,
                "candidates_found": 0,
                "produced_jd_urls": [],
            }

        if produced:
            status = "success" if not errors else "partial_success"
            failure_reason = None
        else:
            status = "failed"
            failure_reason = "no_jobs_passed_quality"

        return {
            "status": status,
            "failure_reason": failure_reason,
            "error_message": ("; ".join(errors)[:1000] if errors else None),
            "jobs_created": created,
            "jobs_updated": updated,
            "candidates_found": len(produced),
            "produced_jd_urls": produced[:200],
        }


def _upsert_raw_jobs(supabase, source_id, company, source_url, raw_jobs):
    """质量门校验 + 归一化 + upsert（镜像 run.py 的入库逻辑）。返回 (created, updated, jd_urls)。"""
    created = updated = 0
    urls: List[str] = []
    for raw in raw_jobs:
        is_valid, _reason = normalizer.validate_job_quality(raw, source_url)
        if not is_valid:
            continue

        title = normalizer.clean_title(raw.title)
        location = normalizer.clean_location(raw.location)
        summary = normalizer.clean_summary(raw.summary)
        salary = normalizer.clean_salary(raw.salary_text)
        job_type = normalizer.extract_job_type(title, summary) or raw.job_type
        content_hash = normalizer.make_content_hash(title, location, summary)

        job_data = {
            "source_id": source_id,
            "company": raw.company or company,
            "title": title,
            "location": location,
            "job_type": job_type,
            "summary": summary,
            "jd_url": raw.jd_url,
            "apply_url": raw.apply_url,
            "salary_text": salary,
            "posted_at": raw.posted_at,
            "content_hash": content_hash,
            "status": "active",
        }
        result = db.upsert_job(supabase, job_data)
        if result == "created":
            created += 1
        else:
            updated += 1
        urls.append(raw.jd_url)
    return created, updated, urls


# 平台配方注册表：key -> recipe 实例。
RECIPES: dict = {SpaKeywordRecipe.key: SpaKeywordRecipe()}


def resolve_recipe(query: str, city: str = "", company: str = "") -> Optional[str]:
    """根据入参选一个已注册的平台配方 key；无命中返回 None。"""
    for key, recipe in RECIPES.items():
        matcher = getattr(recipe, "matches", None)
        if callable(matcher) and matcher(query=query, city=city, company=company):
            return key
    return None


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------
def run_discovery(params: dict, supabase=None) -> dict:
    """
    执行一次按需发现，回写 discovery_runs 生命周期。返回汇总 dict（便于本地调试/单测断言）。
    params: parse_discovery_env() 的产物。
    """
    supabase = supabase or db.get_supabase()
    run_id = params["run_id"]

    # 1. queued -> running
    db.update_discovery_run(supabase, run_id, status="running")
    print(f"[discovery] run {run_id[:8]} running: query={params['query']!r} "
          f"city={params['city']!r} job_type={params['job_type']!r}")

    # 2. 解析平台配方
    recipe_key = resolve_recipe(params["query"], params["city"], params.get("company", ""))

    if not recipe_key:
        summary = {
            "status": "failed",
            "failure_reason": "no_recipe_matched",
            "jobs_created": 0,
            "jobs_updated": 0,
            "candidates_found": 0,
            "produced_jd_urls": [],
        }
        db.update_discovery_run(
            supabase,
            run_id,
            status=summary["status"],
            failure_reason=summary["failure_reason"],
            error_message="No browser-discovery recipe matched this query.",
            jobs_created=0,
            jobs_updated=0,
            candidates_found=0,
            finished_at=_now_iso(),
            diagnostics={"produced_jd_urls": [], "recipe": None},
        )
        print(f"[discovery] run {run_id[:8]} -> failed (no_recipe_matched)")
        return summary

    # 3. 跑命中的平台配方，入库，回写 produced_jd_urls + 终态。
    recipe = RECIPES[recipe_key]
    result = recipe.run(supabase=supabase, params=params)
    produced = result.get("produced_jd_urls", [])
    status = result.get("status", "partial_success" if produced else "failed")
    db.update_discovery_run(
        supabase,
        run_id,
        status=status,
        failure_reason=result.get("failure_reason"),
        error_message=result.get("error_message"),
        jobs_created=result.get("jobs_created", 0),
        jobs_updated=result.get("jobs_updated", 0),
        candidates_found=result.get("candidates_found", len(produced)),
        finished_at=_now_iso(),
        diagnostics={"produced_jd_urls": produced, "recipe": recipe_key},
    )
    print(f"[discovery] run {run_id[:8]} -> {status} via {recipe_key} "
          f"(created={result.get('jobs_created', 0)}, updated={result.get('jobs_updated', 0)})")
    return result


def run_from_env() -> bool:
    """run.py 入口：若处于发现模式则执行并返回 True；否则返回 False（让 run.py 走全量抓取）。"""
    params = parse_discovery_env(os.environ)
    if not params:
        return False
    try:
        run_discovery(params)
    except Exception as e:  # 失败也要把行落终态，否则前端永远卡在 running
        run_id = params["run_id"]
        try:
            db.update_discovery_run(
                db.get_supabase(),
                run_id,
                status="failed",
                failure_reason="discovery_exception",
                error_message=f"{type(e).__name__}: {e}"[:1000],
                finished_at=_now_iso(),
            )
        except Exception:
            pass
        raise
    return True
