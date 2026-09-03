"""说法层存量治理编排：计划阶段保持纯函数，避免单测接触 Supabase。"""
import unittest

import insight_topic_sweep as S
import insight_topic_sweep as sweep


class TestBuildPlan(unittest.TestCase):
    def test_routes_metrics_and_prioritizes_duplicate_retirement(self):
        # 若重复项仍参与转投/抽数，或数值写回 payload 丢失，这个端到端计划断言会失败。
        rows = [
            {"id": "keep", "company_id": "c1", "metric_key": "bonus_months", "content": "年终奖发 3 个月。", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "route", "company_id": "c1", "metric_key": "promotion_pace", "content": "薪酬范围 15-30k。", "created_at": "2026-01-02T00:00:00Z"},
            {"id": "retire", "company_id": "c1", "metric_key": "promotion_pace", "content": "公司校招面向2026届毕业生。", "created_at": "2026-01-03T00:00:00Z"},
            {"id": "original", "company_id": "c2", "metric_key": "overtime_level", "content": "团队实行单休和双休。", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "duplicate", "company_id": "c2", "metric_key": "overtime_level", "content": " 团队实行单休和双休。 ", "created_at": "2026-01-02T00:00:00Z"},
        ]

        plan = S.build_plan(rows)

        self.assertEqual(plan["keep"], 2)
        self.assertEqual(plan["reroute"], {"pay_level": 1})
        self.assertEqual(plan["retire"], ["retire"])
        self.assertEqual(plan["dedupe"], ["duplicate"])
        self.assertEqual(plan["metric_updates"], [{"id": "keep", "metric_value": 3.0}])
        self.assertEqual(
            plan["reroute_updates"],
            [{"id": "route", "metric_key": "pay_level", "metric_value": 22.5}],
        )


if __name__ == "__main__":
    unittest.main()


class FakeQuery:
    def __init__(self, log):
        self.log = log
        self.values = None
        self.ids = None

    def upsert(self, payloads, **kw):
        self.log.append(("upsert", payloads, kw))
        return self

    def update(self, values):
        self.values = values
        return self

    def in_(self, column, ids):
        self.ids = list(ids)
        return self

    def execute(self):
        self.log.append(("update", self.values, self.ids))
        return self


class FakeClient:
    def __init__(self):
        self.log = []

    def table(self, name):
        return FakeQuery(self.log)


class TestApplyPlan(unittest.TestCase):
    """⚠️ 2026-09-04 线上实测炸过：PostgREST 的 upsert = INSERT ... ON CONFLICT，
    Postgres 会先校验待插入行的 NOT NULL。只带 {id, metric_value} 的部分 payload
    会因 company_id 为空整批失败。这里把「绝不用 upsert」钉死。
    """

    def _plan(self):
        return {
            "metric_updates": [
                {"id": "a", "metric_value": 3.0},
                {"id": "b", "metric_value": 3.0},
                {"id": "c", "metric_value": 2.0},
            ],
            "reroute_updates": [
                {"id": "d", "metric_key": "pay_level"},
                {"id": "e", "metric_key": "pay_level", "metric_value": 22.5},
            ],
            "retire": ["f"],
            "dedupe": ["f", "g"],
        }

    def test_never_uses_upsert(self):
        client = FakeClient()
        sweep.apply_plan(client, self._plan())
        self.assertEqual([c for c in client.log if c[0] == "upsert"], [])

    def test_same_patch_is_batched_into_one_request(self):
        client = FakeClient()
        sweep.apply_plan(client, self._plan())
        writes = [(c[1], c[2]) for c in client.log if c[0] == "update"]
        # 同值合成一批：metric_value=3.0 的两条只发一次
        self.assertIn(({"metric_value": 3.0}, ["a", "b"]), writes)
        self.assertIn(({"metric_value": 2.0}, ["c"]), writes)
        # 带数值的转投必须同时写两列，不能只写主题
        self.assertIn(({"metric_key": "pay_level", "metric_value": 22.5}, ["e"]), writes)

    def test_retire_and_dedupe_are_deduplicated(self):
        client = FakeClient()
        sweep.apply_plan(client, self._plan())
        retire = [c for c in client.log if c[0] == "update" and c[1] == {"status": "retired"}]
        self.assertEqual(len(retire), 1)
        self.assertEqual(retire[0][2], ["f", "g"])
