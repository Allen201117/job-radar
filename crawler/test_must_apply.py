import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import must_apply


class MustApplyListTest(unittest.TestCase):
    def _json_file(self, rows):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "must-apply-list.json"
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return path

    def test_patterns_reads_json_in_order(self):
        path = self._json_file([
            {"name": "字节跳动", "pattern": "%字节%"},
            {"name": "OPPO", "pattern": "%OPPO%"},
        ])

        with mock.patch.object(must_apply, "MUST_APPLY_JSON", path):
            self.assertEqual(must_apply.patterns(), ["%字节%", "%OPPO%"])

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


if __name__ == "__main__":
    unittest.main()
