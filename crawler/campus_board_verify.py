"""校招板块候选源的验收门（层2）—— 真抓一轮，过三关才 enable。

层1（campus_board_probe_run.py）只证明「这个 URL 像个校招板块」。真正决定能否入库的是这里：

  关1 真抓得到 —— 用该源自己的 adapter 跑一轮，落进香港库
  关2 **非重复** —— 与同租户既有源比**岗位身份**，重叠 ≥80% 判重复
  关3 健康岗 ≥1 —— 回读香港库：该源名下有 active 且 jd_url/title 齐全的岗

任何一关不过：**删源 + 删本次落下的脏岗**，写台账退避。复用 gap_funnel 已验证的工艺。

## 关2 为什么是这条流水线里最要紧的一关

飞书实测：`/campus` 与 `/index` 的 jd_url 完全不同（portal 前缀不同），按 URL 比交集为 0，
看着像两个板块；按岗位 ID 比才发现是同一批 600 个岗。若放进来，就是迁移 186 那场灾难重演：
同一份岗被两个源抢，某条 jd_url 归先插入的源所有，另一个源的历史行就此搁浅、last_seen_at
再不更新 → 该租户的缺席探活占比越过 50% 安全闸 → 整源跳过 → **死岗永远下不了架**。
所以宁可漏建一个源，也绝不放一个重复源进来。

## 为什么在 CI 跑
moka 是浏览器 adapter，单源 2-5 分钟。40 个候选 = 1.5~3.5 小时，只能放 CI 的时间预算里。
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

import campus_board_probe as P
import db
import jobs_db
from campus_board_probe_run import RETRY_DAYS, upsert_attempt
from run import run_crawl


def _log(msg):
    print(f"[campus-verify] {msg}", flush=True)


def sibling_source(candidate, all_sources):
    """找同租户的既有（社招）源——非重复门的比较对象。找不到返回 None。"""
    ad, url = candidate.get("adapter_name"), candidate.get("source_url") or ""
    if ad == "moka":
        tenant = P.moka_tenant(url)
        for s in all_sources:
            if (s.get("adapter_name") == "moka" and s["id"] != candidate["id"]
                    and P.moka_tenant(s.get("source_url") or "") == tenant):
                return s
    elif ad == "hotjob":
        tenant = P.hotjob_tenant(url)
        for s in all_sources:
            if (s.get("adapter_name") == "hotjob" and s["id"] != candidate["id"]
                    and P.hotjob_tenant(s.get("source_url") or "") == tenant):
                return s
    return None


def source_jobs(conn, source_id):
    """香港库：该源名下的 active 岗（判健康 + 取身份两用）。"""
    return jobs_db.fetch_all(conn, """
        select jd_url, title from jobs
        where source_id = %s and status = 'active' limit 2000
    """, (str(source_id),))


def healthy_count(rows):
    """健康岗 = active + jd_url 与 title 都齐（质量门口径：拿不到稳定详情链接的不算数）。"""
    return sum(1 for r in rows
               if (r.get("jd_url") or "").strip() and (r.get("title") or "").strip())


def purge_source(supabase, conn, source_id):
    """验收不过：删本次落下的脏岗 + 删源行。顺序不能反——先删岗再删源，避免外键孤儿。"""
    try:
        jobs_db.execute(conn, "delete from jobs where source_id = %s", (str(source_id),))
    except Exception as e:
        _log(f"⚠️ 清理脏岗失败 source_id={source_id}: {type(e).__name__}: {e}")
    try:
        supabase.table("sources").delete().eq("id", source_id).execute()
    except Exception as e:
        _log(f"⚠️ 删源失败 source_id={source_id}: {type(e).__name__}: {e}")


def verify_one(supabase, conn, candidate, all_sources):
    """单个候选走完三关。返回最终 state。"""
    company = candidate.get("company")
    label = f"{company} / {candidate.get('adapter_name')}"

    # 关1：真抓一轮（override 单源，走与主链路完全相同的抓取/质量门/写库路径）
    run_crawl(sources_override=[{**candidate, "enabled": True}], tier="all")

    rows = source_jobs(conn, candidate["id"])
    if not rows:
        _log(f"  ✗ {label}：抓完回读 0 岗")
        purge_source(supabase, conn, candidate["id"])
        return "no_healthy_jobs"

    # 关2：非重复（比岗位身份，不比 URL——见模块 docstring）
    sib = sibling_source(candidate, all_sources)
    if sib:
        sib_rows = source_jobs(conn, sib["id"])
        if P.is_duplicate_board([r["jd_url"] for r in sib_rows], [r["jd_url"] for r in rows]):
            _log(f"  ✗ {label}：与既有源 {sib.get('source_url','')[:52]} 是同一批岗 → 判重复，丢弃")
            purge_source(supabase, conn, candidate["id"])
            return "duplicate_board"
    else:
        # 找不到同租户既有源就无从比对 → 保守丢弃（本流水线的候选**都是**从既有源推导来的，
        # 找不到兄弟说明数据不一致，不该蒙混过关）
        _log(f"  ✗ {label}：找不到同租户既有源，无法做非重复比对 → 保守丢弃")
        purge_source(supabase, conn, candidate["id"])
        return "duplicate_board"

    # 关3：健康岗 ≥1
    healthy = healthy_count(rows)
    if healthy < 1:
        _log(f"  ✗ {label}：{len(rows)} 岗但健康岗 0（缺 jd_url/title）")
        purge_source(supabase, conn, candidate["id"])
        return "no_healthy_jobs"

    supabase.table("sources").update({"enabled": True}).eq("id", candidate["id"]).execute()
    _log(f"  ✅ {label}：{healthy} 个健康校招岗 → 已启用")
    return "healthy"


def main():
    ap = argparse.ArgumentParser(description="校招板块候选源验收门")
    ap.add_argument("--limit", type=int, default=12,
                    help="本轮验收几个候选（moka 是浏览器源 2-5min/个，别开太大撞 CI 超时）")
    args = ap.parse_args()

    if not jobs_db.enabled():
        _log("❌ 未配置 JOBS_DATABASE_URL，无法回读香港库做验收 → 拒绝空转")
        return 1

    supabase = db.get_supabase()
    all_sources = db.fetch_all_rows(lambda: supabase.table("sources").select("*"))

    # ⚠️ 待验收名单只认台账 state='source_added'，**不能**靠「disabled 的 campus URL 源」去猜：
    # 库里本来就有被人工/迁移停用的校招源（如迁移 186 的 beisen 去重、华润电力那条 hotjob），
    # 猜的话会把它们重新 enable，等于悄悄推翻别人的决定。
    try:
        resp = (supabase.table("campus_board_attempts")
                .select("company, adapter_name")
                .eq("state", "source_added").execute())
        awaiting = {(r["company"], r["adapter_name"]) for r in (resp.data or [])}
    except Exception as e:
        _log(f"❌ 台账读取失败，无法确定待验收名单：{type(e).__name__}: {e}")
        return 1
    pending = [s for s in all_sources
               if not s.get("enabled")
               and (s.get("company"), s.get("adapter_name")) in awaiting][:args.limit]
    if not pending:
        _log("没有待验收的候选源。")
        return 0

    _log(f"待验收 {len(pending)} 个候选源")
    conn = jobs_db.get_conn()
    results = {}
    try:
        for cand in pending:
            state = verify_one(supabase, conn, cand, all_sources)
            results[state] = results.get(state, 0) + 1
            upsert_attempt(supabase, cand.get("company"), cand.get("adapter_name"),
                           cand.get("source_url"), state)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    _log(f"验收完成：{results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
