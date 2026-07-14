"""海外必投公司的每日 ATS 自动扩源（公开 JSON 探活，默认 dry-run）。"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import auto_discover as ad
import db
import must_apply
import ops_runs
import probe
import workday_discovery


TARGETS_JSON = Path(__file__).resolve().parent / "targets_overseas_must_apply.json"
TARGET_CAP = int(os.environ.get("AUTO_DISCOVER_OVERSEAS_TARGET_CAP", "80"))
INSERT_CAP = int(os.environ.get("AUTO_DISCOVER_OVERSEAS_INSERT_CAP", "40"))
# workday 租户发现慢（一家最多 6×13 次 httpx）→ 每轮限做几家，别把 CI 跑超时。
WORKDAY_DISCOVER_CAP = int(os.environ.get("AUTO_DISCOVER_WORKDAY_CAP", "30"))
REGIONS = ["US", "SG", "Remote"]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


_OVERSEAS_REGIONS = {"US", "SG", "Remote"}


def existing_overseas_companies(sb):
    """已覆盖 = 「已有**海外**源」的公司（sources.regions 命中 US/SG/Remote），不是 sources 里的所有公司。
    ⚠️ 别拿 ad.existing_source_keys 的全量 company 集合做去重：Apple/Google/Amazon 等大厂库里早有
    **国内**源（apple_cn / workday / amazon 等），会把它们的海外 ATS 源整体挡在探活门外
    （live 实测：海外道因此 0 产出，只剩不用 greenhouse 的冷门公司被探）。
    也别只认 _ATS_URL 那 4 个模板——那样自建/workday 系的已有海外源会被漏判、天天重探。
    URL 级去重仍由 plan_inserts(existing_urls) 兜底，不会重复入库。"""
    try:
        rows = sb.table("sources").select("company,regions").execute().data or []
    except Exception as e:
        print(f"[auto_discover_overseas] 读取 sources 失败，按「全未覆盖」继续: {type(e).__name__}: {e}")
        return set()
    out = set()
    for r in rows:
        company = (r.get("company") or "").strip()
        regions = r.get("regions") or []
        if company and any(str(x).strip() in _OVERSEAS_REGIONS for x in regions):
            out.add(company)
    return out


def load_targets():
    """读取海外必投目标，并统一标记为最高静态优先级。"""
    try:
        rows = json.loads(TARGETS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[auto_discover_overseas] 读取目标清单失败，跳过: {type(e).__name__}: {e}")
        return []
    return [{**row, "_must_apply": True} for row in rows if isinstance(row, dict) and row.get("company")]


def _pattern_by_company():
    """公司展示名 → 必投清单里的 ILIKE 匹配模式（策展时就是按库里 company 的实际写法定的）。"""
    out = {}
    for companies in (must_apply.overseas_by_industry() or {}).values():
        for c in companies:
            name, pat = c.get("name"), c.get("pattern")
            if name and pat:
                out.setdefault(name, pat)
    return out


def filter_uncovered(targets, existing_names, pattern_map=None):
    """滤掉「库里已有海外源」的公司。

    ⚠️ 必须按必投清单的 ILIKE 模式匹配，不能拿展示名做精确/归一比对：库里公司名常是中英混写
    （清单写 Takeda，库里是「武田制药 Takeda」）→ 名字对不上就被当成缺口，白跑一整轮 workday
    租户发现（live 实测：Takeda/Danaher 都被这样白探，发现出来的源其实早在库里、最后全被 URL 去重挡掉）。
    """
    pmap = pattern_map if pattern_map is not None else _pattern_by_company()
    lowered = [str(n or "").lower() for n in existing_names]
    out = []
    for t in targets:
        company = t.get("company") or ""
        token = str(pmap.get(company, company)).replace("%", "").strip().lower()
        if token and any(token in n for n in lowered):
            continue
        out.append(t)
    return out


def build_candidates(targets):
    """展开公司 slug × ATS；URL 仅来自 probe.py 的公开 ATS 模板。"""
    out, seen = [], set()
    for target in targets:
        for adapter in target.get("ats") or []:
            url_fn = probe._ATS_URL.get(adapter)
            if not url_fn:
                continue
            for slug in target.get("slugs") or []:
                url = url_fn(slug)
                if url in seen:
                    continue
                seen.add(url)
                out.append({"company": target["company"], "adapter": adapter, "url": url,
                            "industry": target.get("industry"), "segment": "foreign"})
    return out


def build_workday_candidates(targets, covered_companies, discover_fn=None, cap=None):
    """Workday 兜底：对 ATS 模板没探到的公司做租户/站点发现。

    海外必投里的金融/医药/零售大厂（Salesforce/Pfizer/Visa/Cisco/Comcast…）几乎全在 Workday 上，
    而 Workday 的端点拼不出模板（wd 编号 + site 名各家自选）→ 之前这批公司一个都探不到。
    workday_discovery.discover 用 live 校准过的状态码信号去发现（404=租户在/422=不在），
    命中率实测 5/15；探不到的返回 None 直接丢，不入库、不污染。

    只对「ATS 模板已探到的公司」之外的做（covered_companies），别浪费探活预算。
    ⚠️ 发现一家最多 6(wd) × 13(site) 次 httpx —— 不设 cap 的话 80 家目标能把 CI 跑到超时，
    故按 WORKDAY_DISCOVER_CAP 限制每轮做几家（剩下的下轮 seed 轮转会轮到）。"""
    discover = discover_fn or workday_discovery.discover
    limit = WORKDAY_DISCOVER_CAP if cap is None else cap
    out, tried = [], 0
    for target in targets:
        company = target["company"]
        if company in covered_companies:
            continue
        if tried >= limit:
            break
        tried += 1
        try:
            found = discover(company, target.get("slugs") or [])
        except Exception as e:
            print(f"  ✗ {company} [workday] 发现异常: {type(e).__name__}: {e}")
            continue
        if not found:
            continue
        print(f"  ★ {company} [workday] 发现租户 {found['tenant']}.{found['wd']}/{found['site']} "
              f"({found['total']} 岗)")
        out.append({"company": company, "adapter": "workday", "url": found["url"],
                    "industry": target.get("industry"), "segment": "foreign"})
    return out


def confirm_candidates(candidates, timeout=12, probe_fn=None):
    """复用 probe 的解析和质量门，海外以岗位、有效详情链接为准，不要求在华地点。"""
    probe_fn = probe_fn or (lambda cand: probe.probe_one(cand, timeout=timeout))
    passed = []
    for cand in candidates:
        try:
            result = probe_fn(cand) or {}
        except Exception as e:
            print(f"  ✗ {cand['company']} [{cand['adapter']}]: {type(e).__name__}: {e}")
            continue
        parsed = result.get("parsed", 0) or 0
        valid = result.get("valid", 0) or 0
        sample = result.get("sample") or ""
        if parsed > 0 and valid > 0 and sample:
            passed.append({**cand, "_valid": valid, "_parsed": parsed, "regions": list(REGIONS)})
            print(f"  ✓ {cand['company']} [{cand['adapter']}] parsed={parsed} valid={valid} {sample}")
        else:
            print(f"  ✗ {cand['company']} [{cand['adapter']}] parsed={parsed} valid={valid} sample={bool(sample)}")
    return passed


def main():
    apply = os.environ.get("AUTO_DISCOVER_APPLY", "").lower() in ("1", "true", "yes")
    started = _now_iso()
    sb = db.get_supabase()
    user_wanted = ad.load_user_wanted_companies(sb)
    _, existing_urls = ad.existing_source_keys(sb)
    existing_companies = existing_overseas_companies(sb)
    all_targets = load_targets()
    # 「已有海外源」的公司按必投清单的 ILIKE 模式滤掉（库里多是「武田制药 Takeda」这类中英混写，
    # 拿展示名精确比对会漏判 → 白跑 workday 租户发现，最后又被 URL 去重挡掉）。滤完再交给
    # plan_targets 排序（故 existing 传空集，去重职责已前移到这里 + plan_inserts 的 URL 去重兜底）。
    curated = filter_uncovered(all_targets, existing_companies)
    seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
    targets = ad.plan_targets(curated, user_wanted, set(), TARGET_CAP, seed=seed)
    print(f"[auto_discover_overseas] curated={len(all_targets)} 家 → 未覆盖 {len(curated)} "
          f"(库里已有海外源 {len(existing_companies)} 家) → 本轮 probe {len(targets)} 家 (apply={apply})")
    if not targets:
        ops_runs.record_ops_run(sb, "auto_discover_overseas", {"checked": 0, "produced": 0},
                                status="success", started_at=started, finished_at=_now_iso())
        print("[auto_discover_overseas] 无缺失目标，结束。")
        return

    candidates = build_candidates(targets)
    passed = confirm_candidates(candidates)

    # Workday 兜底：模板探不到的公司（金融/医药/零售大厂多在 Workday）走租户发现，再过同一道探活门。
    covered = {c["company"] for c in passed}
    wd_candidates = build_workday_candidates(targets, covered)
    passed += confirm_candidates(wd_candidates)

    to_insert = ad.plan_inserts(passed, existing_urls, INSERT_CAP)
    print(f"[auto_discover_overseas] 探 {len(targets)} 家 / ATS 候选 {len(candidates)} / "
          f"workday 发现 {len(wd_candidates)} / 验证通过 {len(passed)} / 可入库(去重后) {len(to_insert)}")
    added = 0
    for row in to_insert:
        tag = "+ insert" if apply else "· dry-run"
        print(f"  {tag} [{row['adapter']}] {row['company']} ({row['_valid']}岗) {row['url']}")
        if apply:
            try:
                ad.insert_source(sb, row)
                added += 1
            except Exception as e:
                print(f"    insert 失败(跳过): {type(e).__name__}: {e}")
    ops_runs.record_ops_run(
        sb, "auto_discover_overseas",
        {"checked": len(targets), "produced": added, "companies_enriched": added,
         "candidates": len(to_insert)},
        status=ops_runs.status_from_counts(len(to_insert), len(to_insert) - added),
        started_at=started, finished_at=_now_iso())
    print(f"[auto_discover_overseas] 完成: 入库 {added} 源 (apply={apply})")


if __name__ == "__main__":
    main()
