"""覆盖率差集契约：不连网不连库，全部用 tmp 目录里的假 workflow/schema/contract 文件。"""
import os
import shutil
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
  status            text default 'active',
  created_at        timestamptz default now()
);

alter table jobs add column if not exists country_code text;
"""

WALKTHROUGH_JS = """\
async function main() {
  const summary = {
    users: ok.length, errors: results.length - ok.length,
    zero_shown: ok.filter((r) => r.shown === 0).length,
    latency, issues: issues.length,
  };
  if (process.argv.includes("--record")) {
    const { error } = await client.from("ops_runs").insert({
      module: "ux_walkthrough", run_date: startedAt.slice(0, 10),
      metrics: { ...summary },
    });
  }
}
"""


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_root(tmp):
    root = Path(tmp)
    _write(root / ".github" / "workflows" / "daily-crawl.yml", WORKFLOW_WITH_CRON)
    _write(root / ".github" / "workflows" / "production-smoke.yml", WORKFLOW_NO_CRON)
    _write(root / "jobs-db" / "schema.sql", SCHEMA_SQL)
    _write(root / "scripts" / "ux-walkthrough" / "walkthrough.js", WALKTHROUGH_JS)
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


class WalkthroughMetricParseTest(unittest.TestCase):
    def test_top_level_keys_including_shorthand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            keys = C.parse_walkthrough_metrics(root / "scripts" / "ux-walkthrough" / "walkthrough.js")
            self.assertEqual(keys, {"users", "errors", "zero_shown", "latency", "issues"})


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

    def test_covered_things_do_not_appear_in_the_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            checks = [_check(layer="pipeline", owner=".github/workflows/daily-crawl.yml"),
                      _check(layer="data", db="jobs", sql="select company, title, status, created_at from jobs")]
            exemptions = {"data_columns": {"id": "无业务语义"}}
            gaps = C.compute_gaps(root=root, checks=checks, exemptions=exemptions)
            self.assertNotIn(".github/workflows/daily-crawl.yml", gaps["pipeline_workflows"])
            self.assertNotIn("company", gaps["data_columns"])
            self.assertNotIn("id", gaps["data_columns"])

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

    def test_render_and_main_do_not_crash_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            gaps = C.compute_gaps(root=root, checks=[], exemptions={})
            text = C.render(gaps)
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0)


if __name__ == "__main__":
    unittest.main()
