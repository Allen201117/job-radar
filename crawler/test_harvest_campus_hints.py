"""聚合站线索采集的离线单测（夹具 HTML，不打网络）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harvest_campus_hints as H


PAGE = """
<html><body>
  <a href="https://join.fanruan.com/campus">帆软</a>
  <a href="/go?u=x" >查看详情</a>
  <a href="https://www.zhipin.com/job/1">某公司校招</a>
  <a href="https://app.mokahr.com/campus-recruitment/deepseek">DeepSeek</a>
  <a href="https://example.com/about">关于我们</a>
</body></html>
"""


class ExtractTest(unittest.TestCase):
    def test_keeps_only_apply_looking_official_links(self):
        pairs = dict(H.extract_pairs(PAGE, "https://agg.example/"))
        self.assertEqual(pairs.get("帆软"), "https://join.fanruan.com/campus")
        self.assertEqual(pairs.get("DeepSeek"),
                         "https://app.mokahr.com/campus-recruitment/deepseek")

    def test_third_party_platform_is_dropped(self):
        pairs = dict(H.extract_pairs(PAGE, "https://agg.example/"))
        self.assertNotIn("某公司校招", pairs)

    def test_generic_anchor_text_is_dropped(self):
        """「查看详情」当公司名会让 hint_for 永远打不中，还白占一条车道的退避窗口。"""
        self.assertNotIn("查看详情", dict(H.extract_pairs(PAGE, "https://agg.example/")))

    def test_non_recruiting_link_is_dropped(self):
        self.assertNotIn("关于我们", dict(H.extract_pairs(PAGE, "https://agg.example/")))

    def test_garbage_html_is_safe(self):
        self.assertEqual(H.extract_pairs(None, "https://x/"), [])


class MergeTest(unittest.TestCase):
    ROWS = [
        {"company": "帆软", "cn": "帆软"},
        {"company": "京东方", "cn": "京东方", "campus_url_hint": "https://boe.example/人工核实"},
        {"company": "京东", "cn": "京东"},
    ]

    def test_fills_empty_hint_only(self):
        merged, changed = H.merge_into_targets(
            self.ROWS, [("帆软", "https://join.fanruan.com"),
                        ("京东方", "https://聚合站给的.example")])
        self.assertEqual(changed, 1)
        self.assertEqual(merged[0]["campus_url_hint"], "https://join.fanruan.com")
        self.assertEqual(merged[1]["campus_url_hint"], "https://boe.example/人工核实",
                         "已有 hint 可能是人工核实过的，不许被未核实的聚合站链接盖掉")

    def test_overwrite_flag_forces(self):
        merged, changed = H.merge_into_targets(
            self.ROWS, [("京东方", "https://新的.example")], overwrite=True)
        self.assertEqual(changed, 1)
        self.assertEqual(merged[1]["campus_url_hint"], "https://新的.example")

    def test_exact_name_only_never_prefix_bleeds(self):
        """「京东方」的线索绝不能落到「京东」头上（张冠李戴红线）。"""
        merged, _changed = H.merge_into_targets(
            [{"company": "京东", "cn": "京东"}], [("京东方", "https://boe.example")])
        self.assertIsNone(merged[0].get("campus_url_hint"))

    def test_unmatched_hints_do_not_add_rows(self):
        merged, changed = H.merge_into_targets(
            self.ROWS, [("某没在清单里的公司", "https://x.example/campus")])
        self.assertEqual(changed, 0)
        self.assertEqual(len(merged), len(self.ROWS),
                         "targets 是我们决定要覆盖谁的清单，不该被抓取结果扩张")


if __name__ == "__main__":
    unittest.main()
