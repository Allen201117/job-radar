"""北森逐岗探活器 enrich._detail_beisen（2026-09-23）。

判死信号 `Data.Status == 2` 的证据（北森前端代码 + 全集对拍数字）写在 enrich._detail_beisen 的
docstring 里；这里 mock 网络钉住行为。北森是库里最大的一族（11 万+ active 岗），
**重点是「什么情况下不许判死」**——expired 当天会被 purge-expired 永久删除，
一条含糊信号被当成撤岗，一轮 sweep 就能把整个租户清空。删任何一条「不判死」用例都等于拆安全网。
"""
import json
import pathlib
import unittest
from unittest import mock

import enrich

_ID = "9726f46c-1dbc-4050-a02f-8c2de6df27ce"
_ROW = {"jd_url": f"https://chinalife.zhiye.com/custom/zwxq?jobAdId={_ID}", "summary": "x"}


class _Resp:
    def __init__(self, json_body=None, text=None, status=200):
        self.status_code = status
        self._json = json_body
        self.text = text if text is not None else json.dumps(json_body, ensure_ascii=False)

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json


def _payload(status=1, code=200, **data):
    body = {"Id": _ID, "JobAdName": "南岸支公司签单岗", "Status": status,
            "Duty": "负责签单", "Require": "本科及以上"}
    body.update(data)
    return {"Code": code, "Message": "operation success", "Data": body}


class BeisenLivenessTest(unittest.TestCase):
    def _run(self, resp, row=_ROW):
        calls = []

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return resp

        with mock.patch.object(enrich.httpx, "get", fake_get):
            return enrich._detail_beisen(row, {}), calls

    # ---------- 能判死 ----------

    def test_status_2_is_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_payload(status=2)))

    def test_status_2_as_string_is_closed(self):
        """2026-09-23 全集里 Status 都是数字；字符串 "2" 也要认（防哪天序列化方式变了就整族漏判）。"""
        with self.assertRaises(enrich.JobClosedError):
            self._run(_Resp(_payload(status="2")))

    # ---------- 在招 ----------

    def test_status_1_returns_duty_and_require(self):
        body, calls = self._run(_Resp(_payload(status="1")))
        self.assertEqual(body, "负责签单\n【任职要求】\n本科及以上")
        url, kwargs = calls[0]
        self.assertEqual(url, "https://chinalife.zhiye.com/api/JobAd/GetJobAdInfo")
        self.assertEqual(kwargs["params"]["jobAdId"], _ID)

    def test_status_1_without_body_is_alive_not_unknown(self):
        body, _ = self._run(_Resp(_payload(status=1, Duty="", Require="")))
        self.assertEqual(body, "")

    def test_uppercase_id_in_url_and_response(self):
        row = {"jd_url": f"https://x.zhiye.com/social/detail?JobAdId={_ID.upper()}"}
        body, calls = self._run(_Resp(_payload(status=1, Id=_ID.upper())), row=row)
        self.assertTrue(body)
        self.assertEqual(calls[0][1]["params"]["jobAdId"], _ID)

    # ---------- 不许判死：含糊信号一律 unknown ----------

    def test_nonexistent_id_param_error_is_unknown(self):
        """不存在的 id 返 Code=500「参数错误」——通用参数错误文案，我们传错也长这样。"""
        resp = _Resp({"Code": 500, "Message": "参数错误", "Data": None})
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(resp)

    def test_http_404_is_unknown_not_closed(self):
        """接口 404 = 这个 host 上没这个接口（老门户 / 反代），不是岗位撤了。"""
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(None, text="not found", status=404))

    def test_http_5xx_and_429_are_unknown(self):
        for status in (429, 500, 502):
            with self.assertRaises(enrich.DetailUnknownError, msg=status):
                self._run(_Resp(None, text="", status=status))

    def test_non_json_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(None, text="<html>waf</html>"))

    def test_status_2_with_mismatched_id_is_unknown(self):
        """拿到的不是这条岗位自己的记录（Id 对不上）→ 不管 Status 是几都不判。"""
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_payload(status=2, Id="00000000-0000-0000-0000-000000000000")))

    def test_status_2_without_name_is_unknown(self):
        """半截数据：Status=2 但标题空 → 不判死。"""
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_payload(status=2, JobAdName="")))

    def test_status_2_with_non_200_code_is_unknown(self):
        with self.assertRaises(enrich.DetailUnknownError):
            self._run(_Resp(_payload(status=2, code=500)))

    def test_other_status_values_are_unknown(self):
        """前端只对 2 跳「已停止招聘」；其余取值（实测有 7）语义没证实，既不判死也不算在招。"""
        for status in (0, 7, None, "", "x"):
            with self.assertRaises(enrich.DetailUnknownError, msg=status):
                self._run(_Resp(_payload(status=status)))

    def test_legacy_cms_url_without_job_ad_id_is_unknown_and_sends_nothing(self):
        """老版 CMS 门户没有 jobAdId：不能返 ""（那等于「确认在招」、会盖戳挤掉浏览器巡检），
        而且根本不该发请求（Status=2 的假响应也不许让它判死）。"""
        for url in ("https://eic.zhiye.com/zpdetail/230300234",
                    "https://fotile.zhiye.com/job_show?jobId=561114580",
                    "https://x.zhiye.com/social/detail?jobAdId=not-a-uuid",
                    ""):
            calls = []
            with mock.patch.object(enrich.httpx, "get",
                                   lambda *a, **k: calls.append(1) or _Resp(_payload(status=2))):
                with self.assertRaises(enrich.DetailUnknownError, msg=url):
                    enrich._detail_beisen({"jd_url": url}, {})
            self.assertEqual(calls, [], url)


class BeisenSweepOutcomeTest(unittest.TestCase):
    """接到 enrich_backlog 的结果：unknown 必须落 'err'（不盖戳、不改状态），不能落 'alive'。"""

    def _row_result(self, resp):
        import enrich_backlog
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: resp):
            return enrich_backlog.enrich_row(None, dict(_ROW, id="j1"),
                                             {"adapter_name": "beisen"}, dry_run=True)

    def test_closed_goes_expired(self):
        self.assertEqual(self._row_result(_Resp(_payload(status=2))), "expired")

    def test_param_error_goes_err_not_alive(self):
        self.assertEqual(self._row_result(_Resp({"Code": 500, "Message": "参数错误", "Data": None})),
                         "err")

    def test_open_goes_alive(self):
        self.assertEqual(self._row_result(_Resp(_payload(status=1))), "alive")


class BeisenWiringTest(unittest.TestCase):
    def test_registered_as_httpx(self):
        self.assertIs(enrich.ENRICH_REGISTRY["beisen"], enrich._detail_beisen)
        self.assertEqual(enrich.detail_class("beisen"), "httpx")

    def test_in_liveness_sweep_matrix(self):
        workflow = (pathlib.Path(__file__).resolve().parents[1]
                    / ".github" / "workflows" / "liveness-sweep.yml").read_text(encoding="utf-8")
        matrix = workflow.split("adapter: [", 1)[1].split("]", 1)[0]
        listed = {x.strip() for x in matrix.replace("\n", " ").split(",") if x.strip()}
        self.assertIn("beisen", listed)

    def test_legacy_cms_rows_still_covered_by_browser_audit(self):
        """CMS 门户的岗这里判不了，浏览器巡检不能跟着一起撤掉 beisen。"""
        import audit_dead_links
        self.assertIn("beisen", audit_dead_links._BROWSER_ADAPTERS)


class ExpireRatioGuardTest(unittest.TestCase):
    """判死信号的语义是对方平台定的；哪天北森把 Status=2 挪作他用，双条件拦不住。
    撤岗比例熔断是最后一道闸：expired 当天就被 purge 永久删除，不能让一轮 sweep 清空 11 万岗。"""

    def test_pure_function(self):
        import enrich_backlog as eb
        self.assertFalse(eb.should_trip_expire_guard("beisen", 199, 199))   # 样本不够
        self.assertTrue(eb.should_trip_expire_guard("beisen", 200, 100))    # 50% 线上
        self.assertFalse(eb.should_trip_expire_guard("beisen", 200, 99))
        # 2026-09-23 全集模拟首轮排队顺序：累计判死占比最高 15.7%，离线很远
        self.assertFalse(eb.should_trip_expire_guard("beisen", 29593, 4646))
        # 没登记的 adapter 永不熔断（wt/hotjob 列表本来就夹带 52%/71% 已关闭岗）
        self.assertFalse(eb.should_trip_expire_guard("wt", 10000, 9000))
        self.assertNotIn("wt", eb.EXPIRE_RATIO_GUARD)
        self.assertNotIn("hotjob", eb.EXPIRE_RATIO_GUARD)

    def test_drain_stops_expiring_after_guard_trips(self):
        import enrich_backlog as eb
        rows = [{"id": f"j{i}", "source_id": f"s{i % 40}", "jd_url": "u"} for i in range(1000)]
        smap = {f"s{i}": {"adapter_name": "beisen", "company": "某公司",
                          "source_url": f"https://t{i}.zhiye.com/social"} for i in range(40)}
        seen = []

        def fake_row(sb, row, src, dry_run=False, jobs_conn=None):
            seen.append(row["id"])
            return "expired"

        with mock.patch.object(eb, "fetch_liveness_queue", lambda *a, **k: (rows, smap)), \
                mock.patch.object(eb.jobs_db, "enabled", lambda: False), \
                mock.patch.object(eb.must_apply, "patterns", lambda: []), \
                mock.patch.object(eb, "enrich_row", fake_row):
            stat = eb.drain(None, adapter="beisen", workers=1, dry_run=True, sweep=True,
                            make_sb=lambda: None)
        self.assertEqual(stat["expired"], eb.EXPIRE_GUARD_MIN_SAMPLE)
        self.assertEqual(stat["skipped"], 1000 - eb.EXPIRE_GUARD_MIN_SAMPLE)
        self.assertEqual(len(seen), eb.EXPIRE_GUARD_MIN_SAMPLE)


if __name__ == "__main__":
    unittest.main()
