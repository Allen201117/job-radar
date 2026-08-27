"""BaseAdapter 预检缓存：全部 mock，不访问网络。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import base


class TestHeadPrecheckCache(unittest.TestCase):
    def setUp(self):
        base._HEAD_SKIP_CACHE.clear()

    def test_same_host_reuses_head_result_and_uses_five_second_timeout(self):
        response = mock.Mock(status_code=200)
        with mock.patch.object(base.httpx, "head", return_value=response) as head:
            self.assertIsNone(base.BaseAdapter().should_skip("https://jobs.example/a"))
            self.assertIsNone(base.BaseAdapter().should_skip("https://jobs.example/b"))

        self.assertEqual(head.call_count, 1)
        self.assertEqual(head.call_args.kwargs["timeout"], 5)

    def test_override_keeps_its_own_semantics(self):
        class CustomAdapter(base.BaseAdapter):
            def should_skip(self, source_url):
                return "custom"

        with mock.patch.object(base.httpx, "head") as head:
            self.assertEqual(CustomAdapter().should_skip("https://jobs.example/a"), "custom")
        head.assert_not_called()

    def test_timeout_fails_open_without_caching_host(self):
        with mock.patch.object(base.httpx, "head", side_effect=base.httpx.TimeoutException) as head:
            self.assertIsNone(base.BaseAdapter().should_skip("https://jobs.example/a"))
            self.assertIsNone(base.BaseAdapter().should_skip("https://jobs.example/b"))

        self.assertNotIn(("https", "jobs.example"), base._HEAD_SKIP_CACHE)
        self.assertEqual(head.call_count, 2)
