"""复核国聘存量岗位的「公司归属」，把张冠李戴的标成 removed。

治的病：国聘集团源给子公司岗位起的名字是 `实体名（集团简称）`，而归属门有过两个口子——
  · 2026-09-04：集团展开整个跳过核名，「屯昌县劳动就业服务中心（华润集团）」这类 84% 挂错；
  · 2026-10-10：公司主页接口问不到时放行（`adapters/iguopin._GroupGate` 的立碑注释），
    「中国人民解放军空军（中国石油）」「赞比亚谦比希湿法冶炼有限公司（比亚迪股份有限公司）」进库，
    全量复核 609 家 / 4,199 岗里 42 家 / 178 岗挂错。
adapter 侧两次都已堵上、不再新增；这个脚本清的是存量。

判据是**国聘自己的 group_id**，分三步，每一步都只认国聘的答复：
  ① 实体是谁：拿库里这家公司的一个在招岗去问岗位详情接口，得到 company_id 和国聘的公司名。
     库里的名字 = 国聘公司名 +「（Y）」→ Y 是我们加的集团标签；两者逐字相同 → 没加过标签，不在本工具范围。
  ② 实体属于谁：按 company_id 问公司主页接口，得到它的 group_id。
  ③ Y 是哪个集团：在**本次复核的全体公司**里，找国聘自报集团简称 / 全称等于 Y 的那些，取它们的 group_id。
  实体的 group_id 在③的集合里 → 挂对；不在 → 挂错；任何一步问不到 → 查不到（跳过，绝不据此判错）。
  ④ 写库前逐行再核一遍：判错公司名下的**每一个**在招岗都去问详情接口，company_id 与①拿到的一致才动这一行。
     「要动 N 行就核 N 行」——①只是每家抽一个岗，而同一个公司名字符串背后理论上可以是两家公司。

🚫 为什么不用旧版的两个做法（2026-10-10 同一批数据上对拍过，两个方向都错）：
  · 旧版用「实体名」去关键词搜、在前 10 条里找同名公司，主页接口失败不重试：
    挂错的 42 家它只认出 18 家，「空军（中国石油）」65 岗就在漏掉的 24 家 / 139 岗里。
  · 旧版比的是名字（互相包含就算对）：③ 里的 Y 若在国聘今天的口径里已经没有任何公司自报
    （集团改过简称，如「国聘知行派」），名字必然对不上 → 会把整个集团的岗一起判错。
    现在这种情况记「查不到」：**标签认不出来 ≠ 标签是错的**。

为什么标 removed 而不是改名或删除：
  · 这些是真实岗位，但挂在错误的公司名下，用户看到「中国石油」点进去是解放军空军 —— 必须撤下。
  · removed = 「抓取漏看、可复活」：purge-expired.yml 明确不删它；哪天我们真把这些公司
    作为独立源接进来，upsert 会自动把它转回 active。可逆。
  · 不改名：库里没有它们的正确来源，改名等于凭空造一个没有源支撑的公司。

用法（默认 dry-run，只报数不写库）：
    python3 crawler/audit_iguopin_attribution.py
    python3 crawler/audit_iguopin_attribution.py --apply
    python3 crawler/audit_iguopin_attribution.py --limit 50      # 先小样本看看（标签也只在这 50 家里认，偏保守）
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402
from adapters.iguopin import IguopinAdapter, group_id_of  # noqa: E402

_DETAIL_API = "https://gp-api.iguopin.com/api/jobs/v1/info"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.iguopin.com", "Referer": "https://www.iguopin.com/"}
_TRIES = 3            # 与 adapter 的主页接口同档：国聘会在约 10 秒后回 503，单次失败不是答复
_SAMPLE_JOBS = 6      # 样本岗已下线就换下一个，最多试这么多个
_WORKERS = 3          # 与 adapter 对 gp-api 的并发同档，不额外加压
# 判错的岗占到带标签岗的一半 = 更像是我们的判据坏了（国聘改了字段 / 集团批量改名），不是真有这么多错。
# 与仓库里其它「结果不可信就整轮不写」的闸同档；真要写（如 2026-09-04 那次 84%）加 --force。
_WRONG_RATIO_GUARD = 0.5


def label_of(company: str, entity_name: str):
    """库里的公司名里我们加的集团标签；没加过（或名字与国聘对不上）返回 None。
    只认「国聘公司名 +（标签）」这一种形态 —— 不能按「最后一个括号」去拆：
    「中煤科工集团上海研究院有限公司（中煤科工上海有限公司）」的括号是它自己名字的一部分。"""
    company, entity_name = (company or "").strip(), (entity_name or "").strip()
    if not entity_name or not company.startswith(entity_name + "（") or not company.endswith("）"):
        return None
    return company[len(entity_name) + 1:-1] or None


def judge(companies: dict, facts: dict) -> dict:
    """纯函数。companies: 库里公司名 -> 在招岗数；facts: 库里公司名 -> 国聘的答复，形如
    {"name": 国聘公司名, "group_id": ..., "group_names": [集团简称, 集团全称]}，问不到为 None，
    国聘明确答复没有这家公司为 {"not_found": True}。
    返回 {库里公司名: (结论, 说明)}，结论 ∈ right / wrong / unknown / unlabeled。"""
    label_ids: dict = {}
    for fact in facts.values():
        if not fact or not fact.get("group_id"):
            continue
        for name in fact.get("group_names") or ():
            if name:
                label_ids.setdefault(name, set()).add(str(fact["group_id"]))

    verdicts = {}
    for company in companies:
        fact = facts.get(company)
        if not fact:
            verdicts[company] = ("unknown", "国聘问不到这家公司（接口失败 / 样本岗全下线）")
            continue
        if fact.get("not_found"):
            verdicts[company] = ("unknown", "国聘答复没有这家公司（未找到或审核不通过），归属无从核对 —— 建议人工看一眼")
            continue
        if company == fact.get("name"):
            verdicts[company] = ("unlabeled", "")
            continue
        label = label_of(company, fact.get("name"))
        if not label:
            verdicts[company] = ("unknown", f"库里的名字与国聘的公司名「{fact.get('name')}」对不上")
            continue
        ids = label_ids.get(label)
        group = next((n for n in fact.get("group_names") or () if n), "") or "（国聘没给集团名）"
        if not ids:
            verdicts[company] = ("unknown", f"今天没有公司自报集团是「{label}」（集团改过名？），国聘说它属于 {group}")
        elif str(fact.get("group_id") or "") in ids:
            verdicts[company] = ("right", "")
        elif fact.get("standalone"):
            verdicts[company] = ("wrong", "国聘说它不隶属于任何别的集团（自己就是自己的集团）")
        else:
            verdicts[company] = ("wrong", f"国聘说它属于 {group}")
    return verdicts


def _get_json(client: httpx.Client, url: str, params: dict):
    """返回接口的 JSON；重试用尽仍失败返回 None。"""
    for attempt in range(_TRIES):
        if attempt:
            time.sleep(attempt)
        try:
            response = client.get(url, params=params)
            if response.status_code < 400:
                return response.json() or {}
        except Exception:  # noqa: BLE001 —— 503 / 超时 / 非 JSON 一律重试
            pass
    return None


def job_company_id(job_id, client: httpx.Client):
    """这个岗在国聘口径下是谁发的：返回 (company_id, 国聘公司名)。
    岗位已下线 → ("", "")；接口失败 → None（两者不许混：前者可以换下一个岗问，后者是问不到）。"""
    body = _get_json(client, _DETAIL_API, {"id": job_id})
    if body is None:
        return None
    detail = body.get("data") if body.get("code") == 200 else None
    if isinstance(detail, dict) and detail.get("company_id"):
        return str(detail["company_id"]), str(detail.get("company_name") or "").strip()
    return "", ""


def fetch_fact(job_ids, client: httpx.Client, adapter: IguopinAdapter):
    """一家公司在国聘口径下的身份与集团。任何一步问不到 → None。"""
    company_id = name = None
    for job_id in list(job_ids or ())[:_SAMPLE_JOBS]:
        found = job_company_id(job_id, client)
        if found is None:
            return None                       # 接口失败：别拿「下一个岗」去碰运气，直接算问不到
        if found[0]:
            company_id, name = found
            break
    if not company_id:
        return None                           # 样本岗全都下线了
    try:
        info = adapter._company_home(company_id, _HEADERS)    # 带重试；{} = 国聘明确说没有这家公司
    except Exception:  # noqa: BLE001
        return None
    if not info:
        # 国聘不认这家公司：归属无从谈起。对抓取是「拒」；对清存量是「查不到」——
        # 撤岗要的是「国聘说它属于别人」的正面证据，这里没有。单独标出来，方便人工看。
        return {"name": name, "not_found": True}
    own_id = str(info.get("id") or "").strip()
    if own_id != company_id:
        return None        # 答复不是这家公司的（残缺 / 串了）：不拿它当证据。实测 607 家里两者 100% 相同
    group_id = group_id_of(info, company_id)
    standalone = group_id in ("", own_id)
    if standalone:        # 自己就是自己的集团：集团名就是它自己的简称 / 全称
        names = [info.get("short_name"), info.get("name")]
    else:
        names = [info.get("group_short_name"), info.get("group_name")]
    return {"name": name, "company_id": company_id, "group_id": group_id or own_id, "standalone": standalone,
            "group_names": [str(n).strip() for n in names if str(n or "").strip()]}


def confirm_rows(rows, facts: dict, client: httpx.Client, pool) -> list:
    """逐行核：rows 是 [(job 行 id, 库里公司名, 国聘 job_id)]，返回确实由那家公司发布的行 id。
    岗已下线 / 接口失败 / company_id 对不上 → 这一行不动。"""
    def confirmed(row) -> bool:
        _row_id, company, job_id = row
        found = job_company_id(job_id, client) if job_id else None
        return bool(found) and found[0] == facts[company]["company_id"]

    return [row[0] for row, ok in zip(rows, pool.map(confirmed, rows)) if ok]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    ap.add_argument("--limit", type=int, default=0, help="只处理岗数最多的前 N 家（先小样本试）")
    ap.add_argument("--force", action="store_true",
                    help=f"判错占比 ≥ {_WRONG_RATIO_GUARD:.0%} 时仍然写库（默认拒绝，见 _WRONG_RATIO_GUARD）")
    args = ap.parse_args()

    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出")
        return 1
    conn = jobs_db.get_conn()
    try:
        with conn.cursor() as cur:
            # 全体国聘在招公司都要拉（含没带标签的）：③ 认标签靠的是它们自报的集团名。
            cur.execute("""
                select company, count(*),
                       (array_agg(substring(jd_url from 'id=([0-9]+)')
                                  order by last_seen_at desc nulls last, id))[1:%s]
                from jobs
                where status = 'active' and jd_url like %s
                group by company order by count(*) desc, company
            """, [_SAMPLE_JOBS, "%iguopin.com%"])
            listed = cur.fetchall()
    finally:
        conn.close()            # 问国聘要几分钟到十几分钟，不攥着库连接干等
    if args.limit:
        listed = listed[:args.limit]
    companies = {company: n for company, n, _ in listed}
    samples = {company: [j for j in (job_ids or []) if j] for company, _, job_ids in listed}
    print(f"待复核 {len(companies)} 家公司 / {sum(companies.values())} 个在招岗\n")

    adapter = IguopinAdapter()
    with httpx.Client(timeout=25, headers=_HEADERS, follow_redirects=True) as client, \
            ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        def ask(company):
            return fetch_fact(samples[company], client, adapter)

        facts = dict(zip(companies, pool.map(ask, companies)))
        # 问不到的再问一轮：这个工具不赶时间，而「问不到」一多，该撤的就漏了
        # （2026-10-10 全量试跑，只问一轮时 42 家挂错里有 9 家落在「查不到」）。
        again = [company for company, fact in facts.items() if fact is None]
        facts.update(zip(again, pool.map(ask, again)))

        verdicts = judge(companies, facts)
        tally = {kind: [c for c, (k, _) in verdicts.items() if k == kind]
                 for kind in ("right", "wrong", "unknown", "unlabeled")}

        def size(kind):
            return f"{len(tally[kind])} 家 / {sum(companies[c] for c in tally[kind])} 岗"

        for company in tally["wrong"]:
            print(f"  ✗ {company[:60]:<62} {companies[company]:>4} 岗  {verdicts[company][1]}")
        for company in tally["unknown"]:
            print(f"  ? {company[:60]:<62} {companies[company]:>4} 岗  {verdicts[company][1]}")
        print(f"\n挂对 {size('right')} ｜ 挂错 {size('wrong')} ｜ 查不到 {size('unknown')}"
              f" ｜ 没带标签（不在本工具范围）{size('unlabeled')}")

        wrong_rows = sum(companies[c] for c in tally["wrong"])
        labeled_rows = sum(companies[c] for kind in ("right", "wrong", "unknown") for c in tally[kind])
        blocked = bool(labeled_rows) and wrong_rows >= labeled_rows * _WRONG_RATIO_GUARD and not args.force
        if blocked:
            print(f"⚠️ 判错的岗占带标签岗的 {wrong_rows / labeled_rows:.0%}（≥ {_WRONG_RATIO_GUARD:.0%}）："
                  "更像是判据坏了，本次不写库。确认无误后加 --force。")
            return 2 if args.apply else 0
        if not tally["wrong"]:
            print("没有要撤的岗。")
            return 0

        conn = jobs_db.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("select id::text, company, substring(jd_url from 'id=([0-9]+)') from jobs "
                            "where status = 'active' and jd_url like %s and company = any(%s)",
                            ["%iguopin.com%", tally["wrong"]])
                rows = cur.fetchall()
                row_ids = confirm_rows(rows, facts, client, pool)
                skipped = len(rows) - len(row_ids)
                note = f"逐行核过 {len(row_ids)} / {len(rows)} 行" + (
                    f"；另 {skipped} 行没核上（岗已下线 / 接口失败 / 不是同一家公司），不动" if skipped else "")
                if args.apply:
                    cur.execute("update jobs set status = 'removed' "
                                "where status = 'active' and id = any(%s::uuid[])", [row_ids])
                    print(f"已标记 {cur.rowcount} 个岗 → status='removed'（可逆，purge 不删）。{note}")
                else:
                    print(f"dry-run：将标记 {len(row_ids)} 个岗 → status='removed'（可逆，purge 不删）。{note}")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
