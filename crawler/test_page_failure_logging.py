"""「后续页抓取失败，保留已抓」日志必须带上异常类名 + 首行信息（不打真实网络）。

为什么：fetch_page / 翻页循环通常把「请求 + 解析」写在同一个 try 里，只记「第 N 页抓取失败」
分不清是网络瞬断（ReadTimeout / 5xx）还是我们的解析器炸了（AttributeError…）。
2026-10-04 国家能源集团 2604→794 的 CI 日志只有一句「kinds=1,schType=2: 第 61 页抓取失败」，
靠整源本地重抓、新旧代码逐字段对拍才证明是网络瞬断、不是 selectolax 迁移弄坏了解析。
"""
import ast
import json
import logging
import pathlib
import time
import unittest
from unittest import mock

import httpx

from adapters.amazon import AmazonAdapter
from adapters.base import exc_brief
from adapters import china_ats
from adapters.china_ats import _post_page_with_retry
from adapters.microsoft import MicrosoftAdapter

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


if __name__ == "__main__":
    unittest.main()
