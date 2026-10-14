"""六家自建站的逐岗探活器（2026-10-12）：网易 / 携程 / 百度 / B 站 / 小红书 / OPPO。

判死信号的证据（全集对拍数字）写在 enrich.py「六家自建站」那段注释里；这里 mock 网络钉住行为。
**重点是「什么情况下不许判死」**：expired 次日会被 purge-expired 永久删除。
三层安全网各有一组用例，删任何一条「不判死」用例都等于拆网：
  ① 每个探活器自己的判据（回带的 id 要对得上、状态位只认整数、jd_url 要整串符合形状……）；
  ② 阳性对照（_control_ok）：判死前，这个站这个板块用同一个请求形状刚读到过在招岗——
     对方中途降级 / 改版时，对照做不出来就停，不是「成立一次管到底」；
  ③ 撤岗熔断（enrich_backlog.EXPIRE_RATIO_GUARD）及它的单轮改写。
"""
import json
import pathlib
import unittest
from unittest import mock

import enrich


class _Resp:
    def __init__(self, json_body=None, text=None, status=200, url=""):
        self.status_code = status
        self._json = json_body
        self.text = text if text is not None else json.dumps(json_body, ensure_ascii=False)
        self.url = url

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json


def _reset_state():
    enrich._CONTROL.clear()
    enrich._CONTROL_FAILED.clear()
    enrich._BILIBILI_SESSION.update(client=None, at=0.0, failed_at=0.0)


class _Base(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def tearDown(self):
        _reset_state()


# ───────────────────────── ② 阳性对照 ─────────────────────────

class _Site:
    """假站点：live 集合里的 id 读到在招，其余读到已撤；degraded=True 时对谁都回已撤（对方降级 / 改版）。"""

    def __init__(self, live=("L1",), listed=("L1",)):
        self.live, self.listed = set(live), list(listed)
        self.degraded = False
        self.reads, self.list_calls = [], 0

    def read(self, job_id):
        self.reads.append(job_id)
        if not self.degraded and job_id in self.live:
            return "live", "正文"
        return "gone", ""

    def list_ids(self):
        self.list_calls += 1
        return list(self.listed)

    def settle(self, job_id, key="site"):
        return enrich._settle(key, job_id, self.read, self.list_ids)


class ControlTest(_Base):
    def test_first_gone_verdict_asks_the_list_for_a_live_job(self):
        site = _Site()
        with self.assertRaises(enrich.JobClosedError):
            site.settle("dead-1")
        self.assertEqual(site.reads, ["dead-1", "L1"])
        self.assertEqual(site.list_calls, 1)

    def test_gone_without_any_live_job_is_unknown(self):
        """列表第一页的岗也读不到在招（接口对谁都回空 / 列表接口不通）→ 一行都不判。"""
        for site in (_Site(live=(), listed=("L1", "L2")), _Site(listed=())):
            _reset_state()
            with self.assertRaises(enrich.DetailUnknownError):
                site.settle("dead-1")

    def test_list_that_raises_counts_as_failed(self):
        site = _Site()
        site.list_ids = mock.Mock(side_effect=RuntimeError("list api down"))
        with self.assertRaises(enrich.DetailUnknownError):
            site.settle("dead-1")

    def test_live_read_in_the_normal_flow_satisfies_the_control(self):
        site = _Site(live=("L1", "L2"))
        self.assertEqual(site.settle("L2"), "正文")
        with self.assertRaises(enrich.JobClosedError):
            site.settle("dead-1")
        self.assertEqual(site.list_calls, 0, "刚读到过在招岗，不用再专门去问列表")

    def test_control_is_rechecked_after_a_streak_of_gone_verdicts(self):
        """连判 20 个已撤、中间没读到过在招 → 把记住的那个在招岗再问一遍。"""
        site = _Site(live=("L1",))
        site.settle("L1")
        for i in range(enrich._CONTROL_MAX_GONE_STREAK):
            with self.assertRaises(enrich.JobClosedError):
                site.settle(f"dead-{i}")
        self.assertEqual(site.reads.count("L1"), 1)
        with self.assertRaises(enrich.JobClosedError):
            site.settle("dead-next")
        self.assertEqual(site.reads.count("L1"), 2, "第 21 个已撤之前应该复查对照")

    def test_degraded_site_stops_killing_within_one_streak(self):
        """对方中途开始对谁都回「已撤」（改版 / 限流时回空）：最多再错一轮就停，之后全部 unknown。"""
        site = _Site(live=("L1",), listed=("L1", "L2", "L3"))
        site.settle("L1")
        site.degraded = True
        killed = unknown = 0
        for i in range(200):
            try:
                site.settle(f"really-live-{i}")
            except enrich.JobClosedError:
                killed += 1
            except enrich.DetailUnknownError:
                unknown += 1
        self.assertLessEqual(killed, enrich._CONTROL_MAX_GONE_STREAK)
        self.assertEqual(killed + unknown, 200)
        self.assertGreaterEqual(unknown, 180)

    def test_control_is_rechecked_when_it_gets_old(self):
        site = _Site(live=("L1",))
        with mock.patch.object(enrich.time, "time", return_value=1000.0):
            site.settle("L1")
        with mock.patch.object(enrich.time, "time", return_value=1000.0 + enrich._CONTROL_MAX_AGE_SECONDS + 1):
            with self.assertRaises(enrich.JobClosedError):
                site.settle("dead-1")
        self.assertEqual(site.reads, ["L1", "dead-1", "L1"])

    def test_remembered_job_closed_meanwhile_falls_back_to_the_list(self):
        site = _Site(live=("L1", "L2"), listed=("L2",))
        site.settle("L1")
        site.live.discard("L1")
        with mock.patch.object(enrich.time, "time", return_value=enrich.time.time() + 3600):
            with self.assertRaises(enrich.JobClosedError):
                site.settle("dead-1")
        self.assertEqual(site.list_calls, 1)

    def test_failed_control_is_not_retried_immediately_but_is_retried_later(self):
        site = _Site(live=(), listed=("L1",))
        with mock.patch.object(enrich.time, "time", return_value=5000.0):
            for _ in range(3):
                with self.assertRaises(enrich.DetailUnknownError):
                    site.settle("dead-1")
            self.assertEqual(site.list_calls, 1, "对照没做出来之后 5 分钟内不该再打对方")
        site.live.add("L1")
        with mock.patch.object(enrich.time, "time", return_value=5000.0 + enrich._CONTROL_RETRY_SECONDS + 1):
            with self.assertRaises(enrich.JobClosedError):
                site.settle("dead-1")

    def test_control_is_per_key(self):
        """社招页读得到在招，不证明校招页读得到（百度招聘类型写错回的就是空壳）。"""
        site = _Site(live=("L1",), listed=())
        site.settle("L1", key="baidu:SOCIAL")
        with self.assertRaises(enrich.DetailUnknownError):
            site.settle("dead-1", key="baidu:GRADUATE")
        _reset_state()
        site.settle("L1", key="baidu:SOCIAL")
        with self.assertRaises(enrich.JobClosedError):
            site.settle("dead-1", key="baidu:SOCIAL")

    def test_unknown_read_is_unknown_even_with_a_fresh_control(self):
        enrich._control_note_live("site", "L1")
        with self.assertRaises(enrich.DetailUnknownError):
            enrich._settle("site", "1", lambda _id: ("unknown", "HTTP 503"), lambda: ["L1"])

    def test_every_site_goes_through_the_control(self):
        """六家的判死出口都要带对照用的列表函数；谁被改成不带，谁就回到「对方一降级就整源判死」。"""
        src = pathlib.Path(enrich.__file__).read_text(encoding="utf-8")
        calls = [line.strip() for line in src.splitlines() if line.strip().startswith("return _settle(")]
        self.assertEqual(len(calls), 6, calls)
        for line in calls:
            self.assertRegex(line, r"_read, (lambda: )?_\w+_list_(ids|keys)(\(.*\))?\)$")


# ───────────────────────── ① 各站判据 ─────────────────────────

class _SiteCase(_Base):
    """各站用例：对照结果直接指定（control=True/False），对照自身的行为在 ControlTest 里钉。"""
    KEYS = ()

    def _with_control(self, control):
        return mock.patch.object(enrich, "_control_ok", lambda key, read, list_ids: control)


_NETEASE_ROW = {"jd_url": "https://hr.163.com/job-detail.html?id=78550", "summary": "x"}


def _netease_live(job_id=78550, **over):
    data = {"id": job_id, "name": "AI 平台工程实习生", "description": "参与平台研发", "requirement": "本科及以上"}
    data.update(over)
    return {"code": 200, "msg": None, "data": data}


_NETEASE_GONE = {"code": 402, "msg": "职位失效或者不存在", "data": None}


class NeteaseTest(_SiteCase):
    def _run(self, resp, row=_NETEASE_ROW, control=True):
        with mock.patch.object(enrich.httpx, "get", lambda url, **kw: resp), self._with_control(control):
            return enrich._detail_netease(row, {})

    def test_live_returns_body(self):
        self.assertEqual(self._run(_Resp(_netease_live())), "参与平台研发\n本科及以上")

    def test_code_402_is_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_NETEASE_GONE))

    def test_code_402_without_live_control_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_NETEASE_GONE), control=False)

    def test_code_402_with_other_message_or_with_data_is_unknown(self):
        """只认 code 的话，哪天 402 被挪作他用（比如要登录）就整源清空。"""
        for payload in ({"code": 402, "msg": "请先登录", "data": None},
                        {"code": 402, "msg": "职位失效或者不存在", "data": {}},
                        {"code": True, "msg": "职位失效或者不存在", "data": None}):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(payload))

    def test_code_500_for_nonexistent_id_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp({"code": 500, "msg": "系统异常", "data": None}))

    def test_other_jobs_record_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_netease_live(job_id=1)))

    def test_http_error_and_non_json_are_unknown(self):
        for resp in (_Resp(_NETEASE_GONE, status=503), _Resp(_NETEASE_GONE, status=302),
                     _Resp(None, text="<html>waf</html>"), _Resp(None, text="")):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(resp)

    def test_other_url_shapes_are_unknown(self):
        for url in ("https://hr.163.com/job-list.html", "https://hr.163.com/job-detail.html?id=78550&from=x",
                    "https://hr.163.com/job-detail.html?id=７８５５０", "https://hr.163.com/job-detail.html?id=78550abc"):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(_NETEASE_GONE), row={"jd_url": url})

    def test_list_ids(self):
        ok = _Resp({"code": 200, "data": {"total": 2, "list": [{"id": 7}, {"id": 8}, {"name": "no id"}]}})
        with mock.patch.object(enrich.httpx, "post", lambda url, **kw: ok):
            self.assertEqual(enrich._netease_list_ids(), ["7", "8"])
        for bad in (_Resp({"code": 200, "data": None}), _Resp({"code": 200, "data": {"list": "oops"}}),
                    _Resp(None, text="<html></html>")):
            with mock.patch.object(enrich.httpx, "post", lambda url, **kw: bad):
                self.assertEqual(enrich._netease_list_ids(), [])


_CTRIP_ROW = {"jd_url": "https://careers.ctrip.com/#/experienced/job-detail/MJ036646", "summary": "x"}


def _ctrip_payload(rows, total=None, ack="Success", ret="201"):
    return {"retCode": ret, "retMessage": "调用成功",
            "retValue": {"total": len(rows) if total is None else total, "recruitJobAdList": rows},
            "ResponseStatus": {"Ack": ack}}


_CTRIP_HIT = {"fromId": "MJ036646", "jobTitle": "AI数据产品经理(MJ036646)", "duty": "数据基建", "requirements": "三年经验"}


class CtripTest(_SiteCase):
    def _run(self, payload, row=_CTRIP_ROW, control=True, status=200):
        sent = []

        def fake_post(url, **kw):
            sent.append(kw.get("json"))
            return _Resp(payload, status=status)

        with mock.patch.object(enrich.httpx, "post", fake_post), self._with_control(control):
            return enrich._detail_ctrip(row, {}), sent

    def test_live_returns_body_and_asks_by_from_id(self):
        body, sent = self._run(_ctrip_payload([_CTRIP_HIT]))
        self.assertEqual(body, "数据基建\n三年经验")
        self.assertEqual(sent[0]["condition"], {"fromId": ["MJ036646"]})

    def test_empty_result_is_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(_ctrip_payload([]))

    def test_empty_result_without_live_control_is_unknown(self):
        """不存在的 id、传错的参数回的也是这个空结果。"""
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_ctrip_payload([]), control=False)

    def test_results_without_this_job_are_unknown(self):
        """有结果却没有这一条 = 对方没按 fromId 过滤了（接口变了），不是撤岗。"""
        other = dict(_CTRIP_HIT, fromId="MJ000001")
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_ctrip_payload([other]))

    def test_failed_or_malformed_answers_are_unknown(self):
        no_status = _ctrip_payload([])
        del no_status["ResponseStatus"]
        no_total = _ctrip_payload([])
        del no_total["retValue"]["total"]
        no_rows = _ctrip_payload([])
        del no_rows["retValue"]["recruitJobAdList"]
        for payload, status in ((_ctrip_payload([], ack="Failure"), 200), (_ctrip_payload([], ret="500"), 200),
                                (_ctrip_payload([], total=3), 200), (_ctrip_payload([]), 502),
                                ({"retCode": "201", "retValue": None}, 200),
                                (no_status, 200), (no_total, 200), (no_rows, 200)):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(payload, status=status)

    def test_total_of_unexpected_type_is_unknown(self):
        for total in (False, None, "", 0.0, "zero"):
            payload = _ctrip_payload([])
            payload["retValue"]["total"] = total
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(payload)

    def test_from_id_with_unexpected_characters_is_unknown(self):
        """只截出 fromId 的前半段去查，回来的也是「空结果」——那不是撤岗，是我们问错了。"""
        for url in ("https://careers.ctrip.com/", "https://careers.ctrip.com/#/experienced/job-detail/MJ036646.1",
                    "https://careers.ctrip.com/#/experienced/job-detail/MJ036646/apply",
                    "https://careers.ctrip.com/#/experienced/job-detail/MJ 036646",
                    "https://careers.ctrip.com/#/other/job-detail/MJ036646"):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_ctrip_payload([]), row={"jd_url": url})

    def test_each_route_has_its_own_control_and_list(self):
        seen = []

        def fake_settle(key, job_id, read, list_ids):
            with mock.patch.object(enrich, "_ctrip_list_ids", lambda category: seen.append((key, category)) or []):
                list_ids()
            self.assertIs(read, enrich._ctrip_read)
            return ""

        with mock.patch.object(enrich, "_settle", fake_settle):
            enrich._detail_ctrip(_CTRIP_ROW, {})
            enrich._detail_ctrip({"jd_url": "https://careers.ctrip.com/#/campus/job-detail/MJ036717"}, {})
        self.assertEqual(seen, [("ctrip:experienced", "1"), ("ctrip:campus", "2")])

    def test_list_ids_sends_the_category(self):
        sent = []

        def fake_post(url, **kw):
            sent.append(kw["json"]["condition"])
            return _Resp(_ctrip_payload([{"fromId": "MJ1"}, {"fromId": "MJ2"}]))

        with mock.patch.object(enrich.httpx, "post", fake_post):
            self.assertEqual(enrich._ctrip_list_ids("2"), ["MJ1", "MJ2"])
        self.assertEqual(sent[0]["category"], "2")
        self.assertEqual(sent[0]["fromId"], [])
        with mock.patch.object(enrich.httpx, "post", lambda url, **kw: _Resp(None, text="oops", status=500)):
            self.assertEqual(enrich._ctrip_list_ids("1"), [])


_BAIDU_ID = "28872752-bdb3-4217-b265-23a91aefcf4c"
_BAIDU_URL = f"https://talent.baidu.com/jobs/detail/SOCIAL/{_BAIDU_ID}"
_BAIDU_ROW = {"jd_url": _BAIDU_URL, "summary": "x"}
_BAIDU_SHELL = ("<!DOCTYPE html><html><head><title>百度校园招聘</title></head><body>"
                + "<div></div>" * 300 + "使用百度前必读</body></html>")
_BAIDU_LIVE = ("<!DOCTYPE html><html><head><title>百度校园招聘</title></head><body><script>"
               'window.__USE_SSR__=true; window.__INITIAL_DATA__ ={"postId":"' + _BAIDU_ID + '"}</script>'
               + "职责" * 12000 + "</body></html>")


class BaiduTest(_SiteCase):
    def _run(self, text, row=_BAIDU_ROW, control=True, status=200, url=_BAIDU_URL):
        asked = []

        def fake_get(u, **kw):
            asked.append(u)
            return _Resp(None, text=text, status=status, url=url)

        with mock.patch.object(enrich.httpx, "get", fake_get), self._with_control(control):
            return enrich._detail_baidu(row, {}), asked

    def test_live_page_is_alive_and_asked_as_stored(self):
        body, asked = self._run(_BAIDU_LIVE)
        self.assertEqual(body, "")
        self.assertEqual(asked, [_BAIDU_URL])

    def test_shell_is_closed(self):
        self.assertLess(len(_BAIDU_SHELL), enrich._BAIDU_SHELL_MAX_CHARS)
        with self.assertRaises(enrich.JobClosedError):
            self._run(_BAIDU_SHELL)

    def test_shell_without_live_control_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_BAIDU_SHELL, control=False)

    def test_initial_data_without_this_post_id_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_BAIDU_LIVE.replace(_BAIDU_ID, "0" * 8 + "-0000-0000-0000-" + "0" * 12))

    def test_other_small_pages_are_unknown(self):
        """WAF 拦截页、半截页、被跳到别处的页都很小——小不等于空壳。"""
        for text, kw in (("<html><body>Access Denied</body></html>", {}),
                         ("", {}),
                         (_BAIDU_SHELL[:-7], {}),                                  # 没收完（缺 </html>）
                         (_BAIDU_SHELL, {"url": "https://talent.baidu.com/jobs/social-list"}),
                         (_BAIDU_SHELL, {"status": 503})):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(text, **kw)

    def test_big_page_without_data_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_BAIDU_SHELL.replace("<div></div>" * 300, "<div></div>" * 3000))

    def test_non_detail_urls_are_unknown(self):
        for url in ("https://talent.baidu.com/jobs/list",
                    f"https://talent.baidu.com/jobs/detail/social/{_BAIDU_ID}",
                    f"https://talent.baidu.com/jobs/detail/CAMPUS/{_BAIDU_ID}",
                    "https://talent.baidu.com/jobs/detail/SOCIAL/not-a-uuid",
                    f"{_BAIDU_URL}?from=x"):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_BAIDU_SHELL, row={"jd_url": url})

    def test_each_recruit_type_has_its_own_control_and_list(self):
        seen = []

        def fake_settle(key, detail_key, read, list_ids):
            with mock.patch.object(enrich, "_baidu_list_keys", lambda rt: seen.append((key, detail_key, rt)) or []):
                list_ids()
            return ""

        with mock.patch.object(enrich, "_settle", fake_settle):
            for rt in ("SOCIAL", "GRADUATE", "INTERN"):
                enrich._detail_baidu({"jd_url": f"https://talent.baidu.com/jobs/detail/{rt}/{_BAIDU_ID}"}, {})
        self.assertEqual(seen, [(f"baidu:{rt}", f"{rt}/{_BAIDU_ID}", rt) for rt in ("SOCIAL", "GRADUATE", "INTERN")])

    def test_list_keys_carry_the_recruit_type(self):
        sent = []

        def fake_post(url, **kw):
            sent.append(kw["data"])
            return _Resp({"data": {"total": 9, "list": [{"postId": "p1"}, {"postId": "p2"}]}})

        with mock.patch.object(enrich.httpx, "post", fake_post):
            self.assertEqual(enrich._baidu_list_keys("GRADUATE"), ["GRADUATE/p1", "GRADUATE/p2"])
        self.assertEqual(sent[0]["recruitType"], "GRADUATE")
        with mock.patch.object(enrich.httpx, "post", lambda url, **kw: _Resp({"data": []})):
            self.assertEqual(enrich._baidu_list_keys("SOCIAL"), [])


_BILI_ROW = {"jd_url": "https://jobs.bilibili.com/social/positions/29001", "summary": "x"}


def _bili_payload(status=1, job_id=29001, code=0, **over):
    data = {"id": job_id, "positionName": "资深大数据架构工程师", "positionStatus": status,
            "positionDescription": "<strong>工作职责:</strong>流计算"}
    data.update(over)
    return {"code": code, "data": data, "message": "success"}


class _FakeClient:
    def __init__(self, resp=None, token_resp=None):
        self.resp, self.token_resp = resp, token_resp
        self.asked, self.posted, self.headers, self.closed = [], [], {}, False

    def get(self, url, **kw):
        self.asked.append(url)
        if url.endswith("/csrf/token"):
            if isinstance(self.token_resp, Exception):
                raise self.token_resp
            return self.token_resp
        return self.resp

    def post(self, url, **kw):
        self.posted.append((url, kw.get("json")))
        return self.resp

    def close(self):
        self.closed = True


class BilibiliTest(_SiteCase):
    def _run(self, resp, row=_BILI_ROW, control=True):
        client = _FakeClient(resp)
        with mock.patch.object(enrich, "_bilibili_client", lambda: client), self._with_control(control):
            return enrich._detail_bilibili(row, {}), client

    def test_status_1_is_alive(self):
        body, client = self._run(_Resp(_bili_payload(status=1)))
        self.assertIn("流计算", body)
        self.assertEqual(client.asked, ["https://jobs.bilibili.com/api/srs/position/detail/29001"])

    def test_status_0_is_closed(self):
        for status in (0, "0"):
            with self.assertRaises(enrich.JobClosedError):
                self._run(_Resp(_bili_payload(status=status)))

    def test_status_0_without_live_control_is_unknown(self):
        """会话降级后要是所有记录的状态位都变成 0，没有对照就是整源判死。"""
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_bili_payload(status=0)), control=False)

    def test_missing_or_unknown_status_is_unknown(self):
        """⚠️ 0 是「已下架」，所以缺字段、False、0.0 都绝不能被当成 0。"""
        for status in (None, "", 2, "closed", False, 0.0):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(_bili_payload(status=status)))
        payload = _bili_payload()
        del payload["data"]["positionStatus"]
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(payload))

    def test_nonexistent_id_code_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp({"code": 60015, "data": None, "message": "职位不存在或已下架"}))

    def test_other_jobs_record_or_nameless_record_is_unknown(self):
        for payload in (_bili_payload(status=0, job_id=1), _bili_payload(status=0, positionName=""),
                        _bili_payload(status=0, code=False)):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(payload))

    def test_error_code_drops_the_session(self):
        enrich._BILIBILI_SESSION["at"] = 1e18
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp({"code": -101, "data": None, "message": "csrf 校验失败"}))
        self.assertEqual(enrich._BILIBILI_SESSION["at"], 0.0)

    def test_http_error_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_bili_payload(status=0), status=412))

    def test_other_url_shapes_are_unknown(self):
        for url in ("https://jobs.bilibili.com/campus/positions/29001",
                    "https://jobs.bilibili.com/social/positions/29001abc",
                    "https://jobs.bilibili.com/social/positions"):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(_bili_payload(status=0)), row={"jd_url": url})

    def test_list_ids_use_the_session_and_the_adapter_filter(self):
        client = _FakeClient(_Resp({"code": 0, "data": {"total": 2, "list": [{"id": 5}, {"id": 6}]}}))
        with mock.patch.object(enrich, "_bilibili_client", lambda: client):
            self.assertEqual(enrich._bilibili_list_ids(), ["5", "6"])
        self.assertEqual(client.posted[0][1]["positionTypeList"], ["3"])


class BilibiliSessionTest(_Base):
    def _client_factory(self, token_resp):
        made = []

        def factory(**kw):
            client = _FakeClient(token_resp=token_resp)
            made.append(client)
            return client
        return factory, made

    def test_token_becomes_a_header_and_the_session_is_reused(self):
        factory, made = self._client_factory(_Resp({"code": 0, "data": "tok-1"}))
        with mock.patch.object(enrich.httpx, "Client", factory):
            first = enrich._bilibili_client()
            second = enrich._bilibili_client()
        self.assertIs(first, second)
        self.assertEqual(len(made), 1)
        self.assertEqual(first.headers["X-CSRF"], "tok-1")

    def test_session_is_renewed_after_its_ttl(self):
        factory, made = self._client_factory(_Resp({"code": 0, "data": "tok"}))
        with mock.patch.object(enrich.httpx, "Client", factory):
            with mock.patch.object(enrich.time, "time", return_value=10_000.0):
                enrich._bilibili_client()
            with mock.patch.object(enrich.time, "time", return_value=10_000.0 + enrich._BILIBILI_SESSION_TTL + 1):
                enrich._bilibili_client()
        self.assertEqual(len(made), 2)

    def test_no_token_is_unknown_never_closed(self):
        """取不到 token 的每一种失败都只能是「没判出来」；一分钟内不再去取。"""
        for token_resp in (_Resp({"code": 0, "data": ""}), _Resp({"code": 0, "data": {"token": "x"}}),
                           _Resp({"code": 0, "data": None}), _Resp({"code": 0, "data": "tok"}, status=503),
                           _Resp(None, text="<html></html>"), RuntimeError("connect timeout")):
            _reset_state()
            factory, made = self._client_factory(token_resp)
            with mock.patch.object(enrich.httpx, "Client", factory):
                for _ in range(3):
                    with self.assertRaises(enrich.DetailUnknownError):
                        enrich._detail_bilibili(_BILI_ROW, {})
            self.assertEqual(len(made), 1, "失败后一分钟内不该再取 token")
            self.assertTrue(made[0].closed)


_XHS_ROW = {"jd_url": "https://job.xiaohongshu.com/campus/position/22211", "summary": "x"}


def _xhs_payload(status="in_recruitment", position_id=22211, code=200, **over):
    data = {"positionId": position_id, "positionName": "搜索推荐产品实习生", "recruitStatus": status,
            "duty": "负责推词产品", "qualification": "2027 届"}
    data.update(over)
    return {"statusCode": code, "alertMsg": "成功", "data": data, "success": True}


class XiaohongshuTest(_SiteCase):
    def _run(self, resp, row=_XHS_ROW, control=True):
        asked = []

        def fake_get(url, **kw):
            asked.append((url, kw.get("params")))
            return resp

        with mock.patch.object(enrich.httpx, "get", fake_get), self._with_control(control):
            return enrich._detail_xiaohongshu(row, {}), asked

    def test_in_recruitment_is_alive(self):
        body, asked = self._run(_Resp(_xhs_payload()))
        self.assertEqual(body, "负责推词产品\n2027 届")
        self.assertEqual(asked[0][1], {"positionId": "22211"})

    def test_recruit_close_is_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_xhs_payload(status="recruit_close")))

    def test_recruit_close_without_live_control_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_xhs_payload(status="recruit_close")), control=False)

    def test_social_route_is_parsed_too(self):
        row = {"jd_url": "https://job.xiaohongshu.com/social/position/22211", "summary": "x"}
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_xhs_payload(status="recruit_close")), row=row)

    def test_other_status_values_are_unknown(self):
        for status in (None, "", "paused", "RECRUIT_CLOSE", 0, False, ["recruit_close"]):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(_xhs_payload(status=status)))

    def test_invalid_id_answer_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp({"statusCode": 999, "alertMsg": "获取职位详情异常，请确认职位的有效性", "data": None}))

    def test_other_jobs_record_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_xhs_payload(status="recruit_close", position_id=1)))

    def test_http_error_and_non_json_are_unknown(self):
        for resp in (_Resp(_xhs_payload(status="recruit_close"), status=461), _Resp(None, text="<html></html>")):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(resp)

    def test_other_url_shapes_are_unknown(self):
        for url in ("https://job.xiaohongshu.com/social/position/22211/apply",
                    "https://job.xiaohongshu.com/intern/position/22211",
                    "https://job.xiaohongshu.com/social/position/"):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(_xhs_payload(status="recruit_close")), row={"jd_url": url})

    def test_list_ids(self):
        ok = _Resp({"statusCode": 200, "data": {"total": 2, "list": [{"positionId": 11}, {"positionId": 12}]}})
        with mock.patch.object(enrich.httpx, "post", lambda url, **kw: ok):
            self.assertEqual(enrich._xiaohongshu_list_ids(), ["11", "12"])


_OPPO_ROW = {"jd_url": "https://careers.oppo.com/university/oppo/campus/post/1612", "summary": "x"}


def _oppo_payload(status=0, position_id=1612, cities=({"cityName": "深圳市"},), code=0, **over):
    data = {"idRecruitPosition": position_id, "positionName": "高级影像算法工程师-博士", "positionStatus": status,
            "workCityVOList": list(cities) if cities is not None else None,
            "positionDesc": "相机算法", "positionRequire": "博士"}
    data.update(over)
    return {"code": code, "data": data, "msg": "success"}


class OppoTest(_SiteCase):
    def _run(self, resp, row=_OPPO_ROW, control=True):
        with mock.patch.object(enrich.httpx, "get", lambda url, **kw: resp), self._with_control(control):
            return enrich._detail_oppo(row, {})

    def test_status_0_is_alive(self):
        """⚠️ 极性和 B 站相反：OPPO 的 0 是在招。"""
        self.assertEqual(self._run(_Resp(_oppo_payload(status=0))), "相机算法\n博士")

    def test_status_1_without_cities_is_closed(self):
        for cities in ((), None):
            with self.assertRaises(enrich.JobClosedError):
                self._run(_Resp(_oppo_payload(status=1, cities=cities)))

    def test_status_1_without_live_control_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_oppo_payload(status=1, cities=())), control=False)

    def test_status_1_with_cities_is_unknown(self):
        """状态位的含义是按全集推的，所以要第二个条件；只有状态位是 1 的不判。"""
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_oppo_payload(status=1)))

    def test_missing_or_unknown_status_is_unknown(self):
        for status in (None, "", 2, True, 1.0):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(_oppo_payload(status=status, cities=())))

    def test_cities_missing_or_of_unexpected_type_do_not_count_as_empty(self):
        """降级响应把字段整个丢掉，不等于「工作城市为空」。"""
        for cities in (False, 0, "", {}):
            payload = _oppo_payload(status=1)
            payload["data"]["workCityVOList"] = cities
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(payload))
        payload = _oppo_payload(status=1)
        del payload["data"]["workCityVOList"]
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(payload))

    def test_nonexistent_id_answer_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp({"code": 500, "data": None, "msg": "未知的系统错误"}))

    def test_other_jobs_record_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_oppo_payload(status=1, cities=(), position_id=7)))

    def test_http_error_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_oppo_payload(status=1, cities=()), status=429))

    def test_other_url_shapes_are_unknown(self):
        for url in ("https://careers.oppo.com/university/oppo/campus/post/1612/apply",
                    "https://careers.oppo.com/social/post/1612",
                    "https://careers.oppo.com/university/oppo/campus/post?recruitType=Graduate"):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(_oppo_payload(status=1, cities=())), row={"jd_url": url})

    def test_list_ids(self):
        ok = _Resp({"code": 0, "data": {"total": 2, "records": [{"idRecruitPosition": 1769}, {"idRecruitPosition": 1880}]}})
        with mock.patch.object(enrich.httpx, "post", lambda url, **kw: ok):
            self.assertEqual(enrich._oppo_list_ids(), ["1769", "1880"])


class FlagTest(unittest.TestCase):
    def test_only_integers_and_ascii_digit_strings_count(self):
        self.assertEqual([enrich._flag(v) for v in (0, 1, "0", " 2 ", 200)], [0, 1, 0, 2, 200])
        for value in (False, True, None, "", 0.0, 1.0, "1.0", "-1", "０", "²", [], {}, "closed"):
            self.assertIsNone(enrich._flag(value), repr(value))


# ───────────────────────── 接线 + ③ 熔断 ─────────────────────────

_SITES = ("netease", "ctrip", "baidu", "bilibili", "xiaohongshu", "oppo")


class WiringTest(_Base):
    def test_registered(self):
        for site in _SITES:
            self.assertIn(site, enrich.ENRICH_REGISTRY)

    def test_not_in_browser_audit(self):
        """有逐岗接口的就不走浏览器巡检（与 google / huawei 同理）：留在那边只会重复探，
        而且浏览器对这六家判不出——网易、百度的在招页它都判不成 alive。"""
        import audit_dead_links
        for site in _SITES:
            self.assertNotIn(site, audit_dead_links._BROWSER_ADAPTERS)

    def test_alibaba_stays_in_browser_audit_and_out_of_the_registry(self):
        """阿里系详情接口的 content=null 不稳（隔一两个小时 2% 读回在招；channel 传错时在招岗也回 null），
        不能拿来判死。要接它，先解决这件事，再删这条用例。"""
        import audit_dead_links
        self.assertIn("alibaba", audit_dead_links._BROWSER_ADAPTERS)
        self.assertNotIn("alibaba", enrich.ENRICH_REGISTRY)

    def test_closed_and_unknown_reach_the_sweep_as_expired_and_err(self):
        import enrich_backlog as eb
        row = {"id": "r1", "jd_url": _OPPO_ROW["jd_url"], "summary": "已有正文", "title": "t"}
        src = {"adapter_name": "oppo"}

        def closed(_row, _src):
            raise enrich.JobClosedError("closed")

        def unknown(_row, _src):
            raise enrich.DetailUnknownError("unknown")

        with mock.patch.dict(enrich.ENRICH_REGISTRY, {"oppo": closed}):
            self.assertEqual(eb.enrich_row(None, row, src, dry_run=True), "expired")
        with mock.patch.dict(enrich.ENRICH_REGISTRY, {"oppo": unknown}):
            self.assertEqual(eb.enrich_row(None, row, src, dry_run=True), "err")
        with mock.patch.dict(enrich.ENRICH_REGISTRY, {"oppo": lambda _row, _src: ""}):
            self.assertEqual(eb.enrich_row(None, row, src, dry_run=True), "alive")


class ExpireGuardTest(unittest.TestCase):
    def test_registered_at_half(self):
        """清完存量后这六家的日常撤岗率是个位数；一轮判死过半 = 信号语义变了，先停。"""
        import enrich_backlog as eb
        for site in _SITES:
            self.assertEqual(eb.EXPIRE_RATIO_GUARD.get(site), 0.5)
            self.assertTrue(eb.should_trip_expire_guard(site, 1000, 600))

    def test_override_is_per_run_and_per_adapter(self):
        import enrich_backlog as eb
        with mock.patch.dict("os.environ", {eb.EXPIRE_GUARD_OVERRIDE_ENV: "ctrip=0.95, netease=off"}):
            self.assertFalse(eb.should_trip_expire_guard("ctrip", 1000, 900))
            self.assertTrue(eb.should_trip_expire_guard("ctrip", 1000, 960))
            self.assertFalse(eb.should_trip_expire_guard("netease", 1000, 1000))
            self.assertTrue(eb.should_trip_expire_guard("oppo", 1000, 600), "没点名的 adapter 仍按登记的阈值")
            self.assertEqual(eb.active_expire_guard_overrides(_SITES), {"ctrip": 0.95, "netease": float("inf")})
        self.assertTrue(eb.should_trip_expire_guard("ctrip", 1000, 600), "不带环境变量时回到登记的阈值")
        self.assertEqual(eb.active_expire_guard_overrides(_SITES), {})

    def test_override_ignores_anything_that_is_not_a_fraction_or_off(self):
        """想写 95% 写成 95、手滑写成 1e9 / inf / 空，都不许把熔断关掉。"""
        import enrich_backlog as eb
        for bad in ("ctrip=95", "ctrip=1e9", "ctrip=inf", "ctrip=nan", "ctrip=", "ctrip=abc", "ctrip=0", "ctrip=-0.5",
                    "ctrip=1.01", "ctrip", "=0.9", ",,"):
            with mock.patch.dict("os.environ", {eb.EXPIRE_GUARD_OVERRIDE_ENV: bad}):
                self.assertTrue(eb.should_trip_expire_guard("ctrip", 1000, 600), bad)
                self.assertEqual(eb.active_expire_guard_overrides(_SITES), {}, bad)

    def test_override_cannot_open_a_guard_for_unregistered_adapters(self):
        import enrich_backlog as eb
        with mock.patch.dict("os.environ", {eb.EXPIRE_GUARD_OVERRIDE_ENV: "wt=0.1,hotjob=off"}):
            self.assertFalse(eb.should_trip_expire_guard("wt", 1000, 999))
            self.assertEqual(eb.active_expire_guard_overrides(("wt", "hotjob")), {})

    def test_workflow_only_writes_on_an_exact_false(self):
        """手动触发时 dry_run 填成别的任何值都按只探不写走；定时任务（没有输入）是 false = 真写。"""
        workflow = (pathlib.Path(__file__).resolve().parents[1]
                    / ".github" / "workflows" / "liveness-sweep.yml").read_text(encoding="utf-8")
        self.assertIn('EXTRA="--dry-run"\n          if [ "$DRY_RUN" = "false" ]; then EXTRA=""; fi', workflow)
        self.assertIn("DRY_RUN: ${{ github.event.inputs.dry_run || 'false' }}", workflow)
        self.assertIn("type: boolean", workflow.split("dry_run:", 1)[1].split("expire_guard_override:", 1)[0])


if __name__ == "__main__":
    unittest.main()
