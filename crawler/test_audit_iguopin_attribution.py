"""国聘存量归属复核工具的判据。夹具里的公司名与集团关系取自 2026-10-10 国聘的真实答复（部分 id 是占位）。

这个工具会把在招岗标成 removed，所以两个方向都要钉死：
  · 该判错的必须判错（漏判 = 张冠李戴继续挂着）；
  · 拿不准的一律「查不到」（误判 = 把真岗撤掉）。
"""
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import audit_iguopin_attribution as audit
from audit_iguopin_attribution import judge, label_of

CNPC = "10685317164949722"      # 中国石油
CSCEC = "g-cscec"               # 中国建筑
CCTEG = "10685382754151861"     # 中国煤科


def _member(name, group_id, short, full):
    return {"name": name, "group_id": group_id, "standalone": False, "group_names": [short, full]}


def _standalone(name, own_id, short=""):
    return {"name": name, "group_id": own_id, "standalone": True, "group_names": [n for n in (short, name) if n]}


class LabelTest(unittest.TestCase):
    def test_label_is_what_we_appended_to_the_iguopin_name(self):
        self.assertEqual(label_of("大庆油田有限责任公司（中国石油）", "大庆油田有限责任公司"), "中国石油")

    def test_brackets_inside_the_company_own_name_are_not_a_label(self):
        """按「最后一个括号」拆会把公司自己名字里的括号当成集团标签。"""
        own = "中煤科工集团上海研究院有限公司（中煤科工上海有限公司）"
        self.assertIsNone(label_of(own, own))
        self.assertEqual(label_of(own + "（中国建筑）", own), "中国建筑")

    def test_name_that_does_not_start_with_the_iguopin_name_has_no_label(self):
        self.assertIsNone(label_of("别的公司（中国石油）", "大庆油田有限责任公司"))


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.facts = {
            # 真成员：给「中国石油」「中国建筑」这两个标签各提供一个可认的 group_id
            "大庆油田有限责任公司（中国石油）":
                _member("大庆油田有限责任公司", CNPC, "中国石油", "中国石油天然气集团有限公司"),
            "中国建筑西南勘察设计研究院有限公司":
                _member("中国建筑西南勘察设计研究院有限公司", CSCEC, "中国建筑", "中国建筑集团有限公司"),
        }

    def _judge(self, **extra):
        self.facts.update(extra)
        return judge({name: 1 for name in self.facts}, self.facts)

    def test_real_member_is_right_and_unlabeled_rows_are_out_of_scope(self):
        verdicts = self._judge()
        self.assertEqual(verdicts["大庆油田有限责任公司（中国石油）"][0], "right")
        self.assertEqual(verdicts["中国建筑西南勘察设计研究院有限公司"][0], "unlabeled")

    def test_standalone_unit_under_a_group_label_is_wrong(self):
        """用户报的第一行：解放军空军在国聘是军事机构、自己就是自己的集团。"""
        name = "中国人民解放军空军（中国石油）"
        verdicts = self._judge(**{name: _standalone("中国人民解放军空军", "141193342678470539")})
        self.assertEqual(verdicts[name][0], "wrong")

    def test_member_of_another_group_is_wrong_even_with_brackets_in_its_name(self):
        """用户报的第二行：中煤科工属于中国煤科，名字里自带一对括号。"""
        own = "中煤科工集团上海研究院有限公司（中煤科工上海有限公司）"
        name = own + "（中国建筑）"
        verdicts = self._judge(**{name: _member(own, CCTEG, "中国煤科", "中国煤炭科工集团有限公司")})
        self.assertEqual(verdicts[name][0], "wrong")
        self.assertIn("中国煤科", verdicts[name][1])

    def test_lookup_failure_is_never_a_wrong_verdict(self):
        name = "某公司（中国石油）"
        self.assertEqual(self._judge(**{name: None})[name][0], "unknown")

    def test_label_nobody_reports_today_is_unknown_not_wrong(self):
        """「国聘知行派」：这两家今天自报的集团是国投集团，全库没有任何公司再自报这个简称。
        旧工具按名字比，把它们判成了错 —— 集团改个简称，整个集团的岗就会被一起撤掉。"""
        name = "北京知行派教育科技有限公司（国聘知行派）"
        fact = _member("北京知行派教育科技有限公司", "g-sdic", "国投集团", "国家开发投资集团有限公司")
        self.assertEqual(self._judge(**{name: fact})[name][0], "unknown")

    def test_two_group_ids_sharing_one_short_name_are_both_right(self):
        """国聘上「中国能建」是两个集团实体（集团公司 / 股份公司），简称相同、group_id 不同。"""
        a, b = "甲公司（中国能建）", "乙公司（中国能建）"
        verdicts = self._judge(**{
            a: _member("甲公司", "g-ceec-group", "中国能建", "中国能源建设集团有限公司"),
            b: _member("乙公司", "g-ceec-ltd", "中国能建", "中国能源建设股份有限公司"),
        })
        self.assertEqual((verdicts[a][0], verdicts[b][0]), ("right", "right"))

    def test_group_itself_carrying_its_own_short_name_is_right(self):
        name = "中国远洋海运集团有限公司（中远海运集团）"
        fact = _standalone("中国远洋海运集团有限公司", "g-cosco", short="中远海运集团")
        self.assertEqual(self._judge(**{name: fact})[name][0], "right")

    def test_iguopin_renamed_company_is_unknown(self):
        """库里的实体名和国聘今天的公司名对不上：拆不出标签，不判。"""
        name = "旧名字有限公司（中国石油）"
        fact = _standalone("新名字有限公司", "c-new")
        self.assertEqual(self._judge(**{name: fact})[name][0], "unknown")


class FetchFactTest(unittest.TestCase):
    """问国聘的那一步：问不到必须是 None，不能编一个结论出来。"""

    def setUp(self):
        sleeper = mock.patch("audit_iguopin_attribution.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    class _Resp:
        def __init__(self, payload=None, status_code=200):
            self._payload, self.status_code = payload, status_code

        def json(self):
            if self._payload is None:
                raise ValueError("not json")
            return self._payload

    def _client(self, answers):
        client = mock.Mock()
        client.get.side_effect = answers
        return client

    def test_detail_503_is_retried_then_gives_up_as_unknown(self):
        client = self._client([self._Resp(status_code=503)] * audit._TRIES)
        self.assertIsNone(audit.fetch_fact(["j1", "j2"], client, mock.Mock()))
        self.assertEqual(client.get.call_count, audit._TRIES, "接口失败不该换下一个岗去碰运气")

    def test_offline_sample_job_falls_through_to_the_next_one(self):
        gone = self._Resp({"code": 2001, "msg": "数据不存在。", "data": None})     # 国聘对不存在的岗的原样答复
        live = self._Resp({"code": 200, "data": {"company_id": "c1", "company_name": "大庆油田有限责任公司"}})
        adapter = mock.Mock()
        adapter._company_home.return_value = {"id": "c1", "group_id": CNPC, "group_short_name": "中国石油",
                                              "group_name": "中国石油天然气集团有限公司"}
        fact = audit.fetch_fact(["j1", "j2"], self._client([gone, live]), adapter)
        self.assertEqual(fact["name"], "大庆油田有限责任公司")
        self.assertEqual(fact["group_id"], CNPC)
        self.assertFalse(fact["standalone"])
        self.assertEqual(fact["group_names"], ["中国石油", "中国石油天然气集团有限公司"])

    def test_company_iguopin_does_not_recognise_is_unknown_for_cleanup(self):
        """code 2204：抓取端当「拒」，清存量端当「查不到」—— 撤岗要的是「国聘说它属于别人」的正面证据。"""
        live = self._Resp({"code": 200, "data": {"company_id": "c1", "company_name": "某研究所"}})
        adapter = mock.Mock()
        adapter._company_home.return_value = {}
        fact = audit.fetch_fact(["j1"], self._client([live]), adapter)
        self.assertTrue(fact["not_found"])
        name = "某研究所（中国石油）"
        verdict, note = judge({name: 2}, {name: fact})[name]
        self.assertEqual(verdict, "unknown")
        self.assertIn("没有这家公司", note)

    def test_home_lookup_failure_is_unknown(self):
        live = self._Resp({"code": 200, "data": {"company_id": "c1", "company_name": "某公司"}})
        adapter = mock.Mock()
        adapter._company_home.side_effect = RuntimeError("HTTP 503")
        self.assertIsNone(audit.fetch_fact(["j1"], self._client([live]), adapter))

    def test_standalone_company_reports_itself_as_its_group(self):
        live = self._Resp({"code": 200, "data": {"company_id": "c-plaaf", "company_name": "中国人民解放军空军"}})
        adapter = mock.Mock()
        adapter._company_home.return_value = {"id": "c-plaaf", "name": "中国人民解放军空军", "short_name": "",
                                              "group_id": "c-plaaf", "group_name": "中国人民解放军空军",
                                              "group_short_name": "", "classify_cn": "军事机构"}
        fact = audit.fetch_fact(["j1"], self._client([live]), adapter)
        self.assertTrue(fact["standalone"])
        self.assertEqual(fact["group_names"], ["中国人民解放军空军"])


class ConfirmRowsTest(unittest.TestCase):
    """写库前逐行再核：判据是每家抽一个岗得出的，要动的却是这家名下的每一行。"""

    def setUp(self):
        sleeper = mock.patch("audit_iguopin_attribution.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_only_rows_published_by_the_judged_company_are_touched(self):
        name = "中国人民解放军空军（中国石油）"
        facts = {name: {"company_id": "c-plaaf"}}
        rows = [("row-ok", name, "j-ok"), ("row-other", name, "j-other"), ("row-gone", name, "j-gone"),
                ("row-down", name, "j-down"), ("row-noid", name, None)]
        resp = FetchFactTest._Resp
        answers = {
            "j-ok": resp({"code": 200, "data": {"company_id": "c-plaaf", "company_name": "中国人民解放军空军"}}),
            "j-other": resp({"code": 200, "data": {"company_id": "c-someone-else", "company_name": "同名的另一家"}}),
            "j-gone": resp({"code": 2001, "msg": "数据不存在。", "data": None}),
            "j-down": resp(status_code=503),
        }
        client = mock.Mock()
        client.get.side_effect = lambda _url, params: answers[params["id"]]
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(audit.confirm_rows(rows, facts, client, pool), ["row-ok"])


if __name__ == "__main__":
    unittest.main()
