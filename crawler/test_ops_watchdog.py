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


class TestUnfinishedCrawls(unittest.TestCase):
    """规则 I：抓取半途死了 —— 有 started_at 没 finished_at。

    真实病例：2026-09-05 05:06 前后 10 个源在约 30 秒内集体留下空记录（像一次 CI 超时），
    而它们的 status 全是当时的占位符 'skipped'，与「按设计跳过」同形 → 规则 F 看不见、
    模块级绿灯，没有任何告警。
    """

    NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    SOURCES = {
        "s1": {"adapter_name": "beisen", "company": "诺禾致源", "enabled": True},
        "s2": {"adapter_name": "workday", "company": "Visa", "enabled": True},
        "s3": {"adapter_name": "moka", "company": "正泰集团", "enabled": False},
    }

    def _row(self, sid, hours_ago, finished=False, status="running"):
        started = self.NOW - timedelta(hours=hours_ago)
        return {
            "source_id": sid,
            "status": status,
            "started_at": started.isoformat(),
            "finished_at": (started + timedelta(seconds=3)).isoformat() if finished else None,
        }

    def test_flags_runs_that_never_wrote_a_terminal_status(self):
        rows = [self._row("s1", 8), self._row("s2", 9)]
        [finding] = W.evaluate_unfinished_crawls(rows, self.SOURCES, now=self.NOW)
        self.assertEqual(finding["rule"], "I")
        self.assertIn("2", finding["summary"])

    def test_ignores_finished_runs(self):
        rows = [self._row("s1", 8, finished=True), self._row("s2", 9, finished=True)]
        self.assertEqual(W.evaluate_unfinished_crawls(rows, self.SOURCES, now=self.NOW), [])

    def test_does_not_flag_in_flight_runs(self):
        """正在跑的源 finished_at 也是空 —— 不许把它们报成崩溃。"""
        rows = [self._row("s1", 0.1), self._row("s2", 1)]
        self.assertEqual(W.evaluate_unfinished_crawls(rows, self.SOURCES, now=self.NOW), [])

    def test_catches_legacy_skipped_placeholder(self):
        """迁移 234 之前的占位符是 'skipped' —— 判据不看 status，这类必须照样抓得到。

        这正是规则 I 存在的理由：只认 'running' 等于只修了新数据，
        而线上历史孤儿全是 'skipped'。
        """
        rows = [self._row("s1", 8, status="skipped")]
        self.assertEqual(len(W.evaluate_unfinished_crawls(rows, self.SOURCES, now=self.NOW)), 1)

    def test_ignores_disabled_sources(self):
        self.assertEqual(
            W.evaluate_unfinished_crawls([self._row("s3", 8)], self.SOURCES, now=self.NOW), [])

    def test_ignores_unknown_source_id(self):
        self.assertEqual(
            W.evaluate_unfinished_crawls([self._row("nope", 8)], self.SOURCES, now=self.NOW), [])

    def test_reports_the_densest_minute_as_a_batch_kill(self):
        """一次超时带走一整批 —— 证据里要点出「同一分钟 N 条」，否则看不出是批量事故。"""
        rows = [self._row("s1", 8), self._row("s2", 8), self._row("s1", 8)]
        [finding] = W.evaluate_unfinished_crawls(rows, self.SOURCES, now=self.NOW)
        joined = " ".join(finding["evidence"])
        self.assertIn("3 条同时留空", joined)
        self.assertIn("CI 超时", joined)

    def test_single_stragglers_are_not_called_a_batch_kill(self):
        rows = [self._row("s1", 8), self._row("s2", 9)]
        [finding] = W.evaluate_unfinished_crawls(rows, self.SOURCES, now=self.NOW)
        self.assertNotIn("CI 超时", " ".join(finding["evidence"]))


if __name__ == "__main__":
    unittest.main()


class CoverageShortfallRuleTest(unittest.TestCase):
    """规则 G：源「跑绿了但没抓全」。真实病例见 2026-09-04 的 crawl_runs 实测。"""

    SOURCES = {
        "s1": {"id": "s1", "adapter_name": "beisen", "company": "奇瑞汽车", "enabled": True},
        "s2": {"id": "s2", "adapter_name": "smartrecruiters", "company": "Bosch 博世", "enabled": True},
        "s3": {"id": "s3", "adapter_name": "beisen", "company": "已停用", "enabled": False},
        "s4": {"id": "s4", "adapter_name": "feishu", "company": "蔚来", "enabled": True},
    }

    @staticmethod
    def _row(sid, reported, found, complete=False, started="2026-08-27T00:00:00+00:00"):
        return {"source_id": sid, "status": "success", "started_at": started,
                "reported_total": reported, "jobs_found": found, "coverage_complete": complete}

    def test_reports_aggregate_with_biggest_gap_first(self):
        rows = [self._row("s1", 5643, 600), self._row("s4", 2055, 600)]
        [finding] = W.evaluate_coverage_shortfall(rows, self.SOURCES)
        self.assertEqual(finding["rule"], "G")
        self.assertIn("2 个源", finding["summary"])
        self.assertIn("6498", finding["summary"])        # 5043 + 1455
        self.assertIn("奇瑞汽车", finding["evidence"][0])  # 缺口最大的排最前

    def test_coverage_complete_true_is_not_a_shortfall(self):
        """外企 ATS 的 reported_total 是**过滤前全球总数**，抓完才按 regions 做地区后置过滤。
        把它们算进来 = 天天喊狼来了，这条规则就废了。"""
        rows = [self._row("s2", 4828, 1705, complete=True)]
        self.assertEqual(W.evaluate_coverage_shortfall(rows, self.SOURCES), [])

    def test_unknown_coverage_is_not_a_shortfall(self):
        """coverage_complete=None = 接口没给分母，诚实盲区，不是抓不全。"""
        rows = [self._row("s1", 5643, 600, complete=None)]
        self.assertEqual(W.evaluate_coverage_shortfall(rows, self.SOURCES), [])

    def test_small_gaps_stay_quiet(self):
        rows = [self._row("s1", 5000, 4950)]      # 比例够高
        self.assertEqual(W.evaluate_coverage_shortfall(rows, self.SOURCES), [])
        rows = [self._row("s1", 300, 100)]        # 比例低但绝对量小
        self.assertEqual(W.evaluate_coverage_shortfall(rows, self.SOURCES), [])

    def test_total_gap_below_floor_stays_quiet(self):
        rows = [self._row("s1", 1000, 700)]       # 单源过线但全站才 300
        self.assertEqual(W.evaluate_coverage_shortfall(rows, self.SOURCES), [])

    def test_disabled_source_is_skipped(self):
        rows = [self._row("s3", 28827, 600)]
        self.assertEqual(W.evaluate_coverage_shortfall(rows, self.SOURCES), [])

    def test_only_latest_run_per_source_counts(self):
        """一个源一天跑 4 轮，早上没抓全、晚上抓全了 → 不该再报。"""
        rows = [self._row("s1", 5643, 600, started="2026-08-27T01:00:00+00:00"),
                self._row("s1", 5643, 5643, complete=True, started="2026-08-27T13:00:00+00:00")]
        self.assertEqual(W.evaluate_coverage_shortfall(rows, self.SOURCES), [])

    def test_issue_title_is_stable(self):
        rows = [self._row("s1", 5643, 600), self._row("s4", 2055, 600)]
        [finding] = W.evaluate_coverage_shortfall(rows, self.SOURCES)
        self.assertEqual(W.issue_title(finding), "[watchdog] 源抓不全：抓取覆盖")


class DeadSourceRuleTest(unittest.TestCase):
    SOURCES = {
        "s1": {"id": "s1", "adapter_name": "workday", "company": "奥的斯 Otis",
               "source_url": "https://otis.wd5.myworkdayjobs.com/wday/cxs/otis/REC_Ext_Gateway/jobs", "enabled": True},
        "s2": {"id": "s2", "adapter_name": "moka", "company": "某公司", "source_url": "https://x", "enabled": True},
        "s3": {"id": "s3", "adapter_name": "ashby", "company": "已停用", "source_url": "https://y", "enabled": False},
    }

    @staticmethod
    def _rows(sid, n, status="failed", error="HTTPStatusError: 422"):
        return [{"source_id": sid, "status": status, "error_message": error} for _ in range(n)]

    def test_all_failed_source_is_reported_with_top_error(self):
        rows = self._rows("s1", 20) + self._rows("s2", 20, status="success", error=None)
        findings = W.evaluate_dead_sources(rows, self.SOURCES, days=5)
        self.assertEqual([f["subject"] for f in findings], ["workday / 奥的斯 Otis"])
        self.assertEqual(findings[0]["rule"], "F")
        self.assertIn("HTTPStatusError: 422", findings[0]["evidence"][0])
        self.assertIn("REC_Ext_Gateway", findings[0]["evidence"][1])

    def test_one_success_in_window_is_not_dead(self):
        rows = self._rows("s1", 19) + self._rows("s1", 1, status="success", error=None)
        self.assertEqual(W.evaluate_dead_sources(rows, self.SOURCES), [])

    def test_partial_success_and_empty_do_not_count_as_failed(self):
        rows = self._rows("s1", 10, status="partial_success", error=None)
        self.assertEqual(W.evaluate_dead_sources(rows, self.SOURCES), [])

    def test_too_few_runs_and_disabled_sources_are_skipped(self):
        rows = self._rows("s1", W.DEAD_SOURCE_MIN_RUNS - 1) + self._rows("s3", 30)
        self.assertEqual(W.evaluate_dead_sources(rows, self.SOURCES), [])

    def test_issue_title_is_stable_per_source(self):
        rows = self._rows("s1", 10)
        [finding] = W.evaluate_dead_sources(rows, self.SOURCES)
        self.assertEqual(W.issue_title(finding), "[watchdog] 源连续失败：workday / 奥的斯 Otis")

    def test_daily_crawl_module_has_output_spec(self):
        # run.py 2026-09-03 起写 daily_crawl 台账；没声明口径规则 A 会静默跳过它。
        self.assertIn("daily_crawl", W.MODULE_OUTPUT)


class DuplicatePortalTest(unittest.TestCase):
    """规则 H：同一个 ATS 门户挂多个 enabled 源 —— 用 2026-09-04 实际踩到的三处做用例。"""

    @staticmethod
    def _src(company, url, enabled=True):
        return {"company": company, "source_url": url, "enabled": enabled, "adapter_name": "moka"}

    def test_portal_identity_is_host_independent(self):
        from ops_watchdog import portal_identity
        a = portal_identity("https://campus.geely.com/campus-recruitment/geely/78436")
        b = portal_identity("https://app.mokahr.com/campus-recruitment/geely/78436")
        self.assertEqual(a, b, "同一 portal 换个域名必须算同一个身份")
        self.assertEqual(a, "geely/78436")

    def test_different_portals_not_grouped(self):
        from ops_watchdog import portal_identity
        self.assertNotEqual(
            portal_identity("https://app.mokahr.com/campus-recruitment/geely/78436"),
            portal_identity("https://app.mokahr.com/social-recruitment/geely/96123"),
            "同一家公司的校招/社招是两个门户，不能算重复")

    def test_flags_the_three_real_duplicates(self):
        from ops_watchdog import evaluate_duplicate_portals
        sources = {
            "1": self._src("吉利汽车", "https://campus.geely.com/campus-recruitment/geely/78436"),
            "2": self._src("吉利", "https://app.mokahr.com/campus-recruitment/geely/78436"),
            "3": self._src("大疆创新", "https://apply.careers.dji.com/social-recruitment/dji/170070"),
            "4": self._src("大疆", "https://app.mokahr.com/social-recruitment/dji/170070"),
            "5": self._src("网易", "https://app.mokahr.com/social-recruitment/netease/999"),
        }
        out = evaluate_duplicate_portals(sources)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["rule"], "H")
        self.assertIn("2", out[0]["summary"])            # 两个门户重复
        self.assertTrue(any("geely/78436" in e for e in out[0]["evidence"]))
        self.assertFalse(any("netease" in e for e in out[0]["evidence"]), "没重复的源不该被报")

    def test_disabled_duplicate_is_not_flagged(self):
        """已经按规则关掉厂商域名那条之后，就不该再天天喊。"""
        from ops_watchdog import evaluate_duplicate_portals
        sources = {
            "1": self._src("吉利汽车", "https://campus.geely.com/campus-recruitment/geely/78436"),
            "2": self._src("吉利", "https://app.mokahr.com/campus-recruitment/geely/78436",
                           enabled=False),
        }
        self.assertEqual(evaluate_duplicate_portals(sources), [])

    def test_no_portal_pattern_is_ignored(self):
        from ops_watchdog import evaluate_duplicate_portals, portal_identity
        self.assertIsNone(portal_identity("https://fullhan.zhiye.com/social"))
        self.assertEqual(evaluate_duplicate_portals({
            "1": self._src("A", "https://a.zhiye.com/social"),
            "2": self._src("B", "https://b.zhiye.com/social")}), [])

    def test_workday_case_only_duplicate_is_caught(self):
        """Workday 大小写会带进 jd_url，而 canonical_jd_url 区分大小写 → 唯一索引拦不住。
        live 实测 Visa：visa/Visa 与 visa/visa 两条源并存，703 个岗两边都有。"""
        from ops_watchdog import evaluate_duplicate_portals, portal_identity
        self.assertEqual(portal_identity("https://x.wd5.myworkdayjobs.com/wday/cxs/shell/ShellCareers/jobs"),
                         portal_identity("https://x.wd5.myworkdayjobs.com/wday/cxs/shell/shellcareers/jobs"))
        out = evaluate_duplicate_portals({
            "1": {"company": "Visa", "enabled": True, "adapter_name": "workday",
                  "source_url": "https://visa.wd5.myworkdayjobs.com/wday/cxs/visa/Visa/jobs"},
            "2": {"company": "Visa", "enabled": True, "adapter_name": "workday",
                  "source_url": "https://visa.wd5.myworkdayjobs.com/wday/cxs/visa/visa/jobs"}})
        self.assertEqual(len(out), 1)
        self.assertTrue(any("visa/visa" in e for e in out[0]["evidence"]))

    def test_moka_apply_and_recruitment_forms_are_same_portal(self):
        """同一个 tenant/portalId 的两种 URL 写法 —— live 实测特斯拉 1,043 个 uuid 两边都有。"""
        from ops_watchdog import evaluate_duplicate_portals
        out = evaluate_duplicate_portals({
            "1": {"company": "特斯拉中国 Tesla", "enabled": True, "adapter_name": "moka",
                  "source_url": "https://app.mokahr.com/apply/tesla/46129"},
            "2": {"company": "特斯拉", "enabled": True, "adapter_name": "moka",
                  "source_url": "https://app.mokahr.com/social-recruitment/tesla/46129"}})
        self.assertEqual(len(out), 1)
        self.assertTrue(any("tesla/46129" in e for e in out[0]["evidence"]))

    def test_beisen_and_feishu_board_pairs_are_not_flagged(self):
        """🚫 回归：板块段在路径里的平台**不归本规则管**。
        汇顶 social(64) 与 campus(35) 实测交集为 0，按租户名归一会误杀 72 组合法板块对。"""
        from ops_watchdog import evaluate_duplicate_portals
        self.assertEqual(evaluate_duplicate_portals({
            "1": {"company": "汇顶科技", "enabled": True, "adapter_name": "beisen",
                  "source_url": "https://goodix.zhiye.com/social"},
            "2": {"company": "汇顶科技", "enabled": True, "adapter_name": "beisen",
                  "source_url": "https://goodix.zhiye.com/campus"},
            "3": {"company": "蔚来", "enabled": True, "adapter_name": "feishu",
                  "source_url": "https://nio.jobs.feishu.cn/index/position"},
            "4": {"company": "蔚来", "enabled": True, "adapter_name": "feishu",
                  "source_url": "https://nio.jobs.feishu.cn/campus/position"}}), [])

    def test_same_company_different_portals_still_not_flagged(self):
        """吉利校招门户 78436 与社招门户 96123 是两个 portal，不能算重复。"""
        from ops_watchdog import evaluate_duplicate_portals
        self.assertEqual(evaluate_duplicate_portals({
            "1": {"company": "吉利", "enabled": True, "adapter_name": "moka",
                  "source_url": "https://app.mokahr.com/campus-recruitment/geely/78436"},
            "2": {"company": "浙江吉利控股集团", "enabled": True, "adapter_name": "moka",
                  "source_url": "https://app.mokahr.com/social-recruitment/geely/96123"}}), [])

    def test_wt_brand_identity_is_host_and_case_independent(self):
        """wt 同一 brand 两种入口等价：live 实测 GWM 自有子域与共享 host 的 postId 120/120 重合。
        brand 大小写不统一（BASF/CT/cifi/feihe），必须转小写才归得到一起。"""
        from ops_watchdog import portal_identity
        self.assertEqual(portal_identity("https://gwm.hotjob.cn/wt/GWM/web/index"),
                         portal_identity("https://www.hotjob.cn/wt/gwm/web/index"))
        self.assertEqual(portal_identity("https://www.hotjob.cn/wt/BASF/web/index"), "basf")

    def test_wt_different_brands_not_grouped(self):
        from ops_watchdog import evaluate_duplicate_portals
        self.assertEqual(evaluate_duplicate_portals({
            "1": {"company": "长城汽车", "enabled": True, "adapter_name": "wt",
                  "source_url": "https://gwm.hotjob.cn/wt/GWM/web/index"},
            "2": {"company": "中国电信", "enabled": True, "adapter_name": "wt",
                  "source_url": "https://www.hotjob.cn/wt/CT/web/index"}}), [])

    def test_wt_same_brand_two_entrances_is_flagged(self):
        """防患用例：同一 brand 各插一条（自有子域 + 共享 host）必须报出来。
        全库当前 39 brand / 39 源、0 组重复，这条是防它长回来。"""
        from ops_watchdog import evaluate_duplicate_portals
        out = evaluate_duplicate_portals({
            "1": {"company": "长城汽车", "enabled": True, "adapter_name": "wt",
                  "source_url": "https://gwm.hotjob.cn/wt/GWM/web/index"},
            "2": {"company": "长城", "enabled": True, "adapter_name": "wt",
                  "source_url": "https://www.hotjob.cn/wt/gwm/web/index"}})
        self.assertEqual(len(out), 1)
        self.assertTrue(any("gwm" in e for e in out[0]["evidence"]))
