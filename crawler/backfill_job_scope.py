"""按新的中文地名规则回填存量岗的 country_code / job_scope。

为什么需要单独回填：`country_code` / `job_scope` 在 `jobs_db._UPDATE_COLS` 里且不受
`_PRESERVE_IF_EMPTY` 保护，所以**还在对方列表上的岗**下一轮重抓会自然纠正；但已经不在
列表上、只靠 detail 探活维持的存量岗永远等不到那一轮，得手工推一把。

⚠️ 必须排在 daily-crawl 之后跑。抢在前面 = 那一轮跑的还是旧代码，upsert 会把刚回填好的
值原样刷回去，白干一场（2026-09-05 踩过）。

判据只看**地点字符串本身**，不看 source.regions：
  - `derive_country_code` 抽得出国家 → 写 country_code，job_scope 按大中华区与否定
    （地点能定国家时一律以地点为准，这是 derive_job_scope 既有的优先级）
  - 抽不出但地点自报「海外」「国外」 → country_code 留空，只把 job_scope 改成 overseas
只更新 `country_code is null` 的行 —— 已经有国家码的行本次改动一行都不动
（改前用全库 19,418 个不同地点对拍过：新旧规则**零改判**，全部变化都是 None → 有值）。

用法：
    python3 crawler/backfill_job_scope.py              # dry-run，只报数
    python3 crawler/backfill_job_scope.py --apply
    python3 crawler/backfill_job_scope.py --apply --status active
"""

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402
from geo import _GREATER_CHINA, derive_country_code, is_overseas_unspecified  # noqa: E402

# 一条 UPDATE 里塞多少个地点字符串。地点用 `= any(%s)` 走 jobs_location 索引，
# 批大到几千会让计划器改走全表扫，也更容易撞 statement_timeout。
LOCATION_BATCH = 200


def plan(cur, status=None):
    """扫全部不同地点，算出「该写什么」。返回 (country_plan, overseas_only, stats)。

    country_plan: {(code, scope): [location, ...]}
    overseas_only: [location, ...]  —— 自报海外但给不出国家的
    """
    where = ["country_code is null", "location is not null", "location <> ''"]
    params = []
    if status:
        where.append("status = %s")
        params.append(status)
    cur.execute(
        f"select location, count(*) from jobs where {' and '.join(where)} group by location",
        params,
    )
    rows = cur.fetchall()

    country_plan = {}
    overseas_only = []
    stats = Counter()
    stats["distinct_locations"] = len(rows)
    for location, n in rows:
        stats["rows_scanned"] += n
        code = derive_country_code(location)
        if code is not None:
            scope = "domestic" if code in _GREATER_CHINA else "overseas"
            country_plan.setdefault((code, scope), []).append(location)
            stats["rows_with_new_country"] += n
            stats[f"code:{code}"] += n
        elif is_overseas_unspecified(location):
            overseas_only.append(location)
            stats["rows_overseas_unspecified"] += n
        else:
            stats["rows_still_unknown"] += n
    return country_plan, overseas_only, stats


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def apply_plan(cur, country_plan, overseas_only, status=None):
    """真的写库。每条 UPDATE 都带 `country_code is null` 兜底，重跑幂等。"""
    status_sql = " and status = %s" if status else ""
    updated = Counter()

    for (code, scope), locations in sorted(country_plan.items()):
        for batch in _chunks(locations, LOCATION_BATCH):
            params = [code, scope, batch]
            if status:
                params.append(status)
            cur.execute(
                "update jobs set country_code = %s, job_scope = %s "
                f"where country_code is null and location = any(%s){status_sql}",
                params,
            )
            updated["country_code"] += cur.rowcount

    for batch in _chunks(overseas_only, LOCATION_BATCH):
        params = [batch]
        if status:
            params.append(status)
        cur.execute(
            "update jobs set job_scope = 'overseas' "
            "where country_code is null and coalesce(job_scope, 'domestic') <> 'overseas' "
            f"and location = any(%s){status_sql}",
            params,
        )
        updated["overseas_only"] += cur.rowcount

    return updated


def print_report(stats, updated, apply):
    print(f"不同地点写法：{stats['distinct_locations']}")
    print(f"候选行（country_code 为空）：{stats['rows_scanned']}")
    print(f"  能抽出国家：{stats['rows_with_new_country']}")
    print(f"  自报海外但无国家：{stats['rows_overseas_unspecified']}")
    print(f"  仍抽不出：{stats['rows_still_unknown']}")
    print("\n按国家码：")
    for key, n in sorted(
        ((k, v) for k, v in stats.items() if k.startswith("code:")),
        key=lambda kv: -kv[1],
    ):
        print(f"  {key[5:]:>4}  {n:>8}")
    if apply:
        print(f"\n实际写入 country_code：{updated['country_code']} 行")
        print(f"实际只改 job_scope：{updated['overseas_only']} 行")
    else:
        print("\ndry-run，未写库")


def main():
    parser = argparse.ArgumentParser(description="按新的中文地名规则回填 country_code / job_scope")
    parser.add_argument("--apply", action="store_true", help="真的写库；默认只 dry-run 报数")
    parser.add_argument("--status", help="只处理某个 status（如 active）；留空 = 全部")
    args = parser.parse_args()

    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出（本脚本只对自建香港 jobs 库生效）")
        return 1

    # jobs_db.get_conn() 已是 autocommit（见该函数注释），不要在这里包 `with conn:`。
    conn = jobs_db.get_conn()
    try:
        with conn.cursor() as cur:
            country_plan, overseas_only, stats = plan(cur, status=args.status)
            updated = apply_plan(cur, country_plan, overseas_only, status=args.status) if args.apply else Counter()
        print_report(stats, updated, apply=args.apply)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
