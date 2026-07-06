import unittest

import enrich_backlog


class MustApplyLivenessPriorityTest(unittest.TestCase):
    def test_must_apply_source_groups_are_interleaved_first(self):
        by_src = {
            "ordinary": [{"id": "o1"}, {"id": "o2"}],
            "bytedance": [{"id": "b1"}],
            "oppo": [{"id": "p1"}, {"id": "p2"}],
        }
        smap = {
            "ordinary": {"company": "普通公司"},
            "bytedance": {"company": "北京字节跳动科技有限公司"},
            "oppo": {"company": "OPPO 广东移动通信有限公司"},
        }

        rows = enrich_backlog.interleave_liveness_rows_by_priority(
            by_src,
            smap,
            match_company=lambda name: "字节" in name or "oppo" in name.lower(),
        )

        self.assertEqual([r["id"] for r in rows], ["b1", "p1", "o1", "p2", "o2"])

    def test_no_must_apply_sources_keep_original_interleave_order(self):
        by_src = {
            "s1": [{"id": "a1"}, {"id": "a2"}],
            "s2": [{"id": "b1"}],
        }
        smap = {
            "s1": {"company": "普通公司甲"},
            "s2": {"company": "普通公司乙"},
        }

        rows = enrich_backlog.interleave_liveness_rows_by_priority(
            by_src,
            smap,
            match_company=lambda name: False,
        )

        self.assertEqual([r["id"] for r in rows], ["a1", "b1", "a2"])


if __name__ == "__main__":
    unittest.main()
