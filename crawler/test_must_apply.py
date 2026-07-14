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

    def test_match_company_is_case_insensitive_substring(self):
        path = self._json_file([
            {"name": "字节跳动", "pattern": "%字节%"},
            {"name": "OPPO", "pattern": "%OPPO%"},
        ])

        with mock.patch.object(must_apply, "MUST_APPLY_JSON", path):
            self.assertTrue(must_apply.match_company("北京字节跳动科技有限公司"))
            self.assertTrue(must_apply.match_company("oppo广东移动通信有限公司"))
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
