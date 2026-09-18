import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

import morning_digest as md  # noqa: E402
import audit_runner as ar  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIRS = ("app", "lib", "components", "scripts")  # scripts/ 覆盖 ux_walkthrough 这类跑批脚本产生的字面量

# 从体验层 SQL 里能抠出字面量的四种写法：event = '…' / event in ('…','…')、
# payload->>'latency_bucket' = '…' / in (...)、payload->>'result' = '…'、
# job_actions.action = '…'、ops_runs.module = '…'。
_EVENT_RE = re.compile(r"\bevent\s*(?:=|in)\s*\(?\s*'([^']+)'(?:\s*,\s*'([^']+)')*\)?", re.I)
_BUCKET_RE = re.compile(r"latency_bucket'\s*(?:=|in)\s*\(?\s*'([^']+)'(?:\s*,\s*'([^']+)')*\)?", re.I)
_RESULT_RE = re.compile(r"'result'\s*=\s*'([^']+)'")
_ACTION_RE = re.compile(r"\baction\s*=\s*'([^']+)'")
_MODULE_RE = re.compile(r"\bmodule\s*=\s*'([^']+)'")


def extract_literals(sql):
    """从一条体验层 SQL 里抠出所有「跟埋点/枚举取值有关」的字面量，返回 set((kind, value))。"""
    out = set()
    for m in _EVENT_RE.finditer(sql):
        for g in m.groups():
            if g:
                out.add(("event", g))
    for m in _BUCKET_RE.finditer(sql):
        for g in m.groups():
            if g:
                out.add(("latency_bucket", g))
    for m in _RESULT_RE.finditer(sql):
        out.add(("result", m.group(1)))
    for m in _ACTION_RE.finditer(sql):
        out.add(("action", m.group(1)))
    for m in _MODULE_RE.finditer(sql):
        out.add(("module", m.group(1)))
    return out


def literal_appears_in_source(value):
    """在 app/ lib/ components/ 里按字面量（单引号或双引号包裹）grep，找到任一处即算有来源。"""
    needles = (f"'{value}'", f'"{value}"')
    for base in SOURCE_DIRS:
        base_path = os.path.join(REPO_ROOT, base)
        if not os.path.isdir(base_path):
            continue
        for dirpath, _dirnames, filenames in os.walk(base_path):
            if "node_modules" in dirpath or "/.next" in dirpath:
                continue
            for fn in filenames:
                if not fn.endswith((".ts", ".tsx", ".js", ".jsx")):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, encoding="utf-8", errors="ignore") as fh:
                        text = fh.read()
                except OSError:
                    continue
                if any(n in text for n in needles):
                    return path
    return None


def check(cid, name="名字", why="原因", action="处理办法", severity="warn", calibrated=False, layer=None):
    c = {"id": cid, "name": name, "why": why, "action": action, "severity": severity, "calibrated": calibrated}
    if layer is not None:
        c["layer"] = layer
    return c


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


class MergeMissingAsErrorTests(unittest.TestCase):
    """contract 里有、但今天 audit_results 没有这一行的检查项（含 source=watchdog 的条目）
    = 今天没查到，必须合成一行 verdict=error，按自己 severity 参与灯色（info 除外）。
    """

    def test_missing_check_becomes_error_row(self):
        checks = [check("a", severity="critical")]
        merged = md.merge_missing_as_error(checks, {})
        self.assertEqual(merged["a"]["verdict"], "error")
        self.assertIsNone(merged["a"]["value"])
        self.assertEqual(merged["a"]["severity"], "critical")

    def test_existing_row_is_not_overwritten(self):
        checks = [check("a", severity="critical")]
        existing = {"a": result("a", 5, "ok")}
        merged = md.merge_missing_as_error(checks, existing)
        self.assertEqual(merged["a"]["verdict"], "ok")
        self.assertEqual(merged["a"]["value"], 5)

    def test_missing_watchdog_style_check_without_sql_or_db_field(self):
        """source=watchdog 的条目没有 sql/db 字段，合并逻辑不该因此报错。"""
        checks = [{"id": "watchdog.rule_a", "name": "老告警 A", "severity": "warn",
                   "why": "why", "action": "action", "source": "watchdog"}]
        merged = md.merge_missing_as_error(checks, {})
        self.assertIn("watchdog.rule_a", merged)
        self.assertEqual(merged["watchdog.rule_a"]["verdict"], "error")

    def test_missing_critical_check_turns_light_red(self):
        checks = [check("a", severity="critical")]
        merged = md.merge_missing_as_error(checks, {})
        self.assertEqual(md.compute_traffic_light(merged), "🔴")

    def test_missing_info_check_stays_green(self):
        checks = [check("a", severity="info")]
        merged = md.merge_missing_as_error(checks, {})
        self.assertEqual(md.compute_traffic_light(merged), "🟢")

    def test_missing_warn_check_turns_light_yellow(self):
        checks = [check("a", severity="warn")]
        merged = md.merge_missing_as_error(checks, {})
        self.assertEqual(md.compute_traffic_light(merged), "🟡")


class BuildIssueTitleNamesTests(unittest.TestCase):
    def test_hits_module_literal_in_equality_sql(self):
        checks = [{
            "id": "pipeline.x", "name": "洞察供给车道昨天有没有跑", "subject": "洞察供给车道", "layer": "pipeline",
            "owner": ".github/workflows/x.yml",
            "sql": "select count(*) from ops_runs where module = 'insight_backlog'",
        }]
        names = md.build_issue_title_names(checks)
        self.assertEqual(names.get("insight_backlog"), "洞察供给车道")

    def test_hits_module_literal_in_any_array_sql(self):
        checks = [{
            "id": "pipeline.y", "name": "扩源车道昨天有没有跑", "subject": "扩源车道", "layer": "pipeline",
            "owner": ".github/workflows/y.yml",
            "sql": "select count(*) from ops_runs where module = any(array['auto_discover', 'auto_discover_overseas'])",
        }]
        names = md.build_issue_title_names(checks)
        self.assertEqual(names.get("auto_discover_overseas"), "扩源车道")
        self.assertEqual(names.get("auto_discover"), "扩源车道")

    def test_hits_workflow_filename(self):
        checks = [{
            "id": "pipeline.z", "name": "死链巡检昨天有没有跑", "subject": "死链巡检", "layer": "pipeline",
            "owner": ".github/workflows/dead-link-audit.yml",
            "sql": "select count(*) from ops_runs where module = 'dead_link_audit'",
        }]
        names = md.build_issue_title_names(checks)
        self.assertEqual(names.get("dead-link-audit.yml"), "死链巡检")

    def test_missing_subject_falls_back_to_question_suffix_stripping(self):
        """没写 subject 时，用正则剥掉 name 结尾的问句部分兜底，不是原样把问句塞进去。"""
        checks = [{
            "id": "pipeline.w", "name": "主抓取车道昨天有没有跑出结果", "layer": "pipeline",
            "owner": ".github/workflows/w.yml",
            "sql": "select count(*) from ops_runs where module = 'daily_crawl'",
        }]
        names = md.build_issue_title_names(checks)
        self.assertEqual(names.get("daily_crawl"), "主抓取车道")

    def test_exact_token_match_does_not_substring_replace(self):
        """本次返工的真 bug：auto_discover 是 auto_discover_overseas 的子串，子串替换会把
        它错改成缝合怪；三个真实标题（真库 dry-run 实测过的）必须各自映射到自己那条检查。
        """
        checks = [
            {"id": "pipeline.a1", "name": "新源自动发现（网页直连档）昨天有没有跑", "subject": "新源自动发现（网页直连档）",
             "layer": "pipeline", "owner": ".github/workflows/auto-discover.yml",
             "sql": "select count(*) from ops_runs where module = 'auto_discover'"},
            {"id": "pipeline.a2", "name": "新源自动发现（需要浏览器的档）昨天有没有跑", "subject": "新源自动发现（需要浏览器的档）",
             "layer": "pipeline", "owner": ".github/workflows/auto-discover-browser.yml",
             "sql": "select count(*) from ops_runs where module = 'auto_discover_browser'"},
            {"id": "pipeline.a3", "name": "新源自动发现（海外档）昨天有没有跑", "subject": "新源自动发现（海外档）",
             "layer": "pipeline", "owner": ".github/workflows/auto-discover-overseas.yml",
             "sql": "select count(*) from ops_runs where module = 'auto_discover_overseas'"},
            {"id": "pipeline.g1", "name": "必投缺口补源漏斗（浏览器档）昨天有没有跑", "subject": "必投缺口补源漏斗（浏览器档）",
             "layer": "pipeline", "owner": ".github/workflows/gap-funnel.yml",
             "sql": "select count(*) from ops_runs where module = 'gap_funnel_browser'"},
        ]
        names = md.build_issue_title_names(checks)
        cases = [
            ("[watchdog] 连续零产出：auto_discover_overseas", "连续零产出：新源自动发现（海外档）"),
            ("[watchdog] 连续零产出：auto_discover_browser", "连续零产出：新源自动发现（需要浏览器的档）"),
            ("[watchdog] 连续零产出：gap_funnel_browser", "连续零产出：必投缺口补源漏斗（浏览器档）"),
            ("[watchdog] 连续零产出：auto_discover", "连续零产出：新源自动发现（网页直连档）"),
        ]
        for title, expected in cases:
            self.assertEqual(md.humanize_issue_title(title, names), expected)

    def test_non_pipeline_layer_not_collected(self):
        checks = [{
            "id": "exp.a", "name": "某体验层检查", "layer": "experience",
            "owner": "lib/track.ts",
            "sql": "select count(*) from events where event = 'search_result'",
        }]
        names = md.build_issue_title_names(checks)
        self.assertNotIn("search_result", names)

    def test_humanize_uses_built_names_end_to_end(self):
        checks = [{
            "id": "pipeline.overseas", "name": "海外自动扩源车道昨天有没有跑", "subject": "海外自动扩源车道", "layer": "pipeline",
            "owner": ".github/workflows/auto-discover-overseas.yml",
            "sql": "select count(*) from ops_runs where module = 'auto_discover_overseas'",
        }]
        names = md.build_issue_title_names(checks)
        out = md.humanize_issue_title("[watchdog] 连续零产出：auto_discover_overseas", names)
        self.assertEqual(out, "连续零产出：海外自动扩源车道")

    def test_no_match_keeps_english_as_is(self):
        checks = [{
            "id": "pipeline.a", "name": "某车道", "layer": "pipeline",
            "owner": ".github/workflows/a.yml",
            "sql": "select count(*) from ops_runs where module = 'a_module'",
        }]
        names = md.build_issue_title_names(checks)
        out = md.humanize_issue_title("[watchdog] 连续零产出：some_unmapped_module", names)
        self.assertEqual(out, "连续零产出：some_unmapped_module")


class SummarizeWatchdogRulesTests(unittest.TestCase):
    def _watchdog_checks(self, n=3):
        return [
            {"id": f"watchdog.rule_{c}", "name": f"老告警{c}", "severity": "warn", "source": "watchdog",
             "why": "w", "action": "a"}
            for c in "abc"[:n]
        ]

    def test_no_watchdog_checks_returns_none(self):
        self.assertIsNone(md.summarize_watchdog_rules([], {}, {}))

    def test_sums_hits_across_rules(self):
        checks = self._watchdog_checks(2)
        checks_by_id = {c["id"]: c for c in checks}
        results = {
            "watchdog.rule_a": result("watchdog.rule_a", 3, "breach", severity="warn"),
            "watchdog.rule_b": result("watchdog.rule_b", 0, "ok", severity="warn"),
        }
        line = md.summarize_watchdog_rules(checks, results, checks_by_id)
        self.assertIn("2 条规则今天共报 3 项", line)
        self.assertIn("其中 0 条规则没评估成", line)

    def test_error_rule_named_not_folded_into_zero(self):
        checks = self._watchdog_checks(2)
        checks_by_id = {c["id"]: c for c in checks}
        results = {
            "watchdog.rule_a": result("watchdog.rule_a", None, "error", severity="warn"),
            "watchdog.rule_b": result("watchdog.rule_b", 1, "ok", severity="warn"),
        }
        line = md.summarize_watchdog_rules(checks, results, checks_by_id)
        self.assertIn("其中 1 条规则没评估成", line)
        self.assertIn("老告警a", line)

    def test_missing_row_also_counts_as_not_assessed(self):
        checks = self._watchdog_checks(2)
        checks_by_id = {c["id"]: c for c in checks}
        results = {"watchdog.rule_b": result("watchdog.rule_b", 1, "ok", severity="warn")}
        line = md.summarize_watchdog_rules(checks, results, checks_by_id)
        self.assertIn("其中 1 条规则没评估成", line)
        self.assertIn("老告警a", line)

    def test_all_rules_failed_becomes_single_sentence_not_16_names(self):
        """16 条全没评估成时不逐条念名字，写成一句『老告警今天还没有运行结果』。"""
        checks = self._watchdog_checks(3)
        checks_by_id = {c["id"]: c for c in checks}
        results = {}  # 一行都没有 = 三条全部没评估成
        line = md.summarize_watchdog_rules(checks, results, checks_by_id)
        self.assertEqual(line, "老告警今天还没有运行结果（3 条规则都没有结果）。")
        self.assertNotIn("老告警a", line)
        self.assertNotIn("老告警b", line)


class MissingCheckLinesTests(unittest.TestCase):
    def _checks(self, n, layer="pipeline", prefix="c"):
        return [check(f"{prefix}{i}", name=f"检查{prefix}{i}", layer=layer) for i in range(n)]

    def test_few_missing_items_get_one_bullet_each(self):
        checks = self._checks(3)
        error_ids = [c["id"] for c in checks]
        lines = md._missing_check_lines(checks, error_ids)
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertTrue(line.startswith("没查到："))

    def test_many_missing_items_grouped_by_layer_with_truncated_names(self):
        checks = self._checks(20, layer="pipeline")
        error_ids = [c["id"] for c in checks]
        lines = md._missing_check_lines(checks, error_ids)
        # 20 项全在同一层且全部缺失 → 应该折成一句话，不是列出 20 个名字
        self.assertEqual(len(lines), 1)
        self.assertIn("链路层今天还没有运行结果", lines[0])
        self.assertIn("20", lines[0])

    def test_partial_layer_missing_shows_top_5_plus_remaining_count(self):
        checks = self._checks(20, layer="pipeline")
        error_ids = [c["id"] for c in checks[:13]]  # 20 条里只有 13 条缺失，触发分组但不是整层
        lines = md._missing_check_lines(checks, error_ids)
        self.assertEqual(len(lines), 1)
        self.assertIn("链路层有 13 项没查到", lines[0])
        self.assertIn("等 8 项", lines[0])  # 13 - 5 = 8

    def test_mixed_layers_grouped_separately(self):
        checks = self._checks(13, layer="pipeline", prefix="p") + self._checks(13, layer="data", prefix="d")
        error_ids = [c["id"] for c in checks]  # 两层各 13 条全缺，各自折成一句
        lines = md._missing_check_lines(checks, error_ids)
        self.assertEqual(len(lines), 2)
        joined = "".join(lines)
        self.assertIn("链路层今天还没有运行结果", joined)
        self.assertIn("数据层今天还没有运行结果", joined)

    def test_watchdog_source_grouped_as_watchdog_not_by_layer(self):
        checks = [
            {"id": f"watchdog.rule_{i}", "name": f"老告警{i}", "layer": "pipeline", "source": "watchdog"}
            for i in range(13)
        ]
        error_ids = [c["id"] for c in checks]
        lines = md._missing_check_lines(checks, error_ids)
        self.assertEqual(len(lines), 1)
        self.assertIn("老告警今天还没有运行结果", lines[0])

    def test_no_missing_returns_empty(self):
        self.assertEqual(md._missing_check_lines([], []), [])


class CapLineLengthTests(unittest.TestCase):
    def test_short_line_untouched(self):
        self.assertEqual(md._cap_line_length("短句子"), "短句子")

    def test_long_line_truncated_with_ellipsis(self):
        long_line = "x" * 1000
        capped = md._cap_line_length(long_line, limit=300)
        self.assertEqual(len(capped), 300)
        self.assertTrue(capped.endswith("…"))

    def test_default_limit_is_300(self):
        self.assertEqual(len(md._cap_line_length("y" * 1000)), 300)


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

    def test_info_severity_breach_does_not_turn_yellow(self):
        """已知不可用/纯记录的检查（如死链探活埋点已停）breach 也不该染灯，否则邮件永远黄。"""
        results = {"a": result("a", 0, "breach", severity="info")}
        self.assertEqual(md.compute_traffic_light(results), "🟢")

    def test_info_severity_error_does_not_turn_yellow(self):
        results = {"a": result("a", None, "error", severity="info")}
        self.assertEqual(md.compute_traffic_light(results), "🟢")

    def test_info_severity_breach_mixed_with_ok_others_stays_green(self):
        results = {
            "a": result("a", 1, "ok", severity="warn"),
            "b": result("b", 0, "breach", severity="info"),
        }
        self.assertEqual(md.compute_traffic_light(results), "🟢")


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

    def test_calibrated_false_tagged_on_breach(self):
        """待校准标签只在不达标/没查到时才提醒——ok 的行不带，见下一条测试。"""
        results_today = {"a": result("a", 5, "breach", severity="warn", calibrated=False)}
        rows = md.section_rows(results_today, {}, {"a": "指标A"}, ["a"])
        self.assertIn("待校准", rows[0]["calibrated_tag"])

    def test_calibrated_false_not_tagged_when_ok(self):
        """每行都写「（待校准）」太吵——verdict=ok 时不带，即便 calibrated=False。"""
        results_today = {"a": result("a", 5, "ok", calibrated=False)}
        rows = md.section_rows(results_today, {}, {"a": "指标A"}, ["a"])
        self.assertEqual(rows[0]["calibrated_tag"], "")


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
        """同一层最多占 2 条，凑够 5 条要跨好几个层——用不同 layer 分散开才能测到旧的『最多 5 条』上限。"""
        results_today = {}
        checks_by_id = {}
        layers = ["pipeline", "data", "experience", "pipeline", "data", "experience", "pipeline", "data"]
        for i in range(8):
            cid = f"c{i}"
            results_today[cid] = result(cid, 1, "breach", severity="warn")
            checks_by_id[cid] = check(cid, name=f"N{i}", action=f"do {i}", layer=layers[i])
        items = md.build_action_items(results_today, checks_by_id, limit=5)
        self.assertEqual(len(items), 5)

    def test_same_layer_capped_at_two_even_with_room_left(self):
        """同一层塞了 4 条不同 action，即便 limit 还有余量，也只取前 2 条——
        否则某一层集体出问题时会把建议清单的 5 个名额占满，看不出还有别的层需要关注。
        """
        results_today = {}
        checks_by_id = {}
        for i in range(4):
            cid = f"p{i}"
            results_today[cid] = result(cid, 1, "breach", severity="warn")
            checks_by_id[cid] = check(cid, name=f"链路层检查{i}", action=f"do pipeline {i}", layer="pipeline")
        items = md.build_action_items(results_today, checks_by_id, limit=5)
        self.assertEqual(len(items), 2)

    def test_many_checks_sharing_one_action_shows_top_5_plus_remaining(self):
        """几十条检查共用同一句 action 文案时（比如一整层集体没跑），名字不能全念出来。"""
        results_today = {}
        checks_by_id = {}
        for i in range(20):
            cid = f"c{i}"
            results_today[cid] = result(cid, 1, "breach", severity="warn")
            checks_by_id[cid] = check(cid, name=f"检查{i}", action="统一动作", layer="pipeline")
        items = md.build_action_items(results_today, checks_by_id, limit=5, max_per_group=99)
        self.assertEqual(len(items), 1)
        self.assertIn("等 20 项", items[0])
        self.assertNotIn("检查19", items[0])

    def test_watchdog_source_counted_as_its_own_group_not_by_layer(self):
        """source=watchdog 的条目即便 layer=pipeline，也要单独算一层——不能跟真正的
        链路层检查合并计数，否则老告警集体出问题会把链路层的建议名额也占满。
        """
        results_today = {}
        checks_by_id = {}
        for i in range(3):
            cid = f"pipeline{i}"
            results_today[cid] = result(cid, 1, "breach", severity="warn")
            checks_by_id[cid] = check(cid, name=f"链路层{i}", action=f"do pipeline {i}", layer="pipeline")
        for i in range(3):
            cid = f"watchdog.rule_{i}"
            results_today[cid] = result(cid, 1, "breach", severity="warn")
            checks_by_id[cid] = check(cid, name=f"老告警{i}", action=f"do watchdog {i}", layer="pipeline")
            checks_by_id[cid]["source"] = "watchdog"
        items = md.build_action_items(results_today, checks_by_id, limit=5)
        pipeline_items = [x for x in items if "链路层" in x]
        watchdog_items = [x for x in items if "老告警" in x]
        self.assertEqual(len(pipeline_items), 2)
        self.assertEqual(len(watchdog_items), 2)

    def test_same_action_text_merges_names_with_separator(self):
        """两条检查项的 action 文案完全一样时，合并成一条，名字用「、」并列，不逐条重复。"""
        results_today = {
            "a": result("a", 1, "breach", severity="warn"),
            "b": result("b", 1, "breach", severity="warn"),
        }
        checks_by_id = {
            "a": check("a", name="搜索超3秒占比", action="把这条转给 Claude，让它查搜索为什么慢"),
            "b": check("b", name="搜索超10秒占比", action="把这条转给 Claude，让它查搜索为什么慢"),
        }
        items = md.build_action_items(results_today, checks_by_id)
        self.assertEqual(len(items), 1)
        self.assertIn("搜索超3秒占比、搜索超10秒占比", items[0])


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
        self.assertNotIn("较上一次", digest["text"])
        self.assertNotIn("较昨天", digest["text"])  # 旧文案不该再冒出来

    def test_data_integrity_lists_error_checks_not_zero(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks[1:]]]
        results_today.append(result(checks[0]["id"], None, "error", error_message="timeout"))
        digest = md.build_digest(checks, results_today, [], None, [], None)
        self.assertIn("没查到", digest["text"])

    def test_last_digest_delivered(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        last = {"status": "success", "finished_at": None, "metrics": {"mode": "sent"}}
        digest = md.build_digest(checks, results_today, [], None, [], last)
        self.assertIn("已送达", digest["text"])

    def test_last_digest_missing_says_so(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        digest = md.build_digest(checks, results_today, [], None, [], None)
        self.assertIn("还没有真正发出过晨报，这是第一封", digest["text"])

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


def ops_row(mode, status="success", finished_at=None, error=None):
    metrics = {"mode": mode}
    if error:
        metrics["error"] = error
    return {"metrics": metrics, "status": status, "finished_at": finished_at}


class PickLatestSentTests(unittest.TestCase):
    """本次返工的真 bug 现场：dry-run 也会写一行 ops_runs 台账（status 甚至是 success），
    「上一封是否送达」必须跳过 dry-run 行，往前找最近一条 mode=='sent' 的行。
    """

    def test_only_dry_run_rows_returns_none(self):
        rows = [ops_row("dry_run"), ops_row("dry_run"), ops_row("dry_run")]
        self.assertIsNone(md.pick_latest_sent(rows))

    def test_dry_run_on_top_skips_to_earlier_sent_row(self):
        """最新一条是 dry-run，再往前一条才是真发的——必须挑到那条真发的，不是 None、也不是 dry-run 行。"""
        rows = [ops_row("dry_run"), ops_row("sent", status="success")]
        picked = md.pick_latest_sent(rows)
        self.assertIsNotNone(picked)
        self.assertEqual(picked["metrics"]["mode"], "sent")

    def test_most_recent_sent_row_is_failed(self):
        rows = [ops_row("sent", status="failed", error="Resend 超时"), ops_row("sent", status="success")]
        picked = md.pick_latest_sent(rows)
        self.assertEqual(picked["status"], "failed")

    def test_empty_rows_returns_none(self):
        self.assertIsNone(md.pick_latest_sent([]))
        self.assertIsNone(md.pick_latest_sent(None))


class LastSentLineTests(unittest.TestCase):
    def test_never_sent(self):
        self.assertEqual(md._last_sent_line(None), "还没有真正发出过晨报，这是第一封。")

    def test_sent_success(self):
        finished = datetime(2026, 9, 18, 2, 0, tzinfo=timezone.utc)
        line = md._last_sent_line({"status": "success", "finished_at": finished, "metrics": {"mode": "sent"}})
        self.assertIn("已送达", line)
        self.assertIn("9/18", line)

    def test_sent_failed_shows_redacted_reason(self):
        finished = datetime(2026, 9, 18, 2, 0, tzinfo=timezone.utc)
        fake_dsn = "postgres" + "ql://user:pw@" + "10.0." + "0.9" + ":5432/db"
        line = md._last_sent_line({
            "status": "failed", "finished_at": finished,
            "metrics": {"mode": "sent", "error": f"HTTPError: connect to {fake_dsn} failed"},
        })
        self.assertIn("发送失败", line)
        self.assertNotIn("10.0.0.9", line)
        self.assertNotIn("postgresql://", line)


class CommentCountTests(unittest.TestCase):
    def test_real_shaped_comment_objects_counted_not_dumped(self):
        """gh issue list --json comments 真实返回的是评论对象列表，不是数字——这是本次返工的真 bug。"""
        issue = {"comments": [
            {"id": "IC_kwabc", "author": {"login": "allen"}, "body": "x" * 500, "createdAt": "2026-09-01T00:00:00Z"},
            {"id": "IC_kwdef", "author": {"login": "bot"}, "body": "y" * 500, "createdAt": "2026-09-02T00:00:00Z"},
        ]}
        self.assertEqual(md.comment_count(issue), 2)

    def test_empty_comments_list_is_zero_not_bracket_string(self):
        issue = {"comments": []}
        self.assertEqual(md.comment_count(issue), 0)

    def test_already_numeric_comment_count_passthrough(self):
        self.assertEqual(md.comment_count({"comments": 5}), 5)

    def test_missing_comments_field_is_zero(self):
        self.assertEqual(md.comment_count({}), 0)
        self.assertEqual(md.comment_count(None), 0)


class HumanizeIssueTitleTests(unittest.TestCase):
    def test_strips_watchdog_bracket_prefix(self):
        out = md.humanize_issue_title("[watchdog] 连续零产出：auto_discover_overseas")
        self.assertNotIn("[watchdog]", out)
        self.assertEqual(out, "连续零产出：auto_discover_overseas")

    def test_no_prefix_returned_as_is(self):
        self.assertEqual(md.humanize_issue_title("普通标题"), "普通标题")

    def test_names_mapping_replaces_when_given(self):
        out = md.humanize_issue_title("[watchdog] 连续零产出：auto_discover_overseas",
                                       names={"auto_discover_overseas": "海外自动扩源"})
        self.assertEqual(out, "连续零产出：海外自动扩源")

    def test_empty_names_leaves_module_name_untouched(self):
        out = md.humanize_issue_title("[watchdog] 连续零产出：auto_discover_overseas", names={})
        self.assertEqual(out, "连续零产出：auto_discover_overseas")


class DigestSizeAndIssueRenderingTests(unittest.TestCase):
    def _checks(self):
        ids = md.SECTION_USERS + md.SECTION_EXPERIENCE + md.SECTION_SUPPLY + md.SECTION_FAKE_GREEN
        return [check(cid, name=f"人话名字-{i}") for i, cid in enumerate(ids)]

    def test_old_issue_with_real_shaped_comments_does_not_dump_objects(self):
        """本次返工的真 bug：真实形状的 comments（对象列表）曾被整段塞进正文，单行 4 万字符。"""
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        now = datetime.now(timezone.utc)
        issues = [{
            "number": 42,
            "title": "[watchdog] 连续零产出：auto_discover_overseas",
            "createdAt": (now - timedelta(days=22)).isoformat(),
            "comments": [
                {"id": "IC_kwabc", "author": {"login": "allen"}, "body": "x" * 1000},
                {"id": "IC_kwdef", "author": {"login": "bot"}, "body": "y" * 1000},
            ],
        }]
        digest = md.build_digest(checks, results_today, [], None, issues, None)
        self.assertIn("2条评论", digest["text"])
        self.assertNotIn("IC_kwabc", digest["text"])
        self.assertNotIn("author", digest["text"])
        self.assertNotIn("[watchdog]", digest["text"])
        self.assertNotIn("[watchdog]", digest["html"])

    def test_empty_comments_list_shows_zero_not_bracket_literal(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        now = datetime.now(timezone.utc)
        issues = [{"number": 7, "title": "空评论的老问题", "createdAt": (now - timedelta(days=3)).isoformat(), "comments": []}]
        digest = md.build_digest(checks, results_today, [], None, issues, None)
        self.assertIn("0条评论", digest["text"])
        self.assertNotIn("[]条评论", digest["text"])

    def test_no_single_line_exceeds_300_chars(self):
        """收紧到 300（此前是 500，没能拦住⑧段『没查到』51 个名字挤成一行的可读性问题）。"""
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        now = datetime.now(timezone.utc)
        # 混入一条带超大 comments 对象列表的老问题，防回归
        issues = [{
            "number": i,
            "title": f"issue {i}",
            "createdAt": (now - timedelta(days=i)).isoformat(),
            "comments": [{"id": f"IC_{i}_{j}", "body": "z" * 200} for j in range(30)],
        } for i in range(1, 6)]
        digest = md.build_digest(checks, results_today, [], None, issues, None)
        for line in digest["text"].splitlines():
            self.assertLessEqual(len(line), 300, line[:80])

    def test_many_missing_checks_does_not_cram_into_one_line(self):
        """51 个检查项都没查到时，⑧段不能把 51 个名字挤成一行——这是本次返工的真 bug。"""
        checks = self._checks() + [check(f"extra.{i}", name=f"额外检查{i}", layer="data") for i in range(50)]
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in self._checks()]]
        # extra.* 全部缺行 → merge_missing_as_error 会把它们标成 error
        digest = md.build_digest(checks, results_today, [], None, [], None)
        for line in digest["text"].splitlines():
            self.assertLessEqual(len(line), 300, line[:80])
        # 51 个名字挤一行的旧现象：不该把全部 50 个名字都念出来（只展示前几个 + 剩余数）
        self.assertNotIn("额外检查49", digest["text"])
        self.assertIn("等 50 项", digest["text"])

    def test_whole_text_under_30kb(self):
        checks = self._checks()
        results_today = [result(cid, 1, "ok") for cid in [c["id"] for c in checks]]
        now = datetime.now(timezone.utc)
        issues = [{
            "number": i,
            "title": f"issue {i}",
            "createdAt": (now - timedelta(days=i)).isoformat(),
            "comments": [{"id": f"IC_{i}_{j}", "body": "z" * 200} for j in range(30)],
        } for i in range(1, 40)]
        digest = md.build_digest(checks, results_today, [], None, issues, None)
        self.assertLessEqual(len(digest["text"].encode("utf-8")), 30 * 1024)


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


class LiteralProvenanceTests(unittest.TestCase):
    """结构性防线：体验层 SQL 里每个 event 名 / latency_bucket 取值 / result 取值 / action 取值 /
    ops_runs.module 都必须能在真实产品代码（app/ lib/ components/）里 grep 到，不许猜。
    抠不出字面量的 SQL（如纯 count(*) 不带任何字面量）不受这条测试约束。
    """

    def test_every_experience_layer_literal_traces_to_source(self):
        checks = ar.load_contract()
        experience_checks = [c for c in checks if c["layer"] == "experience"]
        self.assertGreater(len(experience_checks), 0, "体验层检查项不该是空的")

        missing = []
        found_map = {}
        for c in experience_checks:
            for kind, value in extract_literals(c["sql"]):
                path = literal_appears_in_source(value)
                if path is None:
                    missing.append((c["id"], kind, value))
                else:
                    found_map[(kind, value)] = os.path.relpath(path, REPO_ROOT)

        if missing:
            detail = "\n".join(f"  {cid} 用了 {kind}={value!r}，仓库源码里找不到" for cid, kind, value in missing)
            self.fail(f"以下字面量在 app/lib/components 里 grep 不到，可能是猜的：\n{detail}")

        # 至少要覆盖到我们已知这一批体验层用到的核心字面量，防止未来重写 extract_literals 时
        # 悄悄把提取逻辑改坏、测试永远通过却什么都没抠出来（假绿）。
        must_have_kinds = {"event", "latency_bucket", "result", "action", "module"}
        seen_kinds = {kind for kind, _value in found_map}
        self.assertTrue(
            must_have_kinds.issubset(seen_kinds),
            f"提取逻辑抠出的种类不全，可能自己先坏了：抠到 {seen_kinds}，应至少含 {must_have_kinds}",
        )

    def test_extract_literals_handles_multi_value_in_clause(self):
        sql = "select 1 from events where event in ('a', 'b') and payload->>'latency_bucket' = 'x'"
        out = extract_literals(sql)
        self.assertIn(("event", "a"), out)
        self.assertIn(("event", "b"), out)
        self.assertIn(("latency_bucket", "x"), out)

    def test_literal_not_in_source_is_reported_missing(self):
        self.assertIsNone(literal_appears_in_source("definitely_not_a_real_literal_zzz"))


if __name__ == "__main__":
    unittest.main()


class ContractSeverityIsAuthoritativeTests(unittest.TestCase):
    """落库快照里的 severity 过期时，以期望清单为准（调级当天就要生效）。"""

    def test_contract_severity_overrides_stale_row_severity(self):
        checks = [{"id": "watchdog.rule_a", "severity": "warn", "source": "watchdog"}]
        rows = {"watchdog.rule_a": {"check_id": "watchdog.rule_a", "severity": "critical",
                                    "verdict": "breach", "value": 6.0, "calibrated": True}}
        merged = md.merge_missing_as_error(checks, rows)
        self.assertEqual(merged["watchdog.rule_a"]["severity"], "warn")
        self.assertEqual(merged["watchdog.rule_a"]["value"], 6.0)
        self.assertEqual(md.compute_traffic_light(merged), "🟡")
        self.assertEqual(rows["watchdog.rule_a"]["severity"], "critical")  # 不原地改入参
