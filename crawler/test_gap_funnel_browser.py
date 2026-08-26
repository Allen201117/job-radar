import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gap_funnel
import gap_funnel_browser as browser
import normalizer
from adapters.base import RawJob
from adapters.china_ats import CompanySpaAdapter


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
            gap_funnel._after(NOW, gap_funnel._NO_STABLE_JD_RETRY_DAYS),
        )
        self.assertEqual(gate_calls, [])
        self.assertTrue(result["evidence"]["manual_review"])

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


if __name__ == "__main__":
    unittest.main()
