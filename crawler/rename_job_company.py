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

🚫 sources.company 的迁移生效后别马上 --apply，先等在飞的抓取轮过完这条源（2026-10-10 踩，迁移 312）：
   迁移生效前已经读完源清单的那一轮抓取，会拿旧公司名把刚改好的行写回去（85 行改完 1 分钟后 84 行变回旧名）。
   判法与防法同 remove_jobs_by_url_prefix.py 模块注释里那块碑。

批量模式（--map-file，2026-10-11 加）：一批「旧名 → 新名」一次改完，**只按旧名精确匹配、不要链接前缀**。
  只给「旧名这个写法本身就不该存在」的情况用——源名带渠道后缀（「TCL 校招」→「TCL」，迁移 320）这一类：
  49 个名字逐个点「前缀 + 旧名」要手跑 50 多次，而这些旧名不会是别家公司的名字，前缀护栏没有可护的东西。
  「把 A 公司挂错的岗改成 B 公司」仍然必须用上面的前缀模式。批量模式自己的护栏：
  · 改之前先数会不会撞 jobs 的 (company, title, location, jd_url) 唯一键，撞一组就整批不动。
  · --apply 前回读 Supabase：还有任何一条源叫清单里的旧名（迁移没生效）、或有抓取正在跑（迁移生效前开跑的那一轮
    会按旧名写回），就拒绝执行。dry-run 也读，只提示不拦。
  · 改名和留底是同一条语句：改到的每一行把 (岗位 id, 旧名, 新名) 记进 job_company_renames；回滚照这张表改回去：
        update jobs j set company = r.old_company from job_company_renames r
         where r.batch = '<批次>' and r.job_id = j.id and j.company = r.new_company;
  ⚠️ `company` 是招聘类型分类的输入（jobs_guard_recruitment_class）：改名的行分类会被清空等重算，
     跑完**立刻**手动触发 backfill-recruitment-category，别等定时那一趟。

用法：
    python3 crawler/rename_job_company.py --url-prefix https://x.hotjob.cn/SUxxx/ --from 旧名 --to 新名            # dry-run
    python3 crawler/rename_job_company.py --url-prefix https://x.hotjob.cn/SUxxx/ --from 旧名 --to 新名 --apply    # 真写
    python3 crawler/rename_job_company.py --map-file crawler/company_renames/20261011_channel_suffix.json          # 批量 dry-run
    python3 crawler/rename_job_company.py --map-file crawler/company_renames/20261011_channel_suffix.json --rehearse  # 真执行后回滚
    python3 crawler/rename_job_company.py --map-file crawler/company_renames/20261011_channel_suffix.json --apply  # 批量真写
"""
import argparse
import json
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


# ── 批量模式 ─────────────────────────────────────────────────────────────────────
# 留底表。jobs-db/schema.sql 里有逐字相同的一份（test_rename_job_company 对拍）；脚本自己也建，
# 这样不必为一张独立小表去跑整份 schema（那会排队等 jobs 的排他锁，见 CLAUDE.md jobs-db-migrate 那块碑）。
RENAME_LOG_DDL = """create table if not exists job_company_renames (
  job_id      uuid        not null,
  old_company text        not null,
  new_company text        not null,
  batch       text        not null,
  renamed_at  timestamptz not null default now(),
  primary key (job_id, batch)
)"""

_MAP_TEMP_SQL = "create temp table if not exists _rename_map (old_name text primary key, new_name text not null)"
_MAP_CLEAR_SQL = "delete from _rename_map"
_MAP_FILL_SQL = "insert into _rename_map (old_name, new_name) values (%s, %s)"

_MAP_COUNT_SQL = """
    select m.old_name, m.new_name, j.status, count(*)
    from jobs j join _rename_map m on m.old_name = j.company
    group by 1, 2, 3
    order by 1, 3
"""

# 改名后会撞 unique (company, title, location, jd_url) 的组数。唯一约束把 NULL 当互不相同，所以三列任一为空的行不会撞。
_MAP_COLLISION_SQL = """
    select count(*) from (
      select coalesce(m.new_name, j.company), j.title, j.location, j.jd_url
      from jobs j left join _rename_map m on m.old_name = j.company
      where j.title is not null and j.location is not null and j.jd_url is not null
        and j.company in (select old_name from _rename_map union select new_name from _rename_map)
      group by 1, 2, 3, 4
      having count(*) > 1 and count(m.old_name) > 0
    ) x
"""

# 改名 + 留底是**一条语句**：update 改到的行由 returning 直接喂给留底表。
# 分成两条（先 insert 留底、再 update）时，READ COMMITTED 下两条各取各的快照，夹在中间被在飞抓取写回旧名的行
# 会被改名却没留底，而回滚就靠这张表。
_MAP_APPLY_SQL = """
    with renamed as (
      update jobs j
         set company = m.new_name
        from _rename_map m
       where j.company = m.old_name
      returning j.id, m.old_name, m.new_name
    ), logged as (
      insert into job_company_renames (job_id, old_company, new_company, batch)
      select id, old_name, new_name, %s from renamed
      on conflict (job_id, batch) do nothing
      returning 1
    )
    select (select count(*) from renamed), (select count(*) from logged)
"""

_MAP_LEFT_SQL = "select count(*) from jobs j join _rename_map m on m.old_name = j.company"


def load_rename_map(path):
    """读清单文件 → (batch, [(旧名, 新名)])。写错的清单在碰库之前就拒绝。"""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    batch = str(doc.get("batch") or "").strip()
    if not batch:
        raise ValueError("清单缺 batch（留底表按它区分批次）")
    pairs, seen = [], set()
    for item in doc.get("renames") or []:
        old, new = str(item.get("from") or ""), str(item.get("to") or "")
        if not old.strip() or not new.strip():
            raise ValueError(f"清单里有空名字：{item!r}")
        if old != old.strip() or new != new.strip():
            raise ValueError(f"名字首尾带空白（库里按精确相等匹配，多一个空格就对不上）：{item!r}")
        if old == new:
            raise ValueError(f"旧名与新名相同：{old!r}")
        if old in seen:
            raise ValueError(f"旧名重复：{old!r}")
        seen.add(old)
        pairs.append((old, new))
    if not pairs:
        raise ValueError("清单是空的")
    chained = sorted(new for _old, new in pairs if new in seen)
    if chained:
        raise ValueError(f"新名同时又是另一条的旧名（改名结果取决于执行顺序）：{chained}")
    return batch, pairs


def plan_map(cur, pairs):
    """把清单装进临时表，返回 ({(旧名, 新名): {status: 行数}}, 会撞唯一键的组数)。只读（临时表除外）。"""
    cur.execute(_MAP_TEMP_SQL)
    cur.execute(_MAP_CLEAR_SQL)
    for old, new in pairs:
        cur.execute(_MAP_FILL_SQL, [old, new])
    cur.execute(_MAP_COUNT_SQL)
    counts = {}
    for old, new, status, n in cur.fetchall():
        counts.setdefault((old, new), {})[status] = n
    cur.execute(_MAP_COLLISION_SQL)
    collisions = cur.fetchall()[0][0]
    return counts, collisions


def apply_map(cur, batch, rehearse=False):
    """改名 + 留底，同一条语句、同一个事务。返回 (改名行数, 留底行数)。plan_map 必须先在同一个连接上跑过。

    rehearse=True：整套真执行（触发器、唯一键、锁都真走一遍），最后 rollback —— 库里什么都不留。
    单测里的假游标只验流程，SQL 本身只有在真库上跑过才算数，所以 --apply 之前先 --rehearse 一次。
    """
    cur.execute(RENAME_LOG_DDL)
    cur.execute("begin")
    try:
        cur.execute("set local lock_timeout = '10s'")
        cur.execute("set local statement_timeout = '600s'")
        cur.execute(_MAP_APPLY_SQL, [batch])
        updated, logged = cur.fetchall()[0]
        cur.execute("rollback" if rehearse else "commit")
    except Exception:
        try:
            cur.execute("rollback")
        except Exception as rollback_exc:  # 连接已断：服务端会自己回滚，别让它盖掉真正的原因
            print(f"  （回滚语句没发出去：{type(rollback_exc).__name__}；连接断开时服务端自动回滚）")
        raise
    return updated, logged


def source_state(pairs, now=None):
    """回读 Supabase：返回 (还叫旧名的源名, 新名里已出现在 sources 的个数, 近 4 小时开跑却没收尾的抓取条数)。

    · 还叫旧名的源名非空 = 源名迁移没生效，这时改存量，下一轮重抓会按旧名全写回去。
    · 新名一个都不在 sources 里 = 多半连错了项目或读不到表（读回 0 行会被当成「没有旧名」而放行），当作读失败。
    · 抓取在飞：run.py 的源清单是整轮开跑时一次读进去的，迁移生效前开跑的那一轮还会按旧名写
      （迁移 312 踩过：85 行改完 1 分钟后 84 行变回旧名）。这里只能看到「此刻正在抓某条源」，看不到两条源之间的空档，
      所以它是补充，不能代替 apply 前看一眼 `gh run list --status in_progress`。
    """
    from datetime import datetime, timedelta, timezone

    import db  # 延迟导入：前缀模式不需要 Supabase

    olds = {old for old, _new in pairs}
    news = {new for _old, new in pairs}
    sb = db.get_supabase()
    names = {r.get("company") for r in db.fetch_all_rows(lambda: sb.table("sources").select("id,company"))}
    since = ((now or datetime.now(timezone.utc)) - timedelta(hours=4)).isoformat()
    in_flight = db.fetch_all_rows(
        lambda: sb.table("crawl_runs").select("id").is_("finished_at", "null").gte("started_at", since))
    return sorted(names & olds), len(names & news), len(in_flight)


def _source_blockers(pairs, read_state, allow_in_flight=False):
    """返回 [拦截原因]。读失败直接抛（绝不能把「没读到」当成「可以改」）。"""
    still_old, new_present, in_flight = read_state(pairs)
    reasons = []
    if still_old:
        reasons.append(f"sources 里还有 {len(still_old)} 个源名是清单里的旧名：{still_old[:8]} —— "
                       "源名迁移没生效就改存量，下一轮重抓会按旧名全写回去")
    if not new_present:
        reasons.append("清单里的新名一个都不在 sources 里 —— 多半连错了库或没读到表，当作读失败")
    if in_flight and not allow_in_flight:
        reasons.append(f"有 {in_flight} 条抓取正在跑（近 4 小时开跑、还没收尾）—— 迁移生效前开跑的那一轮会按旧名写回。"
                       "等它跑完；确认在飞的轮次都晚于迁移生效再加 --allow-in-flight")
    return reasons


def run_map(cur, path, apply=False, rehearse=False, allow_in_flight=False, read_state=source_state):
    """批量模式主流程。返回进程退出码（0 成功 / 2 被护栏拦下）。"""
    batch, pairs = load_rename_map(path)
    counts, collisions = plan_map(cur, pairs)
    by_status = {}
    for (old, new), per in sorted(counts.items()):
        print(f"  {old} → {new}  " + "  ".join(f"{k}={v}" for k, v in sorted(per.items())))
        for k, v in per.items():
            by_status[k] = by_status.get(k, 0) + v
    total = sum(by_status.values())
    print(f"\n批次 {batch}：清单 {len(pairs)} 个名字，库里有岗的 {len(counts)} 个，共 {total} 行"
          + "（" + "，".join(f"{k} {v}" for k, v in sorted(by_status.items())) + "）")
    if collisions:
        print(f"✗ 改名后会撞 (company, title, location, jd_url) 唯一键 {collisions} 组 —— 整批不动。"
              "先按 jd_url 查出是哪几行，处理掉再跑")
        return 2
    print("撞唯一键 0 组")
    if not total:
        print("没有要改的行")
        return 0
    blockers = _source_blockers(pairs, read_state, allow_in_flight=allow_in_flight)
    for reason in blockers:
        print(("✗ " if apply else "⚠️ 现在 --apply 会被拦：") + reason)
    if rehearse:
        updated, logged = apply_map(cur, batch, rehearse=True)
        print(f"演练：真执行后已回滚，库里没有留下改动。改名 {updated} 行、留底 {logged} 行")
        return 0
    if not apply:
        print("dry-run：没有写库（--rehearse 真执行后回滚 / --apply 真写）")
        return 0
    if blockers:
        return 2
    updated, logged = apply_map(cur, batch)
    print(f"已改 {updated} 行（留底 {logged} 行，表 job_company_renames，batch={batch}）")
    if updated != total:
        print(f"  ⚠️ 计划改 {total} 行、实际改 {updated} 行（差额 = 两步之间被并发写入的行）")
    if logged != updated:
        print(f"  ⚠️ 留底 {logged} 行少于改名 {updated} 行：差的是同一批次以前留过底的行（重跑时正常），回滚仍按首次留底的旧名")
    cur.execute(_MAP_LEFT_SQL)
    left = cur.fetchall()[0][0]
    print(f"回读：仍叫旧名的行 {left}" + ("" if not left else " ⚠️ 有抓取轮按旧名写回了，等它跑完再跑一次"))
    print("⚠️ 这些行的招聘类型分类已被清空等重算：现在就手动触发 backfill-recruitment-category")
    return 0


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url-prefix", help="jd_url 前缀（租户/门户级），只改这个前缀下的行")
    ap.add_argument("--from", dest="old_name", help="现在挂着的（错的）公司名，精确匹配")
    ap.add_argument("--to", dest="new_name", help="改成的公司名")
    ap.add_argument("--map-file", help="批量模式：旧名 → 新名清单（JSON），只按旧名精确匹配。与上面三个参数二选一")
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    ap.add_argument("--rehearse", action="store_true", help="批量模式：整套真执行后回滚，库里不留改动（验 SQL / 触发器 / 耗时）")
    ap.add_argument("--allow-in-flight", action="store_true",
                    help="批量模式：有抓取在跑也执行。只在确认在飞的轮次都晚于源名迁移生效时用")
    args = ap.parse_args(argv)
    if args.map_file:
        if args.url_prefix or args.old_name or args.new_name:
            ap.error("--map-file 与 --url-prefix / --from / --to 二选一")
        if args.apply and args.rehearse:
            ap.error("--apply 与 --rehearse 二选一")
        return args
    if args.rehearse or args.allow_in_flight:
        ap.error("--rehearse / --allow-in-flight 只在 --map-file 批量模式下可用")
    if not (args.url_prefix and args.old_name and args.new_name):
        ap.error("要么给 --map-file，要么 --url-prefix / --from / --to 三个都给")
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
            if args.map_file:
                return run_map(cur, args.map_file, apply=args.apply, rehearse=args.rehearse,
                               allow_in_flight=args.allow_in_flight)
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
