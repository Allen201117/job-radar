"""main() 中途崩溃必须留痕：补写 ops_runs(status=failed, crash=<异常类名>) 再原样抛出。

另覆盖 2026-09-23 修的 bug：`_usable()` 曾只认 template，把 fetch() 已经证明可用的
{"cms"/"ssr"/"cards": true} 标记全判成「不可用」——26 个待探租户里 25 个（2 cms + 23 ssr）
因此天天被当成「还没探出路由」重探，harvested 连续 3 天卡 0。
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harvest_beisen_routes as M


class UsableAcceptsAllZeroBrowserMarkersTest(unittest.TestCase):
    """`_usable()` 必须复用 china_ats._beisen_route_usable，不能另起一套判据——
    两处一旦漂移，fetch() 判定「可用」的路由会在这里被判成「不可用」而永远不落盘。"""

    def test_template_dict_is_usable(self):
        route = {"template": "https://x.zhiye.com/social/detail?jobAdId={id}", "idfield": "Id"}
        self.assertEqual(M._usable(route), route)

    def test_plain_string_base_is_usable(self):
        self.assertEqual(M._usable("https://x.zhiye.com/social/detail"), "https://x.zhiye.com/social/detail")

    def test_cms_marker_is_usable(self):
        self.assertEqual(M._usable({"cms": True}), {"cms": True})

    def test_cards_marker_is_usable(self):
        self.assertEqual(M._usable({"cards": True}), {"cards": True})

    def test_ssr_marker_is_usable(self):
        self.assertEqual(M._usable({"ssr": True}), {"ssr": True})

    def test_none_and_empty_are_unusable(self):
        self.assertIsNone(M._usable(None))
        self.assertIsNone(M._usable(""))
        self.assertIsNone(M._usable({}))

    def test_dict_without_any_known_key_is_unusable(self):
        """防呆：随便一个 dict（比如误传了别的结构）不能被当成可用路由。"""
        self.assertIsNone(M._usable({"foo": True}))

    def test_legacy_ssr_path_param_shape_is_unusable(self):
        """别把被禁的 {ssr_path, ssr_param} 老残留形状跟新加的 {"ssr": true} 标记搞混——
        前者配不了新版接口的 uuid，必须继续判不可用。"""
        self.assertIsNone(M._usable({"ssr_path": "zwxq", "ssr_param": "jobId"}))


class DescribeTest(unittest.TestCase):
    def test_string_route(self):
        self.assertEqual(M._describe("https://x.zhiye.com/social/detail"),
                          "https://x.zhiye.com/social/detail")

    def test_template_dict(self):
        self.assertEqual(M._describe({"template": "https://x.zhiye.com/social/detail?jobAdId={id}"}),
                          "https://x.zhiye.com/social/detail?jobAdId={id}")

    def test_cms_marker(self):
        self.assertEqual(M._describe({"cms": True}), "cms")

    def test_cards_marker(self):
        self.assertEqual(M._describe({"cards": True}), "cards")

    def test_ssr_marker(self):
        self.assertEqual(M._describe({"ssr": True}), "ssr")


class RunHarvestsZeroBrowserTenantsTest(unittest.TestCase):
    """`_run()` 端到端回归：CMS/ssr 首次探测成功必须真的被数进 harvested、真的落盘，
    不能像修之前那样连续 3 天 attempted=26/harvested=0（watchdog 规则 A 因此报警）。"""

    def setUp(self):
        self._saved_cache = dict(M.china_ats._BEISEN_ROUTE_CACHE)
        M.china_ats._BEISEN_ROUTE_CACHE.clear()
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        Path(path).write_text("{}", encoding="utf-8")
        self._tmp_path = Path(path)
        self._patcher = mock.patch.object(M, "_ROUTES_FILE", self._tmp_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_path.unlink(missing_ok=True)
        M.china_ats._BEISEN_ROUTE_CACHE.clear()
        M.china_ats._BEISEN_ROUTE_CACHE.update(self._saved_cache)

    def test_cms_ssr_and_browser_successes_all_counted(self):
        rows = [
            {"source_url": "https://cms-tenant.zhiye.com/social", "enabled": True, "notes": None},
            {"source_url": "https://ssr-tenant.zhiye.com/social", "enabled": True, "notes": None},
            {"source_url": "https://needs-browser.zhiye.com/social", "enabled": True, "notes": None},
        ]

        def fake_fetch(self_adapter, source_url):
            host = source_url.split("/")[2]
            if host == "cms-tenant.zhiye.com":
                M.china_ats._BEISEN_ROUTE_CACHE[host] = {"cms": True}
                return '{"_ssr_jobs": []}'
            if host == "ssr-tenant.zhiye.com":
                M.china_ats._BEISEN_ROUTE_CACHE[host] = {"ssr": True}
                return '{"_ssr_jobs": []}'
            # 第三家模拟「真需要浏览器点击捕获」但探不到路由的情况——不该被算作 harvested。
            M.china_ats._BEISEN_ROUTE_CACHE[host] = None
            return '{"_intercepted": [{"Data": [], "Count": 0}]}'

        with mock.patch.object(M.db, "fetch_all_rows", return_value=rows), \
             mock.patch.object(M.china_ats.BeisenAdapter, "fetch", fake_fetch), \
             mock.patch.object(M.ops_runs, "record_ops_run") as rec:
            M._run("fake-sb", datetime.now(timezone.utc))

        args, _kwargs = rec.call_args
        self.assertEqual(args[1], "harvest_beisen_routes")
        metrics = args[2]
        self.assertEqual(metrics["attempted"], 3)
        self.assertEqual(metrics["harvested"], 2, "cms + ssr 两家零浏览器可抓的必须都算进 harvested")

        saved = json.loads(self._tmp_path.read_text(encoding="utf-8"))
        self.assertEqual(saved.get("cms-tenant.zhiye.com"), {"cms": True})
        self.assertEqual(saved.get("ssr-tenant.zhiye.com"), {"ssr": True})
        self.assertNotIn("needs-browser.zhiye.com", saved,
                          "探不到路由的租户不许落盘（None 不可用，留待下次重试）")


class MainCrashRecordsFailedLedgerTest(unittest.TestCase):
    def test_crash_after_supabase_obtained_writes_failed_and_reraises(self):
        with patch.object(M.db, "get_supabase", return_value="fake-supabase-client"), \
             patch.object(M, "_run", side_effect=RuntimeError("boom")), \
             patch.object(M.ops_runs, "record_ops_run") as rec, \
             patch("sys.argv", ["prog.py"]):
            with self.assertRaises(RuntimeError):
                M.main()
            self.assertEqual(rec.call_count, 1)
            args, kwargs = rec.call_args
            self.assertEqual(args[0], "fake-supabase-client")
            self.assertEqual(args[1], "harvest_beisen_routes")
            self.assertEqual(args[2], {"crash": "RuntimeError"})
            self.assertEqual(args[3], "failed")

    def test_supabase_itself_failing_reraises_without_calling_record_ops_run(self):
        with patch.object(M.db, "get_supabase", side_effect=ConnectionError("no db")), \
             patch.object(M.ops_runs, "record_ops_run") as rec, \
             patch("sys.argv", ["prog.py"]):
            with self.assertRaises(ConnectionError):
                M.main()
            rec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
