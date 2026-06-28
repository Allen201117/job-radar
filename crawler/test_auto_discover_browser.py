"""auto_discover_browser 浏览器确认逻辑单测（mock probe_one，不开真浏览器/不连库）。

红线：只入库**确认真产岗(valid>0)**的源；探不出岗的(新版异构/张冠李戴 tenant)丢弃；确认异常不炸；CONFIRM_CAP 封顶。
"""
import unittest

import auto_discover_browser as adb


def _c(company, url, adapter="beisen"):
    return {"company": company, "adapter": adapter, "url": url, "industry": "制造", "segment": "private"}


class ConfirmCandidatesTest(unittest.TestCase):
    def test_keeps_only_valid_producers(self):
        cands = [_c("A", "https://a.zhiye.com/social"), _c("B", "https://b.zhiye.com/social")]
        fn = lambda c: {"valid": 7, "china": 7} if c["company"] == "A" else {"valid": 0}
        out = adb.confirm_candidates(cands, cap=10, timeout=5, probe_fn=fn)
        self.assertEqual([r["company"] for r in out], ["A"])     # B 探不出岗 → 丢弃
        self.assertEqual(out[0]["_valid"], 7)

    def test_confirm_cap_limits_browser_work(self):
        cands = [_c(f"C{i}", f"https://c{i}.mokahr.com", "moka") for i in range(20)]
        seen = []
        def fn(c):
            seen.append(c["company"]); return {"valid": 3}
        out = adb.confirm_candidates(cands, cap=6, timeout=5, probe_fn=fn)
        self.assertEqual(len(seen), 6)        # 只确认前 6 家（浏览器慢，每日小批）
        self.assertEqual(len(out), 6)

    def test_probe_exception_skipped_not_fatal(self):
        cands = [_c("A", "https://a.zhiye.com/social"), _c("B", "https://b.zhiye.com/social")]
        def fn(c):
            if c["company"] == "A":
                raise RuntimeError("playwright timeout")
            return {"valid": 4}
        out = adb.confirm_candidates(cands, cap=10, timeout=5, probe_fn=fn)
        self.assertEqual([r["company"] for r in out], ["B"])     # A 异常跳过，不炸，B 照常确认

    def test_empty_or_none_result_dropped(self):
        cands = [_c("A", "https://a.zhiye.com/social")]
        out = adb.confirm_candidates(cands, cap=10, timeout=5, probe_fn=lambda c: None)
        self.assertEqual(out, [])              # probe 返回 None → 不入


if __name__ == "__main__":
    unittest.main()
