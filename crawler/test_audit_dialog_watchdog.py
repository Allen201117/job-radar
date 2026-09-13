"""覆盖 2026-09-13 死链审计 dialog/watchdog 修复（3 次 dead-link-audit 分片 150min 超时被取消）。

真因：北森 zhiye 站(如 ccccltd.zhiye.com)对已下架岗位用 window.alert('职位已下架') 提示，
本文件此前从未注册 page.on("dialog", ...)，无监听器时该对话框由 Node 驱动进程自己内部
自动 dismiss；一旦这次自动 dismiss 与我们紧接着发起的下一跳 goto() 并发，驱动内部会抛出
未捕获的 promise rejection 崩溃整个 Node 进程（Page.handleJavaScriptDialog: Not attached
to an active page）。驱动崩溃后 Python 侧可能长时间拿不到明确异常，陷入无输出的挂起。

这里覆盖两条红线：
1. 对话框处理器自身失败也绝不能外抛——它是防止驱动崩溃的最后一道防线，处理器自己再抛出
   等于没修。
2. 驱动/页面异常后处理单个岗位的逻辑必须落 unsure、绝不能判 dead（宁可漏判不可错杀，dead
   会被 --apply 置 expired、次日被 purge-expired 永久删除），并尝试重建浏览器兜底继续。
3. watchdog 心跳过期后必须触发强制退出动作；心跳保持新鲜时绝不能误触发。

全部用 mock，不打真网、不启真浏览器。
"""
import threading
import time
import unittest
from unittest.mock import MagicMock

import audit_dead_links


class DialogGuardTest(unittest.TestCase):
    def _install_and_get_handler(self):
        page = MagicMock()
        audit_dead_links._install_dialog_guard(page)
        self.assertEqual(page.on.call_count, 1)
        event, handler = page.on.call_args[0]
        self.assertEqual(event, "dialog")
        return handler

    def test_dismiss_called_for_alert(self):
        handler = self._install_and_get_handler()
        dialog = MagicMock(type="alert", message="职位已下架")
        handler(dialog)
        dialog.dismiss.assert_called_once()
        dialog.accept.assert_not_called()

    def test_accept_called_for_beforeunload(self):
        # beforeunload 的语义是"是否允许离开当前页"：dismiss=留在原地会顶住我们自己发起的
        # goto()/reload()，我们才是发起导航的一方，理应放行。
        handler = self._install_and_get_handler()
        dialog = MagicMock(type="beforeunload", message="")
        handler(dialog)
        dialog.accept.assert_called_once()
        dialog.dismiss.assert_not_called()

    def test_handler_never_raises_even_if_dismiss_fails(self):
        """核心断言：处理器是防驱动崩溃的最后一道防线，自己出错也不能外抛，否则又回到
        「未捕获异常拖垮整个驱动进程」的老路。"""
        handler = self._install_and_get_handler()
        dialog = MagicMock(type="alert", message="职位已下架")
        dialog.dismiss.side_effect = Exception("Not attached to an active page")
        try:
            handler(dialog)
        except Exception as e:  # pragma: no cover - 断言失败时才会走到这里
            self.fail(f"dialog handler 不应外抛异常，实际抛出 {type(e).__name__}: {e}")

    def test_handler_never_raises_even_if_accept_fails(self):
        handler = self._install_and_get_handler()
        dialog = MagicMock(type="beforeunload", message="")
        dialog.accept.side_effect = Exception("Target closed")
        try:
            handler(dialog)
        except Exception as e:  # pragma: no cover
            self.fail(f"dialog handler 不应外抛异常，实际抛出 {type(e).__name__}: {e}")


class ProcessJobTest(unittest.TestCase):
    @staticmethod
    def _make_hold(page):
        return {"b": MagicMock(), "pg": page}

    def test_crashed_driver_never_classified_dead_and_rebuild_attempted(self):
        """驱动/页面在 goto() 阶段崩溃 -> 必须落 unsure，绝不能是 dead；
        且要尝试 fresh() 重建，为下一岗恢复兜底。"""
        page = MagicMock()
        page.goto.side_effect = Exception("Not attached to an active page")
        hold = self._make_hold(page)
        fresh = MagicMock()
        job = {"id": "job-1", "title": "某岗位", "jd_url": "https://example.com/a"}

        h, verdict, why, previous_url = audit_dead_links._process_job(hold, fresh, job, None)

        self.assertEqual(verdict, "unsure")
        self.assertNotEqual(verdict, "dead")
        self.assertEqual(why, "Exception")
        self.assertIsNone(previous_url)
        fresh.assert_called_once()

    def test_fresh_failure_during_recovery_does_not_propagate(self):
        """连重建浏览器本身都失败时，也不能把异常甩出 _process_job——留给下一岗再试。"""
        page = MagicMock()
        page.goto.side_effect = Exception("driver dead")
        hold = self._make_hold(page)
        fresh = MagicMock(side_effect=Exception("relaunch also failed"))
        job = {"id": "job-2", "title": "某岗位", "jd_url": "https://example.com/b"}

        try:
            h, verdict, why, previous_url = audit_dead_links._process_job(hold, fresh, job, None)
        except Exception as e:  # pragma: no cover
            self.fail(f"_process_job 不应外抛异常，实际抛出 {type(e).__name__}: {e}")
        self.assertEqual(verdict, "unsure")
        fresh.assert_called_once()

    def test_happy_path_classifies_normally(self):
        """正常渲染成功时 verdict 走 classify() 的真实结果，不受本次修复影响。"""
        page = MagicMock()
        page.inner_text.return_value = "某岗位职责与要求……"
        hold = self._make_hold(page)
        fresh = MagicMock()
        job = {"id": "job-3", "title": "某岗位", "jd_url": "https://example.com/c"}

        h, verdict, why, previous_url = audit_dead_links._process_job(hold, fresh, job, None)

        self.assertEqual(verdict, "alive")
        self.assertEqual(previous_url, job["jd_url"])
        fresh.assert_not_called()


class WatchdogTest(unittest.TestCase):
    def test_fires_after_stale_heartbeat(self):
        heartbeat = [time.time() - 1000]  # 早已过期
        stop_event = threading.Event()
        fired = threading.Event()
        exit_calls = []

        def fake_exit(code):
            exit_calls.append(code)
            fired.set()

        t = audit_dead_links._start_watchdog(
            heartbeat, stop_event, timeout_s=0.05, poll_s=0.01, exit_fn=fake_exit)
        try:
            self.assertTrue(fired.wait(2), "watchdog 应在心跳过期后触发 exit_fn")
            self.assertEqual(exit_calls, [3])
        finally:
            stop_event.set()
            t.join(timeout=2)

    def test_does_not_fire_while_heartbeat_fresh(self):
        heartbeat = [time.time()]
        stop_event = threading.Event()
        exit_calls = []

        def fake_exit(code):
            exit_calls.append(code)

        t = audit_dead_links._start_watchdog(
            heartbeat, stop_event, timeout_s=5, poll_s=0.01, exit_fn=fake_exit)
        try:
            # 模拟主循环持续汇报心跳，watchdog 不应误触发。
            for _ in range(20):
                heartbeat[0] = time.time()
                time.sleep(0.02)
        finally:
            stop_event.set()
            t.join(timeout=2)
        self.assertEqual(exit_calls, [], "心跳持续新鲜时不应触发强制退出")


if __name__ == "__main__":
    unittest.main()
