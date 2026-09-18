"""停用影子门户源之后，把它名下的 active 岗标 removed（可逆）：按 jd_url 前缀 + 公司名点名。

治的病：同一家公司两个门户各挂一条源（规则 H），停用一条源只挡住「以后」，库里已有的 active 行
不会自己消失——该源不再抓，list-absence 撤岗轮不到它（wt / hotjob 的 supports_absence_liveness=False），
liveness-sweep 只判「对方关闭」，在招的重复岗会一直 active、用户一直看到两张卡。

为什么标 removed 不标 expired（同 remove_school_entries 的取舍）：
  · removed = 抓取漏看可复活，purge-expired 不删；哪天把源重新启用，下一轮重抓会把它们翻回 active —— 这正是可逆。
  · expired 次日被 purge 永久删除，影子源判断一旦错了就没有回头路。

护栏：默认 dry-run；--apply 必须 --url-prefix 点名门户 **且** --company 精确点名；只翻 status='active' 的行；参数绑定。

用法：
    python3 crawler/remove_jobs_by_url_prefix.py --url-prefix https://tbea.hotjob.cn/wt/TBEA/ --company 新疆特变电工集团
    python3 crawler/remove_jobs_by_url_prefix.py --url-prefix https://tbea.hotjob.cn/wt/TBEA/ --company 新疆特变电工集团 --apply
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


def run(cur, url_prefix, company, apply=False):
    """返回 (命中 active 行数, 实际改动行数或 None)。"""
    pattern = like_prefix(url_prefix)
    cur.execute(_COUNT_SQL, [company, pattern])
    (planned,) = cur.fetchone()
    if not apply or not planned:
        return planned, None
    cur.execute(_UPDATE_SQL, [company, pattern])
    if cur.rowcount != planned:
        print(f"  ⚠️ 计划改 {planned} 行、实际改 {cur.rowcount} 行（差额 = 两步之间状态变了的行）")
    return planned, cur.rowcount


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url-prefix", required=True, help="jd_url 前缀（门户级，完整 https 前缀）")
    ap.add_argument("--company", required=True, help="精确公司名，与前缀同时成立才动")
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    args = ap.parse_args(argv)
    if not args.url_prefix.startswith("https://") or len(args.url_prefix) < len("https://a.b/"):
        ap.error("--url-prefix 必须是完整 https 前缀（含主机与路径）")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出（本脚本只对自建香港 jobs 库生效）")
        return 1
    conn = jobs_db.get_conn()  # autocommit=True，别加 `with conn:`
    try:
        with conn.cursor() as cur:
            planned, updated = run(cur, args.url_prefix, args.company, apply=args.apply)
    finally:
        conn.close()
    if not planned:
        print(f"前缀 {args.url_prefix} 下没有 company='{args.company}' 的 active 行 —— 无事可做")
        return 0
    if args.apply:
        print(f"已标 {updated} 行 → status='removed'（可逆，purge 不删）")
    else:
        print(f"dry-run 将标 {planned} 行 → status='removed'（加 --apply 真写）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
