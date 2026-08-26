"""必投清单缺口漏斗 P1：httpx 入口发现 → 指纹 → 探活 → 真抓 → 回读验收。"""
import argparse
import os
import re
import zlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import httpx

import ats_tenant_seed
import db
import entry_finder
import gap_census
import jobs_db
import must_apply
import ops_runs
import platform_fingerprint
import probe
import run
import site_entry


_TRUE = {"1", "true", "yes", "on"}
# anti_bot / login_wall 是**对方的门槛**（反爬、要登录），只能转人工 → 永不重试。
# no_stable_jd 不一样：它是**我们没拿到逐岗链接**，属于自身抓取能力问题，
# 而抓取能力一直在改进（2026-08-26 就修掉一个：P2 对标准 ATS 租户误用通用盲抓，
# 万泰生物同一 URL 由 0 个岗变 15 个）。把它钉成永不重试 = 每次能力升级都救不回存量。
# 故给长退避，让系统改进后能自我修复。
_MANUAL_PLATFORMS = {"anti_bot", "login_wall"}
_NO_STABLE_JD_RETRY_DAYS = 45
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _env_int(name, default):
    try:
        return max(0, int(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _iso(value):
    return value.astimezone(timezone.utc).isoformat()


def _after(now, days):
    return _iso(now + timedelta(days=days))


def _after_spread(now, days, key, *, spread=None):
    """退避 + 按公司名稳定抖动，避免同批失败的公司在同一天雪崩式回归。

    固定天数退避会让同一批失败的公司**全部落在同一天**：2026-08-26 实测
    31 家 wrong_platform + 6 家 no_official_entry 全挤在 9/25，而每天只处理 20 家
    —— 从今天到 9/25 队列半空、到那天又一次性挤爆，之后再空一个月。
    抖动用 crc32(公司名) 而非随机数：同一家每次算出的偏移一致，重跑不会来回漂。
    """
    span = max(1, int(spread if spread is not None else max(1, days // 3)))
    offset = zlib.crc32(str(key or "").encode("utf-8")) % (span * 2 + 1) - span
    return _after(now, max(1, int(days) + offset))


def _source_payload(entry, adapter, source_url, crawl_method="http"):
    industries = entry.get("industries") or []
    return {
        "company": entry["company"],
        "source_url": source_url,
        "source_type": "official",
        "adapter_name": adapter,
        "crawl_method": crawl_method,
        "industry": industries[0] if industries else None,
        "enabled": False,
        "notes": "gap_funnel:pending",
    }


def _prepare_source(supabase, entry, adapter, source_url, crawl_method="http"):
    payload = _source_payload(entry, adapter, source_url, crawl_method)
    response = (
        supabase.table("sources")
        .select("*")
        .eq("source_url", source_url)
        .limit(1)
        .execute()
    )
    existing = (response.data or [None])[0]
    if existing:
        if existing.get("enabled"):
            raise RuntimeError("source_url 已由 enabled source 占用")
        (
            supabase.table("sources")
            .update(payload)
            .eq("id", existing["id"])
            .execute()
        )
        previous = {
            key: existing.get(key)
            for key in payload
            if key in existing
        }
        return {**existing, **payload}, False, previous

    response = supabase.table("sources").insert(payload).execute()
    rows = response.data or []
    if not rows or not rows[0].get("id"):
        raise RuntimeError("sources insert 未返回 id")
    return rows[0], True, None


def _enable_source(supabase, source_id, state):
    (
        supabase.table("sources")
        .update({"enabled": True, "notes": "gap_funnel:%s" % state})
        .eq("id", source_id)
        .execute()
    )


def _delete_source(supabase, source_id):
    supabase.table("sources").delete().eq("id", source_id).execute()


def _delete_crawl_runs(supabase, source_id):
    supabase.table("crawl_runs").delete().eq("source_id", source_id).execute()


def _disable_source(supabase, source_id, state):
    (
        supabase.table("sources")
        .update({"enabled": False, "notes": "gap_funnel:%s" % state})
        .eq("id", source_id)
        .execute()
    )


def read_source_counts(conn, source_id):
    rows = jobs_db.fetch_all(
        conn,
        """
        select
          count(*) filter (
            where summary is not null and char_length(btrim(summary)) >= 60
          ) as healthy,
          count(*) as total
        from jobs
        where source_id = %s and status = 'active'
        """,
        (str(source_id),),
    )
    row = rows[0] if rows else {}
    return {"healthy": int(row.get("healthy") or 0), "total": int(row.get("total") or 0)}


def read_source_samples(conn, source_id, limit=5):
    return jobs_db.fetch_all(
        conn,
        """
        select company, title, jd_url
        from jobs
        where source_id = %s and status = 'active'
          and title is not null and jd_url is not null
        order by first_seen_at desc, id
        limit %s
        """,
        (str(source_id), int(limit)),
    )


def delete_source_jobs(conn, source_id):
    return jobs_db.execute(
        conn, "delete from jobs where source_id = %s", (str(source_id),)
    )


def validate_jd_url(url, title, company=None, *, client=None, timeout=15):
    """抽查逐岗链接：HTTP 200，且页面正文含岗位标题与公司身份信号。"""
    own_client = client is None
    cli = client or httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": _UA, "Accept-Language": "zh-CN,en;q=0.8"},
    )
    try:
        response = None
        for _attempt in range(2):
            try:
                response = cli.get(url, timeout=timeout)
                break
            except Exception:
                continue
        if response is None or response.status_code != 200:
            return False
        expected = "".join(str(title or "").split()).casefold()
        actual = "".join((response.text or "").split()).casefold()
        if not expected or expected not in actual:
            return False
        company_tokens = [
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", str(company or ""))
            if len(token) >= 2
        ]
        return not company_tokens or any(token in actual for token in company_tokens)
    finally:
        if own_client:
            cli.close()


def _sample_that_passes(samples, validate_jd, pattern, company):
    for sample in samples or []:
        url = sample.get("jd_url")
        title = sample.get("title")
        company_matches = must_apply.match_company_against_patterns(
            sample.get("company"), [pattern]
        )
        if (
            company_matches
            and url
            and title
            and validate_jd(url, title, company)
        ):
            return sample
    return None


def _rollback(supabase, jobs_conn, source_id, delete_jobs, *, inserted_new, state,
              previous_source=None):
    errors = []
    try:
        delete_jobs(jobs_conn, source_id)
    except Exception as exc:
        errors.append(exc)
    if inserted_new:
        try:
            _delete_crawl_runs(supabase, source_id)
        except Exception as exc:
            errors.append(exc)
        try:
            _delete_source(supabase, source_id)
        except Exception as exc:
            errors.append(exc)
    else:
        try:
            if previous_source is not None:
                (
                    supabase.table("sources")
                    .update(previous_source)
                    .eq("id", source_id)
                    .execute()
                )
            else:
                _disable_source(supabase, source_id, state)
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise RuntimeError(
            "验收失败且清理不完整: %s"
            % "; ".join("%s: %s" % (type(exc).__name__, exc) for exc in errors)
        )


def run_acceptance_gate(entry, *, adapter, source_url, supabase, jobs_conn,
                        apply, process_source=run._process_one_source,
                        read_counts=read_source_counts,
                        read_samples=read_source_samples,
                        validate_jd=validate_jd_url,
                        delete_jobs=delete_source_jobs,
                        now=None, crawl_method="http", enable_thin=True,
                        thin_rescue=None):
    """真抓验收门。dry-run 不插源、不抓取、不写或删任何数据。

    thin_rescue：可选回调 `(samples) -> bool`，只在「抓到岗位但全是薄卡」时调用。
    某些平台的列表接口**天生不返回正文**（moka 就是，库里 2.6 万张 moka 卡靠每晚
    逐岗渲染 backfill 补正文），对它们要求「当场就有健康岗」等于永远进不来。
    回调的职责是**抽样证明这个源的正文确实取得到**——取得到才放行，
    质量红线不变，变的只是验证方式（当场全有 → 抽样可得）。
    """
    now = now or datetime.now(timezone.utc)
    if not apply:
        return {
            "state": "dry_run",
            "kept_source": False,
            "source_id": None,
            "next_retry_at": None,
            "evidence": {"planned_adapter": adapter, "planned_source_url": source_url},
        }

    source, inserted_new, previous_source = _prepare_source(
        supabase, entry, adapter, source_url, crawl_method
    )
    source_id = source["id"]
    try:
        crawl_result = process_source(source, supabase)
        counts = read_counts(jobs_conn, source_id)
        healthy = int(counts.get("healthy") or 0)
        total = int(counts.get("total") or 0)
        samples = read_samples(jobs_conn, source_id) if total > 0 else []
        passed_sample = (
            _sample_that_passes(
                samples, validate_jd, entry["pattern"], entry["company"]
            )
            if total > 0 else None
        )
    except Exception as original_exc:
        try:
            _rollback(
                supabase, jobs_conn, source_id, delete_jobs,
                inserted_new=inserted_new, state="no_active_jobs",
                previous_source=previous_source,
            )
        except Exception as rollback_exc:
            original_detail = "%s: %s" % (
                type(original_exc).__name__, str(original_exc)[:500]
            )
            rollback_detail = "%s: %s" % (
                type(rollback_exc).__name__, str(rollback_exc)[:500]
            )
            print(
                "[gap_funnel] 验收异常: %s; 回滚异常: %s"
                % (original_detail, rollback_detail)
            )
            raise RuntimeError(
                "验收失败: %s; 回滚失败: %s"
                % (original_detail, rollback_detail)
            ) from original_exc
        raise
    evidence = {
        "crawl_result": crawl_result,
        "healthy_jobs": healthy,
        "total_jobs": total,
        "source_inserted_new": inserted_new,
    }
    if passed_sample:
        evidence["sample_jd_url"] = passed_sample["jd_url"]

    crawl_ok = (crawl_result or {}).get("status") in ("success", "partial_success")
    if not crawl_ok or total == 0:
        _rollback(
            supabase, jobs_conn, source_id, delete_jobs,
            inserted_new=inserted_new, state="no_active_jobs",
            previous_source=previous_source,
        )
        return {
            "state": "no_active_jobs",
            "kept_source": False,
            "source_id": None,
            "inserted_new": inserted_new,
            "next_retry_at": _after(now, 14),
            "fail_reason": "真抓后香港库无 active 岗",
            "evidence": evidence,
        }
    if not passed_sample:
        _rollback(
            supabase, jobs_conn, source_id, delete_jobs,
            inserted_new=inserted_new, state="no_stable_jd",
            previous_source=previous_source,
        )
        return {
            "state": "no_stable_jd",
            "kept_source": False,
            "source_id": None,
            "inserted_new": inserted_new,
            "next_retry_at": _after_spread(
                now, _NO_STABLE_JD_RETRY_DAYS, entry.get("company")
            ),
            "fail_reason": "逐岗链接打不开，或页面缺岗位标题/公司身份信号",
            "evidence": evidence,
        }
    state = "healthy" if healthy >= 1 else "thin_only"
    if state == "thin_only" and not enable_thin and thin_rescue is not None:
        try:
            rescued = bool(thin_rescue(samples))
        except Exception as exc:
            rescued = False
            evidence["thin_rescue_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        evidence["thin_rescue"] = rescued
        if rescued:
            enable_thin = True
    if state == "thin_only" and not enable_thin:
        _rollback(
            supabase, jobs_conn, source_id, delete_jobs,
            inserted_new=inserted_new, state=state,
            previous_source=previous_source,
        )
        return {
            "state": state,
            "kept_source": False,
            "source_id": None,
            "inserted_new": inserted_new,
            "next_retry_at": _after_spread(now, 14, entry.get("company")),
            "fail_reason": "浏览器道真抓后只有薄正文岗位，未达到健康岗验收门",
            "evidence": evidence,
        }
    _enable_source(supabase, source_id, state)
    return {
        "state": state,
        "kept_source": True,
        "source_id": source_id,
        "inserted_new": inserted_new,
        "next_retry_at": (
            None if state == "healthy"
            else _after_spread(now, 14, entry.get("company"))
        ),
        "fail_reason": None,
        "evidence": evidence,
    }


def _attempt_payload(row, result, now):
    evidence = dict(row.get("evidence") or {})
    evidence.update(result.get("evidence") or {})
    state = result["state"]
    next_retry_at = result.get("next_retry_at")
    if state == "dry_run":
        # dry-run 走到验收门就停（不插源、不抓取），但**已经查到的入口/平台必须落台账**：
        # 否则这一轮烧掉的搜索额度白花，下一轮还得对同一批公司重搜一遍
        # （2026-07-26 首轮实测：dry-run 花了 37 次搜索，什么都没记下来）。
        # 落成 platform_known + 立即可重试 → 下次 apply 跑时 process_company 直接复用
        # official_entry_url、跳过搜索。'dry_run' 不是台账 state 枚举值，不能直接写。
        state = "platform_known"
        next_retry_at = _iso(now)
    return {
        "scope": row.get("scope", "domestic"),
        "company": row["company"],
        "pattern": row["pattern"],
        "industries": row.get("industries") or [],
        "state": state,
        "official_entry_url": result.get(
            "official_entry_url", row.get("official_entry_url")
        ),
        "detected_platform": result.get(
            "detected_platform", row.get("detected_platform")
        ),
        "source_id": result.get("source_id"),
        "fail_reason": result.get("fail_reason"),
        "evidence": evidence,
        "attempts": int(row.get("attempts") or 0) + 1,
        "rounds_no_entry": int(
            result.get("rounds_no_entry", row.get("rounds_no_entry") or 0)
        ),
        "last_attempt_at": _iso(now),
        "next_retry_at": next_retry_at,
        "updated_at": _iso(now),
    }


def _write_attempt(supabase, payload):
    supabase.table("must_apply_gap_attempts").upsert(
        payload, on_conflict="scope,company"
    ).execute()


def _failure_for_platform(fingerprint, now, company=None):
    platform = fingerprint["platform"]
    if platform in _MANUAL_PLATFORMS:
        return {
            "state": platform,
            "detected_platform": platform,
            "next_retry_at": None,
            "fail_reason": fingerprint.get("reason") or platform,
            "evidence": {"fingerprint": fingerprint},
        }
    return {
        "state": "wrong_platform",
        "detected_platform": platform,
        "next_retry_at": _after_spread(now, 30, company),
        "fail_reason": "P1 httpx 道无可用 adapter",
        "evidence": {"fingerprint": fingerprint},
    }


def _candidate_items(row, official_url, finder_result):
    items = list((finder_result or {}).get("candidates") or [])
    if not items and finder_result:
        items = [
            item
            for item in ((finder_result.get("evidence") or {}).get("candidate_urls") or [])
            if item.get("verdict") in ("trusted_ats", "likely_official")
        ]
    if not items:
        items = list(((row.get("evidence") or {}).get("candidate_urls") or []))
    if official_url and not any(item.get("url") == official_url for item in items):
        items.insert(0, {"url": official_url})
    # 按「去掉 #fragment 的地址」去重：同一个招聘页的锚点变体（/career、/career#jobs、
    # /career#contactus、/career#hot）本质是同一页，却会吃满 5 个候选名额，
    # 把真正的外部 ATS 入口挤出去——实测万泰生物的 moka 租户地址就是这么丢的。
    seen = set()
    out = []
    for item in items:
        url = str((item or {}).get("url") or "").strip()
        if not url:
            continue
        key = url.split("#", 1)[0] or url
        if key in seen:
            continue
        seen.add(key)
        out.append({**(item or {}), "url": url})
        if len(out) >= 5:
            break
    return out


def _strict_httpx_probe_safe(adapter, source_url):
    if not adapter or not source_url:
        return False
    if adapter == "feishu" or str(adapter).endswith("_feishu"):
        return False
    return run._source_is_httpx_safe({
        "adapter_name": adapter,
        "source_url": source_url,
    })


def _routable_source_url(adapter, source_url):
    if not adapter or not source_url:
        return False
    if adapter == "hotjob":
        parts = [
            part
            for part in urlparse(str(source_url)).path.split("/")
            if part
        ]
        return (
            len(parts) >= 3
            and parts[1].lower() == "pb"
            and parts[2].lower() in {
                "social.html", "school.html", "interns.html"
            }
        )
    return True


def _rejection(url, reason, fingerprint=None):
    return {
        "url": url,
        "host": (urlparse(str(url or "")).hostname or "").lower(),
        "reason": reason,
        "platform": (fingerprint or {}).get("platform"),
        "identity_reason": (fingerprint or {}).get("identity_reason"),
    }


def _evaluate_candidates(row, candidates, *, trusted_site, fingerprinter):
    """候选统一过指纹、身份和路由门；官网候选跳过搜索 URL 评分门。"""
    rejections = []
    fallbacks = []
    identity_checked = 0
    identity_mismatches = 0
    for candidate in candidates:
        candidate_url = candidate["url"]
        if not trusted_site:
            verdict, _score, url_reason = entry_finder.classify_candidate_url(
                candidate_url, row["company"]
            )
            if verdict == "reject":
                rejections.append(_rejection(candidate_url, url_reason))
                continue
        fingerprint = fingerprinter(candidate_url, company=row["company"])
        platform = fingerprint.get("platform")
        if platform in _MANUAL_PLATFORMS:
            fallbacks.append((candidate_url, fingerprint))
            rejections.append(_rejection(
                candidate_url,
                fingerprint.get("reason") or platform,
                fingerprint,
            ))
            continue

        identity_checked += 1
        if fingerprint.get("identity_ok") is not True:
            if fingerprint.get("identity_reason") == "page_company_not_found":
                identity_mismatches += 1
            rejections.append(_rejection(
                candidate_url,
                fingerprint.get("identity_reason") or "identity_unverified",
                fingerprint,
            ))
            continue

        adapter = fingerprint.get("adapter")
        source_url = fingerprint.get("source_url")
        if platform == "iguopin" and adapter == "iguopin" and not source_url:
            source_url = "https://www.iguopin.com/job?company=%s" % quote(
                row["company"], safe=""
            )
            fingerprint = {**fingerprint, "source_url": source_url}
        if not _routable_source_url(adapter, source_url):
            fallbacks.append((candidate_url, fingerprint))
            rejections.append(_rejection(
                candidate_url, "adapter_source_url_unroutable", fingerprint
            ))
            continue
        if not _strict_httpx_probe_safe(adapter, source_url):
            # 转交 P2 浏览器道。platform/adapter 置空是 P2 队列筛选要的（它只接 unknown_spa），
            # 但**已经认出来的平台必须留着**：万泰生物是标准 moka 租户、广汽是 beisen 租户，
            # P2 拿不到这个信息就只能用 company_spa 通用盲抓 → 抓不到逐岗链接 → no_stable_jd。
            # 2026-08-26 实测同一个 URL：company_spa 抓 0 个，moka adapter 抓 15 个带完整 jd_url 的岗。
            browser_fingerprint = {
                **fingerprint,
                "platform": "unknown_spa",
                "adapter": None,
                "real_platform": platform,
                "real_adapter": adapter,
                "real_source_url": source_url,
                "source_url": candidate_url,
                "reason": "requires_browser",
            }
            fallbacks.append((candidate_url, browser_fingerprint))
            rejections.append(_rejection(
                candidate_url, "requires_browser", browser_fingerprint
            ))
            continue
        return {
            "selected": (candidate_url, fingerprint, adapter, source_url),
            "fallbacks": fallbacks,
            "rejections": rejections,
            "identity_checked": identity_checked,
            "identity_mismatches": identity_mismatches,
        }
    return {
        "selected": None,
        "fallbacks": fallbacks,
        "rejections": rejections,
        "identity_checked": identity_checked,
        "identity_mismatches": identity_mismatches,
    }


def _preferred_browser_fallback(fallbacks):
    return next(
        (
            item
            for item in fallbacks
            if item[1].get("platform") == "unknown_spa"
            and item[1].get("identity_ok") is True
        ),
        None,
    )


def process_company(row, *, supabase, jobs_conn, apply, search_remaining,
                    insert_allowed, now=None, finder=entry_finder.find_official_entry,
                    fingerprinter=platform_fingerprint.fingerprint,
                    prober=probe.probe_one, site_resolver=None,
                    site_link_finder=None):
    """处理一家公司；返回 (台账结果, 搜索次数, 是否消耗 insert 配额)。"""
    now = now or datetime.now(timezone.utc)
    site_resolver = site_resolver or site_entry.resolve_official_site_details
    site_link_finder = site_link_finder or site_entry.find_careers_links
    official_url = row.get("official_entry_url")
    cached_rejections = []
    entry_channel = (row.get("evidence") or {}).get("entry_channel") or "search"
    if official_url:
        cached_verdict, _score, cached_reason = (
            entry_finder.classify_candidate_url(official_url, row["company"])
        )
        if cached_verdict == "reject":
            cached_rejections.append(_rejection(official_url, cached_reason))
            official_url = None
    search_used = 0
    finder_result = None
    selected = None
    fallbacks = []
    rejections = list(cached_rejections)
    identity_checked = 0
    identity_mismatches = 0
    candidate_evidence = {}

    if not official_url:
        site_result = None
        try:
            site_result = site_resolver(row["company"], supabase=supabase)
        except Exception:
            site_result = None
        if isinstance(site_result, str):
            site_result = {
                "home_url": site_result,
                "entry_channel": "wikidata_site",
            }
        if site_result and site_result.get("home_url"):
            try:
                site_candidates = site_link_finder(
                    row["company"], site_result["home_url"]
                )
            except Exception:
                site_candidates = []
            site_candidates = _candidate_items(
                row, None, {"candidates": site_candidates}
            )
            candidate_evidence.update({
                "site_home_url": site_result["home_url"],
                "candidate_urls": list(site_candidates),
            })
            evaluated = _evaluate_candidates(
                row,
                site_candidates,
                trusted_site=True,
                fingerprinter=fingerprinter,
            )
            selected = evaluated["selected"]
            fallbacks.extend(evaluated["fallbacks"])
            rejections.extend(evaluated["rejections"])
            identity_checked += evaluated["identity_checked"]
            identity_mismatches += evaluated["identity_mismatches"]
            if selected:
                entry_channel = site_result.get(
                    "entry_channel", "wikidata_site"
                )
            else:
                browser_fallback = _preferred_browser_fallback(
                    evaluated["fallbacks"]
                )
                if browser_fallback:
                    entry_channel = site_result.get(
                        "entry_channel", "wikidata_site"
                    )
                    fallback_url, fallback_fingerprint = browser_fallback
                    rejected_hosts = sorted({
                        item["host"] for item in rejections if item.get("host")
                    })
                    rejection_evidence = {
                        **candidate_evidence,
                        "entry_channel": entry_channel,
                        "candidate_rejections": rejections,
                        "rejected_candidate_hosts": rejected_hosts,
                    }
                    result = _failure_for_platform(
                        fallback_fingerprint, now, row["company"]
                    )
                    result["official_entry_url"] = fallback_url
                    result["evidence"] = {
                        **result.get("evidence", {}),
                        **rejection_evidence,
                    }
                    return result, 0, False

    if not official_url and selected is None:
        finder_result = finder(
            row["company"],
            supabase,
            prev_row=row,
            max_searches=min(2, max(0, search_remaining)),
            now=now,
            consume=True,
        )
        search_used = int(finder_result.get("search_used") or 0)
        if not finder_result.get("found"):
            failed = dict(finder_result)
            fail_reason = str(failed.get("fail_reason") or "")
            if (
                failed.get("state") == "unknown"
                and not failed.get("next_retry_at")
                and (
                    search_remaining <= 0
                    or "无可用搜索 provider" in fail_reason
                    or "搜索额度已耗尽" in fail_reason
                )
            ):
                failed["next_retry_at"] = _after(now, 1)
            evidence = dict(failed.get("evidence") or {})
            search_candidates = list(evidence.get("candidate_urls") or [])
            evidence.update(candidate_evidence)
            evidence["candidate_urls"] = (
                list(candidate_evidence.get("candidate_urls") or [])
                + search_candidates
            )
            evidence.update({
                "entry_channel": "search",
                "candidate_rejections": rejections,
                "rejected_candidate_hosts": sorted({
                    item["host"]
                    for item in rejections
                    if item.get("host")
                }),
            })
            failed["evidence"] = evidence
            return failed, search_used, False
        official_url = finder_result["official_entry_url"]
        search_candidates = _candidate_items(row, official_url, finder_result)
        search_evidence = dict((finder_result or {}).get("evidence") or {})
        previous_candidates = list(candidate_evidence.get("candidate_urls") or [])
        candidate_evidence.update(search_evidence)
        candidate_evidence["candidate_urls"] = (
            previous_candidates + search_candidates
        )
        evaluated = _evaluate_candidates(
            row,
            search_candidates,
            trusted_site=False,
            fingerprinter=fingerprinter,
        )
        selected = evaluated["selected"]
        fallbacks.extend(evaluated["fallbacks"])
        rejections.extend(evaluated["rejections"])
        identity_checked += evaluated["identity_checked"]
        identity_mismatches += evaluated["identity_mismatches"]
        entry_channel = "search"
    elif official_url:
        candidates = _candidate_items(row, official_url, finder_result)
        candidate_evidence = dict((finder_result or {}).get("evidence") or {})
        candidate_evidence["candidate_urls"] = candidates
        evaluated = _evaluate_candidates(
            row,
            candidates,
            trusted_site=False,
            fingerprinter=fingerprinter,
        )
        selected = evaluated["selected"]
        fallbacks.extend(evaluated["fallbacks"])
        rejections.extend(evaluated["rejections"])
        identity_checked += evaluated["identity_checked"]
        identity_mismatches += evaluated["identity_mismatches"]

    rejected_hosts = sorted({
        item["host"] for item in rejections if item.get("host")
    })
    rejection_evidence = {
        **candidate_evidence,
        "entry_channel": entry_channel,
        "candidate_rejections": rejections,
        "rejected_candidate_hosts": rejected_hosts,
    }
    if selected is None:
        if (
            identity_checked > 0
            and identity_mismatches == identity_checked
            and not fallbacks
        ):
            return {
                "state": "wrong_platform",
                "official_entry_url": None,
                "detected_platform": None,
                "next_retry_at": _after(now, 30),
                "fail_reason": "候选入口均非本公司（张冠李戴）",
                "evidence": rejection_evidence,
            }, search_used, False
        browser_fallback = _preferred_browser_fallback(fallbacks)
        if browser_fallback:
            fallback_url, fallback_fingerprint = browser_fallback
        elif fallbacks:
            fallback_url, fallback_fingerprint = next(
                (
                    item
                    for item in fallbacks
                    if item[1].get("platform") == "unknown_spa"
                ),
                fallbacks[0],
            )
        else:
            fallback_url = official_url
            fallback_fingerprint = {
                "platform": "unknown",
                "adapter": None,
                "source_url": None,
                "reason": "no_routable_candidate",
            }
        result = _failure_for_platform(
            fallback_fingerprint, now, row["company"]
        )
        result["official_entry_url"] = fallback_url
        result["evidence"] = {
            **result.get("evidence", {}),
            **rejection_evidence,
        }
        return result, search_used, False

    official_url, fingerprint, adapter, source_url = selected

    probe_result = prober({
        "company": row["company"],
        "adapter": adapter,
        "url": source_url,
        "industry": (row.get("industries") or [None])[0],
    })
    if not probe_result.get("ok") or int(probe_result.get("valid") or 0) <= 0:
        return {
            "state": "no_active_jobs",
            "official_entry_url": official_url,
            "detected_platform": fingerprint.get("platform"),
            "next_retry_at": _after(now, 14),
            "fail_reason": probe_result.get("reason") or "只读探活无有效岗位",
            "evidence": {
                "fingerprint": fingerprint,
                "probe": probe_result,
                **rejection_evidence,
            },
        }, search_used, False

    if apply and not insert_allowed:
        return {
            "state": "platform_known",
            "official_entry_url": official_url,
            "detected_platform": fingerprint.get("platform"),
            "next_retry_at": _after(now, 1),
            "fail_reason": "本轮 insert 配额已用完",
            "evidence": {
                "fingerprint": fingerprint,
                "probe": probe_result,
                **rejection_evidence,
            },
        }, search_used, False

    gate = run_acceptance_gate(
        row,
        adapter=adapter,
        source_url=source_url,
        supabase=supabase,
        jobs_conn=jobs_conn,
        apply=apply,
        now=now,
    )
    if not apply:
        gate.update({
            "state": "platform_known",
            "official_entry_url": official_url,
            "detected_platform": fingerprint.get("platform"),
            "fail_reason": None,
            "evidence": {
                **gate.get("evidence", {}),
                "fingerprint": fingerprint,
                "probe": probe_result,
                **rejection_evidence,
                "planned_action": "真抓+香港库回读验收",
            },
        })
    else:
        gate["official_entry_url"] = official_url
        gate["detected_platform"] = fingerprint.get("platform")
        gate["evidence"] = {
            **gate.get("evidence", {}),
            "fingerprint": fingerprint,
            "probe": probe_result,
            **rejection_evidence,
        }
    return gate, search_used, bool(apply and gate.get("inserted_new"))


def run_round(*, scope="domestic", limit=None, company=None, apply=False,
              supabase=None, jobs_conn=None, now=None):
    now = now or datetime.now(timezone.utc)
    started = now
    supabase = supabase or db.get_supabase()
    jobs_conn = jobs_conn or jobs_db.get_conn()
    company_cap = limit if limit is not None else _env_int("GAP_FUNNEL_COMPANY_CAP", 20)
    search_cap = _env_int("GAP_FUNNEL_SEARCH_CAP", 40)
    insert_cap = _env_int("GAP_FUNNEL_INSERT_CAP", 15)
    census_result = gap_census.census(
        supabase,
        jobs_conn,
        scope=scope,
        cap=company_cap,
        company=company,
        apply=apply,
        now=now,
    )
    queue = census_result["queue"]
    round_source_rows = []
    if queue:
        try:
            round_source_rows = db.fetch_all_rows(
                lambda: supabase.table("sources").select(
                    "id,company,source_url,enabled"
                ).eq("enabled", True)
            )
        except Exception:
            round_source_rows = []

    def round_site_resolver(company_name, **_kwargs):
        return site_entry.resolve_official_site_details(
            company_name,
            supabase=supabase,
            source_rows=round_source_rows,
        )

    outcomes = []
    search_used = 0
    inserts_used = 0
    stopped_search_cap = False

    for row in queue:
        scoped = {**row, "scope": scope}
        try:
            result, used, inserted = process_company(
                scoped,
                supabase=supabase,
                jobs_conn=jobs_conn,
                apply=apply,
                search_remaining=search_cap - search_used,
                insert_allowed=inserts_used < insert_cap,
                now=now,
                site_resolver=round_site_resolver,
            )
            search_used += used
            inserts_used += int(inserted)
            payload = _attempt_payload(scoped, result, now)
        except Exception as exc:
            print(
                "[gap_funnel] %s 处理异常: %s: %s"
                % (row["company"], type(exc).__name__, str(exc)[:500])
            )
            payload = _attempt_payload(scoped, {
                "state": scoped.get("state") or "unknown",
                "next_retry_at": _after(now, 1),
                "fail_reason": "%s: %s" % (type(exc).__name__, str(exc)[:500]),
                "evidence": {"exception_type": type(exc).__name__},
            }, now)
        outcomes.append(payload)
        # 逐家打印判定：dry-run 的全部价值就在于人能看懂它每家判了什么、凭什么判的。
        print(
            "[gap_funnel] %s → %s｜入口=%s｜平台=%s｜原因=%s"
            % (payload["company"], payload["state"],
               payload.get("official_entry_url") or "-",
               payload.get("detected_platform") or "-",
               payload.get("fail_reason") or "-")
        )
        # 台账**不分 apply**：它是我们自己的簿记（不是 sources/jobs），
        # dry-run 也必须落盘，否则这轮烧掉的搜索额度白花、下轮还得重搜同一批公司。
        try:
            _write_attempt(supabase, payload)
        except Exception as exc:
            print(
                "[gap_funnel] %s 台账写入失败: %s: %s"
                % (row["company"], type(exc).__name__, str(exc)[:160])
            )

    counts = Counter(item["state"] for item in outcomes)
    failed = sum(
        count for state, count in counts.items()
        if state not in ("healthy", "thin_only", "platform_known")
    )
    metrics = {
        "checked": len(outcomes),
        "processed": len(outcomes),
        "healthy": counts.get("healthy", 0),
        "thin_only": counts.get("thin_only", 0),
        "search_used": search_used,
        "inserted": inserts_used,
        "sources_added": sum(
            1
            for item in outcomes
            if item.get("state") in ("healthy", "thin_only")
            and item.get("evidence", {}).get("source_inserted_new") is True
            and item.get("source_id")
        ),
        "states": dict(counts),
        "dry_run": not apply,
        "list_version": must_apply.version(),
        "stopped_search_cap": stopped_search_cap,
    }
    if apply:
        ops_runs.record_ops_run(
            supabase,
            "gap_funnel",
            metrics,
            status=ops_runs.status_from_counts(len(outcomes), failed),
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        )
    failures = ",".join(
        "%s=%s" % (state, count)
        for state, count in sorted(counts.items())
        if state not in ("healthy", "thin_only")
    ) or "无"
    print(
        "[gap_funnel] 处理=%d 新增healthy=%d thin_only=%d 失败态=%s "
        "真实搜索消耗=%d/%d apply=%s"
        % (
            len(outcomes),
            counts.get("healthy", 0),
            counts.get("thin_only", 0),
            failures,
            search_used,
            search_cap,
            apply,
        )
    )
    return {"outcomes": outcomes, "metrics": metrics, "queue": queue}


def run_tenant_seed_round(*, limit=None, apply=False, supabase=None,
                          jobs_conn=None, now=None):
    """将本地 ATS 租户快照按既有验收门转成候选源，默认仅 dry-run。"""
    now = now or datetime.now(timezone.utc)
    supabase = supabase or db.get_supabase()
    insert_cap = _env_int("GAP_FUNNEL_TENANT_SEED_INSERT_CAP", 15)
    requested = insert_cap if limit is None else max(0, int(limit))
    tenant_cap = min(requested, insert_cap)
    existing_source_urls = [
        row.get("source_url")
        for row in db.fetch_all_rows(
            lambda: supabase.table("sources").select("source_url")
        )
        if row.get("source_url")
    ]
    tenants = ats_tenant_seed.rank_tenants(
        ats_tenant_seed.filter_new_tenants(
            ats_tenant_seed.load_upstream_tenants(), existing_source_urls
        ),
        must_apply.all_patterns(),
    )[:tenant_cap]
    queue = [{
        **tenant,
        "adapter": tenant["platform"],
        "crawl_method": "playwright",
    } for tenant in tenants]
    if apply and jobs_conn is None:
        jobs_conn = jobs_db.get_conn()

    outcomes = []
    for tenant in queue:
        entry = {
            "company": tenant["name"],
            "pattern": "%%%s%%" % tenant["name"],
            "industries": [],
        }
        result = run_acceptance_gate(
            entry,
            adapter=tenant["adapter"],
            source_url=tenant["url"],
            supabase=supabase,
            jobs_conn=jobs_conn,
            apply=apply,
            now=now,
            crawl_method=tenant["crawl_method"],
            enable_thin=False,
        )
        healthy = int((result.get("evidence") or {}).get("healthy_jobs") or 0)
        outcome = {**tenant, **result}
        outcomes.append(outcome)
        print(
            "[tenant_seed] %s → %s｜平台=%s｜URL=%s｜健康岗=%d"
            % (tenant["name"], result["state"], tenant["platform"], tenant["url"], healthy)
        )
    return {
        "outcomes": outcomes,
        "queue": queue,
        "metrics": {
            "checked": len(outcomes),
            "states": dict(Counter(item["state"] for item in outcomes)),
            "dry_run": not apply,
            "insert_cap": insert_cap,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="必投清单缺口漏斗 P1（httpx 道）")
    parser.add_argument("--scope", choices=["domestic", "overseas"], default="domestic")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--company", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tenant-seed", action="store_true")
    args = parser.parse_args(argv)
    apply = os.environ.get("GAP_FUNNEL_APPLY", "").strip().lower() in _TRUE
    if args.dry_run:
        apply = False
    if args.tenant_seed:
        run_tenant_seed_round(
            limit=max(0, args.limit) if args.limit is not None else None,
            apply=apply,
        )
        return
    run_round(
        scope=args.scope,
        limit=max(0, args.limit) if args.limit is not None else None,
        company=args.company,
        apply=apply,
    )


if __name__ == "__main__":
    main()
