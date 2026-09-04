"""陈旧 active 体检：把「很久没再被抓到的在招岗」分三桶，并指明每桶归谁处置。

**这个脚本只读，没有 --apply，也不会有。** 原因见下面「为什么不能清」。

背景（2026-09-04 live 实测）：439,785 个 active 里 123,120 个（28%）三天没再被抓到。
一眼看去像「死岗堆积、该清」，但**逐源看完就会发现绝大多数根本不能判死**。

╔═ 为什么不能清 ═══════════════════════════════════════════════════════════════╗
║ CLAUDE.md 立过碑：「『列表里没有』≠『已撤岗』——除非先证明该列表是全集」。          ║
║ 2026-07-29 华为踩过：见列表只返 13 条而库里 460 个 active，就推断差额是死岗、        ║
║ 开了 list-absence 撤岗 → 逐个核验后 **460 个全部在招、0 个撤岗**（675e459→c9a7e73）。║
║ 「库里 active ≫ 最近抓到的」有两种成因、处置完全相反：                              ║
║   ① 死岗堆积（该清）  ② 列表接口只返子集 / 没翻完（一清就是删在招岗）                ║
║ 本脚本的三桶就是用来**区分这两者**的，不是用来批量清的。                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

三桶（判据是**源级**的「这个源最近还抓到过东西吗」，不是岗位级的）：

  A 源近 2 天仍在抓 → **不可判死**。源活着、我们也在抓，这个岗没被再看到，
    最可能的解释是**列表没翻完**（外企 ATS 动辄上万条、我们有 list_cap 和限流），
    而不是它死了。实测这一桶占 92%（113,245 行），典型是 Amazon 12,470 行里 7,761 行、
    Wells Fargo 6,958 里 4,967。归属：**抓全率**（见 CLAUDE.md「抓全自愈 paginate_all」
    与 reported_total 契约），不是探活的活，更不是去重的活。

  B 源近 14 天抓过、但已停几天 → 观察。可能是 CI 排期/限流，也可能刚坏。

  C 源已停 ≥14 天 → **源健康问题**。整源不再产出（武田制药 2,113 行停 34 天、
    凯莱英停 70 天、中国钢研停 77 天）。这些岗的「在招」已经很久没被任何东西验证过，
    但**依然不能因此判死**——源坏了不代表对方撤了岗。归属：修源；真要确认岗位死活，
    走**逐岗 detail 判死**（ENRICH_REGISTRY + liveness-sweep），那条路才有资格改 status。

📌 通用规矩（CLAUDE.md）：不可逆操作前，核验样本量必须匹配影响面——要清 3,862 行
   就得核验 3,862 行，抽查 2 个不算数。而 expired 当天会被 purge **永久删除**。

用法：
    python3 crawler/audit_stale_active.py                # 三桶概览 + 桶 C 清单
    python3 crawler/audit_stale_active.py --bucket-c 40  # 多列几个桶 C 的源
    python3 crawler/audit_stale_active.py --company 比亚迪  # 单看某家
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402

# 源级「还在抓吗」的分界。2 天而不是 1 天：daily CI 有排期抖动，1 天会把正常源误判成停了。
FRESH_SOURCE_DAYS = 2
DEAD_SOURCE_DAYS = 14
# 岗位级「陈旧」的分界，只用于报数，不用于任何判定。
STALE_JOB_DAYS = 3

_BUCKET_SQL = f"""
with s as (
  select source_id,
         count(*) as rows_n,
         count(*) filter (where last_seen_at < now() - interval '{STALE_JOB_DAYS} days') as stale_n,
         max(last_seen_at) as src_last
  from jobs where status = 'active' {{company_filter}}
  group by 1)
select case
         when src_last > now() - interval '{FRESH_SOURCE_DAYS} days'
           then 'A 源仍在抓 → 列表没翻完，不可判死（抓全率的活）'
         when src_last > now() - interval '{DEAD_SOURCE_DAYS} days'
           then 'B 源近期抓过、已停几天 → 观察'
         else 'C 源已停 >= {DEAD_SOURCE_DAYS} 天 → 源健康问题（修源，别判死）'
       end as bucket,
       count(*) as sources_n, sum(rows_n) as active_rows, sum(stale_n) as stale_rows
from s group by 1 order by 1
"""

_BUCKET_C_SQL = f"""
with s as (
  select source_id, count(*) as rows_n, max(last_seen_at) as src_last
  from jobs where status = 'active' {{company_filter}}
  group by 1)
select c.company, s.rows_n, s.src_last::date, (now()::date - s.src_last::date) as days_stopped
from s join lateral (select company from jobs where source_id = s.source_id limit 1) c on true
where s.src_last < now() - interval '{DEAD_SOURCE_DAYS} days'
order by s.rows_n desc limit %s
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="陈旧 active 三桶体检（只读）")
    ap.add_argument("--company", action="append", default=[], help="只看某家（可重复，子串匹配）")
    ap.add_argument("--bucket-c", type=int, default=20, help="桶 C 列几行（默认 20）")
    args = ap.parse_args()

    company_filter, params = "", []
    if args.company:
        company_filter = " and (" + " or ".join(["company ilike %s"] * len(args.company)) + ")"
        params = [f"%{c}%" for c in args.company]

    conn = jobs_db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("select count(*), count(*) filter (where last_seen_at < now() - interval "
                        f"'{STALE_JOB_DAYS} days') from jobs where status='active'{company_filter}", params)
            total, stale = cur.fetchone()
            pct = (100.0 * stale / total) if total else 0.0
            print(f"active 总数 {total:,}，其中 {STALE_JOB_DAYS} 天没再抓到 {stale:,}（{pct:.1f}%）\n")

            cur.execute(_BUCKET_SQL.format(company_filter=company_filter), params)
            print(f"{'分桶':<52} {'源数':>6} {'在招行数':>10} {'其中陈旧':>10}")
            for bucket, sources_n, active_rows, stale_rows in cur.fetchall():
                print(f"{bucket:<52} {sources_n:>6} {active_rows:>10,} {stale_rows:>10,}")

            cur.execute(_BUCKET_C_SQL.format(company_filter=company_filter), params + [args.bucket_c])
            rows = cur.fetchall()
            if rows:
                print(f"\n桶 C —— 整源已停 >= {DEAD_SOURCE_DAYS} 天（去修源；判岗位死活走逐岗 detail）：")
                print(f"  {'公司':<34} {'在招行数':>9} {'最后抓到':>12} {'停了':>6}")
                for company, rows_n, src_last, days in rows:
                    print(f"  {str(company)[:32]:<34} {rows_n:>9,} {str(src_last):>12} {days:>4}天")
    finally:
        conn.close()

    print("\n⚠️ 本脚本不改任何数据，也不该改。桶 A 是「没翻完」不是「死了」——"
          "\n   要判死只能走逐岗 detail（ENRICH_REGISTRY + liveness-sweep），"
          "\n   list-absence 撤岗只对「已证明列表返全集」的源开（见 CLAUDE.md 华为立碑）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
