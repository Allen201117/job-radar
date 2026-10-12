"""字节「中文站链接已下线、全球站在招」的存量岗：原地换成全球站链接并挪到全球站那条源（一次性，2026-10-12）。

为什么需要它（背景与全集数字见 adapters/bytedance.py 文件头）：
  库里约 1,300 行字节海外岗存的是中文站链接，打开是「该职位已下线」，它们的在招页面在全球站 joinbytedance.com。
  adapter 改成按公开门户取之后，这批行会从中文站两条源的列表里消失、被缺席撤岗删掉，再由全球站那条源当新岗插回来——
  上千个岗的首见时间被刷成当天，在海外用户那里全显示成本周新岗。所以先原地挪，保住 id 和首见时间。

怎么做：三条源各用真实 adapter 取一遍公开门户列表 → plan_rehome 逐行定处置 → rehome_allowed 三道闸 →
  --apply 时 apply_rehome 一条语句写库。判据和闸各自写在那三个函数的说明里，这里不重复。
  只改 jd_url / apply_url / source_id（canonical 由库里触发器跟着算）；地点、国家等内容列由全球站源下一轮
  按同一个 canonical upsert 时刷新。闸不过 → 不写库、退出码 2。

用法（默认 dry-run）：
  python3 crawler/bytedance_global_rehome.py [--apply] [--out report.json]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
import jobs_db  # noqa: E402
import normalizer  # noqa: E402
from adapters.bytedance import (  # noqa: E402
    BytedanceAdapter, BytedanceCampusAdapter, BytedanceGlobalAdapter,
)

MAX_FRACTION = 0.15
_CN_URL_RE = re.compile(r"^https://jobs\.bytedance\.com/(?:experienced|campus)/position/(\d+)/detail/?$")
_GLOBAL_URL_RE = re.compile(r"^https://joinbytedance\.com/search/(\d+)/?$")


def post_id_of(jd_url):
    """岗位编号：中文站 / 全球站两种链接都认；认不出返回 None。"""
    m = _CN_URL_RE.match(jd_url or "") or _GLOBAL_URL_RE.match(jd_url or "")
    return m.group(1) if m else None


def plan_rehome(lib_rows, global_urls, cn_portal_ids):
    """逐行定处置。lib_rows: [(job_id, jd_url)]（中文站两条源名下的 active 行）；
    global_urls: {编号: 全球站链接}（全球站 adapter 解析后、已过地区白名单的）；cn_portal_ids: 两份中文站列表的编号并集。
    返回 [(action, job_id, old_url, new_url|None)]，action ∈ rehome / keep_on_cn_portal / keep_not_global / keep_unparsed。
    在全球站列表里但地区不在白名单内的岗不在 global_urls 里 → keep_not_global：留在原源，由缺席撤岗下架（现行口径不收）。"""
    actions = []
    for job_id, jd_url in lib_rows:
        m = _CN_URL_RE.match(jd_url or "")
        if not m:
            actions.append(("keep_unparsed", job_id, jd_url, None))
            continue
        pid = m.group(1)
        if pid in cn_portal_ids:
            # 中文站上在招：链接没问题。即便全球站也挂着，也不动（以它现在这条源为准）。
            actions.append(("keep_on_cn_portal", job_id, jd_url, None))
        elif pid in global_urls:
            actions.append(("rehome", job_id, jd_url, global_urls[pid]))
        else:
            actions.append(("keep_not_global", job_id, jd_url, None))
    return actions


def rehome_allowed(n_rehome, n_active, *, lists_complete, global_source_enabled, max_fraction=MAX_FRACTION):
    """能不能写库，以及不能写的原因（给人看的一句话）。三道闸：
    · 三份列表都抓全——中文站列表没抓全时「不在中文站列表里」不成立，会把中文站上在招的岗挪走；
    · 全球站那条源仍是 enabled=false——开着挪会和正在跑的抓取抢同一批 canonical；
    · 要挪的行数 ≤ 在招行数的 max_fraction（预期约 5%）——超过说明列表口径又变了。"""
    if not lists_complete:
        return False, "三份公开门户列表没全部抓全"
    if global_source_enabled:
        return False, "全球站那条源已经是 enabled：先停掉再挪（开着挪会和抓取抢同一批链接）"
    if n_active and n_rehome > n_active * max_fraction:
        return False, f"要挪 {n_rehome} 行，超过在招 {n_active} 行的 {int(max_fraction * 100)}%：列表口径可能又变了"
    return True, ""


def apply_rehome(conn, global_source_id, from_source_ids, actions):
    """原地换链接 + 换源（一条语句、一个事务）。只动 from_source_ids 名下的 active 行；
    新链接已被别的 active 行占着的跳过。返回 {rehomed, skipped_taken}。"""
    todo = [(job_id, new_url) for action, job_id, _old, new_url in actions if action == "rehome"]
    if not todo:
        return {"rehomed": 0, "skipped_taken": 0}
    # 连接是 autocommit：整批放进**一条**语句才是一个事务（要么全挪、要么一行不动）。
    # taken = 新链接已被别的 active 行占着；distinct on = 两行指向同一个新链接时只挪一行（canonical 在 active 里唯一）。
    with conn.cursor() as cur:
        cur.execute(
            """
            with v as (
              select t.id, t.new_url, public.canonicalize_jd_url(t.new_url) as canon
              from unnest(%s::uuid[], %s::text[]) as t(id, new_url)
            ),
            taken as (
              select j.canonical_jd_url from jobs j
              where j.status = 'active' and j.canonical_jd_url in (select canon from v)
            ),
            pick as (
              select distinct on (v.canon) v.id, v.new_url from v
              where v.canon not in (select canonical_jd_url from taken)
              order by v.canon, v.id
            )
            update jobs j set jd_url = p.new_url, apply_url = p.new_url, source_id = %s::uuid
            from pick p where j.id = p.id and j.status = 'active' and j.source_id = any(%s::uuid[])
            """,
            ([j for j, _u in todo], [u for _j, u in todo], global_source_id, list(from_source_ids)))
        rehomed = cur.rowcount
    return {"rehomed": rehomed, "skipped_taken": len(todo) - rehomed}


_PORTALS = (BytedanceGlobalAdapter, BytedanceCampusAdapter, BytedanceAdapter)   # 取列表的顺序：小的先，早失败


def _fetch_portal(adapter_cls, source):
    """用这条源的真实 adapter 取一遍公开门户列表：返回 (岗位, 是否抓全, 对方自报总数)。"""
    adapter = adapter_cls()
    adapter.regions = normalizer.source_regions(source.get("regions"))
    jobs = adapter.parse(adapter.fetch(source["source_url"]))
    return jobs, bool(adapter.fetch_complete), adapter.reported_total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    sb = db.get_supabase()
    rows = db.fetch_all_rows(lambda: sb.table("sources").select("id,company,source_url,adapter_name,enabled,regions"))
    source_of = {}
    for cls in _PORTALS:
        mine = [r for r in rows if r.get("adapter_name") == cls.name]
        if len(mine) != 1:
            print(f"[rehome] adapter={cls.name} 的源应当恰好 1 条，实际 {len(mine)} 条，停。", flush=True)
            sys.exit(2)
        source_of[cls] = mine[0]
    glob = source_of[BytedanceGlobalAdapter]
    from_ids = [source_of[BytedanceAdapter]["id"], source_of[BytedanceCampusAdapter]["id"]]
    if glob.get("enabled"):   # 这道闸不用等列表：取三份列表要七八分钟，早点说
        print(f"[rehome] 不写库：{rehome_allowed(0, 0, lists_complete=True, global_source_enabled=True)[1]}", flush=True)
        sys.exit(2)

    fetched = {cls: _fetch_portal(cls, source_of[cls]) for cls in _PORTALS}
    for cls, (jobs, complete, total) in fetched.items():
        print(f"[rehome] {cls.name}: 取到 {len(jobs)}（对方自报 {total}，抓全 {complete}）", flush=True)
    global_urls = {post_id_of(j.jd_url): j.jd_url for j in fetched[BytedanceGlobalAdapter][0] if post_id_of(j.jd_url)}
    cn_ids = {post_id_of(j.jd_url) for cls in (BytedanceAdapter, BytedanceCampusAdapter) for j in fetched[cls][0]} - {None}
    lists_complete = {cls.name: complete for cls, (_jobs, complete, _total) in fetched.items()}

    conn = jobs_db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("select id::text, jd_url, source_id::text, coalesce(country_code, '∅') from jobs "
                        "where source_id = any(%s::uuid[]) and status = 'active'", (from_ids,))
            lib = {r[0]: r for r in cur.fetchall()}
        actions = plan_rehome([(r[0], r[1]) for r in lib.values()], global_urls, cn_ids)
        counts = Counter(a[0] for a in actions)
        rehome = [a for a in actions if a[0] == "rehome"]
        by_src = Counter("social" if lib[a[1]][2] == from_ids[0] else "campus" for a in rehome)
        by_country = Counter(lib[a[1]][3] for a in rehome)
        ok, why = rehome_allowed(len(rehome), len(lib), lists_complete=all(lists_complete.values()),
                                 global_source_enabled=False)
        print(f"[rehome] 中文站两条源在招 {len(lib)} 行：{dict(counts)}", flush=True)
        print(f"[rehome] 要挪 {len(rehome)} 行：按原源 {dict(by_src)}；按库里现在的国家码 {by_country.most_common(12)}", flush=True)
        for a in rehome[:5]:
            print(f"   例：{a[2]} → {a[3]}", flush=True)
        report = {"apply": args.apply, "allowed": ok, "blocked_reason": why, "active": len(lib),
                  "global_reported": fetched[BytedanceGlobalAdapter][2], "global_kept": len(global_urls),
                  "lists_complete": lists_complete,
                  "counts": dict(counts), "rehome_by_source": dict(by_src), "rehome_by_country": dict(by_country)}
        if not ok:
            print(f"[rehome] 不写库：{why}", flush=True)
        elif args.apply:
            report.update(apply_rehome(conn, glob["id"], from_ids, actions))
            with conn.cursor() as cur:
                cur.execute("select count(*) from jobs where source_id = %s::uuid and status = 'active'", (glob["id"],))
                report["global_active_after"] = cur.fetchone()[0]
            print(f"[rehome] 已写库：挪了 {report['rehomed']} 行，新链接已被占跳过 {report['skipped_taken']} 行；"
                  f"全球站那条源现在在招 {report['global_active_after']} 行", flush=True)
        else:
            print("[rehome] dry-run：没有写库。", flush=True)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=1)
        if not ok:
            sys.exit(2)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
