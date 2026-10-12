"""Moka「一个门户发多家公司的岗」的存量归属纠正：逐行按标题末尾的业务段改 company。

治的病（2026-10-12）：租户 crland 的校招门户 168540 同时发华润置地与华润万象生活的岗，adapter 过去每条都贴
sources.company。adapter 已改成逐行归属（adapters/china_ats.py 的 _MOKA_SHARED_PORTALS），列表里还挂着的岗
下一轮重抓会自愈（company 在 jobs_db._UPDATE_COLS 里）；这里把存量一次改对，并留底可回滚。
rename_job_company.py 的前缀模式用不上：同一个前缀下两家公司混在一起，只能逐行判。

判据 = 与 adapter 同一个函数（moka_shared_portal_verdict），不另写一套；只看库里那一行自己的标题，不联网：
  · 业务段属于别家 → 改成别家；核实过属于本家、现在却挂着别家名 → 改回本家（登记里的 home_company）；
  · **认不出业务段的行一律不动**（宁可漏改不可错改），逐条列出来；
  · 现在挂着的公司名既不是本家也不是登记的别家 → 不动、单独报数（这种行不该存在，先看是什么）。
护栏：
  · 默认 dry-run，--apply 才写；--rehearse 整套真执行后回滚（单测里的假游标只验流程，SQL 要在真库上跑过才算数）。
  · --url-prefix 点名门户（必须是登记在 _MOKA_SHARED_PORTALS 的门户，且正好写到「…/租户/门户号」为止），
    只动 jd_url 以「前缀 + #」开头的行——带上 # 是因为门户号是数字，不带的话 168540 的前缀会扫到 1685401。
    前缀下一行都没有按失败算（前缀写错 / 连错了库），不许绿着什么都没做。
  · --apply / --rehearse 前回读 Supabase：这个门户的启用源必须只有一条、且它的 company 就是登记的本家名
    （源被改过名而登记没跟上时，本家的行该叫什么已经说不清）。--apply 另查有没有抓取正在跑（见下面的顺序）；
    --rehearse 不留改动，不查这一条。读不到按失败算。
  · UPDATE 带「company 仍是读的时候那个值」条件；改名与留底是同一条语句（表 job_company_renames，
    与 rename_job_company 的批量模式共用）；参数一律绑定。
  · 改之前先数会不会撞 jobs 的 (company, title, location, jd_url) 唯一键，撞一行就整批不动。
报数分方向（A→B、B→A 各多少行，0 也列），不只报净值。

⚠️ 顺序：必须等 adapter 的改动进了 main、且改动之前开跑的抓取轮都收尾了再 --apply。company 在 _UPDATE_COLS 里，
   旧代码的那一轮会把列表里的行全刷回 sources.company（迁移 312 踩过同一种：85 行改完 1 分钟后 84 行变回旧名）。
   Supabase 只看得到「此刻正在抓某条源」，看不到两条源之间的空档，apply 前另看一眼 `gh run list --status in_progress`。
⚠️ `company` 是招聘类型分类的输入（jobs_guard_recruitment_class）：改名的行分类会被清空等重算，
   跑完**立刻**手动触发 backfill-recruitment-category；洞察的业务线主体按 jobs.company 抽，接着触发 insight-subjects。

回滚：
    update jobs j set company = r.old_company from job_company_renames r
     where r.batch = '<批次>' and r.job_id = j.id and j.company = r.new_company;

用法：
    python3 crawler/reattribute_moka_shared_portal.py --url-prefix https://app.mokahr.com/campus-recruitment/crland/168540             # dry-run
    python3 crawler/reattribute_moka_shared_portal.py --url-prefix https://app.mokahr.com/campus-recruitment/crland/168540 --rehearse  # 真执行后回滚
    python3 crawler/reattribute_moka_shared_portal.py --url-prefix https://app.mokahr.com/campus-recruitment/crland/168540 --apply     # 真写
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402
from adapters.china_ats import (moka_portal_key, moka_shared_portal,  # noqa: E402
                                moka_shared_portal_verdict)
from rename_job_company import RENAME_LOG_DDL, like_prefix  # noqa: E402

_SELECT_SQL = "select id, jd_url, company, status, title from jobs where jd_url like %s"

# 改名后会撞 unique (company, title, location, jd_url) 的行数：同一个链接、同一个标题和地点，已经有一行挂在新名下。
# 唯一约束把 NULL 当互不相同，所以 title / location 任一为空的行不会撞。
_COLLISION_SQL = """
    select count(*)
    from jobs j join jobs k
      on k.jd_url = j.jd_url and k.title = j.title and k.location = j.location and k.id <> j.id
    where j.id = any(%s::uuid[]) and k.company = %s
"""

# 改名 + 留底是**一条语句**（理由见 rename_job_company._MAP_APPLY_SQL）。
_APPLY_SQL = """
    with renamed as (
      update jobs
         set company = %s
       where id = any(%s::uuid[]) and company = %s
      returning id
    ), logged as (
      insert into job_company_renames (job_id, old_company, new_company, batch)
      select id, %s, %s, %s from renamed
      on conflict (job_id, batch) do nothing
      returning 1
    )
    select (select count(*) from renamed), (select count(*) from logged)
"""

_READBACK_SQL = "select company, status, count(*) from jobs where jd_url like %s group by 1, 2 order by 1, 2"

# 门户前缀必须正好写到门户号为止：后面多带一段（…/168540/jobs）照样认得出是哪个门户，拼出来的 LIKE 却一行都匹配不到。
_PORTAL_PREFIX_RE = re.compile(r"https://[^/#?]+/[^/#?]+/[^/#?]+/\d+")


def portal_pattern(url_prefix: str) -> str:
    """门户前缀 → 只匹配这个门户的岗位链接的 LIKE 模式（前缀 + #）。"""
    return like_prefix(url_prefix + "#")


def portal_companies(url_prefix: str):
    """登记项 → (本家公司名, 别家公司名集合)。"""
    portal = moka_shared_portal(url_prefix)
    return portal["home_company"], frozenset(portal["owners"].values())


def plan(rows, url_prefix: str):
    """纯函数：逐行算该挂哪家。rows=[(id, jd_url, company, status, title)]。
    返回 (changes=[(id, 旧名, 新名, status)], stats Counter, 认不出的行=[(标题, 现在的公司名, status)])。"""
    home, owners = portal_companies(url_prefix)
    changes, stats, unresolved = [], Counter(), []
    for job_id, jd_url, company, status, title in rows:
        if company != home and company not in owners:
            stats["other_company"] += 1
            continue
        owner, known = moka_shared_portal_verdict(jd_url, title)
        if not known:
            unresolved.append((title, company, status))
            continue
        target = owner or home
        if target == company:
            stats["already_correct"] += 1
        else:
            changes.append((str(job_id), company, target, status))
    return changes, stats, unresolved


def count_collisions(cur, changes) -> int:
    groups = defaultdict(list)
    for job_id, _old, new, _status in changes:
        groups[new].append(job_id)
    total = 0
    for new, ids in groups.items():
        cur.execute(_COLLISION_SQL, [ids, new])
        total += cur.fetchall()[0][0]
    return total


def apply_changes(cur, changes, batch: str, rehearse: bool = False) -> dict:
    """按 (旧名, 新名) 分组改名 + 留底，同一个事务。返回 {(旧名, 新名): (改名行数, 留底行数)}。
    rehearse=True：真执行后 rollback，库里什么都不留。"""
    groups = defaultdict(list)
    for job_id, old, new, _status in changes:
        groups[(old, new)].append(job_id)
    done = {}
    cur.execute(RENAME_LOG_DDL)
    cur.execute("begin")
    try:
        cur.execute("set local lock_timeout = '10s'")
        cur.execute("set local statement_timeout = '300s'")
        for (old, new), ids in sorted(groups.items()):
            cur.execute(_APPLY_SQL, [new, ids, old, old, new, batch])
            done[(old, new)] = tuple(cur.fetchall()[0])
        cur.execute("rollback" if rehearse else "commit")
    except Exception:
        try:
            cur.execute("rollback")
        except Exception as rollback_exc:  # 连接已断：服务端会自己回滚，别让它盖掉真正的原因
            print(f"  （回滚语句没发出去：{type(rollback_exc).__name__}；连接断开时服务端自动回滚）")
        raise
    return done


def source_state(url_prefix: str, now=None):
    """回读 Supabase：返回 (这个门户的启用源的 company 列表, 近 4 小时开跑却没收尾的抓取条数)。"""
    import db  # 延迟导入：纯函数与单测不需要 Supabase

    sb = db.get_supabase()
    key = moka_portal_key(url_prefix)
    sources = db.fetch_all_rows(
        lambda: sb.table("sources").select("id,company,source_url,enabled").ilike("source_url", "%mokahr.com%"))
    companies = sorted(r.get("company") or "" for r in sources
                       if r.get("enabled") and moka_portal_key(r.get("source_url") or "") == key)
    since = ((now or datetime.now(timezone.utc)) - timedelta(hours=4)).isoformat()
    in_flight = db.fetch_all_rows(
        lambda: sb.table("crawl_runs").select("id").is_("finished_at", "null").gte("started_at", since))
    return companies, len(in_flight)


def source_blockers(url_prefix: str, read_state=source_state, allow_in_flight: bool = False):
    """返回 [拦截原因]。读失败直接抛（绝不能把「没读到」当成「可以改」）。"""
    home, _owners = portal_companies(url_prefix)
    companies, in_flight = read_state(url_prefix)
    reasons = []
    if companies != [home]:
        reasons.append(f"这个门户的启用源在 sources 里的 company 是 {companies}，不是只有一条 {home!r} —— "
                       "源被改名 / 停用而登记没跟上，或连错了库；本家名对不上就不动")
    if in_flight and not allow_in_flight:
        reasons.append(f"有 {in_flight} 条抓取正在跑（近 4 小时开跑、还没收尾）—— adapter 改动之前开跑的那一轮会按旧归属写回。"
                       "等它跑完；确认在飞的轮次都晚于 adapter 改动进 main 再加 --allow-in-flight")
    return reasons


def report(changes, stats, unresolved, url_prefix: str) -> None:
    home, owners = portal_companies(url_prefix)
    print(f"已正确 {stats['already_correct']} 行；认不出业务段、不动 {len(unresolved)} 行；"
          f"公司名既不是本家也不是登记的别家、不动 {stats['other_company']} 行")
    for title, company, status in unresolved:
        print(f"  认不出：{title}（现在挂 {company}，{status}）")
    by_dir = defaultdict(Counter)
    for _id, old, new, status in changes:
        by_dir[(old, new)][status] += 1
    names = {home} | owners
    print("分方向（每个方向都列，0 也列）：")
    for old in sorted(names):
        for new in sorted(names):
            if old != new:
                c = by_dir.get((old, new), Counter())
                detail = "、".join(f"{s} {n}" for s, n in sorted(c.items()))
                print(f"  {old} → {new}：{sum(c.values())}" + (f"（{detail}）" if detail else ""))


def default_batch(url_prefix: str, today=None) -> str:
    day = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    return f"moka_shared_portal_{moka_portal_key(url_prefix).replace('/', '_')}_{day:%Y%m%d}"


def run(cur, url_prefix: str, *, apply=False, rehearse=False, allow_in_flight=False,
        batch=None, read_state=source_state) -> int:
    """主流程。返回进程退出码（0 成功 / 2 被护栏拦下）。"""
    pattern = portal_pattern(url_prefix)
    cur.execute(_SELECT_SQL, [pattern])
    rows = cur.fetchall()
    print(f"{url_prefix} 下共 {len(rows)} 行：{dict(Counter((r[2], r[3]) for r in rows))}")
    if not rows:
        print("✗ 这个前缀下一行都没有 —— 前缀写错了或连错了库，按失败算")
        return 2
    changes, stats, unresolved = plan(rows, url_prefix)
    report(changes, stats, unresolved, url_prefix)
    if not changes:
        print("没有要改的行")
        return 0
    collisions = count_collisions(cur, changes)
    if collisions:
        print(f"✗ 改名后会撞 (company, title, location, jd_url) 唯一键 {collisions} 行 —— 整批不动。"
              "先按 jd_url 查出是哪几行，处理掉再跑")
        return 2
    print("撞唯一键 0 行")
    if not (apply or rehearse):
        print(f"\ndry-run：将改 {len(changes)} 行，没有写库（--rehearse 真执行后回滚 / --apply 真写）")
        return 0
    # 演练不留改动，有抓取在飞也无妨；本家名对不对两种模式都查。
    blockers = source_blockers(url_prefix, read_state, allow_in_flight=allow_in_flight or rehearse)
    for reason in blockers:
        print("✗ " + reason)
    if blockers:
        return 2
    batch = batch or default_batch(url_prefix)
    done = apply_changes(cur, changes, batch, rehearse=rehearse)
    updated = sum(u for u, _l in done.values())
    logged = sum(lg for _u, lg in done.values())
    detail = "；".join(f"{o} → {n} {u}" for (o, n), (u, _l) in sorted(done.items()))
    if rehearse:
        print(f"\n演练：真执行后已回滚，库里没有留下改动。改名 {updated} 行（{detail}）、留底 {logged} 行")
        return 0
    print(f"\n已改 {updated} 行（{detail}）；留底 {logged} 行，表 job_company_renames，batch={batch}")
    if updated != len(changes):
        print(f"  ⚠️ 计划改 {len(changes)} 行、实际改 {updated} 行（差额 = 两步之间被并发改过的行）")
    if logged != updated:
        print(f"  ⚠️ 留底 {logged} 行少于改名 {updated} 行：差的是同一批次以前留过底的行（重跑时正常），回滚仍按首次留底的旧名")
    cur.execute(_READBACK_SQL, [pattern])
    print("回读（公司名 / 状态 / 行数）：" + "；".join(f"{c} {s} {n}" for c, s, n in cur.fetchall()))
    print("⚠️ 这些行的招聘类型分类已被清空等重算：现在就手动触发 backfill-recruitment-category，再触发 insight-subjects")
    return 0


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url-prefix", required=True,
                    help="门户页地址（= 岗位链接里 # 之前的部分），须已登记在 _MOKA_SHARED_PORTALS")
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    ap.add_argument("--rehearse", action="store_true", help="整套真执行后回滚，库里不留改动")
    ap.add_argument("--allow-in-flight", action="store_true",
                    help="有抓取在跑也执行。只在确认在飞的轮次都晚于 adapter 改动进 main 时用")
    ap.add_argument("--batch", help="留底批次名（默认 moka_shared_portal_<租户>_<门户号>_<北京日期>）")
    args = ap.parse_args(argv)
    if args.apply and args.rehearse:
        ap.error("--apply 与 --rehearse 二选一")
    args.url_prefix = args.url_prefix.rstrip("/")
    if not _PORTAL_PREFIX_RE.fullmatch(args.url_prefix):
        ap.error("--url-prefix 必须是 https://<主机>/<板块>/<租户>/<门户号>，不带 # ? 和多余的路径")
    if moka_shared_portal(args.url_prefix) is None:
        ap.error(f"{args.url_prefix} 没登记在 _MOKA_SHARED_PORTALS，不是共享门户")
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
            return run(cur, args.url_prefix, apply=args.apply, rehearse=args.rehearse,
                       allow_in_flight=args.allow_in_flight, batch=args.batch)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
