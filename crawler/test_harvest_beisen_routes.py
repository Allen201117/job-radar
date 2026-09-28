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
import ops_watchdog as W


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


class PendingHostsQueueTest(unittest.TestCase):
    """2026-09-23~27 建发集团（chinacdc.zhiye.com）每晚探失败的根因：同 host 两条源，旧实现按 id 序取第一条，
    探的是人工定论「永久停用、勿再探」的 /campus 空壳（迁移 201），而不是 enabled 的老版 CMS /subzw/（迁移 199）。"""

    CAMPUS = {"source_url": "https://chinacdc.zhiye.com/campus", "enabled": False,
              "notes": "gap_funnel:closed 该租户只有 /subzw/ 一个板块（2026-08-28 live 逐路径确认）…此行永久停用，勿再探"}
    SUBZW = {"source_url": "https://chinacdc.zhiye.com/subzw/", "enabled": True,
             "notes": "gap_funnel:accepted 板块路径是 /subzw/ 不是 /social"}

    def test_enabled_row_wins_even_when_listed_second(self):
        self.assertEqual(M._pending_hosts([self.CAMPUS, self.SUBZW], {}),
                         [("chinacdc.zhiye.com", "https://chinacdc.zhiye.com/subzw/")])

    def test_closed_funnel_row_alone_is_not_probed(self):
        self.assertEqual(M._pending_hosts([self.CAMPUS], {}), [])

    def test_pending_funnel_row_is_still_probed(self):
        """「漏斗待验收」的 disabled 源仍要探（否则北森新租户永远拿不到路由 → 永远验收不了，死结）。"""
        row = {"source_url": "https://newco.zhiye.com/social", "enabled": False, "notes": "gap_funnel:pending"}
        self.assertEqual(M._pending_hosts([row], {}), [("newco.zhiye.com", "https://newco.zhiye.com/social")])

    def test_plain_disabled_row_is_not_probed(self):
        row = {"source_url": "https://off.zhiye.com/social", "enabled": False, "notes": "人工停用"}
        self.assertEqual(M._pending_hosts([row], {}), [])

    def test_cached_hosts_are_skipped(self):
        self.assertEqual(M._pending_hosts([self.SUBZW], {"chinacdc.zhiye.com": {"cms": True}}), [])


class BrowserOnlyPayloadTest(unittest.TestCase):
    def test_ssr_jobs_with_jd_url_is_browser_only(self):
        payload = json.dumps({"_ssr_jobs": [{"title": "投资经理", "jd_url": "https://huaan.zhiye.com/zpdetail/123456"}]})
        self.assertTrue(M._browser_only_payload(payload))

    def test_new_version_list_without_route_is_not(self):
        """新版接口的列表抓到了、路由没探出来 = 真失败（jd_url 拼不出），不能算 browser_only。"""
        self.assertFalse(M._browser_only_payload('{"_intercepted": [{"Data": [{"Id": "x"}], "Count": 1}]}'))

    def test_empty_or_linkless_ssr_jobs_is_not(self):
        self.assertFalse(M._browser_only_payload('{"_ssr_jobs": []}'))
        self.assertFalse(M._browser_only_payload('{"_ssr_jobs": [{"title": "x", "jd_url": ""}]}'))

    def test_garbage_is_not(self):
        for payload in (None, "", "not json", "[]", 123):
            with self.subTest(payload=payload):
                self.assertFalse(M._browser_only_payload(payload))


class RunReproducesSept27QueueTest(unittest.TestCase):
    """复刻 09-25~27 的待探队列（只剩建发 + 华安）：旧代码 attempted=2 / harvested=0 → status=failed →
    规则 A 连续零产出。修后：建发探 /subzw/ 登记 {"cms": true}；华安判「只能浏览器」不计入 attempted。"""

    def setUp(self):
        self._saved_cache = dict(M.china_ats._BEISEN_ROUTE_CACHE)
        M.china_ats._BEISEN_ROUTE_CACHE.clear()
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        Path(path).write_text("{}", encoding="utf-8")
        self._tmp_path = Path(path)
        self._patcher = mock.patch.object(M, "_ROUTES_FILE", self._tmp_path)
        self._patcher.start()
        self.fetched = []

    def tearDown(self):
        self._patcher.stop()
        self._tmp_path.unlink(missing_ok=True)
        M.china_ats._BEISEN_ROUTE_CACHE.clear()
        M.china_ats._BEISEN_ROUTE_CACHE.update(self._saved_cache)

    def _fake_fetch(self, source_url):
        self.fetched.append(source_url)
        host = source_url.split("/")[2]
        if source_url == "https://chinacdc.zhiye.com/campus":
            raise RuntimeError("beisen: SSR 列表页无 jobId/adId 锚点（非老版 SSR 或被反爬）host=chinacdc.zhiye.com")
        if source_url == "https://chinacdc.zhiye.com/subzw/":
            M.china_ats._BEISEN_ROUTE_CACHE[host] = {"cms": True}
            return json.dumps({"_ssr_jobs": [{"title": "投资经理",
                                              "jd_url": "https://chinacdc.zhiye.com/zwxq?jobId=561284174"}]})
        if host == "huaan.zhiye.com":   # 浏览器 _fetch_ssr 直接取页面锚点：抓得到岗，不登记任何路由
            return json.dumps({"_ssr_jobs": [{"title": "研究员", "jd_url": "https://huaan.zhiye.com/zpdetail/1234567"}]})
        raise AssertionError(source_url)

    def _run(self, rows):
        test = self

        def fake_fetch(_adapter, url):
            return test._fake_fetch(url)

        with mock.patch.object(M.db, "fetch_all_rows", return_value=rows), \
             mock.patch.object(M.china_ats.BeisenAdapter, "fetch", fake_fetch), \
             mock.patch.object(M.ops_runs, "record_ops_run") as rec:
            M._run("fake-sb", datetime.now(timezone.utc))
        return rec.call_args.args

    @staticmethod
    def _ledger(metrics, status):
        return [{"module": "harvest_beisen_routes", "run_date": day, "status": status, "metrics": metrics}
                for day in ("2026-09-29", "2026-09-30")]

    def test_sept27_queue(self):
        rows = [PendingHostsQueueTest.CAMPUS, PendingHostsQueueTest.SUBZW,
                {"source_url": "https://huaan.zhiye.com/social", "enabled": True, "notes": None}]
        _sb, module, metrics, status = self._run(rows)[:4]
        self.assertNotIn("https://chinacdc.zhiye.com/campus", self.fetched)
        self.assertEqual(module, "harvest_beisen_routes")
        self.assertEqual({k: metrics[k] for k in ("harvested", "attempted", "probed", "browser_only",
                                                  "failed", "pending")},
                         {"harvested": 1, "attempted": 1, "probed": 2, "browser_only": 1, "failed": 0,
                          "pending": 2})
        self.assertEqual(status, "success")
        saved = json.loads(self._tmp_path.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"chinacdc.zhiye.com": {"cms": True}})

    def test_only_browser_only_left_is_an_idle_day_for_rule_a(self):
        """下一晚只剩华安：attempted=0 → 规则 A 判空队列，不再天天报零产出。"""
        rows = [{"source_url": "https://huaan.zhiye.com/social", "enabled": True, "notes": None}]
        _sb, _module, metrics, status = self._run(rows)[:4]
        self.assertEqual((metrics["attempted"], metrics["browser_only"], status), (0, 1, "success"))
        findings, _ = W.evaluate_zero_output(self._ledger(metrics, status), "2026-10-01", days=2)
        self.assertEqual(findings, [])

    def test_real_probe_failures_still_alarm(self):
        """真探失败（抛错）照旧记 failed，规则 A 照报——browser_only 不许变成吞失败的口子。"""
        rows = [dict(PendingHostsQueueTest.CAMPUS, notes="gap_funnel:pending")]
        _sb, _module, metrics, status = self._run(rows)[:4]
        self.assertEqual((metrics["attempted"], metrics["failed"], status), (1, 1, "failed"))
        findings, _ = W.evaluate_zero_output(self._ledger(metrics, status), "2026-10-01", days=2)
        self.assertEqual([f["subject"] for f in findings], ["harvest_beisen_routes"])

    def test_list_without_route_still_counts_as_failure(self):
        """新版租户列表抓到了、路由没探出来（下游 jd_url 拼不出 = 0 岗）是真问题，照旧计失败。"""
        rows = [{"source_url": "https://newver.zhiye.com/social", "enabled": True, "notes": None}]

        def fetch_without_route(_adapter, url):
            M.china_ats._BEISEN_ROUTE_CACHE["newver.zhiye.com"] = None
            return '{"_intercepted": [{"Data": [{"Id": "x"}], "Count": 1}]}'

        with mock.patch.object(M.db, "fetch_all_rows", return_value=rows), \
             mock.patch.object(M.china_ats.BeisenAdapter, "fetch", fetch_without_route), \
             mock.patch.object(M.ops_runs, "record_ops_run") as rec:
            M._run("fake-sb", datetime.now(timezone.utc))
        metrics, status = rec.call_args.args[2], rec.call_args.args[3]
        self.assertEqual((metrics["attempted"], metrics["failed"], metrics["browser_only"], status),
                         (1, 1, 0, "failed"))


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
