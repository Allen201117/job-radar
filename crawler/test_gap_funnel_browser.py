import sys
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gap_funnel
import gap_funnel_browser as browser
import normalizer
import probe
from adapters.base import RawJob
from adapters.china_ats import CompanySpaAdapter
from adapters.playwright_base import InterceptFailure


NOW = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)


def _row(company="甲公司", state="wrong_platform"):
    return {
        "scope": "domestic",
        "company": company,
        "pattern": f"%{company}%",
        "industries": ["金融"],
        "state": state,
        "official_entry_url": f"https://jobs.example.com/{company}",
        "detected_platform": "unknown_spa",
    }


class BrowserQueueTest(unittest.TestCase):
    def test_only_unknown_spa_rows_enter_and_cap_is_applied(self):
        rows = [_row(f"公司{i}") for i in range(7)]
        rows.append({**_row("非SPA"), "detected_platform": "greenhouse"})
        rows.append(_row("人工态", state="manual_review"))
        rows.append(_row("无稳定JD", state="no_stable_jd"))
        queued = browser.plan_browser_queue(rows, cap=5, now=NOW)
        self.assertEqual(len(queued), 5)
        self.assertTrue(all(row["detected_platform"] == "unknown_spa" for row in queued))
        self.assertNotIn("人工态", [row["company"] for row in queued])
        self.assertNotIn("无稳定JD", [row["company"] for row in queued])

    def test_future_retry_survives_census_state_reset_to_unknown(self):
        row = {
            **_row("待重试", state="unknown"),
            "next_retry_at": "2026-08-10T00:00:00+00:00",
        }
        self.assertEqual(browser.plan_browser_queue([row], cap=5, now=NOW), [])

    def test_handoff_rows_are_prioritized_before_ledger_queue(self):
        handoff = _row("P1 新公司")
        handoff["next_retry_at"] = "2099-01-01T00:00:00+00:00"
        ledger = [_row("存量公司")]
        queue = browser.merge_browser_queues([handoff], ledger, cap=2, now=NOW)
        self.assertEqual([row["company"] for row in queue], ["P1 新公司", "存量公司"])

    def test_reads_handoff_file_and_falls_back_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            path.write_text(json.dumps({"companies": [_row("交接公司")]}), encoding="utf-8")
            self.assertEqual(browser.load_handoff_rows(path)[0]["company"], "交接公司")
            self.assertEqual(browser.load_handoff_rows(Path(directory) / "missing.json"), [])


class BrowserCompanyTest(unittest.TestCase):
    def test_company_spa_resolves_query_only_and_protocol_relative_job_urls(self):
        adapter = CompanySpaAdapter()
        adapter._origin = "https://jobs.example.com"
        adapter._source_url = "https://jobs.example.com/careers/list"
        self.assertEqual(
            adapter._resolve_url({"jobUrl": "?jobId=1"}, ""),
            "https://jobs.example.com/careers/list?jobId=1",
        )
        self.assertEqual(
            adapter._resolve_url({"jobUrl": "//ats.example.com/job/1"}, ""),
            "https://ats.example.com/job/1",
        )
        self.assertEqual(
            normalizer.validate_job_quality(
                RawJob(
                    company="甲公司",
                    title="工程师",
                    jd_url="https://jobs.example.com/careers/list?jobId=1",
                ),
                "https://jobs.example.com/careers/list",
            ),
            (True, ""),
        )

    def test_browser_jd_validator_rejects_third_party_before_launching_browser(self):
        self.assertFalse(
            browser.validate_jd_url_browser(
                "https://jobs.zhaopin.com/example/1",
                "工程师",
                "甲公司",
            )
        )

    def test_no_per_job_url_becomes_no_stable_jd_with_long_backoff(self):
        """拿不到逐岗 URL 是**我们自身**的抓取能力问题，不是对方门槛 → 长退避而非永不重试。

        钉死这条的原因：抓取能力会改进（2026-08-26 修掉「标准 ATS 租户被通用盲抓」后，
        万泰生物同一 URL 由 0 个岗变 15 个）。若钉成 next_retry_at=None，
        每次能力升级都救不回存量，队列只会单向缩小直到枯竭。
        对方门槛（anti_bot / login_wall）才该永不重试。
        """
        gate_calls = []
        result = browser.process_browser_company(
            _row(),
            supabase=object(),
            jobs_conn=object(),
            apply=True,
            now=NOW,
            prober=lambda _candidate: {
                "ok": False,
                "valid": 0,
                "reason": "没有真实逐岗 URL",
            },
            acceptance_gate=lambda *args, **kwargs: gate_calls.append((args, kwargs)),
        )
        self.assertEqual(result["state"], "no_stable_jd")
        self.assertIsNotNone(result["next_retry_at"])
        self.assertEqual(
            result["next_retry_at"],
            gap_funnel._after_spread(
                NOW, gap_funnel._NO_STABLE_JD_RETRY_DAYS, "甲公司"
            ),
        )
        self.assertEqual(gate_calls, [])
        self.assertTrue(result["evidence"]["manual_review"])

    def test_no_job_data_on_entry_is_not_reported_as_anti_bot(self):
        """入口页正常、只是这一页没有岗位数据 —— 台账必须如实写，不许沿用 anti_bot 字样。

        2026-09-04 台账里 21 家必投公司的 fail_reason 是
        `company_spa: anti_bot_blocked — 未拦截到任何岗位接口 JSON`，逐个核查后无一被反爬：
        漏斗停在「公司官网的招聘介绍页」上，那种页面本来就没有岗位数据。
        标签骗人的代价是排查方向整个错掉（巴斯夫、壳牌各空撞 30 次去研究怎么绕反爬）。
        """
        result = browser.process_browser_company(
            _row(),
            supabase=object(),
            jobs_conn=object(),
            apply=True,
            now=NOW,
            prober=lambda _c: {
                "ok": False,
                "valid": 0,
                "block_kind": "no_job_data_on_entry",
                "reason": "InterceptFailure: company_spa: no_job_data_on_entry — 入口页正常打开",
            },
            acceptance_gate=lambda *a, **k: self.fail("不该跑验收门"),
            fingerprinter=lambda *a, **k: self.fail("没有候选就不该跟跳"),
        )
        self.assertEqual(result["state"], "no_stable_jd")
        self.assertIn("no_job_data_on_entry", result["fail_reason"])
        self.assertNotIn("anti_bot", result["fail_reason"])

    def test_rendered_html_ats_hint_hands_back_to_p1_without_extra_requests(self):
        """渲染后直接认出的 ATS 优先于子域候选：零额外请求，且覆盖跨主域那半。"""
        result = browser.process_browser_company(
            _row(),
            supabase=object(),
            jobs_conn=object(),
            apply=True,
            now=NOW,
            prober=lambda _c: {
                "ok": False,
                "valid": 0,
                "block_kind": "no_job_data_on_entry",
                "ats_hint": {
                    "platform": "hotjob",
                    "adapter": "hotjob",
                    "source_url": "https://www.hotjob.cn/BASF/pb/social.html",
                    # 跨主域 → 只能靠「渲染后的页面自己核出公司名」过身份门
                    "identity_text": "甲公司 社会招聘",
                },
                "hops": ["https://careers.example.com/"],
                "reason": "InterceptFailure: company_spa: no_job_data_on_entry",
            },
            acceptance_gate=lambda *a, **k: self.fail("认出平台后应交回 P1"),
            fingerprinter=lambda *a, **k: self.fail("有 ats_hint 时不该再跟子域跳"),
        )
        self.assertEqual(result["state"], "platform_known")
        self.assertEqual(
            result["official_entry_url"], "https://www.hotjob.cn/BASF/pb/social.html"
        )
        self.assertEqual(result["detected_platform"], "hotjob")
        self.assertEqual(result["next_retry_at"], gap_funnel._iso(NOW))

    def test_follows_rendered_careers_hop_and_routes_a_known_ats(self):
        """跟到的下一跳认出真平台就换过去；feishu 属浏览器平台 → P2 自己接，不交回 P1。"""
        seen = []

        def fingerprinter(url, company=None):
            seen.append((url, company))
            return {
                "platform": "feishu",
                "adapter": "feishu",
                "source_url": "https://tenant.jobs.feishu.cn/index/position",
                "reason": "host_or_html_fingerprint",
                "identity_ok": True,
            }

        gate_calls = []

        def prober(candidate):
            if candidate["url"] == "https://tenant.jobs.feishu.cn/index/position":
                return {"ok": True, "valid": 7}
            return {
                "ok": False,
                "valid": 0,
                "block_kind": "no_job_data_on_entry",
                "hops": ["https://jobs.example.com/"],
                "reason": "InterceptFailure: company_spa: no_job_data_on_entry",
            }

        def gate(_entry, **kwargs):
            gate_calls.append(kwargs)
            return {"state": "healthy", "kept_source": True, "source_id": "s1",
                    "next_retry_at": None, "evidence": {}}

        result = browser.process_browser_company(
            _row(),
            supabase="sb",
            jobs_conn="conn",
            apply=True,
            now=NOW,
            prober=prober,
            acceptance_gate=gate,
            fingerprinter=fingerprinter,
        )
        self.assertEqual(seen, [("https://jobs.example.com/", "甲公司")])
        self.assertEqual(result["state"], "healthy")
        self.assertEqual(gate_calls[0]["adapter"], "feishu")
        self.assertEqual(
            gate_calls[0]["source_url"], "https://tenant.jobs.feishu.cn/index/position"
        )
        # 认出的平台落进 evidence.fingerprint.real_*：下一轮 resolve_browser_adapter 直接短路
        self.assertEqual(result["evidence"]["fingerprint"]["real_adapter"], "feishu")

    def test_reprobes_unknown_spa_hop_and_accepts_it_as_the_real_entry(self):
        """下一跳仍认不出平台，但浏览器在那儿真拿到了岗位 → 用它当入口继续走验收门。"""
        gate_calls = []

        def prober(candidate):
            if candidate["url"] == "https://careers.example.com/":
                return {"ok": True, "valid": 12}
            return {
                "ok": False,
                "valid": 0,
                "block_kind": "no_job_data_on_entry",
                "hops": ["https://careers.example.com/"],
                "reason": "InterceptFailure: company_spa: no_job_data_on_entry",
            }

        def gate(entry, **kwargs):
            gate_calls.append(kwargs)
            return {"state": "healthy", "kept_source": True, "source_id": "s1",
                    "next_retry_at": None, "evidence": {}}

        result = browser.process_browser_company(
            _row(),
            supabase="sb",
            jobs_conn="conn",
            apply=True,
            now=NOW,
            prober=prober,
            acceptance_gate=gate,
            fingerprinter=lambda *a, **k: {
                "platform": "unknown_spa", "adapter": None, "reason": "unknown_spa",
            },
        )
        self.assertEqual(result["state"], "healthy")
        self.assertEqual(gate_calls[0]["source_url"], "https://careers.example.com/")
        self.assertEqual(result["official_entry_url"], "https://careers.example.com/")

    def test_hop_following_is_capped_and_skips_the_current_entry(self):
        tried = []
        result = browser.process_browser_company(
            _row(),
            supabase=object(),
            jobs_conn=object(),
            apply=True,
            now=NOW,
            prober=lambda _c: {
                "ok": False,
                "valid": 0,
                "block_kind": "no_job_data_on_entry",
                # 第一项就是当前入口本身，不该被当成「下一跳」白跑一次
                "hops": ["https://jobs.example.com/甲公司",
                         "https://a.example.com/", "https://b.example.com/",
                         "https://c.example.com/"],
                "reason": "no_job_data_on_entry",
            },
            acceptance_gate=lambda *a, **k: self.fail("不该跑验收门"),
            fingerprinter=lambda url, company=None: tried.append(url) or {
                "platform": "wrong_platform_x", "adapter": None, "reason": "unrecognized",
            },
        )
        self.assertEqual(tried, ["https://a.example.com/", "https://b.example.com/"])
        self.assertEqual(result["state"], "no_stable_jd")

    def test_anti_bot_probe_result_does_not_trigger_hop_following(self):
        """真被拒的不跟跳：那不是「站错了页」，跟跳只是白烧一轮浏览器。"""
        result = browser.process_browser_company(
            _row(),
            supabase=object(),
            jobs_conn=object(),
            apply=True,
            now=NOW,
            prober=lambda _c: {
                "ok": False, "valid": 0, "block_kind": "anti_bot",
                "hops": ["https://jobs.example.com/x"],
                "reason": "InterceptFailure: company_spa: anti_bot_blocked — 对方拒绝访问（HTTP 403）",
            },
            acceptance_gate=lambda *a, **k: self.fail("不该跑验收门"),
            fingerprinter=lambda *a, **k: self.fail("被拒时不该跟跳"),
        )
        self.assertEqual(result["state"], "no_stable_jd")
        self.assertIn("anti_bot_blocked", result["fail_reason"])

    def test_browser_lane_calls_the_shared_acceptance_gate(self):
        gate_calls = []

        def shared_gate(entry, **kwargs):
            gate_calls.append((entry, kwargs))
            return {
                "state": "healthy",
                "kept_source": True,
                "source_id": "source-browser",
                "next_retry_at": None,
                "evidence": {},
            }

        result = browser.process_browser_company(
            _row(),
            supabase="sb",
            jobs_conn="conn",
            apply=True,
            now=NOW,
            prober=lambda _candidate: {"ok": True, "valid": 2},
            acceptance_gate=shared_gate,
        )
        self.assertEqual(result["state"], "healthy")
        self.assertEqual(len(gate_calls), 1)
        _entry, kwargs = gate_calls[0]
        self.assertEqual(kwargs["adapter"], "company_spa")
        self.assertEqual(kwargs["crawl_method"], "playwright")
        self.assertFalse(kwargs["enable_thin"])

    def test_dry_run_delegates_to_shared_gate_without_local_writes(self):
        calls = []

        def shared_gate(_entry, **kwargs):
            calls.append(kwargs)
            return {
                "state": "dry_run",
                "kept_source": False,
                "source_id": None,
                "next_retry_at": None,
                "evidence": {},
            }

        result = browser.process_browser_company(
            _row(),
            supabase=object(),
            jobs_conn=object(),
            apply=False,
            now=NOW,
            prober=lambda _candidate: {"ok": True, "valid": 1},
            acceptance_gate=shared_gate,
        )
        self.assertEqual(result["state"], "platform_known")
        self.assertFalse(calls[0]["apply"])

    def test_round_dry_run_never_writes_attempts_or_ops_runs(self):
        row = _row()
        with mock.patch.object(
            browser.gap_census,
            "census",
            return_value={"rows": [row], "queue": [], "industry_coverage": {}},
        ), mock.patch.object(
            browser,
            "process_browser_company",
            return_value={
                "state": "platform_known",
                "official_entry_url": row["official_entry_url"],
                "detected_platform": "unknown_spa",
                "next_retry_at": None,
                "evidence": {},
            },
        ), mock.patch.object(
            browser.gap_funnel, "_write_attempt"
        ) as write_attempt, mock.patch.object(
            browser.ops_runs, "record_ops_run"
        ) as record_ops:
            result = browser.run_round(
                supabase=object(),
                jobs_conn=object(),
                apply=False,
                limit=5,
                now=NOW,
            )
        self.assertEqual(result["metrics"]["processed"], 1)
        write_attempt.assert_not_called()
        record_ops.assert_not_called()


class RecognizedAtsIdentityGateTest(unittest.TestCase):
    """认出的 ATS 能不能用，两条实证放行路各守一半（2026-09-05 逐家 live 实测）。

    · 宝洁 careers.pg.com.cn → app.mokahr.com/social-recruitment/pg/91934 是**跨主域**，
      httpx 只拿得到 moka 壳、核不出「宝洁」→ 只能靠「渲染后的页面自己核出公司名」。
    · 埃斯顿 estun1.zhiye.com **渲染后也核不出**「埃斯顿」三个字 → 只能靠
      「P1 已核过入口页身份 + 候选同主域」。
    ⚠️「同主域」那半不能省：入口页身份只为**这个域名**背书，不能替页面上任意一条
      第三方 ATS 链接背书。
    """

    def _run(self, row, ats_hint, prober_ok=True):
        gate_calls = []

        def prober(candidate):
            # 按 adapter 分流，不按 URL —— 换 adapter 后 URL 可能**和入口完全相同**
            # （广汽就是：company_spa 在 gacrnd.zhiye.com 上 0 个岗，beisen 在同一 URL 上 225 个）。
            if candidate["adapter"] == "company_spa":
                return {
                    "ok": False, "valid": 0,
                    "ats_hint": dict(ats_hint),
                    "reason": "company_spa 拼不出逐岗 URL",
                }
            return {"ok": prober_ok, "valid": 42 if prober_ok else 0}

        def gate(_entry, **kwargs):
            gate_calls.append(kwargs)
            return {"state": "healthy", "kept_source": True, "source_id": "s1",
                    "next_retry_at": None, "evidence": {}}

        result = browser.process_browser_company(
            row, supabase="sb", jobs_conn="conn", apply=True, now=NOW,
            prober=prober, acceptance_gate=gate,
            fingerprinter=lambda *a, **k: self.fail("本用例不该跟子域跳"),
        )
        return result, gate_calls

    def test_cross_domain_ats_passes_on_rendered_company_name(self):
        row = {**_row("宝洁"), "official_entry_url": "https://careers.pg.com.cn/"}
        result, gate_calls = self._run(row, {
            "platform": "moka", "adapter": "moka",
            "source_url": "https://app.mokahr.com/social-recruitment/pg/91934",
            "identity_text": "宝洁公司 社会招聘 在招职位",
        })
        self.assertEqual(result["state"], "healthy")
        self.assertEqual(gate_calls[0]["adapter"], "moka")

    def test_swap_fires_without_any_exception(self):
        """触发条件不能只看 block_kind：广汽/埃斯顿/华虹三家 fetch 成功、parse 0 个岗，
        压根不抛异常（block_kind 是 None），只看异常就永远换不了 adapter。"""
        row = {
            **_row("广汽"),
            "official_entry_url": "https://gacrnd.zhiye.com/social/jobs",
            "evidence": {"fingerprint": {"identity_ok": True}},
        }
        result, gate_calls = self._run(row, {
            "platform": "beisen", "adapter": "beisen",
            "source_url": "https://gacrnd.zhiye.com/social/jobs",
            "identity_text": "广汽研究院 社会招聘",
        })
        self.assertEqual(result["state"], "healthy")
        self.assertEqual(gate_calls[0]["adapter"], "beisen")

    def test_lucky_partial_hit_by_company_spa_does_not_short_circuit(self):
        """宝洁实录：company_spa 侥幸解析出 1 个岗 → 探活「成功」→ 源被 enable、1 个岗入库，
        而真身是 moka 租户 pg/91934、实测 42 个。company_spa 是通用盲抓兜底不是真 adapter，
        它「成功」也不算数。"""
        row = {**_row("宝洁"), "official_entry_url": "https://careers.pg.com.cn/cn/zh/"}
        gate_calls = []

        def prober(candidate):
            if candidate["adapter"] == "company_spa":
                return {"ok": True, "valid": 1, "sample": "https://recruit.pg.com.cn/x",
                        "ats_hint": {"platform": "moka", "adapter": "moka",
                                     "source_url": "https://app.mokahr.com/social-recruitment/pg/91934",
                                     "identity_text": "宝洁公司 社会招聘"}}
            return {"ok": True, "valid": 42}

        def gate(_entry, **kwargs):
            gate_calls.append(kwargs)
            return {"state": "healthy", "kept_source": True, "source_id": "s1",
                    "next_retry_at": None, "evidence": {}}

        result = browser.process_browser_company(
            row, supabase="sb", jobs_conn="conn", apply=True, now=NOW,
            prober=prober, acceptance_gate=gate,
            fingerprinter=lambda *a, **k: self.fail("有 ats_hint 时不该跟子域跳"))
        self.assertEqual(result["state"], "healthy")
        self.assertEqual(gate_calls[0]["adapter"], "moka")
        self.assertEqual(
            gate_calls[0]["source_url"],
            "https://app.mokahr.com/social-recruitment/pg/91934")

    def test_swap_is_a_measurement_not_a_gamble(self):
        """认出的真平台探出来更少 → 保留 company_spa 已确认的产出，绝不倒退。"""
        row = {**_row("某公司"), "official_entry_url": "https://careers.example.com/"}
        gate_calls = []

        def prober(candidate):
            if candidate["adapter"] == "company_spa":
                return {"ok": True, "valid": 9,
                        "ats_hint": {"platform": "moka", "adapter": "moka",
                                     "source_url": "https://app.mokahr.com/x/1",
                                     "identity_text": "某公司 招聘"}}
            return {"ok": True, "valid": 2}   # 真 adapter 反而更少

        def gate(_entry, **kwargs):
            gate_calls.append(kwargs)
            return {"state": "healthy", "kept_source": True, "source_id": "s1",
                    "next_retry_at": None, "evidence": {}}

        result = browser.process_browser_company(
            row, supabase="sb", jobs_conn="conn", apply=True, now=NOW,
            prober=prober, acceptance_gate=gate,
            fingerprinter=lambda *a, **k: {"platform": "unknown", "adapter": None})
        self.assertEqual(result["state"], "healthy")
        self.assertEqual(gate_calls[0]["adapter"], "company_spa")
        self.assertEqual(gate_calls[0]["source_url"], "https://careers.example.com/")

    def test_a_working_real_adapter_is_never_second_guessed(self):
        """已经用着真 adapter 且探活成功 → 维持现状，不多花一次浏览器复探。"""
        row = {
            **_row("丁公司"),
            "official_entry_url": "https://tenant.mokahr.com/x",
            "evidence": {"fingerprint": {"real_adapter": "moka",
                                         "real_source_url": "https://tenant.mokahr.com/x"}},
        }
        calls = []

        def prober(candidate):
            calls.append(candidate["adapter"])
            return {"ok": True, "valid": 5,
                    "ats_hint": {"platform": "beisen", "adapter": "beisen",
                                 "source_url": "https://x.zhiye.com/social",
                                 "identity_text": "丁公司"}}

        browser.process_browser_company(
            row, supabase="sb", jobs_conn="conn", apply=True, now=NOW,
            prober=prober,
            acceptance_gate=lambda *a, **k: {
                "state": "healthy", "kept_source": True, "source_id": "s",
                "next_retry_at": None, "evidence": {}},
            fingerprinter=lambda *a, **k: self.fail("不该跟跳"))
        self.assertEqual(calls, ["moka"])   # 只探了一次，没被 ats_hint 折腾

    def test_anti_bot_never_triggers_an_adapter_swap(self):
        row = {**_row("某公司"), "evidence": {"fingerprint": {"identity_ok": True}}}

        def prober(_candidate):
            return {"ok": False, "valid": 0, "block_kind": "anti_bot",
                    "ats_hint": {"platform": "moka", "adapter": "moka",
                                 "source_url": "https://app.mokahr.com/x/1"},
                    "reason": "anti_bot_blocked"}

        result = browser.process_browser_company(
            row, supabase=object(), jobs_conn=object(), apply=True, now=NOW,
            prober=prober,
            acceptance_gate=lambda *a, **k: self.fail("被拒时不该换 adapter 重抓"),
            fingerprinter=lambda *a, **k: self.fail("被拒时不该跟跳"),
        )
        self.assertEqual(result["state"], "no_stable_jd")

    def test_cross_domain_ats_without_any_identity_is_rejected(self):
        row = {**_row("宝洁"), "official_entry_url": "https://careers.pg.com.cn/"}
        result, gate_calls = self._run(row, {
            "platform": "moka", "adapter": "moka",
            "source_url": "https://app.mokahr.com/social-recruitment/pg/91934",
            "identity_text": "登录 注册 职位搜索",
        })
        self.assertEqual(result["state"], "no_stable_jd")
        self.assertEqual(gate_calls, [])
        step = result["evidence"]["entry_hops"][0]
        self.assertFalse(step["trusted"])
        self.assertEqual(step["identity"], "identity_unverified")

    def test_same_domain_candidate_rides_on_the_entry_page_identity(self):
        row = {
            **_row("埃斯顿"),
            "official_entry_url": "https://estun1.zhiye.com/",
            "evidence": {"fingerprint": {"identity_ok": True}},
        }
        result, gate_calls = self._run(row, {
            "platform": "beisen", "adapter": "beisen",
            "source_url": "https://estun1.zhiye.com/campus/jobs",
            "identity_text": "招聘 职位列表",  # 渲染后也核不出「埃斯顿」
        })
        self.assertEqual(result["state"], "healthy")
        self.assertEqual(gate_calls[0]["adapter"], "beisen")

    def test_entry_identity_does_not_vouch_for_a_third_party_domain(self):
        """入口页核过 ≠ 页面上任意第三方 ATS 链接也算核过。"""
        row = {
            **_row("某公司"),
            "official_entry_url": "https://www.example.com/careers",
            "evidence": {"fingerprint": {"identity_ok": True}},
        }
        result, _gate_calls = self._run(row, {
            "platform": "moka", "adapter": "moka",
            "source_url": "https://app.mokahr.com/social-recruitment/other/1",
            "identity_text": "招聘",
        })
        self.assertEqual(result["state"], "no_stable_jd")

    def test_identity_text_never_reaches_the_ledger(self):
        """身份素材只在内存流转：probe_result 整份会被写进 evidence，不摘掉就泄进台账。"""
        row = {**_row("宝洁"), "official_entry_url": "https://careers.pg.com.cn/"}
        result, _ = self._run(row, {
            "platform": "moka", "adapter": "moka",
            "source_url": "https://app.mokahr.com/social-recruitment/pg/91934",
            "identity_text": "宝洁公司 社会招聘 " + "语料" * 500,
        })
        self.assertNotIn("语料", json.dumps(result["evidence"], ensure_ascii=False))


class ProbeBlockKindPassthroughTest(unittest.TestCase):
    """adapter 判过的因必须原样传到调用方；让调用方对着 reason 字符串猜就是老毛病的来源。"""

    def _probe_with(self, error):
        class _Boom:
            def fetch(self, _url):
                raise error

            def parse(self, _html):  # pragma: no cover - fetch 先抛
                return []

        with mock.patch.dict(probe.ADAPTERS, {"company_spa": _Boom()}, clear=False):
            return probe.probe_one({
                "company": "甲公司",
                "adapter": "company_spa",
                "url": "https://www.acme.com/careers",
            })

    def test_surfaces_entry_hint_when_nothing_parsed(self):
        """比异常那条更常见的一类：fetch 成功、parse 出 0 个岗，**不抛异常**。
        2026-09-05 live 实测广汽/埃斯顿/华虹三家 company_spa 全是这样；只看异常就永远认不出它们。
        """
        class _Empty:
            entry_hint = None

            def fetch(self, _url):
                # 真实的 PlaywrightAdapter.fetch 就是在这一步从渲染后的页面认出平台的
                self.entry_hint = {"platform": "beisen", "adapter": "beisen",
                                   "source_url": "https://gacrnd.zhiye.com/social/jobs"}
                return "{}"

            def parse(self, _html):
                return []

        with mock.patch.dict(probe.ADAPTERS, {"company_spa": _Empty()}, clear=False):
            result = probe.probe_one({
                "company": "广汽", "adapter": "company_spa",
                "url": "https://gacrnd.zhiye.com/social/jobs",
            })
        self.assertEqual(result["valid"], 0)
        self.assertIsNone(result.get("block_kind"))
        self.assertEqual(result["ats_hint"]["adapter"], "beisen")

    def test_stale_entry_hint_never_leaks_to_the_next_company(self):
        """ADAPTERS 是共享单例：上一家认出的平台留在实例上就会安到下一家头上。"""
        class _Stale:
            entry_hint = {"platform": "moka", "adapter": "moka",
                          "source_url": "https://app.mokahr.com/x/1"}

            def fetch(self, _url):
                return "{}"      # 本次没认出任何平台，也没重置 —— 全靠 probe_one 那道保险

            def parse(self, _html):
                return []

        with mock.patch.dict(probe.ADAPTERS, {"company_spa": _Stale()}, clear=False):
            result = probe.probe_one({
                "company": "乙公司", "adapter": "company_spa",
                "url": "https://www.other.com/careers",
            })
        self.assertNotIn("ats_hint", result)

    def test_entry_hint_is_surfaced_even_when_jobs_were_found(self):
        """探活「成功」也要把认出的平台交出去 —— 换不换由调用方按 valid 多少决定。

        曾经只在 valid==0 时才带，漏掉了更坏的一种：宝洁 company_spa 侥幸解析出 1 个岗 →
        探活成功 → 源被 enable、1 个岗入库，而真身 moka 租户有 42 个。
        「抓到了一点点」比「一个都没抓到」更危险：绿灯、有源、北极星算它有货，没有告警会响。
        """
        class _Works:
            entry_hint = None

            def fetch(self, _url):
                self.entry_hint = {"platform": "moka", "adapter": "moka",
                                   "source_url": "https://app.mokahr.com/x/1"}
                return "{}"

            def parse(self, _html):
                return [RawJob(company="丙公司", title="工程师",
                               jd_url="https://recruit.example.com/job/1",
                               location="上海")]

        with mock.patch.dict(probe.ADAPTERS, {"company_spa": _Works()}, clear=False):
            result = probe.probe_one({
                "company": "丙公司", "adapter": "company_spa",
                "url": "https://recruit.example.com/list",
            })
        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["ats_hint"]["adapter"], "moka")

    def test_surfaces_kind_and_hops(self):
        result = self._probe_with(InterceptFailure(
            "company_spa: no_job_data_on_entry — 入口页正常打开",
            block_kind="no_job_data_on_entry",
            hops=["https://jobs.acme.com/"],
        ))
        self.assertFalse(result["ok"])
        self.assertEqual(result["block_kind"], "no_job_data_on_entry")
        self.assertEqual(result["hops"], ["https://jobs.acme.com/"])

    def test_plain_errors_keep_the_old_shape(self):
        result = self._probe_with(RuntimeError("boom"))
        self.assertNotIn("block_kind", result)
        self.assertNotIn("hops", result)
        self.assertEqual(result["reason"], "RuntimeError: boom")


class ResolveBrowserAdapterTest(unittest.TestCase):
    """P1 认出的平台必须传到 P2，否则标准 ATS 租户会被通用盲抓打成 no_stable_jd。

    2026-08-26 实测万泰生物同一个 URL：company_spa 抓 0 个岗，moka adapter 抓 15 个
    带完整逐岗 jd_url 的岗。
    """

    def test_uses_real_adapter_and_its_source_url(self):
        row = {"evidence": {"fingerprint": {
            "real_adapter": "moka",
            "real_source_url": "https://app.mokahr.com/social-recruitment/ystwt/97880",
        }}}
        self.assertEqual(
            browser.resolve_browser_adapter(row, "https://entry.example/jobs"),
            ("moka", "https://app.mokahr.com/social-recruitment/ystwt/97880"),
        )

    def test_falls_back_to_company_spa(self):
        """真认不出、老数据没这个字段、adapter 不在浏览器白名单 —— 都回落通用盲抓。"""
        for row in (
            {"evidence": {"fingerprint": {"real_adapter": None}}},
            {"evidence": {}},
            {},
            {"evidence": {"fingerprint": {"real_adapter": "workday"}}},
        ):
            with self.subTest(row=row):
                self.assertEqual(
                    browser.resolve_browser_adapter(row, "https://x.example/jobs"),
                    ("company_spa", "https://x.example/jobs"),
                )

    def test_real_adapter_without_source_url_keeps_entry(self):
        row = {"evidence": {"fingerprint": {"real_adapter": "beisen"}}}
        self.assertEqual(
            browser.resolve_browser_adapter(row, "https://gacrnd.zhiye.com"),
            ("beisen", "https://gacrnd.zhiye.com"),
        )


class ForceRerunTest(unittest.TestCase):
    """人工点名（--company）必须绕过退避，否则修好 bug 也验证不了。

    死锁实录（2026-08-26）：万泰生物因「P2 拿不到真实 adapter」被打成 no_stable_jd
    → 退避 45 天 → 修好该 bug 后想立刻验证，--company 却因退避跑不动 →
    而 real_adapter 恰恰只有重跑才会写入 → 互相锁死。
    """

    def test_backoff_blocks_by_default_but_not_when_named(self):
        future = datetime(2031, 1, 1, tzinfo=timezone.utc).isoformat()
        rows = [{
            "company": "万泰生物",
            "detected_platform": "unknown_spa",
            "official_entry_url": "https://app.mokahr.com/social-recruitment/ystwt/97880",
            "state": "no_stable_jd",
            "next_retry_at": future,
        }]
        self.assertEqual(browser.plan_browser_queue(rows, cap=5, now=NOW), [])
        forced = browser.plan_browser_queue(
            rows, cap=5, now=NOW, ignore_backoff=True
        )
        self.assertEqual([row["company"] for row in forced], ["万泰生物"])


class ThinRescueTest(unittest.TestCase):
    """薄卡救济：抽样证明正文取得到才放行，质量红线不放松。

    背景（2026-08-26 live）：moka 列表接口天生不返回正文，库里 2.6 万张 moka 卡
    全靠每晚逐岗渲染 backfill 补。验收门要求「当场就有健康岗」→ 任何 moka 租户
    都永远进不来。万泰生物实测：列表 15 个岗全是薄卡，但逐岗渲染 3/3 都补出了
    390-890 字的真实岗位职责。
    """

    _SAMPLES = [{"jd_url": "u1"}, {"jd_url": "u2"}, {"jd_url": "u3"}]

    def test_non_whitelisted_adapter_gets_no_rescue(self):
        """非白名单平台完全不救济——行为与改动前一致。"""
        self.assertIsNone(browser.make_thin_rescue("company_spa"))
        self.assertIsNone(browser.make_thin_rescue("beisen"))

    def test_passes_when_summaries_are_recoverable(self):
        rescue = browser.make_thin_rescue("moka", scraper=lambda _u: "正" * 80)
        self.assertTrue(rescue(self._SAMPLES))

    def test_rejects_when_summaries_are_not_recoverable(self):
        for scraper in (lambda _u: "短", lambda _u: "", lambda _u: None):
            with self.subTest(scraper=scraper):
                rescue = browser.make_thin_rescue("moka", scraper=scraper)
                self.assertFalse(rescue(self._SAMPLES))

    def test_one_of_three_is_not_enough(self):
        rescue = browser.make_thin_rescue(
            "moka", scraper=lambda u: "正" * 80 if u == "u1" else ""
        )
        self.assertFalse(rescue(self._SAMPLES))

    def test_too_few_samples_rejected(self):
        rescue = browser.make_thin_rescue("moka", scraper=lambda _u: "正" * 80)
        self.assertFalse(rescue([{"jd_url": "u1"}]))
        self.assertFalse(rescue([]))


if __name__ == "__main__":
    unittest.main()
