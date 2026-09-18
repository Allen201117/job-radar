"""找招聘入口的五条车道：**搜索额度只能是最后手段**（创始人 2026-09-18 定）。

背景：`entry_finder` 的搜索是全局共享额度（CLAUDE.md「搜索额度是全局共享的」），
缺口漏斗每跑一家就吃一次，与 T3 洞察、校招时间线链抢同一个池子。而「找入口」这件事
本身有大量**零额度/近零成本**的办法先试。按成本从低到高：

  1. slug      —— 五大 ATS 域名套路固定（`{slug}.zhiye.com` / `{slug}.hotjob.cn` /
                  `{slug}.jobs.feishu.cn` / Moka / WinTalent），discover_domestic 早有确定性
                  探活 oracle；猜不中是**变体太少**，用 LLM 补 ≤10 个变体（几分钱、不吃搜索额度）。
  2. homepage  —— 公司官网域名比校招入口好猜；首页/招聘模板页里找「加入我们 / Careers」，
                  一跳到 ATS 交给指纹。纯 httpx（site_entry，本仓库已有）。
  3. hint      —— 聚合站/targets 文件里已有的网申链接当线索（campus_hints），零网络。
  4. iguopin   —— 央国企走国聘这个**免费索引**（已有 adapter + group_id 锚点核名），不搜外网。
  5. search    —— 以上都没找到才用 entry_finder（吃全局搜索额度）。

任一条车道找到并通过下游探活 + 归属核验就停 —— 但**核验不在本模块**：这里只负责
「产出候选 URL」，身份门 / 路由门 / 探活 / 真抓回读健康岗全部还在 gap_funnel 的原有那几道门上。
本模块不放宽任何一道门，只改「候选从哪来、按什么顺序来」。

⚠️ 每条车道有**独立退避**（`evidence.lanes.<车道>.next_retry_at`）：
一条车道失败只锁自己，不锁整家公司。CLAUDE.md 记过「退避锁死自我修复」的坑 ——
把所有失败共用一个公司级退避，等于任一条路不通就让这家公司整月消失。
"""
import zlib
from datetime import datetime, timedelta, timezone
from urllib.parse import quote


LANE_SLUG = "slug"
LANE_HOMEPAGE = "homepage"
LANE_HINT = "hint"
LANE_IGUOPIN = "iguopin"
LANE_SEARCH = "search"

# 顺序即成本顺序（见模块 docstring）。改顺序前先问「这条车道花的是什么」。
LANE_ORDER = (LANE_SLUG, LANE_HOMEPAGE, LANE_HINT, LANE_IGUOPIN, LANE_SEARCH)

# 逐车道退避天数：**各不相同是刻意的**。
#  · slug 靠 LLM 变体，模型换代/变体表扩充后有自我修复空间 → 中等 21 天；
#  · homepage 依赖对方官网结构，改版频率低 → 14 天（我们这边的解析也在改进）；
#  · hint 是静态线索表，没换表之前重试纯属白跑 → 最长 45 天；
#  · iguopin 只对央国企有意义，非央国企怎么试都不会有 → 45 天；
#  · search 的退避沿用 entry_finder 的公司级口径，这里只记账不另设（见 record 里的说明）。
LANE_RETRY_DAYS = {
    LANE_SLUG: 21,
    LANE_HOMEPAGE: 14,
    LANE_HINT: 45,
    LANE_IGUOPIN: 45,
    LANE_SEARCH: 7,
}

_IGUOPIN_TEMPLATE = "https://www.iguopin.com/job?company=%s"


def _now(now=None):
    return now or datetime.now(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat()


def _parse(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def backoff_until(now, lane, key):
    """退避时间 + 按公司名稳定抖动（同 gap_funnel._after_spread 的理由：
    固定天数会让同一批失败的公司全部落在同一天，队列一会儿空一会儿爆）。"""
    days = LANE_RETRY_DAYS.get(lane, 14)
    span = max(1, days // 3)
    offset = zlib.crc32(("%s|%s" % (lane, key or "")).encode("utf-8")) % (span * 2 + 1) - span
    return _iso(now + timedelta(days=max(1, days + offset)))


def lane_ledger(row):
    """取台账里的逐车道簿记（evidence.lanes）。形状不对一律当空表。"""
    lanes = (row or {}).get("evidence") or {}
    lanes = lanes.get("lanes")
    return dict(lanes) if isinstance(lanes, dict) else {}


def lane_blocked(ledger, lane, now):
    """这条车道还在退避里吗。读不懂的时间戳按「不退避」处理（fail-open：
    宁可多试一次，也不要因为一条坏时间戳把车道永久锁死）。"""
    entry = (ledger or {}).get(lane)
    if not isinstance(entry, dict):
        return False
    until = _parse(entry.get("next_retry_at"))
    return bool(until and until > now)


def plan_lanes(row, *, now=None, enabled=LANE_ORDER):
    """本轮该试哪些车道（按 LANE_ORDER，跳过退避中的）。"""
    now = _now(now)
    ledger = lane_ledger(row)
    return [lane for lane in LANE_ORDER
            if lane in set(enabled) and not lane_blocked(ledger, lane, now)]


def record_lane(ledger, lane, *, found, company, now, reason=None, candidates=0):
    """把一条车道的本轮结论写回簿记，返回**新** dict（不原地改调用方的对象）。

    找到了 → 清掉退避（next_retry_at=None），下次这家再来还先走这条便宜车道；
    没找到 → 只给**这条车道**设退避，其它车道不受影响。
    search 车道刻意不设自己的退避：它的重试节奏由 entry_finder 的公司级
    rounds_no_entry / next_retry_at 管着，这里再设一个会出现两套互相打架的节流。
    """
    out = dict(ledger or {})
    entry = {
        "found": bool(found),
        "reason": reason,
        "candidates": int(candidates or 0),
        "attempted_at": _iso(now),
        "attempts": int((out.get(lane) or {}).get("attempts") or 0) + 1,
    }
    if found or lane == LANE_SEARCH:
        entry["next_retry_at"] = None
    else:
        entry["next_retry_at"] = backoff_until(now, lane, company)
    out[lane] = entry
    return out


# ── 各车道的候选产出 ────────────────────────────────────────────────────────
# 统一返回 [{"url", "lane", ...可选 "preset"}]。
# `preset` = 这条候选**已经**由本车道自己做过平台识别与归属核验（如 discover_domestic 的
# title-verify / 自报 company 核验），下游可跳过 fingerprint 的页面身份门 —— 但**不跳过**
# 路由门、探活、真抓回读。给 preset 的车道必须自己有等价强度的归属判据，否则不许给。


def _candidate(url, lane, **extra):
    url = str(url or "").strip()
    return {**extra, "url": url, "lane": lane} if url else None


def slug_candidates(company, *, seeds=(), supabase=None, variant_fn=None,
                    platform_probe=None, platforms=("feishu", "hotjob", "beisen", "moka")):
    """车道 1：LLM 变体 × 五大 ATS 确定性 oracle。命中即带 preset（已 title-verify）。"""
    if variant_fn is None:
        import slug_variants

        variant_fn = slug_variants.variants
    if platform_probe is None:
        import discover_domestic

        platform_probe = discover_domestic._probe_company
    slugs = variant_fn(company, seeds=seeds, supabase=supabase)
    if not slugs:
        return []
    try:
        hits = platform_probe(
            {"company": company, "cn": company, "slugs": list(slugs), "industry": ""},
            set(platforms),
        ) or []
    except Exception:  # noqa: BLE001 —— 一条车道探测炸了不该拖垮整家公司
        return []
    return hit_candidates(hits)


def hit_candidates(hits):
    """discover_domestic 命中 → 候选列表。**只收 verified=True**（张冠李戴门不可旁路）。"""
    out = []
    for hit in hits or []:
        if not isinstance(hit, dict) or not hit.get("verified"):
            continue
        platform = hit.get("platform")
        urls = []
        if platform == "feishu":
            urls = [(hit.get("url"), "feishu")]
        elif platform == "wecruit":
            origin, suite = hit.get("origin"), hit.get("suite_key")
            if origin and suite:
                urls = [("%s/%s/pb/%s" % (origin, suite, page), "hotjob")
                        for page, _rt, count in (hit.get("channels") or []) if count]
        elif platform == "wt":
            origin, brand = hit.get("origin"), hit.get("wt_brand")
            if origin and brand:
                urls = [("%s/wt/%s/web/index" % (origin, brand), "wt")]
        elif platform == "beisen":
            urls = [(hit.get("url_social"), "beisen"), (hit.get("url_campus"), "beisen")]
        elif platform == "moka":
            urls = [(hit.get("url"), "moka")]
        for url, adapter in urls:
            item = _candidate(url, LANE_SLUG, preset={
                "platform": platform if platform != "wecruit" else "hotjob",
                "adapter": adapter,
                "source_url": url,
                "identity_ok": True,
                "identity_reason": "discover_domestic:title_verified",
                "reason": "slug_oracle:%s" % (hit.get("slug_hit") or hit.get("slug") or "?"),
            })
            if item:
                out.append(item)
    return out


def homepage_candidates(company, *, site_resolver, link_finder):
    """车道 2：官网首页 → 「加入我们 / Careers」链接（site_entry，纯 httpx）。

    返回 (候选列表, entry_channel)；entry_channel 沿用 site_entry 的通道名，
    台账里能看出官网是从本地域名表 / 库内源 / Wikidata / LLM 哪一路来的。
    """
    try:
        site = site_resolver(company)
    except Exception:  # noqa: BLE001
        site = None
    if isinstance(site, str):
        site = {"home_url": site, "entry_channel": "wikidata_site"}
    if not site or not site.get("home_url"):
        return [], None
    try:
        links = link_finder(company, site["home_url"]) or []
    except Exception:  # noqa: BLE001
        links = []
    out = [_candidate(item.get("url"), LANE_HOMEPAGE, **{
        key: value for key, value in (item or {}).items() if key != "url"
    }) for item in links]
    return [item for item in out if item], site


def hint_candidates(company, *, hints=None):
    """车道 3：聚合站/targets 的网申链接线索（零网络）。线索不带 preset —— 未经核验。"""
    import campus_hints

    url = campus_hints.hint_for(company, hints=hints)
    item = _candidate(url, LANE_HINT, reason="campus_url_hint")
    return [item] if item else []


_IGUOPIN_LIST_API = "https://gp-api.iguopin.com/api/jobs/v1/recom-job"
_IGUOPIN_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.iguopin.com",
    "Referer": "https://www.iguopin.com/",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
}


def iguopin_indexed(company, *, client=None, timeout=10):
    """国聘的索引里**真有这家**吗（一次列表检索 + 归属核名）。

    ⚠️ 不能省掉这一步直接给每家都拼一条 /job?company= 候选：那会让国聘变成**所有**公司的
    兜底入口，每家都要白跑一次 adapter 探活；更坏的是国聘的搜索是**集团级模糊匹配**
    （CLAUDE.md「归属准确性没有旁路」那块碑：84% 挂错公司就是这么来的），
    「搜得到」和「是这家」是两回事 —— 所以这里用 company_name_match 核名，
    不是「返回条数 > 0」就算数。

    任何异常返回 False（这条车道不通而已，下一条车道接着走）。
    """
    name = str(company or "").strip()
    if not name:
        return False
    import company_name_match
    import httpx

    payload = {"search": {"page": 1, "page_size": 20, "keyword": name},
               "recom": {"update_time": True, "company_nature": True, "hot_job": True}}
    try:
        cli = client or httpx.Client(timeout=timeout, follow_redirects=True)
        try:
            response = cli.post(_IGUOPIN_LIST_API, json=payload,
                                headers=_IGUOPIN_HEADERS, timeout=timeout)
            body = response.json() or {}
        finally:
            if client is None:
                cli.close()
    except Exception:  # noqa: BLE001
        return False
    if body.get("code") != 200:
        return False
    rows = ((body.get("data") or {}).get("list")) or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        listed = str(row.get("company_name") or row.get("company") or "").strip()
        if listed and company_name_match.company_name_matches(listed, name):
            return True
    return False


def iguopin_candidates(company, *, indexed=None):
    """车道 4：国聘当免费索引。**不搜外网**，先在国聘自己的索引里核到这家，再交给已有 adapter。

    归属的最终判据仍是 adapter 自己的 `group_id` 锚点核名（CLAUDE.md「归属准确性没有旁路」
    那块碑说的就是它）。这条候选带 preset 跳过**页面身份门** —— /job?company= 是纯 SPA 壳，
    httpx 拿不到可核验正文，再跑一遍页面身份门只会把好候选判掉；而真正管归属的那道门
    在下游 adapter 里，一条都没少。
    """
    name = str(company or "").strip()
    if not name:
        return []
    check = indexed if indexed is not None else iguopin_indexed
    if not check(name):
        return []
    url = _IGUOPIN_TEMPLATE % quote(name, safe="")
    item = _candidate(url, LANE_IGUOPIN, reason="iguopin_company_index", preset={
        "platform": "iguopin", "adapter": "iguopin", "source_url": url,
        "identity_ok": True,
        "identity_reason": "iguopin:indexed_name_match+adapter_group_id_anchor",
        "reason": "iguopin_company_index",
    })
    return [item] if item else []


def lane_metric_keys():
    """ops_runs 台账用的分车道计数键（含 not_found，绿灯零产出要看得见）。"""
    return tuple("found_by_%s" % lane for lane in LANE_ORDER) + ("not_found",)


def summarize_lanes(outcomes):
    """本轮结果 → {found_by_slug: n, ..., not_found: n}。所有键恒存在（含 0）。

    恒存在是刻意的：CLAUDE.md 明令「零产出必须看得见」，缺键的台账会被读成
    「这条车道没跑」而不是「跑了但一家没找到」。
    """
    counts = {key: 0 for key in lane_metric_keys()}
    for outcome in outcomes or []:
        lane = ((outcome or {}).get("evidence") or {}).get("entry_lane")
        key = "found_by_%s" % lane
        counts[key if key in counts else "not_found"] += 1
    return counts
