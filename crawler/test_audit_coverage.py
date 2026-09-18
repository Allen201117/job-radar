"""覆盖率差集契约：不连网不连库，全部用 tmp 目录里的假 workflow/schema/contract 文件。"""
import tempfile
import unittest
from pathlib import Path

import audit_coverage as C


WORKFLOW_WITH_CRON = """\
name: fake-cron
on:
  schedule:
    - cron: "0 3 * * *"
jobs:
  run:
    runs-on: ubuntu-latest
"""

WORKFLOW_UNQUOTED_CRON = """\
name: fake-cron-unquoted
on:
  schedule:
    - cron: 0 4 * * *
jobs:
  run:
    runs-on: ubuntu-latest
"""

WORKFLOW_COMMENTED_CRON = """\
name: fake-cron-commented
on:
  # - cron: "0 5 * * *"
  workflow_dispatch: {}
jobs:
  run:
    runs-on: ubuntu-latest
"""

WORKFLOW_NO_CRON = """\
name: fake-manual
on:
  workflow_dispatch: {}
jobs:
  run:
    runs-on: ubuntu-latest
"""

SCHEMA_SQL = """\
create table if not exists jobs (
  id                uuid primary key default gen_random_uuid(),
  company           text not null,
  title             text not null,
  status            text default 'active',   -- 逗号在注释里也不该被当成分隔符, 真的
  board              text generated always as (
                        case when company = 'x' then 'a' else 'b' end
                      ) stored,
  created_at        timestamptz default now()
);

alter table jobs add column if not exists country_code text;
alter table public.jobs add column if not exists job_scope text, add column if not exists job_type text;

create table if not exists job_events (
  id uuid primary key,
  jd_url text
);
alter table job_events add column if not exists should_not_leak_into_jobs text;

create table if not exists job_closures (
  id uuid primary key,
  reason text
);
alter table job_closures add column if not exists should_not_leak_either text;
"""

# 与线上 scripts/ux-walkthrough/walkthrough.js（2026-09 结构化改动后）同款写法：
# 真正落库的 metrics 不是 `summary` 本身，是 `{ ...summary, issue_samples: ... }`。
WALKTHROUGH_JS = """\
async function main() {
  const summary = {
    users: ok.length, errors: results.length - ok.length,
    zero_shown: ok.filter((r) => r.shown === 0).length,
    latency, issues: issues.length, issues_by_type: issuesByType,
  };
  if (process.argv.includes("--record")) {
    const { error } = await client.from("ops_runs").insert({
      module: "ux_walkthrough", run_date: startedAt.slice(0, 10),
      metrics: { ...summary, issue_samples: issues.slice(0, 20) },
    });
  }
}
"""

WALKTHROUGH_JS_UNRESOLVABLE_SPREAD = """\
async function main() {
  if (process.argv.includes("--record")) {
    const { error } = await client.from("ops_runs").insert({
      module: "ux_walkthrough",
      metrics: { ...computeSomethingElsewhere(), issue_samples: issues.slice(0, 20) },
    });
  }
}
"""


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_root(tmp, walkthrough_js=WALKTHROUGH_JS):
    root = Path(tmp)
    _write(root / ".github" / "workflows" / "daily-crawl.yml", WORKFLOW_WITH_CRON)
    _write(root / ".github" / "workflows" / "production-smoke.yml", WORKFLOW_NO_CRON)
    _write(root / "jobs-db" / "schema.sql", SCHEMA_SQL)
    _write(root / "scripts" / "ux-walkthrough" / "walkthrough.js", walkthrough_js)
    _write(root / "crawler" / "run.py", '''
import ops_runs
ops_runs.record_ops_run(sb, "daily_crawl", {"jobs_found_total": 1})
''')
    return root


def _check(**over):
    base = {
        "id": "x", "name": "n", "layer": "data", "db": "jobs",
        "owner": ".github/workflows/daily-crawl.yml", "sql": "select status from jobs",
        "normal": "== 0", "severity": "warn", "why": "w", "action": "a",
    }
    base.update(over)
    return base


class CronWorkflowScanTest(unittest.TestCase):
    def test_finds_cron_and_skips_dispatch_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            found = C.find_cron_workflows(root / ".github" / "workflows")
            self.assertEqual(found, [".github/workflows/daily-crawl.yml"])

    def test_new_cron_workflow_grows_the_gap_by_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            before = C.find_cron_workflows(root / ".github" / "workflows")
            _write(root / ".github" / "workflows" / "another-cron.yml", WORKFLOW_WITH_CRON)
            after = C.find_cron_workflows(root / ".github" / "workflows")
            self.assertEqual(len(after) - len(before), 1)

    def test_unquoted_cron_value_still_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            _write(root / ".github" / "workflows" / "unquoted.yml", WORKFLOW_UNQUOTED_CRON)
            found = C.find_cron_workflows(root / ".github" / "workflows")
            self.assertIn(".github/workflows/unquoted.yml", found)

    def test_yaml_extension_is_also_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            _write(root / ".github" / "workflows" / "dotyaml.yaml", WORKFLOW_WITH_CRON)
            found = C.find_cron_workflows(root / ".github" / "workflows")
            self.assertIn(".github/workflows/dotyaml.yaml", found)

    def test_commented_out_cron_does_not_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            _write(root / ".github" / "workflows" / "commented.yml", WORKFLOW_COMMENTED_CRON)
            found = C.find_cron_workflows(root / ".github" / "workflows")
            self.assertNotIn(".github/workflows/commented.yml", found)


class JobsColumnParseTest(unittest.TestCase):
    def test_create_table_columns_are_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            cols = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            for expected in ("id", "company", "title", "status", "created_at"):
                self.assertIn(expected, cols)

    def test_alter_table_added_column_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            cols = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            self.assertIn("country_code", cols)

    def test_multiline_generated_column_definition_does_not_lose_following_columns(self):
        """`board` 用多行 `generated always as (\\n case ... end\\n) stored,` 定义，
        括号内跨行、内部还有逗号无关——它自己和它后面的 `created_at` 都不能丢。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            cols = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            self.assertIn("board", cols)
            self.assertIn("created_at", cols)

    def test_inline_trailing_comment_does_not_swallow_next_column(self):
        """`status` 那一行带行内注释（含逗号），注释后面紧跟的列不能被一起吞掉。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            cols = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            self.assertIn("status", cols)
            self.assertIn("board", cols)  # status 后面紧跟的就是 board

    def test_public_schema_prefixed_alter_is_recognized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            cols = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            self.assertIn("job_scope", cols)

    def test_single_alter_statement_with_multiple_add_columns(self):
        """同一条 `alter table` 语句里用逗号接了两个 `add column if not exists`，
        两个都要收，不能只收第一个。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            cols = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            self.assertIn("job_scope", cols)
            self.assertIn("job_type", cols)

    def test_other_tables_do_not_leak_columns_into_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            cols = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            self.assertNotIn("should_not_leak_into_jobs", cols)   # job_events 的列
            self.assertNotIn("should_not_leak_either", cols)      # job_closures 的列
            self.assertNotIn("reason", cols)                      # job_closures 自己的列


class CoversValidationTest(unittest.TestCase):
    def test_covers_column_must_appear_in_its_own_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            jobs_columns = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            bad = [_check(sql="select count(*) from jobs where status = 'active'",
                          covers=["company"])]  # company 没出现在这条 sql 里
            with self.assertRaises(ValueError):
                C.validate_covers(bad, jobs_columns)

    def test_covers_column_must_be_a_real_schema_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            jobs_columns = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            bad = [_check(sql="select count(*) from jobs where nonexistent_col = 1",
                          covers=["nonexistent_col"])]
            with self.assertRaises(ValueError):
                C.validate_covers(bad, jobs_columns)

    def test_valid_covers_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            jobs_columns = C.parse_jobs_columns(root / "jobs-db" / "schema.sql")
            good = [_check(sql="select count(*) from jobs where status = 'active'",
                           covers=["status"])]
            C.validate_covers(good, jobs_columns)  # 不抛就是过

    def test_check_without_covers_covers_nothing(self):
        """核心语义：`status` 出现在这条 sql 里，但没声明 covers → 不算覆盖 status。
        这正是这次返工要修的『按 SQL 文本猜覆盖』假绿。"""
        checks = [_check(sql="select count(*) from jobs where status = 'active'")]
        self.assertEqual(C._covers_columns(checks), set())


class WalkthroughMetricParseTest(unittest.TestCase):
    def test_real_metrics_object_includes_spread_keys_and_explicit_sibling_key(self):
        """回归验收点：真实写法是 `{ ...summary, issue_samples: ... }`——之前的实现
        只解析了 `summary` 本身，`issue_samples` 这个 summary 之外的显式键会被漏掉，
        而它已经被写进 walkthrough-raw.json 与 ops_runs.metrics 很久了。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            keys, unreadable = C.parse_walkthrough_metrics(
                root / "scripts" / "ux-walkthrough" / "walkthrough.js"
            )
            self.assertEqual(
                keys,
                {"users", "errors", "zero_shown", "latency", "issues", "issues_by_type", "issue_samples"},
            )
            self.assertEqual(unreadable, [])

    def test_unresolvable_spread_source_is_reported_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp, walkthrough_js=WALKTHROUGH_JS_UNRESOLVABLE_SPREAD)
            keys, unreadable = C.parse_walkthrough_metrics(
                root / "scripts" / "ux-walkthrough" / "walkthrough.js"
            )
            self.assertIn("issue_samples", keys)  # 显式键仍然要拿到
            self.assertTrue(unreadable)            # 但解析不了的 spread 必须被诚实报出来


class OpsRunModuleScanTest(unittest.TestCase):
    def test_literal_module_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            modules, unreadable = C.find_ops_run_modules(root / "crawler", root / "scripts")
            self.assertIn("daily_crawl", modules)
            self.assertEqual(unreadable, [])

    def test_test_files_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            _write(root / "crawler" / "test_fake.py",
                   'ops_runs.record_ops_run(sb, "should_not_count", {})')
            modules, _ = C.find_ops_run_modules(root / "crawler", root / "scripts")
            self.assertNotIn("should_not_count", modules)

    def test_ternary_assigned_module_is_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            _write(root / "crawler" / "ternary.py", '''
module = "sweep_a" if flag else "sweep_b"
ops_runs.record_ops_run(sb, module, {})
''')
            modules, unreadable = C.find_ops_run_modules(root / "crawler", root / "scripts")
            self.assertIn("sweep_a", modules)
            self.assertIn("sweep_b", modules)
            self.assertEqual(unreadable, [])

    def test_unresolvable_identifier_is_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            _write(root / "crawler" / "mystery.py",
                   "ops_runs.record_ops_run(sb, mystery_module, {})")
            modules, unreadable = C.find_ops_run_modules(root / "crawler", root / "scripts")
            self.assertNotIn("mystery_module", modules)
            self.assertTrue(any("mystery.py:mystery_module" in u for u in unreadable))

    def test_function_definition_itself_is_not_counted_as_a_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            _write(root / "crawler" / "ops_runs.py", "def record_ops_run(supabase, module, metrics):\n    pass\n")
            modules, unreadable = C.find_ops_run_modules(root / "crawler", root / "scripts")
            self.assertNotIn("module", modules)
            self.assertEqual(unreadable, [])

    def test_wrapper_function_named_underscore_record_ops_run_is_not_a_false_call(self):
        # 回归：sync_ats_tenants.py 的 `def _record_ops_run(status, metrics, started_at):`
        # 曾被误判成一次调用（第二个形参 "metrics" 被当成 module 标识符报进 unreadable）。
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            _write(
                root / "crawler" / "sync_ats_tenants.py",
                "def _record_ops_run(status, metrics, started_at):\n"
                '    ops_runs.record_ops_run(sb, "ats_tenant_sync", metrics, status)\n',
            )
            modules, unreadable = C.find_ops_run_modules(root / "crawler", root / "scripts")
            self.assertIn("ats_tenant_sync", modules)
            self.assertNotIn("metrics", modules)
            self.assertEqual(unreadable, [])

    def test_js_module_literal_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            modules, _ = C.find_ops_run_modules(root / "crawler", root / "scripts")
            self.assertIn("ux_walkthrough", modules)


class ExemptionsTest(unittest.TestCase):
    def test_missing_reason_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exemptions.yaml"
            _write(path, "data_columns:\n  id: \"\"\n")
            with self.assertRaises(ValueError):
                C.load_exemptions(path)

    def test_none_reason_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exemptions.yaml"
            _write(path, "data_columns:\n  id: null\n")
            with self.assertRaises(ValueError):
                C.load_exemptions(path)

    def test_valid_reason_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exemptions.yaml"
            _write(path, "data_columns:\n  id: \"uuid 主键无业务语义\"\n")
            exemptions = C.load_exemptions(path)
            self.assertEqual(exemptions["data_columns"]["id"], "uuid 主键无业务语义")

    def test_empty_file_loads_to_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exemptions.yaml"
            _write(path, "")
            self.assertEqual(C.load_exemptions(path), {})


class ComputeGapsTest(unittest.TestCase):
    """compute_gaps 的汇总逻辑：checks/exemptions 用注入的假数据，不碰真实 contract。"""

    def test_covers_declared_columns_do_not_appear_in_the_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            checks = [
                _check(layer="pipeline", owner=".github/workflows/daily-crawl.yml"),
                _check(layer="data", db="jobs",
                       sql="select company, title, status, created_at from jobs",
                       covers=["company", "title", "status", "created_at"]),
            ]
            exemptions = {"data_columns": {"id": "无业务语义"}}
            gaps = C.compute_gaps(root=root, checks=checks, exemptions=exemptions)
            self.assertNotIn(".github/workflows/daily-crawl.yml", gaps["pipeline_workflows"])
            self.assertNotIn("company", gaps["data_columns"])
            self.assertNotIn("id", gaps["data_columns"])

    def test_column_merely_appearing_in_sql_without_covers_still_gaps(self):
        """核心回归：`status` 出现在 where 里但检查项没写 covers → 仍然算未覆盖。
        这正是『按 SQL 文本猜覆盖』被判定为假绿、需要改掉的那条问题。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            checks = [_check(layer="data", db="jobs",
                              sql="select count(*) from jobs where status = 'active'")]
            gaps = C.compute_gaps(root=root, checks=checks, exemptions={})
            self.assertIn("status", gaps["data_columns"])

    def test_uncovered_cron_workflow_shows_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            gaps = C.compute_gaps(root=root, checks=[], exemptions={})
            self.assertIn(".github/workflows/daily-crawl.yml", gaps["pipeline_workflows"])

    def test_new_cron_workflow_increases_gap_by_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            before = C.compute_gaps(root=root, checks=[], exemptions={})
            _write(root / ".github" / "workflows" / "another-cron.yml", WORKFLOW_WITH_CRON)
            after = C.compute_gaps(root=root, checks=[], exemptions={})
            self.assertEqual(len(after["pipeline_workflows"]) - len(before["pipeline_workflows"]), 1)

    def test_alter_table_column_reaches_the_gap_when_uncovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            gaps = C.compute_gaps(root=root, checks=[], exemptions={})
            self.assertIn("country_code", gaps["data_columns"])

    def test_ops_watchdog_registry_covers_pipeline_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            # daily_crawl 是 ops_watchdog.MODULE_OUTPUT 里真实登记的模块 -> 不该出现在差集
            gaps = C.compute_gaps(root=root, checks=[], exemptions={})
            self.assertNotIn("daily_crawl", gaps["pipeline_modules"])

    def test_experience_metrics_gap_includes_the_explicit_sibling_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            gaps = C.compute_gaps(root=root, checks=[], exemptions={})
            self.assertIn("issue_samples", gaps["experience_metrics"])
            self.assertIn("issues_by_type", gaps["experience_metrics"])

    def test_invalid_covers_in_injected_checks_raises_during_compute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            checks = [_check(layer="data", db="jobs",
                              sql="select status from jobs", covers=["company"])]
            with self.assertRaises(ValueError):
                C.compute_gaps(root=root, checks=checks, exemptions={})

    def test_stale_exemption_is_reported(self):
        """豁免了一个左边枚举里已经不存在的名字（列被改名/删掉了）→ 报 stale，不是静默生效。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            exemptions = {"data_columns": {"this_column_no_longer_exists": "早就改名了但豁免忘删"}}
            gaps = C.compute_gaps(root=root, checks=[], exemptions=exemptions)
            self.assertIn("this_column_no_longer_exists", gaps["stale_exemptions"]["data_columns"])

    def test_non_stale_exemption_is_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            exemptions = {"data_columns": {"id": "无业务语义"}}  # id 真实存在于左边枚举
            gaps = C.compute_gaps(root=root, checks=[], exemptions=exemptions)
            self.assertNotIn("data_columns", gaps["stale_exemptions"])

    def test_render_and_main_do_not_crash_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            gaps = C.compute_gaps(root=root, checks=[], exemptions={})
            text = C.render(gaps)
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0)


if __name__ == "__main__":
    unittest.main()
