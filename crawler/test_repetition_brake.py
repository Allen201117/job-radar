"""重复度刹车（RepetitionBrake）单测。

治的病：2026-09-04 把单源上限 600→8000 之后，一轮多入库 5.2 万岗，其中 2.1 万（41%）是
三家门店批量发布（星巴克 9,044 行只有 34 种归一标题）。可测后果：杭州 20%、上海 12%、
北京 9.7% 的在招岗变成这三家的门店副本。

这里钉死三件事：
  ① 批量源会被刹住；② 正常源**绝不**被误刹（误刹 = 漏抓真岗，比不刹更严重）；
  ③ 刹停后 fetch_complete 必须是 False（否则 list-absence 会把没翻到的尾巴整批判撤岗）。
"""
import os
import unittest

from adapters.base import (DEFAULT_REPEAT_STALL_ROWS, RepetitionBrake,
                           normalize_title_for_repetition, resolve_repeat_stall_rows)


class NormalizeTitleTest(unittest.TestCase):
    def test_strips_job_id_and_leading_name_segment(self):
        # 我爱我家式标题：姓名- + 门店名 + (J岗位号)
        self.assertEqual(normalize_title_for_repetition("何奇-公园悦府新租赁A店(J726033)"),
                         "公园悦府新租赁A店")

    def test_full_time_and_part_time_same_role_collapse(self):
        # 星巴克把用工形式写进标题；对「还有没有新角色」这个问题它们是同一个角色。
        self.assertEqual(normalize_title_for_repetition("全职 | 星级咖啡师"),
                         normalize_title_for_repetition("兼职 |星级咖啡师（学生兼职）"))

    def test_distinct_professional_roles_stay_distinct(self):
        a = normalize_title_for_repetition("【智界汽车】制造中心-制造工程部（ME）-总装工艺主任师(J32190)")
        b = normalize_title_for_repetition("【智界汽车】制造中心-制造工程部（ME）-项目管理主任师(J32192)")
        self.assertNotEqual(a, b)

    def test_non_string_input_does_not_raise(self):
        self.assertEqual(normalize_title_for_repetition(None), "")
        self.assertEqual(normalize_title_for_repetition(12345), "")


class RepetitionBrakeTest(unittest.TestCase):
    def test_trips_after_stall_rows_without_new_role(self):
        brake = RepetitionBrake(stall_rows=100)
        self.assertFalse(brake.observe(["星级咖啡师"] * 50))   # 第一页带来 1 个新角色
        self.assertFalse(brake.observe(["星级咖啡师"] * 50))   # 停滞 50
        self.assertTrue(brake.observe(["星级咖啡师"] * 50))    # 停滞 100 → 刹停
        self.assertTrue(brake.tripped)

    def test_new_role_resets_the_counter(self):
        brake = RepetitionBrake(stall_rows=100)
        brake.observe(["A"] * 50)
        brake.observe(["A"] * 50)          # 停滞 50
        self.assertFalse(brake.observe(["A"] * 49 + ["B"]))   # 出现新角色 → 归零
        self.assertFalse(brake.observe(["B"] * 50))           # 只停滞 50，还不到 100

    def test_diverse_source_never_trips(self):
        """正常源必须一路放行——误刹 = 漏抓真岗。奇瑞实测每 50 条带来 ~26 个新角色。

        ⚠️ 造数据别只靠数字区分（"工程师1"/"工程师2"）——归一会去数字、把它们判成同一个角色，
        那是**刻意**的（同一角色开 N 个坑不是新信息），但会让这条断言测的东西跑偏。"""
        brake = RepetitionBrake(stall_rows=DEFAULT_REPEAT_STALL_ROWS)
        words = ["总装工艺", "项目管理", "造型设计", "内外饰采购", "数字架构", "整车电子",
                 "底盘调校", "电池热管理", "供应链质量", "海外市场"]
        for page in range(20):
            titles = [f"{a}{b}主任师" for a in words for b in words][page * 50:(page + 1) * 50]
            self.assertFalse(brake.observe(titles), f"第 {page} 页误刹")
        self.assertFalse(brake.tripped)

    def test_titles_differing_only_by_digits_are_the_same_role(self):
        """刻意行为：同一角色开 N 个坑（"星级咖啡师1..N"）不是新信息，不该顶开刹车。"""
        brake = RepetitionBrake(stall_rows=100)
        brake.observe([f"星级咖啡师{i}" for i in range(50)])
        brake.observe([f"星级咖啡师{i}" for i in range(50, 100)])
        self.assertTrue(brake.observe([f"星级咖啡师{i}" for i in range(100, 150)]))

    def test_blank_titles_neither_count_as_new_nor_reset(self):
        """取不到标题的行不该被当成「新角色」而把刹车永远顶开。"""
        brake = RepetitionBrake(stall_rows=100)
        brake.observe(["A"] * 50)
        self.assertFalse(brake.observe([""] * 50))    # 空串不算新角色 → 继续累计停滞
        self.assertTrue(brake.observe([""] * 50))

    def test_disabled_by_zero_stall_rows(self):
        brake = RepetitionBrake(stall_rows=0)
        for _ in range(100):
            self.assertFalse(brake.observe(["同一个岗"] * 50))
        self.assertFalse(brake.tripped)


class ResolveStallRowsTest(unittest.TestCase):
    def test_env_override(self):
        old = os.environ.get("CRAWL_REPEAT_STALL_ROWS")
        try:
            os.environ["CRAWL_REPEAT_STALL_ROWS"] = "42"
            self.assertEqual(resolve_repeat_stall_rows(), 42)
            os.environ["CRAWL_REPEAT_STALL_ROWS"] = "0"      # 0 = 关掉刹车
            self.assertEqual(resolve_repeat_stall_rows(), 0)
            os.environ["CRAWL_REPEAT_STALL_ROWS"] = "不是数字"
            self.assertEqual(resolve_repeat_stall_rows(), DEFAULT_REPEAT_STALL_ROWS)
        finally:
            os.environ.pop("CRAWL_REPEAT_STALL_ROWS", None)
            if old is not None:
                os.environ["CRAWL_REPEAT_STALL_ROWS"] = old


if __name__ == "__main__":
    unittest.main()
