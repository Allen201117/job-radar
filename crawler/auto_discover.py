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
from datetime import datetime, timezone
from pathlib import Path

import db
import ops_runs
import discover_domestic as dd

DAILY_TARGET_CAP = int(os.environ.get("AUTO_DISCOVER_TARGET_CAP", "30"))   # 每日最多 probe 多少家缺失公司
DAILY_INSERT_CAP = int(os.environ.get("AUTO_DISCOVER_INSERT_CAP", "20"))   # 每日最多入库多少源
PLATFORMS = {"feishu", "hotjob"}   # httpx-safe（hotjob 内含 wt/wecruit）；beisen/moka 需浏览器，留后置
_CURATED_FILES = ("targets_private500_full.json", "targets_private500.json", "targets_soe500.json")


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
        try:
            for t in (json.loads(p.read_text(encoding="utf-8")) or []):
                c = (t.get("company") or "").strip()
                if c and c not in seen:
                    seen.add(c)
                    out.append(t)
        except Exception:
            pass
    return out


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
    """库里已有的公司名 + source_url（含 disabled），用于去重。"""
    rows = sb.table("sources").select("company,source_url").execute().data or []
    companies = {(r.get("company") or "").strip() for r in rows}
    urls = {(r.get("source_url") or "").strip() for r in rows}
    return companies, urls


def plan_targets(curated, user_wanted, existing_companies, cap, seed=0):
    """纯函数：本轮要 probe 的目标 = 库里没有的精选目标公司；用户点名想要的**优先**，其余按 seed 随机轮转
    （避免每天死磕同一批失败目标，让覆盖随天数滚动），封顶 cap。"""
    missing = [t for t in curated if (t.get("company") or "").strip()
               and (t.get("company") or "").strip() not in existing_companies]
    wanted_first = [t for t in missing if (t.get("company") or "").strip() in user_wanted]
    rest = [t for t in missing if (t.get("company") or "").strip() not in user_wanted]
    random.Random(seed).shuffle(rest)
    return (wanted_first + rest)[:cap]


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


def insert_source(sb, row):
    """入库一条已验证源（service-role，与 app/api/sources 同字段口径），并给新公司排队职业洞察。"""
    sb.table("sources").insert({
        "company": row["company"], "source_url": row["url"], "source_type": "official",
        "adapter_name": row["adapter"], "crawl_method": "http",
        "segment": row.get("segment") or "private", "industry": row.get("industry"),
        "notes": f"auto_discover: live探活 {row.get('_valid', '?')} 岗", "enabled": True,
    }).execute()
    try:
        sb.table("company_profiles").upsert(
            {"company": row["company"], "insight_checked_at": None}, on_conflict="company").execute()
    except Exception:
        pass


def main():
    apply = os.environ.get("AUTO_DISCOVER_APPLY", "").lower() in ("1", "true", "yes")
    started = _now_iso()
    sb = db.get_supabase()
    curated = load_curated_targets()
    user_wanted = load_user_wanted_companies(sb)
    existing_companies, existing_urls = existing_source_keys(sb)
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
