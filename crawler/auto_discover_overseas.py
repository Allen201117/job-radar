"""海外必投公司的每日 ATS 自动扩源（公开 JSON 探活，默认 dry-run）。"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import auto_discover as ad
import db
import ops_runs
import probe


TARGETS_JSON = Path(__file__).resolve().parent / "targets_overseas_must_apply.json"
TARGET_CAP = int(os.environ.get("AUTO_DISCOVER_OVERSEAS_TARGET_CAP", "80"))
INSERT_CAP = int(os.environ.get("AUTO_DISCOVER_OVERSEAS_INSERT_CAP", "40"))
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
    curated = load_targets()
    seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
    targets = ad.plan_targets(curated, user_wanted, existing_companies, TARGET_CAP, seed=seed)
    print(f"[auto_discover_overseas] curated={len(curated)} user_wanted={len(user_wanted)} "
          f"existing={len(existing_companies)} → 本轮 probe {len(targets)} 家海外缺失公司 (apply={apply})")
    if not targets:
        ops_runs.record_ops_run(sb, "auto_discover_overseas", {"checked": 0, "produced": 0},
                                status="success", started_at=started, finished_at=_now_iso())
        print("[auto_discover_overseas] 无缺失目标，结束。")
        return

    candidates = build_candidates(targets)
    passed = confirm_candidates(candidates)
    to_insert = ad.plan_inserts(passed, existing_urls, INSERT_CAP)
    print(f"[auto_discover_overseas] 探 {len(targets)} 家 / ATS 候选 {len(candidates)} / "
          f"验证通过 {len(passed)} / 可入库(去重后) {len(to_insert)}")
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
