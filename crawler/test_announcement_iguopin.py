"""国聘公告接入的回归（用例来自 2026-09-18 / 2026-10-10 接口实测数据）。不打网络。"""
import unittest
from datetime import date

from announcements import iguopin
from announcements.iguopin import (
    _audience, _employer_type, _mentions_place, _province_of, _region, _BANNED_HOSTS,
)


class TestRegionAttribution(unittest.TestCase):
    """⚠️ 归属准确性高于一切：宁可写「未知」，不可写错的地区。"""

    def test_trusts_district_when_title_agrees(self):
        self.assertEqual(_region({
            "districts_cn": ["唐山"], "districts": ["000000.130000.130200"],
            "title": "唐山工业职业技术大学关于2026年选聘高层次人才的公告",
        }), "河北省")

    def test_province_name_also_counts(self):
        # 市名（济南）不在标题里，但省名「山东」在 → 采信，落到省级
        self.assertEqual(_region({
            "districts_cn": ["济南"], "districts": ["000000.370000.370100"],
            "title": "山东大学财务部非事业编制人员招聘公告",
        }), "山东省")

    def test_rejects_iguopin_geocoding_errors(self):
        """国聘按名字自动地理编码，实测会错。对不上就写未知。"""
        # 福州市鼓楼区 → 被编码成开封鼓楼区（两地都有鼓楼区）
        self.assertIsNone(_region({
            "districts_cn": ["开封"], "districts": ["000000.410000.410200.410204"],
            "title": "福州市鼓楼区国有资产投资发展集团有限公司2026年公开招聘公告",
        }))
        # 贵州锦丰矿业 → 被编码成江苏丰县（匹配上了「锦丰」）
        self.assertIsNone(_region({
            "districts_cn": ["徐州"], "districts": ["000000.320000.320300.320321"],
            "title": "贵州锦丰矿业有限公司招聘公告", "main_company_name": "贵州锦丰矿业有限公司",
        }))

    def test_substring_collision_is_not_a_match(self):
        """⚠️ 回归：「五**大连**池」不是大连。裸子串会把一条黑龙江的公告判成辽宁省。"""
        self.assertIsNone(_region({
            "districts_cn": ["大连"], "districts": ["000000.210000.210200"],
            "title": "五大连池风景区教育幼儿园关于招聘5名公益性岗位的公告",
        }))
        self.assertFalse(_mentions_place("五大连池风景区", "大连"))
        self.assertTrue(_mentions_place("大连理工大学招聘", "大连"))
        self.assertTrue(_mentions_place("中化学数科（北京）电子商务", "北京"), "括号后也算词首")

    def test_multi_or_nationwide_is_quanguo(self):
        self.assertEqual(_region({"districts_cn": ["全国"], "districts": []}), "全国")
        self.assertEqual(_region({"districts_cn": ["天津", "大连", "哈尔滨"], "districts": []}), "全国")
        self.assertIsNone(_region({"districts_cn": [], "districts": []}))

    def test_province_code_lookup(self):
        self.assertEqual(_province_of("000000.320000.320300.320321"), "江苏省")
        self.assertIsNone(_province_of(""))
        self.assertIsNone(_province_of(None))


class TestAudience(unittest.TestCase):
    """⚠️ 国聘自己的标签不可信：81/100 打着「校招」，含明显的社招。以标题为准。"""

    def test_society_open_plus_grad_year_is_both(self):
        self.assertEqual(_audience({
            "title": "赣州旅游投资集团2026年社会公开招聘公告",
            "announcement_tags": [{"label": "校招"}], "graduation_years_cn": ["2026"],
        }), "both", "标题说「社会公开招聘」+ 国聘给了 2026 届 —— 两个信号都真，答案是两者皆可")

    def test_no_graduation_requirement_is_not_a_fresh_signal(self):
        """⚠️ `graduation_years_cn` 常填「无毕业年份要求」——意思恰恰相反，不能当应届信号。"""
        self.assertEqual(_audience({
            "title": "某某公司招聘公告", "graduation_years_cn": ["无毕业年份要求"],
            "announcement_tags": [{"label": "校招"}],
        }), "unknown")

    def test_real_graduation_year_is_a_fresh_signal(self):
        self.assertEqual(_audience({
            "title": "某某公司招聘公告", "graduation_years_cn": ["2027"],
        }), "fresh_grad")

    def test_campus_title(self):
        self.assertEqual(_audience({"title": "中国五矿2027校园招聘"}), "fresh_grad")


class TestEmployerType(unittest.TestCase):
    def test_uses_iguopin_category_for_companies(self):
        self.assertEqual(_employer_type({"category_cn": ["中央企业"], "title": "中国五矿2027校园招聘"}), "央企")
        self.assertEqual(_employer_type({"category_cn": ["央企子公司"], "title": "龙源电力校园招聘"}), "央企")
        self.assertEqual(_employer_type({"category_cn": ["地方国企"], "title": "某国资集团招聘"}), "地方国企")

    def test_falls_back_to_title_for_non_company_categories(self):
        # 事业单位 / 教师 / 医疗 交回标题判，与各省人社厅那批同口径
        self.assertEqual(_employer_type({"category_cn": ["教师"], "title": "某某大学招聘公告"}), "高校")
        self.assertEqual(_employer_type({"category_cn": ["医疗"], "title": "某某医院招聘公告"}), "医疗卫生")


class TestBannedHosts(unittest.TestCase):
    def test_third_party_platforms_are_red_line(self):
        for host in ("zhaopin.com", "chinahr.com", "51job.com", "zhipin.com", "liepin.com"):
            self.assertIn(host, _BANNED_HOSTS)


# ── 2026-10-10：列表接口没有翻页、硬顶 100 条；默认列表 = 置顶 + 即将截止 ─────────────────────
# 下面的假接口按「请求体」回条目，不打网络。形状取自当天实测的真实响应。

def _item(i, status, cat="11q4iQX", cat_cn="事业单位", **over):
    base = {
        "announcement_id": f"a{i}", "title": f"某单位{i}公开招聘公告", "apply_status": status,
        "category_code": [cat], "category_cn": [cat_cn],
        "apply_url": f"https://hr.example.cn/notice/{i}",
        "apply_start_time": "2026-10-01 00:00:00", "apply_end_time": "2026-10-30 00:00:00",
        "apply_time": "2026/10/30", "districts": [], "districts_cn": [],
    }
    base.update(over)
    return base


class _FakeApi:
    """按 (状态, 分类) 回条目；记下每次请求体。`cells[(status, code)]` 是该格的全部条目。"""

    def __init__(self, cells, fail_at=None, error=None):
        self.cells, self.calls, self.fail_at, self.error = cells, [], fail_at, error

    def __call__(self, body):
        self.calls.append(body)
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise self.error
        status = body["apply_status"][0]
        codes = body.get("category_codes")
        if codes:
            pool = self.cells.get((status, codes[0]), [])
        else:
            pool = [it for (s, _c), items in self.cells.items() if s == status for it in items]
        return pool[:iguopin._LIST_CAP]      # 接口硬顶：最多回 100 条


def _collect(api, **kw):
    return iguopin.collect_in_window(api, pause=0, **kw)


class TestCollectInWindow(unittest.TestCase):
    """接口一次最多回 100 条且不能翻页 → 必须按 状态 × 分类 切片，而不是只取默认列表。"""

    def test_never_sends_paging_fields_and_filters_by_status(self):
        api = _FakeApi({(1, "11q4iQX"): [_item(i, 1) for i in range(3)]})
        _collect(api)
        for body in api.calls:
            self.assertNotIn("page", body, "page / page_size 服务端根本不读：三页实测是同一批")
            self.assertIn(body["apply_status"][0], (1, 2), "只取在报名期的两档；不带状态 = 置顶 + 即将截止")

    def test_status_under_cap_needs_no_slicing(self):
        api = _FakeApi({(1, "11q4iQX"): [_item(i, 1) for i in range(40)],
                        (2, "11q4iQX"): [_item(100 + i, 2) for i in range(7)]})
        items, stats = _collect(api)
        self.assertEqual(len(api.calls), 2, "两档状态都不满 100 → 已经取全，不必再按分类切")
        self.assertEqual(len(items), 47)
        self.assertEqual(stats["capped_cells"], [])

    def test_capped_status_is_sliced_by_category_and_long_window_is_not_starved(self):
        """回归本体：正在报名（还有时间的）有 150+60 条，只取默认列表一条都拿不全。"""
        cells = {
            (1, "11q4iQX"): [_item(i, 1) for i in range(150)],                               # 事业单位：撞上限
            (1, "1122Rdki"): [_item(1000 + i, 1, "1122Rdki", "中央企业") for i in range(60)],  # 央企：能取全
            (2, "11q4iQX"): [_item(2000 + i, 2) for i in range(30)],
        }
        api = _FakeApi(cells)
        items, stats = _collect(api)
        got = {it["announcement_id"] for it in items}
        self.assertTrue({f"a{1000 + i}" for i in range(60)} <= got, "没撞上限的分类必须一条不落")
        self.assertEqual(sum(1 for it in items if it["apply_status"] == 1), 160, "事业单位 100（上限）+ 央企 60")
        self.assertEqual(stats["capped_cells"], ["正在报名|事业单位"], "回满 100 的格子要如实上报：它没取全")
        self.assertEqual(stats["by_status"], {"正在报名": 160, "即将截止": 30})
        # 状态 2 整体不满 100 → 不为它再打分类请求
        self.assertFalse([b for b in api.calls if b["apply_status"] == [2] and "category_codes" in b])

    def test_unknown_category_code_is_discovered_and_queried(self):
        """国聘新增一个分类：条目自带的码不在表里 → 当场补查，别静默漏掉一整类。"""
        # 新分类排在前面 → 它的条目出现在「只按状态查」的那 100 条里，才发现得了它
        api = _FakeApi({(1, "11NEWcat"): [_item(5000 + i, 1, "11NEWcat", "新分类") for i in range(120)],
                        (1, "11q4iQX"): [_item(i, 1) for i in range(100)]})
        _items, stats = _collect(api)
        self.assertIn("11NEWcat=新分类", stats["new_category_codes"])
        self.assertIn({"apply_status": [1], "category_codes": ["11NEWcat"]}, api.calls)
        self.assertIn("正在报名|新分类", stats["capped_cells"])

    def test_first_request_failure_is_loud(self):
        """第一次请求就被拒 = 签名坏了 / 接口变了 → 必须抛出，不许带着 0 条安静收工。"""
        api = _FakeApi({}, fail_at=1, error=iguopin.IguopinApiError("/list", 401, "签名错误"))
        with self.assertRaises(iguopin.IguopinApiError):
            _collect(api)

    def test_mid_run_rejection_keeps_what_was_fetched(self):
        """实测：连续打到约第 200 次，接口回 HTTP 200 + 业务码 403。带着已取到的收工，并留下痕迹。"""
        cells = {(1, code): [_item(f"{code}-{i}", 1, code, name) for i in range(100)]
                 for code, name in iguopin._CATEGORY_CODES.items()}
        api = _FakeApi(cells, fail_at=5, error=iguopin.IguopinApiError("/list", 403, "账号类型错误或权限不足"))
        items, stats = _collect(api)
        self.assertTrue(stats["api_rejected"])
        self.assertEqual(stats["api_error_code"], 403)
        self.assertEqual(len(api.calls), 5, "被拒之后不再继续打")
        self.assertGreater(len(items), 100, "已经取到的不能丢")

    def test_request_budget_is_a_hard_stop(self):
        cells = {(s, code): [_item(f"{s}{code}-{i}", s, code, name) for i in range(100)]
                 for s in (1, 2) for code, name in iguopin._CATEGORY_CODES.items()}
        api = _FakeApi(cells)
        _items, stats = _collect(api, max_requests=6)
        self.assertEqual(len(api.calls), 6)
        self.assertTrue(stats["budget_exhausted"])

    def test_long_window_status_goes_first(self):
        """预算不够 / 中途被拒时先保住「还有时间报」的那一档：分类请求先打完正在报名，才轮到即将截止。"""
        cells = {(s, code): [_item(f"{s}{code}-{i}", s, code, name) for i in range(100)]
                 for s in (1, 2) for code, name in iguopin._CATEGORY_CODES.items()}
        api = _FakeApi(cells)
        _collect(api, max_requests=2 + 5)
        self.assertEqual(api.calls[0], {"apply_status": [1]})
        sliced = [b["apply_status"] for b in api.calls if "category_codes" in b]
        self.assertEqual(sliced, [[1]] * 5, "预算只够 5 格时，这 5 格必须全给正在报名")

    def test_non_json_body_mid_run_does_not_lose_the_round(self):
        """限流前后对方可能回网关页（HTTP 200 但不是 JSON）。_call 把它归成 IguopinApiError，
        中途遇到才能带着已取到的收工，而不是一个 ValueError 冒出去把上千条全丢掉。"""
        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                if isinstance(self._payload, Exception):
                    raise self._payload
                return self._payload

        class _Client:
            def __init__(self, payload):
                self.payload = payload

            def post(self, *_a, **_k):
                return _Resp(self.payload)

        for bad in (ValueError("Expecting value"), ["not", "a", "dict"], None):
            with self.assertRaises(iguopin.IguopinApiError) as ctx:
                iguopin._call(_Client(bad), iguopin._LIST_PATH, {})
            self.assertEqual(ctx.exception.code, "bad_body")
        self.assertEqual(iguopin._call(_Client({"code": 200, "data": None}), iguopin._LIST_PATH, {}), {})
        self.assertEqual(iguopin._call(_Client({"code": 200, "data": {"list": [1]}}), iguopin._LIST_PATH, {}), {"list": [1]})

    def test_incomplete_round_is_not_reported_as_success(self):
        base = {"request_errors": 0, "api_rejected": False, "budget_exhausted": False}
        self.assertEqual(iguopin._incomplete(base), 0)
        self.assertEqual(iguopin._incomplete({**base, "capped_cells": ["正在报名|事业单位"]}), 0, "撞上限不算失败")
        for flag in ("api_rejected", "budget_exhausted"):
            self.assertGreater(iguopin._incomplete({**base, flag: True}), 0, flag)
        self.assertEqual(iguopin._incomplete({**base, "request_errors": 2}), 2)

    def test_network_errors_skip_the_cell_then_give_up(self):
        import httpx
        api = _FakeApi({(1, "11q4iQX"): [_item(i, 1) for i in range(100)]})
        real = api.__call__

        def flaky(body):
            if len(api.calls) >= 2:           # 前两次（两档状态）成功，之后一直断线
                api.calls.append(body)
                raise httpx.ConnectError("Server disconnected")
            return real(body)

        items, stats = _collect(flaky)
        self.assertEqual(stats["request_errors"], iguopin._MAX_REQUEST_ERRORS, "连续失败到上限就收工，不一格格硬撞")
        self.assertEqual(len(items), 100)


class TestRecheck(unittest.TestCase):
    ROW = {"id": "r1", "source_url": "https://old.example.cn/n/1", "title": "旧公告1"}

    def _hit(self, status, title="旧公告1"):
        return [_item(1, status, title=title, apply_url="https://old.example.cn/n/1")]

    def test_budget_never_leaves_a_row_half_judged(self):
        calls = []
        rows = [dict(self.ROW, id=f"r{i}") for i in range(5)]
        out = iguopin.recheck_unseen(lambda body: calls.append(body) or [], rows, max_requests=5, pause=0)
        self.assertEqual((out["unknown"], out["stopped"]), (["r0", "r1"], "budget"), "一行要 2 次；剩 1 次就不开下一行")
        self.assertEqual(len(calls), 4)

    def test_error_stops_but_keeps_finished_verdicts(self):
        seq = iter([self._hit(1), iguopin.IguopinApiError("/list", 403, "拒绝")])

        def call(_body):
            nxt = next(seq)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

        out = iguopin.recheck_unseen(call, [self.ROW, dict(self.ROW, id="r2")], pause=0)
        self.assertEqual((out["alive"], out["closed"], out["stopped"]), (["r1"], [], "api_rejected:403"))
        self.assertEqual(out["unknown"], ["r2"], "出错时正在查的那一行排到队尾：否则它每轮都堵在最前面，后面的永远轮不到")

    def test_unexpected_response_shape_cannot_break_the_round(self):
        """复验是附带的活：搜索接口回了没见过的形状（元素是 None）也只能让复验收工，不能让整轮入库跟着崩。"""
        out = iguopin.recheck_unseen(lambda _body: [None], [self.ROW, dict(self.ROW, id="r2")], pause=0)
        self.assertEqual((out["stopped"], out["unknown"], out["closed"]), ("error:AttributeError", ["r1"], []))

    def test_closed_also_needs_the_same_publish_date(self):
        """同一个入口、同一个标题分批重发：上一批结束了、这一批还在报。只比链接和标题会把在报的这行下掉。"""
        row = dict(self.ROW, published_at="2026-10-01")
        ended_old_batch = [_item(1, 4, title="旧公告1", apply_url="https://old.example.cn/n/1",
                                 apply_start_time="2026-08-01 00:00:00")]
        ended_same_batch = [_item(1, 4, title="旧公告1", apply_url="https://old.example.cn/n/1",
                                  apply_start_time="2026-10-01 00:00:00")]

        def by(hits):
            return lambda body: hits if body["apply_status"] == [4] else []

        self.assertEqual(iguopin.recheck_unseen(by(ended_old_batch), [row], pause=0)["closed"], [])
        self.assertEqual(iguopin.recheck_unseen(by(ended_same_batch), [row], pause=0)["closed"], ["r1"])

    def test_closed_needs_url_and_title_and_not_in_window(self):
        def by(status_hits):
            return lambda body: status_hits.get(tuple(body["apply_status"]), [])

        closed = iguopin.recheck_unseen(by({(4,): self._hit(4)}), [self.ROW], pause=0)
        self.assertEqual(closed["closed"], ["r1"])
        # 在报名期的列表里还搜得到同一个入口 → 活着，哪怕「结束」列表里也有它
        alive = iguopin.recheck_unseen(by({(1, 2): self._hit(1, title="改过的标题"), (4,): self._hit(4)}), [self.ROW], pause=0)
        self.assertEqual((alive["alive"], alive["closed"]), (["r1"], []))
        # 结束列表里只对上了链接、标题不同 → 是同入口的另一份公告，不算
        other = iguopin.recheck_unseen(by({(4,): self._hit(4, title="另一份公告")}), [self.ROW], pause=0)
        self.assertEqual((other["closed"], other["unknown"]), ([], ["r1"]))

    def test_queue_skips_seen_and_soon_ending_and_puts_stalest_first(self):
        today = date(2026, 10, 10)
        rows = [
            {"id": "a", "source_url": "u-seen", "deadline": "2026-12-31", "last_checked_at": "2026-10-01T00:00:00+00:00"},
            {"id": "b", "source_url": "u-soon", "deadline": "2026-10-15", "last_checked_at": "2026-10-01T00:00:00+00:00"},
            {"id": "c", "source_url": "u-new", "deadline": "2026-12-31", "last_checked_at": "2026-10-09T00:00:00+00:00"},
            {"id": "d", "source_url": "u-old", "deadline": "2026-12-31", "last_checked_at": "2026-10-02T00:00:00+00:00"},
            {"id": "e", "source_url": "u-none", "deadline": None, "last_checked_at": None},
        ]
        self.assertEqual([r["id"] for r in iguopin._recheck_queue(rows, {"u-seen"}, today)], ["e", "d", "c"])


class TestWindow(unittest.TestCase):
    """⚠️ apply_end_time 不总是报名截止日：约四成写着「招满即止」，那个日期只是国聘登记的上限。"""
    TODAY = date(2026, 10, 10)

    def test_fixed_deadline_uses_structured_end(self):
        self.assertEqual(iguopin._window_of(_item(1, 1)),
                         (date(2026, 10, 30), "2026-10-01 至 2026-10-30", date(2026, 10, 1)))

    def test_rolling_keeps_platform_end_but_says_so(self):
        for text in ("招满即止", "报满即止"):
            deadline, shown, _pub = iguopin._window_of(_item(1, 1, apply_time=text, apply_end_time="2026-12-31 00:00:00"))
            self.assertEqual(deadline, date(2026, 12, 31), "国聘自己到这天才标结束：留着它，过期治理照常")
            self.assertEqual(shown, text, "但文案必须是国聘原话——读侧靠它不把占位日写成「报名截止」")

    def test_missing_times_do_not_crash(self):
        """旧写法 item.get('apply_start_time','')[:10] 在键存在但值为 None 时直接 TypeError。"""
        deadline, shown, published = iguopin._window_of(_item(
            1, 1, apply_start_time=None, apply_end_time=None, apply_time=None, create_time="2026-10-02 08:00:00"))
        self.assertIsNone(deadline)
        self.assertEqual(shown, "")
        self.assertEqual(published, date(2026, 10, 2))


class TestHarvestGates(unittest.TestCase):
    """量变大了，质量门一道都不能少：标题门 / 过程通知 / 第三方平台 / 已过期 / 同入口去重。"""
    TODAY = date(2026, 10, 10)

    def _run(self, items, **kw):
        api = _FakeApi({(1, "11q4iQX"): items})
        orig = iguopin._PAUSE_SECONDS
        iguopin._PAUSE_SECONDS = 0
        try:
            return iguopin.harvest(None, dry_run=True, today=self.TODAY, call=api, **{"check_links": False, **kw})
        finally:
            iguopin._PAUSE_SECONDS = orig

    def test_long_running_rolling_is_kept_and_passed_end_is_dropped(self):
        """两个方向各一条。保留：曾按「发布超 45 天就不收」处理招满即止，当场丢掉 173 条还在报的
        （8 月开的 2027 届校招）。丢弃：国聘登记的结束日已过的，招满即止也不收。"""
        m = self._run([
            _item(1, 1, apply_time="招满即止", apply_start_time="2026-08-12 00:00:00", apply_end_time="2026-12-31 00:00:00"),
            _item(2, 2, apply_time="招满即止", apply_end_time="2026-10-09 00:00:00"),
            _item(3, 2, apply_end_time="2026-10-09 00:00:00"),
        ])
        self.assertEqual([r["source_url"] for r in m["rows"]], ["https://hr.example.cn/notice/1"])
        self.assertEqual(m["drops"], {"deadline_passed": 2})

    def _persist(self, items, active=(), owned=(), search=None):
        """带假库走完整写库路径。返回 (metrics, 假库, 台账, 点过的链接)。"""
        class _FakeSb:
            def __init__(self):
                self.upserted, self.conflict, self.updates, self._change = [], None, [], None

            def table(self, _name):
                return self

            def upsert(self, rows, on_conflict=None):
                self.upserted.extend(rows)
                self.conflict = on_conflict
                return self

            def update(self, change):
                self._change = change
                return self

            def in_(self, _col, ids):
                self.updates.append((dict(self._change), list(ids)))
                return self

            def eq(self, *_a):
                return self

            def execute(self):
                return self

        api = _FakeApi({(1, "11q4iQX"): items})

        def call(body):
            return search(body) if "keywords" in body else api(body)

        sb, ledger, checked = _FakeSb(), [], []
        names = ("_active_rows", "_other_portal_urls", "_link_alive", "_PAUSE_SECONDS")
        orig = [getattr(iguopin, n) for n in names] + [iguopin.ops_runs.record_ops_run]
        iguopin._active_rows = lambda _sb: list(active)
        iguopin._other_portal_urls = lambda _sb: set(owned)
        iguopin._link_alive = lambda _client, url: checked.append(url) or True
        iguopin._PAUSE_SECONDS = 0
        # 存副本：真实的台账是调用那一刻就序列化的，harvest 之后往同一个 dict 里加的 rows 不会进台账
        iguopin.ops_runs.record_ops_run = lambda _sb, module, metrics, **kw: ledger.append((module, dict(metrics), kw))
        try:
            m = iguopin.harvest(sb, today=self.TODAY, call=call)
        finally:
            for n, v in zip(names, orig):
                setattr(iguopin, n, v)
            iguopin.ops_runs.record_ops_run = orig[-1]
        return m, sb, ledger, checked

    def test_never_overwrites_rows_owned_by_another_portal(self):
        """回归（2026-10-10 首轮真跑后对库抓到）：source_url 是全表唯一键，国聘给的入口有时就是各省栏目里
        同一篇公告的官方链接。照常 upsert 会把那一行覆盖成国聘的——一轮 14 行，3 行地区因此变成未知。"""
        m, sb, ledger, checked = self._persist(
            [_item(1, 1), _item(2, 1), _item(3, 1)],
            active=[{"id": "r1", "source_url": "https://hr.example.cn/notice/1", "title": "某单位1公开招聘公告",
                     "deadline": "2026-10-30", "last_checked_at": "2026-10-09T00:00:00+00:00"}],
            owned={"https://hr.example.cn/notice/2"})
        self.assertEqual(m["drops"], {"owned_by_other_portal": 1})
        self.assertEqual(sorted(r["source_url"] for r in sb.upserted),
                         ["https://hr.example.cn/notice/1", "https://hr.example.cn/notice/3"])
        self.assertEqual(sb.conflict, "source_url")
        self.assertTrue(all(r["status"] == "active" and r["expire_reason"] is None for r in sb.upserted),
                        "以前被下架、现在国聘又挂出来的：复活时旧的下架原因要清掉")
        self.assertEqual(checked, ["https://hr.example.cn/notice/3"], "已在展示的入口不重复点，别的来源的根本不碰")
        self.assertEqual(m["new_urls"], 1)
        self.assertEqual((ledger[0][0], ledger[0][2]["status"]), ("announcement_iguopin", "success"))
        self.assertNotIn("rows", ledger[0][1], "台账里不塞整批入库行")
        self.assertEqual(m["recheck"]["queued"], 0, "本轮见到了的行不用复验")
        self.assertEqual(sb.updates, [])

    def test_unseen_rows_are_rechecked_and_only_confirmed_closed_ones_come_down(self):
        """公司提前结束报名后，取数那一步再也见不到这条，库里那行却会挂到国聘原先登记的结束日（招满即止的能挂两个月）。
        逐条按标题问国聘：明说已结束的才下架；还在报的、搜不到的都不动。"""
        def row(i, **over):
            return {"id": f"r{i}", "source_url": f"https://old.example.cn/n/{i}", "title": f"旧公告{i}",
                    "deadline": "2026-12-31", "last_checked_at": f"2026-10-0{i}T00:00:00+00:00", **over}

        def search(body):
            title, statuses = body["keywords"], body["apply_status"]
            hit = lambda i, st: [_item(i, st, title=f"旧公告{i}", apply_url=f"https://old.example.cn/n/{i}")]  # noqa: E731
            if title == "旧公告1" and statuses == [1, 2]:
                return hit(1, 1)                                   # 还在报
            if title == "旧公告2" and statuses == [4]:
                return hit(2, 4)                                   # 国聘已标结束
            if title == "旧公告4" and statuses == [4]:              # 同一个入口、但是另一份公告结束了 → 不能算
                return [_item(4, 4, title="另一份公告", apply_url="https://old.example.cn/n/4")]
            return []

        m, sb, _ledger, _checked = self._persist(
            [_item(9, 1)],
            active=[row(1), row(2), row(3), row(4), row(5, deadline="2026-10-12")],
            search=search)
        self.assertEqual(m["recheck"], {"queued": 4, "alive": 1, "closed": 1, "unknown": 2, "requests": 7, "stopped": None},
                         "离结束日不到 7 天的不排队；还在报的只问 1 次，其余各问 2 次")
        by_ids = {tuple(ids): change for change, ids in sb.updates}
        self.assertEqual(by_ids[("r2",)]["status"], "expired")
        self.assertEqual(by_ids[("r2",)]["expire_reason"], "iguopin_closed")
        self.assertNotIn("status", by_ids[("r1",)], "还在报的只盖时间戳")
        self.assertIn("last_seen_at", by_ids[("r1",)])
        self.assertEqual(set(by_ids[("r3", "r4")]), {"last_checked_at"}, "搜不到 / 只对上链接没对上标题：不动，只记查过了")

    def test_recheck_is_skipped_right_after_the_api_rejected_us(self):
        api = _FakeApi({(1, code): [_item(f"{code}-{i}", 1, code, name) for i in range(100)]
                        for code, name in iguopin._CATEGORY_CODES.items()},
                       fail_at=4, error=iguopin.IguopinApiError("/list", 403, "账号类型错误或权限不足"))
        asked = []
        orig = (iguopin._active_rows, iguopin._other_portal_urls, iguopin._link_alive, iguopin._PAUSE_SECONDS,
                iguopin.ops_runs.record_ops_run)
        iguopin._active_rows = lambda _sb: [{"id": "r1", "source_url": "https://old.example.cn/n/1", "title": "旧公告1",
                                             "deadline": "2026-12-31", "last_checked_at": None}]
        iguopin._other_portal_urls = lambda _sb: set()
        iguopin._link_alive = lambda _client, _url: True
        iguopin._PAUSE_SECONDS = 0
        ledger = []
        iguopin.ops_runs.record_ops_run = lambda _sb, module, metrics, **kw: ledger.append(kw["status"])

        class _Sb:
            def __getattr__(self, _name):
                return lambda *a, **k: self

        def call(body):
            if "keywords" in body:
                asked.append(body)
                return []
            return api(body)

        try:
            m = iguopin.harvest(_Sb(), today=self.TODAY, call=call)
        finally:
            (iguopin._active_rows, iguopin._other_portal_urls, iguopin._link_alive, iguopin._PAUSE_SECONDS,
             iguopin.ops_runs.record_ops_run) = orig
        self.assertTrue(m["api_rejected"])
        self.assertEqual(asked, [], "刚被接口拒过就别再去问了")
        self.assertEqual(ledger, ["partial"])

    def test_shared_entry_keeps_a_deterministic_row(self):
        """同一个入口挂着几份公告、唯一键又是链接 → 只能留一条。留登记结束日最晚的，与接口返回顺序无关。"""
        a = _item(1, 1, title="集团甲公司校园招聘", apply_url="https://group.example.cn/", apply_end_time="2026-10-20 00:00:00")
        b = _item(2, 1, title="集团乙公司校园招聘", apply_url="https://group.example.cn/", apply_end_time="2026-11-30 00:00:00")
        for order in ([a, b], [b, a]):
            m = self._run(order)
            self.assertEqual([(r["title"], r["deadline"]) for r in m["rows"]], [("集团乙公司校园招聘", "2026-11-30")])
            self.assertEqual(m["drops"], {"duplicate_url": 1})

    def test_link_check_has_a_time_budget_and_defers_instead_of_waving_through(self):
        """首轮有上千个新入口；境外 runner 上每个连不上的站要等到超时。没有总时限 = job 被取消、一条都没写进去。
        时限到了还没点到的**不入库**（留给下一轮），不是不点就放行。即将截止的排在前面先点。"""
        checked = []
        orig = (iguopin._link_alive, iguopin._LINK_CHECK_BUDGET_SECONDS, iguopin._LINK_WORKERS)
        iguopin._LINK_WORKERS = 1                                   # 单线程，顺序才可断言
        iguopin._link_alive = lambda _client, url: (checked.append(url) or not url.endswith("/3"))
        try:
            items = [_item(1, 1), _item(2, 2), _item(3, 2)]
            iguopin._LINK_CHECK_BUDGET_SECONDS = 3600
            m = self._run(items, check_links=True)
            self.assertEqual(checked[:2], ["https://hr.example.cn/notice/2", "https://hr.example.cn/notice/3"],
                             "即将截止的先点：正在报名的晚一天入库无妨，它们晚一天可能就过期了")
            self.assertEqual(m["drops"], {"dead_link": 1})
            self.assertEqual(m["kept"], 2)

            checked.clear()
            iguopin._LINK_CHECK_BUDGET_SECONDS = -1                   # 时限已过
            m = self._run(items, check_links=True)
            self.assertEqual(checked, [], "时限到了就不再发请求")
            self.assertEqual(m["drops"], {"link_check_deferred": 3})
            self.assertEqual(m["kept"], 0, "没点过的新入口不能直接入库")
        finally:
            iguopin._link_alive, iguopin._LINK_CHECK_BUDGET_SECONDS, iguopin._LINK_WORKERS = orig

    def test_every_gate_still_applies(self):
        m = self._run([
            _item(1, 1),                                                               # 正常
            _item(2, 1, title="某单位公开招聘拟聘人员公示"),                              # 标题门：公示
            _item(3, 1, title="2026年大连市公安局公开招聘警务辅助人员（第二批）笔试公告"),   # assess 标题层：过程通知
            _item(4, 1, apply_url="https://www.zhipin.com/dz/x/job"),                   # 第三方平台红线
            _item(5, 1, apply_url="https://xiaoyuan.zhaopin.com/x"),                    # 第三方平台红线
            _item(6, 1, apply_end_time="2026-10-09 00:00:00"),                          # 已过期
            _item(7, 1, apply_url=""),                                                  # 没有入口
            _item(8, 1, apply_url="https://hr.example.cn/notice/1"),                    # 与第 1 条同入口
        ])
        self.assertEqual(m["drops"], {"not_recruitment": 1, "process_notice": 1, "banned_platform": 2,
                                      "deadline_passed": 1, "no_apply_url": 1, "duplicate_url": 1})
        self.assertEqual(m["kept"], 1)
        self.assertEqual(m["fetched"], 8)

    def test_rows_carry_rolling_wording_and_metrics(self):
        m = self._run([_item(1, 1), _item(2, 1, apply_time="招满即止", apply_end_time="2026-12-31 00:00:00")])
        by_url = {r["source_url"]: r for r in m["rows"]}
        rolling = by_url["https://hr.example.cn/notice/2"]
        self.assertEqual((rolling["deadline"], rolling["deadline_text"]), ("2026-12-31", "招满即止"))
        self.assertEqual(m["rolling"], 1)
        self.assertEqual(m["with_deadline"], 2)
        for key in ("requests", "capped_cells", "by_status", "api_rejected", "request_errors"):
            self.assertIn(key, m, "台账里必须看得见：打了几次、哪些格子没取全、有没有被拒")

    def test_zero_items_is_an_error_not_a_quiet_success(self):
        with self.assertRaises(RuntimeError):
            self._run([])

    def test_assess_title_layer_does_not_kill_reopened_registration(self):
        """否定性判断最容易误杀：「重启报名系统公告」是新开的报名窗，不是过程通知。"""
        m = self._run([_item(1, 1, title="江苏农牧科技职业学院公开招聘重启报名系统公告")])
        self.assertEqual(m["kept"], 1)

if __name__ == "__main__":
    unittest.main()
