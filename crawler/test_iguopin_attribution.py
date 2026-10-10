"""国聘集团展开的归属核验（张冠李戴红线）。

2026-09-04 线上实锤：南方电网的子公司名单里有「海南电网有限责任公司」，adapter 拿它去
关键词搜，而**国聘的搜索是集团级模糊匹配**，回来的既有真兄弟公司（鼎和财产保险，
名字里没有「南方电网」），也有毫不相干的「中国（海南）改革发展研究院有限责任公司」
「洋浦国际投资咨询有限公司」「海南健康发展研究院」——国聘自己写着它们分别是
民营企业 / 洋浦经济开发区 / 事业单位。旧写法对 `_group_child` 直接放行、跳过核验，
于是这些公司被打上「（南方电网）」入库。

钉死三件事：
① 集团口径（group_id）是权威，名字不是——鼎和保险必须放行；
② 「查到了但没有集团」= 定论，必须拒——这正是旧修法失败的地方（当成「查不到」放行了）；
③ 「请求失败」≠「没有集团」，也 ≠「是本集团」：核不了的行**本轮不写**（下轮重查），不许放行。
   2026-10-10 前这里是「放行」，而国聘公司主页接口实测 4%~40% 回 503 →
   「中国人民解放军空军（中国石油）」「赞比亚…（比亚迪股份有限公司）」就是这么进库的
   （全量复核 609 家：42 家 / 178 岗挂错，其中 39 家是 10-09、10-10 两晚进来的）。
   放行进来的行没有任何机制撤掉：下一轮查成功了只是「不再刷新」，旧行照样挂着。
"""
import unittest
from unittest import mock

import adapters.iguopin as iguopin
from adapters.iguopin import IguopinAdapter, _row_passes_match, reset_process_caches


class _Adapter(IguopinAdapter):
    """把网络调用换成查表，其余逻辑照跑。"""

    def __init__(self, table):
        self._table = table          # company_id -> group_id / "" / None
        self.calls = []

    def _fetch_company_group_id(self, company_id, headers):
        # 只替掉「真发请求」那一层，`_company_group_id` 的三态语义 + 进程级缓存照跑，
        # 这样「同一家只查一次」这条断言覆盖的是真实路径而不是被绕开的桩。
        self.calls.append(company_id)
        return self._table.get(company_id, None)


def _row(cid, name, child=None):
    row = {"company_id": cid, "company_name": name}
    if child:
        row["_group_child"] = child
    return row


GROUP = "10685309282299237"          # 南方电网


class GroupMembershipTest(unittest.TestCase):
    def setUp(self):
        reset_process_caches()
        self.a = _Adapter({
            "c_dinghe": GROUP,       # 鼎和财产保险：真子公司，名字里没有「南方电网」
            "c_inst": "",            # 中国（海南）改革发展研究院：查到了，无集团
            "c_yangpu": "other_grp", # 洋浦国际投资咨询：属于别的集团
            "c_boom": None,          # 接口失败
        })
        self.ok = self.a._group_membership_checker(GROUP, {})

    def test_real_subsidiary_passes_even_though_name_mismatches(self):
        row = _row("c_dinghe", "鼎和财产保险股份有限公司", child="海南电网有限责任公司")
        self.assertTrue(_row_passes_match(row, "南方电网", self.ok),
                        "名字对不上但 group_id 对得上 —— 按名字核会误杀真子公司")

    def test_company_without_group_is_rejected(self):
        row = _row("c_inst", "中国（海南）改革发展研究院有限责任公司", child="海南电网有限责任公司")
        self.assertFalse(_row_passes_match(row, "南方电网", self.ok),
                         "「查到了、但没有集团」是定论，不能当成「查不到」放行")

    def test_company_in_another_group_is_rejected(self):
        row = _row("c_yangpu", "洋浦国际投资咨询有限公司", child="海南电网有限责任公司")
        self.assertFalse(_row_passes_match(row, "南方电网", self.ok))

    def test_lookup_failure_is_not_a_pass(self):
        """核不了 ≠ 核过了。旧口径在这里放行，线上正是从这个口子进来的。"""
        row = _row("c_boom", "中国人民解放军空军", child="中国石油报社")
        self.assertFalse(_row_passes_match(row, "南方电网", self.ok),
                         "查询失败的行不许带着集团名入库")
        self.assertEqual(self.ok.unverified, {"c_boom"}, "核不了的公司要记下来，调用方据此报数 / 熔断")

    def test_lookup_failure_is_asked_once_per_round(self):
        """失败不进进程级缓存（下一条源还会重查），但同一条源的同一轮里不许逐行重问：
        主页接口失败一次要等 10 秒，一家公司 60 个岗逐行重问就是 10 分钟。"""
        for _ in range(5):
            _row_passes_match(_row("c_boom", "某公司"), "南方电网", self.ok)
        self.assertEqual(self.a.calls.count("c_boom"), 1)

    def test_group_verdict_is_cached_per_company(self):
        for _ in range(5):
            _row_passes_match(_row("c_dinghe", "鼎和财产保险股份有限公司"), "南方电网", self.ok)
        self.assertEqual(self.a.calls.count("c_dinghe"), 1, "同一家公司只该查一次")

    def test_group_rule_also_applies_to_direct_keyword_rows(self):
        """有集团口径时对**所有**行生效——直接搜出来的鼎和保险同样是真子公司。"""
        row = _row("c_dinghe", "鼎和财产保险股份有限公司")     # 无 _group_child 标记
        self.assertTrue(_row_passes_match(row, "南方电网", self.ok))
        row2 = _row("c_inst", "中国（海南）改革发展研究院有限责任公司")
        self.assertFalse(_row_passes_match(row2, "南方电网", self.ok))

    def test_without_group_falls_back_to_name_match(self):
        """非集团源（没有 group_id）仍走原来的精准核名，行为不变。"""
        self.assertTrue(_row_passes_match(_row("x", "中通快递股份有限公司"), "中通", None))
        self.assertFalse(_row_passes_match(_row("x", "北京华晋中通电力有限公司"), "中通", None))

    def test_missing_company_id_is_not_a_pass(self):
        """没有 company_id 就没法问国聘它属于谁 —— 同样是「核不了」，同样不许放行。"""
        self.assertFalse(_row_passes_match({"company_name": "某公司"}, "南方电网", self.ok))
        self.assertEqual(self.ok.unverified, {""})

    def test_verdicts_are_not_counted_as_unverified(self):
        _row_passes_match(_row("c_dinghe", "鼎和财产保险股份有限公司"), "南方电网", self.ok)
        _row_passes_match(_row("c_inst", "中国（海南）改革发展研究院有限责任公司"), "南方电网", self.ok)
        self.assertEqual(self.ok.unverified, set(), "「查到了、不属于」是定论，不算核不了")
        self.assertEqual(self.ok.checked, {"c_dinghe", "c_inst"})


class _Resp:
    def __init__(self, payload=None, status_code=200):
        self._payload, self.status_code = payload, status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("not json")       # 503 的响应体不是 JSON
        return self._payload


def _home(cid, group_id, **extra):
    return _Resp({"code": 200, "data": {"company_info": {"id": cid, "group_id": group_id, **extra}}})


def _job(job_id, company_name, company_id):
    return {"job_id": str(job_id), "job_name": f"岗位 {job_id}", "company_id": str(company_id),
            "company_name": company_name, "contents": f"岗位 {job_id} 职责"}


class HomeLookupTest(unittest.TestCase):
    """公司主页接口的三种答复必须分开：定论 / 国聘说没有这家公司 / 暂时问不到。"""

    def setUp(self):
        reset_process_caches()
        sleeper = mock.patch("adapters.iguopin.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_503_is_retried_and_the_answer_is_used(self):
        """2026-10-10 实测：同一家公司 3 并发连打 40 次有 16 次 503，单次失败不能当结论。"""
        answers = [_Resp(status_code=503), _home("c1", "grp")]
        with mock.patch("adapters.iguopin.httpx.get", side_effect=answers) as get:
            self.assertEqual(IguopinAdapter()._fetch_company_group_id("c1", {}), "grp")
        self.assertEqual(get.call_count, 2)

    def test_gives_up_as_unknown_after_bounded_retries(self):
        with mock.patch("adapters.iguopin.httpx.get", return_value=_Resp(status_code=503)) as get:
            self.assertIsNone(IguopinAdapter()._fetch_company_group_id("c1", {}))
        self.assertEqual(get.call_count, iguopin._HOME_TRIES)

    def test_company_not_found_is_a_verdict_not_a_failure(self):
        """code 2204「未找到对应企业或该企业审核不通过或异常」是国聘的明确答复，不是网络抖动。
        旧实现把它和 503 一样当「暂时不知道」放行，而它每晚都是这个答复 →
        「中国科学院遗传与发育生物学研究所农业资源研究中心（中国石油）」从 09-16 挂到 10-10。"""
        not_found = _Resp({"code": 2204, "msg": "未找到对应企业或该企业审核不通过或异常", "data": None})
        with mock.patch("adapters.iguopin.httpx.get", return_value=not_found) as get:
            adapter = IguopinAdapter()
            self.assertEqual(adapter._company_group_id("c1", {}), "", "国聘不认这家公司 = 它没有集团")
            self.assertEqual(adapter._company_group_id("c1", {}), "")
        self.assertEqual(get.call_count, 1, "定论要缓存，也不该重试")


class FetchFailClosedTest(unittest.TestCase):
    """端到端：国聘主页接口失败时，fetch 不许把核不了的公司挂到集团名下。"""

    SOURCE = "https://www.iguopin.com/job?company=中国石油&match=中国石油"
    ROWS = [_job("j1", "中国石油工程建设有限公司天津分公司", "c-cnpc"),
            _job("j2", "大庆油田有限责任公司", "c-daqing"),
            _job("j3", "宝鸡石油机械有限责任公司", "c-baoji"),
            _job("j4", "中国人民解放军空军", "c-plaaf")]

    def setUp(self):
        reset_process_caches()
        sleeper = mock.patch("adapters.iguopin.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.home = {
            "c-cnpc": _home("c-cnpc", "g-cnpc", group_short_name="中国石油",
                            group_name="中国石油天然气集团有限公司"),
            "c-daqing": _home("c-daqing", "g-cnpc"),
            "c-baoji": _home("c-baoji", "g-cnpc"),
            "c-plaaf": _Resp(status_code=503),     # 真相：军事机构、自己是自己的集团；但这一轮问不到
        }
        self.home_calls = []

    def _run(self, rows, adapter=None):
        """self.home: company_id -> 响应（或 Exception）。锚点是 c-cnpc（中国石油集团成员）。"""
        def fake_post(_url, **_kwargs):
            return _Resp({"code": 200, "data": {"total": len(rows), "list": [dict(r) for r in rows]}})

        def fake_get(url, **kwargs):
            if "company/index/v1/home" in url:
                self.home_calls.append(kwargs["params"]["company_id"])
                answer = self.home[kwargs["params"]["company_id"]]
                if isinstance(answer, Exception):
                    raise answer
                return answer
            if "children-list" in url:
                return _Resp({"code": 200, "data": []})
            row = next(r for r in rows if r["job_id"] == kwargs["params"]["id"])
            return _Resp({"code": 200, "data": dict(row)})

        adapter = adapter or IguopinAdapter()
        with mock.patch("adapters.iguopin.httpx.post", side_effect=fake_post), \
             mock.patch("adapters.iguopin.httpx.get", side_effect=fake_get):
            payload = adapter.fetch(self.SOURCE)
        return adapter, [job.company for job in adapter.parse(payload)]

    def test_unverifiable_company_is_not_written_under_the_group(self):
        adapter, companies = self._run(self.ROWS)
        self.assertEqual(companies, ["中国石油工程建设有限公司天津分公司",
                                     "大庆油田有限责任公司（中国石油）",
                                     "宝鸡石油机械有限责任公司（中国石油）"])
        self.assertFalse(adapter.fetch_complete, "有行没核上 = 这一轮没写全，不能记成抓全")
        self.assertEqual(adapter.coverage_stop_reason, "attribution_unverified")

    def test_stop_reason_does_not_leak_into_the_next_source(self):
        """同一个 adapter 实例被复用时（probe、单测；抓取主链是每源新建实例），上一条源的停因不许带到下一条。"""
        adapter, _ = self._run(self.ROWS)
        self.assertEqual(adapter.coverage_stop_reason, "attribution_unverified")
        self.home["c-plaaf"] = _home("c-plaaf", "c-plaaf")       # 下一轮问到了：它是独立机构
        adapter, companies = self._run(self.ROWS, adapter=adapter)
        self.assertIsNone(adapter.coverage_stop_reason)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(len(companies), 3)
        self.assertFalse([c for c in companies if "解放军" in c])

    def test_raises_when_most_companies_cannot_be_verified(self):
        """主页接口整体不可用时：宁可这一轮记 failed（库里一行不动），
        也不许「放行全部」或「安静地写 0 条还报 success」。"""
        rows = [self.ROWS[0], self.ROWS[3], _job("j5", "国家电投集团五凌电力有限公司", "c-wuling")]
        self.home["c-plaaf"] = RuntimeError("connect timeout")
        self.home["c-wuling"] = _Resp(status_code=503)
        with self.assertRaises(RuntimeError) as ctx:
            self._run(rows)
        self.assertIn("归属", str(ctx.exception))

    def test_companies_already_known_do_not_skew_the_abort_ratio(self):
        """预热只问进程级缓存里没有的公司。同集团的第二条源（校招源）里三家成员都缓存过，只剩上一轮
        没问到的那一家 —— 按「这次问的里面有多少问不到」算是 1/1，整源 failed，三家真子公司当晚不刷新。
        比例必须在全体公司上算（独立审查挑出来的，第一版就是这么错的）。"""
        self._run(self.ROWS)
        adapter, companies = self._run(self.ROWS)       # 进程级缓存没清：只有空军还要问，仍然问不到
        self.assertEqual(len(companies), 3)
        self.assertEqual(adapter.coverage_stop_reason, "attribution_unverified")

    def test_incomplete_pagination_is_not_relabelled_as_an_attribution_gap(self):
        """列表本来就没翻完的轮次保持原状：停因改成「归属没核上」的话，
        ops_watchdog 规则 G 会把这个真缺口从榜上摘走。"""
        adapter = IguopinAdapter()
        adapter.fetch_complete, adapter.coverage_stop_reason = False, None
        gate = adapter._group_membership_checker("g-cnpc", {})
        gate._verdicts.update({"a": True, "b": True, "c": False, "d": None})
        adapter._account_unverified(gate, "中国石油")
        self.assertIsNone(adapter.coverage_stop_reason)

    def test_stops_asking_early_when_the_home_api_is_down(self):
        """接口大面积失败时每家要白等 3×10 秒。一条源两三百家全问完才放弃就是几十分钟，
        而国聘四十多条源同主机一队串行跑在同一个分片里（分片 180 分钟被杀会饿死排在后面的源）。"""
        strangers = [_job(f"s{i}", f"无关公司 {i}", f"c-x{i}") for i in range(90)]
        for row in strangers:
            self.home[row["company_id"]] = _Resp(status_code=503)
        with self.assertRaises(RuntimeError):
            self._run([self.ROWS[0]] + strangers)
        asked = {cid for cid in self.home_calls if cid.startswith("c-x")}
        self.assertEqual(len(asked), iguopin._PREFETCH_CHUNK, "第一批就该看出接口不可用，不该把 90 家问完")


if __name__ == "__main__":
    unittest.main()
