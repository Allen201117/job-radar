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
import json
import os
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote

import china_keyword_expansion as cke
import company_industry as comp_ind
import db
import jobs_db
import normalizer
import ops_runs
from adapters.base import RawJob
from adapters.bytedance import BytedanceAdapter
from adapters.feishu import NioAdapter, XpengAdapter, HorizonAdapter, XiaomiAdapter
from adapters.tencent import TencentAdapter
from adapters.greenhouse import GreenhouseAdapter
from adapters.lever import LeverAdapter


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# 发现每源翻页默认上限（每页约 20 → 4 页≈80/家）。可被 DISCOVERY_MAX_PAGES 覆盖以按 CI 耗时权衡产出量。
# 注意是「每源」深度而非总量上限 —— 发现的价值在广度（多官方源），故不做跨源总量截断。
DEFAULT_DISCOVERY_MAX_PAGES = 4
MAX_DISCOVERY_MAX_PAGES = 10


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

    pages_raw = str(env.get("DISCOVERY_MAX_PAGES") or "").strip()
    try:
        max_pages = int(pages_raw) if pages_raw else DEFAULT_DISCOVERY_MAX_PAGES
    except ValueError:
        max_pages = DEFAULT_DISCOVERY_MAX_PAGES
    max_pages = max(1, min(max_pages, MAX_DISCOVERY_MAX_PAGES))

    return {
        "run_id": run_id,
        "query": query,
        "city": str(env.get("DISCOVERY_CITY") or "").strip(),
        "job_type": str(env.get("DISCOVERY_JOB_TYPE") or "").strip(),
        # 偏好底层逻辑：排除词（命中即丢弃）。城市/类型已在 API 端按「手动优先、否则偏好」解析好。
        "exclude": _parse_str_list(env.get("DISCOVERY_EXCLUDE")),
        # 跨行业门：用户目标行业 + 豁免公司（手动指名，不挡）。API 端解析好，空则不设门。
        "industries": _parse_str_list(env.get("DISCOVERY_INDUSTRIES")),
        "industry_exempt": _parse_str_list(env.get("DISCOVERY_INDUSTRY_EXEMPT")),
        "limit": limit,
        "max_pages": max_pages,
    }


def _parse_str_list(value) -> List[str]:
    """解析 JSON 数组或逗号分隔字符串为去空白字符串列表。"""
    s = str(value or "").strip()
    if not s:
        return []
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except (ValueError, TypeError):
        pass
    return [p.strip() for p in s.split(",") if p.strip()]


def parse_company_refresh_env(env: dict) -> Optional[dict]:
    """解析「刷新公司库」入参。非该模式（缺 mode/run_id）返回 None。
    scope（source_ids）+ filters 太长放不进 workflow input，故存在 discovery_runs.diagnostics，
    CI 端按 run_id 读 DB 取（见 run_company_refresh）。"""
    mode = str(env.get("DISCOVERY_MODE") or "").strip().lower()
    run_id = str(env.get("DISCOVERY_RUN_ID") or "").strip()
    if mode != "company_refresh" or not run_id:
        return None
    return {"run_id": run_id}


# ---------------------------------------------------------------------------
# 关键词匹配 / URL 构造（纯函数，可单测）
# ---------------------------------------------------------------------------
def is_campus_or_intern(job_type: str) -> bool:
    """页面所选类型是否属于「校招/实习」（决定字节走 /campus 板块而非 /experienced 社招板块）。"""
    return (job_type or "").strip() in ("实习", "校招")


def build_keyword_list_urls(adapter_name: str, query: str, job_type: str = "") -> Optional[List[str]]:
    """为支持关键词检索的源构造关键词专用列表 URL；不支持则返回 None（用适配器默认 list_urls 再后置过滤）。
    字节按页面所选类型选板块：实习/校招 → /campus，社招/全部 → /experienced（修「一味爬社招」）。"""
    term = (query or "").strip()
    if not term:
        return None
    if adapter_name == "bytedance":
        board = "campus" if is_campus_or_intern(job_type) else "experienced"
        return [f"https://jobs.bytedance.com/{board}/position?keyword={quote(term)}"]
    # 飞书系列表页的关键词参数不稳定，走默认 list_urls + 后置过滤，避免猜错参数。
    return None


def apply_keyword_to_adapter(adapter, adapter_name: str, query: str, job_type: str = "") -> None:
    """把关键词注入支持服务端检索的适配器（字节=列表 URL，腾讯=API keyword）；
    不支持的不动，靠 filter_raw_jobs 后置过滤兜底。
    字节选 /campus 板块时，同步把 detail_template 切到 /campus，保证产出的 jd_url 指向正确详情页。"""
    term = (query or "").strip()
    if not term:
        return
    kw_urls = build_keyword_list_urls(adapter_name, term, job_type)
    if kw_urls:
        adapter.list_urls = kw_urls
        if adapter_name == "bytedance" and is_campus_or_intern(job_type):
            adapter.detail_template = "https://jobs.bytedance.com/campus/position/{id}/detail"
    if adapter_name == "tencent":
        adapter.discovery_keyword = term


def select_discovery_targets(sources, allowlist) -> list:
    """从 sources 里挑出参与按需发现的源（adapter_name 在白名单内）。
    保留同一 adapter 的多个公司（为 Greenhouse/Lever/ATS 等多公司单适配器铺路）。"""
    return [s for s in (sources or []) if s.get("adapter_name") in allowlist]


def job_matches_query(raw: RawJob, query: str) -> bool:
    """岗位是否命中关键词。字段感知 + 职能门——与前端看板 jobMatchesChinaKeyword 同口径：
    标题命中始终算，正文（公司/地点/类型/摘要/薪资）命中须过职能门（治"pm→算法"跨职能误召）。
    双语同义词扩展 + 短缩写词边界，让中文发现词也能命中英文外企岗。空 query 视为命中。"""
    body = " ".join(
        filter(None, [raw.company, raw.location, raw.job_type, raw.summary, raw.salary_text])
    )
    return cke.job_matches(raw.title or "", body, query)


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


# 招聘三桶分类（与前端 lib/china-keyword-expansion.js recruitmentCategory 完全同口径）。
# 未知信号默认社招（社招是主体）；用于按页面所选「岗位类型」严格过滤发现结果。
_INTERN_TYPES = {"暑期实习", "日常实习", "实习"}
_CAMPUS_TYPES = {"校招", "管培生", "留学生专项"}
_KNOWN_CATEGORIES = {"社招", "校招", "实习"}


def recruitment_category(raw: RawJob) -> str:
    """把岗位归并到 社招 / 校招 / 实习 三桶之一（默认社招），与前端筛选一致。"""
    specific = normalizer.extract_job_type(raw.title or "", raw.summary) or (raw.job_type or "")
    if specific in _INTERN_TYPES:
        return "实习"
    if specific in _CAMPUS_TYPES:
        return "校招"
    low = specific.lower()
    if "实习" in specific or "intern" in low:
        return "实习"
    if any(k in specific for k in ("校招", "校园", "应届", "毕业生", "管培", "管理培训生", "留学生")) or \
            any(k in low for k in ("campus", "new grad", "graduate", "overseas student")):
        return "校招"
    return "社招"


def job_matches_type(raw: RawJob, job_type: str) -> bool:
    """岗位是否命中页面所选招聘类型。空 / 未知类型视为不过滤（命中）；否则按三桶精确匹配。"""
    want = (job_type or "").strip()
    if want not in _KNOWN_CATEGORIES:
        return True
    return recruitment_category(raw) == want


def job_excluded(raw: RawJob, exclude: Optional[List[str]]) -> bool:
    """命中用户偏好里的排除词则丢弃（子串小写匹配，搜 标题/公司/地点/类型/摘要/薪资）。空列表=不排除。"""
    terms = [str(t).strip().lower() for t in (exclude or []) if str(t).strip()]
    if not terms:
        return False
    hay = " ".join(
        filter(None, [raw.title, raw.company, raw.location, raw.job_type, raw.summary, raw.salary_text])
    ).lower()
    return any(t in hay for t in terms)


def source_industry_ok(company, industries, exempt=None) -> bool:
    """源级跨行业门（爬虫端「行业-公司-岗位」）：源公司的行业与用户目标行业相容则放行。
    放行当：用户没填可识别行业 / 公司行业判不出 / 行业 ∈ 用户目标；额外——
    手动指名的公司（exempt = 用户 target_companies + 当前筛选 company，substring）一律豁免，
    与 lib/scoring.ts「公司命中不受跨行业门约束」同口径。整源同公司 → 判一次即可，省去抓取。"""
    cl = str(company or "").lower()
    if any(e and str(e).strip().lower() in cl for e in (exempt or [])):
        return True
    return comp_ind.job_industry_allowed(company, industries)


def filter_raw_jobs(
    raw_jobs: List[RawJob], query: str, city: str, job_type: str = "",
    exclude: Optional[List[str]] = None,
) -> List[RawJob]:
    """按关键词 + 城市 + 招聘类型 + 偏好排除词严格过滤抓到的岗位（纯函数）。
    类型过滤是所有源通用的兜底：即便板块选错/混排，也只放行页面所选类型；
    exclude 来自用户偏好 exclude_keywords，命中即丢，保证不抓与用户背景无关/不想要的岗位。"""
    return [
        raw
        for raw in raw_jobs
        if job_matches_query(raw, query)
        and job_matches_city(raw, city)
        and job_matches_type(raw, job_type)
        and not job_excluded(raw, exclude)
    ]


# ---------------------------------------------------------------------------
# 平台配方
# ---------------------------------------------------------------------------
class SpaKeywordRecipe:
    """对已知官方源（字节 + 飞书系 + 腾讯）按关键词做拦截/接口抓取并入库。"""

    key = "spa_keyword"
    # adapter_name -> Adapter 类（与 run.py ADAPTERS / sources.adapter_name 对齐）。
    # 多公司单适配器（未来 greenhouse/lever 等）也只需在此登记一次，靠 sources 行扩公司。
    DISCOVERY_ADAPTERS = {
        "bytedance": BytedanceAdapter,
        "nio_feishu": NioAdapter,
        "xpeng_feishu": XpengAdapter,
        "horizon_feishu": HorizonAdapter,
        "xiaomi_feishu": XiaomiAdapter,
        "tencent": TencentAdapter,
        # 外企 ATS（通用适配器，多公司靠 sources 行扩展；parse 已裁到在华岗位）
        "greenhouse": GreenhouseAdapter,
        "lever": LeverAdapter,
    }
    discovery_max_pages = DEFAULT_DISCOVERY_MAX_PAGES  # 默认每源翻页；可被 params["max_pages"]（DISCOVERY_MAX_PAGES）覆盖

    def matches(self, query: str, city: str = "", company: str = "") -> bool:
        # 目前是唯一的种子配方：有关键词即适用。
        return bool((query or "").strip())

    def run(self, supabase, params: dict) -> dict:
        query = params["query"]
        city = params.get("city", "")
        job_type = params.get("job_type", "")
        exclude = params.get("exclude") or []
        industries = params.get("industries") or []
        industry_exempt = params.get("industry_exempt") or []
        max_pages = params.get("max_pages") or self.discovery_max_pages

        sources = db.get_sources(supabase)
        # 源驱动：遍历白名单内的每个 enabled source（支持同一 adapter 多公司）。
        targets = select_discovery_targets(sources, self.DISCOVERY_ADAPTERS)
        # 跨行业门（爬虫端）：丢弃行业与用户目标不符的源（手动指名公司豁免）。
        if industries:
            targets = [t for t in targets
                       if source_industry_ok(t.get("company") or t.get("adapter_name"), industries, industry_exempt)]

        if not targets:
            return {
                "status": "failed",
                "failure_reason": "no_spa_sources_in_db",
                "error_message": "No discovery source rows found; apply migration 010 (+ future seeds).",
                "jobs_created": 0,
                "jobs_updated": 0,
                "candidates_found": 0,
                "produced_jd_urls": [],
            }

        produced: List[str] = []
        created = updated = 0
        errors: List[str] = []

        for source in targets:
            adapter_name = source.get("adapter_name")
            adapter_cls = self.DISCOVERY_ADAPTERS.get(adapter_name)
            if not adapter_cls:
                continue
            company = source.get("company") or adapter_name
            try:
                adapter = adapter_cls()
                try:
                    adapter.max_pages = min(getattr(adapter, "max_pages", 2), max_pages)
                except Exception:
                    pass
                apply_keyword_to_adapter(adapter, adapter_name, query, job_type)

                html = adapter.fetch(source["source_url"])
                raw_jobs = adapter.parse(html)
                matched = filter_raw_jobs(raw_jobs, query, city, job_type, exclude)
                c, u, urls = _upsert_raw_jobs(
                    supabase, source["id"], company, source["source_url"], matched
                )
                created += c
                updated += u
                produced.extend(urls)
                print(f"[discovery]   {company}({adapter_name}): parsed={len(raw_jobs)} "
                      f"matched={len(matched)} created={c} updated={u}")
            except Exception as e:
                errors.append(f"{adapter_name}: {type(e).__name__}: {e}")
                print(f"[discovery]   {adapter_name}: FAILED {type(e).__name__}: {e}")
                continue

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


import threading as _threading
_disc_tls = _threading.local()


def _jobs_conn():
    """Phase 1：每线程独立香港 jobs 库连接（httpx 分档并发时每 worker 一个）。"""
    c = getattr(_disc_tls, "conn", None)
    if c is None:
        c = jobs_db.get_conn()
        _disc_tls.conn = c
    return c


def _upsert_raw_jobs(supabase, source_id, company, source_url, raw_jobs):
    """质量门校验 + 归一化 + upsert（镜像 run.py 的入库逻辑）。返回 (created, updated, created_jd_urls)。
    jobs 写入：配了 JOBS_DATABASE_URL 写香港库（每线程独立连接），否则 Supabase。
    ⚠ 第三个返回值【只含真新增(created)的 jd_url】——刷新/发掘据此流式「带回」，绝不把重抓到的
    旧岗位(updated)混进带回充数（治用户痛点：刷新等半天「带回 199」、实际真新增才 2）。"""
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
        # 结构化字段从**完整** raw.summary 抽取（截断前），adapter 直填的优先
        experience = raw.experience or normalizer.extract_experience(raw.summary)
        education = raw.education or normalizer.extract_education(raw.summary)
        deadline = raw.deadline or normalizer.extract_deadline(raw.summary)

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
            "experience": experience,
            "education": education,
            "deadline": deadline,
            "content_hash": content_hash,
            "status": "active",
        }
        result = jobs_db.upsert_job(_jobs_conn(), job_data) if jobs_db.enabled() else db.upsert_job(supabase, job_data)
        if result == "created":
            created += 1
            urls.append(raw.jd_url)  # 只收真新增；重抓到的旧岗位(updated)不进「带回」，不充数
        else:
            updated += 1
    return created, updated, urls


def _safe_update_run(supabase, run_id, **fields):
    """增量心跳写入：失败只记日志不抛——漏一次心跳不致命（下个源会补），
    绝不让瞬时写失败炸掉整轮抓取（已 upsert 的岗位不丢可见性）。"""
    try:
        db.update_discovery_run(supabase, run_id, **fields)
    except Exception as e:  # noqa: BLE001
        print(f"[refresh]   (heartbeat write failed, ignored: {type(e).__name__}: {e})")


class CompanyRefreshRecipe:
    """「刷新公司库」配方：httpx 源【并发】先跑（按主机分队、跨主机并行，秒级出结果流式冒头）、
    浏览器源后置串行（chromium 渲染 2-5min，此时前端已先看到 httpx 结果，不再干等 10 分钟）；每抓完
    一个源就增量回写 discovery_runs（产出+进度+心跳）支撑前端流式。并发线程安全：jobs 连接(_jobs_conn)
    与 supabase(_get_thread_supabase) 均 thread-local，adapter 每源独立实例（防 per-source 状态串台，
    见 run.py:238），累加器与心跳回写用锁串行化（回写同一 run 行须互斥，避免并发覆盖丢更新）。"""

    key = "company_refresh"

    def run(self, supabase, run_id: str, source_ids: List[str], filters: dict, base_diag: dict) -> dict:
        import run as runmod  # 延迟导入避免与 run.py 循环依赖；复用 ADAPTERS + httpx 分档 + 并发基建
        from concurrent.futures import ThreadPoolExecutor

        query = filters.get("query") or filters.get("keyword") or ""
        city = filters.get("city") or ""
        job_type = filters.get("job_type") or filters.get("jobType") or ""
        exclude = filters.get("exclude") or []
        industries = filters.get("industries") or []
        industry_exempt = filters.get("industry_exempt") or []

        rows = db.get_sources_by_ids(supabase, source_ids)
        # 跨行业门（爬虫端）：丢弃「公司行业与用户目标行业不符」的源（手动指名公司豁免）。整源同公司 → 源级判一次，省抓取。
        if industries:
            kept = [s for s in rows
                    if source_industry_ok(s.get("company") or s.get("adapter_name"), industries, industry_exempt)]
            if len(kept) != len(rows):
                print(f"[refresh] 跨行业门跳过 {len(rows) - len(kept)}/{len(rows)} 源（用户目标行业 {industries}）")
            rows = kept
        total = len(rows)
        # 分档：httpx 源并发抓（秒级），浏览器源后置串行（每个 chromium 渲染 2-5min）。
        httpx_rows = [s for s in rows if runmod._is_httpx_safe(s.get("adapter_name"))]
        browser_rows = [s for s in rows if not runmod._is_httpx_safe(s.get("adapter_name"))]

        lock = _threading.Lock()
        seen: set = set()
        produced: List[str] = []
        acc = {"created": 0, "updated": 0, "done": 0}
        errors: List[str] = []

        def _fetch_one(source, sb):
            """抓单源 → 逐岗过滤 → upsert → 锁内累加 + 增量心跳。永不抛（单源失败不炸整批，对齐 run.py 约定）。"""
            adapter_name = source.get("adapter_name")
            company = source.get("company") or adapter_name
            registered = runmod.ADAPTERS.get(adapter_name)
            c = u = 0
            new_urls: List[str] = []
            err = None
            if registered is None:
                err = f"{adapter_name}: unknown_adapter"
            else:
                try:
                    # 每源独立实例：adapter 持 per-source 可变状态（workday/oracle 在 fetch 里按 url 设
                    # self._host 等），并发共享单例会互相覆写 → 岗位张冠李戴（run.py:238-243 实锤）。
                    adapter = type(registered)()
                    html = adapter.fetch(source["source_url"])
                    raw_jobs = adapter.parse(html)
                    # 逐岗按用户 关键词/城市/类型/排除词 过滤（CLAUDE.md #1/#2）后再入库 + 流式。
                    matched = filter_raw_jobs(raw_jobs, query, city, job_type, exclude)
                    c, u, new_urls = _upsert_raw_jobs(sb, source["id"], company, source["source_url"], matched)
                    print(f"[refresh]   {company}({adapter_name}): parsed={len(raw_jobs)} "
                          f"matched={len(matched)} created={c} updated={u}")
                except Exception as e:  # noqa: BLE001 —— 单源失败不炸整批
                    err = f"{adapter_name}: {type(e).__name__}: {e}"
                    print(f"[refresh]   {adapter_name}: FAILED {type(e).__name__}: {e}")
            # 锁内：累加 + 跨源去重 + 增量心跳（回写同一 run 行须互斥）。
            with lock:
                acc["created"] += c
                acc["updated"] += u
                for url in new_urls:  # 跨源去重，避免同一 jd_url 流式时重复成卡片
                    if url and url not in seen:
                        seen.add(url)
                        produced.append(url)
                if err:
                    errors.append(err)
                acc["done"] += 1
                _safe_update_run(
                    supabase, run_id,
                    status="running",
                    jobs_created=acc["created"], jobs_updated=acc["updated"],
                    candidates_found=len(produced),
                    diagnostics={**base_diag, "produced_jd_urls": produced[:200],
                                 "progress": {"done": acc["done"], "total": total},
                                 "last_update_at": _now_iso(), "recipe": self.key},
                )

        workers = max(1, int(os.environ.get("CRAWL_CONCURRENCY", "6") or "6"))
        # 阶段 1：httpx 源并发（按主机分队——同主机串行防限流、跨主机并行；每线程独立 supabase）。
        if httpx_rows and workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(
                    lambda q: [_fetch_one(s, runmod._get_thread_supabase()) for s in q],
                    runmod._group_by_host(httpx_rows)))
        else:
            for s in httpx_rows:
                _fetch_one(s, supabase)
        # 阶段 2：浏览器源串行后置（chromium 非线程安全，逐个跑；前端此时已先有 httpx 结果可看）。
        for s in browser_rows:
            _fetch_one(s, supabase)

        if produced:
            status = "success" if not errors else "partial_success"
            failure_reason = None
        elif errors:
            status = "failed"
            failure_reason = "all_sources_failed"
        else:
            status = "success"  # 跑完无匹配新岗 = 成功(0 新增)，不是失败
            failure_reason = None

        return {
            "status": status,
            "failure_reason": failure_reason,
            "error_message": ("; ".join(errors)[:1000] if errors else None),
            "jobs_created": acc["created"],
            "jobs_updated": acc["updated"],
            "produced_jd_urls": produced,
            "progress": {"done": total, "total": total},
        }


def run_company_refresh(params: dict, supabase=None) -> dict:
    """执行一次「刷新公司库」：认领守卫 → 读 scope/filters → 跑配方（增量回写）→ 终态回写。"""
    supabase = supabase or db.get_supabase()
    run_id = params["run_id"]

    # 1. 状态认领守卫：queued→running（仅当前 status='queued'）；已被认领则退出，防双 worker 抢同一 run。
    if not db.claim_discovery_run(supabase, run_id):
        print(f"[refresh] run {run_id[:8]} not claimable (already running/terminal), exit")
        return {"status": "skipped", "reason": "already_claimed"}

    # 2. 读 scope + filters（dispatch 端已存入 diagnostics）。
    run_row = db.get_discovery_run(supabase, run_id)
    diag = (run_row or {}).get("diagnostics") or {}
    source_ids = [str(x) for x in (diag.get("source_ids") or []) if str(x).strip()]
    filters = diag.get("filters") or {}
    base_diag = {"source_ids": source_ids, "filters": filters, "click_time": diag.get("click_time")}

    if not source_ids:
        db.update_discovery_run(
            supabase, run_id, status="failed", failure_reason="empty_scope",
            error_message="No source_ids in run diagnostics.", finished_at=_now_iso(),
            diagnostics={**base_diag, "produced_jd_urls": [], "progress": {"done": 0, "total": 0},
                         "last_update_at": _now_iso(), "recipe": CompanyRefreshRecipe.key},
        )
        print(f"[refresh] run {run_id[:8]} -> failed (empty_scope)")
        return {"status": "failed", "failure_reason": "empty_scope"}

    print(f"[refresh] run {run_id[:8]} running: {len(source_ids)} sources filters={filters}")

    # 3. 跑配方（增量回写在 recipe 内逐源进行）。
    recipe = CompanyRefreshRecipe()
    result = recipe.run(supabase, run_id, source_ids, filters, base_diag)
    produced = result.get("produced_jd_urls", [])

    # 4. 终态回写（保留 source_ids/filters，附最终 produced + progress）。
    db.update_discovery_run(
        supabase, run_id,
        status=result["status"],
        failure_reason=result.get("failure_reason"),
        error_message=result.get("error_message"),
        jobs_created=result.get("jobs_created", 0),
        jobs_updated=result.get("jobs_updated", 0),
        candidates_found=len(produced),
        finished_at=_now_iso(),
        diagnostics={**base_diag, "produced_jd_urls": produced[:200],
                     "progress": result.get("progress", {"done": 0, "total": 0}),
                     "last_update_at": _now_iso(), "recipe": CompanyRefreshRecipe.key},
    )
    print(f"[refresh] run {run_id[:8]} -> {result['status']} "
          f"(created={result.get('jobs_created', 0)}, updated={result.get('jobs_updated', 0)}, "
          f"produced={len(produced)})")
    return result


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


def _mark_run_failed(run_id: str, reason: str, exc: Exception) -> None:
    """异常兜底：把 run 落终态 failed，否则前端永远卡在 running。"""
    try:
        db.update_discovery_run(
            db.get_supabase(), run_id, status="failed", failure_reason=reason,
            error_message=f"{type(exc).__name__}: {exc}"[:1000], finished_at=_now_iso(),
        )
    except Exception:  # noqa: BLE001
        pass


def _record_discovery_ops(result: dict, started_at: str, mode: str) -> None:
    if result.get("status") == "skipped":
        return
    status = result.get("status")
    ledger_status = "failed" if status == "failed" else ("partial" if status == "partial_success" else "success")
    created = int(result.get("jobs_created") or 0)
    updated = int(result.get("jobs_updated") or 0)
    ops_runs.record_ops_run(
        db.get_supabase(),
        "discovery",
        {
            "checked": 1,
            "jobs_created": created,
            "jobs_updated": updated,
            "produced": created + updated,
            "mode": mode,
        },
        status=ledger_status,
        started_at=started_at,
        finished_at=_now_iso(),
    )


def run_from_env() -> bool:
    """run.py 入口：处于「刷新公司库」或「浏览器发现」模式则执行并返回 True；否则 False（让 run.py 走全量抓取）。"""
    # 「刷新公司库」模式优先（mode=company_refresh）。
    refresh = parse_company_refresh_env(os.environ)
    if refresh:
        started_at = _now_iso()
        try:
            result = run_company_refresh(refresh)
            _record_discovery_ops(result, started_at, "company_refresh")
        except Exception as e:  # 失败也要落终态，否则前端永远卡 running
            _mark_run_failed(refresh["run_id"], "refresh_exception", e)
            _record_discovery_ops({"status": "failed"}, started_at, "company_refresh")
            raise
        return True

    # 「按需浏览器发现」模式（mode=discovery）。
    params = parse_discovery_env(os.environ)
    if not params:
        return False
    started_at = _now_iso()
    try:
        result = run_discovery(params)
        _record_discovery_ops(result, started_at, "discovery")
    except Exception as e:  # 失败也要落终态，否则前端永远卡 running
        _mark_run_failed(params["run_id"], "discovery_exception", e)
        _record_discovery_ops({"status": "failed"}, started_at, "discovery")
        raise
    return True
