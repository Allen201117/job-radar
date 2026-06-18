"""
Job Radar Crawler — 主入口。
由 GitHub Actions 每天调用，也可以本地手动运行。

用法：
  python run.py                  # 跑全部 enabled sources
  python run.py --source apple   # 只跑指定 source（按 adapter_name）
"""
import argparse
import os
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import db
import jobs_db
import normalizer
from robots import check_robots
from adapters.apple import AppleAdapter, AppleChinaAdapter
from adapters.baidu import BaiduAdapter
from adapters.jd import JdAdapter
from adapters.haier import HaierAdapter
from adapters.siemens import SiemensAdapter
from adapters.tencent import TencentAdapter
from adapters.bytedance import BytedanceAdapter, BytedanceCampusAdapter
from adapters.feishu import NioAdapter, XpengAdapter, HorizonAdapter, XiaomiAdapter, FeishuGenericAdapter
from adapters.greenhouse import GreenhouseAdapter
from adapters.lever import LeverAdapter
from adapters.ashby import AshbyAdapter
from adapters.smartrecruiters import SmartRecruitersAdapter
from adapters.workday import WorkdayAdapter
from adapters.eightfold import EightfoldAdapter
from adapters.oracle import OracleAdapter
from adapters.china_ats import MokaAdapter, BeisenAdapter, CompanySpaAdapter
from adapters.hotjob import HotJobAdapter
from adapters.wt import WtAdapter
from adapters.amazon import AmazonAdapter
from adapters.phenom import PhenomAdapter
from adapters.microsoft import MicrosoftAdapter
from adapters.google import GoogleAdapter
from adapters.netease import NeteaseAdapter
from adapters.oppo import OppoAdapter
from adapters.xiaohongshu import XiaohongshuAdapter
from adapters.alibaba import AlibabaAdapter
from adapters.huawei import HuaweiAdapter
from adapters.ctrip import CtripAdapter


SUMMARY_STORAGE_LIMIT = int(os.environ.get("JOB_SUMMARY_STORAGE_LIMIT", "500") or "500")


def cap_summary_for_storage(summary):
    """Keep jobs.summary small enough for the hot database table."""
    if summary is None:
        return None
    text = str(summary).strip()
    if not text:
        return None
    if len(text) <= SUMMARY_STORAGE_LIMIT:
        return text
    return text[: max(0, SUMMARY_STORAGE_LIMIT - 3)].rstrip() + "..."


ADAPTERS = {
    "apple": AppleAdapter(),
    "apple_cn": AppleChinaAdapter(),  # Apple 在华岗位（保留全球 apple 源）
    "baidu": BaiduAdapter(),
    "jd": JdAdapter(),
    "haier": HaierAdapter(),
    "siemens": SiemensAdapter(),
    "tencent": TencentAdapter(),
    "bytedance": BytedanceAdapter(),
    "bytedance_campus": BytedanceCampusAdapter(),  # 字节校招/实习（与社招同平台）
    "nio_feishu": NioAdapter(),
    "xpeng_feishu": XpengAdapter(),
    "horizon_feishu": HorizonAdapter(),
    "xiaomi_feishu": XiaomiAdapter(),
    # 外企 ATS（通用适配器，按公司加 sources 行；parse 已裁到在华岗位）
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "smartrecruiters": SmartRecruitersAdapter(),  # 大量在华跨国企业用此 ATS（外企100强主力）
    "workday": WorkdayAdapter(),  # 外企100强主力：CXS API + location facet 服务端过滤到在华
    "eightfold": EightfoldAdapter(),  # 外企 ATS：eightfold.ai 公开接口 + location 服务端收窄到在华
    "oracle": OracleAdapter(),  # 外企自建门户主力：Oracle 招聘云 CE API + locationsFacet 过滤到在华
    "amazon": AmazonAdapter(),  # 外企自建巨头：Amazon.jobs 公开 search.json 按国家码筛在华
    "phenom": PhenomAdapter(),  # 外企自建巨头：Phenom People 公开 /api/jobs（AMD/L'Oréal 等）
    "microsoft": MicrosoftAdapter(),  # 外企自建巨头：MS pcsx httpx（apply.careers 子域绕 Akamai）
    "google": GoogleAdapter(),  # 外企自建巨头：Google careers 无头浏览器 DOM 抓取
    # 中国本土 ATS / 企业官网 SPA（通用适配器，按公司加 sources 行；host 从 source_url 动态解析）
    "moka": MokaAdapter(),
    "beisen": BeisenAdapter(),
    "company_spa": CompanySpaAdapter(),
    "feishu": FeishuGenericAdapter(),  # 飞书招聘数据驱动通用层（国内版 Workday）：host 从 source_url 解析
    "hotjob": HotJobAdapter(),  # HotJob / wecruit 通用层：TCL 等国内企业公开招聘站
    "wt": WtAdapter(),  # 老版 WinTalent：伊利/中广核/中国电信/现代等,直连 position/list JSON,零浏览器
    "netease": NeteaseAdapter(),  # 网易自建门户：hr.163.com queryPage 公开接口,零浏览器
    "oppo": OppoAdapter(),  # OPPO 校招门户：careers.oppo.com openapi 公开接口,零浏览器
    "xiaohongshu": XiaohongshuAdapter(),  # 小红书自建门户：job.xiaohongshu.com pageQueryPosition,零浏览器
    "alibaba": AlibabaAdapter(),  # 阿里集团 BU 门户通用层：position/search 公开接口,host 动态解析,零浏览器
    "huawei": HuaweiAdapter(),  # 华为自建门户：career.huawei.com getJob 公开接口,零鉴权零浏览器
    "ctrip": CtripAdapter(),  # 携程自建门户：careers.ctrip.com getJobAd 公开接口,零浏览器
}

# 中国本土公司源（每日后台爬取高优）：本土覆盖优先级 > 外企，排在外企 ATS 前先抓。
# 扩本土覆盖（新增本土 adapter）是当前最高优先 backlog，见 CLAUDE.md「核心产品原则#3」。
DOMESTIC_ADAPTERS = {
    "baidu", "jd", "bytedance", "bytedance_campus", "tencent",
    "nio_feishu", "xpeng_feishu", "horizon_feishu", "xiaomi_feishu", "haier",
    "moka", "beisen", "company_spa", "feishu", "hotjob", "wt", "netease", "oppo", "xiaohongshu", "alibaba", "huawei", "ctrip",  # 本土 ATS / 企业官网 SPA（扩覆盖主攻方向）
}


# ── P4 并发提速：按 adapter 抓取方式分档 ──────────────────────────────────────────
# httpx-safe = 纯 httpx 抓取、不起浏览器，线程安全可并发。故意用「白名单」而非「黑名单」：
# 未知 / 浏览器 adapter 一律落串行档（fail-safe），杜绝把 Playwright（sync API，非线程安全）
# 的 adapter 误并发跑崩夜间 cron。新增 httpx adapter 时显式加进来才享受并发。
_HTTPX_SAFE_ADAPTERS = {
    "apple", "apple_cn", "baidu", "jd", "haier", "siemens", "tencent",
    "greenhouse", "lever", "ashby", "smartrecruiters", "workday", "eightfold",
    "oracle", "amazon", "phenom", "microsoft", "hotjob", "wt",
    "netease", "oppo", "xiaohongshu", "alibaba", "huawei", "ctrip",  # PlaywrightAdapter 子类但自带 httpx fetch、无 super().fetch（已逐一核实）
}


def _is_httpx_safe(adapter_name) -> bool:
    return (adapter_name or "") in _HTTPX_SAFE_ADAPTERS


def _partition_by_tier(sources):
    """拆成 (并发档 httpx-safe, 串行档 浏览器/未知)，各自保持原顺序（本土优先排序不被打乱）。"""
    concurrent, serial = [], []
    for s in sources:
        (concurrent if _is_httpx_safe(s.get("adapter_name") or "") else serial).append(s)
    return concurrent, serial


# 并发档每线程独立 supabase 客户端。根因（2026-06-10 实锤，traceback 指向
# httpcore/_sync/http2.py + postgrest）：supabase-py 客户端走 HTTP/2 单连接多路复用，
# 被多个 worker 线程共享时并发读同一 socket → Errno 35（Resource temporarily unavailable）
# 大面积失败（hotjob 89/102 源全灭）。每线程一个客户端 = 每线程自己的连接，根治。
_TLS = threading.local()


def _get_thread_supabase():
    if not hasattr(_TLS, "sb"):
        _TLS.sb = db.get_supabase()
    return _TLS.sb


def _get_thread_jobs_conn():
    """Phase 1：每线程独立的自建香港 jobs 库连接（psycopg2 连接非线程安全，须每线程一个）。"""
    if not hasattr(_TLS, "jobs_conn"):
        _TLS.jobs_conn = jobs_db.get_conn()
    return _TLS.jobs_conn


def _group_by_host(sources):
    """并发档按主机分队：同主机一队（队内串行=礼貌爬取），跨主机并行。
    动机（2026-06-10 实锤）：102 个 hotjob 源几乎全在 wecruit.hotjob.cn 一台主机上，
    源级并发=对单服务器并发轰炸 → 对端限流，56 源 Errno 35 全灭。按主机分队后同主机
    请求天然串行，跨主机才吃并发，既礼貌又不触发限流。队序按首现顺序（保本土优先）。"""
    from urllib.parse import urlparse

    queues, index = [], {}
    for s in sources:
        try:
            host = urlparse(s.get("source_url") or "").netloc or f"_bad_{len(queues)}"
        except Exception:
            host = f"_bad_{len(queues)}"
        if host not in index:
            index[host] = len(queues)
            queues.append([])
        queues[index[host]].append(s)
    return queues


def _process_one_source(source, supabase) -> dict:
    """处理单个源：robots → should_skip → fetch → parse → 质量门 → upsert。
    返回 {status, created, updated}；**永不抛异常**（并发档 ex.map 迭代结果时不会炸整批）。
    status：success/partial_success=有效入库；empty/no_valid=无可入库岗；skipped=robots/预检跳过；failed=未知 adapter/异常。"""
    company = source["company"]
    adapter_name = source.get("adapter_name") or ""
    source_url = source["source_url"]
    source_id = source["id"]

    adapter = ADAPTERS.get(adapter_name)
    if not adapter:
        print(f"  [skip] {company}: 未找到 adapter '{adapter_name}'")
        try:
            run_id = db.create_crawl_run(supabase, source_id)
            db.update_crawl_run(supabase, run_id, "failed",
                                error_message=f"Unknown adapter: {adapter_name}")
        except Exception as e:  # DB 瞬时错误（如 Errno 35）也不许炸穿
            print(f"    crawl_run 记录失败: {e}")
        return {"status": "failed", "created": 0, "updated": 0}

    print(f"  [{adapter_name}] {company} ({source_url})")
    # run_id 的创建必须在 try 内：高负载下 Supabase 偶发 Errno 35（实锤于 2026-06-10 hotjob 全量
    # 并发跑），在 try 外抛出会炸穿「永不抛异常」约定 → ex.map 迭代时掀翻整批并发档。
    run_id = None

    try:
        run_id = db.create_crawl_run(supabase, source_id)
        # 1. robots check
        robots_result = check_robots(source_url)
        if not robots_result["allowed"]:
            print(f"    robots blocked: {robots_result['reason']}")
            db.update_crawl_run(supabase, run_id, "skipped",
                                error_message=f"robots.txt: {robots_result['reason']}")
            return {"status": "skipped", "created": 0, "updated": 0}

        # 2. pre-check
        skip_reason = adapter.should_skip(source_url)
        if skip_reason:
            print(f"    skip: {skip_reason}")
            db.update_crawl_run(supabase, run_id, "skipped",
                                error_message=skip_reason)
            return {"status": "skipped", "created": 0, "updated": 0}

        # 3. fetch
        print(f"    fetching...")
        html = adapter.fetch(source_url)

        # 4. parse
        raw_jobs = adapter.parse(html)
        print(f"    parsed {len(raw_jobs)} jobs")

        if not raw_jobs:
            db.update_crawl_run(supabase, run_id, "success",
                                jobs_found=0)
            return {"status": "empty", "created": 0, "updated": 0}

        valid_jobs = []
        invalid_reasons = {}
        for raw in raw_jobs:
            is_valid, reason = normalizer.validate_job_quality(raw, source_url)
            if is_valid:
                valid_jobs.append(raw)
            else:
                invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1

        if not valid_jobs:
            reason_text = ", ".join(
                f"{reason}: {count}" for reason, count in invalid_reasons.items()
            )
            print(f"    no high-quality jobs: {reason_text}")
            db.update_source_timestamp(supabase, source_id)
            db.update_crawl_run(
                supabase,
                run_id,
                "partial_success",
                jobs_found=len(raw_jobs),
                error_message=(
                    "Parsed rows, but none had high-quality job detail URLs. "
                    f"{reason_text}"
                ),
            )
            return {"status": "no_valid", "created": 0, "updated": 0}

        # 5. normalize & 批量 upsert
        #    逐岗 upsert 每岗 2 次 Supabase REST（先查后写）是快档 ~30min 瓶颈（全量数万岗→6-10万往返）。
        #    整源攒成一批，db.upsert_jobs_batch 压成「1 次批量 select + 分块 upsert/insert」。
        job_batch = []
        for raw in valid_jobs:
            title = normalizer.clean_title(raw.title)
            location = normalizer.clean_location(raw.location)
            full_summary = normalizer.clean_summary(raw.summary)
            summary = cap_summary_for_storage(full_summary)
            salary = normalizer.clean_salary(raw.salary_text)
            job_type = normalizer.extract_job_type(title, full_summary) or raw.job_type
            content_hash = normalizer.make_content_hash(title, location, full_summary)
            # 结构化字段从**完整** raw.summary 抽取（在 clean_summary 截断之前），adapter 直填的优先
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

            job_batch.append(job_data)

        # jobs 已迁自建香港 PG（Phase 1）：配了 JOBS_DATABASE_URL 写香港库；否则写 Supabase。
        if jobs_db.enabled():
            created, updated = jobs_db.upsert_jobs_batch(_get_thread_jobs_conn(), job_batch)
        else:
            created, updated = db.upsert_jobs_batch(supabase, job_batch)

        # 6. update source timestamp
        db.update_source_timestamp(supabase, source_id)

        # 7. update crawl_run
        db.update_crawl_run(
            supabase,
            run_id,
            "partial_success" if invalid_reasons else "success",
            jobs_found=len(valid_jobs),
            jobs_created=created,
            jobs_updated=updated,
            error_message=(
                "Skipped low-quality rows: "
                + ", ".join(
                    f"{reason}: {count}"
                    for reason, count in invalid_reasons.items()
                )
                if invalid_reasons
                else None
            ),
        )

        if invalid_reasons:
            print(f"    skipped invalid rows: {invalid_reasons}")
        print(f"    created={created}, updated={updated}")
        return {"status": "partial_success" if invalid_reasons else "success",
                "created": created, "updated": updated}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"    FAILED: {error_msg}")
        traceback.print_exc()
        try:
            if run_id is not None:
                db.update_crawl_run(supabase, run_id, "failed",
                                    error_message=error_msg[:1000])
        except Exception as e2:  # 失败路径里 DB 再抛（同类瞬时错误）也不许炸穿
            print(f"    crawl_run 记录失败: {e2}")
        return {"status": "failed", "created": 0, "updated": 0}


def run_crawl(filter_adapter: str = None, tier: str = "all",
              shard_index: int = 0, shard_count: int = 1):
    supabase = db.get_supabase()
    sources = db.get_sources(supabase)

    if not sources:
        print("[crawler] 没有 enabled sources，退出。")
        return

    if filter_adapter:
        sources = [s for s in sources if s.get("adapter_name") == filter_adapter]
        if not sources:
            print(f"[crawler] 没有匹配 adapter_name='{filter_adapter}' 的 enabled source，退出。")
            return

    # 本土优先：CI 时间有限时先抓中国本土公司源（高优），外企 ATS 殿后。
    sources.sort(key=lambda s: 0 if (s.get("adapter_name") or "") in DOMESTIC_ADAPTERS else 1)
    domestic_n = sum(1 for s in sources if (s.get("adapter_name") or "") in DOMESTIC_ADAPTERS)
    # P4 分档：httpx-safe 源并发抓（线程池，墙钟不再逐个叠加），浏览器(Playwright 非线程安全)/未知源串行抓。
    concurrent_sources, serial_sources = _partition_by_tier(sources)
    # 分档：快档 daily 只跑 httpx 并发档；重档 enrichment 跑 browser 串行档（或 all 全量）。默认 all=两档都跑（向后兼容）。
    if tier == "httpx":
        serial_sources = []
    elif tier == "browser":
        concurrent_sources = []
    # 源分片轮转：重档按天 1/shard_count（round-robin 每 shard_count 取第 shard_index 个），
    # 一周覆盖全量，单跑墙钟压到 GitHub Actions 6h 硬杀以下。默认 shard_count=1 = 不分片。
    if shard_count > 1:
        shard_index %= shard_count
        concurrent_sources = concurrent_sources[shard_index::shard_count]
        serial_sources = serial_sources[shard_index::shard_count]
    workers = max(1, int(os.environ.get("CRAWL_CONCURRENCY", "6") or "6"))
    active_n = len(concurrent_sources) + len(serial_sources)
    print(f"[crawler] tier={tier} shard={shard_index}/{shard_count}；本次抓取 {active_n}/{len(sources)} 源"
          f"（本土优先 {domestic_n} / 外企 {len(sources) - domestic_n}）"
          f"；并发档 {len(concurrent_sources)} 源 × {workers} 线程 / 串行档 {len(serial_sources)} 源（浏览器）...")

    results = []
    # 并发档先跑（httpx 快，CI 即便超时也先把这批收完）；workers=1 时退化为串行（安全阀，可用 CRAWL_CONCURRENCY=1 回退）。
    # 并发单位 = 主机队列（同主机串行防把单服务器打爆，跨主机并行吃满 workers）。
    if concurrent_sources and workers > 1:
        host_queues = _group_by_host(concurrent_sources)
        print(f"[crawler] 并发档按主机分 {len(host_queues)} 队（同主机串行、跨主机并行）")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            # 注意每线程用 _get_thread_supabase()（线程局部客户端），不共享主线程的 supabase。
            for queue_results in ex.map(
                    lambda q: [_process_one_source(s, _get_thread_supabase()) for s in q],
                    host_queues):
                results.extend(queue_results)
    else:
        results.extend(_process_one_source(s, supabase) for s in concurrent_sources)
    # 串行档：浏览器源逐个跑（domestic-browser 已被本土优先排序排在前，优先抓）。
    for s in serial_sources:
        results.append(_process_one_source(s, supabase))

    total_created = sum(r["created"] for r in results)
    total_updated = sum(r["updated"] for r in results)
    success_count = sum(1 for r in results if r["status"] in ("success", "partial_success"))
    fail_count = sum(1 for r in results if r["status"] == "failed")

    print(f"\n[crawler] 完成: {success_count} 成功, {fail_count} 失败, "
          f"created={total_created}, updated={total_updated}")
    return {"created": total_created, "updated": total_updated,
            "success": success_count, "failed": fail_count}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Radar Crawler")
    parser.add_argument("--source", type=str, default=None,
                        help="只跑指定 adapter (apple/baidu/jd/haier/siemens)")
    parser.add_argument("--tier", choices=["all", "httpx", "browser"],
                        default=(os.environ.get("CRAWL_TIER") or "all"),
                        help="all=两档都跑(默认/全量) | httpx=只跑并发档(快档 daily) | browser=只跑浏览器串行档(重档)")
    parser.add_argument("--shard-index", type=int,
                        default=int(os.environ.get("CRAWL_SHARD_INDEX", "0") or "0"),
                        help="源分片轮转：本次跑第 index 片（0-based；重档按星期几传 0-6）")
    parser.add_argument("--shard-count", type=int,
                        default=int(os.environ.get("CRAWL_SHARD_COUNT", "1") or "1"),
                        help="源分片轮转：共分几片（重档按天 1/7 轮转传 7；默认 1=不分片）")
    args = parser.parse_args()

    # 按需「浏览器发现」模式（GitHub Actions workflow_dispatch 触发，通过 DISCOVERY_* 环境变量传参）。
    # 命中则跑发现并退出；否则走常规全量/单源抓取（受 --tier / --shard-* 收窄）。
    import discovery
    if discovery.run_from_env():
        sys.exit(0)

    run_crawl(filter_adapter=args.source, tier=args.tier,
              shard_index=max(0, args.shard_index),
              shard_count=max(1, args.shard_count))
