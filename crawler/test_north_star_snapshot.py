import unittest

import north_star_snapshot as snapshot


class NorthStarSnapshotTest(unittest.TestCase):
    def test_build_snapshot_metrics_keeps_real_zero_and_uses_worst_industry(self):
        companies = [
            {"name": "甲", "pattern": "%甲%", "industries": ["科技"]},
            {"name": "乙", "pattern": "%乙%", "industries": ["金融"]},
        ]
        rows = [
            {"company": "甲", "state": "healthy"},
            {"company": "乙", "state": "unknown"},
        ]

        result = snapshot.build_snapshot_metrics(companies, rows, 9, 12)

        self.assertEqual(result["must_apply_healthy_companies"], 1)
        self.assertEqual(result["must_apply_total_companies"], 2)
        self.assertEqual(result["worst_industry"], "金融")
        self.assertEqual(result["worst_industry_healthy_companies"], 0)
        self.assertEqual(result["job_validity_rate"], 0.75)

    def test_build_snapshot_metrics_leaves_rate_empty_when_no_active_jobs(self):
        result = snapshot.build_snapshot_metrics(
            [{"name": "甲", "pattern": "%甲%", "industries": ["科技"]}],
            [{"company": "甲", "state": "unknown"}],
            0,
            0,
        )
        self.assertIsNone(result["job_validity_rate"])


if __name__ == "__main__":
    unittest.main()
