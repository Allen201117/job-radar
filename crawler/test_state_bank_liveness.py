"""国有大行 + 中国移动五家自建门户的逐岗撤岗探活器（2026-09-06）。

判死信号全部经真伪 id live 对拍（证据写在 enrich.py 各函数注释里）；这里 mock 网络钉住行为。
**这些用例的重点不是「能判死」，是「什么情况下不许判死」**——这五个源合计 9,268 个 active 岗，
探活器一旦把含糊信号当撤岗，一轮 sweep 就能把整个源清空，而 expired 次日会被 purge 永久删除。
所以每个 detector 都有一组「含糊信号 → 不判死」的用例，删任何一条都等于拆掉安全网。
"""
import json
import pathlib
import unittest
from unittest import mock

import enrich


class _Resp:
    """够用的假响应：status_code / text / json()。json_body 显式给 None 表示「不是 JSON」。"""

    def __init__(self, json_body=None, text="", status=200):
        self.status_code = status
        self._json = json_body
        self.text = text if text or json_body is None else json.dumps(json_body, ensure_ascii=False)

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """记录每次请求并按顺序吐出预置响应；同时充当上下文管理器。

    responses 可以是列表（按调用顺序）或 callable(method, url, kwargs) -> _Resp。"""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _next(self, method, url, kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if callable(self.responses):
            return self.responses(method, url, kwargs)
        return self.responses[len(self.calls) - 1]

    def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_client(responses):
    """把 enrich._cn_portal_client 换成假 client；返回 (patcher_cm, client) 供断言请求内容。"""
    client = _FakeClient(responses)
    return mock.patch.object(enrich, "_cn_portal_client",
                             lambda headers, timeout=None: client), client


class SpdbLivenessTest(unittest.TestCase):
    _ROW = {"jd_url": "https://job.spdb.com.cn/jobDetail?jobId=10023380&type=2"}
    _LIVE = ("<html><body><div>返回列表</div>"
             "<div>业务储备生 拉萨分行 应聘条件 本科及以上学历</div>"
             "<footer>All rights reserved</footer></body></html>")
    # 不存在的 jobId 返回的 936 字节固定错误壳（2026-09-06 live，三种伪 id 逐字节一致）。
    _GONE = ('<html><body><div class="my404">500</div>'
             '<div class="my404text">您访问的页面出错了！</div></body></html>')

    def test_live_page_returns_body(self):
        patcher, client = _patch_client([_Resp(text=self._LIVE)])
        with patcher:
            out = enrich._detail_spdb(self._ROW, {})
        self.assertIn("应聘条件", out)
        # type 必须沿用 jd_url 里的值（1=社招/2=校招，用错打不开）。
        self.assertEqual(client.calls[0]["params"], {"jobId": "10023380", "type": "2"})

    def test_my404_shell_raises_job_closed(self):
        patcher, _ = _patch_client([_Resp(text=self._GONE)])
        with patcher, self.assertRaises(enrich.JobClosedError):
            enrich._detail_spdb(self._ROW, {})

    def test_error_marker_with_real_body_is_not_closed(self):
        """半截页面（错误壳标记出现、但正文也抽得出来）一律不判死。"""
        half = self._LIVE.replace("<body>", '<body><div class="my404">您访问的页面出错了！</div>')
        patcher, _ = _patch_client([_Resp(text=half)])
        with patcher:
            self.assertIn("应聘条件", enrich._detail_spdb(self._ROW, {}))

    def test_blank_page_without_marker_is_not_closed(self):
        patcher, _ = _patch_client([_Resp(text="<html><body>改版了</body></html>")])
        with patcher:
            self.assertEqual(enrich._detail_spdb(self._ROW, {}), "")

    def test_transient_5xx_is_not_closed(self):
        patcher, _ = _patch_client([_Resp(text="", status=503)])
        with patcher:
            self.assertEqual(enrich._detail_spdb(self._ROW, {}), "")

    def test_missing_job_id_makes_no_request(self):
        patcher, client = _patch_client([])
        with patcher:
            self.assertEqual(enrich._detail_spdb({"jd_url": "https://job.spdb.com.cn/jobDetail"}, {}), "")
        self.assertEqual(client.calls, [])


class IcbcLivenessTest(unittest.TestCase):
    _ROW = {"jd_url": "https://job.icbc.com.cn/pc/index.html#/main/school/postDetail/00000000000006393132"}

    @staticmethod
    def _live(**over):
        data = {"postId": "00000000000006393132", "publishPostName": "科技菁英",
                "postStatus": "R03409", "applyState": 1,
                "enterEndTime": "2099-10-08 23:59:00", "postDepict": ""}
        data.update(over)
        return _Resp({"retCode": "0", "retMsg": "查询成功", "data": data})

    def test_live_post_returns_decoded_depict(self):
        # postDepict = base64(urlencode(HTML))，解码逻辑与 adapters/icbc.py 共用一份。
        import base64
        import urllib.parse
        depict = base64.b64encode(urllib.parse.quote("<p>岗位职责若干</p>").encode()).decode()
        patcher, client = _patch_client([self._live(postDepict=depict)])
        with patcher:
            self.assertIn("岗位职责若干", enrich._detail_icbc(self._ROW, {}))
        self.assertEqual(client.calls[0]["json"]["private"],
                         {"postId": "00000000000006393132"})

    def test_gone_message_raises_job_closed(self):
        patcher, _ = _patch_client([_Resp({"retCode": "9", "retMsg": "岗位已失效", "data": {}})])
        with patcher, self.assertRaises(enrich.JobClosedError):
            enrich._detail_icbc(self._ROW, {})

    def test_param_error_shares_retcode_9_but_is_not_closed(self):
        """⚠️ 空 postId 也返 retCode=9，只是 retMsg 是「请求参数错误」——那是我们传错了。
        只认 retCode 的话这里会把在招岗误杀，所以必须连 retMsg 一起认。"""
        patcher, _ = _patch_client([_Resp({"retCode": "9", "retMsg": "请求参数错误", "data": {}})])
        with patcher:
            self.assertEqual(enrich._detail_icbc(self._ROW, {}), "")

    def test_apply_closed_needs_both_flag_and_past_deadline(self):
        patcher, _ = _patch_client([self._live(applyState=2, enterEndTime="2020-01-01 23:59:59")])
        with patcher, self.assertRaises(enrich.JobClosedError):
            enrich._detail_icbc(self._ROW, {})

    def test_apply_state_2_with_future_deadline_is_not_closed(self):
        """半截数据（applyState 缺省成 2、截止日还在未来）不许判死。"""
        patcher, _ = _patch_client([self._live(applyState=2, enterEndTime="2099-01-01 23:59:59")])
        with patcher:
            self.assertEqual(enrich._detail_icbc(self._ROW, {}), "")

    def test_apply_state_2_without_deadline_is_not_closed(self):
        patcher, _ = _patch_client([self._live(applyState=2, enterEndTime="")])
        with patcher:
            self.assertEqual(enrich._detail_icbc(self._ROW, {}), "")

    def test_empty_data_is_not_closed(self):
        patcher, _ = _patch_client([_Resp({"retCode": "0", "retMsg": "查询成功", "data": {}})])
        with patcher:
            self.assertEqual(enrich._detail_icbc(self._ROW, {}), "")

    def test_non_json_is_not_closed(self):
        patcher, _ = _patch_client([_Resp(None, text="<html>waf</html>")])
        with patcher:
            self.assertEqual(enrich._detail_icbc(self._ROW, {}), "")

    def test_missing_post_id_makes_no_request(self):
        patcher, client = _patch_client([])
        with patcher:
            self.assertEqual(
                enrich._detail_icbc({"jd_url": "https://job.icbc.com.cn/pc/index.html#/main/social"}, {}), "")
        self.assertEqual(client.calls, [])


class CcbLivenessTest(unittest.TestCase):
    _ROW = {"jd_url": ("https://job3.ccb.com/cn/job/job_detail.html?planId=2026090108928217"
                       "&planPost=20260901111630530411&planType=XY&orgId=2034199"
                       "&secondOrgId=8b18d581486f94cf014913fae5877e31")}
    _WARM = _Resp({"SUCCESS": "true"})

    @staticmethod
    def _detail(**over):
        body = {"SUCCESS": "true", "planPostName": "客户经理岗", "planStatus": "1",
                "planName": "2027年度校园招聘", "postDate": "2026-09-04",
                "postDesc": "客户管户", "PostRequest": "本科以上"}
        body.update(over)
        return _Resp(body)

    def test_warmup_runs_before_detail(self):
        """⚠️ 不热身直接打 NHR107 会拿到 SUCCESS=false「请重新登录」——热身不是可选项。"""
        patcher, client = _patch_client([self._WARM, self._detail()])
        with patcher:
            out = enrich._detail_ccb(self._ROW, {})
        self.assertIn("客户管户", out)
        self.assertEqual(client.calls[0]["params"]["TXCODE"], "100119")
        self.assertEqual(client.calls[1]["params"]["TXCODE"], "NHR107")
        # 详情接口的 orgId 传的是**二级机构 id**，与 adapters/ccb.py 同口径。
        self.assertEqual(client.calls[1]["params"]["orgId"],
                         "8b18d581486f94cf014913fae5877e31")

    def test_plan_status_2_raises_job_closed(self):
        patcher, _ = _patch_client([self._WARM, self._detail(planStatus="2")])
        with patcher, self.assertRaises(enrich.JobClosedError):
            enrich._detail_ccb(self._ROW, {})

    def test_empty_skeleton_raises_job_closed(self):
        skeleton = {"SUCCESS": "true", "planPostName": "", "planStatus": "",
                    "planName": "", "postDate": "", "postDesc": "", "PostRequest": ""}
        patcher, _ = _patch_client([self._WARM, _Resp(skeleton)])
        with patcher, self.assertRaises(enrich.JobClosedError):
            enrich._detail_ccb(self._ROW, {})

    def test_partial_payload_is_not_an_empty_skeleton(self):
        """只要还有一个业务字段有值就不算空骨架——宁可漏判不可错杀。"""
        patcher, _ = _patch_client([self._WARM, _Resp(
            {"SUCCESS": "true", "planPostName": "客户经理岗", "planStatus": "",
             "planName": "", "postDate": "", "postDesc": "", "PostRequest": ""})])
        with patcher:
            self.assertEqual(enrich._detail_ccb(self._ROW, {}), "")

    def test_success_false_is_not_closed(self):
        """冷会话「请重新登录」/「要素不完整」都是 SUCCESS=false，既不是登录墙也不是撤岗。"""
        patcher, _ = _patch_client([self._WARM, _Resp(
            {"SUCCESS": "false", "ERRORMSG": "暂时未能处理您的请求，请重新登录。"})])
        with patcher:
            self.assertEqual(enrich._detail_ccb(self._ROW, {}), "")

    def test_empty_body_is_not_closed(self):
        """Bot UA 会换来 HTTP 200 + 零字节 body（_repair_json 抛 RuntimeError）→ 不判死。"""
        patcher, _ = _patch_client([self._WARM, _Resp(None, text="")])
        with patcher:
            self.assertEqual(enrich._detail_ccb(self._ROW, {}), "")

    def test_missing_params_make_no_request(self):
        patcher, client = _patch_client([])
        with patcher:
            self.assertEqual(
                enrich._detail_ccb({"jd_url": "https://job3.ccb.com/cn/job/job_detail.html"}, {}), "")
        self.assertEqual(client.calls, [])


class BankcommLivenessTest(unittest.TestCase):
    _ROW = {"jd_url": "https://job.bankcomm.com/#/social/recruitmentInfo/?positionId=38498"}
    _CAMPUS_ROW = {"jd_url": "https://job.bankcomm.com/#/school/recruitmentInfo/?positionId=38498"}

    @staticmethod
    def _detail_ok():
        return _Resp({"RSP_HEAD": {"TRAN_SUCCESS": "1"},
                      "RSP_BODY": {"results": {"pubName": "客户服务经理",
                                               "responsibility": "负责营业网点营运",
                                               "require": "本科以上"}}})

    @staticmethod
    def _sys_error():
        # 不存在的 positionId 返回的就是这个**通用**系统异常码——单凭它判死会清空整源。
        return _Resp({"RSP_HEAD": {"TRAN_SUCCESS": "0", "ERROR_CODE": "JUMPTESTBP9001",
                                   "ERROR_MESSAGE": "系统异常"}, "RSP_BODY": {"results": None}})

    @staticmethod
    def _listed(ids):
        return _Resp({"RSP_HEAD": {"TRAN_SUCCESS": "1"},
                      "RSP_BODY": {"results": {"total": len(ids),
                                               "policyList": [{"positionId": i} for i in ids]}}})

    def test_detail_success_returns_summary(self):
        patcher, client = _patch_client([self._detail_ok()])
        with patcher:
            out = enrich._detail_bankcomm(self._ROW, {})
        self.assertIn("负责营业网点营运", out)
        self.assertEqual(len(client.calls), 1)   # 活岗只走一跳

    def test_sys_error_plus_absent_on_both_boards_is_closed(self):
        patcher, client = _patch_client([self._sys_error(), self._listed([]), self._listed([])])
        with patcher, self.assertRaises(enrich.JobClosedError):
            enrich._detail_bankcomm(self._ROW, {})
        # 社招板块（engageType=3）先查，再查校招（1）——两个都查不到才判死。
        self.assertEqual(
            [c["data"] and json.loads(c["data"]["REQ_MESSAGE"])["REQ_BODY"]["params"]
             ["businessPara"]["engageType"] for c in client.calls[1:]], [3, 1])

    def test_sys_error_but_still_listed_is_not_closed(self):
        patcher, _ = _patch_client([self._sys_error(), self._listed([38498])])
        with patcher:
            self.assertEqual(enrich._detail_bankcomm(self._ROW, {}), "")

    def test_found_on_the_other_board_is_not_closed(self):
        """岗位换了板块（社招↔校招）不许当撤岗——只查一个板块必然误杀。"""
        patcher, _ = _patch_client([self._sys_error(), self._listed([]), self._listed([38498])])
        with patcher:
            self.assertEqual(enrich._detail_bankcomm(self._ROW, {}), "")

    def test_campus_section_queries_school_board_first(self):
        patcher, client = _patch_client([self._sys_error(), self._listed([38498])])
        with patcher:
            enrich._detail_bankcomm(self._CAMPUS_ROW, {})
        params = json.loads(client.calls[1]["data"]["REQ_MESSAGE"])["REQ_BODY"]["params"]
        self.assertEqual(params["businessPara"]["engageType"], 1)

    def test_list_call_not_answering_is_not_closed(self):
        """列表接口自己也没答成（TRAN_SUCCESS != 1）→ 站点不在状态，不构成撤岗证据。"""
        patcher, _ = _patch_client([self._sys_error(),
                                    _Resp({"RSP_HEAD": {"TRAN_SUCCESS": "0"}, "RSP_BODY": {}})])
        with patcher:
            self.assertEqual(enrich._detail_bankcomm(self._ROW, {}), "")

    def test_missing_position_id_makes_no_request(self):
        """⚠️ 空 positionId 查列表会返回整版岗位，把「没查到」伪装成「查到了」——绝不能发出去。"""
        patcher, client = _patch_client([])
        with patcher:
            self.assertEqual(enrich._detail_bankcomm(
                {"jd_url": "https://job.bankcomm.com/#/social/recruitmentInfo/"}, {}), "")
        self.assertEqual(client.calls, [])


class CmccLivenessTest(unittest.TestCase):
    _ROW = {"jd_url": "https://job.10086.cn/personal/job/detail.html?id=08f1bb8a-ccac&typess=1"}

    def test_live_job_returns_summary(self):
        patcher, client = _patch_client([_Resp({"code": "0000", "message": "处理成功",
                                                "data": {"description": "数据分析",
                                                         "dutyCondition": "本科以上"}})])
        with patcher:
            out = enrich._detail_cmcc(self._ROW, {})
        self.assertIn("数据分析", out)
        self.assertIn("本科以上", out)

    def test_double_encoded_json_body_is_parsed(self):
        """⚠️ 带 Accept: application/json 时这个接口返回的是「JSON 字符串套 JSON」，
        r.json() 拿到 str。不兜住的话整源探活全变 err，看着像网络抖动、实则永远不好。"""
        inner = json.dumps({"code": "0000", "data": {"description": "数据分析"}}, ensure_ascii=False)
        patcher, _ = _patch_client([_Resp(inner)])
        with patcher:
            self.assertIn("数据分析", enrich._detail_cmcc(self._ROW, {}))

    def test_request_does_not_send_accept_json(self):
        captured = {}

        def fake_client(headers, timeout=None):
            captured.update(headers)
            return _FakeClient([_Resp({"code": "0000", "data": {"description": "x"}})])

        with mock.patch.object(enrich, "_cn_portal_client", fake_client):
            enrich._detail_cmcc(self._ROW, {})
        self.assertNotIn("Accept", captured)

    def test_not_found_raises_job_closed(self):
        patcher, _ = _patch_client([_Resp({"code": "2000", "message": "未查询到职位信息",
                                           "data": None})])
        with patcher, self.assertRaises(enrich.JobClosedError):
            enrich._detail_cmcc(self._ROW, {})

    def test_signature_failure_is_not_closed(self):
        """签名失败也是 HTTP 200（code=9999）——是我们这边的问题，不是对方撤岗。"""
        patcher, _ = _patch_client([_Resp({"code": "9999", "message": "无效的签名"})])
        with patcher:
            self.assertEqual(enrich._detail_cmcc(self._ROW, {}), "")

    def test_missing_field_error_is_not_closed(self):
        patcher, _ = _patch_client([_Resp({"code": "1001", "message": "必填项为空"})])
        with patcher:
            self.assertEqual(enrich._detail_cmcc(self._ROW, {}), "")

    def test_code_2000_with_unexpected_message_is_not_closed(self):
        patcher, _ = _patch_client([_Resp({"code": "2000", "message": "服务繁忙"})])
        with patcher:
            self.assertEqual(enrich._detail_cmcc(self._ROW, {}), "")

    def test_missing_id_makes_no_request(self):
        patcher, client = _patch_client([])
        with patcher:
            self.assertEqual(enrich._detail_cmcc(
                {"jd_url": "https://job.10086.cn/personal/job/detail.html"}, {}), "")
        self.assertEqual(client.calls, [])


class LivenessWiringTest(unittest.TestCase):
    """注册表 ↔ liveness-sweep matrix 的接线：漏一头就等于「写了探活器但从来没跑过」。"""

    _NEW = ("spdb", "icbc", "ccb", "bankcomm", "cmcc")

    def test_five_portals_are_registered_as_httpx(self):
        for adapter in self._NEW:
            self.assertEqual(enrich.detail_class(adapter), "httpx", adapter)

    def test_backlog_drain_picks_them_up(self):
        import enrich_backlog
        for adapter in self._NEW:
            self.assertIn(adapter, enrich_backlog.HTTPX_ADAPTERS, adapter)

    def test_every_registered_adapter_is_in_the_sweep_matrix(self):
        """⚠️ chnenergy 就是这么漏的：2026-09-05 进了 ENRICH_REGISTRY，却没加进 matrix，
        于是只被 enrich-backlog 补正文、一次都没被探活过。这条断言防它再发生。"""
        workflow = (pathlib.Path(__file__).resolve().parents[1]
                    / ".github" / "workflows" / "liveness-sweep.yml").read_text(encoding="utf-8")
        matrix = workflow.split("adapter: [", 1)[1].split("]", 1)[0]
        listed = {x.strip() for x in matrix.replace("\n", " ").split(",") if x.strip()}
        missing = sorted(set(enrich.ENRICH_REGISTRY) - listed)
        self.assertEqual(missing, [], f"这些 adapter 有探活器但不在 liveness-sweep matrix 里：{missing}")

    def test_abchina_is_deliberately_not_registered(self):
        """农行走浏览器（响应体 SM4 加密，明文只在页面内存里），不能塞进 httpx 通道。
        它的详情页判死另有坑（hash 路由不 reload 会读到上一个岗的页面），单独排期。"""
        self.assertIsNone(enrich.detail_class("abchina"))


if __name__ == "__main__":
    unittest.main()
