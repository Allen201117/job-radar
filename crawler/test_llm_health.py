"""LLM 运行健康信号单测：chat_content 记录成败 + llm_run_unhealthy 判据（不打网络）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import httpx
import insight_engine as E


class _FakeClient:
    """假 httpx client：按给定 status 返回响应；chat_content 传 client= 即可注入。"""

    def __init__(self, status, text='{"choices":[{"message":{"content":"ok"}}]}'):
        self.status = status
        self.text = text

    def post(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(self.status, request=httpx.Request("POST", url), text=self.text)

    def close(self):
        pass


class _SeqClient:
    """按序返回一串 status（模拟 429 重试后恢复）。"""

    def __init__(self, statuses, text='{"choices":[{"message":{"content":"ok"}}]}'):
        self.statuses = list(statuses)
        self.text = text
        self.calls = 0

    def post(self, url, json=None, headers=None, timeout=None):
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        return httpx.Response(status, request=httpx.Request("POST", url), text=self.text)

    def close(self):
        pass


class LlmRunHealthTest(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("SILICONFLOW_API_KEY", "test-key")  # 让 configured=True
        E.reset_llm_health()
        self._sleep = E.time.sleep
        E.time.sleep = lambda *a, **k: None  # 别在单测里真 sleep

    def tearDown(self):
        E.time.sleep = self._sleep

    def test_zero_calls_is_healthy(self):
        self.assertFalse(E.llm_run_unhealthy())

    def test_success_records_ok(self):
        out = E.chat_content([{"role": "user", "content": "x"}], client=_FakeClient(200))
        self.assertEqual(out, "ok")
        self.assertFalse(E.llm_run_unhealthy())
        self.assertEqual(E.llm_run_health()["ok"], 1)

    def test_403_marks_account_error_and_unhealthy(self):
        with self.assertRaises(httpx.HTTPStatusError):
            E.chat_content([{"role": "user", "content": "x"}], client=_FakeClient(403))
        self.assertTrue(E.llm_run_health()["account_error"])
        self.assertTrue(E.llm_run_unhealthy())

    def test_401_also_account_error(self):
        with self.assertRaises(httpx.HTTPStatusError):
            E.chat_content([{"role": "user", "content": "x"}], client=_FakeClient(401))
        self.assertTrue(E.llm_run_unhealthy())

    def test_500_is_fail_but_not_account_error(self):
        with self.assertRaises(httpx.HTTPStatusError):
            E.chat_content([{"role": "user", "content": "x"}], client=_FakeClient(500))
        h = E.llm_run_health()
        self.assertFalse(h["account_error"])
        # 有调用且全失败 → 仍判不健康（整轮空转）
        self.assertTrue(E.llm_run_unhealthy())

    def test_mixed_ok_and_fail_is_healthy(self):
        E.chat_content([{"role": "user", "content": "x"}], client=_FakeClient(200))
        with self.assertRaises(httpx.HTTPStatusError):
            E.chat_content([{"role": "user", "content": "x"}], client=_FakeClient(500))
        # 至少成一次 → 不算整体失败（部分失败是常态）
        self.assertFalse(E.llm_run_unhealthy())

    def test_429_then_success_recovers(self):
        # 429 限流 → 退避重试 → 第 3 次 200 成功；整轮判健康
        client = _SeqClient([429, 429, 200])
        out = E.chat_content([{"role": "user", "content": "x"}], client=client)
        self.assertEqual(out, "ok")
        self.assertEqual(client.calls, 3)
        self.assertFalse(E.llm_run_unhealthy())

    def test_429_persistent_raises_and_unhealthy(self):
        # 一直 429 → 重试用尽后抛 + 判不健康（本轮空转）
        with self.assertRaises(httpx.HTTPStatusError):
            E.chat_content([{"role": "user", "content": "x"}], client=_SeqClient([429]))
        self.assertTrue(E.llm_run_unhealthy())

    def test_reset(self):
        with self.assertRaises(httpx.HTTPStatusError):
            E.chat_content([{"role": "user", "content": "x"}], client=_FakeClient(403))
        self.assertTrue(E.llm_run_unhealthy())
        E.reset_llm_health()
        self.assertFalse(E.llm_run_unhealthy())


if __name__ == "__main__":
    unittest.main()
