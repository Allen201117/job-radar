"""byd_liveness 撤岗核验单测（纯函数 + 假游标 + 打桩，不打网络、不连库、不开浏览器）。

红线：只下架「不在全量列表 且 详情接口两轮都回空骨架」的岗；读到在招 / 判不了一律不动；
源没了、列表没抓全、链接解不出、上一轮的岗大面积缺席、对照不过、判死占比过高 → 整轮一个都不下架。
"""
import datetime as dt
import unittest
from unittest import mock

import psycopg2

import byd_liveness as L
from adapters.byd import DETAIL_URL_PREFIX, BydAdapter, detail_state


def _u(token):
    return DETAIL_URL_PREFIX + token


# 2026-10-11 实测的两种回答原样（已撤岗与不存在的 id 回的是同一个东西）。
_GONE_BODY = {"code": 0, "msg": "操作成功", "oK": True, "data": {
    "city": None, "collectionStatus": "00112", "createTime": None, "detail": None, "enFatherOrgName": None,
    "enOrgName": None, "fatherOrg": None, "fatherOrgName": None, "id": None, "orgName": None,
    "positionEngineerList": [], "positionFunctionList": [], "positionName": None, "positionRegionList": [],
    "positionTypeId": None, "province": None, "publishTime": None, "relatedDetailId": None, "sortId": None,
    "tag": None, "tagDetailList": None}}
_LIVE_BODY = {"code": 0, "msg": "操作成功", "oK": True, "data": {
    "city": "深圳市", "collectionStatus": "00112", "createTime": None, "detail": None, "enFatherOrgName": None,
    "enOrgName": None, "fatherOrg": "11019378", "fatherOrgName": "汽车事业群", "id": "2104369283076308994",
    "orgName": "直营事业部", "positionEngineerList": [], "positionFunctionList": [{"x": 1}],
    "positionName": "店端销售顾问", "positionRegionList": [{"x": 1}], "positionTypeId": "003066",
    "province": "广东省", "publishTime": None, "relatedDetailId": None, "sortId": None, "tag": None,
    "tagDetailList": [{"name": "工作职责", "detail": "接待到店客户"}]}}


class DetailStateTest(unittest.TestCase):
    def test_live_needs_same_id_and_name(self):
        self.assertEqual(detail_state(200, _LIVE_BODY, "2104369283076308994"), "live")
        as_number = {**_LIVE_BODY, "data": {**_LIVE_BODY["data"], "id": 2104369283076308994}}
        self.assertEqual(detail_state(200, as_number, "2104369283076308994"), "live")

    def test_empty_skeleton_is_gone(self):
        self.assertEqual(detail_state(200, _GONE_BODY, "2053673516951162882"), "gone")

    def test_another_jobs_data_is_not_live(self):
        """回带的 id 不是所问的那个 → 不认（不许拿别的岗的数据证明这个岗在招）。"""
        self.assertEqual(detail_state(200, _LIVE_BODY, "2053673516951162882"), "unknown")

    def test_error_code_is_unknown_not_gone(self):
        body = {"code": 4005, "data": None, "msg": "数据校验不通过: null", "oK": False}
        self.assertEqual(detail_state(200, body, "1"), "unknown")

    def test_non_200_and_non_json_are_unknown(self):
        self.assertEqual(detail_state(500, _GONE_BODY, "1"), "unknown")
        self.assertEqual(detail_state(200, None, "1"), "unknown")
        self.assertEqual(detail_state(200, {"code": 0, "data": []}, "1"), "unknown")

    def test_anything_beyond_the_bare_skeleton_is_unknown(self):
        def variant(**patch):
            return {**_GONE_BODY, "data": {**_GONE_BODY["data"], **patch}}

        # 没有 id 却有岗位名 / 有正文 / 多出一个有值字段（哪怕是接口日后新加的）—— 都不是那个空骨架，不判死
        self.assertEqual(detail_state(200, variant(positionName="店端销售顾问"), "1"), "unknown")
        self.assertEqual(detail_state(200, variant(tagDetailList=[{"name": "工作职责", "detail": "x"}]), "1"), "unknown")
        self.assertEqual(detail_state(200, variant(city="深圳市"), "1"), "unknown")
        self.assertEqual(detail_state(200, variant(newField={"positionName": "店端销售顾问"}), "1"), "unknown")
        self.assertEqual(detail_state(200, variant(sortId=0), "1"), "unknown")
        # 有 id 却没岗位名：既不是在招也不是空骨架
        self.assertEqual(detail_state(200, variant(id="1"), "1"), "unknown")
        self.assertEqual(detail_state(200, variant(id="1", positionName="   "), "1"), "unknown")


class SettleStatesTest(unittest.TestCase):
    def test_gone_needs_both_rounds(self):
        first = {"a": "gone", "b": "gone", "c": "live", "d": "unknown", "e": "gone", "f": "gone"}
        second = {"a": "gone", "b": "live", "e": "unknown"}
        self.assertEqual(L.settle_states(first, second), {
            "a": "gone", "b": "unknown", "c": "live", "d": "unknown", "e": "unknown", "f": "unknown"})


class PlanTest(unittest.TestCase):
    def test_every_branch(self):
        rows = [("r1", _u("ok")),          # 在列表、链接正常
                ("r2", _u("broken")),      # 在列表、老的坏链接 → 改链接
                ("r3", _u("gone")),        # 不在列表、两轮空骨架 → 下架
                ("r4", _u("live")),        # 不在列表、详情在招 → 不动
                ("r5", _u("unknown")),     # 不在列表、判不了 → 不动
                ("r6", _u("nokey")),       # 解不出 id → 不动
                ("r7", _u("brokengone"))]  # 坏链接且已撤 → 直接下架，不必先改链接
        decoded = {_u("ok"): ("1", None), _u("broken"): ("2", _u("bro//ken")), _u("gone"): ("3", None),
                   _u("live"): ("4", None), _u("unknown"): ("5", None), _u("brokengone"): ("7", _u("x//y"))}
        acts = L.plan(rows, decoded, {"1", "2"}, {"3": "gone", "4": "live", "5": "unknown", "7": "gone"})
        got = {a[1]: (a[0], a[3]) for a in acts}
        self.assertEqual(got, {
            "r1": ("keep", None), "r2": ("relink", _u("bro//ken")), "r3": ("expire", None),
            "r4": ("keep_live_unlisted", None), "r5": ("keep_unknown", None),
            "r6": ("keep_undecodable", None), "r7": ("expire", None)})

    def test_listed_job_is_never_expired_whatever_detail_says(self):
        acts = L.plan([("r1", _u("ok"))], {_u("ok"): ("1", None)}, {"1"}, {"1": "gone"})
        self.assertEqual(acts[0][0], "keep")

    def test_unprobed_absent_job_is_unknown_not_expired(self):
        acts = L.plan([("r1", _u("ok"))], {_u("ok"): ("1", None)}, set(), {})
        self.assertEqual(acts[0][0], "keep_unknown")


class ControlTest(unittest.TestCase):
    def test_positive_all_live_passes(self):
        self.assertTrue(L.positive_control_ok({"1", "2", "3"}, lambda j: "live"))

    def test_positive_any_non_live_fails(self):
        self.assertFalse(L.positive_control_ok({"1", "2", "3"}, lambda j: "gone" if j == "2" else "live", k=3))
        self.assertFalse(L.positive_control_ok({"1"}, lambda j: "unknown"))

    def test_positive_empty_list_cannot_vouch(self):
        self.assertFalse(L.positive_control_ok(set(), lambda j: "live"))

    def test_negative_asks_ids_that_cannot_exist(self):
        asked = []
        ok = L.negative_control_ok({"2104369283076308994", "2084078591028551682"},
                                   lambda j: asked.append(j) or "gone")
        self.assertTrue(ok)
        self.assertEqual(asked, ["1", "2104369283076308995"])

    def test_negative_fails_when_signal_changed(self):
        self.assertFalse(L.negative_control_ok({"5"}, lambda j: "unknown"))
        self.assertFalse(L.negative_control_ok({"5"}, lambda j: "live"))


class SentinelTest(unittest.TestCase):
    def test_control_runs_before_and_after_every_chunk(self):
        log = []
        states, ok = L.probe_with_sentinels(
            [str(i) for i in range(5)], lambda j: log.append(j) or "gone",
            lambda: log.append("ctrl") or True, chunk=2)
        self.assertTrue(ok)
        self.assertEqual(len(states), 5)
        self.assertEqual([i for i, x in enumerate(log) if x == "ctrl"], [0, 3, 6, 8])

    def test_failed_first_control_probes_nothing(self):
        probed = []
        states, ok = L.probe_with_sentinels(["1", "2"], lambda j: probed.append(j) or "gone", lambda: False)
        self.assertEqual((states, ok, probed), ({}, False, []))

    def test_control_failing_midway_voids_the_run(self):
        calls = iter([True, True, False])
        _states, ok = L.probe_with_sentinels([str(i) for i in range(6)], lambda j: "gone",
                                             lambda: next(calls), chunk=2)
        self.assertFalse(ok)

    def test_nothing_to_probe_still_checks_the_signal(self):
        ran = []
        self.assertEqual(L.probe_with_sentinels([], lambda j: "gone", lambda: ran.append(1) or True), ({}, True))
        self.assertEqual(ran, [1])


class GateTest(unittest.TestCase):
    def test_ratio_boundary(self):
        self.assertIsNone(L.expire_blocked_reason(30, 100, 0.3))
        self.assertIn("31/100", L.expire_blocked_reason(31, 100, 0.3))
        self.assertIsNone(L.expire_blocked_reason(0, 0, 0.3))

    def test_backlog_is_blocked_by_default_and_passes_only_when_widened(self):
        # 2026-10-11 的存量：7,481 行里 5,429 行已撤（73%）
        self.assertIsNotNone(L.expire_blocked_reason(5429, 7481, L.DEFAULT_MAX_EXPIRE_FRACTION))
        self.assertIsNone(L.expire_blocked_reason(5429, 7481, 0.75))

    def test_decode_gate(self):
        urls = [_u(str(i)) for i in range(100)]
        self.assertIsNone(L.decode_blocked_reason(urls, {u: ("1", None) for u in urls}))
        self.assertIsNone(L.decode_blocked_reason(urls, {u: ("1", None) for u in urls[:95]}))
        self.assertIn("94/100", L.decode_blocked_reason(urls, {u: ("1", None) for u in urls[:94]}))
        # 官方路由整个变了：一条都解不出，绝不许当成「0 个要下架」放过去
        self.assertIn("0/100", L.decode_blocked_reason(urls, {}))
        self.assertIsNotNone(L.decode_blocked_reason(["https://job.byd.com/other?x"], {}))
        self.assertIsNone(L.decode_blocked_reason([], {}))

    def test_recent_absent_gate(self):
        listed = {str(i) for i in range(100)}
        recent = [str(i) for i in range(100)]
        self.assertIsNone(L.recent_absent_blocked_reason(recent, listed))
        self.assertIsNone(L.recent_absent_blocked_reason(recent, {str(i) for i in range(20, 100)}))    # 缺 20%
        self.assertIn("21/100", L.recent_absent_blocked_reason(recent, {str(i) for i in range(21, 100)}))
        self.assertEqual(L.recent_absent_blocked_reason([], listed), "no_recent_reference")

    def test_live_unlisted_gate(self):
        self.assertIsNone(L.live_unlisted_blocked_reason(0, 2000))
        self.assertIsNone(L.live_unlisted_blocked_reason(20, 2000))
        self.assertIn("21/2000", L.live_unlisted_blocked_reason(21, 2000))

    def test_fraction_argument_rejects_nonsense(self):
        self.assertEqual(L._fraction("0.75"), 0.75)
        for bad in ("nan", "-0.1", "1.5"):
            with self.assertRaises(L.argparse.ArgumentTypeError):
                L._fraction(bad)


class ExitCodeTest(unittest.TestCase):
    def test_clean_run(self):
        self.assertEqual(L.exit_code([{"company": "比亚迪"}], apply=True), 0)

    def test_no_source_is_never_green(self):
        self.assertEqual(L.exit_code([], apply=False), L.EXIT_BLOCKED)
        self.assertEqual(L.exit_code([], apply=True), L.EXIT_BLOCKED)

    def test_ratio_block_is_only_a_report_in_dry_run(self):
        rep = [{"company": "比亚迪", "blocked": "too_many:5429/7481>0.3"}]
        self.assertEqual(L.exit_code(rep, apply=False), 0)
        self.assertEqual(L.exit_code(rep, apply=True), L.EXIT_BLOCKED)

    def test_untrusted_run_is_red_even_in_dry_run(self):
        for reason in ("control_failed", "list_incomplete", "error:RuntimeError", "decode_degraded:0/7481",
                       "recent_absent_too_many:900/2100", "no_recent_reference", "list_not_full_set:40/2100"):
            self.assertEqual(L.exit_code([{"company": "比亚迪", "blocked": reason}], apply=False), L.EXIT_BLOCKED)


_NOW = dt.datetime(2026, 10, 11, 16, 0, tzinfo=dt.timezone.utc)


class _Cursor:
    def __init__(self, store, dup_urls, conflict_urls, refreshed):
        self.store, self.dup_urls, self.conflict_urls, self.refreshed = store, dup_urls, conflict_urls, refreshed
        self.rowcount, self._rows = 0, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id from jobs"):
            self._rows = [("other",)] if params[1] in self.dup_urls else []
        elif s.startswith("update jobs set jd_url"):
            if params[0] in self.conflict_urls:
                raise psycopg2.errors.UniqueViolation("jobs_company_title_location_jd_url_key")
            self.store.setdefault("relinked", []).append((params[2], params[0], params[1]))
            self.rowcount = 1
        elif s.startswith("update jobs set status='expired'"):
            ids = list(params[2])
            if "last_seen_at <" in s:
                self.store["expire_guard"] = params[3]
                ids = [i for i in ids if i not in self.refreshed]   # 核验期间又被抓取刷新过的行不动
                self.store["expired"] = ids
            else:
                self.store["dup_expired"] = ids
            self._rows = [(i,) for i in ids]
        elif s.startswith("update jobs set enrich_checked_at"):
            self.store["stamped"] = list(params[1])
        else:
            raise AssertionError("没料到的 SQL: " + sql)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, dup_urls=(), conflict_urls=(), refreshed=()):
        self.store = {}
        self._args = (set(dup_urls), set(conflict_urls), set(refreshed))
        self.closed = False

    def cursor(self):
        return _Cursor(self.store, *self._args)

    def close(self):
        self.closed = True


_ACTIONS = [("keep", "r1", _u("ok"), None),
            ("relink", "r2", _u("a"), _u("a//b")),           # 原地改链接
            ("relink", "r3", _u("takenx"), _u("taken//x")),   # 新链接已被另一行在招岗占 → 这行是重复
            ("relink", "r8", _u("oldx"), _u("old//x")),       # 新链接被一行已下架的旧行占着 → 撞唯一约束
            ("expire", "r4", _u("gone"), None),
            ("expire", "r9", _u("gone2"), None),              # 核验期间又被抓取看到了
            ("keep_live_unlisted", "r5", _u("live"), None),
            ("keep_unknown", "r6", _u("unk"), None),
            ("keep_undecodable", "r7", _u("bad"), None)]


class ApplyActionsTest(unittest.TestCase):
    def _conn(self):
        return _Conn(dup_urls={_u("taken//x")}, conflict_urls={_u("old//x")}, refreshed={"r9"})

    def test_relink_expire_and_stamp(self):
        conn = self._conn()
        with mock.patch.object(L.jobs_db, "record_job_events", return_value=0) as events:
            out = L.apply_actions(conn, "src", _ACTIONS, not_seen_since=_NOW)
        self.assertEqual(out, {"relinked": 1, "expired": 1, "dup_expired": 1, "dup_kept": 0, "relink_conflict": 1})
        self.assertEqual(conn.store["relinked"], [("r2", _u("a//b"), _u("a//b"))])   # jd_url 与 apply_url 同改
        self.assertEqual(conn.store["expired"], ["r4"])
        self.assertEqual(conn.store["expire_guard"], _NOW)
        self.assertEqual(conn.store["dup_expired"], ["r3"])
        self.assertEqual(conn.store["stamped"], ["r1", "r2"])     # 只给核实在招的行盖戳；没改成 / 没核出来的不盖
        # CLOSED 事件只记真被下架的行：r9 被 last_seen 条件挡住，不许有它
        self.assertEqual([e[2] for e in events.call_args[0][1]], ["r4", "r3"])

    def test_one_relink_conflict_does_not_stop_the_rest(self):
        """撞唯一约束的那一行跳过，后面的下架照做（否则每次重跑都卡在同一行）。"""
        conn = self._conn()
        with mock.patch.object(L.jobs_db, "record_job_events", return_value=0):
            out = L.apply_actions(conn, "src", _ACTIONS, not_seen_since=_NOW)
        self.assertEqual((out["relink_conflict"], out["expired"]), (1, 1))

    def test_duplicates_are_kept_when_expiry_is_blocked(self):
        conn = self._conn()
        with mock.patch.object(L.jobs_db, "record_job_events", return_value=0) as events:
            out = L.apply_actions(conn, "src", [a for a in _ACTIONS if a[0] != "expire"],
                                  not_seen_since=_NOW, expire_dups=False)
        self.assertEqual((out["expired"], out["dup_expired"], out["dup_kept"]), (0, 0, 1))
        self.assertNotIn("expired", conn.store)
        self.assertNotIn("dup_expired", conn.store)
        self.assertEqual(events.call_args[0][1], [])

    def test_nothing_to_do_writes_nothing(self):
        conn = _Conn()
        with mock.patch.object(L.jobs_db, "record_job_events", return_value=0):
            out = L.apply_actions(conn, "src", [("keep_unknown", "r1", _u("x"), None)], not_seen_since=_NOW)
        self.assertEqual(out, {"relinked": 0, "expired": 0, "dup_expired": 0, "dup_kept": 0, "relink_conflict": 0})
        self.assertEqual(conn.store, {})


class ReconcileSourceTest(unittest.TestCase):
    """整条流程（列表 / 解 id / 探详情 / 写库全打桩）：验的是「哪道闸不过就不许写」。"""

    SRC = {"id": "src", "company": "比亚迪 BYD", "source_url": "https://job.byd.com/portal/pc/#/social/x"}

    def _run(self, *, apply, states=None, second_states=None, list_total=None, n_listed=10, n_absent=2,
             max_fraction=0.3, listed_probe=None, fake_probe_state="gone", decoded_patch=None,
             recent_missing=0, fail_control_after=None):
        listed = [str(100 + i) for i in range(n_listed)]
        absent = [str(900 + i) for i in range(n_absent)]
        dropped = [str(500 + i) for i in range(recent_missing)]     # 上一轮还在、这一轮列表里没了
        rows = ([(f"row{j}", _u(j), True) for j in listed + dropped]
                + [(f"row{j}", _u(j), False) for j in absent])
        decoded = {_u(j): (j, None) for j in listed + absent + dropped}
        if decoded_patch is not None:
            decoded = decoded_patch(decoded)
        states, calls, ctrl = states or {}, {}, {"n": 0}

        def fake_list(adapter, client):
            adapter.reported_total = len(listed) if list_total is None else list_total
            return [{"id": j} for j in listed]

        def fake_probe(client, job_id):
            calls[job_id] = calls.get(job_id, 0) + 1
            if job_id in listed:
                ctrl["n"] += 1
                if fail_control_after is not None and ctrl["n"] > fail_control_after:
                    return "gone"
                return (listed_probe or (lambda j: "live"))(job_id)
            if job_id in absent or job_id in dropped:
                if calls[job_id] > 1 and second_states is not None:
                    return second_states.get(job_id, "gone")
                return states.get(job_id, "gone")
            return fake_probe_state   # 阴性对照用的伪 id

        applied, conns = [], []

        def fake_apply(conn, sid, actions, **kw):
            applied.append((list(actions), kw))
            return {"relinked": 0, "expired": sum(a[0] == "expire" for a in actions), "dup_expired": 0,
                    "dup_kept": 0, "relink_conflict": 0}

        def fake_conn():
            conns.append(_Conn())
            return conns[-1]

        with mock.patch.object(L.httpx, "Client", mock.MagicMock()), \
                mock.patch.object(BydAdapter, "_fetch_list_rows", fake_list), \
                mock.patch.object(BydAdapter, "decode_detail_urls", lambda self, url, urls: decoded), \
                mock.patch.object(L.jobs_db, "get_conn", fake_conn), \
                mock.patch.object(L, "load_active_rows", lambda conn, sid: rows), \
                mock.patch.object(L, "probe", fake_probe), \
                mock.patch.object(L, "apply_actions", fake_apply):
            rec, blocked = L.reconcile_source(self.SRC, apply=apply, max_fraction=max_fraction)
        self.assertTrue(all(c.closed for c in conns))     # 库连接用完即关，不留着空等十几分钟
        return rec, blocked, applied, calls

    def test_happy_path_expires_only_confirmed_gone(self):
        rec, blocked, applied, _ = self._run(apply=True, states={"900": "gone", "901": "live"}, n_listed=120)
        self.assertFalse(blocked)
        self.assertEqual((rec["keep"], rec["expire"], rec["keep_live_unlisted"]), (120, 1, 1))
        actions, kw = applied[0]
        self.assertEqual([a[1] for a in actions if a[0] == "expire"], ["row900"])
        self.assertIn("not_seen_since", kw)
        self.assertNotIn("expire_dups", kw)

    def test_dry_run_never_writes(self):
        rec, blocked, applied, _ = self._run(apply=False)
        self.assertFalse(blocked)
        self.assertEqual(rec["expire"], 2)
        self.assertEqual(applied, [])

    def test_second_round_disagreement_is_not_expired(self):
        rec, _blocked, _applied, calls = self._run(apply=True, second_states={"900": "live"})
        self.assertEqual((rec.get("expire", 0), rec["keep_unknown"]), (1, 1))
        self.assertEqual((calls["900"], calls["901"]), (2, 2))     # 每个缺席的岗真的被问了两轮

    def test_incomplete_list_blocks_before_anything_else(self):
        rec, blocked, applied, calls = self._run(apply=True, list_total=99)
        self.assertEqual((blocked, rec["blocked"], applied, calls), (True, "list_incomplete", [], {}))

    def test_zero_reported_total_is_not_a_complete_list(self):
        rec, blocked, applied, _ = self._run(apply=True, list_total=0)
        self.assertEqual((blocked, rec["blocked"], applied), (True, "list_incomplete", []))

    def test_undecodable_links_block_instead_of_reporting_zero(self):
        rec, blocked, applied, calls = self._run(apply=True, decoded_patch=lambda d: {})
        self.assertTrue(blocked)
        self.assertTrue(rec["blocked"].startswith("decode_degraded:0/"))
        self.assertEqual((applied, calls), ([], {}))

    def test_last_crawls_jobs_vanishing_blocks_even_with_widened_ratio(self):
        """上一轮还在的 10 个岗里这一轮缺了 5 个：列表不是全集。把占比闸放到 1.0 也不放行。"""
        rec, blocked, applied, calls = self._run(apply=True, n_listed=5, recent_missing=5, max_fraction=1.0)
        self.assertTrue(blocked)
        self.assertEqual(rec["blocked"], "recent_absent_too_many:5/10")
        self.assertEqual((applied, calls), ([], {}))

    def test_failed_positive_control_blocks_before_probing(self):
        """接口对在招岗也回空骨架（整体退化）→ 读到的 gone 全不可信：不探、不写。"""
        rec, blocked, applied, calls = self._run(apply=True, listed_probe=lambda j: "gone")
        self.assertEqual((blocked, rec["blocked"], applied), (True, "control_failed", []))
        self.assertFalse([j for j in calls if j.startswith("9")])

    def test_failed_negative_control_blocks(self):
        """不存在的 id 读不到空骨架了 = 判死信号本身变了。"""
        rec, blocked, applied, _ = self._run(apply=True, fake_probe_state="unknown")
        self.assertEqual((blocked, rec["blocked"], applied), (True, "control_failed", []))

    def test_control_failing_after_the_probes_voids_them(self):
        # 第 1 遍对照（8 个在招岗）过；探完第一轮后的那一遍开始读不到在招
        rec, blocked, applied, _ = self._run(apply=True, fail_control_after=8)
        self.assertEqual((blocked, rec["blocked"], applied), (True, "control_failed", []))

    def test_too_many_live_but_unlisted_means_list_is_not_the_full_set(self):
        states = {str(900 + i): "live" for i in range(3)}
        rec, blocked, applied, _ = self._run(apply=True, states=states, n_listed=100, n_absent=3)
        self.assertTrue(blocked)
        self.assertEqual(rec["blocked"], "list_not_full_set:3/103")
        self.assertEqual(applied, [])

    def test_ratio_gate_blocks_expire_but_still_repairs_live_rows(self):
        rec, blocked, applied, _ = self._run(apply=True, n_listed=8, n_absent=8, max_fraction=0.3)
        self.assertTrue(blocked)
        self.assertTrue(rec["blocked"].startswith("too_many:8/16"))
        actions, kw = applied[0]
        self.assertFalse([a for a in actions if a[0] == "expire"])
        self.assertIs(kw["expire_dups"], False)

    def test_ratio_gate_in_dry_run_writes_nothing(self):
        _rec, blocked, applied, _ = self._run(apply=False, n_listed=8, n_absent=8)
        self.assertTrue(blocked)
        self.assertEqual(applied, [])


class MainTest(unittest.TestCase):
    def _main(self, sources, argv, reconcile=None):
        ledger = []
        sb = mock.MagicMock()
        with mock.patch.object(L.db, "get_supabase", return_value=sb), \
                mock.patch.object(L.db, "fetch_all_rows", return_value=sources), \
                mock.patch.object(L, "reconcile_source", reconcile or (lambda *a, **k: ({"company": "比亚迪"}, False))), \
                mock.patch.object(L.ops_runs, "record_ops_run",
                                  lambda sb, module, metrics, status, **kw: ledger.append((module, status, metrics)) or True), \
                mock.patch.object(L.sys, "argv", ["byd_liveness.py", *argv]):
            return L.main(), ledger

    SRC = [{"id": "s", "company": "比亚迪 BYD", "source_url": "u", "adapter_name": "byd", "enabled": True}]

    def test_missing_source_is_red_and_recorded_as_failed(self):
        for sources in ([], [{**self.SRC[0], "enabled": False}]):
            code, ledger = self._main(sources, ["--apply"])
            self.assertEqual(code, L.EXIT_BLOCKED)
            self.assertEqual([(m, s) for m, s, _ in ledger], [("byd_liveness", "failed")])
            code, ledger = self._main(sources, [])
            self.assertEqual((code, ledger), (L.EXIT_BLOCKED, []))

    def test_crash_in_one_source_is_blocked_not_green(self):
        def boom(*a, **k):
            raise RuntimeError("byd: queryList returned 2000 unique rows, expected 2078")

        code, ledger = self._main(self.SRC, ["--apply"], reconcile=boom)
        self.assertEqual(code, L.EXIT_BLOCKED)
        self.assertEqual(ledger[0][1], "failed")
        self.assertEqual(ledger[0][2]["blocked"], "error:RuntimeError")

    def test_dry_run_writes_no_ledger(self):
        code, ledger = self._main(self.SRC, [])
        self.assertEqual((code, ledger), (0, []))

    def test_apply_success_is_recorded(self):
        code, ledger = self._main(self.SRC, ["--apply"],
                                  reconcile=lambda *a, **k: ({"company": "比亚迪", "expire": 3, "expired": 3}, False))
        self.assertEqual(code, 0)
        self.assertEqual((ledger[0][1], ledger[0][2]["expired"]), ("success", 3))


if __name__ == "__main__":
    unittest.main()
