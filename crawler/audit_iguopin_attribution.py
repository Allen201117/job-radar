"""复核国聘存量岗位的「公司归属」，把张冠李戴的标成 removed。

治的病（2026-09-04 实测）：国聘集团展开这条路径过去**整个跳过核名**
（见 adapters/iguopin.py 的 `_row_passes_match` 注释），把关键词模糊搜回来的无关公司
挂到了集团名下。抽样 40 家，**34 家（85%）归属是错的**：
  · 屯昌县劳动就业服务中心（华润集团）—— 国聘说它是事业单位、无集团
  · 中信建投期货有限公司（恒力石化）—— 国聘说它是地方国企、无集团
  · 新疆天业（集团）有限公司（中国物流集团）—— 国聘说它属于新疆天业集团
adapter 侧已修好、不再新增；这个脚本清的是存量。

判据：拿库里的 `实体名（集团名）` 里的实体名去国聘查它自己的公司主页，
比对 `group_short_name`。**只有国聘明确说了归属、且与我们标的不一致时才判错**——
查不到、接口失败一律跳过（宁可漏清，不可误杀）。

为什么标 removed 而不是改名或删除：
  · 这些是真实岗位，但挂在错误的公司名下，用户看到「恒力石化」点进去是中信建投期货 —— 必须撤下。
  · removed = 「抓取漏看、可复活」：purge-expired.yml 明确不删它；哪天我们真把这些公司
    作为独立源接进来，upsert 会自动把它转回 active。可逆。
  · 不改名：库里没有它们的正确来源，改名等于凭空造一个没有源支撑的公司。

用法（默认 dry-run，只报数不写库）：
    python3 crawler/audit_iguopin_attribution.py
    python3 crawler/audit_iguopin_attribution.py --apply
    python3 crawler/audit_iguopin_attribution.py --limit 50      # 先小样本看看
"""
import argparse
import os
import re
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402

_LIST_API = "https://gp-api.iguopin.com/api/jobs/v1/recom-job"
_HOME_API = "https://gp-api.iguopin.com/api/company/index/v1/home"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.iguopin.com", "Referer": "https://www.iguopin.com/"}
_SUFFIX_RE = re.compile(r"^(.*)（([^）]+)）$")


def official_group(entity: str, client: httpx.Client):
    """国聘口径下这家公司的集团简称。返回 None = 查不到/失败（调用方须跳过，不判错）。"""
    try:
        body = client.post(_LIST_API, json={
            "search": {"page": 1, "page_size": 10, "keyword": entity},
            "recom": {"update_time": True, "company_nature": True, "hot_job": True},
        }).json()
        hit = next((row for row in ((body.get("data") or {}).get("list") or [])
                    if str(row.get("company_name") or "").strip() == entity), None)
        if not hit:
            return None
        info = client.get(_HOME_API, params={"company_id": hit.get("company_id")}).json()
        company_info = (info.get("data") or {}).get("company_info")
        if not isinstance(company_info, dict):
            return None
        return str(company_info.get("group_short_name")
                   or company_info.get("short_name") or "").strip()
    except Exception:
        return None


def _mismatch(claimed: str, official: str) -> bool:
    """国聘说无集团（""）→ 我们标了集团就是错。否则要求双向包含之一，容忍简称长短差异。"""
    if official == "":
        return True
    return not (claimed == official or claimed in official or official in claimed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run 报数）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 家（先小样本试）")
    ap.add_argument("--sleep", type=float, default=0.15, help="每家之间的间隔秒数")
    args = ap.parse_args()

    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出")
        return 1
    conn = jobs_db.get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                select company, count(*) from jobs
                where status = 'active' and jd_url like %s and company ~ %s
                group by company order by count(*) desc
            """, ["%iguopin%", "（[^）]+）$"])
            rows = cur.fetchall()
            if args.limit:
                rows = rows[:args.limit]
            print(f"待复核 {len(rows)} 家公司\n")
            wrong = ok = skipped = affected = 0
            with httpx.Client(timeout=20, headers=_HEADERS, follow_redirects=True) as client:
                for full, n in rows:
                    m = _SUFFIX_RE.match(full)
                    if not m:
                        skipped += 1
                        continue
                    entity, claimed = m.group(1), m.group(2)
                    official = official_group(entity, client)
                    if official is None:          # 查不到 → 跳过，绝不据此判错
                        skipped += 1
                        continue
                    if not _mismatch(claimed, official):
                        ok += 1
                        continue
                    wrong += 1
                    affected += n
                    reason = f"国聘说{'无集团' if official == '' else '属于 ' + official}"
                    print(f"  ✗ {full[:44]:<46} {n:>4} 岗  {reason}")
                    if args.apply:
                        cur.execute("update jobs set status = 'removed' "
                                    "where status = 'active' and company = %s", [full])
                    time.sleep(args.sleep)
            verb = "已标记" if args.apply else "dry-run 将标记"
            print(f"\n归属正确 {ok} 家 / 归属错误 {wrong} 家 / 查不到跳过 {skipped} 家")
            print(f"{verb} {affected} 个岗 → status='removed'（可逆，purge 不删）")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
