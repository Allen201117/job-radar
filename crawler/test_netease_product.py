"""网易 adapter 按 productName 派生子公司归属的纯函数单测（零网络）。

盯住三条不变量：
  ① 能归一到必投清单的 productName → 写清单规范名（网易有道 / 网易云音乐）；
  ② 归一不出的 → 回落「网易」（与改造前逐字一致，不许留空）；
  ③ 派生名必须仍命中母公司「网易」的 `%网易%`，否则就是拆了子公司丢了母公司。
"""
import json
import unittest

import must_apply
from adapters.netease import (
    NeteaseAdapter,
    _derive_company,
    _load_product_company_map,
    _substring_pattern_token,
)


def _payload(rows):
    """包成 fetch() 的返回形状：{"_intercepted": [{"data": {"list": [...]}}]}。"""
    return json.dumps({"_intercepted": [{"data": {"list": rows}}]}, ensure_ascii=False)


class TestNeteaseProductDerivation(unittest.TestCase):
    def test_maps_products_present_in_must_apply_list(self):
        self.assertEqual(_derive_company("网易有道"), "网易有道")
        self.assertEqual(_derive_company("网易云音乐"), "网易云音乐")
        self.assertEqual(_derive_company("  网易有道  "), "网易有道")

    def test_unknown_products_fall_back_to_empty(self):
        # 这些取值都来自 2026-08-27 live 抓到的真实 productName 分布。
        for product in ("网易游戏（互娱）", "网易游戏（雷火）", "网易职能", "网易智企",
                        "网易传媒", "网易严选", "网易伏羲", "其他", "星间工作室", "美泰163"):
            self.assertEqual(_derive_company(product), "", product)

    def test_no_substring_collision_with_unrelated_company(self):
        # 清单里有「元气森林」(%元气森林%)；「网易元气」绝不能被误认成它。
        self.assertEqual(_derive_company("网易元气"), "")

    def test_blank_and_non_string_inputs(self):
        for product in (None, "", "   ", 123, [], {}):
            self.assertEqual(_derive_company(product), "")

    def test_substring_pattern_token(self):
        self.assertEqual(_substring_pattern_token("%网易%"), "网易")
        # 非「前后带 %」的形状一律拒绝 → 上层据此关闭派生。
        for bad in ("网易", "网易%", "%网易", "%%", "%网_易%", "%网%易%", None, 42, ""):
            self.assertEqual(_substring_pattern_token(bad), "", repr(bad))

    def test_derived_names_still_match_parent_pattern(self):
        """核心前提：派生名仍命中「网易」的 `%网易%`，母公司不会因为拆子公司而变缺口。"""
        derived = _load_product_company_map()
        self.assertIn("网易有道", derived)
        self.assertIn("网易云音乐", derived)
        parent = [c for companies in must_apply.by_industry().values()
                  for c in companies if c.get("name") == "网易"]
        self.assertEqual(len(parent), 1, "必投清单里应恰好有一行「网易」")
        token = _substring_pattern_token(parent[0].get("pattern"))
        self.assertEqual(token, "网易", "「网易」的 pattern 必须是 %网易% 子串模式")
        for name in derived:
            self.assertIn(token, name, f"{name} 不含 {token}，会把母公司弄丢")

    def test_parse_assigns_company_per_product(self):
        rows = [
            {"id": 1, "name": "高级算法工程师", "productName": "网易有道",
             "workPlaceNameList": ["北京市"], "description": "做题家教研"},
            {"id": 2, "name": "推荐算法工程师", "productName": "网易云音乐",
             "workPlaceNameList": ["杭州市"], "description": "歌曲推荐"},
            {"id": 3, "name": "游戏客户端开发", "productName": "网易游戏（互娱）",
             "workPlaceNameList": ["广州市"], "description": "客户端"},
            {"id": 4, "name": "HRBP", "productName": "", "workPlaceNameList": ["杭州市"]},
            {"id": 5, "name": "财务分析", "workPlaceNameList": ["杭州市"]},  # 无 productName 字段
        ]
        jobs = NeteaseAdapter().parse(_payload(rows))
        self.assertEqual([j.company for j in jobs],
                         ["网易有道", "网易云音乐", "网易", "网易", "网易"])
        self.assertEqual(jobs[0].jd_url, "https://hr.163.com/job-detail.html?id=1")
        self.assertEqual(jobs[0].location, "北京市")


if __name__ == "__main__":
    unittest.main()
