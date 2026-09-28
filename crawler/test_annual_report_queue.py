"""年报链队列：同一批 40 家天天被重选（issue #40）的回归 + 退避 / 轮转 / 口径。不打真实网络。

现象（CI 日志逐日 stat）：09-03 parsed 30 / already_latest 3 → 09-04 already_latest 32 → 09-20 36
→ 09-27 already_latest 37 + section_not_found 3，checked 恒为 40、written 恒为 0。
根因：旧实现 ``candidates[:limit]``，候选按 company_profiles.id 排序 → 每天是同一批。
"""
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import official_annual_report as A
import ops_watchdog as W

NOW = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)


def _cand(i, checked_at=None, result=None):
    profile = {"id": f"p{i:03d}", "company": f"公司{i}", "aliases": [],
               "annual_report_checked_at": checked_at, "annual_report_result": result}
    stock = {"zwjc": f"公司{i}", "code": f"{600000 + i}"}
    return profile, stock


def _ids(picked):
    return [profile["id"] for profile, _stock in picked]


class StarvationRegressionTest(unittest.TestCase):
    """复刻 09-27 那一轮：id 序前 40 家里 37 家已写过 FY2025、3 家解析不出员工章节。"""

    def setUp(self):
        self.candidates = [_cand(i) for i in range(120)]
        self.written = {f"p{i:03d}": {2025} for i in range(37)}
        # 那 3 家 section_not_found：新代码下它们会被记下结果（这里模拟前一天刚记过）。
        for i in (37, 38, 39):
            profile, _ = self.candidates[i]
            profile["annual_report_checked_at"] = (NOW - timedelta(days=1)).isoformat()
            profile["annual_report_result"] = "section_not_found"

    def test_old_slice_was_all_dead_weight(self):
        """旧口径 candidates[:40] 选出来的 40 家，没有一家是还有活可干的——这就是 written 恒 0 的原因。"""
        old = self.candidates[:40]
        picked, _stats = A.select_queue(self.candidates, self.written, NOW, 40)
        self.assertFalse(set(_ids(old)) & set(_ids(picked)))

    def test_new_queue_gives_the_turn_to_never_checked_companies(self):
        picked, stats = A.select_queue(self.candidates, self.written, NOW, 40)
        self.assertEqual(_ids(picked), [f"p{i:03d}" for i in range(40, 80)])
        self.assertEqual(stats, {"candidates": 120, "up_to_date": 37, "backoff": 3, "due": 80})

    def test_next_day_rotates_to_the_following_batch(self):
        picked, _ = A.select_queue(self.candidates, self.written, NOW, 40)
        for profile, _stock in picked:      # 模拟这 40 家当天都查出「已是最新」之外的定论
            profile["annual_report_checked_at"] = NOW.isoformat()
            profile["annual_report_result"] = "parsed"
        picked2, _ = A.select_queue(self.candidates, self.written, NOW + timedelta(days=1), 40)
        self.assertEqual(_ids(picked2), [f"p{i:03d}" for i in range(80, 120)])


class BackoffAndOrderTest(unittest.TestCase):
    def test_conclusive_result_backs_off_for_recheck_days_then_returns(self):
        recent = (NOW - timedelta(days=A.RECHECK_DAYS - 1)).isoformat()
        expired = (NOW - timedelta(days=A.RECHECK_DAYS + 1)).isoformat()
        for result in sorted(A.CONCLUSIVE_RESULTS):
            with self.subTest(result=result):
                picked, stats = A.select_queue([_cand(1, recent, result)], {}, NOW, 40)
                self.assertEqual((picked, stats["backoff"]), ([], 1))
                picked, stats = A.select_queue([_cand(1, expired, result)], {}, NOW, 40)
                self.assertEqual((_ids(picked), stats["backoff"]), (["p001"], 0))

    def test_inconclusive_result_is_not_backed_off_but_goes_to_the_back(self):
        """failed / no_reports 是「没查成」不是结论：不退避，但不许插到从没查过的公司前面。"""
        yesterday = (NOW - timedelta(days=1)).isoformat()
        long_ago = (NOW - timedelta(days=200)).isoformat()
        cands = [
            _cand(1, yesterday, "failed"),
            _cand(2, yesterday, "no_reports"),
            _cand(3, long_ago, "already_latest"),   # 定论已过期 → 该复查了
            _cand(4),                                # 从没查过
        ]
        picked, stats = A.select_queue(cands, {}, NOW, 40)
        self.assertEqual(_ids(picked), ["p004", "p003", "p001", "p002"])
        self.assertEqual(stats["backoff"], 0)
        picked, _ = A.select_queue(cands, {}, NOW, 2)
        self.assertEqual(_ids(picked), ["p004", "p003"])

    def test_persistent_failures_cannot_starve_new_companies(self):
        """40 家天天接口失败，也挤不掉后面从没查过的公司（旧实现下它们会永远占满 40 个名额）。"""
        yesterday = (NOW - timedelta(days=1)).isoformat()
        cands = [_cand(i, yesterday, "failed") for i in range(40)] + [_cand(i) for i in range(40, 45)]
        picked, _ = A.select_queue(cands, {}, NOW, 40)
        self.assertEqual(_ids(picked)[:5], [f"p{i:03d}" for i in range(40, 45)])

    def test_stable_order_among_never_checked(self):
        cands = [_cand(i) for i in (5, 2, 9)]
        picked, _ = A.select_queue(cands, {}, NOW, 40)
        self.assertEqual(_ids(picked), ["p005", "p002", "p009"])

    def test_limit_zero_and_negative(self):
        self.assertEqual(A.select_queue([_cand(1)], {}, NOW, 0)[0], [])
        self.assertEqual(A.select_queue([_cand(1)], {}, NOW, -3)[0], [])


class LatestPossibleYearTest(unittest.TestCase):
    """FY Y 的年报只能在 Y 年结束后发布 → 此刻可能存在的最新年度 = 北京时间今年 - 1。"""

    def test_year_boundary_follows_shanghai_not_utc(self):
        # UTC 12-31 20:00 = 北京 1-1 04:00：北京已进 2027，FY2026 年报从此刻起「可能存在」。
        self.assertEqual(A.latest_possible_report_year(datetime(2026, 12, 31, 15, 0, tzinfo=timezone.utc)), 2025)
        self.assertEqual(A.latest_possible_report_year(datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc)), 2026)

    def test_written_latest_year_is_skipped_until_a_newer_year_can_exist(self):
        cand = [_cand(1)]
        written = {"p001": {2024, 2025}}
        self.assertEqual(A.select_queue(cand, written, NOW, 40)[1]["up_to_date"], 1)
        jan = datetime(2027, 1, 2, tzinfo=timezone.utc)
        picked, stats = A.select_queue(cand, written, jan, 40)
        self.assertEqual((_ids(picked), stats["up_to_date"]), (["p001"], 0))

    def test_older_written_year_is_still_due(self):
        picked, stats = A.select_queue([_cand(1)], {"p001": {2024}}, NOW, 40)
        self.assertEqual((_ids(picked), stats["up_to_date"]), (["p001"], 0))


class RecheckDaysMatchesT2TtlTest(unittest.TestCase):
    def test_same_ttl_as_insight_backlog(self):
        """不另起阈值：与 T2 官方事实复核周期同口径（读源码比对，免得为一个常量拉起 insight_backlog 的重依赖）。"""
        src = (Path(__file__).resolve().parent / "insight_backlog.py").read_text(encoding="utf-8")
        match = re.search(r"^TTL_DAYS\s*=\s*(\d+)", src, re.M)
        self.assertIsNotNone(match)
        self.assertEqual(A.RECHECK_DAYS, int(match.group(1)))


class _FakeQuery:
    def __init__(self, log, table):
        self.log, self.table, self.payload, self.filters = log, table, None, []

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def execute(self):
        self.log.append((self.table, self.payload, tuple(self.filters)))
        return mock.Mock(data=[])


class _FakeSb:
    def __init__(self):
        self.log = []

    def table(self, name):
        return _FakeQuery(self.log, name)


class MainLoopTest(unittest.TestCase):
    """main() 端到端：队列 → 每家记下结果（含异常）→ 台账带队列分解。"""

    def _run_main(self, argv, profiles, written, outcomes):
        sb = _FakeSb()
        stocks = [{"zwjc": p["company"], "code": str(600000 + i), "orgId": "x"} for i, p in enumerate(profiles)]

        def fake_process(_sb, _client, profile, _stock, dry_run=False):
            outcome = outcomes[profile["id"]]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with mock.patch.object(A, "enabled", return_value=True), \
                mock.patch.object(A.db, "get_supabase", return_value=sb), \
                mock.patch.object(A, "fetch_stock_list", return_value=stocks), \
                mock.patch.object(A, "fetch_profiles", return_value=profiles), \
                mock.patch.object(A, "fetch_written_years", return_value=written), \
                mock.patch.object(A, "process_company", side_effect=fake_process), \
                mock.patch.object(A.time, "sleep"), \
                mock.patch.object(A.ops_runs, "record_ops_run") as rec, \
                mock.patch("sys.argv", ["official_annual_report.py", *argv]):
            A.main()
        return sb, rec

    def test_skips_up_to_date_stamps_every_result_and_reports_queue(self):
        profiles = [_cand(i)[0] for i in range(5)]
        written = {"p000": {2025}, "p001": {2025}}
        outcomes = {"p002": ("parsed", 2), "p003": ("section_not_found", 0), "p004": RuntimeError("504")}
        sb, rec = self._run_main(["--limit", "40"], profiles, written, outcomes)

        stamped = {filters[0][1]: payload["annual_report_result"]
                   for table, payload, filters in sb.log if table == "company_profiles"}
        self.assertEqual(stamped, {"p002": "parsed", "p003": "section_not_found", "p004": "failed"})

        _sb, module, metrics = rec.call_args.args[:3]
        self.assertEqual(module, "annual_report")
        self.assertEqual({k: metrics[k] for k in ("candidates", "up_to_date", "backoff", "due", "checked",
                                                  "parsed", "written", "section_not_found", "failed")},
                         {"candidates": 5, "up_to_date": 2, "backoff": 0, "due": 3, "checked": 3,
                          "parsed": 1, "written": 2, "section_not_found": 1, "failed": 1})

    def test_dry_run_does_not_stamp(self):
        profiles = [_cand(0)[0]]
        sb, _rec = self._run_main(["--dry-run"], profiles, {}, {"p000": ("parsed", 0)})
        self.assertEqual([entry for entry in sb.log if entry[0] == "company_profiles"], [])

    def test_named_company_bypasses_queue_filters(self):
        """点名单家 = 人工要求重查（例如改了解析器），不被「已是最新」或退避挡掉。"""
        profile = _cand(0, (NOW - timedelta(days=1)).isoformat(), "section_not_found")[0]
        with mock.patch.object(A, "select_queue", side_effect=AssertionError("点名时不该走队列")):
            sb, rec = self._run_main(["--company", "公司0"], [profile], {"p000": {2025}},
                                     {"p000": ("section_not_found", 0)})
        self.assertEqual(rec.call_args.args[2]["checked"], 1)


class WatchdogWorkKeyTest(unittest.TestCase):
    """规则 A 的处理量口径：already_latest 是正确结论不是「有活没干」。"""

    @staticmethod
    def _rows(metrics):
        return [{"module": "annual_report", "run_date": day, "status": "success", "metrics": metrics}
                for day in ("2026-09-26", "2026-09-27")]

    def test_only_already_latest_is_idle(self):
        rows = self._rows({"checked": 12, "already_latest": 12, "written": 0, "parsed": 0,
                           "section_not_found": 0, "scanned_pdf": 0, "failed": 0, "no_reports": 0})
        findings, _ = W.evaluate_zero_output(rows, "2026-09-28", days=2)
        self.assertEqual(findings, [])

    def test_historic_rows_still_judged_zero(self):
        """改口径不许把过去那几天倒回去改判：09-26/27 真有 3 家解析不出、0 写入，仍是零产出。"""
        rows = self._rows({"checked": 40, "already_latest": 37, "section_not_found": 3, "written": 0,
                           "parsed": 0, "scanned_pdf": 0, "failed": 0, "no_reports": 0})
        findings, _ = W.evaluate_zero_output(rows, "2026-09-28", days=2)
        self.assertEqual([f["subject"] for f in findings], ["annual_report"])

    def test_stock_list_failure_is_zero_not_idle(self):
        rows = self._rows({"checked": 0, "failed": 1, "written": 0})
        findings, _ = W.evaluate_zero_output(rows, "2026-09-28", days=2)
        self.assertEqual([f["subject"] for f in findings], ["annual_report"])

    def test_every_work_key_is_a_real_stat_key(self):
        """口径里的键必须是 main() 真会写的 stat 键，否则恒为 0 = 一条永远不报的假检查。"""
        src = (Path(__file__).resolve().parent / "official_annual_report.py").read_text(encoding="utf-8")
        stat_line = re.search(r'stat = \{(.+?)\}\n', src).group(1)
        produced, work = W.MODULE_OUTPUT["annual_report"]
        for key in (*produced, *work):
            self.assertIn(f'"{key}"', stat_line)


if __name__ == "__main__":
    unittest.main()
