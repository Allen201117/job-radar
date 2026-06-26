"""01 spec §6.1：源级失败自适应——should_trip_adapter 在样本足够且 miss 率超线时熔断该 adapter 本轮剩余。
样本不足一律不熔断（避免对天生难探的源误杀）。"""
import unittest

import enrich_backlog


class TripAdapterTest(unittest.TestCase):
    def test_below_min_sample_never_trips(self):
        # 样本不足（默认 min_sample=50）：即便全 miss 也不熔断
        self.assertFalse(enrich_backlog.should_trip_adapter(10, 10, min_sample=50, miss_ratio=0.7))
        self.assertFalse(enrich_backlog.should_trip_adapter(49, 49, min_sample=50, miss_ratio=0.7))

    def test_high_miss_after_sample_trips(self):
        # 达样本 + miss 率超线 → 熔断
        self.assertTrue(enrich_backlog.should_trip_adapter(50, 40, min_sample=50, miss_ratio=0.7))  # 0.8 >= 0.7
        self.assertTrue(enrich_backlog.should_trip_adapter(100, 90, min_sample=50, miss_ratio=0.7))

    def test_moderate_miss_does_not_trip(self):
        # 达样本但 miss 率未超线 → 不熔断（正常源 60% miss 不算限流）
        self.assertFalse(enrich_backlog.should_trip_adapter(100, 60, min_sample=50, miss_ratio=0.7))

    def test_boundary_ratio(self):
        # 恰好等于阈值 → 熔断（>=）
        self.assertTrue(enrich_backlog.should_trip_adapter(100, 70, min_sample=50, miss_ratio=0.7))
        self.assertFalse(enrich_backlog.should_trip_adapter(100, 69, min_sample=50, miss_ratio=0.7))

    def test_zero_checked_safe(self):
        self.assertFalse(enrich_backlog.should_trip_adapter(0, 0, min_sample=50, miss_ratio=0.7))


if __name__ == "__main__":
    unittest.main()
