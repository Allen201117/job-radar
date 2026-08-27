"""ops_watchdog 判据单测：只测纯函数，不打网络。

重点测「什么情况**不该**告警」——告警系统真正的失败模式是噪音太大，
被当成狼来了以后，真出事那次也没人看。
"""
import contextlib
import io
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ops_watchdog as W


NOW = datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc)
TODAY = "2026-08-27"


def _run(module, day, status="success", **metrics):
    return {"module": module, "run_date": day, "status": status, "metrics": metrics}


class AccountErrorTest(unittest.TestCase):
    def test_402_is_account_level(self):
        # 这条是整个规则 D 的由来：欠费返 402，旧判据只认 401/403 → 静默烧了两天额度。
        self.assertTrue(W.is_account_level_error(402))

    def test_401_and_403_still_account_level(self):
        self.assertTrue(W.is_account_level_error(401))
        self.assertTrue(W.is_account_level_error(403))

    def test_429_only_counts_when_body_names_quota(self):
        self.assertFalse(W.is_account_level_error(429, "System is too busy now"))
        self.assertTrue(W.is_account_level_error(429, "quota exceeded"))
        self.assertTrue(W.is_account_level_error(429, "insufficient credits"))

    def test_balance_text_without_status(self):
        self.assertTrue(W.is_account_level_error(200, "Error: balance is insufficient"))
        self.assertTrue(W.is_account_level_error(0, "账户余额不足"))

    def test_plain_failures_are_not_account_level(self):
        self.assertFalse(W.is_account_level_error(500, "internal error"))
        self.assertFalse(W.is_account_level_error(None, ""))


class CronParsingTest(unittest.TestCase):
    def test_daily(self):
        self.assertEqual(W.cron_max_gap_minutes("30 3 * * *"), 1440)

    def test_weekly(self):
        self.assertEqual(W.cron_max_gap_minutes("30 5 * * 1"), 7 * 1440)

    def test_every_three_hours(self):
        self.assertEqual(W.cron_max_gap_minutes("0 */3 * * *"), 180)

    def test_uneven_hour_list_uses_max_gap_not_average(self):
        # 1,7,13,17 的平均间隔 6h、真实最大 8h。用平均会把正常的 8h 空档判成超期。
        self.assertEqual(W.cron_max_gap_minutes("0 1,7,13,17 * * *"), 480)

    def test_unparseable(self):
        self.assertIsNone(W.cron_max_gap_minutes("bogus"))
        self.assertIsNone(W.cron_max_gap_minutes("0 3 1 * *"))   # 按月日触发的不猜


class WorkflowMetaTest(unittest.TestCase):
    SAMPLE = """name: sample

on:
  schedule:
    - cron: "0 22 * * *"   # 每日 UTC 22:00
  #   - cron: "15 22 * * *"   # 这条是被注释停掉的，不算声明
  workflow_dispatch:

jobs:
  audit:
    runs-on: ubuntu-latest
    timeout-minutes: 150
    steps:
      - name: run
        timeout-minutes: 20
        run: echo hi
  smoke:
    name: Smoke check
    timeout-minutes: 45
    steps:
      - run: echo hi
"""

    def setUp(self):
        self.meta = W.parse_workflow_meta(self.SAMPLE)

    def test_commented_cron_is_not_a_declaration(self):
        # 本仓库 6 个 LLM workflow 就是靠注释 cron 停掉的；当成「该跑没跑」会天天误报。
        self.assertEqual(self.meta["crons"], ["0 22 * * *"])
        self.assertEqual(self.meta["max_gap_minutes"], 1440)

    def test_step_level_timeout_is_not_job_level(self):
        self.assertEqual(W.timeout_for_job(self.meta, "audit"), 150)
        self.assertEqual(self.meta["max_timeout"], 150)

    def test_matrix_job_name_maps_back_to_declared_timeout(self):
        self.assertEqual(W.timeout_for_job(self.meta, "audit (3/6)"), 150)

    def test_job_display_name_lookup(self):
        self.assertEqual(W.timeout_for_job(self.meta, "Smoke check"), 45)

    def test_unknown_job_falls_back_to_file_max(self):
        self.assertEqual(W.timeout_for_job(self.meta, "who-am-i"), 150)


class ZeroOutputTest(unittest.TestCase):
    def test_two_days_of_work_with_no_output_alerts(self):
        rows = [_run("auto_discover", "2026-08-25", checked=80, produced=0),
                _run("auto_discover", "2026-08-26", checked=80, produced=0)]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual([f["subject"] for f in findings], ["auto_discover"])
        self.assertEqual(findings[0]["rule"], "A")

    def test_empty_queue_is_not_an_alert(self):
        # 队列空了产出 0 是正常的。把它算成故障 = 每天都在喊狼来了。
        rows = [_run("campus_cycle_backlog", "2026-08-25", companies_processed=0, verified=0),
                _run("campus_cycle_backlog", "2026-08-26", companies_processed=0, verified=0)]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(findings, [])

    def test_all_runs_failed_counts_as_zero_output(self):
        rows = [_run("gap_funnel", "2026-08-25", "failed", processed=20, sources_added=0),
                _run("gap_funnel", "2026-08-26", "failed", processed=20, sources_added=0)]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual([f["subject"] for f in findings], ["gap_funnel"])

    def test_one_bad_day_is_not_enough(self):
        rows = [_run("auto_discover", "2026-08-25", checked=80, produced=3),
                _run("auto_discover", "2026-08-26", checked=80, produced=0)]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(findings, [])

    def test_today_is_excluded_from_the_window(self):
        # watchdog 跑在 UTC 01:00，当天大多数任务还没跑；拿半天数据当一整天判会误报。
        rows = [_run("auto_discover", "2026-08-25", checked=80, produced=5),
                _run("auto_discover", "2026-08-26", checked=80, produced=5),
                _run("auto_discover", TODAY, checked=80, produced=0)]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(findings, [])

    def test_missing_day_breaks_the_streak(self):
        # 「那天压根没跑」是规则 E 的事，不该在这里再告一遍。
        rows = [_run("auto_discover", "2026-08-26", checked=80, produced=0)]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(findings, [])

    def test_unknown_module_is_reported_not_guessed(self):
        rows = [_run("brand_new_module", "2026-08-25", whatever=0),
                _run("brand_new_module", "2026-08-26", whatever=0)]
        findings, skipped = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(findings, [])
        self.assertIn("brand_new_module", skipped)

    def test_muted_module_is_silent(self):
        rows = [_run("auto_discover", "2026-08-25", checked=80, produced=0),
                _run("auto_discover", "2026-08-26", checked=80, produced=0)]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2, muted=["auto_discover"])
        self.assertEqual(findings, [])


class TimeoutKillTest(unittest.TestCase):
    META = {".github/workflows/x.yml": W.parse_workflow_meta(
        "jobs:\n  audit:\n    timeout-minutes: 100\n")}

    def _run_row(self, run_id, conclusion="cancelled"):
        return {"id": run_id, "path": ".github/workflows/x.yml",
                "conclusion": conclusion, "created_at": "2026-08-26T22:00:00Z", "run_number": run_id}

    def _job(self, minutes, conclusion="cancelled"):
        start = datetime(2026, 8, 26, 22, 0, tzinfo=timezone.utc)
        return {"name": "audit", "conclusion": conclusion,
                "started_at": start.isoformat(),
                "completed_at": (start + timedelta(minutes=minutes)).isoformat()}

    def test_job_level_kill_is_caught_even_when_run_looks_fine(self):
        # run 级会骗人：dead-link-audit 有过 run 级 cancelled、job 级 success/cancelled 混着的实例。
        runs = [self._run_row(1, conclusion="success")]
        findings = W.evaluate_timeout_kills(runs, {1: [self._job(98), self._job(3, "success")]}, self.META)
        self.assertEqual(len(findings), 1)
        self.assertIn("撞到声明的 timeout", findings[0]["summary"])

    def test_single_early_cancel_is_probably_a_human(self):
        runs = [self._run_row(1)]
        findings = W.evaluate_timeout_kills(runs, {1: [self._job(10)]}, self.META)
        self.assertEqual(findings, [])

    def test_repeated_early_kills_still_alert(self):
        # 实测 dead-link-audit 每晚在第 90 分钟被杀、声明 timeout 却是 150 分钟——
        # 只按「撞 timeout」判，这件天天发生的事永远告不出来。
        runs = [self._run_row(1), self._run_row(2)]
        findings = W.evaluate_timeout_kills(
            runs, {1: [self._job(60)], 2: [self._job(60)]}, self.META)
        self.assertEqual(len(findings), 1)
        self.assertIn("另有原因", findings[0]["summary"])

    def test_successful_jobs_never_alert(self):
        runs = [self._run_row(1, "success"), self._run_row(2, "success")]
        findings = W.evaluate_timeout_kills(
            runs, {1: [self._job(99, "success")], 2: [self._job(99, "success")]}, self.META)
        self.assertEqual(findings, [])


class StuckLedgerTest(unittest.TestCase):
    def test_old_queued_rows_alert(self):
        rows = [{"status": "queued", "mode": "insight_enrich",
                 "created_at": (NOW - timedelta(days=52)).isoformat(), "company": "某公司"}]
        findings = W.evaluate_stuck_ledger(rows, now=NOW, hours=6)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "C")
        self.assertIn("52 天", findings[0]["summary"])

    def test_fresh_queued_rows_are_fine(self):
        rows = [{"status": "queued", "mode": "insight_enrich",
                 "created_at": (NOW - timedelta(hours=1)).isoformat()}]
        self.assertEqual(W.evaluate_stuck_ledger(rows, now=NOW, hours=6), [])

    def test_finished_rows_ignored(self):
        rows = [{"status": "success", "mode": "insight_enrich",
                 "created_at": (NOW - timedelta(days=9)).isoformat()}]
        self.assertEqual(W.evaluate_stuck_ledger(rows, now=NOW, hours=6), [])


class AccountErrorScanTest(unittest.TestCase):
    def test_events_with_account_error_code_alert(self):
        events = [{"event": "resume_parse_fallback_rule",
                   "created_at": (NOW - timedelta(hours=3)).isoformat(),
                   "payload": {"diagnostics": {"error_code": "llm_insufficient_balance"}}}]
        findings = W.evaluate_account_errors(events, [], now=NOW)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["subject"], "llm_insufficient_balance")

    def test_rate_limit_alone_is_not_account_level(self):
        events = [{"event": "resume_parse_fallback_rule",
                   "created_at": (NOW - timedelta(hours=3)).isoformat(),
                   "payload": {"diagnostics": {"error_code": "llm_rate_limited"}}}]
        self.assertEqual(W.evaluate_account_errors(events, [], now=NOW), [])

    def test_old_events_are_out_of_window(self):
        events = [{"event": "resume_parse_fallback_rule",
                   "created_at": (NOW - timedelta(days=9)).isoformat(),
                   "payload": {"diagnostics": {"error_code": "llm_auth_error"}}}]
        self.assertEqual(W.evaluate_account_errors(events, [], now=NOW), [])

    def test_ops_runs_account_error_flag(self):
        rows = [{"module": "insight_backlog", "run_date": "2026-08-26",
                 "metrics": {"llm_account_error": True}}]
        findings = W.evaluate_account_errors([], rows, now=NOW)
        self.assertEqual(len(findings), 1)


class OverdueTest(unittest.TestCase):
    def test_daily_workflow_silent_for_47_days_alerts(self):
        states = [{"name": "db-report.yml", "crons": ["30 3 * * *"], "max_gap_minutes": 1440,
                   "last_run_at": (NOW - timedelta(days=47)).isoformat()}]
        findings = W.evaluate_overdue(states, now=NOW)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "E")

    def test_on_time_workflow_is_silent(self):
        states = [{"name": "purge-expired.yml", "crons": ["30 2 * * *"], "max_gap_minutes": 1440,
                   "last_run_at": (NOW - timedelta(hours=20)).isoformat()}]
        self.assertEqual(W.evaluate_overdue(states, now=NOW), [])

    def test_high_frequency_workflow_tolerates_dropped_triggers(self):
        # GitHub 会丢 schedule 触发（本项目实测丢过 2/3）。20 分钟一次的任务静默 4 小时
        # 就告警 = 天天误报；下限 24h 保证只有真死了才叫。
        states = [{"name": "campus-crawl.yml", "crons": ["*/20 * * * *"], "max_gap_minutes": 20,
                   "last_run_at": (NOW - timedelta(hours=4)).isoformat()}]
        self.assertEqual(W.evaluate_overdue(states, now=NOW), [])
        states[0]["last_run_at"] = (NOW - timedelta(hours=30)).isoformat()
        self.assertEqual(len(W.evaluate_overdue(states, now=NOW)), 1)

    def test_brand_new_workflow_that_never_ran_is_not_an_alert(self):
        # 昨天才加进来的周任务还没到第一次触发点，不算「该跑没跑」。
        states = [{"name": "ats-tenant-sync.yml", "crons": ["30 5 * * 1"], "max_gap_minutes": 10080,
                   "last_run_at": None,
                   "file_changed_at": (NOW - timedelta(days=1)).isoformat()}]
        self.assertEqual(W.evaluate_overdue(states, now=NOW), [])

    def test_long_standing_workflow_that_never_ran_alerts(self):
        states = [{"name": "ghost.yml", "crons": ["30 5 * * 1"], "max_gap_minutes": 10080,
                   "last_run_at": None,
                   "file_changed_at": (NOW - timedelta(days=90)).isoformat()}]
        self.assertEqual(len(W.evaluate_overdue(states, now=NOW)), 1)

    def test_no_cron_means_no_expectation(self):
        states = [{"name": "migrate.yml", "crons": [], "max_gap_minutes": None, "last_run_at": None}]
        self.assertEqual(W.evaluate_overdue(states, now=NOW), [])


class IssueRenderTest(unittest.TestCase):
    def test_title_is_stable_per_subject(self):
        # 标题就是去重键：同一个问题必须永远算出同一个标题，否则每天新开一个 issue。
        finding = {"rule": "A", "subject": "auto_discover", "summary": "x", "evidence": []}
        self.assertEqual(W.issue_title(finding), "[watchdog] 连续零产出：auto_discover")
        self.assertEqual(W.issue_title(finding), W.issue_title(dict(finding)))

    def test_body_carries_evidence(self):
        body = W.render_issue_body(
            {"rule": "C", "subject": "discovery_runs", "summary": "卡住了",
             "evidence": ["证据一", "证据二"], "next": "先看这里"}, now=NOW)
        self.assertIn("卡住了", body)
        self.assertIn("- 证据一", body)
        self.assertIn("先看这里", body)
        self.assertIn("ops_watchdog.py", body)


class PublishTest(unittest.TestCase):
    def test_dry_run_never_touches_github(self):
        """dry-run 必须是零副作用的——演练时不能真往仓库里灌 issue。"""
        calls = []
        original = W._gh
        W._gh = lambda *a, **k: calls.append(a) or ""
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                opened, commented = W.publish(
                    "owner/repo",
                    [{"rule": "A", "subject": "m", "summary": "s", "evidence": []}],
                    apply=False, now=NOW)
        finally:
            W._gh = original
        self.assertEqual((opened, commented, calls), (0, 0, []))


if __name__ == "__main__":
    unittest.main()
