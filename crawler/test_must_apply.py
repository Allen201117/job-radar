import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

import must_apply


class MustApplyListTest(unittest.TestCase):
    def _json_file(self, rows):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "must-apply-list.json"
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return path

    def test_patterns_returns_all_industries_deduped_in_json_order(self):
        path = self._json_file({
            "互联网": [
                {"name": "字节跳动", "pattern": "%字节%"},
                {"name": "OPPO", "pattern": "%OPPO%"},
            ],
            "制造": [
                {"name": "重复公司", "pattern": "%字节%"},
                {"name": "比亚迪", "pattern": "%比亚迪%"},
            ],
        })

        with mock.patch.object(must_apply, "MUST_APPLY_JSON", path):
            self.assertEqual(must_apply.patterns(), ["%字节%", "%OPPO%", "%比亚迪%"])

    def test_old_list_shape_remains_compatible(self):
        path = self._json_file([
            {"name": "字节跳动", "pattern": "%字节%"},
            {"name": "OPPO", "pattern": "%OPPO%"},
        ])

        with mock.patch.object(must_apply, "MUST_APPLY_JSON", path):
            self.assertEqual(must_apply.patterns(), ["%字节%", "%OPPO%"])

    def test_by_industry_and_selected_industry_patterns(self):
        rows = {
            "互联网": [{"name": "字节跳动", "pattern": "%字节%"}],
            "制造": [
                {"name": "重复公司", "pattern": "%字节%"},
                {"name": "比亚迪", "pattern": "%比亚迪%"},
            ],
        }
        path = self._json_file(rows)

        with mock.patch.object(must_apply, "MUST_APPLY_JSON", path):
            self.assertEqual(must_apply.by_industry(), rows)
            self.assertEqual(must_apply.patterns_for_industries(["制造", "互联网"]),
                             ["%字节%", "%比亚迪%"])
            self.assertEqual(must_apply.patterns_for_industries(None),
                             ["%字节%", "%比亚迪%"])

    def test_version_metadata_and_brand_fields_do_not_break_python_reader(self):
        rows = {
            "_version": "2026Q3-v1",
            "物流": [{
                "name": "京东物流",
                "pattern": "%京东物流%",
                "parentPattern": "%京东%",
                "brandTokens": ["京东物流"],
            }],
        }
        path = self._json_file(rows)
        with mock.patch.object(must_apply, "MUST_APPLY_JSON", path):
            grouped = must_apply.by_industry()
            self.assertEqual(list(grouped), ["物流"])
            self.assertEqual(grouped["物流"][0]["brandTokens"], ["京东物流"])
            self.assertEqual(must_apply.patterns(), ["%京东物流%"])
            self.assertEqual(must_apply.version(), "2026Q3-v1")

    def test_company_patterns_are_pattern_plus_aliases(self):
        """别名 = 同一家公司在库里的其它写法（壳牌 ↔ Shell），与 pattern 同语义。"""
        self.assertEqual(
            must_apply.company_patterns({"pattern": "%壳牌%", "aliases": ["%Shell%"]}),
            ["%壳牌%", "%Shell%"],
        )
        # 没写别名 / 别名为空 → 行为与加别名前逐字一致
        self.assertEqual(must_apply.company_patterns({"pattern": "%甲%"}), ["%甲%"])
        self.assertEqual(must_apply.company_patterns({"pattern": "%甲%", "aliases": []}), ["%甲%"])
        # 空白、重复、非字符串一律不进匹配集（脏数据不该悄悄放宽匹配面）
        self.assertEqual(
            must_apply.company_patterns({"pattern": "%甲%", "aliases": [" ", "%甲%", None, "%A%"]}),
            ["%甲%", "%A%"],
        )
        self.assertEqual(must_apply.company_patterns(None), [])

    def test_patterns_include_aliases_so_membership_tests_see_english_names(self):
        path = self._json_file({
            "能源": [{"name": "壳牌", "pattern": "%壳牌%", "aliases": ["%Shell%"]}],
            "汽车": [{"name": "大陆集团", "pattern": "%大陆集团%", "aliases": ["%Continental%"]}],
        })
        with mock.patch.object(must_apply, "MUST_APPLY_JSON", path):
            self.assertEqual(must_apply.patterns(),
                             ["%壳牌%", "%Shell%", "%大陆集团%", "%Continental%"])
            # 探活倾斜/富化优先级都靠这个布尔判断，英文名不能再被漏掉
            self.assertTrue(must_apply.match_company("Shell China"))
            self.assertTrue(must_apply.match_company("Continental Automotive"))
            self.assertFalse(must_apply.match_company("随便公司"))

    def test_patterns_for_company_looks_up_aliases_by_list_name(self):
        path = self._json_file({
            "能源": [{"name": "壳牌", "pattern": "%壳牌%", "aliases": ["%Shell%"]}],
        })
        with mock.patch.object(must_apply, "MUST_APPLY_JSON", path):
            self.assertEqual(must_apply.patterns_for_company("壳牌"), ["%壳牌%", "%Shell%"])
            self.assertEqual(must_apply.patterns_for_company("不在清单里"), [])
            self.assertEqual(must_apply.patterns_for_company(""), [])

    def test_match_company_is_case_insensitive_substring(self):
        path = self._json_file([
            {"name": "字节跳动", "pattern": "%字节%"},
            {"name": "OPPO", "pattern": "%OPPO%"},
        ])

        with mock.patch.object(must_apply, "MUST_APPLY_JSON", path):
            self.assertTrue(must_apply.match_company("北京字节跳动科技有限公司"))
            self.assertTrue(must_apply.match_company("oppo广东移动通信有限公司"))
            self.assertTrue(must_apply.match_company_against_patterns(
                "国网江苏省电力有限公司（国家电网）", ["%国家电网%"]))
            self.assertFalse(must_apply.match_company("随便公司"))
            self.assertFalse(must_apply.match_company(""))

    def test_missing_file_warns_and_fails_open(self):
        missing = Path(tempfile.gettempdir()) / "job-radar-missing-must-apply-list.json"
        err = io.StringIO()

        with mock.patch.object(must_apply, "MUST_APPLY_JSON", missing), contextlib.redirect_stderr(err):
            self.assertEqual(must_apply.patterns(), [])
            self.assertFalse(must_apply.match_company("北京字节跳动科技有限公司"))

        self.assertIn("必投清单", err.getvalue())

    def test_overseas_patterns_and_all_patterns_dedupe_in_order(self):
        domestic = self._json_file([{"name": "国内", "pattern": "%共享%"}])
        overseas = self._json_file({
            "科技": [{"name": "Google", "pattern": "%Google%"}],
            "金融": [{"name": "重复", "pattern": "%共享%"}],
        })
        with mock.patch.object(must_apply, "MUST_APPLY_JSON", domestic), \
             mock.patch.object(must_apply, "OVERSEAS_MUST_APPLY_JSON", overseas):
            self.assertEqual(must_apply.overseas_patterns(), ["%Google%", "%共享%"])
            self.assertEqual(must_apply.all_patterns(), ["%共享%", "%Google%"])

    def test_overseas_missing_file_fails_open_without_changing_domestic_patterns(self):
        domestic = self._json_file([{"name": "国内", "pattern": "%国内%"}])
        missing = Path(tempfile.gettempdir()) / "job-radar-missing-overseas-must-apply-list.json"
        with mock.patch.object(must_apply, "MUST_APPLY_JSON", domestic), \
             mock.patch.object(must_apply, "OVERSEAS_MUST_APPLY_JSON", missing):
            self.assertEqual(must_apply.patterns(), ["%国内%"])
            self.assertEqual(must_apply.overseas_patterns(), [])
            self.assertEqual(must_apply.all_patterns(), ["%国内%"])


if __name__ == "__main__":
    unittest.main()
