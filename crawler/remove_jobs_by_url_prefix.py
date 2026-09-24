"""停用影子门户源之后，把它名下的 active 岗标 removed（可逆）：按 jd_url 前缀 + 公司名点名。

治的病：同一家公司两个门户各挂一条源（规则 H），停用一条源只挡住「以后」，库里已有的 active 行
不会自己消失——该源不再抓，list-absence 撤岗轮不到它（wt / hotjob 的 supports_absence_liveness=False），
liveness-sweep 只判「对方关闭」，在招的重复岗会一直 active、用户一直看到两张卡。

为什么标 removed 不标 expired（同 remove_school_entries 的取舍）：
  · removed = 抓取漏看可复活，purge-expired 不删；哪天把源重新启用，下一轮重抓会把它们翻回 active —— 这正是可逆。
  · expired 次日被 purge 永久删除，影子源判断一旦错了就没有回头路。

护栏：默认 dry-run；--apply 必须 --url-prefix 点名门户 **且** --company 精确点名；只翻 status='active' 的行；参数绑定。

--only-twins-under <保留门户前缀>（规则 H 的处置口径）：只标「在保留门户下有同一个 `#` 片段（hash 路由的岗位 id，
如 moka 的 `#/job/<uuid>`）且那行还在招」的行，只在影子门户出现的岗不动。没有 `#` 片段的行一律不算孪生（宁可不动）。
两个前缀不许互相包含，否则会拿自己当自己的孪生。

--twin-key 认「同一个岗」看哪一段（默认 hash，即上面的 `#` 片段）：
  · jobadid：北森的岗位 id 在 `?jobAdId=<uuid>` 里、没有 `#`。同一个北森门户挂在两个域名上时两边 id 相同
    （2026-09-24 实测 tjsemi→zhonghuan 758/758、ke.zhiye.com→campus.ke.com 45/45）。
  · title：标题一字不差。只给「两个不同租户各发一份同一个招聘需求」用——两边 id 不同，标题里都带同一个
    招聘编号（上实集团门户 vs 上海医药门户：`上海医药2027技术工培生(J12541)`，150 个在招里 117 个）。
    ⚠️ 标题里没有编号的租户别用它：同名不同岗会被当成孪生。

用法：
    python3 crawler/remove_jobs_by_url_prefix.py --url-prefix https://tbea.hotjob.cn/wt/TBEA/ --company 新疆特变电工集团
    python3 crawler/remove_jobs_by_url_prefix.py --url-prefix https://tbea.hotjob.cn/wt/TBEA/ --company 新疆特变电工集团 --apply
    python3 crawler/remove_jobs_by_url_prefix.py --company 作业帮 \
        --url-prefix 'https://app.mokahr.com/social-recruitment/zuoyebang/150144#' \
        --only-twins-under 'https://app.mokahr.com/social-recruitment/zuoyebang/41328#'
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402
from rename_job_company import like_prefix  # noqa: E402

_COUNT_SQL = """
    select count(*)
    from jobs
    where status = 'active'
      and company = %s
      and jd_url like %s
"""

_UPDATE_SQL = """
    update jobs
       set status = 'removed'
     where status = 'active'
       and company = %s
       and jd_url like %s
"""

# 保留门户那侧必须包成 array(...)：它是不相关子查询 → InitPlan 只扫一次表。写成 `in (select …)` 时
# 规划器把影子侧估成 1 行、选嵌套循环，实际 307 行就把 jobs 全表并行扫 307 遍（2026-09-23 香港库 EXPLAIN）。
# {c} = 列名前缀（影子侧为空，保留门户侧为 `k.`）。取不到键的行（空串）一律不算孪生。
_TWIN_KEYS = {
    "hash": "split_part({c}jd_url, '#', 2)",
    "jobadid": "lower(coalesce(substring({c}jd_url from 'jobAdId=([0-9A-Za-z-]+)'), ''))",
    "title": "coalesce({c}title, '')",
}


def twin_sql(key="hash"):
    expr = _TWIN_KEYS[key]
    return f"""
       and {expr.format(c='')} <> ''
       and {expr.format(c='')} = any(array(
             select {expr.format(c='k.')}
               from jobs k
              where k.status = 'active'
                and k.jd_url like %s))
"""


def run(cur, url_prefix, company, apply=False, twins_under=None, twin_key="hash"):
    """返回 (命中 active 行数, 实际改动行数或 None)。twins_under / twin_key 见模块注释。"""
    params = [company, like_prefix(url_prefix)]
    count_sql, update_sql = _COUNT_SQL, _UPDATE_SQL
    if twins_under:
        params.append(like_prefix(twins_under))
        count_sql, update_sql = count_sql + twin_sql(twin_key), update_sql + twin_sql(twin_key)
    cur.execute(count_sql, params)
    (planned,) = cur.fetchone()
    if not apply or not planned:
        return planned, None
    cur.execute(update_sql, params)
    if cur.rowcount != planned:
        print(f"  ⚠️ 计划改 {planned} 行、实际改 {cur.rowcount} 行（差额 = 两步之间状态变了的行）")
    return planned, cur.rowcount


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url-prefix", required=True, help="jd_url 前缀（门户级，完整 https 前缀）")
    ap.add_argument("--company", required=True, help="精确公司名，与前缀同时成立才动")
    ap.add_argument("--only-twins-under", help="保留门户的 jd_url 前缀：只标在它下面有在招孪生行的（见模块注释）")
    ap.add_argument("--twin-key", choices=sorted(_TWIN_KEYS), default="hash",
                    help="认孪生看哪一段：hash=`#` 片段 / jobadid=北森 jobAdId / title=标题一字不差（见模块注释）")
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    args = ap.parse_args(argv)
    for flag, value in (("--url-prefix", args.url_prefix), ("--only-twins-under", args.only_twins_under)):
        if value is not None and (not value.startswith("https://") or len(value) < len("https://a.b/")):
            ap.error(f"{flag} 必须是完整 https 前缀（含主机与路径）")
    keep = args.only_twins_under
    if args.twin_key != "hash" and not keep:
        ap.error("--twin-key 只在 --only-twins-under 时有意义")
    if keep and (keep.startswith(args.url_prefix) or args.url_prefix.startswith(keep)):
        ap.error("--only-twins-under 与 --url-prefix 互相包含：会拿自己当自己的孪生")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出（本脚本只对自建香港 jobs 库生效）")
        return 1
    conn = jobs_db.get_conn()  # autocommit=True，别加 `with conn:`
    try:
        with conn.cursor() as cur:
            planned, updated = run(cur, args.url_prefix, args.company, apply=args.apply,
                                   twins_under=args.only_twins_under, twin_key=args.twin_key)
    finally:
        conn.close()
    if not planned:
        twin_note = f"（且在 {args.only_twins_under} 下有在招孪生）" if args.only_twins_under else ""
        print(f"前缀 {args.url_prefix} 下没有 company='{args.company}' 的 active 行{twin_note} —— 无事可做")
        return 0
    if args.apply:
        print(f"已标 {updated} 行 → status='removed'（可逆，purge 不删）")
    else:
        print(f"dry-run 将标 {planned} 行 → status='removed'（加 --apply 真写）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
