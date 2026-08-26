"""必投清单缺口漏斗 P2：unknown_spa 浏览器道。"""
import argparse
import os
import re
from collections import Counter
from datetime import datetime, timezone

import db
import entry_finder
import gap_census
import gap_funnel
import jobs_db
import must_apply
import ops_runs
import probe


_TRUE = {"1", "true", "yes", "on"}
_TERMINAL_STATES = {
    "healthy",
    "manual_review",
    # no_stable_jd 不在此列：它是我们没拿到逐岗链接（自身能力问题，会随 adapter 改进
    # 而变化），靠 next_retry_at 的长退避重试，不能钉成永不重试。见 gap_funnel._MANUAL_PLATFORMS。
    "anti_bot",
    "login_wall",
    "governance_candidate",
}


def validate_jd_url_browser(url, title, company=None, *, timeout=15):
    """浏览器渲染后的逐岗页仍须 HTTP 200，且含岗位标题和公司身份信号。"""
    _verdict, _score, reason = entry_finder.classify_candidate_url(url, company)
    if reason in {
        "third_party_job_platform",
        "content_site",
        "campus_repost",
        "news_or_encyclopedia_path",
    }:
        return False
    from playwright.sync_api import sync_playwright

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            page = browser.new_context(locale="zh-CN").new_page()
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=max(1, int(timeout)) * 1000,
            )
            if response is None or response.status != 200:
                return False
            try:
                page.wait_for_load_state(
                    "networkidle", timeout=min(max(1, int(timeout)), 8) * 1000
                )
            except Exception:
                pass
            actual = "".join(page.content().split()).casefold()
            expected = "".join(str(title or "").split()).casefold()
            if not expected or expected not in actual:
                return False
            company_tokens = [
                token.casefold()
                for token in re.findall(
                    r"[A-Za-z0-9\u4e00-\u9fff]+", str(company or "")
                )
                if len(token) >= 2
            ]
            return not company_tokens or any(token in actual for token in company_tokens)
        finally:
            browser.close()


def _env_int(name, default):
    try:
        return max(0, int(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def plan_browser_queue(rows, *, cap=5, now=None):
    """纯函数：只接 unknown_spa；人工终止态永不重试，薄岗按原 retry 时间重试。"""
    now = now or datetime.now(timezone.utc)
    candidates = []
    for row in rows or []:
        if row.get("detected_platform") != "unknown_spa":
            continue
        if not row.get("official_entry_url") or row.get("state") in _TERMINAL_STATES:
            continue
        retry_at = gap_census._parse_datetime(row.get("next_retry_at"))
        if row.get("state") != "wrong_platform" and retry_at is not None and retry_at > now:
            continue
        candidates.append(row)
    return sorted(
        candidates,
        key=lambda row: str(row.get("company") or "").casefold(),
    )[:max(0, int(cap or 0))]



# P1 认出平台但因「httpx 道不安全」转交 P2 时，会把 platform/adapter 置空（P2 队列靠
# unknown_spa 筛选），真实平台留在 evidence.fingerprint.real_* 里。P2 必须把它取回来：
# 万泰生物是标准 moka 租户，company_spa 通用盲抓 0 个岗，moka adapter 抓 15 个带完整 jd_url 的岗。
_BROWSER_ADAPTER_WHITELIST = {"moka", "beisen", "feishu", "company_spa"}


def resolve_browser_adapter(row, entry_url):
    """纯函数：优先用 P1 认出的真实 adapter，认不出才回落 company_spa 通用盲抓。"""
    fingerprint = ((row or {}).get("evidence") or {}).get("fingerprint") or {}
    adapter = str(fingerprint.get("real_adapter") or "").strip()
    if adapter not in _BROWSER_ADAPTER_WHITELIST or adapter == "company_spa":
        return "company_spa", entry_url
    # adapter 真正消费的列表 URL 可能与展示入口不同（P1 已解析好）。
    real_source_url = str(fingerprint.get("real_source_url") or "").strip()
    return adapter, (real_source_url or entry_url)


def process_browser_company(
    row,
    *,
    supabase,
    jobs_conn,
    apply,
    now=None,
    prober=probe.probe_one,
    acceptance_gate=gap_funnel.run_acceptance_gate,
    jd_validator=validate_jd_url_browser,
):
    """拦截探活后调用 P1/P2 共用的真抓验收门。"""
    now = now or datetime.now(timezone.utc)
    source_url = row.get("official_entry_url")
    adapter, source_url = resolve_browser_adapter(row, source_url)
    candidate = {
        "company": row["company"],
        "adapter": adapter,
        "url": source_url,
        "industry": (row.get("industries") or [None])[0],
    }
    try:
        probe_result = (
            prober(candidate)
            if source_url
            else {"ok": False, "valid": 0, "reason": "缺少官方招聘入口"}
        )
    except Exception as exc:
        probe_result = {
            "ok": False,
            "valid": 0,
            "reason": "%s: %s" % (type(exc).__name__, str(exc)[:500]),
        }
    if (
        not source_url
        or not probe_result.get("ok")
        or int(probe_result.get("valid") or 0) <= 0
    ):
        return {
            "state": "no_stable_jd",
            "official_entry_url": source_url,
            "detected_platform": "unknown_spa",
            "next_retry_at": gap_funnel._after(
                now, gap_funnel._NO_STABLE_JD_RETRY_DAYS
            ),
            "fail_reason": probe_result.get("reason") or "浏览器拦截未拿到真实逐岗 URL",
            "evidence": {
                "probe": probe_result,
                "manual_review": True,
            },
        }

    result = acceptance_gate(
        row,
        adapter=adapter,
        source_url=source_url,
        supabase=supabase,
        jobs_conn=jobs_conn,
        apply=apply,
        now=now,
        crawl_method="playwright",
        enable_thin=False,
        validate_jd=jd_validator,
    )
    result.update({
        "official_entry_url": source_url,
        "detected_platform": "unknown_spa",
        "evidence": {
            **result.get("evidence", {}),
            "probe": probe_result,
        },
    })
    if not apply:
        result.update({
            "state": "platform_known",
            "fail_reason": None,
            "evidence": {
                **result["evidence"],
                "planned_action": "%s 真抓+香港库健康岗回读验收" % adapter,
            },
        })
    return result


def run_round(*, scope="domestic", limit=None, company=None, apply=False,
              supabase=None, jobs_conn=None, now=None):
    now = now or datetime.now(timezone.utc)
    started = now
    supabase = supabase or db.get_supabase()
    jobs_conn = jobs_conn or jobs_db.get_conn()
    cap = limit if limit is not None else _env_int("GAP_FUNNEL_BROWSER_CAP", 5)
    census_result = gap_census.census(
        supabase,
        jobs_conn,
        scope=scope,
        cap=0,
        company=company,
        apply=False,
        now=now,
    )
    queue = plan_browser_queue(census_result["rows"], cap=cap, now=now)
    outcomes = []
    for row in queue:
        scoped = {**row, "scope": scope}
        try:
            result = process_browser_company(
                scoped,
                supabase=supabase,
                jobs_conn=jobs_conn,
                apply=apply,
                now=now,
            )
            payload = gap_funnel._attempt_payload(scoped, result, now)
        except Exception as exc:
            payload = gap_funnel._attempt_payload(scoped, {
                "state": scoped.get("state") or "wrong_platform",
                "next_retry_at": gap_funnel._after(now, 1),
                "fail_reason": "%s: %s" % (type(exc).__name__, str(exc)[:500]),
                "evidence": {"exception_type": type(exc).__name__},
            }, now)
        outcomes.append(payload)
        if apply:
            try:
                gap_funnel._write_attempt(supabase, payload)
            except Exception as exc:
                print(
                    "[gap_funnel_browser] %s 台账写入失败: %s: %s"
                    % (row["company"], type(exc).__name__, str(exc)[:160])
                )

    counts = Counter(row["state"] for row in outcomes)
    failed = sum(
        count for state, count in counts.items()
        if state not in ("healthy", "platform_known")
    )
    metrics = {
        "checked": len(outcomes),
        "processed": len(outcomes),
        "healthy": counts.get("healthy", 0),
        "thin_only": counts.get("thin_only", 0),
        "sources_added": sum(
            1
            for row in outcomes
            if row.get("state") == "healthy"
            and row.get("source_id")
            and row.get("evidence", {}).get("source_inserted_new") is True
        ),
        "states": dict(counts),
        "dry_run": not apply,
        "list_version": must_apply.version(),
    }
    if apply:
        ops_runs.record_ops_run(
            supabase,
            "gap_funnel_browser",
            metrics,
            status=ops_runs.status_from_counts(len(outcomes), failed),
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        )
    failures = ",".join(
        "%s=%s" % item
        for item in sorted(counts.items())
        if item[0] not in ("healthy", "platform_known")
    ) or "无"
    print(
        "[gap_funnel_browser] 处理=%d 新增healthy=%d 失败态=%s apply=%s"
        % (len(outcomes), counts.get("healthy", 0), failures, apply)
    )
    return {"outcomes": outcomes, "metrics": metrics, "queue": queue}


def main(argv=None):
    parser = argparse.ArgumentParser(description="必投清单缺口漏斗 P2（浏览器道）")
    parser.add_argument("--scope", choices=["domestic", "overseas"], default="domestic")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--company", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    apply = os.environ.get("GAP_FUNNEL_APPLY", "").strip().lower() in _TRUE
    if args.dry_run:
        apply = False
    run_round(
        scope=args.scope,
        limit=max(0, args.limit) if args.limit is not None else None,
        company=args.company,
        apply=apply,
    )


if __name__ == "__main__":
    main()
