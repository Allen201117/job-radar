"""reattribute_beisen_shared_tenant 的纯函数与写库分组（不打真网络、不连库）。"""
import unittest
from unittest import mock

import reattribute_beisen_shared_tenant as R

HOST = "chinalife.zhiye.com"
U = "https://chinalife.zhiye.com/custom/zwxq?jobAdId="


class JobUuidTest(unittest.TestCase):
    def test_extracts_and_lowercases(self):
        self.assertEqual(R.job_uuid(U + "C13B2A58-37d3"), "c13b2a58-37d3")
        self.assertEqual(R.job_uuid("https://chinalife.zhiye.com/custom/zwxq"), "")
        self.assertEqual(R.job_uuid(None), "")


class PlanTest(unittest.TestCase):
    def test_both_directions_and_unresolved(self):
        rows = [
            ("1", U + "a", "中国人寿", "active"),   # 广发的岗挂错 → 改
            ("2", U + "b", "中国人寿", "active"),   # 国寿的岗 → 已正确
            ("3", U + "c", "广发银行", "expired"),  # 反方向：国寿的岗挂成广发 → 改回
            ("4", U + "d", "中国人寿", "active"),   # 查不到机构 → 不动
            ("5", U + "e", "广发银行", "active"),   # 广银理财 → 已正确
        ]
        entities = {"a": "广发银行中山分行", "b": "寿险重庆分公司", "c": "财险上海分公司", "e": "广银理财有限责任公司"}
        changes, stats = R.plan(rows, entities, HOST, "中国人寿")
        self.assertEqual(changes, [("1", "中国人寿", "广发银行", "active"),
                                   ("3", "广发银行", "中国人寿", "expired")])
        self.assertEqual(stats["already_correct"], 2)
        self.assertEqual(stats["unresolved"], 1)

    def test_empty_entity_is_unresolved_not_home(self):
        """机构是空串 ≠ 属于本家：不许顺手改成 --home。"""
        changes, stats = R.plan([("1", U + "a", "广发银行", "active")], {"a": ""}, HOST, "中国人寿")
        self.assertEqual(changes, [])
        self.assertEqual(stats["unresolved"], 1)


class ApplyTest(unittest.TestCase):
    def test_groups_by_direction_and_guards_old_name(self):
        cur = mock.Mock()
        cur.rowcount = 2
        done = R.apply_changes(cur, [("1", "中国人寿", "广发银行", "active"),
                                     ("2", "中国人寿", "广发银行", "expired")])
        self.assertEqual(done, {("中国人寿", "广发银行"): 2})
        sql, params = cur.execute.call_args[0]
        self.assertIn("and company = %s", sql)          # 并发改过的行不碰
        self.assertEqual(params, ["广发银行", ["1", "2"], "中国人寿"])


class DetailEntityTest(unittest.TestCase):
    def _client(self, payload):
        c = mock.Mock()
        c.get.return_value.json.return_value = payload
        return c

    def test_reads_org_of_closed_job(self):
        c = self._client({"Code": 200, "Data": {"Org": "广发银行江门分行", "Status": 2}})
        self.assertEqual(R.detail_entity(c, HOST, "x"), "广发银行江门分行")

    def test_missing_job_is_none(self):
        c = self._client({"Code": 500, "Message": "参数错误", "Data": None})
        self.assertIsNone(R.detail_entity(c, HOST, "x"))

    def test_row_without_entity_is_none(self):
        c = self._client({"Code": 200, "Data": {"Org": "", "ClassificationTwo": None}})
        self.assertIsNone(R.detail_entity(c, HOST, "x"))


class ArgsTest(unittest.TestCase):
    def test_refuses_unregistered_host(self):
        with self.assertRaises(SystemExit):
            R.main(["--host", "boe.zhiye.com", "--home", "京东方"])


if __name__ == "__main__":
    unittest.main()
