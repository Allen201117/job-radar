import unittest

from announcements.classify import (
    detect_audience,
    detect_employer_type,
    is_recruitment_announcement,
)


class TestIsRecruitment(unittest.TestCase):
    def test_real_recruitment(self):
        self.assertTrue(is_recruitment_announcement("北京水利医院2026年公开招聘工作人员公告"))
        self.assertTrue(is_recruitment_announcement("首都经济贸易大学2026年人才引进公告（第二批）"))
        self.assertTrue(is_recruitment_announcement("广东松山职业技术学院2026年公开招聘博士研究生公告"))

    def test_non_recruitment_filtered(self):
        # Phase 0 实测：栏目里混着这些非报名通知，必须剔除
        self.assertFalse(is_recruitment_announcement("广东省事业单位2026年集中公开招聘高校毕业生笔试成绩公告"))
        self.assertFalse(is_recruitment_announcement("关于广东省事业单位2026年公开招聘笔试合格分数线的公告"))
        self.assertFalse(is_recruitment_announcement("广东省教育厅所属事业单位2026年公开招聘拟聘用人员公示"))
        self.assertFalse(is_recruitment_announcement("XX单位2026年公开招聘资格复审公告"))
        self.assertFalse(is_recruitment_announcement("招聘政策法规"))

    def test_stats_policy_process_filtered(self):
        # 扩省实测：综合栏目混着报名统计/政策办法/资格确认/公务员遴选，必须剔除
        self.assertFalse(is_recruitment_announcement("重庆市事业单位2026年第三季度公开招聘工作人员考试报名统计"))
        self.assertFalse(is_recruitment_announcement("关于印发《贵州省事业单位公开招聘操作办法（试行）》的通知"))
        self.assertFalse(is_recruitment_announcement("河南医药健康技师学院2026年公开招聘面试资格确认公告"))
        self.assertFalse(is_recruitment_announcement("事业单位公开招聘专业设置参考目录"))
        # 「遴选」不在 INCLUDE：公开遴选=体制内在职流动，不算对外招聘
        self.assertFalse(is_recruitment_announcement("重庆市属事业单位2026年公开遴选工作人员报名统计"))

    def test_stats_keyword_does_not_overfilter(self):
        # 「统计局」招聘是真公告——EXCLUDE 用「报名统计」而非裸「统计」，不能误杀
        self.assertTrue(is_recruitment_announcement("重庆市统计局2026年公开招聘工作人员公告"))

    def test_empty(self):
        self.assertFalse(is_recruitment_announcement(""))


class TestAudience(unittest.TestCase):
    def test_fresh_grad(self):
        self.assertEqual(detect_audience("面向2027届高校毕业生公开招聘"), "fresh_grad")

    def test_experienced(self):
        self.assertEqual(detect_audience("面向社会人员公开招聘，需2年以上工作经验"), "experienced")

    def test_both(self):
        self.assertEqual(detect_audience("应届毕业生及社会人员均可报名"), "both")

    def test_unknown(self):
        self.assertEqual(detect_audience("北京水利医院2026年公开招聘工作人员公告"), "unknown")


class TestEmployerType(unittest.TestCase):
    def test_types(self):
        self.assertEqual(detect_employer_type("广东松山职业技术学院2026年公开招聘博士研究生公告"), "高校")
        self.assertEqual(detect_employer_type("北京水利医院2026年公开招聘工作人员公告"), "医疗卫生")
        self.assertEqual(detect_employer_type("军队文职人员2026年公开招聘"), "军队文职")
        self.assertEqual(detect_employer_type("XX事业单位2026年公开招聘"), "事业单位")

    def test_none_when_not_recruitment(self):
        self.assertIsNone(detect_employer_type("某某通知"))


if __name__ == "__main__":
    unittest.main()
