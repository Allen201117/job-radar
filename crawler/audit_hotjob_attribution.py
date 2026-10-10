"""复核 wecruit（hotjob）存量源的公司归属：sources.company 与租户自报的 suite/config.companyName 对不上就报出来。

治的病：接 wecruit 源时公司名是人/清单给的，suiteKey 是探活猜的，探活只证明「这个租户真出岗」，
不证明「这个租户就是我们猜的那家公司」。已经两次张冠李戴：
  · 248：jd.hotjob.cn 记成京东，实为精雕科技（74 岗）
  · 274：wecruit SU612f55… 记成领益智造，实为特变电工（1,903 岗，挂错三个月无人发现）
新接源的门在 discover_domestic._hotjob_channel / gap_funnel 的 identity 核验里已经有了；**这个脚本查的是存量**——
每个 enabled 的 wecruit 源问一次租户自己的 `suite/config`（companyName 是租户后台填的，与探活无关），
两个方向任一方向核心 token 能对上就算通过（「新疆特变电工集团」↔「特变电工股份有限公司」靠反向的「特变电工」对上）。

只读、没有 --apply：对不上的源要人看过 suite/config 原文再决定改名（走 sources 迁移 + rename-job-company.yml），
因为「对不上」也可能是品牌名 vs 法人名（如「领益智造」vs「广东领益智造股份有限公司」这种是对得上的，
但「TME」vs「腾讯音乐娱乐」这种拉丁品牌名就对不上）。接口失败一律记 unknown、不判错。

老版 wt 门户（adapter_name='wt'）同样复核（2026-10-10 加）：
  · 迁移 105：www.hotjob.cn/wt/CT 记成中国电信，实为财通证券（215 岗挂错名四个月，同一批岗在财通门户下另有一份）
  · jks.hotjob.cn/wt/JKS 记成晶科能源，实为金科服务（85 岗；晶科能源在必投清单里，覆盖数全靠这批物业岗撑着）
两条都是接入时按 BRAND 代号猜的公司名。wt 没有 suite/config，门户「自己说自己是谁」只有三处，见 wt_identity。

用法：
    python3 crawler/audit_hotjob_attribution.py            # 全部 enabled wecruit 源 + wt 源
    python3 crawler/audit_hotjob_attribution.py --limit 20
"""
import argparse
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

import ops_runs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from discover_domestic import _CN_STOP, _GENERIC_PREFIX  # noqa: E402
from company_name_match import strip_leading_place  # noqa: E402  地名前缀（「苏州凌志软件」→「凌志软件」）

_CONFIG_API = "/wecruit/suite/config/"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_CHANNEL_SUFFIX = re.compile(r"(校招|社招|实习|校园招聘|社会招聘|实习生)$")
_NON_CJK = re.compile(r"[^一-鿿]+")

# 人工核过「名字对不上但归属没错」的租户（suiteKey → 理由）。只收「同一法人换了名」这一类；
# 品牌 vs 母公司靠 keywords / 组织树自动对上（一汽-大众 / 一汽奥迪 的 companyName 都是中国一汽，keywords 才写品牌）。
_KNOWN_OK = {
    "SU625d4a0b2f9d24287db127c8": "国投证券 = 原安信证券（2024 更名），租户 companyName 仍写旧名",
    "SU6116236b2f9d24229ef9364c": "华润水泥 = 华润建材科技（2024 更名），清单口径仍叫华润水泥",
    "SU6474230c0dcad45af14d7963": "瓜子二手车 = 车好多集团旗下品牌，租户以集团名自报",
}


def cjk_name(company: str) -> str:
    """sources.company → 只留中文、去掉渠道后缀：「领益智造 Lingyi 实习」→「领益智造」。"""
    cn = _NON_CJK.sub("", company or "")
    prev = None
    while prev != cn:
        prev, cn = cn, _CHANNEL_SUFFIX.sub("", cn)
    return cn


def _strip_place(cn: str) -> str:
    """剥地名前缀，剩不到 3 个字就不剥：「中国银行」剥成「银行」、「上海证券」剥成「证券」会对上任何一家银行 / 券商。"""
    rest = strip_leading_place(cn)
    return rest if len(rest) >= 3 else cn


def _tokens(cn: str, head: bool = True):
    """比对用的核心子串：全名、去掉「集团 / 有限公司 / 招聘 / 官网」后的名字、（head=True 时）前 3 个字。
    口径同 discover_domestic._core_tokens，严两处（那边是扩源探活的宽口径，不动它）：
      · 「地名 + 1 个字」不算 token：「中国石」会让中国石油对上中国石化，「中国电」会让中国电信对上中国电建；
      · 前 3 个字只在库名这一侧用（品牌多在名字开头）；门户文本的前 3 个字常是行业词
        （「新能源汽车招聘官网」的「新能源」会对上任何名字里带新能源的公司），反向比对时 head=False。"""
    cn = (cn or "").strip()
    stripped = cn
    for stop in _CN_STOP:
        stripped = stripped.replace(stop, "")
    toks = {cn, stripped.strip()}
    if head and len(cn) >= 4:
        toks.add(cn[:3])
    return {t for t in toks
            if len(t) >= 2 and t not in _GENERIC_PREFIX and len(strip_leading_place(t)) >= 2}


def names_agree(source_company: str, tenant_texts, reverse: bool = True) -> bool:
    """库里公司名 vs 租户自报的一组文本（companyName / keywords / 组织树名）：
    任一文本、任一方向核心 token 对上即通过；库名先剥地名前缀（苏州凌志软件 → 凌志软件）。
    库名没有中文时退回拉丁名不区分大小写子串（TCL ↔ TCL集团）。两边任一为空 → False。
    reverse=False：只认「库名的 token 落在文本里」，不认反方向——文本不是公司名（部门 / 事业群）时用。"""
    if isinstance(tenant_texts, str):
        tenant_texts = [tenant_texts]
    texts = [str(t or "").strip() for t in tenant_texts if str(t or "").strip()]
    a = cjk_name(source_company)
    if not texts:
        return False
    if not a:
        latin = _CHANNEL_SUFFIX.sub("", (source_company or "")).strip().lower()
        return bool(latin) and any(latin in t.lower() for t in texts)
    cands = {a, _strip_place(a)}
    for b in texts:
        for x in cands:
            if any(t in b for t in _tokens(x)):
                return True
            if reverse and any(t in x for t in _tokens(b, head=False)):
                return True
    return False


def tenant_identity(source_url: str, client: httpx.Client):
    """POST suite/config，返回 ([companyName, keywords, 组织树名…], error)。失败返回 (None, 原因)。"""
    parsed = urlparse(source_url)
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parts:
        return None, "no suite key"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    try:
        r = client.post(f"{origin}{_CONFIG_API}{parts[0]}",
                        headers={"Referer": source_url, "Origin": origin})
        data = (r.json() or {}).get("data") or {}
        name = str(data.get("companyName") or "").strip()
        if not name:
            return None, "no companyName in data"
        texts = [name, str(data.get("keywords") or "")]
        for org in data.get("suitOrgInfoPOs") or []:
            if isinstance(org, dict):
                texts.append(str(org.get("orgName") or org.get("name") or ""))
        return [t for t in texts if t.strip()], None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def load_sources(sb, limit=None, adapter="hotjob", url_like="%/pb/%"):
    """enabled 的 wecruit 源（/pb/ 形态；wt 源传 adapter='wt', url_like='%/wt/%'）；PostgREST 默认 1000 行截断，这里分页取全。"""
    rows, page, size = [], 0, 1000
    while True:
        res = (sb.table("sources").select("id,company,source_url,adapter_name")
               .eq("adapter_name", adapter).eq("enabled", True)
               .like("source_url", url_like)
               .order("source_url").range(page * size, page * size + size - 1).execute())
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < size:
            break
        page += 1
    return rows[:limit] if limit else rows


def audit(rows, client):
    """返回 (mismatches, unknowns, ok_count)。同一租户的多条源只问一次接口。"""
    cache = {}
    mismatches, unknowns, ok = [], [], 0
    for row in rows:
        url = row["source_url"]
        suite = ([p for p in urlparse(url).path.split("/") if p] or [""])[0]
        key = urlparse(url).netloc + "/" + suite
        if key not in cache:
            cache[key] = tenant_identity(url, client)
        tenant, err = cache[key]
        if tenant is None:
            unknowns.append((row["company"], url, err))
        elif suite in _KNOWN_OK or names_agree(row["company"], tenant):
            ok += 1
        else:
            mismatches.append((row["company"], url, tenant[0]))
    return mismatches, unknowns, ok


# ── 老版 wt 门户 ──────────────────────────────────────────────────────────────
# 门户「自己说自己是谁」只有三处（2026-10-10 全部 40 个 enabled wt 源逐个 live 看过）：
#   ① 首页 302 到新版门户（12 个）→ 问那个门户的 suite/config，和 wecruit 源同一把尺子；
#   ② 落地页 <title>（「金科服务招聘」「伊利招聘官网」；「首页」「职位列表」这类不带公司名的不算）；
#   ③ 列表首屏每个岗的 orgName（发布机构）。
# ①② 是门户自报的公司名：自报了、却和库名一条都对不上 → 对不上。只认 HTTP 200 的页面——403 / 拦截页的
#   title（「403 Forbidden」）不是自报，当成自报就把「没打通」报成了「挂错名」。
# ③ 只用来「对上」，不用来判「对不上」：它常是部门 / 城市 / 事业群（中广核是「西安 / 长沙」，华友钴业是
#   「新能源产业集团」，南方基金是「权益研究部」），证明不了挂错名——中广核的落地页正文、华友 9 条岗位正文
#   都写着自家名字。只有 ③ 且对不上的，单列「判不了」（南方基金就停在这一档：两边都没证据）。
_WT_PORTAL = re.compile(r"^https://[^/]+/SU[0-9a-f]+/pb/")
_HTML_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
# title 去掉这些词后不剩 2 个字 = 没带公司名（「首页」「职位列表」「招聘官网更新提示」「校园招聘」）。
_TITLE_BOILERPLATE = re.compile(
    r"首页|职位列表|职位|岗位|招聘|微官网|官网|官方|网站|系统|更新|提示|校园|社会|人才|加入我们|home|[\W_]", re.I)
_LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
# 拉丁词里不算品牌的：公司后缀与泛称。
_LATIN_GENERIC = {"group", "holdings", "holding", "limited", "company", "corporation", "corp", "ltd", "inc",
                  "china", "international", "global", "technology", "tech", "the", "and"}

# 人工核过「名字对不上但归属没错」的 wt 门户（host/BRAND → 理由），同 _KNOWN_OK 的口径。
_WT_KNOWN_OK = {
    "zhaolian.hotjob.cn/zhaolian": "招联金融 = 招联消费金融有限公司的品牌名，门户 title 与发布机构都写品牌名",
}


def wt_key(source_url: str):
    """wt 源地址 → 'host/BRAND'；不是 /wt/{BRAND}/ 形态返回 None。"""
    parsed = urlparse(source_url or "")
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parsed.netloc or len(parts) < 2 or parts[0].lower() != "wt":
        return None
    return f"{parsed.netloc}/{parts[1]}"


def wt_identity(source_url: str, client):
    """返回 (门户自报的公司名文本, 列表首屏的发布机构名, 没拿到的原因)。任一步失败只记原因、不抛。"""
    parsed = urlparse(source_url)
    brand = [p for p in parsed.path.split("/") if p][1]
    origin = f"{parsed.scheme}://{parsed.netloc}"
    index = f"{origin}/wt/{brand}/web/index"
    declared, orgs, notes = [], [], []
    try:
        resp = client.get(index)
        final = str(resp.url)
        if resp.status_code != 200:
            notes.append(f"首页 HTTP {resp.status_code}")
        elif _WT_PORTAL.match(final):
            texts, err = tenant_identity(final, client)
            if texts:
                declared = texts
            else:
                notes.append(f"首页跳到的新版门户没报公司名（{err}）")
        else:
            found = _HTML_TITLE.search(resp.text or "")
            title = re.sub(r"\s+", " ", found.group(1)).strip() if found else ""
            if len(_TITLE_BOILERPLATE.sub("", title)) >= 2:
                declared = [title]
    except Exception as e:  # noqa: BLE001
        notes.append(f"首页 {type(e).__name__}")
    for recruit_type in (2, 1):   # 社招 / 校招各看首屏 10 条；一个渠道失败不连累另一个
        try:
            payload = client.get(f"{origin}/wt/{brand}/web/json/position/list",
                                 params={"brandCode": 1, "recruitType": recruit_type, "page": 1},
                                 headers={"Referer": index}).json()
            for post in (payload or {}).get("postList") or []:
                name = str((post or {}).get("orgName") or "").strip()
                if name and name not in orgs:
                    orgs.append(name)
        except Exception as e:  # noqa: BLE001
            notes.append(f"列表 recruitType={recruit_type} {type(e).__name__}")
    return declared, orgs, notes


def _latin_brand_in(company: str, texts) -> bool:
    """库名里的拉丁品牌词（≥3 个字母、不是 Group / Ltd 这类泛称）作为整词出现在门户文本里：
    「TCL实业控股」↔「TCL招聘」。names_agree 只在库名**没有中文**时才比拉丁名，中英混写的库名要这一步补上。"""
    words = {w.lower() for w in _LATIN_WORD.findall(company or "")} - _LATIN_GENERIC
    return any(re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", str(t), re.I)
               for w in words for t in texts)


def wt_verdict(company: str, declared, org_names) -> str:
    """'ok' / 'mismatch' / 'undecidable'，判据见本节开头。
    发布机构只认「库名落在机构名里」：反过来拿机构名去库名里找，「新能源产业集团」会对上任何带新能源的公司。"""
    declared = [t for t in declared if t]
    org_names = [t for t in org_names if t]
    if (names_agree(company, declared) or names_agree(company, org_names, reverse=False)
            or _latin_brand_in(company, declared + org_names)):
        return "ok"
    return "mismatch" if declared else "undecidable"


def audit_wt(rows, client):
    """返回 (mismatches, undecidable, unknowns, ok_count)。同一门户的多条源只问一次。
    unknowns = 首页和列表都没拿到任何名字（接口打不通）；undecidable = 拿到了，但门户没自报公司名。"""
    cache = {}
    mismatches, undecidable, unknowns, ok = [], [], [], 0
    for row in rows:
        company, url = row["company"], row["source_url"]
        key = wt_key(url)
        if key is None:
            unknowns.append((company, url, "not a /wt/{BRAND}/ url"))
            continue
        if key not in cache:
            cache[key] = wt_identity(url, client)
        declared, orgs, notes = cache[key]
        if not declared and not orgs:
            unknowns.append((company, url, "；".join(notes) or "首页与列表都没给出名字"))
            continue
        verdict = "ok" if key in _WT_KNOWN_OK else wt_verdict(company, declared, orgs)
        if verdict == "ok":
            ok += 1
        elif verdict == "mismatch":
            mismatches.append((company, url, declared[0]))
        else:
            undecidable.append((company, url, "、".join(orgs[:4])))
    return mismatches, undecidable, unknowns, ok


def main(argv=None):
    started_at = datetime.now(timezone.utc)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    from db import get_supabase  # noqa: E402  延迟导入：单测不需要 Supabase 环境
    try:
        sb = get_supabase()
    except Exception as e:
        sys.stderr.write(f"[audit-hotjob] 无法获取 Supabase client，台账写不了: {type(e).__name__}\n")
        raise
    try:
        return _run(sb, args, started_at)
    except Exception as e:
        # 中途任何未捕获异常都要留痕（读源列表 / httpx client 初始化失败等），再原样抛出。
        ops_runs.record_ops_run(
            sb, "audit_hotjob_attribution", {"crash": type(e).__name__}, "failed", started_at=started_at,
        )
        raise


def _run(sb, args, started_at):
    rows = load_sources(sb, args.limit)
    wt_rows = load_sources(sb, args.limit, adapter="wt", url_like="%/wt/%")
    with httpx.Client(timeout=20, follow_redirects=True,
                      headers={"User-Agent": _UA, "Accept": "application/json, text/plain, */*"}) as client:
        mismatches, unknowns, ok = audit(rows, client)
        wt_mismatches, wt_undecidable, wt_unknowns, wt_ok = audit_wt(wt_rows, client)
    print(f"[audit-hotjob] sources={len(rows)} ok={ok} mismatch={len(mismatches)} unknown={len(unknowns)}")
    print(f"[audit-hotjob] wt sources={len(wt_rows)} ok={wt_ok} mismatch={len(wt_mismatches)} "
          f"undecidable={len(wt_undecidable)} unknown={len(wt_unknowns)}")
    for company, url, tenant in mismatches:
        print(f"::warning::归属对不上: sources.company='{company}' 租户自报='{tenant}' {url}")
    for company, url, tenant in wt_mismatches:
        print(f"::warning::归属对不上: sources.company='{company}' 门户自报='{tenant}' {url}")
    for company, url, err in unknowns + wt_unknowns:
        print(f"  unknown: '{company}' {url} ({err})")
    for company, url, orgs in wt_undecidable:
        print(f"  判不了: '{company}' {url}（门户没自报公司名，发布机构：{orgs}）")
    # 台账口径：mismatch/unknown 是核对结果，不是抓取失败——failed 只反映「租户接口打不通」（unknown）。
    # wt 的「判不了」是门户没自报公司名，不是接口失败，不计进 failed。
    ops_runs.record_ops_run(
        sb, "audit_hotjob_attribution",
        {"sources": len(rows), "ok": ok, "mismatch": len(mismatches), "unknown": len(unknowns),
         "wt_sources": len(wt_rows), "wt_ok": wt_ok, "wt_mismatch": len(wt_mismatches),
         "wt_undecidable": len(wt_undecidable), "wt_unknown": len(wt_unknowns)},
        ops_runs.status_from_counts(len(rows) + len(wt_rows), len(unknowns) + len(wt_unknowns)),
        started_at=started_at,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
