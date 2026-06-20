"""playwright_base 智能等待单测 —— 用假 page 模拟时间推进，不启动真实浏览器。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from adapters.playwright_base import PlaywrightAdapter


class _FakePage:
    """假 page：wait_for_timeout 推进 elapsed；到 capture_at 时往 collected 追加一次"响应"。"""

    def __init__(self, collected, capture_at_ms=None):
        self.elapsed = 0
        self._collected = collected
        self._capture_at = capture_at_ms
        self._captured = False

    def wait_for_timeout(self, ms):
        self.elapsed += ms
        if self._capture_at is not None and not self._captured and self.elapsed >= self._capture_at:
            self._collected.append({"job": "x"})  # 模拟拦截到一个岗位接口响应
            self._captured = True


class AwaitListCaptureTests(unittest.TestCase):
    def test_returns_early_after_capture_then_quiet(self):
        # 命中(300ms) + 静默窗口(1800ms) ≈ 2100ms，远小于 wait_ms=6000 → 提前返回省时间
        a = PlaywrightAdapter()
        collected = []
        page = _FakePage(collected, capture_at_ms=300)
        a._await_list_capture(page, collected, matchers=("listPosition",))
        self.assertLess(page.elapsed, a.wait_ms)
        self.assertGreaterEqual(page.elapsed, 300 + a.quiet_after_capture_ms)  # 绝不少等：命中+静默窗口

    def test_waits_full_when_never_captured(self):
        # 一直没拦到岗位接口 → 等满 wait_ms（与旧固定等待一致，绝不少等丢数据）
        a = PlaywrightAdapter()
        collected = []
        page = _FakePage(collected, capture_at_ms=None)
        a._await_list_capture(page, collected, matchers=("listPosition",))
        self.assertGreaterEqual(page.elapsed, a.wait_ms)

    def test_empty_matchers_uses_fixed_wait(self):
        # 拦截所有 JSON（matchers 为空）无法判定岗位接口 → 固定等满 wait_ms，不冒提前返回风险
        a = PlaywrightAdapter()
        collected = []
        page = _FakePage(collected, capture_at_ms=100)
        a._await_list_capture(page, collected, matchers=())
        self.assertEqual(page.elapsed, a.wait_ms)

    def test_burst_within_quiet_window_resets_timer(self):
        # 静默窗口内又来一波响应 → 重置静默、继续等，绝不在还在加载时提前返回（保住二次 XHR 的岗位）。
        # （间隔 > 静默窗口的极晚 XHR 是本方法的已知局限：靠 quiet_after_capture_ms=1800 默认窗口兜住
        #  正常的同页 XHR 突发；上限仍是 wait_ms，最坏退回旧固定等待行为。）
        a = PlaywrightAdapter()
        a.quiet_after_capture_ms = 900
        collected = []

        class _TwoBurstPage(_FakePage):
            def wait_for_timeout(self, ms):
                self.elapsed += ms
                if self.elapsed in (300, 900):  # 第二波(900)在第一波静默窗口(300+900=1200)内 → 应重置
                    self._collected.append({"job": "x"})

        page = _TwoBurstPage(collected)
        a._await_list_capture(page, collected, matchers=("x",))
        # 第二波(900)重置静默 → 至少等到 900+900=1800，证明没在 300+900=1200 处误提前返回
        self.assertGreaterEqual(page.elapsed, 1800)
        self.assertLess(page.elapsed, a.wait_ms)  # 且第二波后静默够久即返回，没死等到 wait_ms 上限


if __name__ == "__main__":
    unittest.main()
