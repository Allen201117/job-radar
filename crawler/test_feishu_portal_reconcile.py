"""feishu_portal_reconcile 存量对账单测（纯函数 + 假游标，不打网络、不连库）。

红线：只下架「不在公开列表里 且 在自己链接门户上读到 0」的岗；读到 1 / 读不到一律不动；
在列表里但链接门户不对 → 改链接不下架；新链接撞上已有在招行 → 这行是重复才下架。
"""
import unittest

import feishu_portal_reconcile as R

H = "https://t.jobs.feishu.cn"


def _u(portal, jid):
    return f"{H}/{portal}/position/{jid}/detail"


class PlanSourceTest(unittest.TestCase):
    def test_every_branch(self):
        lib = [("a", _u("index", "1")),      # 在列表、门户一致
               ("b", _u("index", "2")),      # 在列表、门户不一致（莉莉丝 index→career）
               ("c", _u("index", "3")),      # 不在列表、读到 0 → 下架
               ("d", _u("index", "4")),      # 不在列表、读到 1 → 不动
               ("e", _u("index", "5")),      # 不在列表、读不到 → 不动
               ("f", "https://t.jobs.feishu.cn/odd/url")]
        status = {("3", "index"): 0, ("4", "index"): 1, ("5", "index"): None}
        acts = R.plan_source(lib, {"1": "index", "2": "career"}, lambda j, p: status[(j, p)])
        got = {a[1]: (a[0], a[3]) for a in acts}
        self.assertEqual(got["a"], ("keep", None))
        self.assertEqual(got["b"], ("relink", _u("career", "2")))
        self.assertEqual(got["c"], ("expire", None))
        self.assertEqual(got["d"], ("keep_online_unlisted", None))
        self.assertEqual(got["e"], ("keep_unknown", None))
        self.assertEqual(got["f"], ("keep_nonstd_url", None))

    def test_status_read_under_the_links_own_portal(self):
        """状态必须按链接自己的门户问——同一岗不带头读 1、带 index 读 0。"""
        asked = []
        R.plan_source([("x", _u("social", "9"))], {}, lambda j, p: asked.append((j, p)) or 0)
        self.assertEqual(asked, [("9", "social")])

    def test_list_not_reached_never_relinks_only_status_decides(self):
        acts = R.plan_source([("a", _u("index", "1"))], None, lambda j, p: 1)
        self.assertEqual(acts[0][0], "keep_online_unlisted")

    def test_err_is_not_zero(self):
        acts = R.plan_source([("a", _u("index", "1"))], {}, lambda j, p: "ERR")
        self.assertEqual(acts[0][0], "keep_unknown")


class ControlTest(unittest.TestCase):
    def test_all_ones_pass(self):
        self.assertTrue(R.control_ok("h", {"1": "index", "2": "index"}, lambda j, p: 1))

    def test_any_non_one_fails(self):
        self.assertFalse(R.control_ok("h", {"1": "index", "2": "index", "3": "index"},
                                      lambda j, p: 0 if j == "2" else 1, k=3))

    def test_empty_list_cannot_vouch(self):
        self.assertIsNone(R.control_ok("h", {}, lambda j, p: 1))
        self.assertIsNone(R.control_ok("h", None, lambda j, p: 1))


class RunControlTest(unittest.TestCase):
    """公开门户 0 岗的源（海底捞 / 地素时尚）无从本源对照，靠本轮全局对照。"""

    def test_run_control_needs_enough_passes_and_no_failure(self):
        self.assertTrue(R.run_control_ok([True] * 10 + [None] * 3))
        self.assertFalse(R.run_control_ok([True] * 9 + [None]))
        self.assertFalse(R.run_control_ok([True] * 50 + [False]))

    def test_expire_allowed(self):
        self.assertTrue(R.expire_allowed(True, False))
        self.assertTrue(R.expire_allowed(None, True))
        self.assertFalse(R.expire_allowed(None, False))
        self.assertFalse(R.expire_allowed(False, True))   # 本源对照失败，全局再好也不信


class _Cur:
    def __init__(self, taken):
        self.taken, self.sql, self.rowcount, self._one = taken, [], 0, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        if sql.startswith("select id from jobs"):
            self._one = ("other",) if params[1] in self.taken else None
        elif sql.startswith("update jobs set jd_url"):
            self.rowcount = 1
        elif sql.startswith("update jobs set status='expired'"):
            self.rowcount = len(params[2])

    def fetchone(self):
        return self._one


class _Conn:
    def __init__(self, taken=()):
        self.cur = _Cur(set(taken))

    def cursor(self):
        return self.cur


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self._rec = R.jobs_db.record_job_events
        self.events = []
        R.jobs_db.record_job_events = lambda conn, ev: self.events.extend(ev) or len(ev)

    def tearDown(self):
        R.jobs_db.record_job_events = self._rec

    def test_relink_expire_and_dup(self):
        conn = _Conn(taken={_u("career", "3")})
        out = R.apply_actions(conn, "src", [
            ("relink", "j2", _u("index", "2"), _u("career", "2")),
            ("relink", "j3", _u("index", "3"), _u("career", "3")),   # 新链接已被别的在招行占用 → 重复
            ("expire", "j4", _u("index", "4"), None),
            ("keep", "j1", _u("index", "1"), None),
        ])
        self.assertEqual(out, {"relinked": 1, "expired": 2, "dup_expired": 1})
        expire_sql = [p for s, p in conn.cur.sql if s.startswith("update jobs set status='expired'")]
        self.assertEqual(sorted(expire_sql[0][2]), ["j3", "j4"])
        self.assertEqual({e[2] for e in self.events}, {"j3", "j4"})
        self.assertTrue(all(e[1] == "CLOSED" for e in self.events))

    def test_nothing_to_do_writes_nothing(self):
        conn = _Conn()
        out = R.apply_actions(conn, "src", [("keep", "j1", _u("index", "1"), None)])
        self.assertEqual(out, {"relinked": 0, "expired": 0, "dup_expired": 0})
        self.assertFalse(any(s.startswith("update") for s, _ in conn.cur.sql))


if __name__ == "__main__":
    unittest.main()
