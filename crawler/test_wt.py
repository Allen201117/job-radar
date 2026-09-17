"""wt（老版 WinTalent hotjob.cn）适配器单测：recruitType → job_type 的招聘类型标注。"""
import json
import unittest

from adapters.wt import WtAdapter


class WtRecruitTypeJobTypeTest(unittest.TestCase):
    def setUp(self):
        self.a = WtAdapter()
        self.a.company_name = "测试公司"
        self.a._bind_source("https://test.hotjob.cn/wt/test/web/index")

    def test_campus_and_intern_recruit_types_are_labelled(self):
        """wt 列表接口的 postType 只是职能类别（「市场营销类」），不含招聘类型词汇；
        权威的招聘类型信号是我们请求时用的 recruitType（1=校招 / 2=社招 / 12=实习）。

        2026-09-17 实锤：华发股份 9 个校招岗、李宁 1 个校招岗，因为 job_type 只有
        「职能管理类」这类职能词，被 sourceDeclaredCategory 判不出招聘类型，入库后
        全部兜底成「社招」。把 recruitType 换算的中文标签塞进 job_type 即可救回，
        职能类别保留在前面（继续喂给 classifyJobFunction）。
        """
        posts = [
            {"postId": "1", "postName": "房产开发-会计助理/专员",
             "postType": "职能管理类", "_wtRecruitType": 1},
            {"postId": "3", "postName": "财务实习生",
             "postType": "职能管理类", "_wtRecruitType": 12},
        ]
        by = {p["postId"]: self.a._map(p) for p in posts}
        self.assertEqual(by["1"].job_type, "职能管理类 校园招聘")
        self.assertEqual(by["3"].job_type, "职能管理类 实习")

    def test_social_recruit_type_is_deliberately_not_labelled(self):
        """🚫 rt=2 **不标**「社会招聘」——这是回归护栏，不是遗漏。

        社招是 recruitmentCategory 层7 的默认态，标了不增加信息；而标上会让层3（declared）
        抢在层4（url 门户）/ 层5（标题强校招标记）**之前**拍板。2026-09-17 全库计数：
        wt 源 recruitType=2 的在招岗里有 **170 个判成校招、91 个判成实习**（公司把校招岗
        挂在社招板块，靠标题「XX 届 / 应届」被层5 捞回来）——标上就当场压回社招。
        同一个取舍在 lib/china-keyword-expansion.js 层4「不对 postType=society 对称判社招」
        那条注释里已经立过一次。
        """
        job = self.a._map({"postId": "2", "postName": "客研总监",
                           "postType": "市场营销类", "_wtRecruitType": 2})
        self.assertEqual(job.job_type, "市场营销类")

    def test_missing_post_type_still_gets_recruit_label(self):
        post = {"postId": "4", "postName": "某校招岗", "_wtRecruitType": 1}
        self.assertEqual(self.a._map(post).job_type, "校园招聘")

    def test_absent_recruit_type_falls_back_to_bare_function_category(self):
        """`_wtRecruitType` 缺失时旧逻辑兜底 rt=2 → 按上面的规矩同样不加标签。"""
        post = {"postId": "5", "postName": "某岗", "postType": "职能管理类"}
        self.assertEqual(self.a._map(post).job_type, "职能管理类")

    def test_end_to_end_parse_labels_per_post(self):
        payload = json.dumps({"_intercepted": [{"postList": [
            {"postId": "6", "postName": "校招岗", "postType": "职能管理类",
             "_wtRecruitType": 1},
            {"postId": "7", "postName": "社招岗", "postType": "市场营销类",
             "_wtRecruitType": 2},
        ]}]}, ensure_ascii=False)
        by = {j.title: j for j in self.a.parse(payload)}
        self.assertEqual(by["校招岗"].job_type, "职能管理类 校园招聘")
        self.assertEqual(by["社招岗"].job_type, "市场营销类")


class WtSchoolEntryGateTest(unittest.TestCase):
    """「按院校设的投递入口」不是岗位，不入库（2026-09-18 立，见 _INSTITUTION_TITLE 注释）。"""

    def setUp(self):
        self.a = WtAdapter()
        self.a.company_name = "中广核"
        self.a._bind_source("https://cgn.hotjob.cn/wt/CGN/web/index")

    def _map(self, name, content="。", cond="。", rt=1):
        return self.a._map({"postId": "1", "postName": name, "postType": "其他",
                            "workContent": content, "serviceCondition": cond,
                            "_wtRecruitType": rt})

    def test_school_name_with_empty_body_is_dropped(self):
        """中广核把校招做成「一所院校一条 post」：标题是院校名、正文只有一个句号。
        2026-09-18 live 全库 957 行全是这个形态，用户在校招专区看到的是大学名而不是岗位。"""
        for name in ("北京建筑大学", "电子科技大学", "海外院校", "其他院校",
                     "中国地质大学（武汉）", "清华大学深圳国际研究生院",
                     "中国原子能科学研究院", "哈尔滨焊接研究所"):
            self.assertIsNone(self._map(name), f"应被拦下: {name}")

    def test_real_job_whose_title_ends_with_institution_word_is_kept(self):
        """⚠️ 单看标题会误杀：特变电工「FPGA软件工程师-研究院」是真岗（live 4 行）。
        判据必须是「院校名标题」**且**「正文为空」的交集。"""
        job = self._map("FPGA软件工程师-研究院",
                        content="1、参与FPGA技术需求分析，设计相应场景下FPGA方案；")
        self.assertIsNotNone(job)
        self.assertEqual(job.title, "FPGA软件工程师-研究院")

    def test_thin_card_with_normal_title_is_kept(self):
        """⚠️ 单看正文也会误杀：三棵树「行政接待类实习生」正文同样为空，但它是真岗。
        薄卡按 CLAUDE.md §4 该留在库里（只是不计入「有效在招」），不该被这道门顺手删掉。"""
        self.assertIsNotNone(self._map("行政接待类实习生"))
        self.assertIsNotNone(self._map("实习生（客房部）", rt=12))

    def test_parse_skips_them_end_to_end_and_counts(self):
        payload = json.dumps({"_intercepted": [{"postList": [
            {"postId": "10", "postName": "上海交通大学", "postType": "其他",
             "workContent": "。", "serviceCondition": "。", "_wtRecruitType": 1},
            {"postId": "11", "postName": "核电运行值班员", "postType": "技术类",
             "workContent": "负责机组运行监盘…", "_wtRecruitType": 1},
        ]}]}, ensure_ascii=False)
        jobs = self.a.parse(payload)
        self.assertEqual([j.title for j in jobs], ["核电运行值班员"])
        self.assertEqual(self.a._skipped_school_entries, 1)


if __name__ == "__main__":
    unittest.main()
