"""crawl_runs 生命周期契约：占位符必须是 running，且 running 只能是占位符。

背景（2026-09-05，迁移 234）：create_crawl_run 原来用 'skipped' 当占位符 —— 进程中途死掉时
这行就永远停在 skipped，与 robots 拦截 / adapter.should_skip 主动跳过在 status 上完全无法区分，
全表 72 条孤儿因此冒充「按设计跳过」躺了三个月。这里把「不许再退回去」钉死。
"""
import re
import unittest
from pathlib import Path

import db

ROOT = Path(__file__).resolve().parents[1]


class _FakeTable:
    def __init__(self, sink):
        self.sink = sink

    def insert(self, payload):
        self.sink.append(payload)
        return self

    def execute(self):
        return None


class _FakeSupabase:
    def __init__(self):
        self.inserts = []

    def table(self, name):
        assert name == "crawl_runs"
        return _FakeTable(self.inserts)


class CrawlRunPlaceholderTest(unittest.TestCase):
    def test_placeholder_status_is_running_not_skipped(self):
        sb = _FakeSupabase()
        run_id = db.create_crawl_run(sb, "source-1")
        [payload] = sb.inserts
        self.assertEqual(payload["status"], "running")
        # skipped 是「按设计跳过」的终态，必须带 finished_at + error_message 才写得出来；
        # 拿它当占位符 = 让「跑崩了」冒充「跳过」。
        self.assertNotEqual(payload["status"], "skipped")
        self.assertEqual(payload["id"], run_id)
        self.assertEqual(payload["source_id"], "source-1")
        self.assertNotIn("finished_at", payload)

    def test_run_py_never_writes_running_as_a_terminal_status(self):
        """running 只由占位符产生。哪天有人拿它当结论写回去，'没收尾' 这个判据当场失效。"""
        src = (ROOT / "crawler" / "run.py").read_text(encoding="utf-8")
        calls = re.findall(r"update_crawl_run\((?:[^()]|\([^()]*\))*\)", src, re.DOTALL)
        self.assertTrue(calls, "run.py 里一个 update_crawl_run 调用都没找到，正则该修了")
        for call in calls:
            self.assertNotIn("running", call)


class CrawlRunStatusCheckMigrationTest(unittest.TestCase):
    """CHECK 是全量重建而非增量：漏抄一个旧值会把存量行打成非法。"""

    def test_migration_234_keeps_every_old_status_and_adds_running(self):
        sql = (ROOT / "supabase" / "migrations"
               / "234_crawl_runs_running_status.sql").read_text(encoding="utf-8")
        m = re.search(r"add constraint crawl_runs_status_check\s*\n?\s*check \(status in \(([^)]*)\)\)",
                      sql, re.IGNORECASE)
        self.assertIsNotNone(m, "找不到重建后的 crawl_runs_status_check 定义")
        values = set(re.findall(r"'([a-z_]+)'", m.group(1)))
        self.assertEqual(
            values,
            {"success", "partial_success", "failed", "skipped", "running"},
        )

    def test_backfill_only_touches_the_orphan_predicate(self):
        """回填谓词必须**恰好**是「占位符从没被覆盖过」，不能顺手改别的行。"""
        sql = (ROOT / "supabase" / "migrations"
               / "234_crawl_runs_running_status.sql").read_text(encoding="utf-8")
        normalized = re.sub(r"\s+", " ", sql.lower())
        self.assertIn(
            "update crawl_runs set status = 'running' where status = 'skipped' "
            "and finished_at is null",
            normalized,
        )
        self.assertNotIn("set status = 'failed'", normalized)


if __name__ == "__main__":
    unittest.main()
