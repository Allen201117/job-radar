"""wt 源「按院校设的投递入口」的存量清理：标题=院校名 ∧ 正文为空 → status='removed'。

治的病（2026-09-18 实测）：中广核（cgn.hotjob.cn，wt 适配器）把校园招聘做成「每所目标院校一条 post」——
postName 就是院校名（「北京建筑大学」「海外院校」「其他院校」，294 个 distinct 标题 × 不同城市 = 957 行），
workContent / serviceCondition 都只有一个句号。它们有独立 postId 和可打开的详情页，所以过了质量门；
jd_url 带 recruitType=1 → 全部判成「校招」，校招专区里于是有 957 张标题是大学名、点开没有任何 JD 的卡片。

入库侧 `adapters/wt.py::_is_school_entry` 已拦住新增（commit bc8ef08；crawl_runs 台账：
2026-09-17 20:55 UTC 起中广核每轮 jobs_found=0，之前每轮 957）。**这个脚本清的是闸门装上之前灌进去的存量。**

为什么标 removed 而不是 expired：
  · removed = 「抓取漏看，可复活」——purge-expired.yml 明确不删它；这是可逆操作。
  · expired = 逐岗探活确认撤岗，**次日就被 purge 永久删除**。这批行的复核成本不值得赌一次不可逆。
  · 既然 adapter 不再吐这些 post，list upsert 不会再见到它们 → 不会被翻回 active
    （REAPPEARED 只在「再次被抓到」时发生）。⚠️ 反过来：哪天有人把闸门拆了，下一轮重抓会把这批
    removed 全部复活——那是「可逆」的设计本身，不是 bug；先修闸门再重跑本脚本即可。

为什么 sweep 清不掉：wt 的 supports_absence_liveness=False；这些 post 在中广核官网是真实存在的页面，
liveness-sweep 的 _detail_wt（req_state=9501）判不了它们死。

判据 = 与 adapter **同一份**（WtAdapter._is_school_entry），不在这里另写一份：
  SQL 只做粗筛（wt 形态 jd_url + 标题含院校词 + 正文去掉「。/空白/【任职要求】」后为空），
  拉回来的每一行再过一遍 adapter 的正则，**只有两边都判真的 id 才写**。
  两边唯一已知差异是 PG `[:space:]` 与 Python `\\s` 对生僻空白字符的覆盖，方向是「SQL 少选」→ 漏清不误清。

⚠️ 写库必须 --company 点名（同 collapse_bulk_duplicates 的规矩）：dry-run 报全部命中公司；
   要清哪家由人看过报表再决定。不可逆操作前核验样本量必须匹配影响面——
   2026-09-18 已对中广核 957 行逐行核过（两条判据各 957 命中、交集 957、job_actions 引用 0）。

用法（默认 dry-run，只报数不写库）：
    python3 crawler/remove_school_entries.py                              # = --check
    python3 crawler/remove_school_entries.py --apply --company 中广核     # 真写，点名一家
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402
from adapters.wt import WtAdapter  # noqa: E402

# 与 adapters/wt.py 的 _DETAIL_TPL 同形：{origin}/wt/{brand}/mobweb/position/detail?brandCode=…
# 标题词表 = _INSTITUTION_TITLE 里的后缀集合；正文条件 = _EMPTY_BODY 的字符集取反后「一个都没有」。
_CANDIDATE_SQL = """
    select id, company, title, summary
    from jobs
    where status = 'active'
      and jd_url like '%%/wt/%%/mobweb/position/detail?%%'
      and title ~ '(大学|学院|院校|研究生院|研究院|研究所|学校)'
      and coalesce(summary, '') !~ '[^。[:space:]【】任职要求]'
"""

_GATE = WtAdapter()._is_school_entry


def confirm_school_entries(rows):
    """纯函数：只留 adapter 闸门也判真的行。rows = [(id, company, title, summary)] → [(id, company, title)]。"""
    return [(job_id, company, title) for job_id, company, title, summary in rows
            if _GATE(title or "", summary)]


def find_candidates(cur, companies=()):
    """返回 (SQL 粗筛行, 闸门确认行)。companies 非空时只看点名的公司（精确匹配，参数绑定）。"""
    sql, params = _CANDIDATE_SQL, []
    if companies:
        sql += "      and company = any(%s)\n"
        params.append(list(companies))
    cur.execute(sql, params)
    candidates = cur.fetchall()
    return candidates, confirm_school_entries(candidates)


def run(cur, apply=False, companies=()):
    """dry-run 只读；apply 把确认行翻成 removed（只翻 active）。返回 {company: 确认行数}。"""
    candidates, confirmed = find_candidates(cur, companies)
    report = dict(Counter(company for _, company, _ in confirmed))
    rejected = len(candidates) - len(confirmed)
    if rejected:
        print(f"  SQL 粗筛 {len(candidates)} 行，其中 {rejected} 行未过 adapter 闸门（保留）")
    if apply and confirmed:
        ids = [job_id for job_id, _, _ in confirmed]
        cur.execute("update jobs set status = 'removed' where status = 'active' and id = any(%s::uuid[])",
                    [ids])
        if cur.rowcount != len(ids):
            print(f"  ⚠️ 计划写 {len(ids)} 行、实际改 {cur.rowcount} 行（差额 = 两步之间已不是 active 的行）")
    return report


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只读报数（默认行为，显式写上更清楚）")
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    ap.add_argument("--company", action="append", default=[],
                    help="精确公司名，可重复；--apply 时必填（见模块注释）")
    args = ap.parse_args(argv)
    if args.check and args.apply:
        ap.error("--check 与 --apply 二选一")
    if args.apply and not args.company:
        ap.error("--apply 必须配 --company 点名公司；不提供一键全清，理由见模块注释")
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
            report = run(cur, apply=args.apply, companies=args.company)
    finally:
        conn.close()
    if not report:
        print("没有命中「标题=院校名 ∧ 正文为空」的 wt 在招行 —— 无需清理")
        return 0
    print(f"{'公司':<22}{'命中行':>8}")
    for company, n in sorted(report.items(), key=lambda kv: -kv[1]):
        print(f"{company:<22}{n:>8}")
    total = sum(report.values())
    print(f"\n{'已标' if args.apply else 'dry-run 将标'} {total} 行 → status='removed'（可逆，purge 不删）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
