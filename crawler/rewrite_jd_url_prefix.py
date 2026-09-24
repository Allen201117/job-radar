"""香港 jobs 库「详情链接拼错门户路径 / 租户搬家」的存量纠正：把 active 行 jd_url 的前缀换成正确的。

治的病（2026-09-24 长安）：北森路由缓存里长安记成 `changan.zhiye.com/jobs/zwxq`，拼出来的
`/jobs/zwxq?jobAdId=…` 真渲染落在**列表页**，不是岗位详情（违反 jd_url 红线）；真详情是
`/social/detail?jobAdId=…`（同一个 jobAdId，真浏览器实测社招 / 校招岗都能打开）。
只改 beisen_routes.json 不够：下一轮列表重抓会按新链接的 canonical 找不到旧行 → 插一批新行，
旧行照样挂 active → 同一个岗两张卡。所以先把存量改对，重抓就会落到同一行上。
同类待办：Workday 租户搬数据中心（武田 wd3→wd502 / 奥的斯 wd5→wd504）也是「先改存量 jd_url host」。

改写 = 把前缀 from 换成 to，其余原样保留（jobAdId、query 都不动）；apply_url 以 from 开头的一并换。
canonical_jd_url 由表上的触发器（before update of jd_url）自动重算，不用管。

护栏（同 remove_jobs_by_url_prefix / rename_job_company 的规矩）：
  · 默认 dry-run 只报数；--apply 才写。
  · 必须 --from-prefix / --to-prefix 两个完整 https 前缀 + --company 精确点名，只动 status='active'。
  · to 不许以 from 开头（否则重跑会一直往后拼，不幂等）；两者不许相同。
  · 冲突跳过、不报错回滚：改完的链接若已有**别的 active 行**占着同一个 canonical（唯一索引），
    或已有同公司+标题+地点+新链接的行（表级唯一约束），这行不改，报数给人看。
  · 参数一律绑定，不拼字符串。

用法：
    python3 crawler/rewrite_jd_url_prefix.py --company '长安汽车 Changan' \
        --from-prefix https://changan.zhiye.com/jobs/zwxq --to-prefix https://changan.zhiye.com/social/detail
    （加 --apply 真写）
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402
from rename_job_company import like_prefix  # noqa: E402

_NEW_URL = "(%(to)s || substr(j.jd_url, char_length(%(from)s) + 1))"

_CONFLICT = f"""
    (exists (select 1 from jobs k
              where k.status = 'active' and k.id <> j.id
                and k.canonical_jd_url = public.canonicalize_jd_url({_NEW_URL}))
     or exists (select 1 from jobs k
                 where k.id <> j.id and k.company = j.company and k.title = j.title
                   and k.location = j.location and k.jd_url = {_NEW_URL}))
"""

_SCOPE = """
      from jobs j
     where j.status = 'active'
       and j.company = %(company)s
       and j.jd_url like %(pattern)s
"""

_COUNT_SQL = f"""
    select count(*) filter (where not {_CONFLICT}),
           count(*) filter (where {_CONFLICT})
    {_SCOPE}
"""

_UPDATE_SQL = f"""
    update jobs j
       set jd_url = {_NEW_URL},
           apply_url = case when j.apply_url like %(pattern)s
                            then %(to)s || substr(j.apply_url, char_length(%(from)s) + 1)
                            else j.apply_url end
     where j.status = 'active'
       and j.company = %(company)s
       and j.jd_url like %(pattern)s
       and not {_CONFLICT}
"""


def params_for(from_prefix, to_prefix, company):
    return {"from": from_prefix, "to": to_prefix, "company": company,
            "pattern": like_prefix(from_prefix)}


def run(cur, from_prefix, to_prefix, company, apply=False):
    """返回 (可改行数, 冲突跳过行数, 实际改动行数或 None)。"""
    params = params_for(from_prefix, to_prefix, company)
    cur.execute(_COUNT_SQL, params)
    planned, conflicts = cur.fetchone()
    if not apply or not planned:
        return planned, conflicts, None
    cur.execute(_UPDATE_SQL, params)
    if cur.rowcount != planned:
        print(f"  ⚠️ 计划改 {planned} 行、实际改 {cur.rowcount} 行（差额 = 两步之间状态变了的行）")
    return planned, conflicts, cur.rowcount


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-prefix", required=True, help="要换掉的 jd_url 前缀（完整 https 前缀）")
    ap.add_argument("--to-prefix", required=True, help="换成的 jd_url 前缀（完整 https 前缀）")
    ap.add_argument("--company", required=True, help="精确公司名，与前缀同时成立才动")
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    args = ap.parse_args(argv)
    for flag, value in (("--from-prefix", args.from_prefix), ("--to-prefix", args.to_prefix)):
        if not value.startswith("https://") or len(value) < len("https://a.b/"):
            ap.error(f"{flag} 必须是完整 https 前缀（含主机与路径）")
    if args.from_prefix == args.to_prefix:
        ap.error("--from-prefix 与 --to-prefix 相同，无事可做")
    if args.to_prefix.startswith(args.from_prefix):
        ap.error("--to-prefix 以 --from-prefix 开头：改完的行还会被下一次运行再改一遍（不幂等）")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出（本脚本只对自建香港 jobs 库生效）")
        return 1
    conn = jobs_db.get_conn()  # autocommit=True，别加 `with conn:`
    try:
        with conn.cursor() as cur:
            planned, conflicts, updated = run(cur, args.from_prefix, args.to_prefix,
                                              args.company, apply=args.apply)
    finally:
        conn.close()
    head = f"前缀 {args.from_prefix} → {args.to_prefix}（company='{args.company}'）"
    if conflicts:
        print(f"{head}：{conflicts} 行改完会与已有行冲突，跳过不动（请人工看一眼）")
    if not planned:
        print(f"{head}：没有可改的 active 行 —— 无事可做")
        return 0
    if args.apply:
        print(f"{head}：已改 {updated} 行")
    else:
        print(f"{head}：dry-run 将改 {planned} 行（加 --apply 真写）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
