"""职业洞察过期下架巡检单测（纯日期逻辑 + sweep 编排，不打网络/DB）。"""
import unittest
from datetime import datetime, timezone

import insight_sweep as S


class TestIsExpired(unittest.TestCase):
    NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)

    def test_past_valid_until_is_expired(self):
        self.assertTrue(S.is_expired({"valid_until": "2026-03-31"}, self.NOW))

    def test_future_valid_until_not_expired(self):
        self.assertFalse(S.is_expired({"valid_until": "2026-12-31"}, self.NOW))

    def test_today_not_expired(self):
        self.assertFalse(S.is_expired({"valid_until": "2026-06-20"}, self.NOW))  # 含当天有效

    def test_no_valid_until_never_expires(self):
        self.assertFalse(S.is_expired({"valid_until": None}, self.NOW))
        self.assertFalse(S.is_expired({}, self.NOW))


class _FakeQ:
    def __init__(self, store):
        self.store = store
        self._upd = None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **k):
        return self

    def in_(self, col, vals):
        self.store.setdefault("retired_ids", []).extend(vals)
        return self

    def update(self, payload):
        self._upd = payload
        return self

    def execute(self):
        if self._upd is not None:
            self.store.setdefault("updates", []).append(self._upd)
            return type("R", (), {"data": []})()
        return type("R", (), {"data": self.store.get("_rows", [])})()


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeQ(self.store)


class TestSweep(unittest.TestCase):
    NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)

    def test_retires_only_expired(self):
        store = {"_rows": [
            {"id": "a", "valid_until": "2026-03-31"},  # 过期
            {"id": "b", "valid_until": "2026-12-31"},  # 新鲜
            {"id": "c", "valid_until": "2025-01-01"},  # 过期
        ]}
        n = S.sweep(_FakeSB(store), self.NOW)
        self.assertEqual(n, 2)
        self.assertEqual(sorted(store.get("retired_ids", [])), ["a", "c"])
        self.assertTrue(all(u == {"status": "retired"} for u in store.get("updates", [])))

    def test_nothing_expired_no_update(self):
        store = {"_rows": [{"id": "b", "valid_until": "2026-12-31"}]}
        n = S.sweep(_FakeSB(store), self.NOW)
        self.assertEqual(n, 0)
        self.assertEqual(store.get("retired_ids", []), [])
        self.assertEqual(store.get("updates", []), [])


if __name__ == "__main__":
    unittest.main()
