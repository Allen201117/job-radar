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


class _Boom(Exception):
    pass


class CrawlRunWritebackTraceTest(unittest.TestCase):
    """两次回写都失败时，必须留下可聚合的痕迹 —— 否则事后只剩一条无解的 running 孤儿。

    2026-09-04 那 7 个 workday 源就死在这个岔口：enrichment-crawl 六片全 success、guard 也
    success，源却开跑后再无下文；GitHub 日志已截断，事后无从判断是进程被杀还是回写失败。
    """

    def setUp(self):
        import run
        self.run = run
        self._orig = {k: getattr(run.db, k) for k in
                      ("create_crawl_run", "update_crawl_run", "update_source_timestamp")}
        self._robots = run.check_robots
        run.db.create_crawl_run = lambda sb, sid: "run-1"
        run.db.update_source_timestamp = lambda sb, sid: None
        run.check_robots = lambda url: {"allowed": True, "reason": ""}

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(self.run.db, k, v)
        self.run.check_robots = self._robots
        self.run.ADAPTERS.pop("_writeback_probe", None)

    def _run_with(self, update_impl, adapter_name="_writeback_probe"):
        self.run.db.update_crawl_run = update_impl
        if adapter_name == "_writeback_probe":
            class _Probe:
                def should_skip(self, url):
                    return "板块未发布"
            self.run.ADAPTERS["_writeback_probe"] = _Probe()
        return self.run._process_one_source(
            {"adapter_name": adapter_name, "company": "探针",
             "source_url": "https://example.test/jobs", "id": "src-1"},
            supabase=None)

    def test_both_writebacks_failing_is_reported(self):
        def always_boom(*a, **k):
            raise _Boom("Errno 35")
        result = self._run_with(always_boom)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["run_unrecorded"],
                        "两次回写都失败却没留痕 = 事后拿不到证据")

    def test_successful_writeback_is_not_flagged(self):
        result = self._run_with(lambda *a, **k: None)
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result.get("run_unrecorded"))

    def test_unknown_adapter_writeback_failure_is_reported(self):
        def always_boom(*a, **k):
            raise _Boom("Errno 35")
        result = self._run_with(always_boom, adapter_name="_no_such_adapter")
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["run_unrecorded"])

    def test_no_row_inserted_is_not_counted_as_unrecorded(self):
        """create 就失败 = 压根没插行，那不是孤儿，别混进这个计数。"""
        self.run.db.create_crawl_run = lambda sb, sid: (_ for _ in ()).throw(_Boom("insert 挂了"))
        result = self._run_with(lambda *a, **k: None, adapter_name="_no_such_adapter")
        self.assertFalse(result.get("run_unrecorded"))
