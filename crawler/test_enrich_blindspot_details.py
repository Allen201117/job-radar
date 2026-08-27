"""盲区六家 detail 探活器（jd/antgroup/haier/ashby/mihoyo/tencent_music，2026-08-28）。

判死信号全部经真伪 id live 对拍（证据在 enrich.py 各函数注释）；这里 mock 网络钉死行为：
明确撤岗信号 → JobClosedError；含糊信号（系统异常/格式错/结构变化/5xx）→ 返回空不判死。
"""
import unittest
from unittest import mock

import enrich


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _HtmlResp:
    def __init__(self, text, status=200):
        self.status_code = status
        self.text = text

    def json(self):
        raise ValueError("not json")


class JdDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://zhaopin.jd.com/web/job-info-detail?requementId=223572"}
    _LIVE = ('<html><body><h1 class="post-name">采销经理</h1>'
             '<div class="main-content"><h2 class="f-title">岗位描述</h2>'
             '<div class="part"><p>分析市场需求</p></div>'
             '<h2 class="f-title">任职要求</h2>'
             '<div class="part"><p>本科以上学历</p></div></div></body></html>')

    def test_extracts_summary_for_live_job(self):
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp(self._LIVE)):
            out = enrich._detail_jd(self._ROW, {})
        self.assertIn("分析市场需求", out)
        self.assertIn("本科以上学历", out)

    def test_redirect_to_homepage_raises_job_closed(self):
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp("", 302)):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_jd(self._ROW, {})

    def test_missing_h1_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp("<html><body>改版了</body></html>")):
            self.assertEqual(enrich._detail_jd(self._ROW, {}), "")

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp("", 503)):
            self.assertEqual(enrich._detail_jd(self._ROW, {}), "")


class AntGroupDetailTest(unittest.TestCase):
    _SOCIAL = {"jd_url": "https://talent.antgroup.com/off-campus-position?positionId=25022803557231"}

    def test_derives_social_board_and_extracts_summary(self):
        cap = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            cap["url"], cap["json"] = url, json
            return _Resp({"success": True, "content": {"description": "负责技术方案", "requirement": "本科以上"}})

        with mock.patch.object(enrich.httpx, "post", fake_post):
            out = enrich._detail_antgroup(self._SOCIAL, {})
        self.assertEqual(cap["url"], "https://hrcareersweb.antgroup.com/api/social/position/detail")
        self.assertEqual(cap["json"], {"id": "25022803557231"})
        self.assertIn("负责技术方案", out)

    def test_campus_path_hits_campus_api(self):
        cap = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            cap["url"] = url
            return _Resp({"success": True, "content": {"description": "校招岗位"}})

        with mock.patch.object(enrich.httpx, "post", fake_post):
            enrich._detail_antgroup({"jd_url": "https://talent.antgroup.com/campus-position?positionId=9"}, {})
        self.assertEqual(cap["url"], "https://hrcareersweb.antgroup.com/api/campus/position/detail")

    def test_content_null_raises_job_closed(self):
        with mock.patch.object(enrich.httpx, "post", lambda *a, **k: _Resp({"success": True, "content": None})):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_antgroup(self._SOCIAL, {})

    def test_success_false_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "post",
                               lambda *a, **k: _Resp({"success": False, "errorMsg": "系统异常", "content": None})):
            self.assertEqual(enrich._detail_antgroup(self._SOCIAL, {}), "")

    def test_missing_positionid_returns_empty(self):
        self.assertEqual(enrich._detail_antgroup({"jd_url": "https://talent.antgroup.com/off-campus-position"}, {}), "")


class HaierDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://maker.haier.net/client/job/detail.html?id=10230172"}

    def test_extracts_summary_for_live_job(self):
        html = ('<html><body><div class="cb-wordwrap">负责数据中心产品设计</div>'
                '<div class="cb-wordwrap">本科以上学历</div></body></html>')
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp(html)):
            out = enrich._detail_haier(self._ROW, {})
        self.assertIn("负责数据中心产品设计", out)

    def test_cb_page404_raises_job_closed(self):
        html = '<html><body><div class="cb-page404"><p>参数错误</p></div></body></html>'
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp(html)):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_haier(self._ROW, {})

    def test_empty_wordwrap_without_page404_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp("<html><body>改版</body></html>")):
            self.assertEqual(enrich._detail_haier(self._ROW, {}), "")


class AshbyDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://jobs.ashbyhq.com/perplexity/50a2def5-adeb-4f13-99c1-88c32482b772"}

    def test_real_posting_extracts_description(self):
        html = ('<title>MTS @ Perplexity</title>'
                '<script type="application/ld+json">{"@type":"JobPosting","description":"<p>做AI</p>"}</script>')
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp(html)):
            self.assertIn("做AI", enrich._detail_ashby(self._ROW, {}))

    def test_generic_shell_raises_job_closed(self):
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp("<title>Jobs</title>")):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_ashby(self._ROW, {})

    def test_real_title_without_ldjson_returns_empty_not_closed(self):
        # 双条件：title 正常但缺 ld+json（结构变化）→ 不判死
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp("<title>MTS @ X</title>")):
            self.assertEqual(enrich._detail_ashby(self._ROW, {}), "")

    def test_non_uuid_url_returns_empty(self):
        self.assertEqual(enrich._detail_ashby({"jd_url": "https://jobs.ashbyhq.com/perplexity"}, {}), "")


class MihoyoDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://jobs.mihoyo.com/#/position/9407"}

    def test_reverses_fragment_id_and_extracts(self):
        cap = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            cap["json"] = json
            return _Resp({"code": 0, "data": {"description": "负责AI", "jobRequire": "本科"}})

        with mock.patch.object(enrich.httpx, "post", fake_post):
            out = enrich._detail_mihoyo(self._ROW, {})
        self.assertEqual(cap["json"]["id"], "9407")
        self.assertIn("负责AI", out)

    def test_campus_hash_route_also_parses(self):
        cap = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            cap["json"] = json
            return _Resp({"code": 0, "data": {"description": "校招"}})

        with mock.patch.object(enrich.httpx, "post", fake_post):
            enrich._detail_mihoyo({"jd_url": "https://jobs.mihoyo.com/#/campus/position/9100"}, {})
        self.assertEqual(cap["json"]["id"], "9100")

    def test_not_found_code_raises_job_closed(self):
        with mock.patch.object(enrich.httpx, "post",
                               return_value=_Resp({"code": 1080001052, "message": "当前职位不存在"})):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_mihoyo(self._ROW, {})

    def test_input_format_error_not_closed(self):
        with mock.patch.object(enrich.httpx, "post", return_value=_Resp({"code": 2080001003})):
            self.assertEqual(enrich._detail_mihoyo(self._ROW, {}), "")


class TencentMusicDetailTest(unittest.TestCase):
    def test_social_board_hits_job_info(self):
        cap = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            cap["url"] = url
            return _Resp({"code": "200", "data": {"duty": "负责生态", "requirement": "5年经验"}})

        row = {"jd_url": "https://join.tencentmusic.com/social/post-details/?id=15055"}
        with mock.patch.object(enrich.httpx, "post", fake_post):
            out = enrich._detail_tencent_music(row, {})
        self.assertIn("/api/job/info", cap["url"])
        self.assertIn("负责生态", out)

    def test_campus_board_hits_uc_job_info(self):
        cap = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            cap["url"] = url
            return _Resp({"code": "200", "data": {"duty": "运营实习"}})

        row = {"jd_url": "https://join.tencentmusic.com/campus/post-details/?id=15056"}
        with mock.patch.object(enrich.httpx, "post", fake_post):
            enrich._detail_tencent_music(row, {})
        self.assertIn("/api/uc-job/info", cap["url"])

    def test_code_404_raises_job_closed(self):
        row = {"jd_url": "https://join.tencentmusic.com/social/post-details/?id=999999"}
        with mock.patch.object(enrich.httpx, "post",
                               return_value=_Resp({"code": 404, "data": {}, "msg": "该岗位不存在！"})):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_tencent_music(row, {})


class RegistryWiringTest(unittest.TestCase):
    def test_blindspot_adapters_registered(self):
        for name in ("jd", "antgroup", "haier", "ashby", "mihoyo", "tencent_music",
                     "iguopin", "pinduoduo", "meituan_campus"):
            self.assertIn(name, enrich.ENRICH_REGISTRY)
            self.assertEqual(enrich.detail_class(name), "httpx")


if __name__ == "__main__":
    unittest.main()


class IguopinDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://www.iguopin.com/job/detail?id=215422750917920320"}

    def test_alive_returns_contents(self):
        body = {"code": 200, "msg": "OK", "data": {"job_id": "215422750917920320",
                                                   "status": 1, "contents": "岗位职责..."}}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp(body)):
            self.assertEqual(enrich._detail_iguopin(self._ROW, {}), "岗位职责...")

    def test_status_2_raises_job_closed(self):
        body = {"code": 200, "data": {"job_id": "196915804485193548", "status": 2}}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp(body)):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_iguopin(self._ROW, {})

    def test_code_2001_raises_job_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({"code": 2001, "msg": "数据不存在。"})):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_iguopin(self._ROW, {})

    def test_unknown_code_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({"code": 5000, "msg": "系统繁忙"})):
            self.assertEqual(enrich._detail_iguopin(self._ROW, {}), "")


class PinduoduoDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://careers.pddglobalhr.com/campus/grad/detail"
                      "?positionId=54ad4666-f80b-47be-840b-5a99cf04a3d7"}

    def test_alive_returns_summary(self):
        body = {"success": True, "result": {"id": "54ad4666-f80b-47be-840b-5a99cf04a3d7",
                                            "normal": True, "jobDuty": "负责xxx",
                                            "serveRequirement": "本科以上"}}
        with mock.patch.object(enrich.httpx, "post", lambda *a, **k: _Resp(body)):
            out = enrich._detail_pinduoduo(self._ROW, {})
        self.assertIn("负责xxx", out)
        self.assertIn("本科以上", out)

    def test_null_id_raises_job_closed(self):
        body = {"success": True, "result": {"id": None, "normal": False}}
        with mock.patch.object(enrich.httpx, "post", lambda *a, **k: _Resp(body)):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_pinduoduo(self._ROW, {})

    def test_success_false_returns_empty_not_closed(self):
        body = {"success": False, "errorCode": 991000000, "errorMsg": "职位id不为空"}
        with mock.patch.object(enrich.httpx, "post", lambda *a, **k: _Resp(body)):
            self.assertEqual(enrich._detail_pinduoduo(self._ROW, {}), "")

    def test_missing_position_id_returns_empty(self):
        self.assertEqual(enrich._detail_pinduoduo({"jd_url": "https://careers.pddglobalhr.com/campus/grad/detail"}, {}), "")


class MeituanCampusAliasTest(unittest.TestCase):
    def test_meituan_campus_reuses_meituan_detail(self):
        self.assertIs(enrich.ENRICH_REGISTRY["meituan_campus"], enrich._detail_meituan)
