"""F2 回归：浏览器巡检的判死信号不能把在招岗误杀。

缺陷原貌（2026-09-08 修）：DEAD_MARKERS 是一张扁平表，对整个 body 做裸子串匹配，且匹配顺序
排在「标题是否在场」之前。于是一个正常在招的岗位，正文里写着「职位编号 404123」，就会命中裸词
"404" 被判 dead → --apply 当场置 expired → 次日被 purge-expired **永久删除**。

判死是不可逆操作，所以这里守的方向是：**证据不足时必须落到 suspect/unsure，不许落到 dead。**
"""
import unittest

from audit_dead_links import classify


class FakePage:
    def __init__(self, text):
        self._text = text

    def inner_text(self, _selector, timeout=0):
        return self._text


def verdict(text, title):
    return classify(FakePage(text), title)[0]


class TestDeadMarkerPrecision(unittest.TestCase):
    # ---- 误杀方向：这些都是在招岗，一个都不许判 dead ----
    def test_job_number_containing_404_is_not_dead(self):
        text = "软件工程师\n职位编号 404123，负责推荐系统研发，欢迎投递。工作地点：北京。"
        self.assertEqual(verdict(text, "软件工程师"), "alive")

    def test_postcode_404100_alone_is_not_dead(self):
        # 标题没渲染出来（suspect 场景），但 404100 是更长数字的一截，不构成 404 页证据
        text = "岗位描述" + "。" * 60 + "\n通讯地址：重庆市万州区某路，邮编 404100。"
        self.assertEqual(verdict(text, "数据分析师"), "suspect")

    def test_footer_activity_ended_is_not_dead(self):
        text = "产品经理\n岗位职责：负责产品规划。\n页脚：2025 校园宣讲活动已结束。"
        self.assertEqual(verdict(text, "产品经理"), "alive")

    def test_other_item_offline_is_not_dead(self):
        text = "算法工程师\n相关推荐：某某岗位已下线\n岗位职责：负责模型训练。"
        self.assertEqual(verdict(text, "算法工程师"), "alive")

    # ---- 漏判方向：真死岗仍要判出来，修复不能把探活变成摆设 ----
    def test_real_404_page_is_dead(self):
        self.assertEqual(verdict("404 Not Found", "软件工程师"), "dead")

    def test_closed_page_with_title_still_dead(self):
        # 强信号：整句话只可能是「这个岗没了」，标题在场也判死（多数关闭页会连标题一起渲染）
        text = "软件工程师\n该职位已下线，感谢你的关注。"
        self.assertEqual(verdict(text, "软件工程师"), "dead")

    def test_strong_marker_variants_still_dead(self):
        for phrase in ["该职位不存在", "岗位已关闭", "已招满", "招聘已结束", "this job is no longer open"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(verdict(f"提示：{phrase}", "产品经理"), "dead")

    def test_weak_marker_without_title_is_dead(self):
        # 标题不在场 + 弱信号 → 仍判死（真 404 页的典型形态）
        text = "很抱歉，页面不见了。" + "错误代码 404。" + "返回首页" * 10
        self.assertEqual(verdict(text, "运营专员"), "dead")

    # ---- 未知仍是未知，不许升级成任何确定结论 ----
    def test_blank_page_is_unsure(self):
        self.assertEqual(verdict("", "软件工程师"), "unsure")

    def test_long_page_without_title_or_marker_is_suspect(self):
        self.assertEqual(verdict("欢迎访问招聘首页。" * 20, "软件工程师"), "suspect")


if __name__ == "__main__":
    unittest.main()
