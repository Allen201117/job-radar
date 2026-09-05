"""crawl_runs 状态契约：占位符必须是 running，且 CHECK 重建时旧值一个不落。

背景（迁移 234）：create_crawl_run 原来拿 'skipped' 当占位符 —— 进程半途死掉的行就永远停在
它，与 robots 拦截 / adapter.should_skip 主动跳过在 status 上完全同形。这两条把「不许再退回去」
钉死：规则 I 虽然按 finished_at 判、退回去也还能报，但页面（SourceTable）和任何读 status 的人
会重新被骗。
"""
import re
import unittest
from pathlib import Path

import db

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "234_crawl_runs_running_status.sql"


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
        # skipped 是「按设计跳过」的终态，一定带 finished_at + error_message；
        # 拿它当占位符 = 让「跑崩了」冒充「跳过」。
        self.assertNotEqual(payload["status"], "skipped")
        self.assertEqual(payload["id"], run_id)
        self.assertNotIn("finished_at", payload)

    def test_run_py_never_writes_running_as_a_terminal_status(self):
        """running 只能由占位符产生；谁把它当结论写回去，『还在跑 vs 没收尾』就分不出来了。"""
        src = (ROOT / "crawler" / "run.py").read_text(encoding="utf-8")
        calls = re.findall(r"update_crawl_run\((?:[^()]|\([^()]*\))*\)", src, re.DOTALL)
        self.assertTrue(calls, "run.py 里一个 update_crawl_run 调用都没找到，正则该修了")
        for call in calls:
            self.assertNotIn("running", call)


class CrawlRunStatusCheckMigrationTest(unittest.TestCase):
    def test_migration_234_keeps_every_old_status_and_adds_running(self):
        """CHECK 是全量重建不是增量：漏抄一个旧值会把存量行打成非法。"""
        sql = MIGRATION.read_text(encoding="utf-8")
        m = re.search(r"add constraint crawl_runs_status_check(.*?);", sql,
                      re.IGNORECASE | re.DOTALL)
        self.assertIsNotNone(m, "找不到重建后的 crawl_runs_status_check 定义")
        self.assertEqual(
            set(re.findall(r"'([a-z_]+)'", m.group(1))),
            {"success", "partial_success", "failed", "skipped", "running"},
        )


if __name__ == "__main__":
    unittest.main()
