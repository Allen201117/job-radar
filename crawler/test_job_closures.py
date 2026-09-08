"""F1 回归：撤岗墓碑与「复活」计数。

缺陷原貌：purge-expired 每天 `delete from jobs where status='expired'`（近 14 天实测均值 2,871 行/天），
而 job_events.job_id 是 ON DELETE CASCADE → CLOSED 事件跟着没。于是按 canonical 查不到任何行，
同一个链接下次被列表抓到就以**全新 uuid + 全新 first_seen_at** 变回 active。
wt/hotjob 的列表本来就夹带已关闭岗（52%/71%），这条链是真能跑通的。
"""
import re
import unittest
from pathlib import Path

import jobs_db

ROOT = Path(__file__).resolve().parents[1]


class FakeCur:
    def __init__(self, hits=None, raise_on_update=False):
        self.hits, self.raise_on_update, self.executed = hits or [], raise_on_update, []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.raise_on_update:
            raise RuntimeError("relation \"job_closures\" does not exist")

    def fetchall(self):
        return [(h,) for h in self.hits]


class TestReopenMarking(unittest.TestCase):
    def test_counts_reopened_canonicals(self):
        cur = FakeCur(hits=["https://x.com/job/1", "https://x.com/job/2"])
        self.assertEqual(jobs_db.mark_reopened_from_closures(cur, ["a", "b"]), 2)

    def test_no_canonicals_is_noop(self):
        cur = FakeCur()
        self.assertEqual(jobs_db.mark_reopened_from_closures(cur, []), 0)
        self.assertEqual(jobs_db.mark_reopened_from_closures(cur, [None, ""]), 0)
        self.assertEqual(cur.executed, [], "空输入不该发 SQL")

    def test_fail_open_when_table_missing(self):
        """墓碑表还没建（迁移未跑）不能拖垮入库主链路——观测功能一律 fail-open。"""
        cur = FakeCur(raise_on_update=True)
        self.assertEqual(jobs_db.mark_reopened_from_closures(cur, ["a"]), 0)

    def test_marks_only_not_suppresses(self):
        """刻意只记不拦：命中墓碑就拒收 = 把真重开的岗永久删掉，违反「宁可漏判不可错杀」。"""
        src = (ROOT / "crawler" / "jobs_db.py").read_text(encoding="utf-8")
        fn = src.split("def mark_reopened_from_closures")[1].split("\ndef ")[0]
        self.assertNotIn("continue", fn)
        self.assertNotIn("return None", fn)
        self.assertIn("update job_closures", fn)


class TestPurgeWorkflowContract(unittest.TestCase):
    """墓碑写入与删除必须在同一事务里，且不能给「还有 active 同链接」的岗立墓碑。"""

    def setUp(self):
        self.wf = (ROOT / ".github" / "workflows" / "purge-expired.yml").read_text(encoding="utf-8")

    def test_tombstone_and_delete_in_one_psql_command(self):
        # 拆成两个 -c 就是两个独立事务：前一个成功后一个失败照样留下不一致。
        body = self.wf.split("deleted_count=")[1].split(")\"")[0]
        self.assertIn("insert into job_closures", body)
        self.assertIn("delete from jobs where status = 'expired'", body)
        self.assertEqual(body.count(" -c "), 1, "墓碑与删除必须在同一个 psql -c（=同一事务）里")

    def test_excludes_canonicals_still_active(self):
        # canonical 唯一约束只作用于 active：已关闭旧行与在招新行可并存，
        # 给它立墓碑会把一个在招岗记成已关闭。
        self.assertIn("and a.status = 'active'", self.wf)
        self.assertIn("not exists", self.wf)

    def test_schema_declares_tombstone_table(self):
        schema = (ROOT / "jobs-db" / "schema.sql").read_text(encoding="utf-8")
        self.assertIn("create table if not exists job_closures", schema)
        self.assertRegex(schema, r"job_closures[\s\S]{0,900}reopen_count")
        # 刻意不做外键：被墓碑记录的那一行马上就要被删掉，加 FK 会让删除失败
        tbl = schema.split("create table if not exists job_closures")[1].split(");")[0]
        self.assertNotIn("references jobs", tbl)


if __name__ == "__main__":
    unittest.main()
