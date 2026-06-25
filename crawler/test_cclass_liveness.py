"""C 类大厂自建门户撤岗探活器单测（纯函数 / mock httpx，不打真网络）。

每个 _detail_xxx 双用：① 撤岗信号 → JobClosedError（liveness-sweep 置 expired）② 在招 → 返回正文或 ""。
关闭信号 live 实测（2026-06-25，记忆 job-radar-cclass-liveness-signals）：必须区别于 bogus/网络错——
红线：绝不把活岗误判为死。下方每源覆盖 alive / closed / 拿不准(不判死) / 缺参 四类。
"""
import unittest
from unittest import mock

import enrich


class _Resp:
    def __init__(self, data=None, status=200, text=""):
        self._data = data
        self.status_code = status
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


def _patch(method, fn):
    return mock.patch.object(enrich.httpx, method, fn)


class AmazonTest(unittest.TestCase):
    ROW = {"jd_url": "https://www.amazon.jobs/en/jobs/10423254/data-center-tech"}

    def test_404_raises_closed(self):
        with _patch("get", lambda url, **kw: _Resp(status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["amazon"](self.ROW, {})

    def test_200_alive_returns_empty(self):
        cap = {}
        with _patch("get", lambda url, **kw: cap.update(url=url) or _Resp(status=200, text="<html>")):
            self.assertEqual(enrich.ENRICH_REGISTRY["amazon"](self.ROW, {}), "")
        self.assertEqual(cap["url"], self.ROW["jd_url"])  # 探 HTML 逐岗页本身，不是 .json


class AppleTest(unittest.TestCase):
    ROW = {"jd_url": "https://jobs.apple.com/en-us/details/200662246-3543/wifi-engineer?team=SFTWR"}

    def test_404_raises_closed(self):
        with _patch("get", lambda url, **kw: _Resp(status=404, data={"error": "jobsite.general.serviceError"})):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["apple"](self.ROW, {})

    def test_200_alive_and_jobnumber_in_url(self):
        cap = {}
        with _patch("get", lambda url, **kw: cap.update(url=url) or _Resp(status=200, data={"res": {"id": "REQ-1"}})):
            self.assertEqual(enrich.ENRICH_REGISTRY["apple"](self.ROW, {}), "")
        self.assertIn("/api/v1/jobDetails/200662246-3543", cap["url"])

    def test_no_jobnumber_returns_empty(self):
        with _patch("get", lambda url, **kw: _Resp(status=500)):
            self.assertEqual(enrich.ENRICH_REGISTRY["apple"]({"jd_url": "https://jobs.apple.com/x"}, {}), "")


class MeituanTest(unittest.TestCase):
    ROW = {"jd_url": "https://zhaopin.meituan.com/web/position/detail?jobUnionId=4466907773"}

    def test_status0_no_data_raises_closed(self):
        with _patch("post", lambda url, **kw: _Resp(data={"data": None, "status": 0, "message": "职位已下线或不存在！"})):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["meituan"](self.ROW, {})

    def test_status1_with_data_alive(self):
        # ⚠️ jobStatus 001 也是活岗（红鲱鱼）：有 data + status=1 → 不判死。
        with _patch("post", lambda url, **kw: _Resp(data={"data": {"jobStatus": "001"}, "status": 1})):
            self.assertEqual(enrich.ENRICH_REGISTRY["meituan"](self.ROW, {}), "")

    def test_missing_id_returns_empty(self):
        self.assertEqual(enrich.ENRICH_REGISTRY["meituan"]({"jd_url": "https://zhaopin.meituan.com/x"}, {}), "")


class MicrosoftTest(unittest.TestCase):
    ROW = {"jd_url": "https://jobs.careers.microsoft.com/global/en/job/200036259"}

    def test_zero_hit_raises_closed(self):
        with _patch("get", lambda url, **kw: _Resp(data={"data": {"positions": []}})):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["microsoft"](self.ROW, {})

    def test_exact_hit_alive(self):
        with _patch("get", lambda url, **kw: _Resp(data={"data": {"positions": [{"displayJobId": "200036259"}]}})):
            self.assertEqual(enrich.ENRICH_REGISTRY["microsoft"](self.ROW, {}), "")

    def test_hits_but_no_exact_match_not_closed(self):
        # n>0 但无精确命中 → 拿不准，绝不判死。
        with _patch("get", lambda url, **kw: _Resp(data={"data": {"positions": [{"displayJobId": "999"}]}})):
            self.assertEqual(enrich.ENRICH_REGISTRY["microsoft"](self.ROW, {}), "")


class SfExpressTest(unittest.TestCase):
    ROW = {"jd_url": "https://hr.sf-express.com/JobSearchById/70413,3"}

    def test_404_title_raises_closed(self):
        html = "<html><head><title>顺丰人才招聘系统-404</title></head></html>"
        with _patch("get", lambda url, **kw: _Resp(status=200, text=html)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["sf_express"](self.ROW, {})

    def test_society_title_alive(self):
        html = "<html><head><title>顺丰人才招聘系统-社会招聘-产品经理</title></head></html>"
        with _patch("get", lambda url, **kw: _Resp(status=200, text=html)):
            self.assertEqual(enrich.ENRICH_REGISTRY["sf_express"](self.ROW, {}), "")


class TencentTest(unittest.TestCase):
    ROW = {"jd_url": "https://careers.tencent.com/jobdesc.html?postId=1933451871519899648"}

    def test_e1005_raises_closed(self):
        with _patch("get", lambda url, **kw: _Resp(data={"Code": 500, "Data": "E1005"})):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["tencent"](self.ROW, {})

    def test_e1003_not_closed(self):
        # bogus 入参错 E1003 ≠ 撤岗 → 不判死（红线）。
        with _patch("get", lambda url, **kw: _Resp(data={"Code": 500, "Data": "E1003"})):
            self.assertEqual(enrich.ENRICH_REGISTRY["tencent"](self.ROW, {}), "")

    def test_alive_returns_summary(self):
        with _patch("get", lambda url, **kw: _Resp(data={"Code": 200, "Data": {"Responsibility": "负责A", "Requirement": "本科"}})):
            body = enrich.ENRICH_REGISTRY["tencent"](self.ROW, {})
        self.assertIn("负责A", body)
        self.assertIn("本科", body)


class VivoTest(unittest.TestCase):
    ROW = {"jd_url": "https://hr.vivo.com/job-detail?_irjc=M1&_irjid=M2069007358904823810"}

    def test_105002_raises_closed(self):
        with _patch("post", lambda url, **kw: _Resp(data={"code": 105002, "message": "官网职位未发布", "success": False})):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["vivo"](self.ROW, {})

    def test_server_error_100000_not_closed(self):
        # bogus 入参 → code=100000 服务器错 ≠ 撤岗 → 不判死。
        with _patch("post", lambda url, **kw: _Resp(status=500, data={"code": 100000, "success": False})):
            self.assertEqual(enrich.ENRICH_REGISTRY["vivo"](self.ROW, {}), "")

    def test_alive_returns_jobdesc(self):
        with _patch("post", lambda url, **kw: _Resp(data={"code": 0, "data": {"job_desc": "岗位职责..."}})):
            self.assertEqual(enrich.ENRICH_REGISTRY["vivo"](self.ROW, {}), "岗位职责...")


class RegistryTest(unittest.TestCase):
    def test_all_seven_registered_as_httpx(self):
        for a in ("amazon", "apple", "meituan", "microsoft", "sf_express", "tencent", "vivo"):
            self.assertEqual(enrich.detail_class(a), "httpx", a)


if __name__ == "__main__":
    unittest.main()
