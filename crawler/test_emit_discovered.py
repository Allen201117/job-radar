"""emit_discovered._confirm_httpx 单测：hotjob/wt 分支必须同时检查 verified，不能只看 count>0。

2026-09-18 修：此前该分支完全没读 hotjob_probe/wt_probe 的 verified 字段，只要 count>0 就写入
迁移候选——这条路径与 discover_domestic.hotjob_probe 的公司名核验漏洞是同一个根因的两个入口，
一并修，一并钉回归。
"""
import unittest
from unittest import mock

import emit_discovered as ed


class ConfirmHttpxVerifiedGateTest(unittest.TestCase):
    def test_hotjob_result_without_verified_is_dropped(self):
        fake = {"platform": "wecruit", "origin": "https://ampace.hotjob.cn",
                "suite_key": "SU1", "count": 40, "verified": False,
                "channels": [("social.html", 2, 40)],
                "note": "self-reported company mismatch: ['厦门新能安（XMC）']"}
        with mock.patch.object(ed.dd, "hotjob_probe", return_value=fake):
            r = ed._confirm_httpx({"company": "安脉时代", "cn": "安脉时代",
                                   "platform": "hotjob", "slug": "ampace"})
        self.assertIsNone(r)

    def test_hotjob_result_with_verified_still_passes(self):
        fake = {"platform": "wecruit", "origin": "https://ampace.hotjob.cn",
                "suite_key": "SU1", "count": 40, "verified": True,
                "channels": [("social.html", 2, 40)]}
        with mock.patch.object(ed.dd, "hotjob_probe", return_value=fake):
            rows = ed._confirm_httpx({"company": "新能安", "cn": "新能安",
                                      "platform": "hotjob", "slug": "ampace"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["adapter"], "hotjob")
        self.assertEqual(rows[0]["_valid"], 40)

    def test_wt_result_without_verified_is_dropped(self):
        fake = {"platform": "wt", "origin": "https://yili.hotjob.cn", "wt_brand": "yili",
                "count": 878, "verified": False, "portal_title": "伊利招聘官网",
                "note": "portal title mismatch: '伊利招聘官网'"}
        with mock.patch.object(ed.dd, "hotjob_probe", return_value=None), \
             mock.patch.object(ed.dd, "wt_probe", return_value=fake):
            r = ed._confirm_httpx({"company": "蒙牛", "cn": "蒙牛",
                                   "platform": "wt", "slug": "yili"})
        self.assertIsNone(r)

    def test_wt_result_with_verified_still_passes(self):
        fake = {"platform": "wt", "origin": "https://yili.hotjob.cn", "wt_brand": "yili",
                "count": 878, "verified": True, "portal_title": "伊利招聘官网"}
        with mock.patch.object(ed.dd, "hotjob_probe", return_value=None), \
             mock.patch.object(ed.dd, "wt_probe", return_value=fake):
            r = ed._confirm_httpx({"company": "伊利", "cn": "伊利",
                                   "platform": "wt", "slug": "yili"})
        self.assertIsNotNone(r)
        self.assertEqual(r["adapter"], "wt")
        self.assertEqual(r["url"], "https://yili.hotjob.cn/wt/yili/web/index")


if __name__ == "__main__":
    unittest.main()
