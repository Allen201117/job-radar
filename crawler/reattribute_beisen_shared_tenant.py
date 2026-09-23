"""北森「一个租户挂着多家公司」的存量归属纠正：逐行按岗位自报的招聘机构改 company。

治的病（2026-09-23）：chinalife.zhiye.com 同时发中国人寿与广发银行的岗，adapter 过去每条都贴
sources.company。adapter 已改成按岗位的 Org 归属（见 adapters/china_ats.py 的 _BEISEN_SHARED_TENANTS），
列表里还挂着的岗下一轮重抓会自愈（company 在 jobs_db._UPDATE_COLS 里），但**已经不在列表里的**
永远等不到重抓（实测 616 行：北森详情接口 Status=2，库里仍 active——北森的 list-absence 还在观察模式）。
rename_job_company.py 按 jd_url 前缀整批改名，这里用不上：同一个前缀下两家公司混在一起，只能逐行判。

判据 = 与 adapter 同一对函数（beisen_hiring_entity + beisen_shared_tenant_owner），不另写一套：
  · 招聘机构先从整租户列表取（一次翻全），列表里没有的再逐条问详情接口 GetJobAdInfo
    （已下线的岗详情接口照样返回 Org，实测 616/616）；
  · 机构属于别家 → 改成别家；属于本家 → 改成 --home；**查不到机构的行一律不动**（宁可漏改不可错改）。
护栏同 rename_job_company：默认 dry-run，--apply 才写；只动 jd_url 在该 host 下的行；
UPDATE 带「company 仍是读的时候那个值」条件，防两步之间被并发改过；参数一律绑定。
报数分方向（A→B、B→A 各多少行），不只报净值。

⚠️ 顺序：必须等 adapter 修复进了 main 再 --apply。company 在 _UPDATE_COLS 里，旧代码的下一轮重抓
会把列表里的行全刷回 sources.company。

用法：
    python3 crawler/reattribute_beisen_shared_tenant.py --host chinalife.zhiye.com --home 中国人寿          # dry-run
    python3 crawler/reattribute_beisen_shared_tenant.py --host chinalife.zhiye.com --home 中国人寿 --apply  # 真写
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from urllib.parse import parse_qs, urlparse

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402
from adapters.china_ats import (_BEISEN_ENTITY_FIELDS, _BEISEN_SHARED_TENANTS,  # noqa: E402
                                BeisenAdapter, beisen_hiring_entity, beisen_shared_tenant_owner)
from adapters.playwright_base import PlaywrightAdapter  # noqa: E402
from rename_job_company import like_prefix  # noqa: E402

_SELECT_SQL = "select id, jd_url, company, status from jobs where jd_url like %s"
_UPDATE_SQL = "update jobs set company = %s where id = any(%s::uuid[]) and company = %s"


def job_uuid(jd_url: str) -> str:
    """北森详情链接里的岗位 id（`?jobAdId=<uuid>`），统一小写；取不到返回空串。"""
    try:
        return ((parse_qs(urlparse(jd_url or "").query).get("jobAdId") or [""])[0]).strip().lower()
    except Exception:
        return ""


def list_entities(host: str) -> dict:
    """整租户列表一次翻全 → {岗位 id: 招聘机构}。复用 adapter 的抓取（共享租户会自动点名 Org 列）。"""
    adapter = BeisenAdapter()
    payload = adapter._httpx_fetch(f"https://{host}/")
    if not payload:
        raise RuntimeError(f"{host}: 列表没抓到（PortalId / 接口不通），不做任何判断")
    out = {}
    for resp in json.loads(payload).get("_intercepted") or []:
        for row in resp.get("Data") or []:
            uid = str(row.get("Id") or "").lower()
            if uid:
                out[uid] = beisen_hiring_entity(row)
    return out


def detail_entity(client, host: str, uid: str):
    """单岗详情接口的招聘机构。返回 None = 没查到（接口失败 / 岗位不存在），调用方须跳过。"""
    fields = json.dumps(list(_BEISEN_ENTITY_FIELDS))
    for attempt in range(3):
        try:
            body = client.get(f"https://{host}/api/JobAd/GetJobAdInfo",
                              params={"jc": "", "jobAdId": uid, "displayFields": fields}).json()
            data = body.get("Data") if isinstance(body, dict) else None
            if not isinstance(data, dict):
                return None          # 「参数错误」/ 岗位不存在：Data=null
            return beisen_hiring_entity(data) or None
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    return None


def plan(rows, entities: dict, host: str, home: str):
    """纯函数：逐行算该挂哪家。rows=[(id, jd_url, company, status)]，entities={岗位 id: 招聘机构}。
    返回 (changes=[(id, 旧名, 新名, status)], stats Counter)。查不到机构的行不进 changes。"""
    changes, stats = [], Counter()
    for job_id, jd_url, company, status in rows:
        entity = entities.get(job_uuid(jd_url))
        if not entity:
            stats["unresolved"] += 1
            continue
        target = beisen_shared_tenant_owner(host, entity) or home
        if target == company:
            stats["already_correct"] += 1
        else:
            changes.append((str(job_id), company, target, status))
    return changes, stats


def apply_changes(cur, changes) -> dict:
    """按 (旧名, 新名) 分组更新；返回 {(旧名, 新名): 实际改的行数}。"""
    groups = defaultdict(list)
    for job_id, old, new, _status in changes:
        groups[(old, new)].append(job_id)
    done = {}
    for (old, new), ids in groups.items():
        cur.execute(_UPDATE_SQL, [new, ids, old])
        done[(old, new)] = cur.rowcount
        if cur.rowcount != len(ids):
            print(f"  ⚠️ {old} → {new}：计划改 {len(ids)} 行、实际改 {cur.rowcount} 行（差额 = 两步之间被并发改过）")
    return done


def report(changes, stats, home: str, host: str) -> None:
    print(f"已正确 {stats['already_correct']} 行；查不到招聘机构、不动 {stats['unresolved']} 行")
    by_dir = defaultdict(Counter)
    for _id, old, new, status in changes:
        by_dir[(old, new)][status] += 1
    names = {home} | {c for _p, c in _BEISEN_SHARED_TENANTS[host]} | {o for o, _n in by_dir} | {n for _o, n in by_dir}
    print("分方向（每个方向都列，0 也列）：")
    for old in sorted(names):
        for new in sorted(names):
            if old != new:
                c = by_dir.get((old, new), Counter())
                detail = "、".join(f"{s} {n}" for s, n in sorted(c.items()))
                print(f"  {old} → {new}：{sum(c.values())}" + (f"（{detail}）" if detail else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", required=True, help="共享租户的北森 host（须已登记在 _BEISEN_SHARED_TENANTS）")
    ap.add_argument("--home", required=True, help="租户本家公司名（= 该租户 sources.company）")
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    ap.add_argument("--sleep", type=float, default=0.2, help="逐条问详情接口的间隔秒数")
    args = ap.parse_args(argv)
    if args.host not in _BEISEN_SHARED_TENANTS:
        ap.error(f"{args.host} 没登记在 _BEISEN_SHARED_TENANTS，不是共享租户")
    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出（本脚本只对自建香港 jobs 库生效）")
        return 1

    conn = jobs_db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_SELECT_SQL, [like_prefix(f"https://{args.host}/")])
            rows = cur.fetchall()
        print(f"{args.host} 下共 {len(rows)} 行：{dict(Counter(r[3] for r in rows))}")

        entities = list_entities(args.host)
        from_list = sum(1 for r in rows if job_uuid(r[1]) in entities)
        need = sorted({job_uuid(r[1]) for r in rows if job_uuid(r[1]) and job_uuid(r[1]) not in entities})
        with httpx.Client(timeout=20, follow_redirects=True,
                          headers={"User-Agent": PlaywrightAdapter.user_agent}) as client:
            for uid in need:
                found = detail_entity(client, args.host, uid)
                if found:
                    entities[uid] = found
                time.sleep(args.sleep)
        from_detail = sum(1 for u in need if u in entities)
        print(f"招聘机构来源：列表 {from_list} 行 / 详情接口 {from_detail} 个岗 / 详情也查不到 {len(need) - from_detail} 个岗")

        changes, stats = plan(rows, entities, args.host, args.home)
        report(changes, stats, args.home, args.host)
        if not args.apply:
            print(f"\ndry-run：将改 {len(changes)} 行（加 --apply 真写）")
            return 0
        with conn.cursor() as cur:
            done = apply_changes(cur, changes)
        print(f"\n已改 {sum(done.values())} 行：" + "；".join(f"{o} → {n} {c}" for (o, n), c in done.items()))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
