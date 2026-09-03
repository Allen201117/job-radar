"""说法层存量治理编排：计划阶段保持纯函数，避免单测接触 Supabase。"""
import unittest

import insight_topic_sweep as S


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
