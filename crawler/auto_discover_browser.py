"""crawler/auto_discover_browser.py — 每日定向自动扩源（浏览器变体）：补 httpx 探不到的 beisen/moka 缺口。

httpx 变体（auto_discover.py）只能发现 feishu/hotjob；但传统制造/能源/安防/金融大厂多用
**beisen(zhiye.com) / moka(mokahr.com)** 这类 SPA 壳，列表/详情必须浏览器渲染，httpx 探不出岗位数——
这正是「自动扩充岗位库」剩下的大头缺口。本脚本接上这块：

  目标同 httpx 变体（精选清单 + 用户 target_companies 里**库里没有的**公司）
  → discover_domestic 的 beisen_probe/moka_probe（**httpx 廉价**，只做 tenant 标题核验防张冠李戴，拿不到岗位数）
  → to_beisen/moka_candidates 候选（{company,adapter,url,industry,segment}）
  → **逐家用真 BeisenAdapter/MokaAdapter（probe.probe_one，内含 Playwright 渲染）确认真产岗（质量门 valid>0）**
  → 只入库**确认产岗**的源（猜错的 tenant / 抽不出岗的新版异构租户自动丢弃）。

慢（浏览器逐家 ~1-3min）→ 两段封顶：先 httpx 廉价探一大批 tenant（TARGET_CAP），再只对前 CONFIRM_CAP 家
开浏览器确认。三道闸同 httpx 变体：AUTO_DISCOVER_APPLY 默认 dry-run / source_url 去重 / 每日上限。
确认串行（一进程一 Playwright，避免 sync_playwright 线程冲突）。

**Track A2（校招板块缺口重探）也接在这里、不接在 httpx 变体**：moka 校招板块岗位数确认同样要
Playwright（跟社招 tenant 发现一样），httpx 变体（auto_discover.py）的 PLATFORMS 不含 moka，探不了。
targeting（哪些必投公司缺校招板块、slug 怎么反推）是纯函数，住在 auto_discover.py（ad.plan_campus_gap_targets），
方便脱离浏览器单测；这里只负责把它接进 sweep→confirm→insert 这条已有的浏览器确认流水线，
独立预算（CAMPUS_GAP_CONFIRM_CAP），不与「全新公司发现」抢同一份 CONFIRM_CAP（否则容易被挤到 0）。
"""
import os
from datetime import datetime, timezone

import db
import must_apply
import ops_runs
import probe
import discover_domestic as dd
import auto_discover as ad

BROWSER_PLATFORMS = {"beisen", "moka"}
TARGET_CAP = int(os.environ.get("AUTO_DISCOVER_BROWSER_TARGET_CAP", "120"))   # httpx 廉价探多少家 tenant
CONFIRM_CAP = int(os.environ.get("AUTO_DISCOVER_BROWSER_CONFIRM_CAP", "15"))  # 浏览器确认封顶（慢~1-3min/家，CI 50min 预算内）
CONFIRM_TIMEOUT = int(os.environ.get("AUTO_DISCOVER_BROWSER_TIMEOUT", "45"))
# 校招板块缺口重探专用浏览器确认封顶（独立预算，见上方 Track A2 说明）。
CAMPUS_GAP_CONFIRM_CAP = int(os.environ.get("AUTO_DISCOVER_CAMPUS_GAP_CONFIRM_CAP", "8"))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def confirm_candidates(cands, cap, timeout, probe_fn=None):
    """逐家用真 adapter（probe.probe_one，内含 Playwright）确认真产岗。返回 valid>0 的（带 _valid/_china）。
    串行（浏览器重，且 sync_playwright 不可同进程多线程）。probe_fn 可注入便于测试。"""
    pf = probe_fn or (lambda c: probe.probe_one(c, timeout=timeout))
    confirmed = []
    for c in cands[:cap]:
        try:
            r = pf(c)
        except Exception as e:
            print(f"  ✗ {c.get('company')} {c.get('adapter')}: {type(e).__name__}: {str(e)[:60]}")
            continue
        valid = (r or {}).get("valid", 0) or 0
        print(f"  {'✓' if valid > 0 else '✗'} {c.get('company')} {c.get('adapter')} ({valid}岗) {c.get('url')}")
        if valid > 0:
            confirmed.append({**c, "_valid": valid, "_china": (r or {}).get("china", valid)})
    return confirmed


def main():
    apply = os.environ.get("AUTO_DISCOVER_APPLY", "").lower() in ("1", "true", "yes")
    started = _now_iso()
    sb = db.get_supabase()
    user_wanted = ad.load_user_wanted_companies(sb)
    existing_companies, existing_urls = ad.existing_source_keys(sb)
    curated = ad.load_targets(existing_companies)
    seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
    targets = ad.plan_targets(curated, user_wanted, existing_companies, TARGET_CAP, seed=seed)
    print(f"[auto_discover_browser] curated={len(curated)} user_wanted={len(user_wanted)} "
          f"existing={len(existing_companies)} → httpx 探 {len(targets)} 家 tenant (apply={apply})")

    # Track A2：已有社招源但缺校招板块的必投公司 —— 绕过上面「整家去重」，moka-only 专补校招板块
    # （beisen/hotjob/wt 校招已在 A0 摸清覆盖，不需重探；targeting 纯函数见 auto_discover.py）。
    try:
        must_apply_by_industry = must_apply.by_industry()
    except Exception as e:
        print(f"[auto_discover_browser] 必投清单读取失败，跳过校招缺口补探: {type(e).__name__}: {e}")
        must_apply_by_industry = {}
    source_rows = ad.load_campus_gap_source_rows(sb)
    campus_gap_targets = ad.plan_campus_gap_targets(must_apply_by_industry, source_rows,
                                                     ad.CAMPUS_GAP_CAP, seed=seed)
    print(f"[auto_discover_browser] 校招板块缺口重探目标 {len(campus_gap_targets)} 家（moka-only）")

    if not targets and not campus_gap_targets:
        ops_runs.record_ops_run(sb, "auto_discover_browser", {"checked": 0, "produced": 0},
                                status="success", started_at=started, finished_at=_now_iso())
        print("[auto_discover_browser] 无缺失目标，结束。")
        return

    hits = dd.sweep(targets, BROWSER_PLATFORMS) if targets else []
    cands = dd.to_beisen_candidates(hits) + dd.to_moka_candidates(hits)
    # 先去重 vs 已有 source_url（别浪费浏览器时间确认已在库的），不截断——截断交给 CONFIRM_CAP。
    cands = ad.plan_inserts(cands, existing_urls, cap=10 ** 9)
    print(f"[auto_discover_browser] tenant 命中候选 {len(cands)} → 浏览器确认前 {CONFIRM_CAP} 家")

    campus_hits = dd.sweep(campus_gap_targets, {"moka"}) if campus_gap_targets else []
    campus_cands = ad.plan_inserts(dd.to_moka_candidates(campus_hits), existing_urls, cap=10 ** 9)
    print(f"[auto_discover_browser] 校招缺口命中候选 {len(campus_cands)} → 浏览器确认前 {CAMPUS_GAP_CONFIRM_CAP} 家")

    confirmed = confirm_candidates(cands, CONFIRM_CAP, CONFIRM_TIMEOUT)
    confirmed += confirm_candidates(campus_cands, CAMPUS_GAP_CONFIRM_CAP, CONFIRM_TIMEOUT)
    added = 0
    for row in confirmed:
        tag = "+ insert" if apply else "· dry-run"
        print(f"  {tag} [{row['adapter']}] {row['company']} ({row['_valid']}岗) {row['url']}")
        if apply:
            try:
                ad.insert_source(sb, row)
                added += 1
            except Exception as e:
                print(f"    insert 失败(跳过): {type(e).__name__}: {e}")

    ops_runs.record_ops_run(
        sb, "auto_discover_browser",
        {"checked": len(targets) + len(campus_gap_targets), "produced": added, "companies_enriched": added,
         "candidates": len(confirmed)},
        status=ops_runs.status_from_counts(len(confirmed), len(confirmed) - added),
        started_at=started, finished_at=_now_iso())
    print(f"[auto_discover_browser] 完成: 确认产岗 {len(confirmed)} / 入库 {added} 源 (apply={apply})")


if __name__ == "__main__":
    main()
