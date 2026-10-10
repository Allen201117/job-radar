"""wt 租户换到新版 wecruit 门户后，把香港 jobs 库存量 active 行的 jd_url 逐岗换成新门户的详情链接。

治的病（2026-10-10 兴业证券）：对方把 xyzq.hotjob.cn 改绑成新版门户，旧链接
`…/wt/xyzq/mobweb/position/detail?…&postIdsAry=273901` 打开落在门户首页（不是岗位），源连续 failed。
只把 sources 换成 hotjob adapter 不够：新链接 `…/SU…/pb/posDetail.html?postId=6ab4…&postType=society`
的 canonical 找不到旧行 → 重抓插一批新行，旧行照样挂 active（同一个岗两张卡），首见时间也从头算。
所以先把存量改对，重抓就会落到同一行上。

为什么不能用 rewrite_jd_url_prefix：岗位号变了，不是换前缀。两边靠同一个号对上——
**wt 的 postId = wecruit 列表行的 externalKey**（兴业证券库里 94 个岗位号对新门户 94 个 externalKey，
一一对应、标题逐字相同）。新链接由 HotJobAdapter._map 拼，和之后重抓写库的是同一个。

哪些行不改（只报数，交给人看）：
  · 只在**没发布的渠道**里（HotJobAdapter.should_skip 判的，页面停在「内部处理中」）——换过去也打不开；
  · 新门户列表里没有 / 岗位号对上但标题不同 / 一个号对上多个新链接且按旧渠道也分不出 / 另一行已占同一个新链接；
  · 改完会撞唯一索引（已有别的 active 行占着这个 canonical，或同公司+标题+地点+新链接）。
  剩在旧前缀下的行按情况另走 remove_jobs_by_url_prefix（标 removed，可逆）。

护栏（同 rewrite_jd_url_prefix / remove_jobs_by_url_prefix 的规矩）：
  · 默认 dry-run 只报数；--apply 才写。只动 status='active' ∧ company 精确点名 ∧ jd_url 在旧前缀下的行。
  · 任何一个渠道的列表没翻完就整轮放弃（没翻完时「新门户没有」不可信）。
  · 渠道发没发布必须真探到答复才算数：HotJobAdapter.should_skip 探测失败时按「不跳过」放行（抓取侧宁可漏判），
    这里不能照搬——没探到就整轮放弃，否则没发布的渠道会被当成发布了，把行改到打不开的页面上。
  · 逐行 update 都带 `jd_url = 旧值` 条件：两步之间被别的进程改过的行不动。参数一律绑定。
  · 幂等：改完的行不在旧前缀下，重跑 0 行。

改完之后：jd_url 一变，库里的触发器（jobs_guard_recruitment_class）会把这些行的招聘类型作废等回填，
由 backfill-recruitment-category 重新算（定时每天几次；apply 完手动触发一次更快），中间这些行按「未分类」参与筛选。

用法：
    python3 crawler/migrate_wt_rows_to_wecruit.py --company 兴业证券 \
        --wt-prefix https://xyzq.hotjob.cn/wt/xyzq/ \
        --portal https://xyzq.hotjob.cn/SU68fb2499b7da1347a9dd852c/pb/social.html \
        --portal https://xyzq.hotjob.cn/SU68fb2499b7da1347a9dd852c/pb/school.html \
        --portal https://xyzq.hotjob.cn/SU68fb2499b7da1347a9dd852c/pb/interns.html
    （加 --apply 真写）
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict, namedtuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psycopg2  # noqa: E402

import jobs_db  # noqa: E402
from adapters.hotjob import HotJobAdapter  # noqa: E402
from rename_job_company import like_prefix  # noqa: E402

# 新门户列表里的一个岗。published = 所在渠道的页面真能打开（should_skip 放行）。
PortalPost = namedtuple("PortalPost", "external_key title url recruit_type published")

_OLD_POST_ID = re.compile(r"[?&]postIdsAry=(\d+)(?:&|$)")
_OLD_RECRUIT_TYPE = re.compile(r"[?&]recruitType=(\d+)(?:&|$)")
_PORTAL_URL = re.compile(r"^https://[^/]+/SU[0-9a-f]+/pb/(?:social|school|interns)\.html$")
_GATE_TRIES, _GATE_RETRY_SECONDS = 3, 5

SKIP_REASONS = {
    "no_post_id": "链接里取不到旧岗位号",
    "not_in_portal": "新门户各渠道列表里都没有这个岗位号",
    "channel_unpublished": "只在新门户没发布的渠道里（页面打不开）",
    "title_mismatch": "岗位号对上了但标题不同",
    "ambiguous": "一个旧岗位号对上多个新链接，按旧渠道也分不出",
    "duplicate_target": "另一行已经要改成同一个新链接",
    "conflict_or_changed": "改完会撞唯一索引，或这行刚被别的进程改过",
}


def fetch_portal_posts(portal_url, make_adapter=HotJobAdapter):
    """抓新门户一个渠道的列表（不补正文），返回 ([PortalPost…], 渠道被跳过的原因或 None)。"""
    adapter = make_adapter()
    for attempt in range(_GATE_TRIES):
        skip_reason, answered = adapter._gate(portal_url)
        if answered:
            break
        if attempt + 1 < _GATE_TRIES:
            time.sleep(_GATE_RETRY_SECONDS)
    else:
        raise RuntimeError(f"{portal_url}：渠道发没发布探了 {_GATE_TRIES} 次都没答复，不能据此改库")
    adapter._enrich_details = lambda *args, **kwargs: None   # 只要列表；正文留给之后的正常抓取
    envelope = json.loads(adapter.fetch(portal_url))["_intercepted"]
    if not adapter.fetch_complete:
        raise RuntimeError(f"{portal_url}：列表没翻完，不能据此改库")
    posts = []
    for payload in envelope:
        for row in ((payload.get("data") or {}).get("pageForm") or {}).get("pageData") or []:
            key = str(row.get("externalKey") or "").strip()
            job = adapter._map(row)
            if key and job:
                posts.append(PortalPost(key, job.title, job.jd_url, adapter._recruit_type, skip_reason is None))
    return posts, skip_reason


def plan(rows, posts):
    """rows = [(id, jd_url, title)]，posts = [PortalPost]。
    返回 (rewrites=[(id, 旧链接, 新链接)], skipped=[(id, 原因键, 标题)])。纯函数，不碰库、不联网。"""
    by_key = defaultdict(list)
    for post in posts:
        by_key[post.external_key].append(post)
    proposals, skipped = [], []
    for row_id, old_url, title in rows:
        found = _OLD_POST_ID.search(old_url or "")
        if not found:
            skipped.append((row_id, "no_post_id", title))
            continue
        candidates = by_key.get(found.group(1), [])
        if not candidates:
            skipped.append((row_id, "not_in_portal", title))
            continue
        candidates = [p for p in candidates if p.published]
        if not candidates:
            skipped.append((row_id, "channel_unpublished", title))
            continue
        candidates = [p for p in candidates if p.title.strip() == (title or "").strip()]
        if not candidates:
            skipped.append((row_id, "title_mismatch", title))
            continue
        old_rt = _OLD_RECRUIT_TYPE.search(old_url)
        same_channel = {p.url for p in candidates if old_rt and str(p.recruit_type) == old_rt.group(1)}
        urls = same_channel or {p.url for p in candidates}
        if len(urls) != 1:
            skipped.append((row_id, "ambiguous", title))
            continue
        proposals.append((row_id, old_url, next(iter(urls)), bool(same_channel), title))
    # 两行要改成同一个新链接（旧库里同一岗位号按渠道存过多行）：留渠道对得上的那行，其余不动。
    rewrites, taken = [], set()
    for row_id, old_url, new_url, _, title in sorted(proposals, key=lambda p: not p[3]):
        if new_url in taken:
            skipped.append((row_id, "duplicate_target", title))
            continue
        taken.add(new_url)
        rewrites.append((row_id, old_url, new_url))
    return rewrites, skipped


_SELECT_SQL = """
    select id, jd_url, title
      from jobs
     where status = 'active'
       and company = %(company)s
       and jd_url like %(pattern)s
     order by jd_url, id
"""

# 与 rewrite_jd_url_prefix 同口径：active 的 canonical 唯一索引 + 表级 (company, title, location, jd_url) 唯一约束。
_CONFLICT = """
    (exists (select 1 from jobs k
              where k.status = 'active' and k.id <> j.id
                and k.canonical_jd_url = public.canonicalize_jd_url(%(new)s))
     or exists (select 1 from jobs k
                 where k.id <> j.id and k.company = j.company and k.title = j.title
                   and k.location = j.location and k.jd_url = %(new)s))
"""

_ROW = "j.id = %(id)s and j.status = 'active' and j.jd_url = %(old)s"

_CHECK_SQL = f"select 1 from jobs j where {_ROW} and not {_CONFLICT}"

_UPDATE_SQL = f"""
    update jobs j
       set jd_url = %(new)s,
           apply_url = case when j.apply_url = %(old)s then %(new)s else j.apply_url end
     where {_ROW}
       and not {_CONFLICT}
"""


def run(cur, company, wt_prefix, posts, apply=False):
    """返回 (候选行数, 改成/可改行数, skipped=[(id, 原因键, 标题)])。canonical 由触发器随 jd_url 重算。"""
    cur.execute(_SELECT_SQL, {"company": company, "pattern": like_prefix(wt_prefix)})
    rows = [(str(r[0]), r[1], r[2]) for r in cur.fetchall()]
    rewrites, skipped = plan(rows, posts)
    titles = {row_id: title for row_id, _, title in rows}
    done = 0
    for row_id, old_url, new_url in rewrites:
        params = {"id": row_id, "old": old_url, "new": new_url}
        if apply:
            try:
                cur.execute(_UPDATE_SQL, params)
                ok = cur.rowcount == 1
            except psycopg2.errors.UniqueViolation:
                ok = False   # 检查与写入之间别的进程刚插了同一个链接：这行不动，后面的行照常
        else:
            cur.execute(_CHECK_SQL, params)
            ok = cur.fetchone() is not None
        if ok:
            done += 1
        else:
            skipped.append((row_id, "conflict_or_changed", titles[row_id]))
    return len(rows), done, skipped


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--company", required=True, help="精确公司名，与旧前缀同时成立才动")
    ap.add_argument("--wt-prefix", required=True, help="旧版 jd_url 前缀，如 https://xyzq.hotjob.cn/wt/xyzq/")
    ap.add_argument("--portal", action="append", required=True,
                    help="新门户渠道页（…/SU…/pb/social.html | school.html | interns.html），可重复")
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    args = ap.parse_args(argv)
    if not re.match(r"^https://[^/]+/wt/[^/]+/", args.wt_prefix):
        ap.error("--wt-prefix 必须形如 https://{host}/wt/{BRAND}/")
    for url in args.portal:
        if not _PORTAL_URL.match(url):
            ap.error(f"--portal 必须形如 https://{{host}}/SU…/pb/social.html（或 school / interns）：{url}")
    if len(set(args.portal)) != len(args.portal):
        ap.error("--portal 有重复")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出（本脚本只对自建香港 jobs 库生效）")
        return 1
    posts = []
    for url in args.portal:
        channel_posts, skip_reason = fetch_portal_posts(url)
        posts.extend(channel_posts)
        state = f"未发布，不往这里改（{skip_reason}）" if skip_reason else "已发布"
        print(f"新门户 {url.rsplit('/', 1)[-1]}：{len(channel_posts)} 个岗，{state}")
    conn = jobs_db.get_conn()  # autocommit=True，别加 `with conn:`
    try:
        with conn.cursor() as cur:
            total, done, skipped = run(cur, args.company, args.wt_prefix, posts, apply=args.apply)
    finally:
        conn.close()
    head = f"company='{args.company}' 旧前缀 {args.wt_prefix}"
    if not total:
        print(f"{head}：没有 active 行 —— 无事可做")
        return 0
    verb = "已改" if args.apply else "dry-run 将改"
    print(f"{head}：active {total} 行，{verb} {done} 行" + ("" if args.apply else "（加 --apply 真写）"))
    for reason, count in Counter(reason for _, reason, _ in skipped).most_common():
        examples = [f"{title}（{row_id}）" for row_id, r, title in skipped if r == reason][:5]
        print(f"  不动 {count} 行：{SKIP_REASONS[reason]}。例：{'；'.join(examples)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
