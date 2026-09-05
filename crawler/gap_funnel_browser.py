"""必投清单缺口漏斗 P2：unknown_spa 浏览器道。"""
import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

import db
import entry_finder
import gap_census
import gap_funnel
import jobs_db
import must_apply
import ops_runs
import platform_fingerprint
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


def plan_browser_queue(rows, *, cap=5, now=None, ignore_backoff=False):
    """纯函数：只接 unknown_spa；人工终止态永不重试，薄岗按原 retry 时间重试。

    ignore_backoff=True 对应人工点名单家公司（--company），语义同 gap_census.plan_queue。
    """
    now = now or datetime.now(timezone.utc)
    candidates = []
    for row in rows or []:
        if row.get("detected_platform") != "unknown_spa":
            continue
        if not row.get("official_entry_url") or row.get("state") in _TERMINAL_STATES:
            continue
        retry_at = gap_census._parse_datetime(row.get("next_retry_at"))
        if (
            not ignore_backoff
            and row.get("state") != "wrong_platform"
            and retry_at is not None
            and retry_at > now
        ):
            continue
        candidates.append(row)
    return sorted(
        candidates,
        key=lambda row: str(row.get("company") or "").casefold(),
    )[:max(0, int(cap or 0))]


def load_handoff_rows(path):
    """读 P1 本轮 artifact；坏文件只告警并回退台账队列。"""
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload.get("companies") if isinstance(payload, dict) else payload
        return [row for row in (rows or []) if isinstance(row, dict)]
    except (OSError, ValueError, TypeError) as exc:
        print("[gap_funnel_browser] 交接文件读取失败，回退台账队列: %s: %s"
              % (type(exc).__name__, exc))
        return []


def merge_browser_queues(handoff_rows, ledger_rows, *, cap, now):
    """P1 当轮 handoff 优先，随后补入台账里本就到期的 unknown_spa 公司。"""
    handoff = plan_browser_queue(
        handoff_rows, cap=len(handoff_rows or []), now=now, ignore_backoff=True)
    ledger = plan_browser_queue(ledger_rows, cap=len(ledger_rows or []), now=now)
    out, seen = [], set()
    for row in handoff + ledger:
        key = str(row.get("company") or "").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= max(0, int(cap or 0)):
            break
    return out



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



# 列表接口天生不返回正文、但逐岗渲染补得到的平台。库里 2.6 万张 moka 卡就是这么来的
# （每晚 scripts/backfill_moka_summaries.py 补），对它们要求「当场有健康岗」= 永远进不来。
_THIN_RESCUE_ADAPTERS = {"moka"}
_THIN_RESCUE_SAMPLE = 3
_THIN_RESCUE_MIN_OK = 2
_THIN_RESCUE_MIN_CHARS = 60


def _scrape_job_summary(page, url, *, timeout=30):
    """逐岗渲染取正文，复用 backfill 脚本里已调好的选择器。"""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "_moka_backfill",
        Path(__file__).resolve().parent.parent / "scripts" / "backfill_moka_summaries.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
    page.wait_for_timeout(2500)
    return module._scrape_jd(page)


def make_thin_rescue(adapter, *, scraper=None):
    """薄卡救济：抽样证明这个源的正文确实取得到，取得到才放行。

    质量红线不变——仍然要求正文可获取，变的只是验证方式：
    「当场每个岗都有正文」→「抽样证明正文补得出来」，后者才符合 moka 的实际工作方式。
    非白名单平台返回 None（不救济，行为与改动前完全一致）。
    """
    if adapter not in _THIN_RESCUE_ADAPTERS:
        return None

    def rescue(samples):
        urls = [
            str((sample or {}).get("jd_url") or "").strip()
            for sample in (samples or [])
        ]
        urls = [url for url in urls if url][:_THIN_RESCUE_SAMPLE]
        if len(urls) < _THIN_RESCUE_MIN_OK:
            return False
        if scraper is not None:
            texts = [scraper(url) for url in urls]
        else:
            from playwright.sync_api import sync_playwright

            texts = []
            with sync_playwright() as runtime:
                browser = runtime.chromium.launch(headless=True)
                try:
                    page = browser.new_context(locale="zh-CN").new_page()
                    for url in urls:
                        try:
                            texts.append(_scrape_job_summary(page, url))
                        except Exception:
                            texts.append("")
                finally:
                    browser.close()
        ok = sum(
            1 for text in texts
            if len(str(text or "").strip()) >= _THIN_RESCUE_MIN_CHARS
        )
        return ok >= _THIN_RESCUE_MIN_OK

    return rescue


# 「站错了页」时最多跟几跳自家招聘子域。跟一跳只是一次 httpx 指纹（便宜），
# 但每跳都可能触发一次浏览器复探（贵），所以设硬上限。
_ENTRY_HOP_LIMIT = 2


def _candidate_trusted(row, entry_url, candidate, identity_text=""):
    """认出的平台能不能用。返回 (放行?, 理由)。

    放行两条路，缺一不可：
      ① **这一页自己核出了公司名**（拿渲染后的文本核，不是拿 httpx 的壳核）；
      ② **P1 已核过入口页身份，且候选与入口页同主域**。

    ⚠️ ② 里「同主域」那半不能省：入口页身份只为**这个域名**背书，不能替页面上任意一条
    第三方 ATS 链接背书。两侧都有实证——宝洁 careers.pg.com.cn → app.mokahr.com 是跨域，
    只能靠 ①；埃斯顿 estun1.zhiye.com 渲染后核不出「埃斯顿」三个字，只能靠 ②。
    """
    company = str((row or {}).get("company") or "").strip()
    source_url = str((candidate or {}).get("source_url") or "")
    if candidate.get("identity_ok") is True:
        return True, "candidate_identity_ok"
    if company and identity_text:
        ok, reason = platform_fingerprint.verify_page_identity(
            company, source_url, identity_text
        )
        if ok:
            return True, "rendered_%s" % reason
    entry_fingerprint = ((row or {}).get("evidence") or {}).get("fingerprint") or {}
    if entry_fingerprint.get("identity_ok") is True:
        entry_root = platform_fingerprint._registrable(
            urlparse(str(entry_url or "")).hostname
        )
        if entry_root and entry_root == platform_fingerprint._registrable(
            urlparse(source_url).hostname
        ):
            return True, "entry_verified_same_domain"
    return False, "identity_unverified"


def _probe_digest(probe_result):
    """探活结果的台账摘要。刻意不整份塞进 evidence（含 identity_text 之类只在内存流转的素材）。"""
    return {
        key: (probe_result or {}).get(key)
        for key in ("ok", "valid", "reason", "block_kind")
        if (probe_result or {}).get(key) is not None
    }


def _route_recognized(row, candidate, *, now, probe_result, hop_trail, entry_url):
    """认出真平台之后交给谁跑。

    · **httpx 平台**（workday / hotjob / greenhouse…）→ 交回 P1，那边有完整路由 + 验收门。
    · **浏览器平台**（moka / beisen / feishu）→ **P2 自己接，不交回去**。两条理由都是实测的：
      P1 的候选门要求 identity_ok is True，而 httpx 对这些平台只拿得到壳核不出公司名
      （宝洁 app.mokahr.com/…/pg/91934 实测 page_company_not_found，42 个岗会被拒掉）；
      且 `_strict_httpx_probe_safe` 对它们恒 False，交回去也只会被再踢回 P2，白跑一轮。
      顺带把认出的平台写进 evidence.fingerprint.real_*，下一轮 resolve_browser_adapter
      直接短路，不用再渲染一次。
    """
    adapter = candidate["adapter"]
    source_url = candidate["source_url"]
    if adapter not in _BROWSER_ADAPTER_WHITELIST:
        return {"handoff": {
            "state": "platform_known",
            "official_entry_url": source_url,
            "detected_platform": candidate.get("platform"),
            "next_retry_at": gap_funnel._iso(now),
            "fail_reason": (
                "no_job_data_on_entry：入口页没有岗位数据，已认出 %s，交回 P1"
                % candidate.get("platform")
            ),
            "evidence": {
                "probe": _probe_digest(probe_result),
                "entry_hops": hop_trail,
                "entry_hop_from": entry_url,
            },
        }}
    entry_fingerprint = ((row or {}).get("evidence") or {}).get("fingerprint") or {}
    return {
        "adapter": adapter,
        "source_url": source_url,
        # 与 P1 交接用的既有字段，别换名字：resolve_browser_adapter 只认 real_adapter/real_source_url。
        "discovered": {**entry_fingerprint,
                       "real_adapter": adapter,
                       "real_source_url": source_url,
                       "real_platform": candidate.get("platform"),
                       "discovered_by": "browser_rendered_entry"},
    }


def _hop_candidates(probe_result, current_url, limit=_ENTRY_HOP_LIMIT):
    """渲染后页面里抽到的招聘子域候选，去掉当前入口本身，保序去重。"""
    seen = {str(current_url or "").rstrip("/")}
    out = []
    for hop in (probe_result or {}).get("hops") or []:
        key = str(hop or "").rstrip("/")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(hop)
        if len(out) >= limit:
            break
    return out


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
    fingerprinter=platform_fingerprint.fingerprint,
):
    """拦截探活后调用 P1/P2 共用的真抓验收门。"""
    now = now or datetime.now(timezone.utc)
    source_url = row.get("official_entry_url")
    adapter, source_url = resolve_browser_adapter(row, source_url)

    def _probe(url):
        try:
            return prober({
                "company": row["company"],
                "adapter": adapter,
                "url": url,
                "industry": (row.get("industries") or [None])[0],
            })
        except Exception as exc:
            return {
                "ok": False,
                "valid": 0,
                "reason": "%s: %s" % (type(exc).__name__, str(exc)[:500]),
            }

    probe_result = (
        _probe(source_url)
        if source_url
        else {"ok": False, "valid": 0, "reason": "缺少官方招聘入口"}
    )

    def _probe_ok(result):
        return bool(result.get("ok")) and int(result.get("valid") or 0) > 0

    hop_trail = []
    discovered = None
    # 探活没拿到可用岗 → 先别急着记失败，看看是不是「站错了页 / 用错了 adapter」。
    # 候选是从**渲染后**的页面抽的：httpx 道（platform_fingerprint.fingerprint）只能救
    # 「服务端渲染、原始 HTML 里就有链接」那半，空 SPA 壳那半只有渲染后才有链接。
    # ⚠️ 触发条件**不能只看 block_kind**：广汽/埃斯顿/华虹三家 company_spa 都是 fetch 成功
    # （JSON 拦到了）、parse 出 0 个岗，压根不抛异常，block_kind 是 None。
    # 真被拒（anti_bot）和页面没打开（entry_unreachable）才不折腾，那两种换 adapter 也没用。
    if (
        source_url
        and not _probe_ok(probe_result)
        and probe_result.get("block_kind") not in ("anti_bot", "entry_unreachable")
    ):
        entry_url = source_url
        # ① 渲染后的页面里直接认出第三方 ATS —— 零额外请求，且覆盖 find_careers_subdomain_hops
        #    够不着的跨主域那半。2026-09-05 对整个 P2 队列 54 家逐个渲染实测：
        #    渲染后认 ATS 命中 11/54，其中 4 家当场抓到真岗共 340 个
        #    （广汽 beisen 225 / 埃斯顿 beisen 63 / 宝洁 moka 42 / 华虹 moka 10）；
        #    而子域候选只有 3/54 抽得出、且全都指纹认不出。两条都留着，但主力是这条。
        ats_hint = dict(probe_result.get("ats_hint") or {})
        # 身份素材只在内存里用，**立刻摘掉**：probe_result 整个会被写进台账 evidence。
        identity_text = ats_hint.pop("identity_text", "")
        if probe_result.get("ats_hint") is not None:
            probe_result["ats_hint"] = ats_hint
        if ats_hint.get("adapter") and ats_hint.get("source_url"):
            trusted, identity_reason = _candidate_trusted(
                row, entry_url, ats_hint, identity_text
            )
            hop_trail.append({
                **ats_hint, "via": "rendered_html_ats",
                "trusted": trusted, "identity": identity_reason,
            })
            if trusted:
                routed = _route_recognized(
                    row, ats_hint, now=now, probe_result=probe_result,
                    hop_trail=hop_trail, entry_url=entry_url,
                )
                if routed.get("handoff"):
                    return routed["handoff"]
                adapter, source_url = routed["adapter"], routed["source_url"]
                discovered = routed["discovered"]
                probe_result = _probe(source_url)
                hop_trail[-1]["probe"] = _probe_digest(probe_result)
        # ② 同主域的自家招聘子域候选，跟过去看它把我们带到哪儿。
        if not _probe_ok(probe_result):
            for hop in _hop_candidates(probe_result, entry_url):
                try:
                    hop_fingerprint = fingerprinter(hop, company=row["company"])
                except Exception as exc:
                    hop_trail.append({
                        "url": hop,
                        "error": "%s: %s" % (type(exc).__name__, str(exc)[:200]),
                    })
                    continue
                step = {
                    "url": hop,
                    "platform": hop_fingerprint.get("platform"),
                    "adapter": hop_fingerprint.get("adapter"),
                    "reason": hop_fingerprint.get("reason"),
                }
                hop_trail.append(step)
                if hop_fingerprint.get("adapter"):
                    candidate = {
                        "platform": hop_fingerprint.get("platform"),
                        "adapter": hop_fingerprint.get("adapter"),
                        "source_url": hop_fingerprint.get("source_url") or hop,
                        "identity_ok": hop_fingerprint.get("identity_ok"),
                    }
                    trusted, identity_reason = _candidate_trusted(row, entry_url, candidate)
                    step.update(trusted=trusted, identity=identity_reason)
                    if not trusted:
                        continue
                    routed = _route_recognized(
                        row, candidate, now=now, probe_result=probe_result,
                        hop_trail=hop_trail, entry_url=entry_url,
                    )
                    if routed.get("handoff"):
                        return routed["handoff"]
                    adapter, source_url = routed["adapter"], routed["source_url"]
                    discovered = routed["discovered"]
                    probe_result = _probe(source_url)
                    step["probe"] = _probe_digest(probe_result)
                    if _probe_ok(probe_result):
                        break
                    continue
                if hop_fingerprint.get("platform") in ("unknown", "unknown_spa"):
                    retried = _probe(hop)
                    step["probe"] = _probe_digest(retried)
                    if _probe_ok(retried):
                        source_url, probe_result = hop, retried
                        break

    if not source_url or not _probe_ok(probe_result):
        # fail_reason 必须说清是哪一种失败。以前不论真假一律带出 adapter 的
        # `anti_bot_blocked` 字样，21 家必投公司因此被当成「被反爬」排查（实为站错了页）。
        evidence = {"probe": probe_result, "manual_review": True}
        if hop_trail:
            evidence["entry_hops"] = hop_trail
        # 这轮认出来的平台即使没抓成也要落盘：下一轮直接用它，不必再渲染一次入口页。
        if discovered:
            evidence["fingerprint"] = discovered
        return {
            "state": "no_stable_jd",
            "official_entry_url": source_url,
            "detected_platform": "unknown_spa",
            "next_retry_at": gap_funnel._after_spread(
                now, gap_funnel._NO_STABLE_JD_RETRY_DAYS, row.get("company")
            ),
            "fail_reason": probe_result.get("reason") or "浏览器拦截未拿到真实逐岗 URL",
            "evidence": evidence,
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
        thin_rescue=make_thin_rescue(adapter),
        validate_jd=jd_validator,
    )
    result.update({
        "official_entry_url": source_url,
        "detected_platform": "unknown_spa",
        "evidence": {
            **result.get("evidence", {}),
            "probe": probe_result,
            **({"entry_hops": hop_trail} if hop_trail else {}),
            **({"fingerprint": discovered} if discovered else {}),
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
              supabase=None, jobs_conn=None, now=None, handoff_file=None):
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
    handoff_rows = load_handoff_rows(handoff_file)
    if company:
        queue = plan_browser_queue(
            census_result["rows"], cap=cap, now=now, ignore_backoff=True)
    else:
        queue = merge_browser_queues(
            handoff_rows, census_result["rows"], cap=cap, now=now)
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
    # thin_only 不是失败：薄卡救济过门后源**已 enable、岗位已入库**，
    # 正文由每晚 backfill 补。P1 一直用这个口径，P2 漏了 → 成功入库却报成失败态，
    # 运营看日志会误判「今天没出货」（2026-08-26 万泰生物实测撞上）。
    _NOT_FAILURE = ("healthy", "platform_known", "thin_only")
    failed = sum(
        count for state, count in counts.items()
        if state not in _NOT_FAILURE
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
        "handoff_loaded": len(handoff_rows),
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
        if item[0] not in _NOT_FAILURE
    ) or "无"
    print(
        "[gap_funnel_browser] 处理=%d 新增healthy=%d thin_only=%d 失败态=%s apply=%s"
        % (
            len(outcomes),
            counts.get("healthy", 0),
            counts.get("thin_only", 0),
            failures,
            apply,
        )
    )
    return {"outcomes": outcomes, "metrics": metrics, "queue": queue}


def main(argv=None):
    parser = argparse.ArgumentParser(description="必投清单缺口漏斗 P2（浏览器道）")
    parser.add_argument("--scope", choices=["domestic", "overseas"], default="domestic")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--company", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--handoff-file", default=None,
                        help="读取 P1 当轮 unknown_spa artifact，优先处理其中公司")
    args = parser.parse_args(argv)
    apply = os.environ.get("GAP_FUNNEL_APPLY", "").strip().lower() in _TRUE
    if args.dry_run:
        apply = False
    run_round(
        scope=args.scope,
        limit=max(0, args.limit) if args.limit is not None else None,
        company=args.company,
        apply=apply,
        handoff_file=args.handoff_file,
    )


if __name__ == "__main__":
    main()
