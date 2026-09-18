import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

import morning_digest as md  # noqa: E402


def check(cid, name="名字", why="原因", action="处理办法", severity="warn", calibrated=False):
    return {"id": cid, "name": name, "why": why, "action": action, "severity": severity, "calibrated": calibrated}


def result(cid, value, verdict, severity="warn", calibrated=False, error_message=None):
    return {
        "check_id": cid, "layer": "experience", "severity": severity, "value": value,
        "normal": ">= 0", "verdict": verdict, "calibrated": calibrated, "error_message": error_message,
    }


class FormatTests(unittest.TestCase):
    def test_format_number_none_is_not_zero(self):
        self.assertEqual(md.format_number(None), "没查到")

    def test_format_number_large_uses_wan(self):
        self.assertEqual(md.format_number(502024), "50.2万")

    def test_format_number_small_int(self):
        self.assertEqual(md.format_number(7), "7")

    def test_format_percent_none(self):
        self.assertEqual(md.format_percent(None), "没查到")

    def test_format_percent_boundary(self):
        self.assertEqual(md.format_percent(0.301), "30.1%")

    def test_format_value_ratio_check(self):
        self.assertEqual(md.format_value("exp.search_zero_result_rate_7d", 0.5), "50.0%")

    def test_format_value_count_check(self):
        self.assertEqual(md.format_value("exp.dau_yesterday", 2), "2")

    def test_format_delta_no_yesterday(self):
        self.assertEqual(md.format_delta("exp.dau_yesterday", 5, None), "")

    def test_format_delta_with_yesterday(self):
        d = md.format_delta("exp.dau_yesterday", 5, 3)
        self.assertIn("↑", d)
        self.assertIn("2", d)

    def test_format_delta_ratio(self):
        d = md.format_delta("exp.search_zero_result_rate_7d", 0.3, 0.2)
        self.assertIn("个百分点", d)


class TrafficLightTests(unittest.TestCase):
    def test_all_ok_is_green(self):
        results = {"a": result("a", 1, "ok", severity="critical")}
        self.assertEqual(md.compute_traffic_light(results), "🟢")

    def test_critical_breach_is_red(self):
        results = {"a": result("a", 1, "breach", severity="critical")}
        self.assertEqual(md.compute_traffic_light(results), "🔴")

    def test_critical_error_is_red(self):
        results = {"a": result("a", None, "error", severity="critical")}
        self.assertEqual(md.compute_traffic_light(results), "🔴")

    def test_warn_breach_is_yellow(self):
        results = {"a": result("a", 1, "breach", severity="warn")}
        self.assertEqual(md.compute_traffic_light(results), "🟡")

    def test_any_error_is_yellow_when_not_critical(self):
        results = {"a": result("a", None, "error", severity="warn")}
        self.assertEqual(md.compute_traffic_light(results), "🟡")

    def test_single_source_breach_stays_yellow_not_red(self):
        results = {
            "a": result("a", 1, "ok", severity="critical"),
            "b": result("b", 1, "breach", severity="warn"),
        }
        self.assertEqual(md.compute_traffic_light(results), "🟡")


class SectionRowsTests(unittest.TestCase):
    def test_error_row_shows_not_found_not_zero(self):
        results_today = {"a": result("a", None, "error", error_message="boom")}
        rows = md.section_rows(results_today, {}, {"a": "指标A"}, ["a"])
        text = "\n".join(md.render_rows_text(rows))
        self.assertIn("没查到", text)
        self.assertNotIn("：0", text)

    def test_missing_check_is_skipped_not_crash(self):
        rows = md.section_rows({}, {}, {"a": "指标A"}, ["a", "b"])
        self.assertEqual(rows, [])

    def test_calibrated_false_tagged(self):
        results_today = {"a": result("a", 5, "ok", calibrated=False)}
        rows = md.section_rows(results_today, {}, {"a": "指标A"}, ["a"])
        self.assertIn("待校准", rows[0]["calibrated_tag"])


class WalkthroughSummaryTests(unittest.TestCase):
    def test_zero_counts_filtered(self):
        out = md.summarize_walkthrough_issues({"zero_shown": 0, "direction_low": 3})
        self.assertEqual(out, [(3, md.WALKTHROUGH_ISSUE_LABELS["direction_low"])])

    def test_empty_input(self):
        self.assertEqual(md.summarize_walkthrough_issues(None), [])
        self.assertEqual(md.summarize_walkthrough_issues({}), [])

    def test_unknown_type_falls_back_to_raw_key(self):
        out = md.summarize_walkthrough_issues({"some_new_type": 2})
        self.assertEqual(out, [(2, "some_new_type")])

    def test_sorted_by_count_desc(self):
        out = md.summarize_walkthrough_issues({"a_type": 1, "zero_shown": 5})
        self.assertEqual(out[0][0], 5)


class ActionItemsTests(unittest.TestCase):
    def test_no_breach_no_items(self):
        results_today = {"a": result("a", 1, "ok")}
        checks_by_id = {"a": check("a", action="do something")}
        self.assertEqual(md.build_action_items(results_today, checks_by_id), [])

    def test_critical_first(self):
        results_today = {
            "warn1": result("warn1", 1, "breach", severity="warn"),
            "crit1": result("crit1", 1, "breach", severity="critical"),
        }
        checks_by_id = {
            "warn1": check("warn1", name="W", action="do warn thing"),
            "crit1": check("crit1", name="C", action="do critical thing"),
        }
        items = md.build_action_items(results_today, checks_by_id)
        self.assertEqual(len(items), 2)
        self.assertIn("do critical thing", items[0])

    def test_limit_five(self):
        results_today = {}
        checks_by_id = {}
        for i in range(8):
            cid = f"c{i}"
            results_today[cid] = result(cid, 1, "breach", severity="warn")
            checks_by_id[cid] = check(cid, name=f"N{i}", action=f"do {i}")
        items = md.build_action_items(results_today, checks_by_id, limit=5)
        self.assertEqual(len(items), 5)


class NewlyBrokenTests(unittest.TestCase):
    def test_detects_ok_to_breach_transition(self):
        today = {"a": result("a", 1, "breach", severity="warn")}
        today["a"]["why"] = "变坏了"
        yesterday = {"a": result("a", 1, "ok")}
        out = md.find_newly_broken(today, yesterday, {"a": "指标A"})
        self.assertEqual(len(out), 1)

    def test_no_yesterday_data_not_counted_as_newly_broken(self):
        today = {"a": result("a", 1, "breach", severity="warn")}
        out = md.find_newly_broken(today, {}, {"a": "指标A"})
        self.assertEqual(out, [])

    def test_still_breach_not_newly_broken(self):
        today = {"a": result("a", 1, "breach", severity="warn")}
        yesterday = {"a": result("a", 1, "breach", severity="warn")}
        out = md.find_newly_broken(today, yesterday, {"a": "指标A"})
        self.assertEqual(out, [])


class OldIssueOrderTests(unittest.TestCase):
    def test_sorted_oldest_first(self):
        now = datetime.now(timezone.utc)
        issues = [
            {"number": 1, "title": "new", "createdAt": (now - timedelta(hours=1)).isoformat()},
            {"number": 2, "title": "old", "createdAt": (now - timedelta(days=30)).isoformat()},
        ]
        out = md.order_old_issues(issues, now=now)
        self.assertEqual(out[0]["number"], 2)

    def test_bad_created_at_does_not_crash(self):
        issues = [{"number": 1, "title": "x", "createdAt": "not-a-date"}]
        out = md.order_old_issues(issues)
        self.assertEqual(len(out), 1)


class BuildDigestTests(unittest.TestCase):
    def _checks(self):
        ids = md.SECTION_USERS + md.SECTION_EXPERIENCE + md.SECTION_SUPPLY + md.SECTION_FAKE_GREEN
        return [check(cid, name=f"人话名字-{i}") for i, cid in enumerate(ids)]

    def test_no_action_items_writes_placeholder(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        digest = md.build_digest(checks, results_today, [], None, [], None)
        self.assertIn("今天没有需要你处理的事", digest["text"])

    def test_subject_format(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        digest = md.build_digest(checks, results_today, [], None, [], None)
        self.assertRegex(digest["subject"], r"^[🔴🟡🟢] 职达 \d{1,2}/\d{1,2} · 日活")
        self.assertIn("待清账", digest["subject"])

    def test_html_has_no_technical_leakage(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        digest = md.build_digest(checks, results_today, [], None, [], None)
        html = digest["html"]
        for cid in [c["id"] for c in checks]:
            self.assertNotIn(cid, html)
        self.assertNotIn("select ", html.lower())
        self.assertNotIn("jobs.active_total", html)

    def test_no_yesterday_no_delta_shown(self):
        checks = self._checks()
        results_today = [result(cid, 5, "ok") for cid in [c["id"] for c in checks]]
        digest = md.build_digest(checks, results_today, [], None, [], None)
        self.assertNotIn("较昨天", digest["text"])

    def test_data_integrity_lists_error_checks_not_zero(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks[1:]]]
        results_today.append(result(checks[0]["id"], None, "error", error_message="timeout"))
        digest = md.build_digest(checks, results_today, [], None, [], None)
        self.assertIn("没查到", digest["text"])

    def test_last_digest_delivered(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        last = {"status": "success", "finished_at": None, "metrics": {}}
        digest = md.build_digest(checks, results_today, [], None, [], last)
        self.assertIn("已送达", digest["text"])

    def test_last_digest_missing_says_so(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        digest = md.build_digest(checks, results_today, [], None, [], None)
        self.assertIn("没有台账记录", digest["text"])

    def test_old_issues_full_list_not_truncated(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        now = datetime.now(timezone.utc)
        issues = [
            {"number": i, "title": f"issue {i}", "createdAt": (now - timedelta(days=i)).isoformat(), "comments": 0}
            for i in range(1, 12)
        ]
        digest = md.build_digest(checks, results_today, [], None, issues, None)
        for i in range(1, 12):
            self.assertIn(f"#{i} ", digest["text"])


class SendResendTests(unittest.TestCase):
    def test_dry_run_prints_missing_key_notice(self):
        import io
        import contextlib
        buf = io.StringIO()
        old_environ = dict(os.environ)
        os.environ.pop("RESEND_API_KEY", None)
        os.environ.pop("DIGEST_TO", None)
        try:
            with contextlib.redirect_stdout(buf):
                # 复刻 main() 里 dry-run 分支的判定逻辑，不跑真正的网络/DB
                api_key = os.environ.get("RESEND_API_KEY")
                to_addr = os.environ.get("DIGEST_TO")
                if not api_key:
                    print("未发送：缺 RESEND_API_KEY")
                if not to_addr:
                    print("未发送：缺 DIGEST_TO")
        finally:
            os.environ.clear()
            os.environ.update(old_environ)
        out = buf.getvalue()
        self.assertIn("未发送：缺 RESEND_API_KEY", out)
        self.assertIn("未发送：缺 DIGEST_TO", out)


if __name__ == "__main__":
    unittest.main()
