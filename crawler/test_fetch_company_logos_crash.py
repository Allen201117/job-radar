"""main() 中途崩溃必须留痕：补写 ops_runs(status=failed, crash=<异常类名>) 再原样抛出。

独立于 test_fetch_company_logos.py（那个文件测的是纯判据），避免混在一起改坏了不好定位。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_company_logos as M


class MainCrashRecordsFailedLedgerTest(unittest.TestCase):
    def test_crash_after_supabase_obtained_writes_failed_and_reraises(self):
        with patch.object(M, "get_supabase", return_value="fake-supabase-client"), \
             patch.object(M, "_run", side_effect=RuntimeError("boom")), \
             patch.object(M.ops_runs, "record_ops_run") as rec, \
             patch("sys.argv", ["fetch_company_logos.py"]):
            with self.assertRaises(RuntimeError):
                M.main()
            self.assertEqual(rec.call_count, 1)
            args, kwargs = rec.call_args
            self.assertEqual(args[0], "fake-supabase-client")
            self.assertEqual(args[1], "company_logos")
            self.assertEqual(args[2], {"crash": "RuntimeError"})
            self.assertEqual(args[3], "failed")

    def test_supabase_itself_failing_reraises_without_calling_record_ops_run(self):
        with patch.object(M, "get_supabase", side_effect=ConnectionError("no db")), \
             patch.object(M.ops_runs, "record_ops_run") as rec, \
             patch("sys.argv", ["fetch_company_logos.py"]):
            with self.assertRaises(ConnectionError):
                M.main()
            rec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
