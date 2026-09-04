import unittest

try:
    from backfill_grad_class import backfill
except ModuleNotFoundError:
    from crawler.backfill_grad_class import backfill


class FakeCursor:
    """只实现本脚本使用的游标接口，不连接真实数据库。"""

    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.selected_ids = []
        self.rowcount = 0
        self._selected = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        params = list(params or [])
        self.executed.append((" ".join(sql.split()), params))
        if sql.lstrip().lower().startswith("select"):
            candidates = [
                row for row in self.rows
                if row[4] == "active" and row[5] is None
            ]
            if len(params) == 2:
                candidates = [row for row in candidates if row[0] > params[0]]
            self._selected = [row[:4] for row in candidates[:params[-1]]]
            self.selected_ids.extend(row[0] for row in self._selected)
            self.rowcount = len(self._selected)
            return
        job_id = params[1]
        row = next(row for row in self.rows if row[0] == job_id)
        self.rowcount = int(row[5] is None)
        if self.rowcount:
            row[5] = params[0]

    def fetchall(self):
        return self._selected


class FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj


class TestBackfillGradClass(unittest.TestCase):
    def make_conn(self):
        return FakeConnection([
            ["001", "后端工程师", "校招", "2027届校园招聘", "active", None],
            ["002", "产品经理", "实习", "2026届实习生", "active", None],
            ["003", "运营", "校招", "欢迎投递", "active", None],
            ["004", "已有届别", "校招", "2027届校园招聘", "active", 2027],
            ["005", "已下线", "校招", "2027届校园招聘", "removed", None],
        ])

    def test_only_extracted_rows_are_written(self):
        conn = self.make_conn()
        stats = backfill(conn, apply=True, batch_size=2)

        self.assertEqual(stats["scanned"], 3)
        self.assertEqual(stats["extracted"], 2)
        self.assertEqual(stats["updated"], 2)
        self.assertEqual(dict(stats["distribution"]), {2027: 1, 2026: 1})
        writes = [sql for sql, _ in conn.cursor_obj.executed if sql.lower().startswith("update")]
        self.assertEqual(len(writes), 2)
        self.assertTrue(all("and grad_class is null" in sql.lower() for sql in writes))

    def test_no_signal_is_not_written(self):
        conn = FakeConnection([["001", "运营", "校招", "欢迎投递", "active", None]])
        stats = backfill(conn, apply=True)

        self.assertEqual(stats["scanned"], 1)
        self.assertEqual(stats["extracted"], 0)
        self.assertEqual(stats["updated"], 0)
        self.assertFalse(any(sql.lower().startswith("update") for sql, _ in conn.cursor_obj.executed))

    def test_limit_only_processes_first_n_candidates(self):
        conn = self.make_conn()
        stats = backfill(conn, apply=False, limit=2, batch_size=2000)

        self.assertEqual(stats["scanned"], 2)
        self.assertEqual(stats["extracted"], 2)
        selects = [params for sql, params in conn.cursor_obj.executed if sql.lower().startswith("select")]
        self.assertEqual(selects, [[2]])

    def test_existing_grad_class_and_non_active_rows_are_not_candidates(self):
        conn = self.make_conn()
        backfill(conn, apply=False)

        select_sql = next(sql for sql, _ in conn.cursor_obj.executed if sql.lower().startswith("select"))
        self.assertIn("status = 'active' and grad_class is null", select_sql.lower())
        self.assertNotIn("004", conn.cursor_obj.selected_ids)
        self.assertNotIn("005", conn.cursor_obj.selected_ids)


if __name__ == "__main__":
    unittest.main()
