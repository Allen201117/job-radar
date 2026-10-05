"""「后续页抓取失败，保留已抓」日志必须带上异常类名 + 首行信息（不打真实网络）。

为什么：fetch_page / 翻页循环通常把「请求 + 解析」写在同一个 try 里，只记「第 N 页抓取失败」
分不清是网络瞬断（ReadTimeout / 5xx）还是我们的解析器炸了（AttributeError…）。
2026-10-04 国家能源集团 2604→794 的 CI 日志只有一句「kinds=1,schType=2: 第 61 页抓取失败」，
靠整源本地重抓、新旧代码逐字段对拍才证明是网络瞬断、不是 selectolax 迁移弄坏了解析。
"""
import ast
import contextlib
import io
import json
import logging
import pathlib
import re
import time
import unittest
from unittest import mock

import httpx

from adapters.amazon import AmazonAdapter
from adapters.apple import AppleAdapter
from adapters.base import RepetitionBrake, exc_brief
from adapters import bytedance, china_ats
from adapters.bytedance import BytedanceAdapter, BytedancePage, collect_bytedance_track
from adapters.china_ats import _post_page_with_retry
from adapters.feishu import NioAdapter
from adapters.microsoft import MicrosoftAdapter
from test_apple_adapter import ApplePaginationTest

_ADAPTERS_DIR = pathlib.Path(__file__).resolve().parent / "adapters"


def _status_error(url: str, status: int = 502) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", url)
    response = httpx.Response(status, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("raise_for_status 应该抛错")


class ExcBriefTests(unittest.TestCase):
    def test_class_name_and_message(self):
        brief = exc_brief(httpx.ReadTimeout("The read operation timed out"))
        self.assertEqual(brief, "ReadTimeout: The read operation timed out")

    def test_parser_exception_is_distinguishable(self):
        try:
            None.text  # noqa: B018 —— 复刻解析器拿到 None 节点
        except AttributeError as exc:
            brief = exc_brief(exc)
        self.assertTrue(brief.startswith("AttributeError: "), brief)
        self.assertIn("text", brief)

    def test_empty_message_keeps_class_name(self):
        self.assertEqual(exc_brief(httpx.ConnectTimeout("")), "ConnectTimeout")

    def test_status_error_keeps_status_but_drops_query_and_mdn_line(self):
        exc = _status_error("https://campus.example.com/api/list?_csrf=SECRET123&page=2")
        brief = exc_brief(exc)
        self.assertTrue(brief.startswith("HTTPStatusError: "), brief)
        self.assertIn("502", brief)
        self.assertIn("https://campus.example.com/api/list", brief)
        self.assertNotIn("SECRET123", brief)       # 查询串里常有 _csrf / 签名
        self.assertNotIn("_csrf", brief)
        self.assertNotIn("mozilla", brief)         # httpx 第二行固定的 MDN 链接不要
        self.assertNotIn("\n", brief)

    def test_userinfo_redacted(self):
        brief = exc_brief(RuntimeError("connect to https://bot:p4ssw0rd@api.example.com/x failed"))
        self.assertNotIn("p4ssw0rd", brief)
        self.assertNotIn("bot:", brief)
        self.assertIn("api.example.com/x", brief)

    def test_hash_route_query_redacted(self):
        # byd / kuaishou / moka 是 hash 路由：查询串在 # 后面，也得抹。
        brief = exc_brief(RuntimeError("net::ERR_TIMED_OUT at https://h.example.com/#/jobs?token=T0K3N&id=9"))
        self.assertNotIn("T0K3N", brief)
        self.assertIn("https://h.example.com/#/jobs?…", brief)
        # 没有查询串的 hash 路由原样保留（岗位 id 是定位问题要用的）
        self.assertIn("#/job-info/31711", exc_brief(RuntimeError("at https://h.example.com/#/job-info/31711")))

    def test_truncated(self):
        brief = exc_brief(ValueError("x" * 5000))
        self.assertLessEqual(len(brief), 200)
        self.assertTrue(brief.startswith("ValueError: xxx"))
        self.assertLessEqual(len(exc_brief(ValueError("x" * 5000), limit=50)), 50)

    def test_huge_single_line_stays_fast(self):
        # 异常里夹整页压缩 HTML 时，URL 正则对「a.a.a.…」是平方级：不限长 8 万字符实测 12s、
        # 1MB 要几十分钟——而它跑在 except 分支里，会把「尽力而为」拖成整个 CI job 卡死。
        blob = "a." * 20_000   # 4 万字符：不限长约 3s，限长后约 3ms
        started = time.perf_counter()
        brief = exc_brief(RuntimeError(blob))
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertLessEqual(len(brief), 200)

    def test_broken_str_never_raises(self):
        # 它在 except 分支里被调用，自己再抛就把「保留已抓」变成整源失败。
        class BrokenStr(Exception):
            def __str__(self):
                raise RuntimeError("no str")

        self.assertEqual(exc_brief(BrokenStr()), "BrokenStr")


class AdapterLogContractTests(unittest.TestCase):
    """凡是「保留已抓 N 条」的告警（= 吞掉了一个异常），参数里必须有 exc_brief(...)。"""

    def test_every_partial_keep_warning_carries_exc_brief(self):
        offenders, seen = [], 0
        for path in sorted(_ADAPTERS_DIR.glob("*.py")):
            src = path.read_text(encoding="utf-8")
            if "保留已抓" not in src:
                continue
            tree = ast.parse(src, filename=str(path))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "warning" and node.args):
                    continue
                fmt = node.args[0]
                if not (isinstance(fmt, ast.Constant) and isinstance(fmt.value, str)
                        and "保留已抓" in fmt.value):
                    continue
                seen += 1
                has_brief = any(
                    isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                    and arg.func.id == "exc_brief"
                    for arg in node.args[1:]
                )
                if not has_brief:
                    offenders.append(f"{path.name}:{node.lineno}")
        # 下限防假绿：改造时（2026-10-05）共 22 处，扫不到说明扫描本身坏了。
        self.assertGreaterEqual(seen, 22)
        self.assertEqual(offenders, [], "这些告警吞了异常却没记类名/信息")


class AmazonLaterPageFailureLogTests(unittest.TestCase):
    """真走一遍 adapter 的翻页循环：第 2 页超时 → 保留第 1 页，告警里点名 ReadTimeout。"""

    def test_later_page_timeout_logged_with_class_name(self):
        page1 = mock.Mock()
        page1.raise_for_status.return_value = None
        page1.json.return_value = {
            "hits": 250,
            "jobs": [{"job_path": f"/jobs/{i}", "title": f"t{i}"} for i in range(100)],
        }
        calls = []

        def fake_get(url, **_kwargs):
            calls.append(url)
            if len(calls) == 1:
                return page1
            raise httpx.ReadTimeout("The read operation timed out")

        adapter = AmazonAdapter()
        with mock.patch("adapters.amazon.httpx.get", side_effect=fake_get):
            with self.assertLogs("adapters.amazon", level="WARNING") as cm:
                payload = adapter.fetch("https://www.amazon.jobs/en/search.json?normalized_country_code[]=CHN")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(json.loads(payload)["jobs"]), 100)   # 第 1 页保留
        self.assertFalse(adapter.fetch_complete)
        msg = "\n".join(cm.output)
        self.assertIn("第 2 页抓取失败，保留已抓 100 条", msg)
        self.assertIn("ReadTimeout: The read operation timed out", msg)


class MicrosoftLaterPageFailureLogTests(unittest.TestCase):
    """此前这里 `except Exception: break` 连一行日志都没有。"""

    def test_later_page_failure_logged(self):
        def fake_get(url, params=None, **_kwargs):
            if params["start"] == 0:
                resp = mock.Mock()
                resp.raise_for_status.return_value = None
                resp.json.return_value = {"data": {"positions": [
                    {"id": f"{params['location']}-{i}", "name": f"t{i}"} for i in range(10)
                ]}}
                return resp
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

        adapter = MicrosoftAdapter()
        with mock.patch("adapters.microsoft.httpx.get", side_effect=fake_get):
            with self.assertLogs("adapters.microsoft", level="WARNING") as cm:
                adapter.fetch("https://apply.careers.microsoft.com/careers")
        self.assertFalse(adapter.fetch_complete)
        self.assertTrue(any("第 2 页抓取失败，保留已抓" in m and "ConnectError: [Errno 11001]" in m
                            for m in cm.output), cm.output)


class BeisenRetryHelperLogTests(unittest.TestCase):
    """北森 httpx 翻页：重试用尽返回 None、调用方直接停翻；用尽时必须留一行带类名的告警。"""

    def test_exhausted_retries_log_last_exception(self):
        cli = mock.Mock()
        cli.post.side_effect = httpx.ReadTimeout("The read operation timed out")
        with mock.patch.object(china_ats, "_PAGE_BACKOFF_SECONDS", 0):
            with self.assertLogs("adapters.china_ats", level="WARNING") as cm:
                payload, ep = _post_page_with_retry(cli, ["https://x.zhiye.com/api/Jobad/GetJobAdPageList"],
                                                    None, {"PageIndex": 3}, attempts=2)
        self.assertIsNone(payload)
        msg = "\n".join(cm.output)
        self.assertIn("PageIndex=3", msg)
        self.assertIn("ReadTimeout: The read operation timed out", msg)

    def test_payload_without_data_is_reported_not_stale_exception(self):
        # 限流体不抛异常、只是没有 Data 列表；先抛过的旧异常不能被当成停翻的原因。
        throttled = mock.Mock()
        throttled.json.return_value = {"Code": 429, "Message": "too many requests"}
        cli = mock.Mock()
        cli.post.side_effect = [httpx.ReadTimeout("old timeout"), throttled]
        with mock.patch.object(china_ats, "_PAGE_BACKOFF_SECONDS", 0):
            with self.assertLogs("adapters.china_ats", level="WARNING") as cm:
                payload, _ = _post_page_with_retry(cli, ["https://x/api/JobAd/GetJobAdPageList"],
                                                   None, {"PageIndex": 7}, attempts=2)
        self.assertIsNone(payload)
        msg = "\n".join(cm.output)
        self.assertIn("没有 Data 列表", msg)
        self.assertIn("429", msg)
        self.assertNotIn("old timeout", msg)

    def test_success_after_failed_endpoint_logs_nothing(self):
        # 端点大小写两试：错的那个抛错、对的那个成功 → 正常返回，不该告警。
        good = mock.Mock()
        good.json.return_value = {"Data": [], "Count": 0}

        def post(ep, **_kwargs):
            if "Jobad" in ep:
                raise ValueError("Expecting value: line 1 column 1 (char 0)")
            return good

        cli = mock.Mock()
        cli.post.side_effect = post
        with self.assertNoLogs("adapters.china_ats", level="WARNING"):
            payload, ep = _post_page_with_retry(
                cli, ["https://x/api/Jobad/GetJobAdPageList", "https://x/api/JobAd/GetJobAdPageList"],
                None, {"PageIndex": 0})
        self.assertEqual(payload, {"Data": [], "Count": 0})
        self.assertIn("JobAd", ep)


class BytedancePageErrorTests(unittest.TestCase):
    """posts 接口非 405 的 4xx/5xx：httpx 报错第二行是 MDN 链接，原样塞进告警会拆成两行。"""

    def test_status_error_recorded_as_one_line_with_class_name(self):
        adapter = BytedanceAdapter()
        adapter.request_interval_s = 0
        err = _status_error(bytedance._POSTS_URL, 503)
        self.assertIn("\n", str(err))   # 负对照：原文确实是两行

        resp = mock.Mock(status_code=503)
        resp.raise_for_status.side_effect = err
        client = mock.Mock()
        client.post.return_value = resp
        page = adapter._request_page(client, {"offset": 0, "limit": 1})

        self.assertFalse(page.ok)
        self.assertTrue(page.error.startswith("HTTPStatusError: "), page.error)
        self.assertIn("503", page.error)
        self.assertNotIn("\n", page.error)
        self.assertNotIn("mozilla", page.error)

    def test_skipped_leaf_page_warning_redacts_query(self):
        # fetch_page 是注入的，异常可以来自任何 URL —— 告警里只留类名 + 脱敏后的首行。
        def fetch_page(rid, offset, limit, category_id=None, city_code=None):
            if limit == 1:
                return BytedancePage(count=3, jobs=[{"id": "r"}])
            if offset == 0:
                return BytedancePage(count=3, jobs=[{"id": "1"}, {"id": "2"}])
            raise _status_error("https://jobs.example.com/api/posts?msToken=SECRET42&offset=2", 429)

        with self.assertLogs("adapters.bytedance", level="WARNING") as cm:
            result = collect_bytedance_track(fetch_page, "1", page_limit=2)
        self.assertFalse(result.complete)
        self.assertEqual(result.skipped_pages, 1)
        msg = "\n".join(cm.output)
        self.assertIn("HTTPStatusError: Client error '429", msg)
        self.assertIn("https://jobs.example.com/api/posts?…", msg)
        self.assertNotIn("SECRET42", msg)
        self.assertNotIn("msToken", msg)
        self.assertNotIn("mozilla", msg)


def _playwright_error(message: str) -> Exception:
    # 同名替身：真 Playwright 的 TimeoutError 首行是「Page.goto: …」，后面跟几十行 call log。
    return type("TimeoutError", (Exception,), {})(message)


class MokaAliasPortalLogTests(unittest.TestCase):
    """别名门户打不开时的告警：只留首行（Playwright call log 不进日志），URL 查询串脱敏。"""

    def test_unreadable_alias_portal_logs_one_redacted_line(self):
        adapter = china_ats.MokaAdapter()
        err = _playwright_error(
            "Page.goto: net::ERR_ABORTED at https://app.mokahr.com/campus_apply/t/999?ticket=SECRET7#/jobs\n"
            "Call log:\n"
            '  - navigating to "https://app.mokahr.com/campus_apply/t/999?ticket=SECRET7#/jobs"\n')
        with mock.patch.object(adapter, "_current_campus_portal_id", return_value="999"), \
                mock.patch.object(adapter, "_open_route", side_effect=err):
            with self.assertLogs("adapters.china_ats", level="WARNING") as cm:
                adapter._raise_if_campus_portal_superseded(
                    object(), "https://app.mokahr.com/campus-recruitment/t/123#/jobs")
        self.assertEqual(len(cm.output), len(adapter._routes))   # 每个路由一行，看不清就不下结论
        msg = "\n".join(cm.output)
        self.assertIn("not readable: TimeoutError: Page.goto: net::ERR_ABORTED", msg)
        self.assertNotIn("SECRET7", msg)
        self.assertNotIn("Call log", msg)


class MokaFirstLineTests(unittest.TestCase):
    """_first_line = exc_brief + 点名挡住按钮的那一行（test_moka_coverage 钉着后者）。"""

    def test_same_output_as_before_for_click_timeout(self):
        exc = Exception("Timeout 2500ms exceeded.\n"
                        "  - <div class=\"sd-Modal-drawer\">…</div> intercepts pointer events\n"
                        "  - retrying")
        self.assertEqual(
            china_ats._first_line(exc),
            "Exception: Timeout 2500ms exceeded. | "
            "- <div class=\"sd-Modal-drawer\">…</div> intercepts pointer events")

    def test_without_intercept_line_is_exc_brief(self):
        exc = _playwright_error("Locator.click: Timeout 2500ms exceeded.\nCall log:\n  - waiting for locator")
        self.assertEqual(china_ats._first_line(exc), "TimeoutError: Locator.click: Timeout 2500ms exceeded.")

    def test_urls_redacted_in_both_lines(self):
        exc = Exception("Timeout at https://a.mokahr.com/x?sig=SECRET1\n"
                        "  - <a href=\"https://a.mokahr.com/y?sig=SECRET2\"> intercepts pointer events")
        line = china_ats._first_line(exc)
        self.assertIn("intercepts pointer events", line)
        self.assertNotIn("SECRET1", line)
        self.assertNotIn("SECRET2", line)

    def test_limit_and_broken_str(self):
        exc = Exception("x" * 300 + "\n - <div> intercepts pointer events")
        self.assertEqual(len(china_ats._first_line(exc)), 240)

        class BrokenStr(Exception):
            def __str__(self):
                raise RuntimeError("no str")

        self.assertEqual(china_ats._first_line(BrokenStr()), "BrokenStr")


class FeishuReplayBrakeLogTests(unittest.TestCase):
    """浏览器重放的 posts URL 是站点 JS 发的，查询串带 _signature；刹车日志只许出现 host+path。"""

    def test_brake_log_drops_signature(self):
        url = ("https://nio.jobs.feishu.cn/api/v1/search/job/posts"
               "?keyword=&limit=10&offset=0&_signature=SIGSECRET")
        calls = []

        def post(u, data=None, headers=None):
            calls.append(u)
            offset = json.loads(data)["offset"]
            resp = mock.Mock()
            resp.json.return_value = {"data": {"count": 100_000, "job_post_list": [
                {"id": f"{offset}-{i}", "title": "门店店员"} for i in range(50)]}}
            return resp

        page = mock.Mock()
        page.request.post.side_effect = post
        adapter = NioAdapter()
        with mock.patch("adapters.feishu.RepetitionBrake", lambda: RepetitionBrake(stall_rows=100)):
            with self.assertLogs("adapters.feishu", level="INFO") as cm:
                rows, total = adapter._replay_paginated(page, url, {})
        self.assertEqual(adapter.coverage_stop_reason, "repetition_brake")
        self.assertTrue(all(u == url for u in calls))   # 重放本身照旧用带签名的完整 URL
        msg = "\n".join(cm.output)
        self.assertIn("重复度刹车", msg)
        self.assertIn("url=https://nio.jobs.feishu.cn/api/v1/search/job/posts?…", msg)
        self.assertNotIn("SIGSECRET", msg)
        self.assertNotIn("_signature", msg)


class AppleRetryPrintTests(unittest.TestCase):
    """中途页重试的 print：HTTPStatusError 原文第二行是 MDN 链接，原样打会拆成两行。"""

    def test_retry_print_is_one_redacted_line_with_class_name(self):
        fake_get, _ = ApplePaginationTest()._fake_get(55)
        failed = []

        def flaky_get(url, **kw):
            if re.search(r"[?&]page=2\b", url) and not failed:   # 第 2 页第一次 503，重试成功
                failed.append(url)
                raise _status_error(url + "&token=SECRET9", 503)
            return fake_get(url, **kw)

        adapter = AppleAdapter()
        adapter.PAGE_RETRY_BACKOFF = (0, 0, 0)
        out = io.StringIO()
        with mock.patch("adapters.apple.httpx.get", side_effect=flaky_get), contextlib.redirect_stdout(out):
            jobs = adapter.parse(adapter.fetch("https://jobs.apple.com/en-us/search"))
        self.assertEqual(len(jobs), 55)
        self.assertEqual(len(failed), 1)
        printed = out.getvalue()
        lines = [line for line in printed.splitlines() if "apple page 2 failed" in line]
        self.assertEqual(len(lines), 1, printed)
        self.assertIn("(HTTPStatusError: Server error '503", lines[0])
        self.assertTrue(lines[0].endswith("; retry"), lines[0])
        self.assertNotIn("SECRET9", printed)
        self.assertNotIn("mozilla", printed)


if __name__ == "__main__":
    unittest.main()
