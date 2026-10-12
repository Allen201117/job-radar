"""六家自建站的逐岗探活器（2026-10-12）：网易 / 携程 / 百度 / B 站 / 小红书 / OPPO。

判死信号的证据（全集对拍数字）写在 enrich.py「六家自建站」那段注释里；这里 mock 网络钉住行为。
**重点是「什么情况下不许判死」**：expired 次日会被 purge-expired 永久删除。这六家里有三家的信号是
「查不到 = 已撤」，参数传错、对方改接口都长这样——所以另有一组用例钉住「没有阳性对照就一行不判」。
删任何一条「不判死」用例都等于拆安全网。
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


class _Base(unittest.TestCase):
    def setUp(self):
        enrich._CANARY.clear()

    def tearDown(self):
        enrich._CANARY.clear()


# ───────────────────────── 阳性对照（三家「查不到 = 已撤」的站共用）─────────────────────────

class CanaryTest(_Base):
    def test_gone_without_live_control_is_unknown(self):
        """对照做不出来（列表接口不通 / 列表里的岗也读不到在招）→ 一行都不判。"""
        with self.assertRaises(enrich.DetailUnknownError):
            enrich._settle("site", "1", lambda _id: ("gone", ""), canary=lambda: False)

    def test_gone_with_live_control_is_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            enrich._settle("site", "1", lambda _id: ("gone", ""), canary=lambda: True)

    def test_control_that_raises_counts_as_failed(self):
        def boom():
            raise RuntimeError("list api down")
        with self.assertRaises(enrich.DetailUnknownError):
            enrich._settle("site", "1", lambda _id: ("gone", ""), canary=boom)

    def test_live_read_satisfies_the_control(self):
        """正常巡检里读到过一个在招岗 = 对照已经成立，之后不用再专门去问列表。"""
        self.assertEqual(enrich._settle("site", "1", lambda _id: ("live", "正文"), canary=lambda: False), "正文")
        with self.assertRaises(enrich.JobClosedError):
            enrich._settle("site", "2", lambda _id: ("gone", ""), canary=lambda: False)

    def test_failed_control_is_not_retried_immediately(self):
        calls = []

        def failing():
            calls.append(1)
            return False
        for _ in range(3):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich._settle("site", "1", lambda _id: ("gone", ""), canary=failing)
        self.assertEqual(len(calls), 1, "对照失败后 5 分钟内不该再打对方")

    def test_control_is_per_site(self):
        enrich._canary_mark("netease")
        with self.assertRaises(enrich.DetailUnknownError):
            enrich._settle("ctrip", "1", lambda _id: ("gone", ""), canary=lambda: False)

    def test_unknown_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            enrich._settle("site", "1", lambda _id: ("unknown", "HTTP 503"), canary=lambda: True)

    def test_three_absence_sites_are_wired_to_a_control(self):
        """网易 / 携程 / 百度的判死出口必须带对照；拿掉任何一个，这三家就回到「参数错也判死」。"""
        src = pathlib.Path(enrich.__file__).read_text(encoding="utf-8")
        for site in ("netease", "ctrip", "baidu"):
            calls = [line for line in src.splitlines() if f'_settle("{site}"' in line]
            self.assertEqual(len(calls), 1, site)
            self.assertTrue(calls[0].rstrip().endswith(f"_{site}_read, _{site}_canary)"), calls[0])


# ───────────────────────── 网易 ─────────────────────────

_NETEASE_ROW = {"jd_url": "https://hr.163.com/job-detail.html?id=78550", "summary": "x"}


def _netease_live(job_id=78550, **over):
    data = {"id": job_id, "name": "AI 平台工程实习生", "description": "参与平台研发", "requirement": "本科及以上"}
    data.update(over)
    return {"code": 200, "msg": None, "data": data}


_NETEASE_GONE = {"code": 402, "msg": "职位失效或者不存在", "data": None}


class NeteaseTest(_Base):
    def _run(self, resp, row=_NETEASE_ROW, control=True):
        with mock.patch.object(enrich.httpx, "get", lambda url, **kw: resp), \
                mock.patch.object(enrich, "_netease_canary", lambda: control):
            return enrich._detail_netease(row, {})

    def test_live_returns_body(self):
        self.assertEqual(self._run(_Resp(_netease_live())), "参与平台研发\n本科及以上")

    def test_code_402_is_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_NETEASE_GONE))

    def test_code_402_without_live_control_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_NETEASE_GONE), control=False)

    def test_code_402_with_other_message_is_unknown(self):
        """只认 code 的话，哪天 402 被挪作他用（比如要登录）就整源清空。"""
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp({"code": 402, "msg": "请先登录", "data": None}))

    def test_code_500_for_nonexistent_id_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp({"code": 500, "msg": "系统异常", "data": None}))

    def test_other_jobs_record_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_netease_live(job_id=1)))

    def test_http_error_and_non_json_are_unknown(self):
        for resp in (_Resp({"code": 402, "msg": "职位失效或者不存在", "data": None}, status=503),
                     _Resp(None, text="<html>waf</html>")):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(resp)

    def test_url_without_id_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_NETEASE_GONE), row={"jd_url": "https://hr.163.com/job-list.html"})


# ───────────────────────── 携程 ─────────────────────────

_CTRIP_ROW = {"jd_url": "https://careers.ctrip.com/#/experienced/job-detail/MJ036646", "summary": "x"}


def _ctrip_payload(rows, total=None, ack="Success", ret="201"):
    return {"retCode": ret, "retMessage": "调用成功",
            "retValue": {"total": len(rows) if total is None else total, "recruitJobAdList": rows},
            "ResponseStatus": {"Ack": ack}}


_CTRIP_HIT = {"fromId": "MJ036646", "jobTitle": "AI数据产品经理(MJ036646)", "duty": "数据基建", "requirements": "三年经验"}


class CtripTest(_Base):
    def _run(self, payload, row=_CTRIP_ROW, control=True, status=200):
        sent = []

        def fake_post(url, **kw):
            sent.append(kw.get("json"))
            return _Resp(payload, status=status)

        with mock.patch.object(enrich.httpx, "post", fake_post), \
                mock.patch.object(enrich, "_ctrip_canary", lambda: control):
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

    def test_failed_calls_are_unknown(self):
        for payload, status in ((_ctrip_payload([], ack="Failure"), 200),
                                (_ctrip_payload([], ret="500"), 200),
                                (_ctrip_payload([], total=3), 200),
                                (_ctrip_payload([]), 502),
                                ({"retCode": "201", "retValue": None}, 200)):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(payload, status=status)

    def test_campus_route_is_parsed_too(self):
        row = {"jd_url": "https://careers.ctrip.com/#/campus/job-detail/MJ036646", "summary": "x"}
        self.assertEqual(self._run(_ctrip_payload([_CTRIP_HIT]), row=row)[0], "数据基建\n三年经验")

    def test_url_without_from_id_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_ctrip_payload([]), row={"jd_url": "https://careers.ctrip.com/"})


# ───────────────────────── 百度 ─────────────────────────

_BAIDU_ID = "28872752-bdb3-4217-b265-23a91aefcf4c"
_BAIDU_URL = f"https://talent.baidu.com/jobs/detail/SOCIAL/{_BAIDU_ID}"
_BAIDU_ROW = {"jd_url": _BAIDU_URL, "summary": "x"}
_BAIDU_SHELL = ("<!DOCTYPE html><html><head><title>百度校园招聘</title></head><body>"
                + "<div></div>" * 300 + "使用百度前必读</body></html>")
_BAIDU_LIVE = ("<!DOCTYPE html><html><head><title>百度校园招聘</title></head><body><script>"
               'window.__USE_SSR__=true; window.__INITIAL_DATA__ ={"postId":"' + _BAIDU_ID + '"}</script>'
               + "职责" * 12000 + "</body></html>")


class BaiduTest(_Base):
    def _run(self, text, row=_BAIDU_ROW, control=True, status=200, url=_BAIDU_URL):
        asked = []

        def fake_get(u, **kw):
            asked.append(u)
            return _Resp(None, text=text, status=status, url=url)

        with mock.patch.object(enrich.httpx, "get", fake_get), \
                mock.patch.object(enrich, "_baidu_canary", lambda: control):
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
                    "https://talent.baidu.com/jobs/detail/SOCIAL/not-a-uuid"):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_BAIDU_SHELL, row={"jd_url": url})


# ───────────────────────── B 站 ─────────────────────────

_BILI_ROW = {"jd_url": "https://jobs.bilibili.com/social/positions/29001", "summary": "x"}


def _bili_payload(status=1, job_id=29001, code=0, **over):
    data = {"id": job_id, "positionName": "资深大数据架构工程师", "positionStatus": status,
            "positionDescription": "<strong>工作职责:</strong>流计算"}
    data.update(over)
    return {"code": code, "data": data, "message": "success"}


class _FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.asked = []

    def get(self, url, **kw):
        self.asked.append(url)
        return self.resp


class BilibiliTest(_Base):
    def _run(self, resp, row=_BILI_ROW):
        client = _FakeClient(resp)
        with mock.patch.object(enrich, "_bilibili_client", lambda: client):
            return enrich._detail_bilibili(row, {}), client

    def test_status_1_is_alive(self):
        body, client = self._run(_Resp(_bili_payload(status=1)))
        self.assertIn("流计算", body)
        self.assertEqual(client.asked, ["https://jobs.bilibili.com/api/srs/position/detail/29001"])

    def test_status_0_is_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_bili_payload(status=0)))

    def test_status_0_as_string_is_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_bili_payload(status="0")))

    def test_missing_or_unknown_status_is_unknown(self):
        """⚠️ 0 是「已下架」，所以缺字段绝不能被当成 0。"""
        for status in (None, "", 2, "closed"):
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
        for payload in (_bili_payload(status=0, job_id=1), _bili_payload(status=0, positionName="")):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(payload))

    def test_error_code_drops_the_session(self):
        enrich._BILIBILI_SESSION["at"] = 1e18
        try:
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp({"code": -101, "data": None, "message": "csrf 校验失败"}))
            self.assertEqual(enrich._BILIBILI_SESSION["at"], 0.0)
        finally:
            enrich._BILIBILI_SESSION["at"] = 0.0

    def test_http_error_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_bili_payload(status=0), status=412))


# ───────────────────────── 小红书 ─────────────────────────

_XHS_ROW = {"jd_url": "https://job.xiaohongshu.com/campus/position/22211", "summary": "x"}


def _xhs_payload(status="in_recruitment", position_id=22211, code=200, **over):
    data = {"positionId": position_id, "positionName": "搜索推荐产品实习生", "recruitStatus": status,
            "duty": "负责推词产品", "qualification": "2027 届"}
    data.update(over)
    return {"statusCode": code, "alertMsg": "成功", "data": data, "success": True}


class XiaohongshuTest(_Base):
    def _run(self, resp, row=_XHS_ROW):
        asked = []

        def fake_get(url, **kw):
            asked.append((url, kw.get("params")))
            return resp

        with mock.patch.object(enrich.httpx, "get", fake_get):
            return enrich._detail_xiaohongshu(row, {}), asked

    def test_in_recruitment_is_alive(self):
        body, asked = self._run(_Resp(_xhs_payload()))
        self.assertEqual(body, "负责推词产品\n2027 届")
        self.assertEqual(asked[0][1], {"positionId": "22211"})

    def test_recruit_close_is_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_xhs_payload(status="recruit_close")))

    def test_social_route_is_parsed_too(self):
        row = {"jd_url": "https://job.xiaohongshu.com/social/position/22211", "summary": "x"}
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_xhs_payload(status="recruit_close")), row=row)

    def test_other_status_values_are_unknown(self):
        for status in (None, "", "paused", "RECRUIT_CLOSE"):
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


# ───────────────────────── OPPO ─────────────────────────

_OPPO_ROW = {"jd_url": "https://careers.oppo.com/university/oppo/campus/post/1612", "summary": "x"}


def _oppo_payload(status=0, position_id=1612, cities=({"cityName": "深圳市"},), code=0, **over):
    data = {"idRecruitPosition": position_id, "positionName": "高级影像算法工程师-博士", "positionStatus": status,
            "workCityVOList": list(cities) if cities is not None else None,
            "positionDesc": "相机算法", "positionRequire": "博士"}
    data.update(over)
    return {"code": code, "data": data, "msg": "success"}


class OppoTest(_Base):
    def _run(self, resp, row=_OPPO_ROW):
        with mock.patch.object(enrich.httpx, "get", lambda url, **kw: resp):
            return enrich._detail_oppo(row, {})

    def test_status_0_is_alive(self):
        """⚠️ 极性和 B 站相反：OPPO 的 0 是在招。"""
        self.assertEqual(self._run(_Resp(_oppo_payload(status=0))), "相机算法\n博士")

    def test_status_1_without_cities_is_closed(self):
        for cities in ((), None):
            with self.assertRaises(enrich.JobClosedError):
                self._run(_Resp(_oppo_payload(status=1, cities=cities)))

    def test_status_1_with_cities_is_unknown(self):
        """状态位的含义是按全集推的，所以要第二个条件；只有状态位是 1 的不判。"""
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_oppo_payload(status=1)))

    def test_missing_or_unknown_status_is_unknown(self):
        for status in (None, "", 2):
            with self.assertRaises(enrich.DetailUnknownError):
                self._run(_Resp(_oppo_payload(status=status, cities=())))

    def test_nonexistent_id_answer_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp({"code": 500, "data": None, "msg": "未知的系统错误"}))

    def test_other_jobs_record_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_oppo_payload(status=1, cities=(), position_id=7)))

    def test_http_error_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_oppo_payload(status=1, cities=()), status=429))


# ───────────────────────── 接线 ─────────────────────────

_SITES = ("netease", "ctrip", "baidu", "bilibili", "xiaohongshu", "oppo")


class WiringTest(unittest.TestCase):
    def test_registered(self):
        for site in _SITES:
            self.assertIn(site, enrich.ENRICH_REGISTRY)

    def test_not_in_browser_audit(self):
        """有逐岗接口的就不走浏览器巡检（与 google / huawei 同理）：留在那边只会重复探，
        而且浏览器对这六家判不出——网易、百度的在招页它都判不成 alive。"""
        import audit_dead_links
        for site in _SITES:
            self.assertNotIn(site, audit_dead_links._BROWSER_ADAPTERS)

    def test_expire_guard_registered(self):
        """清完存量后这六家的日常撤岗率是个位数；一轮判死过半 = 信号语义变了，先停。"""
        import enrich_backlog as eb
        for site in _SITES:
            self.assertEqual(eb.EXPIRE_RATIO_GUARD.get(site), 0.5)

    def test_guard_override_is_per_run_and_per_adapter(self):
        import enrich_backlog as eb
        with mock.patch.dict("os.environ", {"LIVENESS_EXPIRE_GUARD_OVERRIDE": "ctrip=0.95, netease=1.01"}):
            self.assertFalse(eb.should_trip_expire_guard("ctrip", 1000, 900))
            self.assertTrue(eb.should_trip_expire_guard("ctrip", 1000, 960))
            self.assertFalse(eb.should_trip_expire_guard("netease", 1000, 1000))
            self.assertTrue(eb.should_trip_expire_guard("oppo", 1000, 600), "没点名的 adapter 仍按登记的阈值")
        self.assertTrue(eb.should_trip_expire_guard("ctrip", 1000, 600), "不带环境变量时回到登记的阈值")

    def test_guard_override_ignores_garbage_and_unregistered(self):
        import enrich_backlog as eb
        with mock.patch.dict("os.environ", {"LIVENESS_EXPIRE_GUARD_OVERRIDE": "ctrip=abc,,=0.9,wt=0.1,oppo"}):
            self.assertTrue(eb.should_trip_expire_guard("ctrip", 1000, 600), "写坏的值不许把熔断关掉")
            self.assertFalse(eb.should_trip_expire_guard("wt", 1000, 999), "没登记熔断的 adapter 不能靠它新开一道")


if __name__ == "__main__":
    unittest.main()
