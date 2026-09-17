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


if __name__ == "__main__":
    unittest.main()
