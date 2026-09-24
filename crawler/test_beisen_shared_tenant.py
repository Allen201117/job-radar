"""一个北森租户挂着多家公司时，按岗位自报的招聘机构（Org）归属（不打真网络）。

病例（2026-09-23 live）：chinalife.zhiye.com 同时发中国人寿与广发银行的岗，列表接口一次返回整个租户，
旧代码每条都贴 sources.company → 466 个广发银行在招岗挂成「中国人寿」。
事实来源与取舍见 adapters/china_ats.py 的 _BEISEN_SHARED_TENANTS 注释。
"""
import json
import unittest
from unittest import mock

import normalizer
from adapters import china_ats
from adapters.china_ats import BeisenAdapter, beisen_hiring_entity, beisen_shared_tenant_owner

SHARED = "chinalife.zhiye.com"
ROUTE = "https://chinalife.zhiye.com/custom/zwxq"


def _row(uid, title, org=None, c2=None, **extra):
    r = {"Id": uid, "JobAdName": title, "Duty": "职责" * 40, "Require": "要求", "Category": "校园招聘"}
    if org is not None:
        r["Org"] = org
    if c2 is not None:
        r["ClassificationTwo"] = c2
    r.update(extra)
    return r


def _adapter(host=SHARED):
    a = BeisenAdapter()
    a._host = host
    a._detail_route = f"https://{host}/custom/zwxq"
    return a


def _payload(rows):
    return json.dumps({"_intercepted": [{"Data": rows, "Count": len(rows)}]}, ensure_ascii=False)


class OwnerRuleTest(unittest.TestCase):
    def test_bank_branches_and_wealth_subsidiary_go_to_cgb(self):
        for org in ("广发银行江门分行", "广发银行总行", "广发银行信用卡中心", "广银理财有限责任公司"):
            self.assertEqual(beisen_shared_tenant_owner(SHARED, org), "广发银行", org)

    def test_china_life_entities_keep_source_company(self):
        for org in ("寿险重庆分公司", "财险黑龙江分公司", "中国人寿保险（集团）公司", "国寿安保基金管理有限公司", ""):
            self.assertIsNone(beisen_shared_tenant_owner(SHARED, org), org)

    def test_prefix_not_substring(self):
        """本家机构名里夹着别家名字不算别家（用前缀不用子串）。"""
        self.assertIsNone(beisen_shared_tenant_owner(SHARED, "中国人寿驻广发银行联络处"))

    def test_unregistered_host_is_untouched(self):
        self.assertIsNone(beisen_shared_tenant_owner("boe.zhiye.com", "广发银行总行"))
        self.assertIsNone(beisen_shared_tenant_owner("", "广发银行总行"))

    def test_entity_prefers_org_then_classification_two(self):
        self.assertEqual(beisen_hiring_entity({"Org": "广发银行总行", "ClassificationTwo": "中国人寿保险（集团）公司"}),
                         "广发银行总行")   # 实测冲突例：Org 对
        self.assertEqual(beisen_hiring_entity({"Org": "", "ClassificationTwo": "中国人寿保险（海外）股份有限公司"}),
                         "中国人寿保险（海外）股份有限公司")
        self.assertEqual(beisen_hiring_entity({"Org": None}), "")
        self.assertEqual(beisen_hiring_entity(None), "")


class MapTest(unittest.TestCase):
    def test_map_sets_company_per_row(self):
        a = _adapter()
        jobs = a.parse(_payload([
            _row("u1", "支行公司金融方向暑期实习生（中山）", org="广发银行中山分行"),
            _row("u2", "精算分析岗", org="中国人寿保险（集团）公司"),
            _row("u3", "核保管理岗", org="", c2="中国人寿保险（海外）股份有限公司"),
            _row("u4", "香港分行副行长级", org="广发银行总行", c2="中国人寿保险（集团）公司"),
            _row("u5", "投资经理", org="", c2="广银理财有限责任公司"),
        ]))
        by_title = {j.title: j.company for j in jobs}
        self.assertEqual(by_title["支行公司金融方向暑期实习生（中山）"], "广发银行")
        self.assertEqual(by_title["精算分析岗"], "")            # 空 = normalize 用 sources.company 兜底
        self.assertEqual(by_title["核保管理岗"], "")
        self.assertEqual(by_title["香港分行副行长级"], "广发银行")
        self.assertEqual(by_title["投资经理"], "广发银行")
        self.assertEqual({j.jd_url for j in jobs if j.title == "精算分析岗"}, {f"{ROUTE}?jobAdId=u2"})

    def test_normalize_keeps_row_company_over_source_company(self):
        a = _adapter()
        jobs = a.parse(_payload([_row("u1", "一级分行副行长级", org="广发银行西安分行"),
                                 _row("u2", "理赔岗", org="财险上海分公司")]))
        out = {j.title: normalizer.normalize(j, source_id="s", company="中国人寿")["company"] for j in jobs}
        self.assertEqual(out, {"一级分行副行长级": "广发银行", "理赔岗": "中国人寿"})

    def test_non_shared_tenant_ignores_org(self):
        a = _adapter("boe.zhiye.com")
        jobs = a.parse(_payload([_row("u1", "工艺工程师", org="广发银行总行")]))
        self.assertEqual(jobs[0].company, "")


class GuardTest(unittest.TestCase):
    def test_all_rows_without_entity_is_failure_not_silent_fallback(self):
        a = _adapter()
        with self.assertRaises(RuntimeError):
            a.parse(_payload([_row("u1", "柜面经理"), _row("u2", "理赔岗")]))

    def test_some_rows_without_entity_fall_back(self):
        a = _adapter()
        jobs = a.parse(_payload([_row("u1", "柜面经理", org="广发银行江门分行"), _row("u2", "理赔岗")]))
        self.assertEqual({j.title: j.company for j in jobs}, {"柜面经理": "广发银行", "理赔岗": ""})

    def test_non_shared_tenant_without_entity_is_fine(self):
        a = _adapter("boe.zhiye.com")
        self.assertEqual(len(a.parse(_payload([_row("u1", "工艺工程师")]))), 1)

    def test_shared_tenant_ssr_path_is_refused(self):
        a = _adapter()
        html = json.dumps({"_ssr_jobs": [{"jd_url": f"{ROUTE}?jobId=1", "title": "柜面经理"}]}, ensure_ascii=False)
        with self.assertRaises(RuntimeError):
            a.parse(html)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _Client:
    def __init__(self):
        self.bodies = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return type("R", (), {"text": '{"PortalId":"fe9a4897-6c7b-4ebd-904b-da4f88b13020"}'})()

    def post(self, url, json=None, headers=None):
        self.bodies.append(json)
        return _Resp({"Count": 1, "Data": [{"Id": "u1", "JobAdName": "柜面经理", "Org": "广发银行江门分行"}]})


class RequestBodyTest(unittest.TestCase):
    def _fields(self, url):
        cli = _Client()
        with mock.patch.object(china_ats.httpx, "Client", lambda **kw: cli):
            BeisenAdapter()._httpx_fetch(url)
        return cli.bodies[0]["DisplayFields"]

    def test_shared_tenant_asks_for_entity_columns(self):
        fields = self._fields("https://chinalife.zhiye.com/custom/intern")
        self.assertIn("Org", fields)
        self.assertIn("ClassificationTwo", fields)

    def test_other_tenants_request_body_unchanged(self):
        self.assertEqual(self._fields("https://boe.zhiye.com/social"),
                         ["Category", "Kind", "LocId", "PostDate", "WorkWeChatQrCode"])


class _HostClient:
    """按主机回不同列表：siic = 母集团门户，sph = 子公司门户。sph_ok=False 模拟子公司门户拉不到。"""
    LISTS = {
        "siic.zhiye.com": [{"Id": "s1", "JobAdName": "上海医药2027技术工培生(J12541)"},
                           {"Id": "s2", "JobAdName": "公用工程技术员(J12679)"},
                           {"Id": "s3", "JobAdName": "疗养院护士(J13001)"}],
        "sph.zhiye.com": [{"Id": "p1", "JobAdName": "上海医药2027技术工培生(J12541)"},
                          {"Id": "p2", "JobAdName": "公用工程技术员(J12679)"},
                          {"Id": "p3", "JobAdName": "中药研究员(J12413)"}],
    }

    def __init__(self, sph_ok=True):
        self.sph_ok = sph_ok

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return type("R", (), {"text": '{"PortalId":"fe9a4897-6c7b-4ebd-904b-da4f88b13020"}'})()

    def post(self, url, json=None, headers=None):
        host = url.split("/")[2]
        if host == "sph.zhiye.com" and not self.sph_ok:
            raise ConnectionError("sph down")
        rows = self.LISTS[host]
        return _Resp({"Count": len(rows), "Data": rows})


class TwinPortalTest(unittest.TestCase):
    def _fetch(self, url, **kw):
        a = BeisenAdapter()
        with mock.patch.object(china_ats.httpx, "Client", lambda **k: _HostClient(**kw)), \
                mock.patch.object(china_ats.time, "sleep", lambda *_: None):
            out = a._httpx_fetch(url)
        return a, out

    def test_parent_portal_drops_rows_the_subsidiary_portal_also_lists(self):
        a, out = self._fetch("https://siic.zhiye.com/campus/jobs")
        titles = [r["JobAdName"] for r in json.loads(out)["_intercepted"][0]["Data"]]
        self.assertEqual(titles, ["疗养院护士(J13001)"])
        self.assertTrue(a.fetch_complete)      # 剔掉的是别处入库的岗，不是漏抓 → 不许报「没抓全」
        self.assertEqual(a.reported_total, 3)

    def test_subsidiary_portal_unreachable_is_failure_not_silent_double_ingest(self):
        _a, out = self._fetch("https://siic.zhiye.com/campus/jobs", sph_ok=False)
        self.assertIsNone(out)

    def test_subsidiary_portal_itself_is_untouched(self):
        _a, out = self._fetch("https://sph.zhiye.com/campus")
        self.assertEqual(len(json.loads(out)["_intercepted"][0]["Data"]), 3)


if __name__ == "__main__":
    unittest.main()
