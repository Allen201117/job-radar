"""crawler/auto_discover.py — 每日定向自动扩源（发现 → live 探活验证 → 只入库真产岗的）。

为何：产品要岗位库**自动扩充、不靠人工开 session**。但守住 §3「精 > 量、禁止猜 slug 入库」——
本脚本不铺量、不猜 slug 入库：
  · 目标只来自 **精选目标公司清单**（targets_private500/soe500.json，{company,cn,slugs,industry}）
    + **用户真实需求**（user_preferences.target_companies，优先 probe）。
  · 只取 **库里还没有的** 公司，复用已验证的 `discover_domestic.sweep` 对其 slug 做 httpx live 探活
    （feishu / hotjob / wt）。
  · 只有 `to_passed`（verified + 真产岗 count>0 + 标题核验防张冠李戴）的源才入库——**探活不过绝不入库**，
    所以"猜 slug 去 probe"是安全的（猜错=verified False=丢弃，绝不会变成乱爬的源）。

三道安全闸（同 list-absence 套路）：
  ① env AUTO_DISCOVER_APPLY 默认 **dry-run**（只数不插，先线上验证产出干净再开）；
  ② source_url 已存在跳过（去重，不重复入库）；
  ③ 每日 probe / insert 上限（不一夜铺量）。
beisen / moka 的逐岗 count 需浏览器确认，本 httpx cron 不碰（留 browser 变体后置）。
"""
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import db
import ops_runs
import discover_domestic as dd
from generate_targets import norm_company

DAILY_TARGET_CAP = int(os.environ.get("AUTO_DISCOVER_TARGET_CAP", "80"))   # 每日最多 probe 多少家缺失公司
DAILY_INSERT_CAP = int(os.environ.get("AUTO_DISCOVER_INSERT_CAP", "40"))   # 每日最多入库多少源
PLATFORMS = {"feishu", "hotjob"}   # httpx-safe（hotjob 内含 wt/wecruit）；beisen/moka 需浏览器，留后置
# 科技/新经济/消费清单排最前 → load 时标 _priority，plan_targets 里优先探（对齐目标用户，见 CLAUDE.md §3
# 「保精度逐步扩量」：民营500强 76% 是传统制造，与目标用户错配，别让它淹没科技/消费候选）。
_CURATED_FILES = ("targets_must_apply.json", "targets_tech_consumer.json", "targets_private500_full.json",
                  "targets_private500.json", "targets_soe500.json")
_MUST_APPLY_FILES = {"targets_must_apply.json"}
_PRIORITY_FILES = {"targets_tech_consumer.json"}

# ── 校招板块缺口重探（Track A2）：与 lib/campus-sources.ts 的 CAMPUS_URL_RE 同口径
# （两端各自实现，判定逻辑必须一致，否则「校招覆盖率」两处会打架）。
_CAMPUS_TOKEN_RE = re.compile(r"campus|xiaozhao|校招|校园|campus_apply|/campus", re.I)
# moka 社招源 URL 反推 slug：新命名 social-recruitment，旧存量命名 apply，两种历史命名并存。
_MOKA_SOCIAL_SLUG_RE = re.compile(r"app\.mokahr\.com/(?:social-recruitment|apply)/([^/?#]+)", re.I)
# 塌陷行业（用户反馈校招覆盖薄弱的行业，见 P2 设计文档）优先补校招板块。
CAMPUS_GAP_INDUSTRIES = ("传媒/文娱", "物流/供应链", "教育", "金融")
CAMPUS_GAP_CAP = int(os.environ.get("AUTO_DISCOVER_CAMPUS_GAP_CAP", "30"))   # 每日最多重探多少家缺校招板块的公司


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_curated_targets():
    """精选目标公司清单（sweep-shape：{company,cn,slugs,industry}）；多文件按公司名去重(文件间有重叠)。"""
    out, seen = [], set()
    base = Path(__file__).resolve().parent
    for fn in _CURATED_FILES:
        p = base / fn
        if not p.exists():
            continue
        must_apply = fn in _MUST_APPLY_FILES
        priority = fn in _PRIORITY_FILES
        try:
            for t in (json.loads(p.read_text(encoding="utf-8")) or []):
                c = (t.get("company") or "").strip()
                if c and c not in seen:
                    seen.add(c)
                    if must_apply:
                        out.append({**t, "_must_apply": True})
                    elif priority:
                        out.append({**t, "_priority": True})
                    else:
                        out.append(t)
        except Exception:
            pass
    return out


def load_targets(existing_companies):
    """静态精选清单 (+ 可选 LLM 每日生成的新候选，标 _priority 优先探)。
    LLM 生成 gated on env AUTO_DISCOVER_LLM，默认关；生成的候选一样走后续探活验证门，编造/猜错自动丢。
    「持续喂清单」= 静态清单会烧完，靠 generate_targets 每天补新候选维持扩源速度。"""
    targets = load_curated_targets()
    if os.environ.get("AUTO_DISCOVER_LLM", "").lower() in ("1", "true", "yes"):
        try:
            import generate_targets as gt
            n = int(os.environ.get("AUTO_DISCOVER_LLM_N", "50"))
            llm = gt.llm_generate(existing_companies, n=n)
            known = {(t.get("company") or "").strip() for t in targets}
            targets = [c for c in llm if c["company"] not in known] + targets  # LLM 新候选排最前
        except Exception as e:
            print(f"[auto_discover] LLM 生成清单跳过（回退静态）: {type(e).__name__}: {e}")
    return targets


def load_user_wanted_companies(sb):
    """用户需求信号：user_preferences.target_companies 里所有公司（去重）。"""
    try:
        rows = sb.table("user_preferences").select("target_companies").execute().data or []
    except Exception:
        return set()
    wanted = set()
    for r in rows:
        for c in (r.get("target_companies") or []):
            if c and str(c).strip():
                wanted.add(str(c).strip())
    return wanted


def existing_source_keys(sb):
    """库里已有的公司名 + source_url（含 disabled），用于去重。
    ⚠️ 必须分页拉全量：PostgREST 单次查询默认最多返回 1000 行，而 sources 已越过 1000
    （2026-07-14 实测 1042）→ 不分页拿到的是**残缺**去重集，尾部（正是最新入库的）漏掉
    → 去重失效 → 同一 source_url 被反复重复入库（当天 browser 道两轮把 15 个 URL 各插了 2 次）。
    DB 侧另有 sources_source_url_key 唯一索引兜底（迁移 180）。
    分页走 db.fetch_all_rows（每页带 .order("id")：无稳定排序键翻页会重复取同一行 + 漏掉另一行）。"""
    companies, urls = set(), set()
    for r in db.fetch_all_rows(lambda: sb.table("sources").select("company,source_url")):
        c = (r.get("company") or "").strip()
        u = (r.get("source_url") or "").strip()
        if c:
            companies.add(c)
        if u:
            urls.add(u)
    return companies, urls


def load_campus_gap_source_rows(sb):
    """校招缺口判定要用到 source_url/notes/adapter_name（不止公司名，existing_source_keys 只拿名字
    不够判「有没有校招板块」）。⚠️ 同 existing_source_keys：sources 已越过 PostgREST 单次 1000 行硬顶，
    必须分页拉全量，否则尾部（常是最新入库的）漏判导致重复重探。"""
    return db.fetch_all_rows(
        lambda: sb.table("sources").select("company,source_url,notes,adapter_name,enabled"))


def extract_moka_slug(url):
    """从 moka 社招源 URL 反推校招板块探测要用的 slug（同租户 campus-recruitment/{slug} 用同一
    slug，见 discover_domestic.moka_probe）。两种历史命名都要认：
    app.mokahr.com/social-recruitment/{slug}/{orgId}（现行）与 .../apply/{slug}/{orgId}（存量）。"""
    m = _MOKA_SOCIAL_SLUG_RE.search(url or "")
    return m.group(1) if m else None


def plan_campus_gap_targets(must_apply_by_industry, source_rows, cap, seed=0):
    """纯函数：找"已有源但缺校招板块、且能反推出 moka slug"的必投公司 —— 绕过 plan_targets 的整家
    去重（那个去重只防「重复探全新公司」，不该挡「补缺失板块」，否则这批公司永远探不到校招板块）。

    判定口径镜像 lib/campus-sources.ts 的 getCampusSourceCoverage：公司名子串（大小写不敏感）匹配
    必投清单 pattern + enabled 过滤；已有任意源命中 _CAMPUS_TOKEN_RE（URL 或 notes）视为已覆盖，
    幂等跳过（不重复补）。

    A1 的探测器目前只把 moka 的校招板块接上（beisen url_campus / hotjob-wt recruitType=1 校招渠道
    已在 A0 摸清覆盖，不需重探；feishu 的 portal_type 不分社招校招，也不是缺口）——所以本函数只挑
    「匹配到的源里有 moka 社招源、且能从其 URL 反推出 slug」的公司；反推不出 slug 的本轮跳过，不硬猜。

    塌陷行业（CAMPUS_GAP_INDUSTRIES）优先；同一优先级内按 seed 轮转（避免每天死磕同一批）。
    返回值 shape 与 plan_targets 的目标一致（company/cn/slugs/industry），可直接喂
    discover_domestic.sweep(targets, {"moka"})。"""
    enabled_rows = [r for r in (source_rows or []) if r.get("enabled")]
    by_company_lower: dict = {}
    for row in enabled_rows:
        company = (row.get("company") or "").strip()
        if company:
            by_company_lower.setdefault(company.lower(), []).append(row)

    def _matched(pattern):
        needle = str(pattern or "").replace("%", "").strip().lower()
        if not needle:
            return []
        out = []
        for lower_company, rows in by_company_lower.items():
            if needle in lower_company:
                out.extend(rows)
        return out

    def _is_campus_row(row):
        return bool(_CAMPUS_TOKEN_RE.search(row.get("source_url") or "")) or \
               bool(_CAMPUS_TOKEN_RE.search(row.get("notes") or ""))

    seen_names = set()
    priority, rest = [], []
    for industry, companies in (must_apply_by_industry or {}).items():
        for entry in (companies or []):
            name = (entry.get("name") or "").strip()
            pattern = (entry.get("pattern") or "").strip()
            if not name or not pattern or name in seen_names:
                continue
            matched = _matched(pattern)
            if not matched:
                continue  # 连社招源都没有 → 不是「补校招」范畴，交给 plan_targets 整家新探
            if any(_is_campus_row(r) for r in matched):
                continue  # 已有校招源 → 幂等跳过
            moka_row = next((r for r in matched
                             if (r.get("adapter_name") or "") == "moka"
                             and extract_moka_slug(r.get("source_url") or "")), None)
            if not moka_row:
                continue  # 本轮只支持 moka 校招反探；其余平台的缺口本轮跳过，不硬猜
            slug = extract_moka_slug(moka_row["source_url"])
            seen_names.add(name)
            target = {"company": name, "cn": name, "industry": industry, "slugs": [slug],
                      "source_url": moka_row["source_url"]}
            (priority if industry in CAMPUS_GAP_INDUSTRIES else rest).append(target)

    rng = random.Random(seed)
    rng.shuffle(priority)
    rng.shuffle(rest)
    return (priority + rest)[:cap]


def plan_targets(curated, user_wanted, existing_companies, cap, seed=0):
    """纯函数：本轮要 probe 的目标 = 库里没有的精选目标公司。排序 = 用户点名 > 必投缺口(_must_apply)
    > 科技/新经济/消费(_priority) > 其余；各梯队内按 seed 随机轮转（避免每天死磕同一批失败目标，
    让覆盖随天数滚动），封顶 cap。
    用户点名按 norm_company 归一后匹配 company/cn 两个字段——用户写「北京字节跳动科技有限公司」、
    清单写「字节跳动」也要命中（旧实现字符串全等，用户信号经常空转）。"""
    existing = {str(x).strip() for x in (existing_companies or set()) if str(x).strip()}
    existing_norm = {norm_company(x) for x in existing if norm_company(x)}
    raw_wanted = {str(w).strip() for w in (user_wanted or set()) if str(w).strip()}
    wanted_norm = {norm_company(w) for w in raw_wanted if norm_company(w)}

    def _is_wanted(t):
        for key in ("company", "cn"):
            v = (t.get(key) or "").strip()
            if v and (v in raw_wanted or (norm_company(v) and norm_company(v) in wanted_norm)):
                return True
        return False

    missing = []
    for t in curated:
        name = (t.get("company") or "").strip()
        nname = norm_company(name)
        if name and name not in existing and (not nname or nname not in existing_norm):
            missing.append(t)
    wanted_first = [t for t in missing if _is_wanted(t)]
    others = [t for t in missing if not _is_wanted(t)]
    must_apply = [t for t in others if t.get("_must_apply")]
    priority = [t for t in others if not t.get("_must_apply") and t.get("_priority")]
    rest = [t for t in others if not t.get("_must_apply") and not t.get("_priority")]
    rng = random.Random(seed)
    rng.shuffle(wanted_first)
    rng.shuffle(must_apply)
    rng.shuffle(priority)
    rng.shuffle(rest)
    return (wanted_first + must_apply + priority + rest)[:cap]


def plan_inserts(passed, existing_urls, cap):
    """纯函数：从 to_passed 结果挑可入库的 = source_url 不在库、批内去重、封顶 cap。"""
    seen = set(existing_urls)
    out = []
    for row in passed:
        url = (row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(row)
        if len(out) >= cap:
            break
    return out


def resolve_watch_requests(sb, company, source_id):
    """扩源成功后的闭环回写：匹配的「关注公司」请求 → covered。
    没有这步，用户在偏好页看到的覆盖状态永远停在「待接入」、只能等人工运营处理——
    机器听见了用户点名、也接入了，却不告诉用户。匹配用 norm_company 双侧归一（app 端
    normalized_company 的归一口径与 crawler 不同，不能直接比对）。失败不阻断主流程。"""
    try:
        target = norm_company(company)
        if not target:
            return 0
        rows = (sb.table("company_watch_requests")
                .select("id,company,normalized_company,matched_source_ids")
                .in_("status", ["queued", "researching"]).execute().data or [])
        n = 0
        for r in rows:
            cands = {norm_company(r.get("company") or ""), norm_company(r.get("normalized_company") or "")}
            if target not in cands:
                continue
            ids = [x for x in (r.get("matched_source_ids") or []) if x]
            if source_id and source_id not in ids:
                ids.append(source_id)
            sb.table("company_watch_requests").update({
                "status": "covered", "matched_source_ids": ids,
                "resolution_note": "每日自动扩源已接入（live 探活确认在招）",
                "updated_at": _now_iso(),
            }).eq("id", r["id"]).execute()
            n += 1
        if n:
            print(f"    ↳ 关注公司闭环: {company} 覆盖 {n} 条用户请求 → covered")
        return n
    except Exception as e:
        print(f"    watch 回写失败(不阻断): {type(e).__name__}: {e}")
        return 0


def insert_source(sb, row):
    """入库一条已验证源（service-role，与 app/api/sources 同字段口径），并给新公司排队职业洞察
    + 闭环回写用户「关注公司」请求（browser 变体复用本函数，两条扩源道同享闭环）。"""
    payload = {
        "company": row["company"], "source_url": row["url"], "source_type": "official",
        "adapter_name": row["adapter"], "crawl_method": "http",
        "segment": row.get("segment") or "private", "industry": row.get("industry"),
        "notes": f"auto_discover: live探活 {row.get('_valid', '?')} 岗", "enabled": True,
    }
    # 国内两条道不传该字段，继续使用数据库默认的 {CN}；海外入口显式指定覆盖区域。
    if row.get("regions"):
        payload["regions"] = row["regions"]
    res = sb.table("sources").insert(payload).execute()
    source_id = None
    try:
        source_id = ((res.data or [{}])[0] or {}).get("id")
    except Exception:
        pass
    resolve_watch_requests(sb, row["company"], source_id)
    try:
        sb.table("company_profiles").upsert(
            {"company": row["company"], "insight_checked_at": None}, on_conflict="company").execute()
    except Exception:
        pass


def main():
    apply = os.environ.get("AUTO_DISCOVER_APPLY", "").lower() in ("1", "true", "yes")
    started = _now_iso()
    sb = db.get_supabase()
    user_wanted = load_user_wanted_companies(sb)
    existing_companies, existing_urls = existing_source_keys(sb)
    curated = load_targets(existing_companies)
    seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
    targets = plan_targets(curated, user_wanted, existing_companies, DAILY_TARGET_CAP, seed=seed)
    print(f"[auto_discover] curated={len(curated)} user_wanted={len(user_wanted)} "
          f"existing={len(existing_companies)} → 本轮 probe {len(targets)} 家缺失公司 (apply={apply})")
    if not targets:
        ops_runs.record_ops_run(sb, "auto_discover", {"checked": 0, "produced": 0},
                                status="success", started_at=started, finished_at=_now_iso())
        print("[auto_discover] 无缺失目标，结束。")
        return

    hits = dd.sweep(targets, PLATFORMS)
    passed = dd.to_passed(hits)
    to_insert = plan_inserts(passed, existing_urls, DAILY_INSERT_CAP)
    print(f"[auto_discover] sweep 命中 {len(hits)} / 验证通过 {len(passed)} / 可入库(去重后) {len(to_insert)}")

    added = 0
    for row in to_insert:
        tag = "+ insert" if apply else "· dry-run"
        print(f"  {tag} [{row['adapter']}] {row['company']} ({row.get('_valid', '?')}岗) {row['url']}")
        if apply:
            try:
                insert_source(sb, row)
                added += 1
            except Exception as e:
                print(f"    insert 失败(跳过): {type(e).__name__}: {e}")

    ops_runs.record_ops_run(
        sb, "auto_discover",
        {"checked": len(targets), "produced": added, "companies_enriched": added,
         "candidates": len(to_insert)},
        status=ops_runs.status_from_counts(len(to_insert), len(to_insert) - added),
        started_at=started, finished_at=_now_iso())
    print(f"[auto_discover] 完成: 入库 {added} 源 (apply={apply})")


if __name__ == "__main__":
    main()
