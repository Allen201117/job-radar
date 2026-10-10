"""截止日的撤回通道：adapter 确认「这个岗没有截止日」时，清掉库里留着的旧值（2026-10-10 立）。

为什么需要：deadline 在 jobs_db._PRESERVE_IF_EMPTY 里，新值为空时保留旧值——adapter 不写 ≠ 库里清掉。
wt / hotjob 的岗从「指定下线时间」改回「长期发布」后，旧日期会一直留在库里；当天手工清掉的
41,605 行假截止日也是同一个原因攒出来的。
"""
import pathlib
import unittest

import jobs_db
import run
from adapters.base import RawJob
from adapters.hotjob import HotJobAdapter
from adapters.wt import WtAdapter


class AdapterSignalTest(unittest.TestCase):
    """三态：有真截止日 / 确认没有（deadline_absent）/ 判不出（两个都空 → 库里旧值不动）。"""

    def test_hotjob_flags_long_term_posts_only(self):
        a = HotJobAdapter()
        a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html")

        def job(**kw):
            return a._map({"postId": "p", "postName": "某岗", "endDate": "2026-10-22 23:59:59", **kw})

        long_term, dated, unknown = job(longTermRelease=0), job(longTermRelease=1), job()
        self.assertTrue(long_term.deadline_absent)
        self.assertIsNone(long_term.deadline)
        self.assertFalse(dated.deadline_absent)
        self.assertEqual(dated.deadline, "2026-10-22")
        # 字段缺失 = 判不出：不写、也不许清。
        self.assertFalse(unknown.deadline_absent)
        self.assertIsNone(unknown.deadline)

    def test_wt_rolling_window_is_unknown_not_absent(self):
        """标记为 1 的滚动值：平台上有真下线时间，只是 wt 接口不给 → 判不出，不能当成「没有」去清库。
        不然撞上「请求日 + N 个月」那两天，库里的真截止日会被清掉、第二天再写回来，来回跳。"""
        a = WtAdapter()
        a._bind_source("https://test.hotjob.cn/wt/test/web/index")

        def job(**kw):
            return a._map({"postId": "1", "postName": "某岗", "_wtFetchedOn": "2026-10-10", **kw})

        long_term = job(isLongTermRelease=0, endDate="2026-10-10")
        rolling = job(isLongTermRelease=1, endDate="2027-01-10")
        dated = job(isLongTermRelease=1, endDate="2026-12-31")
        self.assertTrue(long_term.deadline_absent)
        self.assertFalse(rolling.deadline_absent)
        self.assertIsNone(rolling.deadline)
        self.assertFalse(dated.deadline_absent)
        self.assertEqual(dated.deadline, "2026-12-31")
        self.assertFalse(job(endDate="2026-12-31").deadline_absent)

    def test_other_adapters_default_to_unknown(self):
        self.assertFalse(RawJob(company="c", title="t").deadline_absent)


class SelectionTest(unittest.TestCase):
    def test_only_confirmed_absent_rows_with_no_deadline_at_all(self):
        raws = [
            RawJob(company="c", title="长期发布", jd_url="https://x/1", deadline_absent=True),
            # 平台说长期发布，但正文明写了报名截止 → 正文那个日期照常写库，不清。
            RawJob(company="c", title="正文有截止日", jd_url="https://x/2", deadline_absent=True),
            RawJob(company="c", title="判不出", jd_url="https://x/3"),
            RawJob(company="c", title="有真截止日", jd_url="https://x/4", deadline="2026-12-31"),
        ]
        jobs = [
            {"jd_url": "https://x/1", "deadline": None},
            {"jd_url": "https://x/2", "deadline": "2026-11-05"},
            {"jd_url": "https://x/3", "deadline": None},
            {"jd_url": "https://x/4", "deadline": "2026-12-31"},
        ]
        self.assertEqual(run._urls_confirmed_without_deadline(raws, jobs), ["https://x/1"])


class _Cur:
    rowcount = 2

    def __init__(self, seen):
        self.seen = seen

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.seen["sql"], self.seen["params"] = sql, params


class _Conn:
    def __init__(self):
        self.seen = {}

    def cursor(self):
        return _Cur(self.seen)


class ClearDeadlinesTest(unittest.TestCase):
    def test_clears_only_active_rows_that_still_carry_a_deadline(self):
        conn = _Conn()
        n = jobs_db.clear_deadlines(conn, [
            "https://a.hotjob.cn/SU1/pb/posDetail.html?postId=9&postType=society&utm_source=x"])
        self.assertEqual(n, 2)
        sql = " ".join(conn.seen["sql"].split())
        self.assertIn("set deadline = null", sql)
        self.assertIn("deadline is not null", sql)        # 没有旧值的行不碰，平时是 0 行更新
        self.assertIn("status = 'active'", sql)           # 走 active 唯一索引；下架行复活后下一轮再清
        self.assertIn("canonical_jd_url = any(%s)", sql)
        # 按库里的归一口径匹配（去 tracking 参数），不是按原始 jd_url。
        self.assertEqual(conn.seen["params"], (
            ["https://a.hotjob.cn/SU1/pb/posDetail.html?postId=9&postType=society"],))

    def test_empty_input_never_touches_the_db(self):
        conn = _Conn()
        self.assertEqual(jobs_db.clear_deadlines(conn, []), 0)
        self.assertEqual(conn.seen, {})


class RunStepContractTest(unittest.TestCase):
    def test_step_is_gated_and_never_blocks_the_crawl(self):
        src = (pathlib.Path(__file__).parent / "run.py").read_text(encoding="utf-8")
        block = src[src.index("# 5d."):src.index("# 6. update source timestamp")]
        self.assertIn("jobs_db.enabled()", block)
        self.assertIn("_urls_confirmed_without_deadline(valid_jobs, job_batch)", block)
        self.assertIn("except Exception", block)


if __name__ == "__main__":
    unittest.main()
