"""必投清单归属判定（must_apply.resolve_owner / sources_for）——纯函数，零网络。

服务的是**事实接地**：拿公司自有官方域名去核校招日期。判错归属 = 把 A 公司的时间挂到 B 头上，
比覆盖统计错一格严重得多，所以这里的用例都是真实踩过或差点踩的坑。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import must_apply as M  # noqa: E402


NAMES = ["京东", "京东物流", "京东科技", "京东方", "腾讯", "腾讯音乐",
         "工商银行", "网易", "网易有道", "阿里巴巴"]


class ResolveOwnerTest(unittest.TestCase):
    def test_longer_list_name_wins_so_boe_is_not_jd(self):
        """京东方(BOE) 与京东是**两家公司**。裸子串 `%京东%` 会把它算成京东 →
        用 boe.com 给京东的校招日期做接地 = 张冠李戴红线。"""
        self.assertEqual(M.resolve_owner("京东方", NAMES), "京东方")
        self.assertEqual(M.resolve_owner("京东方科技集团", NAMES), "京东方")

    def test_plain_name_is_not_stolen_by_longer_entry(self):
        """反向不变量：库里的「京东」不能被更长的「京东科技」抢走。
        （曾经把规则写成双向包含就栽在这，见 resolve_owner docstring。）"""
        self.assertEqual(M.resolve_owner("京东", NAMES), "京东")
        self.assertEqual(M.resolve_owner("网易", NAMES), "网易")

    def test_db_name_longer_than_list_name(self):
        """实际错配全是这个方向——库里写实体全称/带后缀，清单写品牌短名。"""
        self.assertEqual(M.resolve_owner("腾讯音乐 TME", NAMES), "腾讯音乐")
        self.assertEqual(M.resolve_owner("中国工商银行", NAMES), "工商银行")
        self.assertEqual(M.resolve_owner("阿里巴巴控股集团", NAMES), "阿里巴巴")

    def test_subsidiary_keeps_its_own_identity(self):
        self.assertEqual(M.resolve_owner("京东物流", NAMES), "京东物流")
        self.assertEqual(M.resolve_owner("网易有道", NAMES), "网易有道")

    def test_unrelated_and_empty(self):
        self.assertEqual(M.resolve_owner("某不相干公司", NAMES), "")
        self.assertEqual(M.resolve_owner("", NAMES), "")
        self.assertEqual(M.resolve_owner(None, NAMES), "")
        self.assertEqual(M.resolve_owner("京东", []), "")


class SourcesForTest(unittest.TestCase):
    ROWS = [
        {"company": "京东", "source_url": "https://zhaopin.jd.com/a"},
        {"company": "京东方", "source_url": "https://boe.com/careers"},
        {"company": "京东物流", "source_url": "https://jdl.com/x"},
        {"company": "腾讯音乐 TME", "source_url": "https://join.tencentmusic.com/y"},
        {"company": "无关公司", "source_url": "https://other.com/z"},
    ]

    def test_boe_rows_never_leak_into_jd(self):
        urls = [r["source_url"] for r in M.sources_for("京东", self.ROWS, NAMES)]
        self.assertEqual(urls, ["https://zhaopin.jd.com/a"])
        self.assertNotIn("https://boe.com/careers", urls)

    def test_suffixed_db_name_is_picked_up(self):
        urls = [r["source_url"] for r in M.sources_for("腾讯音乐", self.ROWS, NAMES)]
        self.assertEqual(urls, ["https://join.tencentmusic.com/y"])

    def test_no_match_returns_empty(self):
        self.assertEqual(M.sources_for("工商银行", self.ROWS, NAMES), [])

    def test_handles_junk_rows(self):
        rows = self.ROWS + [None, {}, {"company": None}]
        self.assertEqual(len(M.sources_for("京东", rows, NAMES)), 1)


class OwnerIndexAliasTest(unittest.TestCase):
    """别名感知归属：库里用英文名记着这家公司时，也要能归到清单的中文名下。

    `resolve_owner` 是**单向子串**（清单名 ⊂ 库里名），救不了「Shell vs 壳牌」这种
    字面完全不重叠的 —— 2026-09-04 因此把壳牌判成零源、重复插了一条源。
    """

    INDEX = {"壳牌": "壳牌", "Shell": "壳牌", "大陆集团": "大陆集团",
             "Continental": "大陆集团", "京东": "京东", "京东方": "京东方"}

    def test_english_alias_resolves_to_list_name(self):
        self.assertEqual(M.resolve_owner("Shell", self.INDEX), "壳牌")
        self.assertEqual(M.resolve_owner("Continental Automotive", self.INDEX), "大陆集团")

    def test_mapping_keeps_longest_wins_so_boe_is_not_jd(self):
        self.assertEqual(M.resolve_owner("京东方科技集团", self.INDEX), "京东方")
        self.assertEqual(M.resolve_owner("京东", self.INDEX), "京东")

    def test_plain_name_list_behaviour_is_unchanged(self):
        """老调用方（传名字列表）行为必须逐字不变。"""
        self.assertEqual(M.resolve_owner("腾讯音乐 TME", NAMES), "腾讯音乐")
        self.assertEqual(M.resolve_owner("某不相干公司", NAMES), "")

    def test_sources_for_accepts_the_alias_index(self):
        rows = [{"company": "Shell", "source_url": "https://shell.wd3.myworkdayjobs.com/x"},
                {"company": "无关公司", "source_url": "https://other.com/z"}]
        urls = [r["source_url"] for r in M.sources_for("壳牌", rows, self.INDEX)]
        self.assertEqual(urls, ["https://shell.wd3.myworkdayjobs.com/x"])

    def test_real_owner_index_covers_the_two_known_pairs(self):
        index = M.owner_index("domestic")
        self.assertEqual(index.get("Continental"), "大陆集团")
        self.assertEqual(index.get("Shell"), "壳牌")
        self.assertEqual(M.resolve_owner("Continental", index), "大陆集团")

    def test_canonical_names_always_beat_aliases_in_the_merged_index(self):
        """同一家公司在两份清单里叫两个名字（国内「大陆集团」/ 海外「Continental」）。
        并集索引里规范名必须压过别名，否则归属会随清单读取顺序漂。"""
        index = M.owner_index()
        for name in M.all_names():
            self.assertEqual(index.get(name), name)
        self.assertEqual(index.get("Continental"), "Continental")


class AllNamesTest(unittest.TestCase):
    def test_returns_real_list_and_is_deduped(self):
        names = M.all_names()
        self.assertGreater(len(names), 100)
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("京东", names)


if __name__ == "__main__":
    unittest.main()
