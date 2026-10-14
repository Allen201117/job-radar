"""飞书列表每行自报的招聘类型（recruit_type）→ job_type：离线单测，不打真网络。

取值域取自 2026-10-12 对全部 enabled 飞书系源的全量试抓；端到端用例走真实的
adapter._map → normalizer.normalize → recruitment_classify（隔进程调 lib 里那份 JS 裁决）。
"""
import unittest

import normalizer
import recruitment_classify
from adapters import feishu

SOURCE_URL = "https://example.jobs.feishu.cn/index/position"


def _rt(parent, name):
    return {"id": "101", "name": name, "en_name": "x",
            "parent": {"id": "1", "name": parent, "en_name": "y"} if parent else None}


def _post(title, recruit_type, *, description="岗位职责：负责相关工作。", requirement="本科及以上学历。",
          category=None, pid="7000000000000000001"):
    return {"id": pid, "title": title, "description": description, "requirement": requirement,
            "job_category": {"name": category} if category else None,
            "city_info": {"name": "上海"}, "recruit_type": recruit_type}


# 全量里出现过的全部 (上一层, 下一层) → 交给分类器的标签。
OBSERVED = {
    ("社招", "全职"): "社招",
    ("社招", "外包"): "社招",
    ("社招", "劳务"): "社招",
    ("社招", "顾问"): "社招",
    ("社招", "实习"): "实习",
    ("校招", "正式"): "校招",
    ("校招", "实习"): "",
}


class DeclaredRecruitLabelTest(unittest.TestCase):
    def test_every_observed_value(self):
        for (parent, name), want in OBSERVED.items():
            with self.subTest(parent=parent, name=name):
                self.assertEqual(feishu.declared_recruit_label(_rt(parent, name)), want)

    def test_child_level_is_never_passed_as_is(self):
        """「全职」读侧直接判社招（校招>全职 会被按住），「正式」读侧不认：下一层只用来认实习。"""
        self.assertEqual(feishu.declared_recruit_label(_rt("校招", "全职")), "校招")
        self.assertEqual(feishu.declared_recruit_label(_rt("社招", "正式")), "社招")

    def test_names_are_matched_by_containment(self):
        """同平台的字节租户下一层叫「暑期实习 / 日常实习」（test_bytedance 的夹具）；全等匹配会把它们带成 社招 / 校招。"""
        self.assertEqual(feishu.declared_recruit_label(_rt("社招", "日常实习")), "实习")
        self.assertEqual(feishu.declared_recruit_label(_rt("校招", "暑期实习")), "")
        self.assertEqual(feishu.declared_recruit_label(_rt("社会招聘", "全职")), "社招")
        self.assertEqual(feishu.declared_recruit_label(_rt("校园招聘", "正式")), "校招")
        self.assertEqual(feishu.declared_recruit_label(_rt(" 校招 ", " 实习 ")), "")

    def test_missing_or_unknown_gives_no_label(self):
        for value in (None, {}, "社招", {"name": "全职"}, {"name": "全职", "parent": None},
                      _rt("", "全职"), _rt("猎头", "全职"), {"name": "实习", "parent": "校招"}):
            with self.subTest(value=value):
                self.assertEqual(feishu.declared_recruit_label(value), "")


# 类别名自己读起来像招聘类型的：每一个都对应读侧某条规则里的一个词，拼进 job_type 会压过标签。
ADVERSARIAL_CATEGORIES = (
    "实习生", "Internship", "Interns",
    "社招", "社会招聘", "全职", "Experienced Hire", "Professional Services", "Full-time",
    "校招", "校园招聘", "校园大使", "应届生", "管培生", "管理培训生", "留学生专项", "毕业生招聘",
    "Campus Hire", "Graduate Program", "New Grad", "Entry Level",
)


class ComposeJobTypeTest(unittest.TestCase):
    def test_category_is_kept_next_to_label(self):
        self.assertEqual(feishu.compose_job_type("算法", "社招"), "算法 社招")
        self.assertEqual(feishu.compose_job_type("互联网 / 电子 / 网游", "校招"), "互联网 / 电子 / 网游 校招")

    def test_without_label_nothing_changes(self):
        self.assertEqual(feishu.compose_job_type("供应链", ""), "供应链")
        self.assertEqual(feishu.compose_job_type("", ""), "")
        self.assertEqual(feishu.compose_job_type("", "校招"), "校招")

    def test_category_that_reads_as_a_recruit_type_is_dropped(self):
        for category in ADVERSARIAL_CATEGORIES:
            with self.subTest(category=category):
                self.assertEqual(feishu.compose_job_type(category, "社招"), "社招")
                self.assertEqual(feishu.compose_job_type(category, "校招"), "校招")

    def test_lookalike_english_categories_are_kept(self):
        """intern 按整词认：International / Internal / Internet 不是招聘类型，类别名要留在检索文本里。"""
        for category in ("International Business", "Internal Audit", "Internet"):
            with self.subTest(category=category):
                self.assertEqual(feishu.compose_job_type(category, "社招"), f"{category} 社招")


class MapTest(unittest.TestCase):
    def _adapter(self):
        a = feishu.FeishuGenericAdapter()
        a._bind_host(SOURCE_URL)
        a._bind_website_path(SOURCE_URL)
        return a

    def test_label_reaches_job_type(self):
        a = self._adapter()
        self.assertEqual(a._map(_post("销售经理", _rt("社招", "全职"))).job_type, "社招")
        self.assertEqual(a._map(_post("销售经理", _rt("社招", "全职"), category="销售")).job_type, "销售 社招")
        self.assertEqual(a._map(_post("算法工程师", _rt("校招", "正式"))).job_type, "校招")
        self.assertEqual(a._map(_post("运营", _rt("社招", "实习"))).job_type, "实习")

    def test_rows_without_a_usable_label_keep_old_behaviour(self):
        a = self._adapter()
        self.assertIsNone(a._map(_post("销售经理", None)).job_type)
        self.assertEqual(a._map(_post("销售经理", None, category="销售")).job_type, "销售")
        self.assertEqual(a._map(_post("校招-顾问", _rt("校招", "实习"), category="销售")).job_type, "销售")


class EndToEndClassifyTest(unittest.TestCase):
    """真实链路：_map → normalize → 分类器。每条用例都是全量对拍里真出现过的那一类。"""

    def _classify(self, posts):
        a = feishu.FeishuGenericAdapter()
        a._bind_host(SOURCE_URL)
        a._bind_website_path(SOURCE_URL)
        rows = [normalizer.normalize(a._map(p), source_id="s", company="示例公司") for p in posts]
        out = recruitment_classify.classify(rows)
        self.assertTrue(all(cat is not None for cat, _, _ in out), "分类器没跑起来（node 不可用？）")
        return [(cat, explicit) for cat, explicit, _ in out]

    def test_declared_social_is_not_pulled_to_campus_by_body_text(self):
        got = self._classify([
            _post("国际销售代表", _rt("社招", "全职"), requirement="本科及以上，英语六级，应届生亦可；"),
            _post("招聘专员", _rt("社招", "全职"), description="负责部分社会招聘、校园招聘工作；"),
            _post("结构工程师", _rt("社招", "全职"), requirement="24-25届毕业生，机械类相关专业。"),
            _post("行政专员", _rt("社招", "劳务"), requirement="1-3年行政管理相关经验，优秀应届生可放宽。"),
        ])
        self.assertEqual(got, [("社招", True)] * 4)

    def test_declared_campus_without_any_text_signal_is_campus(self):
        """智元 / 小米新零售那一类：标题、正文、链接里都没有校招字样，只有对方自报。"""
        got = self._classify([_post("驱控算法工程师", _rt("校招", "正式"), requirement="硕士及以上学历，机器人相关专业。")])
        self.assertEqual(got, [("校招", True)])

    def test_declared_social_beats_a_campus_portal_path(self):
        """对方给这个岗填的类型（层3）排在链接里的门户路径（层4）前面：校招门户里挂的自报社招岗判社招。"""
        a = feishu.FeishuGenericAdapter()
        campus_url = "https://example.jobs.feishu.cn/campus/position"
        a._bind_host(campus_url)
        a._bind_website_path(campus_url)
        rows = [normalizer.normalize(a._map(_post("销售经理", rt)), source_id="s", company="示例公司")
                for rt in (_rt("社招", "全职"), None)]
        self.assertIn("/campus/position/", rows[0]["jd_url"])
        got = [cat for cat, _, _ in recruitment_classify.classify(rows)]
        self.assertEqual(got, ["社招", "校招"])

    def test_title_internship_still_wins_over_declared_social(self):
        got = self._classify([_post("大模型后训练实习生", _rt("社招", "全职"))])
        self.assertEqual(got, [("实习", True)])

    def test_declared_campus_with_stated_experience_stays_social(self):
        got = self._classify([_post("硬件电子工程师", _rt("校招", "正式"),
                                    requirement="统招本科及以上学历，3年以上嵌入式硬件开发经验。")])
        self.assertEqual(got, [("社招", True)])

    def test_social_internship_without_intern_in_title_is_internship(self):
        got = self._classify([_post("顾问助理-增城-大三", _rt("社招", "实习"))])
        self.assertEqual(got, [("实习", True)])

    def test_campus_internship_is_left_to_title_and_body(self):
        """「校招 > 实习」不带标签：蔚来「校招-…」那批照旧按正文的届别判校招，标题写实习的照旧判实习。"""
        got = self._classify([
            _post("校招-顾问-榆林", _rt("校招", "实习"),
                  requirement="2027届应届毕业生，大专及以上学历；本岗位将邀请您提前参与带薪实习体验。"),
            _post("实习-数据分析", _rt("校招", "实习")),
        ])
        self.assertEqual([cat for cat, _ in got], ["校招", "实习"])

    def test_composed_job_type_always_classifies_as_its_label(self):
        """类别名再怪，拼出来的 job_type 也必须按标签那一桶判（防读侧词表与 _RECRUIT_WORD_RE 漂移）。"""
        categories = ("", "研发", "算法", "互联网 / 电子 / 网游", "International Business",
                      "Internal Audit") + ADVERSARIAL_CATEGORIES
        rows, want = [], []
        for label in ("社招", "校招", "实习"):
            for category in categories:
                rows.append({"title": "岗位", "job_type": feishu.compose_job_type(category, label)})
                want.append(label)
        got = [cat for cat, _, _ in recruitment_classify.classify(rows)]
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
