import unittest

import industry_taxonomy as it


class IndustryTaxonomyTest(unittest.TestCase):
    def test_groups_are_the_11_canonical_categories(self):
        groups = it.groups()
        self.assertEqual(len(groups), 11)
        self.assertEqual(groups[0], "互联网/科技")
        self.assertIn("教育", groups)
        self.assertNotIn("other", groups)

    def test_other_group_marker(self):
        self.assertEqual(it.other_group(), "other")

    def test_mapping_values_all_within_groups_or_other(self):
        allowed = set(it.groups()) | {it.other_group()}
        m = it.mapping()
        self.assertGreater(len(m), 400)
        bad = {k: v for k, v in m.items() if v not in allowed}
        self.assertEqual(bad, {}, f"mapping 里出现了不在 groups∪{{other}} 的值：{bad}")

    def test_classify_industry_empty_and_none_return_none(self):
        self.assertIsNone(it.classify_industry(None))
        self.assertIsNone(it.classify_industry(""))
        self.assertIsNone(it.classify_industry("   "))
        self.assertIsNone(it.classify_industry(123))

    def test_classify_industry_unmapped_returns_none_not_other(self):
        # 未收录的新写法必须返回 None（需要人工补录），不许静默落 other。
        self.assertIsNone(it.classify_industry("这是一个从没见过的行业写法·不存在于表里"))

    def test_classify_industry_task_examples(self):
        # 需求里给出的三个示例口径，逐条钉死。
        self.assertEqual(it.classify_industry("半导体"), "制造/工业")
        self.assertEqual(it.classify_industry("锂电"), "制造/工业")
        self.assertEqual(it.classify_industry("储能"), "制造/工业")
        self.assertEqual(it.classify_industry("证券"), "金融")
        self.assertEqual(it.classify_industry("基金"), "金融")
        self.assertEqual(it.classify_industry("游戏"), "互联网/科技")

    def test_placeholder_labels_land_on_other_not_guessed(self):
        for raw in ["discover", "综合", "综合·央企", "综合·实业·国资", "知名私企"]:
            self.assertEqual(it.classify_industry(raw), "other", raw)

    def test_every_mapping_key_classifies_to_its_own_value(self):
        for raw, expected in it.mapping().items():
            self.assertEqual(it.classify_industry(raw), expected, raw)


if __name__ == "__main__":
    unittest.main()
