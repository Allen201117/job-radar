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

    def test_closed_signal_raises_jobclosed(self):
        # 源站已撤岗：HTTP 200 + {"state":"1017","msg":"...已经关闭..."}，无 data/workContent。
        # 必须区别于「无正文」(返回"")——这是 expired 信号，不是死信。
        row = {"jd_url": "https://wecruit.hotjob.cn/SU1/pb/posDetail.html?postId=P1&postType=society"}
        src = {"source_url": "https://wecruit.hotjob.cn/SU1/pb/social.html", "adapter_name": "hotjob"}
        closed = {"msg": "该职位招聘已经关闭，请查看其他职位", "state": "1017", "type": "warning"}
        with mock.patch.object(enrich.httpx, "post",
                               lambda url, data=None, headers=None, timeout=None: _Resp(closed)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["hotjob"](row, src)


class WtDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://feihe.hotjob.cn/wt/feihe/mobweb/position/detail"
                      "?brandCode=1&safe=Y&recruitType=1&postIdsAry=153001"}
    _SRC = {"source_url": "https://feihe.hotjob.cn/wt/feihe/web/index", "adapter_name": "wt"}

    def test_reverses_to_json_detail_and_extracts_summary(self):
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            cap["params"] = params
            return _Resp({"req_state": 9200,
                          "postInfo": {"workContent": "负责生产实训", "serviceCondition": "本科以上学历"}})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["wt"](self._ROW, self._SRC)
        self.assertEqual(cap["url"], "https://feihe.hotjob.cn/wt/feihe/web/json/position/detail")
        self.assertEqual(cap["params"]["postId"], "153001")
        self.assertEqual(str(cap["params"]["recruitType"]), "1")
        self.assertIn("负责生产实训", body)
        self.assertIn("本科以上学历", body)

    def test_closed_req_state_9501_raises_jobclosed(self):
        # 源站撤岗：HTTP 200 + {"req_state":9501,"req_msg":"…招聘已经关闭…"}，无 postInfo。
        closed = {"req_state": 9501, "req_msg": "该职位招聘已经关闭，请关注其他职位，谢谢!"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp(closed)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["wt"](self._ROW, self._SRC)

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["wt"](self._ROW, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=503)):
            self.assertEqual(enrich.ENRICH_REGISTRY["wt"](self._ROW, self._SRC), "")

    def test_missing_postid_returns_empty(self):
        row = {"jd_url": "https://feihe.hotjob.cn/wt/feihe/mobweb/position/detail?recruitType=1"}
        self.assertEqual(enrich.ENRICH_REGISTRY["wt"](row, self._SRC), "")


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

    def test_404_raises_jobclosed(self):
        # Workday cxs：岗位下架后 /job/{path} 返回 404 = 撤岗信号 → expired（≠ 无正文）。
        row = {"jd_url": "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/X/R-2"}
        src = {"source_url": "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["workday"](row, src)

    def test_transient_5xx_returns_empty_not_closed(self):
        # 5xx/限流 = 瞬时错误，必须走 miss 重试，绝不能 expired（否则误杀活岗）。
        row = {"jd_url": "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/X/R-2"}
        src = {"source_url": "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=503)):
            self.assertEqual(enrich.ENRICH_REGISTRY["workday"](row, src), "")


class OracleDetailTest(unittest.TestCase):
    _JD = "https://co.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/12345"

    def test_reverses_to_rest_endpoint(self):
        row = {"jd_url": self._JD}
        src = {"source_url": "x", "adapter_name": "oracle"}
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            return _Resp({"items": [{"ExternalDescriptionStr": "做 oracle 的事"}]})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["oracle"](row, src)
        self.assertIn("recruitingCEJobRequisitionDetails", cap["url"])
        self.assertIn('Id="12345"', cap["url"])
        self.assertIn("siteNumber=CX_1", cap["url"])
        self.assertIn("做 oracle 的事", body)

    def test_empty_items_raises_jobclosed(self):
        # finder by Id 返回 HTTP 200 + items:[] = 该 requisition 已撤 → expired。
        row = {"jd_url": self._JD}
        src = {"source_url": "x", "adapter_name": "oracle"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({"items": []})):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["oracle"](row, src)

    def test_404_raises_jobclosed(self):
        row = {"jd_url": self._JD}
        src = {"source_url": "x", "adapter_name": "oracle"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["oracle"](row, src)

    def test_transient_5xx_returns_empty_not_closed(self):
        row = {"jd_url": self._JD}
        src = {"source_url": "x", "adapter_name": "oracle"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=503)):
            self.assertEqual(enrich.ENRICH_REGISTRY["oracle"](row, src), "")

    def test_unmatched_jd_url_returns_empty_not_closed(self):
        # jd_url 反推不出 site/job（解析失败）→ 返回 ""（miss），不得当撤岗 expired。
        row = {"jd_url": "https://co.fa.us2.oraclecloud.com/some/other/path"}
        src = {"source_url": "x", "adapter_name": "oracle"}
        self.assertEqual(enrich.ENRICH_REGISTRY["oracle"](row, src), "")


class EightfoldDetailTest(unittest.TestCase):
    _JD = "https://acme.com/careers/job/123456789"
    _SRC = {"source_url": "https://acme.eightfold.ai/api/apply/v2/jobs?domain=acme.com",
            "adapter_name": "eightfold"}

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["eightfold"]({"jd_url": self._JD}, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=502)):
            self.assertEqual(enrich.ENRICH_REGISTRY["eightfold"]({"jd_url": self._JD}, self._SRC), "")


class SmartRecruitersDetailTest(unittest.TestCase):
    _JD = "https://jobs.smartrecruiters.com/Acme/123456"
    _SRC = {"source_url": "x", "adapter_name": "smartrecruiters"}

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["smartrecruiters"]({"jd_url": self._JD}, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=503)):
            self.assertEqual(enrich.ENRICH_REGISTRY["smartrecruiters"]({"jd_url": self._JD}, self._SRC), "")


class GreenhouseDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://boards.greenhouse.io/acme/jobs/4567890"}
    _SRC = {"source_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
            "adapter_name": "greenhouse"}

    def test_reverses_to_boards_api(self):
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            return _Resp({"content": "&lt;p&gt;Build things&lt;/p&gt;"})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["greenhouse"](self._ROW, self._SRC)
        self.assertEqual(cap["url"], "https://boards-api.greenhouse.io/v1/boards/acme/jobs/4567890")
        self.assertIn("Build things", body)

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["greenhouse"](self._ROW, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=503)):
            self.assertEqual(enrich.ENRICH_REGISTRY["greenhouse"](self._ROW, self._SRC), "")


class LeverDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://jobs.lever.co/acme/a1b2c3d4-1111-2222-3333-444455556666"}
    _SRC = {"source_url": "https://api.lever.co/v0/postings/acme?mode=json", "adapter_name": "lever"}

    def test_reverses_to_postings_api(self):
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            return _Resp({"description": "<p>do work</p>",
                          "lists": [{"text": "Reqs", "content": "<li>python</li>"}],
                          "additional": "<p>perks</p>"})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["lever"](self._ROW, self._SRC)
        self.assertEqual(cap["url"],
                         "https://api.lever.co/v0/postings/acme/a1b2c3d4-1111-2222-3333-444455556666")
        self.assertIn("do work", body)
        self.assertIn("python", body)

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["lever"](self._ROW, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=502)):
            self.assertEqual(enrich.ENRICH_REGISTRY["lever"](self._ROW, self._SRC), "")


class GoneHelperTest(unittest.TestCase):
    """通用撤岗约定：任何 fetcher 的 detail 端点 404/410 都判撤岗（杜绝逐源遗漏）。"""
    def test_raise_if_gone_404_410(self):
        for code in (404, 410):
            with self.assertRaises(enrich.JobClosedError):
                enrich._raise_if_gone(_Resp({}, status=code))

    def test_raise_if_gone_passes_through_others(self):
        for code in (200, 429, 500, 502, 503):
            enrich._raise_if_gone(_Resp({}, status=code))  # 不抛 = 通过


class RegistryTest(unittest.TestCase):
    def test_httpx_adapters_registered(self):
        for a in ("workday", "oracle", "eightfold", "smartrecruiters", "hotjob", "wt"):
            self.assertIn(a, enrich.ENRICH_REGISTRY)

    def test_detail_class(self):
        self.assertEqual(enrich.detail_class("hotjob"), "httpx")
        self.assertEqual(enrich.detail_class("wt"), "httpx")
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

    def test_write_failure_returns_err_not_raise(self):
        # Errno35 等写库瞬时错误：enrich_row 返回 "err"（不抛），该行留队列下轮重试，不掀整批。
        class RaiseSB:
            def table(self, n): return self
            def update(self, p): return self
            def eq(self, c, v): return self
            def execute(self): raise RuntimeError("[Errno 35] Resource temporarily unavailable")
        row = {"id": "j5", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 0}
        src = {"adapter_name": "hotjob", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: "足够长的真实职位描述正文内容"):
            res = enrich_backlog.enrich_row(RaiseSB(), row, src)
        self.assertEqual(res, "err")

    def test_closed_signal_sets_expired_not_failcount(self):
        # fetcher 报源站已关闭（JobClosedError）→ status='expired'，不当死信、不动 summary/fail_count。
        sb = _FakeSB()
        row = {"id": "j6", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 1}
        src = {"adapter_name": "hotjob", "source_url": "x"}

        def closed(a, r, s):
            raise enrich.JobClosedError("hotjob state=1017")

        with mock.patch.object(enrich_backlog.enrich, "enrich_one", closed):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "expired")
        patch = sb.updates["j6"]
        self.assertEqual(patch["status"], "expired")
        self.assertNotIn("enrich_fail_count", patch)
        self.assertNotIn("summary", patch)
        self.assertIn("enrich_checked_at", patch)

    def test_sweep_alive_job_with_summary_only_bumps_checked_at(self):
        # 巡检：仍在招、已有正文 → 只更新 enrich_checked_at，不重写 summary、不计死信。
        sb = _FakeSB()
        row = {"id": "j7", "source_id": "s", "title": "x", "jd_url": "u",
               "summary": "已有的职位正文", "enrich_fail_count": 0}
        src = {"adapter_name": "wt", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: "重新抓到的正文也够长足够"):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "alive")
        patch = sb.updates["j7"]
        self.assertEqual(list(patch.keys()), ["enrich_checked_at"])
        self.assertNotIn("summary", patch)
        self.assertNotIn("enrich_fail_count", patch)

    def test_sweep_closed_job_with_summary_expires(self):
        # 核心修复：已有正文但源站已撤岗的存量岗（fetch_queue 永远碰不到）→ 巡检置 expired。
        sb = _FakeSB()
        row = {"id": "j8", "source_id": "s", "title": "x", "jd_url": "u",
               "summary": "旧的职位正文", "enrich_fail_count": 0}
        src = {"adapter_name": "wt", "source_url": "x"}

        def closed(a, r, s):
            raise enrich.JobClosedError("wt req_state=9501")

        with mock.patch.object(enrich_backlog.enrich, "enrich_one", closed):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "expired")
        self.assertEqual(sb.updates["j8"]["status"], "expired")

    def test_dry_run_does_not_write(self):
        sb = _FakeSB()
        row = {"id": "j4", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 0}
        src = {"adapter_name": "hotjob", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: "一段足够长的真实职位描述正文内容"):
            enrich_backlog.enrich_row(sb, row, src, dry_run=True)
        self.assertEqual(sb.updates, {})


if __name__ == "__main__":
    unittest.main()
