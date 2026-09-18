"""必投清单缺口漏斗 P1：httpx 入口发现 → 指纹 → 探活 → 真抓 → 回读验收。"""
import argparse
import json
import os
import re
import zlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import httpx

import ats_tenant_seed
import db
import enrich
import entry_finder
import entry_lanes
import gap_census
import jobs_db
import must_apply
import north_star_snapshot
import ops_runs
import platform_fingerprint
import probe
import run
import site_entry


_TRUE = {"1", "true", "yes", "on"}
# login_wall 是**对方的门槛**，只能转人工 → 永不重试。anti_bot 的策略可能变化，保留长退避复试。
# no_stable_jd 不一样：它是**我们没拿到逐岗链接**，属于自身抓取能力问题，
# 而抓取能力一直在改进（2026-08-26 就修掉一个：P2 对标准 ATS 租户误用通用盲抓，
# 万泰生物同一 URL 由 0 个岗变 15 个）。把它钉成永不重试 = 每次能力升级都救不回存量。
# 故给长退避，让系统改进后能自我修复。
_MANUAL_PLATFORMS = {"login_wall"}
_ANTI_BOT_RETRY_DAYS = 30
_BLOCKED_PLATFORMS = _MANUAL_PLATFORMS | {"anti_bot"}
_NO_STABLE_JD_RETRY_DAYS = 45
_BROWSER_REVIEW_RETRY_DAYS = 14
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


def _sample_validation(sample, *, adapter, source_url, validate_jd, company):
    """返回 pass / fail / browser_review。

    httpx 详情 HTML 对 SPA 只是空壳，不能把「未看见标题」当成链接失效。已有
    enrich detail 探活器的明确关闭信号才可判 fail；没有这类接口的源一律交浏览器复核。
    """
    if adapter in enrich.ENRICH_REGISTRY:
        try:
            enrich.enrich_one(adapter, sample, {
                "source_url": source_url,
                "adapter_name": adapter,
            })
            return "pass"
        except enrich.JobClosedError:
            return "fail"
        except Exception:
            # 网络/限流/接口改版都不能证明岗位已关闭。
            return "browser_review"
    # 无接口关闭信号（包括 browser adapter、未知 SPA、网络异常和接口改版）一律中性复核。
    # HTML 标题核验无法证明 SPA 链接失效，不能再参与删源判定。
    return "browser_review"


def _sample_that_passes(samples, validate_jd, patterns, company, *, adapter, source_url):
    """`patterns` 收 pattern 或 pattern+别名列表：新源抓回来的公司名可能是英文
    （Workday 站点回 `Continental` 而清单写「大陆集团」），只按中文 pattern 核就会把
    **抓通了的源当成张冠李戴删掉**——比判错覆盖率更贵。"""
    pats = [patterns] if isinstance(patterns, str) else [p for p in (patterns or []) if p]
    browser_review = False
    for sample in samples or []:
        url = sample.get("jd_url")
        title = sample.get("title")
        company_matches = must_apply.match_company_against_patterns(
            sample.get("company"), pats
        )
        if company_matches and url and title:
            verdict = _sample_validation(
                sample, adapter=adapter, source_url=source_url,
                validate_jd=validate_jd, company=company,
            )
            if verdict == "pass":
                return sample, False
            if verdict == "browser_review":
                browser_review = True
    return None, browser_review


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
        passed_sample, needs_browser_review = (
            _sample_that_passes(
                samples, validate_jd,
                must_apply.patterns_for_company(entry["company"]) or [entry["pattern"]],
                entry["company"],
                adapter=adapter, source_url=source_url,
            )
            if total > 0 else (None, False)
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
        if needs_browser_review:
            _enable_source(supabase, source_id, "browser_review")
            return {
                # state 是 must_apply_gap_attempts 的受限枚举；复用 platform_known，
                # 具体待办放 fail_reason/evidence，避免为了中性结果写坏台账。
                "state": "platform_known",
                "kept_source": True,
                "source_id": source_id,
                "inserted_new": inserted_new,
                "next_retry_at": _after_spread(
                    now, _BROWSER_REVIEW_RETRY_DAYS, entry.get("company")
                ),
                "fail_reason": "待浏览器复核：未据 SPA 空壳回滚来源",
                "evidence": {**evidence, "browser_review_pending": True},
            }
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
        print(f"[gap_funnel] {company or 'unknown'}: {platform} 需人工处理，不自动重试")
        return {
            "state": platform,
            "detected_platform": platform,
            "next_retry_at": None,
            "fail_reason": fingerprint.get("reason") or platform,
            "evidence": {"fingerprint": fingerprint},
        }
    if platform == "anti_bot":
        return {
            "state": platform,
            "detected_platform": platform,
            "next_retry_at": _after(now, _ANTI_BOT_RETRY_DAYS),
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
    return _dedupe_candidate_items(items)


def _dedupe_candidate_items(items):
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


# ── 校招车道：把「搜到的入口」换算成该平台的校招板块 URL ─────────────────────────
# 社招入口和校招入口常在同一平台的两个板块上：hotjob 是 social.html / school.html，飞书是
# /index/position / /campus/position（用 website-path 头切门户），国聘是 nature=应届生。
# 认不出校招板块的平台（外企 ATS 校招社招混在一个列表里）返回 None → 这条候选在校招车道
# 里视为不可路由，宁可不接也不把社招源当校招源再插一遍。
_CAMPUS_NATURE = "115xW5oQ"


def campus_source_url(adapter, source_url):
    adapter = str(adapter or "")
    url = str(source_url or "")
    if not adapter or not url:
        return None
    if adapter == "hotjob":
        return re.sub(r"/pb/(social|interns)\.html", "/pb/school.html", url) if "/pb/" in url else None
    if adapter == "feishu" or adapter.endswith("_feishu"):
        if "/campus/position" in url or "/internship/position" in url:
            return url
        return re.sub(r"/index/position\b", "/campus/position", url) if "/index/position" in url else None
    if adapter == "iguopin":
        if "nature=" in url:
            return url
        return url + ("&" if "?" in url else "?") + "nature=%s&channel=campus" % _CAMPUS_NATURE
    if adapter == "moka":
        return url if re.search(r"campus", url, re.I) else None
    # 一次抓全三类的 adapter（sources.board = mixed）：社招入口本身就带校招岗，源已存在就不重插
    if adapter in ("beisen", "wt", "tencent", "baidu"):
        return url
    if adapter.endswith("_campus"):
        return url
    return None


def _campus_fingerprinter(fingerprinter):
    """包一层：把指纹认出的 source_url 换成校招板块 URL；换不出来就让它在路由门上被拦。"""

    def wrapped(url, company=None):
        fingerprint = fingerprinter(url, company=company)
        adapter = fingerprint.get("adapter")
        derived = campus_source_url(adapter, fingerprint.get("source_url"))
        if fingerprint.get("platform") in _BLOCKED_PLATFORMS or fingerprint.get("identity_ok") is not True:
            return fingerprint
        if not derived:
            return {**fingerprint, "source_url": None, "reason": "no_campus_board"}
        return {**fingerprint, "source_url": derived}

    return wrapped


def campus_attempt_payload(row, result, now):
    """校招车道的台账写法：**不碰** state / official_entry_url / next_retry_at（那些是社招入口的），
    只把本轮结论记进 evidence.campus_lane 并设校招车道自己的退避。"""
    evidence = dict(row.get("evidence") or {})
    state = result.get("state")
    if state == "dry_run":
        state = "platform_known"
    lane = {
        "state": state,
        "entry_lane": (result.get("evidence") or {}).get("entry_lane"),
        "official_entry_url": result.get("official_entry_url"),
        "detected_platform": result.get("detected_platform"),
        "source_url": ((result.get("evidence") or {}).get("planned_source_url")
                       or (result.get("evidence") or {}).get("source_url")),
        "source_id": result.get("source_id"),
        "fail_reason": result.get("fail_reason"),
        "attempted_at": _iso(now),
    }
    retry = result.get("next_retry_at")
    if state in ("healthy", "thin_only") and result.get("source_id"):
        retry = None   # 接通了：下轮 census 按产出把 campus_channel 翻成 healthy，车道不再排它
    elif not retry:
        retry = _after(now, gap_census._CAMPUS_RETRY_DAYS)
    evidence["campus_lane"] = lane
    evidence["campus_lanes"] = (result.get("evidence") or {}).get("lanes") or {}
    evidence["campus_attempts"] = _as_int(evidence.get("campus_attempts")) + 1
    evidence["campus_next_retry_at"] = retry
    return {
        "scope": row.get("scope", "domestic"),
        "company": row["company"],
        "pattern": row["pattern"],
        "industries": row.get("industries") or [],
        "evidence": evidence,
        "updated_at": _iso(now),
    }


def _as_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def process_campus_channel(row, **kwargs):
    """校招车道 = process_company 换三样：校招查询词、校招板块 URL 换算、不复用社招入口缓存。"""
    finder = kwargs.pop("finder", entry_finder.find_official_entry)
    fingerprinter = kwargs.pop("fingerprinter", platform_fingerprint.fingerprint)

    def campus_finder(company, supabase, **fkw):
        return finder(company, supabase, queries=entry_finder.CAMPUS_QUERIES, **fkw)

    evidence = row.get("evidence") or {}
    lane_row = {
        **row,
        "official_entry_url": None,          # 社招入口不是校招入口，别拿它当缓存
        "evidence": {
            **{k: v for k, v in evidence.items()
               if k not in ("candidate_urls", "entry_channel", "lanes")},
            # 车道退避**两条渠道各记各的**（存在 evidence.campus_lanes）：社招那边
            # slug 车道试过没结果而进入 21 天退避，不该顺手把校招的 slug 车道也锁上 ——
            # 同一家公司的社招门户和校招门户常常是两个不同的 slug / 两个不同的板块。
            "lanes": evidence.get("campus_lanes") or {},
        },
    }
    return process_company(lane_row, finder=campus_finder,
                           fingerprinter=_campus_fingerprinter(fingerprinter), **kwargs)


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
        # `preset` = 出这条候选的车道**自己已经做过**平台识别 + 归属核验
        # （slug 车道走 discover_domestic 的 title-verify / 自报 company 核验，
        #  与 verify_page_identity 同等强度，见 entry_lanes 的注释）。
        # 之所以要这个口子：moka / beisen 这类纯 SPA 壳用 httpx 拿不到可核验的正文，
        # 再跑一遍页面身份门只会把已经核验过的真租户判成 identity_unverified 丢掉。
        # ⚠️ 它只跳过**身份门**，下面的路由门、httpx 安全门、探活、真抓回读一个都不跳。
        preset = candidate.get("preset") if isinstance(candidate, dict) else None
        fingerprint = dict(preset) if isinstance(preset, dict) else fingerprinter(
            candidate_url, company=row["company"]
        )
        platform = fingerprint.get("platform")
        if platform in _BLOCKED_PLATFORMS:
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


def browser_handoff_rows(outcomes):
    """取本轮应即时交给 P2 的 unknown_spa 入口，按公司去重且保留 P2 所需台账字段。"""
    rows, seen = [], set()
    for outcome in outcomes or []:
        if outcome.get("detected_platform") != "unknown_spa":
            continue
        company = str(outcome.get("company") or "").strip()
        entry_url = str(outcome.get("official_entry_url") or "").strip()
        key = company.casefold()
        if not company or not entry_url or key in seen:
            continue
        seen.add(key)
        rows.append({
            field: outcome.get(field)
            for field in (
                "company", "pattern", "industries", "scope", "state",
                "official_entry_url", "detected_platform", "next_retry_at", "evidence",
            )
        })
    return rows


def write_browser_handoff(path, outcomes):
    """将 P1 本轮 unknown_spa 结果写为 P2 artifact。"""
    rows = browser_handoff_rows(outcomes)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "companies": rows}, handle, ensure_ascii=False)
    print("[gap_funnel] P2 交接文件已写 %s（unknown_spa=%d）" % (path, len(rows)))
    return rows


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
    entry_channel = (row.get("evidence") or {}).get("entry_channel") or "search"
    search_used = 0
    finder_result = None
    selected = None
    fallbacks = []
    rejections = []
    identity_checked = 0
    identity_mismatches = 0
    candidate_evidence = {}
    cache_evaluated = False
    if official_url:
        cached_verdict, _score, cached_reason = (
            entry_finder.classify_candidate_url(official_url, row["company"])
        )
        if cached_verdict == "reject":
            rejections.append(_rejection(official_url, cached_reason))
            official_url = None
        else:
            # 缓存入口也必须过与首次发现完全相同的 URL + 页面身份门；缓存错配时不能
            # 继续把旧公司的候选粘住，应丢弃后重新发现。
            cache_evaluated = True
            evaluated = _evaluate_candidates(
                row, [{"url": official_url}], trusted_site=False, fingerprinter=fingerprinter,
            )
            selected = evaluated["selected"]
            fallbacks.extend(evaluated["fallbacks"])
            rejections.extend(evaluated["rejections"])
            identity_checked += evaluated["identity_checked"]
            identity_mismatches += evaluated["identity_mismatches"]
            candidate_evidence["candidate_urls"] = [{"url": official_url}]
            if (
                selected is None
                and identity_checked > 0
                and identity_mismatches == identity_checked
                and not fallbacks
            ):
                official_url = None

    # ── 免费车道（slug / 官网 / 线索 / 国聘），全部排在搜索之前 ─────────────────
    # 创始人 2026-09-18 定：搜索额度只能是最后手段（它是全局共享的，见 CLAUDE.md）。
    # 每条车道**各自退避**：一条不通只锁自己，不锁整家公司（「退避锁死自我修复」那块碑）。
    ledger = entry_lanes.lane_ledger(row)
    entry_lane = (row.get("evidence") or {}).get("entry_lane")
    deferred_browser = None
    if not official_url and selected is None:
        planned = [lane for lane in entry_lanes.plan_lanes(row, now=now)
                   if lane != entry_lanes.LANE_SEARCH]
        for lane in planned:
            lane_items, lane_reason, trusted = [], None, False
            if lane == entry_lanes.LANE_SLUG:
                lane_items = entry_lanes.slug_candidates(
                    row["company"], seeds=row.get("slugs") or (), supabase=supabase)
                trusted = True
            elif lane == entry_lanes.LANE_HOMEPAGE:
                lane_items, site_result = entry_lanes.homepage_candidates(
                    row["company"],
                    site_resolver=lambda name: site_resolver(name, supabase=supabase),
                    link_finder=site_link_finder,
                )
                trusted = True
                if site_result:
                    lane_reason = site_result.get("entry_channel")
                    candidate_evidence["site_home_url"] = site_result.get("home_url")
            elif lane == entry_lanes.LANE_HINT:
                lane_items = entry_lanes.hint_candidates(row["company"])
            elif lane == entry_lanes.LANE_IGUOPIN:
                lane_items = entry_lanes.iguopin_candidates(row["company"])
            # 刻意**不**走 _candidate_items：它在候选为空时会回落到 row.evidence.candidate_urls，
            # 那会把上一轮（甚至别条车道）的陈旧候选当成本车道的产出，把台账和计数一起搞脏。
            lane_items = _dedupe_candidate_items(lane_items)
            if not lane_items:
                ledger = entry_lanes.record_lane(
                    ledger, lane, found=False, company=row["company"], now=now,
                    reason=lane_reason or "no_candidate")
                continue
            candidate_evidence["candidate_urls"] = (
                list(candidate_evidence.get("candidate_urls") or []) + lane_items
            )
            evaluated = _evaluate_candidates(
                row, lane_items, trusted_site=trusted, fingerprinter=fingerprinter,
            )
            fallbacks.extend(evaluated["fallbacks"])
            rejections.extend(evaluated["rejections"])
            identity_checked += evaluated["identity_checked"]
            identity_mismatches += evaluated["identity_mismatches"]
            ledger = entry_lanes.record_lane(
                ledger, lane, found=bool(evaluated["selected"]),
                company=row["company"], now=now,
                reason=lane_reason or ("selected" if evaluated["selected"] else "no_routable"),
                candidates=len(lane_items))
            if evaluated["selected"]:
                selected = evaluated["selected"]
                entry_lane = lane
                entry_channel = lane_reason or lane
                break
            if deferred_browser is None:
                # 浏览器道交接**推迟到所有免费车道跑完**再决定：先前的写法一拿到官网 SPA
                # 就立刻 return，把后面几条更便宜也更可能命中的车道整条堵死。
                browser_fallback = _preferred_browser_fallback(evaluated["fallbacks"])
                if browser_fallback:
                    deferred_browser = (browser_fallback, lane_reason or lane, lane)

    if selected is None and deferred_browser is not None:
        (fallback_url, fallback_fingerprint), channel, lane = deferred_browser
        rejection_evidence = {
            **candidate_evidence,
            "entry_channel": channel,
            "entry_lane": lane,
            "lanes": ledger,
            "candidate_rejections": rejections,
            "rejected_candidate_hosts": sorted({
                item["host"] for item in rejections if item.get("host")
            }),
        }
        result = _failure_for_platform(fallback_fingerprint, now, row["company"])
        result["official_entry_url"] = fallback_url
        result["evidence"] = {**result.get("evidence", {}), **rejection_evidence}
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
                "entry_lane": entry_lanes.LANE_SEARCH,
                "lanes": entry_lanes.record_lane(
                    ledger, entry_lanes.LANE_SEARCH, found=False,
                    company=row["company"], now=now,
                    reason=failed.get("fail_reason")),
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
        ledger = entry_lanes.record_lane(
            ledger, entry_lanes.LANE_SEARCH, found=bool(selected),
            company=row["company"], now=now,
            reason="selected" if selected else "no_routable",
            candidates=len(search_candidates))
        if selected:
            entry_lane = entry_lanes.LANE_SEARCH
    elif official_url and selected is None and not cache_evaluated:
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
        "entry_lane": entry_lane,
        "lanes": ledger,
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
              supabase=None, jobs_conn=None, now=None, handoff_file=None):
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
    if (
        os.environ.get("NORTH_STAR_SNAPSHOT", "").lower() in _TRUE
        and scope == "domestic"
        and not company
    ):
        north_star_snapshot.record_daily_snapshot(
            supabase,
            jobs_conn,
            now=now,
            census_rows=census_result["rows"],
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

    # ── 校招车道（2026-09-17）：missing 的必投公司另搜校招入口。与主队列共用搜索额度与 insert 配额。
    campus_outcomes = []
    campus_queue = census_result.get("campus_queue") or []
    for row in campus_queue:
        if company and row["company"] != company:
            continue
        scoped = {**row, "scope": scope}
        try:
            result, used, inserted = process_campus_channel(
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
        except Exception as exc:
            print("[gap_funnel][campus] %s 处理异常: %s: %s"
                  % (row["company"], type(exc).__name__, str(exc)[:500]))
            result = {"state": "unknown", "next_retry_at": _after(now, 1),
                      "fail_reason": "%s: %s" % (type(exc).__name__, str(exc)[:500])}
        payload = campus_attempt_payload(scoped, result, now)
        campus_outcomes.append(payload)
        lane = payload["evidence"]["campus_lane"]
        print("[gap_funnel][campus] %s → %s｜入口=%s｜平台=%s｜源=%s｜原因=%s"
              % (payload["company"], lane["state"], lane.get("official_entry_url") or "-",
                 lane.get("detected_platform") or "-", lane.get("source_url") or "-",
                 lane.get("fail_reason") or "-"))
        try:
            _write_attempt(supabase, payload)
        except Exception as exc:
            print("[gap_funnel][campus] %s 台账写入失败: %s: %s"
                  % (row["company"], type(exc).__name__, str(exc)[:160]))

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
        # 必投校招渠道分布（迁移 254）：healthy / idle / missing 三个数每天落台账，
        # 「必投校招覆盖率」= healthy / 国内清单数，从 2026-09-17 的 53% 往上走。
        "campus_channel": census_result.get("campus_channel") or {},
        # 分车道计数（2026-09-18）：入口是从哪条车道找到的。所有键恒存在（含 0）——
        # 缺键会被读成「这条车道没跑」，而不是「跑了但一家都没找到」。
        # not_found 单独一栏，专防「绿灯零产出」：处理了 20 家、一条车道都没命中要看得见。
        **entry_lanes.summarize_lanes(outcomes),
        "campus_lane_by_entry_lane": entry_lanes.summarize_lanes([
            {"evidence": {"entry_lane": (item["evidence"].get("campus_lane") or {}).get("entry_lane")}}
            for item in campus_outcomes]),
        "campus_lane_processed": len(campus_outcomes),
        "campus_lane_states": dict(Counter(
            item["evidence"]["campus_lane"]["state"] for item in campus_outcomes)),
        "campus_sources_added": sum(
            1 for item in campus_outcomes
            if item["evidence"]["campus_lane"].get("state") in ("healthy", "thin_only")
            and item["evidence"]["campus_lane"].get("source_id")),
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
    if handoff_file:
        write_browser_handoff(handoff_file, outcomes)
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
    parser.add_argument("--handoff-file", default=None,
                        help="写入本轮 unknown_spa 交接文件，供 P2 浏览器道即时消费")
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
        handoff_file=args.handoff_file,
    )


if __name__ == "__main__":
    main()
