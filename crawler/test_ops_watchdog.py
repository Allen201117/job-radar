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
        # 普通模块：failed = 跑崩了，哪怕台账里没有处理量也算零产出。
        rows = [_run("enrich_backlog", "2026-08-25", "failed"),
                _run("enrich_backlog", "2026-08-26", "failed")]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual([f["subject"] for f in findings], ["enrich_backlog"])


class VerdictStatusZeroOutputTest(unittest.TestCase):
    """gap_funnel / gap_funnel_browser / campus_board_verify：failed = 「一项都没转化」，不是跑崩了。

    2026-08-30 起三个 issue 天天追评：漏斗每天复查 3~6 家没 adapter 的自建站，全部判出否定结论，
    status 记 failed、processed>0、sources_added=0 → 被当成零产出。两个方向都要钉住：
    该安静的安静（正确的否定结论），该响的照样响（走到验收门没加上源 / 抛异常）。
    """

    def test_funnel_with_only_negative_verdicts_is_idle(self):
        # 2026-09-21 / 09-22 线上真实形态（新口径下）：处理 5~6 家，没有一家走到验收门，无异常。
        rows = [_run("gap_funnel", day, "failed", processed=n, sources_added=0, gate_reached=0,
                     errors=0, campus_gate_reached=0, campus_errors=0, campus_sources_added=0)
                for day, n in (("2026-08-25", 5), ("2026-08-26", 6))]
        rows += [_run("gap_funnel_browser", day, "failed", processed=2, sources_added=0,
                      gate_reached=0, errors=0) for day in ("2026-08-25", "2026-08-26")]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(findings, [])

    def test_legacy_rows_without_new_keys_do_not_alert(self):
        # 上线前落的台账没有 gate_reached/errors：看不出有没有可转化的活，不拿 status 猜。
        rows = [_run("gap_funnel", "2026-08-25", "failed", processed=20, sources_added=0),
                _run("gap_funnel", "2026-08-26", "failed", processed=20, sources_added=0)]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(findings, [])

    def test_reaching_the_gate_without_adding_sources_still_alerts(self):
        rows = [_run("gap_funnel", day, "failed", processed=6, gate_reached=2, errors=0,
                     sources_added=0, campus_sources_added=0)
                for day in ("2026-08-25", "2026-08-26")]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual([f["subject"] for f in findings], ["gap_funnel"])

    def test_exceptions_still_alert(self):
        # 施耐德 / 联邦快递那种「同一家天天抛异常、+1 天重试」必须看得见。
        rows = [_run("gap_funnel", day, "failed", processed=5, gate_reached=0, errors=0,
                     campus_errors=5, sources_added=0, campus_sources_added=0)
                for day in ("2026-08-25", "2026-08-26")]
        rows += [_run("gap_funnel_browser", day, "failed", processed=1, gate_reached=0, errors=1,
                      sources_added=0) for day in ("2026-08-25", "2026-08-26")]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(sorted(f["subject"] for f in findings), ["gap_funnel", "gap_funnel_browser"])

    def test_campus_lane_output_counts_as_funnel_output(self):
        rows = [_run("gap_funnel", day, "failed", processed=5, gate_reached=0, errors=0,
                     campus_gate_reached=4, campus_sources_added=n, sources_added=0)
                for day, n in (("2026-08-25", 0), ("2026-08-26", 3))]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(findings, [])

    def test_campus_board_verify_empty_boards_are_idle(self):
        # 9-19 / 9-20 线上真实形态：12 个候选全是「板块空着等开闸」。
        rows = [_run("campus_board_verify", day, "failed", pending=12, enabled=0, empty_board=12,
                     actionable=0) for day in ("2026-08-25", "2026-08-26")]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual(findings, [])

    def test_campus_board_verify_crash_rows_still_alert(self):
        rows = [_run("campus_board_verify", day, "failed", errors=1)
                for day in ("2026-08-25", "2026-08-26")]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual([f["subject"] for f in findings], ["campus_board_verify"])

    def test_campus_board_verify_actionable_without_enabling_alerts(self):
        rows = [_run("campus_board_verify", day, "failed", pending=12, enabled=0, actionable=3,
                     empty_board=9) for day in ("2026-08-25", "2026-08-26")]
        findings, _ = W.evaluate_zero_output(rows, TODAY, days=2)
        self.assertEqual([f["subject"] for f in findings], ["campus_board_verify"])

    def test_verdict_modules_are_all_declared(self):
        self.assertTrue(W.VERDICT_STATUS_MODULES <= set(W.MODULE_OUTPUT))

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
    def _row(sid, reported, found, complete=False, started="2026-08-27T00:00:00+00:00",
             stop_reason=None):
        return {"source_id": sid, "status": "success", "started_at": started,
                "reported_total": reported, "jobs_found": found, "coverage_complete": complete,
                "coverage_stop_reason": stop_reason}

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

    def test_repetition_brake_stop_is_not_a_shortfall(self):
        """任务B：RepetitionBrake 按设计刹停（同一岗位×N家门店批量发布）不算「我们自己停在半路」，
        单独一个刹停源不该触发规则 G（哪怕缺口本身够大）。"""
        rows = [self._row("s1", 5643, 600, stop_reason="repetition_brake")]
        self.assertEqual(W.evaluate_coverage_shortfall(rows, self.SOURCES), [])

    def test_non_braked_shortfall_still_counts_when_mixed_with_braked(self):
        """真漏抓的源不能被同批的刹停源连累忽略；刹停源单列一行，不进 evidence 的缺口列表。"""
        rows = [self._row("s1", 5643, 600), self._row("s4", 2055, 600, stop_reason="repetition_brake")]
        [finding] = W.evaluate_coverage_shortfall(rows, self.SOURCES)
        self.assertIn("1 个源", finding["summary"])
        self.assertIn("5043", finding["summary"])   # 只有 s1 的缺口，s4 不计入
        joined = " ".join(finding["evidence"])
        self.assertIn("奇瑞汽车", joined)
        self.assertNotIn("蔚来（feishu）：官网自报", joined)   # s4 没被当成真缺口列出来
        self.assertIn("另有 1 个源按设计刹停", joined)
        self.assertIn("蔚来", joined)   # 但要在「按设计刹停」那一行里点名

    def test_all_sources_braked_means_rule_g_stays_quiet(self):
        """全是按设计刹停的源时，规则 G 完全不命中（连聚合 finding 都不产生）。"""
        rows = [self._row("s1", 5643, 600, stop_reason="repetition_brake"),
                self._row("s4", 2055, 600, stop_reason="repetition_brake")]
        self.assertEqual(W.evaluate_coverage_shortfall(rows, self.SOURCES), [])


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

    def test_2026_09_18_ledger_backfill_modules_are_registered(self):
        # 结构性审计发现的 9 个「既不写 ops_runs 也不写 crawl_runs」的链路 + 3 个已写台账但
        # 不在 MODULE_OUTPUT 的模块，2026-09-18 一起补登记：每一个都必须落在 MODULE_OUTPUT
        # 或 NO_OUTPUT_MODULES 里，不许既不在这、也不在那（= 又一次「补了台账没人告警」）。
        for module in (
            "campus_board_probe", "campus_board_verify", "harvest_beisen_routes",
            "company_logos", "announcement_harvest", "announcement_iguopin",
            "backfill_job_function", "backfill_recruitment_category", "db_report",
            "production_smoke", "audit_hotjob_attribution", "ats_tenant_sync",
            "announcement_verify",
        ):
            in_output = module in W.MODULE_OUTPUT
            in_no_output = module in W.NO_OUTPUT_MODULES
            self.assertTrue(
                in_output or in_no_output,
                f"{module} 既不在 MODULE_OUTPUT 也不在 NO_OUTPUT_MODULES，规则 A 会静默跳过它",
            )
            self.assertFalse(
                in_output and in_no_output,
                f"{module} 同时登记在两张表里，语义自相矛盾",
            )

    def test_campus_board_probe_zero_output_when_candidates_checked_but_nothing_added(self):
        rows = [{
            "module": "campus_board_probe", "run_date": "2026-09-17", "status": "success",
            "metrics": {"candidates_checked": 12, "triage_ok": 3, "sources_added": 0},
        }, {
            "module": "campus_board_probe", "run_date": "2026-09-16", "status": "success",
            "metrics": {"candidates_checked": 20, "triage_ok": 5, "sources_added": 0},
        }]
        findings, _skipped = W.evaluate_zero_output(rows, "2026-09-18", days=2)
        self.assertEqual([f["subject"] for f in findings], ["campus_board_probe"])

    def test_harvest_beisen_routes_idle_when_no_pending_tenants(self):
        # 待探租户为 0（全部已缓存）是正常的空队列，不该被规则 A 当成零产出。
        rows = [{
            "module": "harvest_beisen_routes", "run_date": "2026-09-17", "status": "success",
            "metrics": {"harvested": 0, "attempted": 0, "cached_total": 331, "pending": 0},
        }, {
            "module": "harvest_beisen_routes", "run_date": "2026-09-16", "status": "success",
            "metrics": {"harvested": 0, "attempted": 0, "cached_total": 331, "pending": 0},
        }]
        findings, _skipped = W.evaluate_zero_output(rows, "2026-09-18", days=2)
        self.assertEqual(findings, [])


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


class StaleApplyProgramsTest(unittest.TestCase):
    """规则 J：/programs 投递入口该复查了（2026-09-07 加）。

    背景：公告制入口改指「当期公告全文」后会随报名窗口过期变旧，而这张表没有任何
    自动复查机制。复查时点原本只写在 notes 里 —— 没人读就等于没写。
    """

    def _row(self, **over):
        row = {
            "company": "中国银行",
            "program_type": "announcement",
            "entry_url": "https://example.com/a/202609/t1.html",
            "enabled": True,
            "verified_at": "2026-09-07T00:00:00+00:00",
            "recheck_after": None,
        }
        row.update(over)
        return row

    def test_到期日已到就报(self):
        rows = [self._row(recheck_after="2026-10-09")]
        found = W.evaluate_stale_apply_programs(rows, today="2026-10-09")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["rule"], "J")
        self.assertIn("中国银行", found[0]["evidence"][0])

    def test_到期日没到就不报(self):
        rows = [self._row(recheck_after="2026-10-09")]
        self.assertEqual(W.evaluate_stale_apply_programs(rows, today="2026-10-08"), [])

    def test_没填到期日的靠核实时间兜底(self):
        # 90 天没重新核实 → 该报；刚核实过 → 不报。别让「没填到期日」变成永远不叫。
        old = self._row(company="东方电气", verified_at="2026-05-01T00:00:00+00:00")
        fresh = self._row(company="中国烟草")
        found = W.evaluate_stale_apply_programs([old, fresh], today="2026-09-07")
        self.assertEqual(len(found), 1)
        joined = " ".join(found[0]["evidence"])
        self.assertIn("东方电气", joined)
        self.assertNotIn("中国烟草", joined)

    def test_停用的行不报(self):
        rows = [self._row(enabled=False, recheck_after="2020-01-01")]
        self.assertEqual(W.evaluate_stale_apply_programs(rows, today="2026-09-07"), [])

    def test_到期日写坏了不拖垮整条规则(self):
        # 一行日期写错不该让别的行也不报 —— 坏行退回 verified_at 兜底判据。
        broken = self._row(company="坏行", recheck_after="不是日期",
                           verified_at="2026-01-01T00:00:00+00:00")
        found = W.evaluate_stale_apply_programs([broken], today="2026-09-07")
        self.assertEqual(len(found), 1)
        self.assertIn("坏行", " ".join(found[0]["evidence"]))

    def test_规则字母都登记了标题(self):
        # H / I 曾经在用却没登记，issue 标题会退化成裸字母。
        for letter in ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O"):
            self.assertIn(letter, W.RULE_TITLES)


class AnnouncementHarvestWatchdogTest(unittest.TestCase):
    NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)

    def test_missing_mac_runner_for_30_hours_alerts(self):
        rows = [{
            "module": "announcement_harvest",
            "metrics": {"runner": "ci", "portals_run": 4},
            "finished_at": "2026-09-17T11:00:00+00:00",
        }]
        [finding] = W.evaluate_missing_mac_announcement_harvest(rows, now=self.NOW)
        self.assertEqual((finding["rule"], finding["subject"]), ("M", "announcement_harvest"))
        self.assertIn("Mac 公告抓取 30 小时无记录", finding["summary"])

    def test_recent_mac_runner_is_healthy(self):
        rows = [{
            "module": "announcement_harvest",
            "metrics": {"runner": "mac", "portals_run": 27},
            "finished_at": "2026-09-17T10:00:00+00:00",
        }]
        self.assertEqual(W.evaluate_missing_mac_announcement_harvest(rows, now=self.NOW), [])


class CampusChannelGapWatchdogTest(unittest.TestCase):
    IN_SEASON = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    OFF_SEASON = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

    def _rows(self, missing, idle=0, healthy=0):
        rows = [{"company": f"缺{i}", "industries": ["金融"], "campus_channel": "missing"} for i in range(missing)]
        rows += [{"company": f"闲{i}", "industries": ["金融"], "campus_channel": "idle"} for i in range(idle)]
        rows += [{"company": f"好{i}", "industries": ["金融"], "campus_channel": "healthy"} for i in range(healthy)]
        return rows

    def test_in_season_missing_channels_alert_with_company_names(self):
        [finding] = W.evaluate_campus_channel_gap(self._rows(missing=3, idle=1, healthy=2), now=self.IN_SEASON, min_missing=1)
        self.assertEqual((finding["rule"], finding["subject"]), ("O", "must_apply_campus_channel"))
        self.assertIn("3 家", finding["summary"])
        self.assertTrue(any("缺0" in line for line in finding["evidence"]))

    def test_off_season_is_silent(self):
        self.assertEqual(W.evaluate_campus_channel_gap(self._rows(missing=30), now=self.OFF_SEASON), [])

    def test_below_threshold_is_silent(self):
        self.assertEqual(W.evaluate_campus_channel_gap(self._rows(missing=2), now=self.IN_SEASON, min_missing=5), [])


class CrawlRunUnrecordedWatchdogTest(unittest.TestCase):
    def test_nonzero_metric_alerts_with_task_and_count(self):
        rows = [
            _run("daily_crawl", "2026-09-17", crawl_run_unrecorded=2),
            _run("campus_crawl", "2026-09-17", crawl_run_unrecorded=0),
            _run("enrich_crawl", "2026-09-17"),
        ]
        [finding] = W.evaluate_crawl_run_unrecorded(rows, today="2026-09-17")
        self.assertEqual(finding["rule"], "N")
        self.assertIn("2", finding["summary"])
        self.assertIn("daily_crawl", "\n".join(finding["evidence"]))

    def test_zero_or_missing_metric_does_not_alert(self):
        rows = [
            _run("daily_crawl", "2026-09-17", crawl_run_unrecorded=0),
            _run("campus_crawl", "2026-09-17"),
        ]
        self.assertEqual(W.evaluate_crawl_run_unrecorded(rows, today="2026-09-17"), [])


class InsightSupplyStallTest(unittest.TestCase):
    """规则 P：洞察库 7 天新增 active 条数（2026-09-17 加）。"""

    def test_low_weekly_additions_alert(self):
        rows = [_run("insight_backlog", "2026-09-17", active_added_7d=3)]
        [finding] = W.evaluate_insight_supply_stall(rows, today="2026-09-17")
        self.assertEqual(finding["rule"], "P")
        self.assertIn("3", finding["summary"])

    def test_healthy_weekly_additions_silent(self):
        rows = [_run("insight_backlog", "2026-09-17", active_added_7d=400)]
        self.assertEqual(W.evaluate_insight_supply_stall(rows, today="2026-09-17"), [])

    def test_missing_metric_silent(self):
        """老台账行没有这个指标，不能当成 0 报警。"""
        rows = [_run("insight_backlog", "2026-09-17", checked=5)]
        self.assertEqual(W.evaluate_insight_supply_stall(rows, today="2026-09-17"), [])

    def test_none_metric_silent(self):
        """None = 没数出来，跟「真的一条没长」是两回事。"""
        rows = [_run("insight_backlog", "2026-09-17", active_added_7d=None)]
        self.assertEqual(W.evaluate_insight_supply_stall(rows, today="2026-09-17"), [])

    def test_uses_latest_run_date(self):
        rows = [
            _run("insight_backlog", "2026-09-10", active_added_7d=1),
            _run("insight_backlog", "2026-09-17", active_added_7d=500),
        ]
        self.assertEqual(W.evaluate_insight_supply_stall(rows, today="2026-09-17"), [])


class AdapterCollapseTest(unittest.TestCase):
    """规则 K：adapter 整体产出塌了，status 却照样 success（2026-09-13 加）。

    真实病例：moka 410 源 09-07~09 日产 3.1~3.8 万岗，09-10 起 490~642，几乎全记 success，
    单轮耗时 22s → 141s。规则 A 看模块、规则 F 看 failed，三天一声不吭。
    这里多数用例测「不该报」：一天跑几轮的源丢一轮、夜档漂出窗口、手动重跑翻倍——
    朴素的「adapter 日合计」回测在这些情况下 24 天误报了 50 多条。
    """

    NOW = datetime(2026, 9, 11, 1, 0, tzinfo=timezone.utc)

    def _sources(self, adapter, n, enabled=True):
        return {f"{adapter}-{i}": {"adapter_name": adapter, "company": f"{adapter}公司{i}",
                                   "enabled": enabled} for i in range(n)}

    def _run(self, sid, window, jobs, hour=4, seconds=22, status="success", finished=True):
        """window=0 是离 NOW 最近的 24h；hour 是该窗里往前推几小时（0<hour<24）。"""
        started = self.NOW - timedelta(days=window, hours=hour)
        return {
            "source_id": sid,
            "status": status,
            "jobs_found": jobs,
            "started_at": started.isoformat(),
            "finished_at": (started + timedelta(seconds=seconds)).isoformat() if finished else None,
        }

    def _history(self, sources, jobs, windows=range(1, 8), rounds=1, seconds=22):
        return [self._run(sid, w, jobs, hour=4 + 5 * r, seconds=seconds)
                for sid in sources for w in windows for r in range(rounds)]

    def test_moka_式骤降要报且依据里点出全是成功和耗时暴涨(self):
        sources = self._sources("moka", 20)
        rows = self._history(sources, 100)
        rows += [self._run(sid, 0, 1, seconds=141) for sid in sources]
        [finding] = W.evaluate_adapter_collapse(rows, sources, now=self.NOW)
        self.assertEqual((finding["rule"], finding["subject"]), ("K", "moka"))
        self.assertIn("20 vs 2000", finding["summary"])
        joined = "\n".join(finding["evidence"])
        self.assertIn("全是成功", joined)
        self.assertIn("×6.4", joined)
        self.assertIn("20 个源自身掉到一半以下", joined)
        self.assertEqual(W.issue_title(finding), "[watchdog] adapter 产出骤降：moka")

    def test_一天跑四轮的源丢了三轮不算骤降(self):
        # 朴素日合计会少 75%；按源取当窗最好一轮就不受影响。
        sources = self._sources("wt", 10)
        rows = self._history(sources, 500, rounds=4)
        rows += [self._run(sid, 0, 500) for sid in sources]
        self.assertEqual(W.evaluate_adapter_collapse(rows, sources, now=self.NOW), [])

    def test_手动重跑让基线翻倍也不会造出假骤降(self):
        # 09-03~05 moka 手动重跑过一天 4 轮：朴素日合计的基线中位数被抬到 4 倍，最近一天正常也像「掉了 75%」。
        sources = self._sources("beisen", 10)
        rows = self._history(sources, 300, windows=(1, 2, 3, 4), rounds=4)
        rows += self._history(sources, 300, windows=(5, 6, 7))
        rows += [self._run(sid, 0, 300) for sid in sources]
        self.assertEqual(W.evaluate_adapter_collapse(rows, sources, now=self.NOW), [])

    def test_最近窗整个没跑不归本规则(self):
        # 夜档漂出窗口 / workflow 没触发 = 「没跑」，不是「跑了没产出」（规则 E / I 的事）。
        sources = self._sources("moka", 20)
        rows = self._history(sources, 100)
        self.assertEqual(W.evaluate_adapter_collapse(rows, sources, now=self.NOW), [])

    def test_没收尾的行不当成零产出(self):
        sources = self._sources("moka", 20)
        rows = self._history(sources, 100)
        rows += [self._run(sid, 0, 0, finished=False, status="running") for sid in sources]
        self.assertEqual(W.evaluate_adapter_collapse(rows, sources, now=self.NOW), [])
        rows += [self._run(sid, 0, 100, hour=10) for sid in sources]
        self.assertEqual(W.evaluate_adapter_collapse(rows, sources, now=self.NOW), [])

    def test_小_adapter_在零和十几之间抖不报(self):
        sources = self._sources("company_spa", 1)
        rows = self._history(sources, 15)
        rows += [self._run(sid, 0, 0) for sid in sources]
        self.assertEqual(W.evaluate_adapter_collapse(rows, sources, now=self.NOW), [])

    def test_绝对量大但只腰斩一半不报(self):
        sources = self._sources("workday", 10)
        rows = self._history(sources, 1000)
        rows += [self._run(sid, 0, 500) for sid in sources]
        self.assertEqual(W.evaluate_adapter_collapse(rows, sources, now=self.NOW), [])

    def test_单源大_adapter_照样看得见(self):
        # bytedance / apple / ccb 都是单源 adapter；设「至少 3 个源」门槛会让它们全瞎。
        sources = self._sources("bytedance", 1)
        rows = self._history(sources, 12000)
        rows += [self._run(sid, 0, 0) for sid in sources]
        [finding] = W.evaluate_adapter_collapse(rows, sources, now=self.NOW)
        self.assertEqual(finding["subject"], "bytedance")

    def test_新源不进对照组_既不凑数也不掩盖(self):
        old = self._sources("moka", 10)
        new = {"moka-new": {"adapter_name": "moka", "company": "新源", "enabled": True}}
        young = {"moka-young": {"adapter_name": "moka", "company": "只跑过两窗", "enabled": True}}
        sources = {**old, **new, **young}
        rows = self._history(old, 100)
        rows += self._history(young, 100, windows=(1, 2))
        rows += [self._run(sid, 0, 0) for sid in old]
        rows += [self._run("moka-new", 0, 5000), self._run("moka-young", 0, 100)]
        [finding] = W.evaluate_adapter_collapse(rows, sources, now=self.NOW)
        self.assertIn("0 vs 1000", finding["summary"])
        self.assertIn("10 个源各取", finding["evidence"][0])

    def test_基线少于三窗的源不参与判定(self):
        sources = self._sources("moka", 20)
        rows = self._history(sources, 100, windows=(1, 2))
        rows += [self._run(sid, 0, 0) for sid in sources]
        self.assertEqual(W.evaluate_adapter_collapse(rows, sources, now=self.NOW), [])

    def test_停用的源和静音的_adapter_不报(self):
        rows_sources = self._sources("moka", 20)
        rows = self._history(rows_sources, 100) + [self._run(sid, 0, 0) for sid in rows_sources]
        disabled = self._sources("moka", 20, enabled=False)
        self.assertEqual(W.evaluate_adapter_collapse(rows, disabled, now=self.NOW), [])
        self.assertEqual(W.evaluate_adapter_collapse(rows, rows_sources, now=self.NOW,
                                                     muted=["moka"]), [])

    def test_要求连续两窗时两窗都得塌(self):
        sources = self._sources("moka", 20)
        baseline = self._history(sources, 100, windows=range(2, 9))
        today_zero = [self._run(sid, 0, 0) for sid in sources]
        one_bad = baseline + [self._run(sid, 1, 100) for sid in sources] + today_zero
        self.assertEqual(
            W.evaluate_adapter_collapse(one_bad, sources, now=self.NOW, recent_days=2), [])
        two_bad = baseline + [self._run(sid, 1, 0) for sid in sources] + today_zero
        [finding] = W.evaluate_adapter_collapse(two_bad, sources, now=self.NOW, recent_days=2)
        self.assertIn("48 小时", finding["summary"])
        self.assertEqual(sum("status 分布" in line for line in finding["evidence"]), 2)

    def test_窗外的行和未来时间的行都不算(self):
        # 最近窗里只有「晚于 NOW」的 0 岗行（started_at 是库端时钟，runner 时钟落后时会出现）→ 不能当成最近一窗塌了。
        sources = self._sources("moka", 20)
        rows = self._history(sources, 100)
        rows += [self._run(sid, -1, 0) for sid in sources]
        rows += [self._run(sid, 9, 0) for sid in sources]      # 早于 1+7 个窗，也不该进基线
        self.assertEqual(W.evaluate_adapter_collapse(rows, sources, now=self.NOW), [])

    def test_加长取数后规则_FGI_仍只看自己的回看窗(self):
        cutoff = self.NOW - timedelta(days=5)
        rows = [{"started_at": (cutoff + timedelta(hours=1)).isoformat()},
                {"started_at": (cutoff - timedelta(hours=1)).isoformat()},
                {"started_at": "不是时间"}]
        kept = W.rows_started_since(rows, cutoff)
        self.assertEqual([r["started_at"] for r in kept], [rows[0]["started_at"], "不是时间"])


class SilentSourcesTest(unittest.TestCase):
    """规则 L：本来每天都抓的 enabled 源，连一行 crawl_runs 都没有了（2026-09-13 加）。

    真实病例：快手 09-09 21:18 之后到 09-12 22:15 零行——enrich-crawl 的 enrich (2) 分片连续几晚撞 180 分钟
    被杀，排在串行浏览器档队尾的源根本没轮到。没有行，F / I / K 都看不见。
    多数用例测「不该报」：夜档被 GitHub 推迟、新源、停用、刚被抓过。
    """

    NOW = datetime(2026, 9, 12, 5, 40, tzinfo=timezone.utc)

    def _sources(self, adapter, n, enabled=True, prefix=None):
        prefix = prefix or adapter
        return {f"{prefix}-{i}": {"adapter_name": adapter, "company": f"{prefix}公司{i}",
                                  "enabled": enabled} for i in range(n)}

    def _rows(self, sources, hours_ago, status="success", finished=True):
        """每个源在「NOW 之前 hours_ago 小时」各一行。"""
        out = []
        for sid in sources:
            for h in hours_ago:
                started = self.NOW - timedelta(hours=h)
                out.append({"source_id": sid, "status": status, "started_at": started.isoformat(),
                            "finished_at": started.isoformat() if finished else None})
        return out

    @staticmethod
    def _nightly(from_hours, nights):
        """从 from_hours 小时前开始往前，每 24h 一晚。"""
        return [from_hours + 24 * k for k in range(nights)]

    def test_快手式断抓要报且标题稳定(self):
        sources = {"ks": {"adapter_name": "kuaishou", "company": "快手 Kuaishou", "enabled": True}}
        rows = self._rows(sources, self._nightly(56, 8))      # 最后一次 56 小时前，此前每晚都有
        [finding] = W.evaluate_silent_sources(rows, sources, now=self.NOW)
        self.assertEqual(finding["rule"], "L")
        self.assertEqual(W.issue_title(finding), "[watchdog] 源断抓：每天都抓的源没被轮到")
        self.assertIn("1 个本来每天都被抓", finding["summary"])
        joined = "\n".join(finding["evidence"])
        self.assertIn("{'kuaishou': 1}", joined)
        self.assertIn("kuaishou / 快手 Kuaishou：最后一次", joined)
        self.assertIn("已 56 小时", joined)
        self.assertIn("create_crawl_run", finding["next"])

    def test_夜档被推迟八小时的正常间隔不报(self):
        # 回测里夜档全部正常时，相邻两次被抓最长 32.2h（08-27 夜档推迟到次日 01:59）。
        sources = self._sources("moka", 5)
        rows = self._rows(sources, self._nightly(33, 8))
        self.assertEqual(W.evaluate_silent_sources(rows, sources, now=self.NOW), [])

    def test_基线锚在断抓之前_夜夜被饿死的源照样报(self):
        # 断抓 3 天多，更早还缺过一晚：锚在 now 的「前 7 天 ≥5 天」会让它掉出资格（09-13 华虹 / 华安基金）。
        sources = {"hh": {"adapter_name": "moka", "company": "华虹", "enabled": True}}
        hours = [76] + [76 + 24 * k for k in range(2, 8)]     # 76h 前最后一次，再往前缺一晚，其余都有
        [finding] = W.evaluate_silent_sources(self._rows(sources, hours), sources, now=self.NOW)
        self.assertIn("断抓前 7 天里 6 天抓到过", "\n".join(finding["evidence"]))

    def test_断抓前不够每天抓的源不报(self):
        sources = self._sources("beisen", 1)
        young = self._rows(sources, [50, 74])                 # 新源：只被抓过两晚
        self.assertEqual(W.evaluate_silent_sources(young, sources, now=self.NOW), [])
        sparse = self._rows(sources, [50, 98, 146, 194])      # 隔天抓一次（窗内 4 个窗有行）
        self.assertEqual(W.evaluate_silent_sources(sparse, sources, now=self.NOW), [])

    def test_窗内一行都没有的源不判(self):
        # 新加的、停用后刚重新启用的：没有「本来每天抓」的依据，别冤枉。
        sources = self._sources("feishu", 3)
        self.assertEqual(W.evaluate_silent_sources([], sources, now=self.NOW), [])

    def test_任何_status_的行都算轮到过(self):
        # failed / skipped / 没收尾的占位符都说明源被选中了——那是 F / I 的事，不是断抓。
        sources = self._sources("moka", 3)
        history = self._rows(sources, self._nightly(56, 8))
        for status, finished in (("failed", True), ("skipped", True), ("running", False)):
            rows = history + self._rows(sources, [10], status=status, finished=finished)
            self.assertEqual(W.evaluate_silent_sources(rows, sources, now=self.NOW), [], status)

    def test_晚于_now_的行说明刚被抓过(self):
        # started_at 是库端时钟，runner 时钟落后时最新一行会「晚于 now」。
        sources = self._sources("moka", 1)
        rows = self._rows(sources, self._nightly(56, 8)) + self._rows(sources, [-0.2])
        self.assertEqual(W.evaluate_silent_sources(rows, sources, now=self.NOW), [])

    def test_停用的源_静音的_adapter_未知源都不报(self):
        live = self._sources("moka", 2)
        rows = self._rows(live, self._nightly(56, 8)) + self._rows({"ghost": {}}, self._nightly(56, 8))
        disabled = self._sources("moka", 2, enabled=False)
        self.assertEqual(W.evaluate_silent_sources(rows, disabled, now=self.NOW), [])
        self.assertEqual(W.evaluate_silent_sources(rows, live, now=self.NOW, muted=["moka"]), [])
        [finding] = W.evaluate_silent_sources(rows, live, now=self.NOW, muted=["", " "])
        self.assertIn("2 个本来每天都被抓", finding["summary"])

    def test_一批源聚合成一条_最久的排前面并点出同日扎堆(self):
        tail = self._sources("moka", 4)
        other = {"ks": {"adapter_name": "kuaishou", "company": "快手", "enabled": True}}
        healthy = self._sources("wt", 3)
        rows = (self._rows(tail, self._nightly(56, 8)) + self._rows(other, self._nightly(80, 8))
                + self._rows(healthy, self._nightly(2, 8)))
        [finding] = W.evaluate_silent_sources(rows, {**tail, **other, **healthy}, now=self.NOW)
        self.assertIn("5 个本来每天都被抓", finding["summary"])
        self.assertIn("最久 80 小时", finding["summary"])
        self.assertIn("{'moka': 4, 'kuaishou': 1}", finding["evidence"][0])
        self.assertIn("4 个停在同一天", finding["evidence"][1])
        self.assertTrue(finding["evidence"][2].startswith("kuaishou / 快手"))

    def test_断抓太久基线落到取数窗外就掉出视野(self):
        # 已知盲区，钉住它免得被当成 bug「修」掉：main() 只取 SILENT_LOOKBACK_DAYS 天。
        sources = self._sources("moka", 1)
        rows = self._rows(sources, self._nightly(24 * 6 + 2, 8))
        cutoff = self.NOW - timedelta(days=W.SILENT_LOOKBACK_DAYS)
        self.assertEqual(W.evaluate_silent_sources(W.rows_started_since(rows, cutoff), sources,
                                                   now=self.NOW), [])
        self.assertEqual(len(W.evaluate_silent_sources(rows, sources, now=self.NOW)), 1)

    def test_取数回看至少装得下阈值加基线(self):
        # 谁把 hours 或 min_days 调大却忘了加回看天数，这条规则就会永远不报、也不报错。
        room = W.SILENT_LOOKBACK_DAYS - (W.SILENT_SOURCE_HOURS // 24)
        self.assertGreaterEqual(room, W.SILENT_MIN_DAYS)
        self.assertGreaterEqual(W.SILENT_SOURCE_HOURS, 36)   # 低于正常最长间隔 32.2h + 余量就会被调度漂移误报


class GuardedEvaluateTest(unittest.TestCase):
    """A/C/D/M/N/P 六条规则 2026-09-19 起各自包了一层：一条抛错不能拖垮其余规则，
    也不能让程序整体崩溃走不到桥接这一步。"""

    def test_success_passes_through_return_value_untouched(self):
        rule_errored = set()
        result = W.guarded_evaluate("A", rule_errored, lambda x: x + 1, 41)
        self.assertEqual(result, 42)
        self.assertEqual(rule_errored, set())

    def test_exception_is_warned_marks_rule_errored_and_returns_none(self):
        rule_errored = set()
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            result = W.guarded_evaluate("F", rule_errored, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertIsNone(result)
        self.assertEqual(rule_errored, {"F"})
        self.assertIn("::warning::", buf.getvalue())
        self.assertIn("F", buf.getvalue())

    def test_one_rule_failing_does_not_affect_evaluation_of_the_next_rule(self):
        """核验点：某条规则抛错后，紧接着评估的下一条规则必须照常拿到自己的真实结果，
        不能被前一条的异常带偏或跳过。"""
        rule_errored = set()
        first = W.guarded_evaluate("D", rule_errored, lambda: (_ for _ in ()).throw(ValueError("x")))
        second = W.guarded_evaluate(
            "M", rule_errored,
            lambda: [{"rule": "M", "subject": "mac", "summary": "s", "evidence": []}],
        )
        self.assertIsNone(first)
        self.assertEqual(rule_errored, {"D"})
        self.assertEqual(len(second), 1)  # M 完全不受 D 抛错影响

    def test_failed_rule_bridges_to_error_with_null_value_end_to_end(self):
        """从 guarded_evaluate 到 build_audit_bridge_rows 的端到端核验：
        某条规则这一轮抛错 → 桥接行必须是 verdict=error / value=None，不是「查到 0」。"""
        rule_errored = set()
        findings = []
        findings += W.guarded_evaluate(
            "N", rule_errored, lambda: (_ for _ in ()).throw(RuntimeError("db down")),
        ) or []
        checks = [{"id": "watchdog.rule_n", "rule": "N", "layer": "pipeline",
                   "severity": "critical", "normal": "== 0", "calibrated": False,
                   "source": "watchdog"}]
        rows = W.build_audit_bridge_rows(findings, rule_errored, checks, "2026-09-19", now=NOW)
        row = rows[0]
        self.assertEqual(row["verdict"], "error")
        self.assertIsNone(row["value"])
        self.assertIsNotNone(row["error_message"])


class AuditBridgeTest(unittest.TestCase):
    """老告警规则接进 audit_results：只做翻译，不重新判定；规则没评估成必须落 error/None。"""

    def _checks(self):
        return [
            {"id": "watchdog.rule_a", "rule": "A", "layer": "pipeline", "severity": "critical",
             "normal": "== 0", "calibrated": False, "source": "watchdog"},
            {"id": "watchdog.rule_f", "rule": "F", "layer": "data", "severity": "critical",
             "normal": "== 0", "calibrated": False, "source": "watchdog"},
        ]

    def test_rule_with_findings_is_breach_with_value_and_detail(self):
        findings = [{"rule": "A", "subject": "daily_crawl", "summary": "s", "evidence": []}]
        rows = W.build_audit_bridge_rows(findings, rule_errored=set(),
                                         checks=self._checks(), today="2026-09-19", now=NOW)
        by_id = {r["check_id"]: r for r in rows}
        a = by_id["watchdog.rule_a"]
        self.assertEqual(a["value"], 1.0)
        self.assertEqual(a["verdict"], "breach")
        self.assertIsNone(a["error_message"])
        self.assertEqual(len(a["detail"]["findings"]), 1)

    def test_rule_with_zero_findings_is_ok_with_no_detail(self):
        rows = W.build_audit_bridge_rows([], rule_errored=set(),
                                         checks=self._checks(), today="2026-09-19", now=NOW)
        f = {r["check_id"]: r for r in rows}["watchdog.rule_f"]
        self.assertEqual(f["value"], 0.0)
        self.assertEqual(f["verdict"], "ok")
        self.assertIsNone(f["detail"])

    def test_rule_that_failed_to_evaluate_is_error_with_null_value_not_zero(self):
        """核验点：规则本轮评估失败必须是 verdict=error / value=None，不许写成「查到 0」。"""
        rows = W.build_audit_bridge_rows([], rule_errored={"F"},
                                         checks=self._checks(), today="2026-09-19", now=NOW)
        f = {r["check_id"]: r for r in rows}["watchdog.rule_f"]
        self.assertIsNone(f["value"])
        self.assertEqual(f["verdict"], "error")
        self.assertIsNotNone(f["error_message"])
        # 没受影响的规则不该被连带标成 error
        a = {r["check_id"]: r for r in rows}["watchdog.rule_a"]
        self.assertEqual(a["verdict"], "ok")

    def test_non_watchdog_checks_are_ignored(self):
        checks = self._checks() + [{"id": "jobs.x", "source": "sql"}]
        rows = W.build_audit_bridge_rows([], set(), checks, "2026-09-19", now=NOW)
        self.assertEqual({r["check_id"] for r in rows}, {"watchdog.rule_a", "watchdog.rule_f"})

    def test_publish_bridge_write_failure_is_warning_not_raise(self):
        """写库失败只打 ::warning::，绝不让这条旁路观测炸掉 watchdog 主流程。"""
        import audit_runner as A
        original_connect = A.connect
        A.connect = lambda db: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                written = W.publish_audit_bridge(self._checks(), [], set(), "2026-09-19", now=NOW)
            self.assertEqual(written, 0)
            self.assertIn("::warning::", buf.getvalue())
        finally:
            A.connect = original_connect
