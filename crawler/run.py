"""
Job Radar Crawler — 主入口。
由 GitHub Actions 每天调用，也可以本地手动运行。

用法：
  python run.py                  # 跑全部 enabled sources
  python run.py --source apple   # 只跑指定 source（按 adapter_name）
"""
import argparse
import sys
import traceback

import db
import normalizer
from robots import check_robots
from adapters.apple import AppleAdapter
from adapters.baidu import BaiduAdapter
from adapters.jd import JdAdapter
from adapters.haier import HaierAdapter
from adapters.siemens import SiemensAdapter
from adapters.tencent import TencentAdapter
from adapters.bytedance import BytedanceAdapter
from adapters.feishu import NioAdapter, XpengAdapter, HorizonAdapter, XiaomiAdapter
from adapters.greenhouse import GreenhouseAdapter
from adapters.lever import LeverAdapter


ADAPTERS = {
    "apple": AppleAdapter(),
    "baidu": BaiduAdapter(),
    "jd": JdAdapter(),
    "haier": HaierAdapter(),
    "siemens": SiemensAdapter(),
    "tencent": TencentAdapter(),
    "bytedance": BytedanceAdapter(),
    "nio_feishu": NioAdapter(),
    "xpeng_feishu": XpengAdapter(),
    "horizon_feishu": HorizonAdapter(),
    "xiaomi_feishu": XiaomiAdapter(),
    # 外企 ATS（通用适配器，按公司加 sources 行；parse 已裁到在华岗位）
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
}


def run_crawl(filter_adapter: str = None):
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

    print(f"[crawler] 开始抓取 {len(sources)} 个源...")

    total_created = 0
    total_updated = 0
    success_count = 0
    fail_count = 0

    for source in sources:
        company = source["company"]
        adapter_name = source.get("adapter_name") or ""
        source_url = source["source_url"]
        source_id = source["id"]

        adapter = ADAPTERS.get(adapter_name)
        if not adapter:
            print(f"  [skip] {company}: 未找到 adapter '{adapter_name}'")
            run_id = db.create_crawl_run(supabase, source_id)
            db.update_crawl_run(supabase, run_id, "failed",
                                error_message=f"Unknown adapter: {adapter_name}")
            fail_count += 1
            continue

        print(f"  [{adapter_name}] {company} ({source_url})")

        run_id = db.create_crawl_run(supabase, source_id)

        try:
            # 1. robots check
            robots_result = check_robots(source_url)
            if not robots_result["allowed"]:
                print(f"    robots blocked: {robots_result['reason']}")
                db.update_crawl_run(supabase, run_id, "skipped",
                                    error_message=f"robots.txt: {robots_result['reason']}")
                continue

            # 2. pre-check
            skip_reason = adapter.should_skip(source_url)
            if skip_reason:
                print(f"    skip: {skip_reason}")
                db.update_crawl_run(supabase, run_id, "skipped",
                                    error_message=skip_reason)
                continue

            # 3. fetch
            print(f"    fetching...")
            html = adapter.fetch(source_url)

            # 4. parse
            raw_jobs = adapter.parse(html)
            print(f"    parsed {len(raw_jobs)} jobs")

            if not raw_jobs:
                db.update_crawl_run(supabase, run_id, "success",
                                    jobs_found=0)
                continue

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
                continue

            # 5. normalize & upsert
            created = 0
            updated = 0
            for raw in valid_jobs:
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

            total_created += created
            total_updated += updated

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
            success_count += 1

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            print(f"    FAILED: {error_msg}")
            traceback.print_exc()
            db.update_crawl_run(supabase, run_id, "failed",
                                error_message=error_msg[:1000])
            fail_count += 1

    print(f"\n[crawler] 完成: {success_count} 成功, {fail_count} 失败, "
          f"created={total_created}, updated={total_updated}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Radar Crawler")
    parser.add_argument("--source", type=str, default=None,
                        help="只跑指定 adapter (apple/baidu/jd/haier/siemens)")
    args = parser.parse_args()

    # 按需「浏览器发现」模式（GitHub Actions workflow_dispatch 触发，通过 DISCOVERY_* 环境变量传参）。
    # 命中则跑发现并退出；否则走常规全量/单源抓取。
    import discovery
    if discovery.run_from_env():
        sys.exit(0)

    run_crawl(filter_adapter=args.source)
