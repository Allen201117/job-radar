"""enrich.py 富化注册表 + enrich_backlog drain 的单测（纯函数 / mock，不打真网络）。

重点：
  1. 每个 httpx fetcher 把 jd_url 正确反推成 detail 端点（错了 = 静默灌错 summary，最危险）。
  2. ENRICH_REGISTRY 分发 + detail_class 分流。
  3. drain 死信：富化无果 → enrich_fail_count+1，不动 summary；有果 → 只写 summary。
"""
import unittest
from unittest import mock

import enrich
import enrich_backlog


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data


class HotjobDetailTest(unittest.TestCase):
    def test_reverses_jd_url_to_detail_post(self):
        row = {"jd_url": "https://wecruit.hotjob.cn/SU123/pb/posDetail.html?postId=P9&postType=campus",
               "title": "算法工程师"}
        src = {"source_url": "https://wecruit.hotjob.cn/SU123/pb/school.html", "adapter_name": "hotjob"}
        cap = {}

        def fake_post(url, data=None, headers=None, timeout=None):
            cap["url"] = url
            cap["data"] = data
            return _Resp({"data": {"workContent": "负责算法", "serviceCondition": "本科以上"}})

        with mock.patch.object(enrich.httpx, "post", fake_post):
            body = enrich.ENRICH_REGISTRY["hotjob"](row, src)
        self.assertIn("/wecruit/positionInfo/listPositionDetail/SU123", cap["url"])
        self.assertEqual(cap["data"]["postId"], "P9")
        self.assertEqual(cap["data"]["recruitType"], 1)  # campus → 1
        self.assertIn("负责算法", body)
        self.assertIn("本科以上", body)

    def test_society_maps_recruit_type_2(self):
        row = {"jd_url": "https://wecruit.hotjob.cn/SUx/pb/posDetail.html?postId=1&postType=society"}
        src = {"source_url": "https://wecruit.hotjob.cn/SUx/pb/social.html", "adapter_name": "hotjob"}
        cap = {}
        with mock.patch.object(enrich.httpx, "post",
                               lambda url, data=None, headers=None, timeout=None: cap.update(d=data) or _Resp({"data": {}})):
            enrich.ENRICH_REGISTRY["hotjob"](row, src)
        self.assertEqual(cap["d"]["recruitType"], 2)

    def test_missing_postid_returns_empty(self):
        row = {"jd_url": "https://wecruit.hotjob.cn/SUx/pb/posDetail.html"}
        src = {"source_url": "https://wecruit.hotjob.cn/SUx/pb/social.html", "adapter_name": "hotjob"}
        self.assertEqual(enrich.ENRICH_REGISTRY["hotjob"](row, src), "")


class WorkdayDetailTest(unittest.TestCase):
    def test_reverses_to_cxs_endpoint(self):
        row = {"jd_url": "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Beijing/Eng_R-1"}
        src = {"source_url": "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs", "adapter_name": "workday"}
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            return _Resp({"jobPostingInfo": {"jobDescription": "<p>do things</p>"}})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["workday"](row, src)
        self.assertEqual(cap["url"], "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/job/Beijing/Eng_R-1")
        self.assertIn("do things", body)

    def test_404_returns_empty(self):
        row = {"jd_url": "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/X/R-2"}
        src = {"source_url": "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs"}
        with mock.patch.object(enrich.httpx, "get",
                               lambda *a, **k: _Resp({}, status=404)):
            self.assertEqual(enrich.ENRICH_REGISTRY["workday"](row, src), "")


class RegistryTest(unittest.TestCase):
    def test_httpx_adapters_registered(self):
        for a in ("workday", "oracle", "eightfold", "smartrecruiters", "hotjob"):
            self.assertIn(a, enrich.ENRICH_REGISTRY)

    def test_detail_class(self):
        self.assertEqual(enrich.detail_class("hotjob"), "httpx")
        self.assertEqual(enrich.detail_class("workday"), "httpx")
        self.assertEqual(enrich.detail_class("beisen"), "browser")
        self.assertIsNone(enrich.detail_class("不存在的源"))

    def test_enrich_one_unknown_returns_empty(self):
        self.assertEqual(enrich.enrich_one("不存在", {"jd_url": "x"}, {}), "")


class _FakeSB:
    """记录 jobs.update 的 patch（按 id）。"""
    def __init__(self):
        self.updates = {}

    def table(self, name):
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def eq(self, col, val):
        self._eq = (col, val)
        return self

    def execute(self):
        if getattr(self, "_eq", (None,))[0] == "id":
            self.updates[self._eq[1]] = self._patch
        return self


class DrainRowTest(unittest.TestCase):
    def test_success_writes_summary_not_failcount(self):
        sb = _FakeSB()
        row = {"id": "j1", "source_id": "s", "title": "后端", "jd_url": "u", "job_type": None, "enrich_fail_count": 0}
        src = {"adapter_name": "hotjob", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: "负责后端服务的设计与开发，维护线上稳定性"):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "filled")
        patch = sb.updates["j1"]
        self.assertIn("summary", patch)
        self.assertNotIn("enrich_fail_count", patch)
        self.assertIn("enrich_checked_at", patch)

    def test_empty_body_increments_failcount(self):
        sb = _FakeSB()
        row = {"id": "j2", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 1}
        src = {"adapter_name": "hotjob", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: ""):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "miss")
        patch = sb.updates["j2"]
        self.assertEqual(patch["enrich_fail_count"], 2)  # 1 → 2
        self.assertNotIn("summary", patch)

    def test_fetch_exception_counts_as_miss(self):
        sb = _FakeSB()
        row = {"id": "j3", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 0}
        src = {"adapter_name": "hotjob", "source_url": "x"}

        def boom(a, r, s):
            raise RuntimeError("network down")

        with mock.patch.object(enrich_backlog.enrich, "enrich_one", boom):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "miss")
        self.assertEqual(sb.updates["j3"]["enrich_fail_count"], 1)

    def test_dry_run_does_not_write(self):
        sb = _FakeSB()
        row = {"id": "j4", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 0}
        src = {"adapter_name": "hotjob", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: "一段足够长的真实职位描述正文内容"):
            enrich_backlog.enrich_row(sb, row, src, dry_run=True)
        self.assertEqual(sb.updates, {})


if __name__ == "__main__":
    unittest.main()
