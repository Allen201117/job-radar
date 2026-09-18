"""香港 jobs 库「公司挂错名」的存量纠正：按 jd_url 前缀点名 + 旧公司名 → 新公司名。

治的病：接源时把租户记成了别的公司（248 精雕被记成京东、274 特变电工被记成领益智造），
sources.company 改对之后，jobs.company 在 jobs_db._UPDATE_COLS 里、**下一轮列表重抓会自愈**，
但那要等一晚，且长期没再被列表看到的行永远不会自愈。本脚本把存量一次改对。

三道护栏（同 remove_school_entries / collapse_bulk_duplicates 的规矩）：
  · 默认 dry-run 只报数；--apply 才写。
  · 写库必须 --url-prefix 点名（jd_url 前缀 = 租户/门户），且 --from 旧名精确匹配 —— 只改「这个门户下、
    现在挂着这个名」的行，别的公司同名行碰不到。
  · 参数一律绑定，不拼字符串。
不动 status / last_seen_at 等任何其它列；不区分 status（expired 行也一并改名，purge 删它时名字是对的）。

用法：
    python3 crawler/rename_job_company.py --url-prefix https://x.hotjob.cn/SUxxx/ --from 旧名 --to 新名            # dry-run
    python3 crawler/rename_job_company.py --url-prefix https://x.hotjob.cn/SUxxx/ --from 旧名 --to 新名 --apply    # 真写
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402

_COUNT_SQL = """
    select status, count(*)
    from jobs
    where company = %s
      and jd_url like %s
    group by status
    order by status
"""

_UPDATE_SQL = """
    update jobs
       set company = %s
     where company = %s
       and jd_url like %s
"""


def like_prefix(prefix):
    """把 URL 前缀变成 LIKE 模式：转义 % / _，尾部加 %。"""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


def run(cur, url_prefix, old_name, new_name, apply=False):
    """返回 {status: 行数}（dry-run 与 apply 同一份计数）。apply 时返回值另带 '_updated'。"""
    pattern = like_prefix(url_prefix)
    cur.execute(_COUNT_SQL, [old_name, pattern])
    report = {status: n for status, n in cur.fetchall()}
    if apply and report:
        cur.execute(_UPDATE_SQL, [new_name, old_name, pattern])
        report["_updated"] = cur.rowcount
        planned = sum(n for k, n in report.items() if k != "_updated")
        if cur.rowcount != planned:
            print(f"  ⚠️ 计划改 {planned} 行、实际改 {cur.rowcount} 行（差额 = 两步之间被并发写入的行）")
    return report


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url-prefix", required=True, help="jd_url 前缀（租户/门户级），只改这个前缀下的行")
    ap.add_argument("--from", dest="old_name", required=True, help="现在挂着的（错的）公司名，精确匹配")
    ap.add_argument("--to", dest="new_name", required=True, help="改成的公司名")
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    args = ap.parse_args(argv)
    if not args.url_prefix.startswith("https://") or len(args.url_prefix) < len("https://a.b/"):
        ap.error("--url-prefix 必须是完整 https 前缀（含主机与路径），防止前缀太短扫到别的门户")
    if args.old_name == args.new_name:
        ap.error("--from 与 --to 相同，无事可做")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出（本脚本只对自建香港 jobs 库生效）")
        return 1
    # get_conn() 已是 autocommit=True，别加 `with conn:`（见 backfill_grad_class 的注释）。
    conn = jobs_db.get_conn()
    try:
        with conn.cursor() as cur:
            report = run(cur, args.url_prefix, args.old_name, args.new_name, apply=args.apply)
    finally:
        conn.close()
    updated = report.pop("_updated", None)
    if not report:
        print(f"前缀 {args.url_prefix} 下没有 company='{args.old_name}' 的行 —— 无需改名")
        return 0
    print(f"{'status':<12}{'行数':>8}")
    for status, n in report.items():
        print(f"{status:<12}{n:>8}")
    total = sum(report.values())
    if args.apply:
        print(f"\n已改 {updated} 行：'{args.old_name}' → '{args.new_name}'")
    else:
        print(f"\ndry-run 将改 {total} 行：'{args.old_name}' → '{args.new_name}'（加 --apply 真写）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
