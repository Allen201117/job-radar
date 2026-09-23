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


class BrowserLedgerMetricsTest(unittest.TestCase):
    """台账要能回答「为什么 0」：各步淘汰计数必须写进 ops_runs，不靠翻 CI 日志。"""

    def test_main_records_elimination_counts(self):
        from unittest import mock
        curated = [{"company": "新料甲", "cn": "新料甲", "slugs": ["a"], "_priority": True, "_llm": True},
                   {"company": "静态乙", "cn": "静态乙", "slugs": ["b"]}]
        hits = [{"platform": "beisen", "verified": True, "company": "新料甲"},
                {"platform": "moka", "verified": False, "company": "静态乙"}]
        raw = [_c("新料甲", "https://a.zhiye.com/social"), _c("新料甲", "https://a.zhiye.com/campus")]
        ledger = mock.Mock(return_value=True)
        with mock.patch.object(adb.db, "get_supabase", return_value=object()), \
             mock.patch.object(adb.ad, "load_user_wanted_companies", return_value=set()), \
             mock.patch.object(adb.ad, "existing_source_keys",
                               return_value=(set(), {"https://a.zhiye.com/campus"})), \
             mock.patch.object(adb.ad, "load_targets", return_value=curated), \
             mock.patch.object(adb.must_apply, "by_industry", return_value={}), \
             mock.patch.object(adb.ad, "load_campus_gap_source_rows", return_value=[]), \
             mock.patch.object(adb.dd, "sweep", return_value=hits), \
             mock.patch.object(adb.dd, "to_beisen_candidates", return_value=raw), \
             mock.patch.object(adb.dd, "to_moka_candidates", return_value=[]), \
             mock.patch.object(adb, "confirm_candidates", return_value=[]), \
             mock.patch.object(adb.ops_runs, "record_ops_run", ledger), \
             mock.patch.dict("os.environ", {"AUTO_DISCOVER_APPLY": ""}):
            adb.main()
        _sb, module, m = ledger.call_args.args[:3]
        self.assertEqual(module, "auto_discover_browser")
        self.assertEqual(m["llm_candidates"], 1)
        self.assertEqual(m["tenant_hits"], 2)
        self.assertEqual(m["tenant_unverified"], 1)
        self.assertEqual(m["deduped"], 1)            # campus URL 已在库
        self.assertEqual(m["confirm_attempted"], 1)
        self.assertEqual(m["confirmed_zero"], 1)
        self.assertEqual(m["produced"], 0)

    def test_feishu_hotjob_hits_inserted_without_browser_confirm(self):
        """2026-09-23 httpx 道并入本道：同一批目标顺手探飞书/hotjob；这两家平台探活时已拿到真实岗位数
        + 核验过公司名，直接入库、不占浏览器确认名额；未过核验的照样丢。"""
        from unittest import mock
        curated = [{"company": "新料甲", "cn": "新料甲", "slugs": ["a"], "_priority": True, "_llm": True}]
        hits = [{"platform": "feishu", "verified": True, "count": 7, "company": "新料甲", "industry": "x",
                 "url": "https://a.jobs.feishu.cn/index/position"},
                {"platform": "feishu", "verified": False, "count": 9, "company": "新料乙", "industry": "x",
                 "url": "https://b.jobs.feishu.cn/index/position"}]
        sweep = mock.Mock(return_value=hits)
        inserted = []
        confirm = mock.Mock(return_value=[])
        with mock.patch.object(adb.db, "get_supabase", return_value=object()), \
             mock.patch.object(adb.ad, "load_user_wanted_companies", return_value=set()), \
             mock.patch.object(adb.ad, "existing_source_keys", return_value=(set(), set())), \
             mock.patch.object(adb.ad, "load_targets", return_value=curated), \
             mock.patch.object(adb.must_apply, "by_industry", return_value={}), \
             mock.patch.object(adb.ad, "load_campus_gap_source_rows", return_value=[]), \
             mock.patch.object(adb.dd, "sweep", sweep), \
             mock.patch.object(adb, "confirm_candidates", confirm), \
             mock.patch.object(adb.ad, "insert_source", lambda sb, row: inserted.append(row)), \
             mock.patch.object(adb.ops_runs, "record_ops_run", mock.Mock(return_value=True)) as ledger, \
             mock.patch.dict("os.environ", {"AUTO_DISCOVER_APPLY": "true"}):
            adb.main()
        self.assertEqual(sweep.call_args.args[1], {"beisen", "moka", "feishu", "hotjob"})
        self.assertEqual([r["url"] for r in inserted], ["https://a.jobs.feishu.cn/index/position"])
        self.assertEqual(inserted[0]["adapter"], "feishu")
        for call in confirm.call_args_list:   # 飞书/hotjob 候选绝不进浏览器确认
            self.assertFalse(any("feishu" in c["url"] for c in call.args[0]))
        m = ledger.call_args.args[2]
        self.assertEqual((m["httpx_passed"], m["produced"], m["tenant_unverified"]), (1, 1, 1))
