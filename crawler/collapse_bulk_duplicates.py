"""批量门店发布源的存量去重：同一个「角色 × 城市」只留一条，其余标 removed。

治的病（2026-09-04 实测）：单源上限从 600 抬到 8000 之后，一轮多入库 5.2 万个岗，
其中 2.1 万是三家门店批量发布的同质副本——星巴克 9,044 行归一后只有 36 种角色。
可测后果：杭州 20%、上海 12.1%、北京 9.7% 的在招岗变成这几家的门店副本。
`adapters.base.RepetitionBrake` 已经止住**新增**，这个脚本清的是**存量**。

为什么标 removed 而不是 expired：
  · removed = 「抓取漏看，可复活」——purge-expired.yml 明确不删它，jobs_db 的 upsert 再见到会
    自动转回 active（REAPPEARED）。这是可逆操作，符合「不可逆操作前核验样本量必须匹配影响面」。
  · expired = 逐岗探活**确认撤岗**，当天会被 purge 永久删除。这些岗是真的在招，标 expired 就是误杀。

为什么按「角色 × 城市」而不是只按角色：
  上海的星级咖啡师和成都的星级咖啡师是两个**不同的机会**，用户按城市筛选时两边都得有。
  实测 22,120 行折叠成 2,824 个（角色 × 城市），覆盖 692 个城市一个不少。

保留哪一条：last_seen_at 最新的（并列时取 first_seen_at 最新）——保证留下的是还在被抓到的活岗。

⚠️ **写库必须显式点名公司**（--company 可重复），不提供「一键全清」：
   自动识别只用来**报告**影响面。原因是「重复率高」有两种成因、处置完全相反——
     ① 真·批量门店发布（星巴克/来伊份/喜茶）→ 该折叠，且 RepetitionBrake 已止住新增；
     ② 存量陈旧 active 堆积（比亚迪 6,313 行里 3,862 行三天没再被抓到）→ 那是探活子系统的活，
        折叠它只会把「该判死的岗」伪装成「已去重」，且它的 adapter 没有刹车、下一轮 upsert
        会把 removed 全部翻回 active，纯属白折腾。
   分不清是哪一种就先跑 dry-run 看 last_seen_at 分布，别一把梭。

用法（默认 dry-run，只报数不写库）：
    python3 crawler/collapse_bulk_duplicates.py                          # 看影响面（全量报告）
    python3 crawler/collapse_bulk_duplicates.py --company 星巴克 --apply  # 真的写，点名一家
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402

# 入选门槛：够大 + 够重复，两个条件缺一不可。
#   MIN_ROWS  防止把「只有 3 个岗、恰好同名」的小源误判成批量发布。
#   MIN_REPEAT_RATE 0.90 是实测选出来的：批量源 0.996/0.988/0.959/0.926，
#   正常源 0.477（奇瑞）/0.464（新东方）/0.427（我爱我家）——两组差一个数量级，中间没有骑墙的。
MIN_ROWS = 1000
MIN_REPEAT_RATE = 0.90

# 归一成「角色核」：去括号内容（含 (J726033) 岗位号）、去数字、去空白。
# 与 adapters.base.normalize_title_for_repetition 同口径；这里用 SQL 表达以免把 38 万行拉到本地。
# ⚠️ 少了那边的「去开头姓名段」——SQL 里做这步会把「上海-店长」的城市前缀也吃掉，
#    对**存量折叠**来说宁可少归一（多留几行）也不能多归一（把不同角色并成一个）。
_NORM_SQL = (
    "regexp_replace(regexp_replace(regexp_replace("
    "title, '[（(\\[【][^）)\\]】]*[）)\\]】]', '', 'g'), '[0-9]+', '', 'g'), '\\s+', '', 'g')"
)


def find_bulk_companies(cur, only_companies=()):
    """返回 [(company, 行数, 角色数, 重复率, 角色x城市)]，按可折叠行数降序。"""
    where = "status = 'active'"
    params = []
    if only_companies:
        where += " and (" + " or ".join(["company like %s"] * len(only_companies)) + ")"
        params.extend(f"%{c}%" for c in only_companies)
    cur.execute(
        f"""
        with j as (select company, location, {_NORM_SQL} as nt from jobs where {where}),
        agg as (
          select company, count(*) rows_n, count(distinct nt) roles,
                 1 - count(distinct nt)::numeric / count(*) repeat_rate,
                 count(distinct (nt || '@' || coalesce(location, ''))) groups_n
          from j group by 1)
        select company, rows_n, roles, round(repeat_rate, 3), groups_n
        from agg where rows_n >= %s and repeat_rate >= %s
        order by rows_n - groups_n desc
        """,
        params + [MIN_ROWS, MIN_REPEAT_RATE],
    )
    return cur.fetchall()


def collapse(cur, company, apply=False):
    """把 company 下每个 (角色, 城市) 组里除最新一条外的 active 岗标 removed。返回影响行数。"""
    select_ids = f"""
        select id from (
          select id, row_number() over (
                   partition by {_NORM_SQL}, coalesce(location, '')
                   order by last_seen_at desc nulls last, first_seen_at desc nulls last, id
                 ) rn
          from jobs where status = 'active' and company = %s
        ) t where rn > 1
    """
    if not apply:
        cur.execute(f"select count(*) from ({select_ids}) x", [company])
        return cur.fetchone()[0]
    cur.execute(f"update jobs set status = 'removed' where id in ({select_ids})", [company])
    return cur.rowcount


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    ap.add_argument("--company", action="append", default=[],
                    help="按子串点名公司，可重复；--apply 时必填（见模块注释）")
    args = ap.parse_args()
    if args.apply and not args.company:
        ap.error("--apply 必须配 --company 点名公司；不提供一键全清，理由见模块注释")

    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出（本脚本只对自建香港 jobs 库生效）")
        return 1
    conn = jobs_db.get_conn()
    try:
        with conn, conn.cursor() as cur:
            rows = find_bulk_companies(cur, args.company)
            # dry-run 顺带把 last_seen_at 新鲜度打出来 —— 区分「批量发布」和「陈旧堆积」的唯一依据
            if not rows:
                print("没有公司同时满足 行数>=%d 且 重复率>=%.2f —— 无需折叠" % (MIN_ROWS, MIN_REPEAT_RATE))
                return 0
            print(f"{'公司':<22}{'行数':>7}{'角色':>7}{'重复率':>8}{'角色x城市':>11}{'折叠':>8}{'3天没再见到':>12}")
            total = 0
            for company, rows_n, roles, rate, groups_n in rows:
                cur.execute("select count(*) from jobs where status='active' and company=%s "
                            "and last_seen_at < now() - interval '3 days'", [company])
                stale = cur.fetchone()[0]
                affected = collapse(cur, company, apply=args.apply)
                total += affected
                print(f"{company:<22}{rows_n:>7}{roles:>7}{float(rate):>8.3f}"
                      f"{groups_n:>11}{affected:>8}{stale:>12}")
            print(f"\n{'已折叠' if args.apply else 'dry-run 将折叠'} {total} 行 → status='removed'（可逆，purge 不删）")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
