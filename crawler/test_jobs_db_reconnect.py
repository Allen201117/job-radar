"""跨境链路自愈：建连重试 + 死连接重连。

背景（2026-07-26 从 CI 日志实测）：GitHub Actions(海外) → 腾讯云香港库这条链路会偶发中断，
连接层不自愈就放大成 workflow 失败——建连抖一下整片 exit 1；长跑任务连接被掐断后剩余几小时
全是 InterfaceError、一行写不进去。这里锁住重试/重连行为，不打真实网络。
"""
import unittest
from unittest import mock

import psycopg2

import jobs_db


class FakeConn:
    """够用的 psycopg2 连接替身：closed=0 表示活着（与 psycopg2 语义一致）。"""

    def __init__(self, closed=0):
        self.closed = closed
        self.autocommit = False
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        self.closed = 1


class ConnAliveTest(unittest.TestCase):
    def test_open_connection_is_alive(self):
        self.assertTrue(jobs_db.conn_alive(FakeConn(closed=0)))

    def test_closed_connection_is_not_alive(self):
        # psycopg2 在链路异常断开后把 closed 置 2（正是 InterfaceError 的来源）
        self.assertFalse(jobs_db.conn_alive(FakeConn(closed=2)))

    def test_none_is_not_alive(self):
        self.assertFalse(jobs_db.conn_alive(None))


class LiveConnTest(unittest.TestCase):
    def test_reuses_healthy_connection(self):
        conn = FakeConn(closed=0)
        maker = mock.Mock()
        self.assertIs(jobs_db.live_conn(conn, maker), conn)
        maker.assert_not_called()  # 活连接不该被重建（重建=白白多一次跨境握手）

    def test_reconnects_when_connection_dropped(self):
        dead, fresh = FakeConn(closed=2), FakeConn(closed=0)
        maker = mock.Mock(return_value=fresh)
        self.assertIs(jobs_db.live_conn(dead, maker), fresh)
        maker.assert_called_once()

    def test_creates_connection_when_none_cached(self):
        fresh = FakeConn(closed=0)
        maker = mock.Mock(return_value=fresh)
        self.assertIs(jobs_db.live_conn(None, maker), fresh)
        maker.assert_called_once()

    def test_falls_back_to_get_conn_without_maker(self):
        fresh = FakeConn(closed=0)
        with mock.patch.object(jobs_db, "get_conn", return_value=fresh) as get_conn:
            self.assertIs(jobs_db.live_conn(None), fresh)
        get_conn.assert_called_once()


class GetConnRetryTest(unittest.TestCase):
    """建连重试：只治网络类抖动，配置/认证错必须立刻抛（重试无意义还拖慢 CI）。"""

    def setUp(self):
        env = mock.patch.dict("os.environ", {"JOBS_DATABASE_URL": "postgresql://u:p@203.0.113.10:5432/jobs"})
        env.start()
        self.addCleanup(env.stop)
        for name, value in (("_load_env", None), ("_materialize_ssl_root_cert", "/tmp/ca.pem")):
            patcher = mock.patch.object(jobs_db, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        sleep = mock.patch.object(jobs_db.time, "sleep")   # 不真等，保持单测秒回
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def test_transient_failure_is_retried_then_succeeds(self):
        conn = FakeConn(closed=0)
        connect = mock.Mock(side_effect=[
            psycopg2.OperationalError("server closed the connection unexpectedly"),
            conn,
        ])
        with mock.patch.object(psycopg2, "connect", connect):
            self.assertIs(jobs_db.get_conn(), conn)
        self.assertEqual(connect.call_count, 2)
        self.assertTrue(conn.autocommit)
        self.sleep.assert_called_once_with(jobs_db._CONNECT_BACKOFF[0])

    def test_gives_up_after_attempt_budget_and_raises_last_error(self):
        boom = psycopg2.OperationalError("server closed the connection unexpectedly")
        connect = mock.Mock(side_effect=boom)
        with mock.patch.object(psycopg2, "connect", connect):
            with self.assertRaises(psycopg2.OperationalError):
                jobs_db.get_conn()
        self.assertEqual(connect.call_count, jobs_db._CONNECT_ATTEMPTS)

    def test_non_network_error_is_not_retried(self):
        connect = mock.Mock(side_effect=psycopg2.ProgrammingError("bad password"))
        with mock.patch.object(psycopg2, "connect", connect):
            with self.assertRaises(psycopg2.ProgrammingError):
                jobs_db.get_conn()
        connect.assert_called_once()
        self.sleep.assert_not_called()

    def test_keepalives_are_enabled_on_every_connection(self):
        """治本项：跨境 NAT/防火墙悄悄掐断空闲连接 → 内核层保活必须开着。"""
        connect = mock.Mock(return_value=FakeConn(closed=0))
        with mock.patch.object(psycopg2, "connect", connect):
            jobs_db.get_conn()
        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs["keepalives"], 1)
        self.assertGreater(kwargs["keepalives_idle"], 0)
        self.assertGreater(kwargs["connect_timeout"], 0)

    def test_backoff_table_covers_every_retry(self):
        self.assertEqual(len(jobs_db._CONNECT_BACKOFF), jobs_db._CONNECT_ATTEMPTS - 1)

    def test_retry_window_survives_a_two_minute_crossborder_blip(self):
        """跨境抖动是「一两分钟的窗口」，不是「几秒」。

        2026-08-08 实测：liveness-sweep / enrich-backlog 两次挂掉，都是 4 次重试在 ~19s 内烧光
        （对端直接 RST，每次建连秒失败，等待总和才是真正的窗口）。重试预算必须覆盖 ≥120s，
        否则一次网络抖动就能打掉整个 CI 分片。"""
        self.assertGreaterEqual(sum(jobs_db._CONNECT_BACKOFF), 120)

    def test_host_and_port_are_redacted_from_raised_error(self):
        """公开仓库红线：Actions 日志全网可读，建连报错不许带香港库 IP/端口。"""
        boom = psycopg2.OperationalError(
            'connection to server at "203.0.113.10", port 5432 failed: '
            "server closed the connection unexpectedly"
        )
        connect = mock.Mock(side_effect=boom)
        with mock.patch.object(psycopg2, "connect", connect):
            with self.assertRaises(psycopg2.OperationalError) as caught:
                jobs_db.get_conn()
        leaked = str(caught.exception)
        self.assertNotIn("203.0.113.10", leaked)
        self.assertNotIn("5432", leaked)
        self.assertIn("server closed the connection unexpectedly", leaked)  # 诊断信息要留住


if __name__ == "__main__":
    unittest.main()
