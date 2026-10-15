"""moka_liveness 撤岗核验单测（纯函数 + 假游标 + 假 HTTP 客户端，不打网络、不连库）。

红线：只下架「这条源最近一轮抓全了的列表里没有 且 详情请求两次都回已停」的岗；读到在招 / 判不了一律不动；
这条源最近一轮没抓全 / 失败 / 还在跑 / 太旧、库里这一轮见到的行数对不上、对照不过、读到在招的缺席岗太多、
拟下架占比过高 → 这条源一个都不下架。所有源都用不上 → 整轮变红，不许安静地报成功。
"""
import datetime as dt
import os
import re
import unittest
from unittest import mock

import httpx

import moka_liveness as L

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 13, 4, 0, tzinfo=UTC)
RUN_START = dt.datetime(2026, 10, 12, 21, 30, tzinfo=UTC)
BASE = "https://app.mokahr.com/social-recruitment/geely/96123"
OTHER = "https://app.mokahr.com/social-recruitment/other/1"


def _url(n, base=BASE):
    return f"{base}#/job/{n:08d}-0000-4000-8000-000000000000"


def _ref(n, base=BASE):
    return L.detail_ref(_url(n, base))


def _run(**over):
    run = {"source_id": "s1", "started_at": RUN_START.isoformat(),
           "finished_at": (RUN_START + dt.timedelta(minutes=9)).isoformat(),
           "status": "success", "coverage_complete": True, "jobs_found": 900, "reported_total": 900}
    run.update(over)
    return run


# 2026-10-12 实测的回包形状：{"data": 密文, "necromancer": 16 位十六进制}，只看密文长度。
# 已停 / 不存在的岗 152 个字符，在招 1,708 个字符以上。
_GONE_BODY = {"data": "x" * 152, "necromancer": "c0ffbfea63f1b389"}
_LIVE_BODY = {"data": "x" * 4204, "necromancer": "c0ffbfea63f1b389"}


def _body(n):
    return {"data": "x" * n, "necromancer": "c0ffbfea63f1b389"}


class DetailRefTest(unittest.TestCase):
    def test_platform_domain_social_portal(self):
        ref = L.detail_ref("https://app.mokahr.com/social-recruitment/geely/96123#/job/8eeb2a7d-bfbd-4d72-a554-781c573bcab5")
        self.assertEqual(ref, L.DetailRef("https://app.mokahr.com", "geely", 96123, "8eeb2a7d-bfbd-4d72-a554-781c573bcab5"))

    def test_tenant_own_domain_and_other_portal_kinds(self):
        self.assertEqual(L.detail_ref("https://talent.catl.com/social-recruitment/catlhr/96144#/job/76b208c8-4a05-4a7b-842d-a33066f21cea"),
                         L.DetailRef("https://talent.catl.com", "catlhr", 96144, "76b208c8-4a05-4a7b-842d-a33066f21cea"))
        for kind in ("apply", "campus_apply", "campus-recruitment"):
            ref = L.detail_ref(f"https://app.mokahr.com/{kind}/shein/2933#/job/1be5920d-bd6b-4eb5-a440-60b119881079")
            self.assertEqual((ref.org, ref.site_id), ("shein", 2933), kind)

    def test_query_before_hash_is_tolerated(self):
        ref = L.detail_ref("https://app.mokahr.com/social-recruitment/pg/91934?locale=en-US#/job/7140e7b0-23c6-4688-939c-e4ae0d78bc2b")
        self.assertEqual((ref.org, ref.site_id, ref.job_id), ("pg", 91934, "7140e7b0-23c6-4688-939c-e4ae0d78bc2b"))

    def test_anything_that_is_not_a_moka_job_link_is_none(self):
        for bad in (None, "", "https://app.mokahr.com/social-recruitment/geely/96123",
                    "https://app.mokahr.com/social-recruitment/geely/96123#/jobs",
                    "https://app.mokahr.com/social-recruitment/geely/abc#/job/8eeb2a7d-bfbd-4d72-a554-781c573bcab5",
                    "https://app.mokahr.com/social-recruitment/geely/96123#/job/not-a-uuid",
                    "https://job.byd.com/portal/pc/#/social/socialPositionDetails?x=1"):
            self.assertIsNone(L.detail_ref(bad), bad)


class AnswerStateTest(unittest.TestCase):
    def test_short_cipher_of_the_known_length_is_gone(self):
        self.assertEqual(L.answer_state(200, _GONE_BODY), "gone")

    def test_long_cipher_is_live(self):
        self.assertEqual(L.answer_state(200, _LIVE_BODY), "live")
        self.assertEqual(L.answer_state(200, _body(1708)), "live")   # 实测最短的在招回包

    def test_any_other_length_is_unknown_not_gone(self):
        # 172 = 英文 locale 的已停回包（我们固定问中文，读到它说明对方回包变了）；108 = 门户 id 不存在。
        # 都不许当成已停：判死只认实测过的那一个长度。
        for n in (0, 108, 151, 153, 172, 400, 999):
            self.assertEqual(L.answer_state(200, _body(n)), "unknown", n)

    def test_non_200_or_malformed_body_is_unknown(self):
        self.assertEqual(L.answer_state(500, _GONE_BODY), "unknown")
        self.assertEqual(L.answer_state(429, _GONE_BODY), "unknown")
        for body in (None, [], "x" * 152, {}, {"data": None, "necromancer": "c0ff"},
                     {"data": {"code": 0}, "necromancer": "c0ff"}, {"code": 0, "data": []}):
            self.assertEqual(L.answer_state(200, body), "unknown", body)

    def test_right_length_in_the_wrong_envelope_is_unknown(self):
        # 只有密文回包（带 necromancer）才认长度；别的信封里恰好 152 / 很长的字符串不算数
        # （对方的明文报错信封是 {code, msg, data, success}）。
        self.assertEqual(L.answer_state(200, {"data": "x" * 152}), "unknown")
        self.assertEqual(L.answer_state(200, {"code": 500, "msg": "系统异常", "data": "x" * 152, "success": False}), "unknown")
        self.assertEqual(L.answer_state(200, {"data": "x" * 4204}), "unknown")


class LatestRunTest(unittest.TestCase):
    def test_latest_started_run_per_source_wins(self):
        runs = [_run(source_id="a", started_at="2026-10-11T21:00:00+00:00", jobs_found=1),
                _run(source_id="a", started_at="2026-10-12T21:00:00+00:00", jobs_found=2),
                _run(source_id="b", started_at="2026-10-12T01:00:00+00:00", jobs_found=3)]
        latest = L.latest_runs(runs)
        self.assertEqual({k: v["jobs_found"] for k, v in latest.items()}, {"a": 2, "b": 3})

    def test_a_newer_unfinished_run_is_not_hidden_behind_an_older_complete_one(self):
        runs = [_run(source_id="a", started_at="2026-10-11T21:00:00+00:00"),
                _run(source_id="a", started_at="2026-10-12T21:00:00+00:00", finished_at=None, status="running")]
        self.assertEqual(L.latest_runs(runs)["a"]["status"], "running")


class RunGateTest(unittest.TestCase):
    def test_complete_recent_run_passes(self):
        self.assertIsNone(L.run_skip_reason(_run(), NOW))
        self.assertIsNone(L.run_skip_reason(_run(status="partial_success"), NOW))

    def test_no_run(self):
        self.assertEqual(L.run_skip_reason(None, NOW), "no_run")

    def test_run_still_in_flight(self):
        self.assertEqual(L.run_skip_reason(_run(finished_at=None, status="running"), NOW), "run_in_progress")

    def test_failed_run(self):
        self.assertEqual(L.run_skip_reason(_run(status="failed", coverage_complete=None), NOW), "run_failed")

    def test_incomplete_or_undeterminable_coverage(self):
        self.assertEqual(L.run_skip_reason(_run(coverage_complete=False), NOW), "list_incomplete")
        self.assertEqual(L.run_skip_reason(_run(coverage_complete=None), NOW), "list_incomplete")

    def test_stale_run(self):
        old = NOW - dt.timedelta(hours=L.MAX_RUN_AGE_HOURS + 1)
        self.assertEqual(L.run_skip_reason(_run(started_at=old.isoformat()), NOW), "run_stale")


class UsableGateTest(unittest.TestCase):
    def test_most_sources_usable_is_fine(self):
        self.assertIsNone(L.usable_blocked_reason(380, 372))
        self.assertIsNone(L.usable_blocked_reason(1, 1))

    def test_no_usable_source_is_a_failed_run_not_a_quiet_success(self):
        # 抓取记录读空 / 昨晚重档没跑 / 抓全率判定回归 → 一条源都核不了。不许报成功（绿灯零产出）。
        self.assertEqual(L.usable_blocked_reason(380, 0), "no_usable_sources:0/380")

    def test_few_usable_sources_is_a_failed_run(self):
        self.assertEqual(L.usable_blocked_reason(380, 100), "few_usable_sources:100/380")


class ControlsTest(unittest.TestCase):
    def test_pass_when_listed_rows_read_live_and_fake_id_reads_gone(self):
        states = {_ref(1): "live", _ref(2): "live", L.fake_ref(_ref(1)): "gone"}
        self.assertTrue(L.controls_ok([_ref(1), _ref(2)], states.get))

    def test_fail_when_a_listed_row_does_not_read_live(self):
        for bad in ("gone", "unknown"):
            states = {_ref(1): "live", _ref(2): bad, L.fake_ref(_ref(1)): "gone"}
            self.assertFalse(L.controls_ok([_ref(1), _ref(2)], states.get), bad)

    def test_fail_when_fake_id_does_not_read_gone(self):
        for bad in ("live", "unknown"):
            states = {_ref(1): "live", L.fake_ref(_ref(1)): bad}
            self.assertFalse(L.controls_ok([_ref(1)], states.get), bad)

    def test_fail_without_any_listed_row(self):
        self.assertFalse(L.controls_ok([], lambda ref: "gone"))

    def test_fake_ref_keeps_the_portal_and_is_a_uuid_that_is_not_the_real_one(self):
        fake = L.fake_ref(_ref(7))
        self.assertEqual((fake.origin, fake.org, fake.site_id), (_ref(7).origin, _ref(7).org, _ref(7).site_id))
        self.assertNotEqual(fake.job_id, _ref(7).job_id)
        self.assertRegex(fake.job_id, r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ProbeAllTest(unittest.TestCase):
    def _go(self, refs, control_results, **kw):
        asked, controls = [], iter(control_results)

        def probe_fn(ref):
            asked.append(ref)
            return "gone"

        calls = []

        def control_fn():
            calls.append(len(asked))
            return next(controls)

        states, ok = L.probe_all(refs, probe_fn, control_fn, threads=1, **kw)
        return states, ok, asked, calls

    def test_opening_control_failure_asks_no_candidate(self):
        states, ok, asked, calls = self._go([_ref(1), _ref(2)], [False], chunk=10)
        self.assertEqual((states, ok, asked), ({}, False, []))

    def test_control_runs_again_after_every_chunk(self):
        states, ok, asked, calls = self._go([_ref(n) for n in range(1, 6)], [True, True, True, True], chunk=2)
        self.assertTrue(ok)
        self.assertEqual(len(states), 5)
        self.assertEqual(calls, [0, 2, 4, 5])   # 开头一次，之后每块（2 / 2 / 1 个）探完各一次

    def test_control_failure_after_a_chunk_voids_the_round(self):
        states, ok, asked, calls = self._go([_ref(n) for n in range(1, 6)], [True, True, False], chunk=2)
        self.assertFalse(ok)
        self.assertEqual(len(asked), 4)   # 第二块之后对照不过，第三块不再探

    def test_opening_control_can_be_skipped_when_one_just_ran(self):
        states, ok, asked, calls = self._go([_ref(1)], [True], chunk=10, check_first=False)
        self.assertEqual((ok, calls), (True, [1]))


class SettleTest(unittest.TestCase):
    def test_only_gone_twice_is_gone(self):
        first = {_ref(1): "gone", _ref(2): "gone", _ref(3): "gone", _ref(4): "live", _ref(5): "unknown"}
        second = {_ref(1): "gone", _ref(2): "live", _ref(4): "gone"}
        self.assertEqual(L.settle(first, second),
                         {_ref(1): "gone", _ref(2): "unknown", _ref(3): "unknown", _ref(4): "live", _ref(5): "unknown"})


class PlanTest(unittest.TestCase):
    def test_each_candidate_gets_one_action(self):
        candidates = [("r1", _url(1)), ("r2", _url(2)), ("r3", _url(3)), ("r4", "https://example.com/not-moka")]
        states = {_ref(1): "gone", _ref(2): "live"}
        self.assertEqual(L.plan(candidates, states),
                         [("expire", "r1"), ("keep_live_unlisted", "r2"), ("keep_unknown", "r3"), ("keep_unparsed", "r4")])


class GatesTest(unittest.TestCase):
    def test_a_few_live_unlisted_rows_are_normal(self):
        # 2026-10-12 实测：特斯拉一个白天重新开放了 12 个岗（在招 1,161 行）
        self.assertIsNone(L.live_unlisted_blocked_reason(12, 1161))
        self.assertIsNone(L.live_unlisted_blocked_reason(5, 10))

    def test_many_live_unlisted_rows_mean_the_list_is_not_the_full_set(self):
        self.assertEqual(L.live_unlisted_blocked_reason(6, 10), "list_not_full_set:6/10")
        self.assertEqual(L.live_unlisted_blocked_reason(59, 1161), "list_not_full_set:59/1161")

    def test_expire_share_gate_matches_absence_sweep(self):
        # 2026-10-12 带着存量时李宁 168 / 328：过半，默认拦；清存量那一次由人放宽
        self.assertEqual(L.expire_blocked_reason(168, 328, 0.5), "too_many:168/328")
        self.assertIsNone(L.expire_blocked_reason(168, 328, 0.6))
        self.assertIsNone(L.expire_blocked_reason(164, 328, 0.5))
        self.assertIsNone(L.expire_blocked_reason(0, 0, 0.5))

    def test_tiny_portals_are_not_frozen_by_the_share_gate(self):
        # 在招不足 8 行的小门户：3 行里停了 2 行不许因为「过半」永远下不了架（与 plan_absence_sweep 同一个下限）
        self.assertIsNone(L.expire_blocked_reason(2, 3, 0.5))


class _Prober:
    """按岗位给回答；同一个岗第 n 次问可以给不同回答。记下问过谁。"""

    def __init__(self, answers, default="unknown"):
        self.answers, self.default, self.asked = answers, default, []

    def __call__(self, ref):
        self.asked.append(ref)
        answer = self.answers.get(ref, self.default)
        if isinstance(answer, list):
            n = sum(1 for r in self.asked if r == ref)
            return answer[min(n, len(answer)) - 1]
        return answer


def _answers(**extra):
    answers = {_ref(900): "live", _ref(901): "live", L.fake_ref(_ref(900)): "gone"}
    answers.update(extra)
    return answers


class ReconcileSourceTest(unittest.TestCase):
    SOURCE = {"id": "s1", "company": "测试公司", "source_url": BASE}

    def _go(self, prober, *, candidates, controls=(_url(900), _url(901)), active=1000, seen=900, run=None,
            apply=True, max_fraction=0.5, source=None):
        expired = []

        def expire_fn(source_id, ids, not_seen_since):
            expired.append((source_id, list(ids), not_seen_since))
            return len(ids)

        rec, blocked = L.reconcile_source(
            source or self.SOURCE, run if run is not None else _run(), active=active, seen=seen,
            candidates=candidates, controls=list(controls), probe_fn=prober, expire_fn=expire_fn, apply=apply,
            max_fraction=max_fraction, now=NOW, threads=1)
        return rec, blocked, expired

    def test_expires_only_rows_that_read_gone_twice(self):
        prober = _Prober({**_answers(), _ref(1): "gone", _ref(2): "gone", _ref(3): "live"})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1)), ("r2", _url(2)), ("r3", _url(3)), ("r4", _url(4))])
        self.assertFalse(blocked)
        self.assertEqual(expired, [("s1", ["r1", "r2"], RUN_START)])
        self.assertEqual((rec["candidates"], rec["expire"], rec["keep_live_unlisted"], rec["keep_unknown"], rec["expired"]),
                         (4, 2, 1, 1, 2))

    def test_gone_once_then_live_is_not_expired(self):
        prober = _Prober({**_answers(), _ref(1): ["gone", "live"], _ref(2): ["gone", "unknown"]})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1)), ("r2", _url(2))])
        self.assertEqual(expired, [])
        self.assertEqual(rec["keep_unknown"], 2)

    def test_dry_run_reports_but_does_not_write(self):
        prober = _Prober({**_answers(), _ref(1): "gone"})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))], apply=False)
        self.assertEqual(expired, [])
        self.assertEqual(rec["expire"], 1)
        self.assertNotIn("expired", rec)

    def test_no_candidates_means_no_requests_at_all(self):
        prober = _Prober(_answers())
        rec, blocked, expired = self._go(prober, candidates=[])
        self.assertEqual((blocked, expired, prober.asked), (False, [], []))

    def test_run_not_usable_means_no_requests_and_no_writes(self):
        for run, reason in ((_run(coverage_complete=False), "list_incomplete"), (_run(status="failed"), "run_failed"),
                            (_run(finished_at=None, status="running"), "run_in_progress")):
            prober = _Prober({**_answers(), _ref(1): "gone"})
            rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))], run=run)
            self.assertEqual((rec.get("skipped"), blocked, expired, prober.asked), (reason, False, [], []), reason)

    def test_source_that_only_takes_a_filtered_part_of_the_portal_is_skipped(self):
        # 源地址带门户筛选（麦当劳只接「管培」）：它的列表本来就不是门户全集，缺席说明不了什么
        prober = _Prober({**_answers(), _ref(1): "gone"})
        source = {**self.SOURCE, "source_url": BASE + "#/jobs?keyword=管培"}
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))], source=source)
        self.assertEqual((rec.get("skipped"), blocked, expired, prober.asked), ("filtered_list", False, [], []))

    def test_source_whose_address_is_not_a_moka_portal_is_skipped(self):
        prober = _Prober({**_answers(), _ref(1): "gone"})
        source = {**self.SOURCE, "source_url": "https://careers.example.com/jobs"}
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))], source=source)
        self.assertEqual((rec.get("skipped"), blocked, expired, prober.asked), ("portal_unparsed", False, [], []))

    def test_fewer_rows_seen_in_the_run_than_the_run_reported_is_skipped(self):
        # 抓取记录说这一轮入库 900 行，库里这一轮被刷新的只有 600 行：这条记录描述的不是库里的状态，不拿它当完整列表
        prober = _Prober({**_answers(), _ref(1): "gone"})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))], seen=600)
        self.assertEqual((rec.get("skipped"), blocked, expired, prober.asked), ("seen_lt_found:600/900", False, [], []))

    def test_small_shortfall_after_the_run_is_tolerated(self):
        # 这一轮之后有几行被巡检下架了：在招里这一轮见到的比抓取记录少一点，属正常，不能因此整条源不核
        prober = _Prober({**_answers(), _ref(1): "gone"})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))], seen=880)
        self.assertEqual(expired, [("s1", ["r1"], RUN_START)])

    def test_failed_control_blocks_the_whole_source(self):
        prober = _Prober({**_answers(), _ref(901): "gone", _ref(1): "gone"})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))])
        self.assertEqual((rec["blocked"], blocked, expired), ("control_failed", True, []))

    def test_control_that_degrades_while_probing_blocks_the_whole_source(self):
        # 对照开头是好的，探完再过一遍时在招岗读成了已停（接口中途退化）→ 这一轮读到的都不算数
        prober = _Prober({**_answers(), _ref(900): ["live", "gone"], _ref(1): "gone"})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))], controls=(_url(900),))
        self.assertEqual((rec["blocked"], expired), ("control_failed", []))

    def test_no_listed_row_to_use_as_control_is_skipped_without_requests(self):
        # 这一轮一个岗都没见到（门户清空了）：没有阳性对照，不下架，留给浏览器巡检。这是常态，不算异常。
        prober = _Prober({**_answers(), _ref(1): "gone"})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))], controls=(), seen=0, run=_run(jobs_found=0))
        self.assertEqual((rec.get("skipped"), blocked, expired, prober.asked), ("no_listed_rows", False, [], []))

    def test_listed_rows_of_another_portal_are_not_used_as_controls(self):
        # 别的门户的行就算读到在招，也证明不了这个门户的详情请求是好的
        prober = _Prober({**_answers(), _ref(5, OTHER): "gone", _ref(1): "gone"})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1))], controls=(_url(5, OTHER), _url(900)))
        self.assertEqual(expired, [("s1", ["r1"], RUN_START)])
        self.assertNotIn(_ref(5, OTHER), prober.asked)
        rec, blocked, expired = self._go(_Prober({_ref(5, OTHER): "live", L.fake_ref(_ref(5, OTHER)): "gone", _ref(1): "gone"}),
                                         candidates=[("r1", _url(1))], controls=(_url(5, OTHER),))
        self.assertEqual((rec.get("skipped"), expired), ("no_listed_rows", []))

    def test_second_pass_does_not_repeat_the_control_that_just_ran(self):
        prober = _Prober({**_answers(), _ref(1): "gone"})
        self._go(prober, candidates=[("r1", _url(1))], controls=(_url(900),))
        # 第一遍：开头 + 探完；第二遍：只在探完之后。共 3 次，而不是 4 次。
        self.assertEqual(prober.asked.count(_ref(900)), 3)
        self.assertEqual(prober.asked.count(_ref(1)), 2)

    def test_too_many_live_unlisted_blocks(self):
        answers = _answers()
        cands = []
        for n in range(1, 11):
            answers[_ref(n)] = "live" if n <= 6 else "gone"
            cands.append((f"r{n}", _url(n)))
        rec, blocked, expired = self._go(_Prober(answers), candidates=cands, active=10, seen=0, run=_run(jobs_found=0))
        self.assertEqual((rec["blocked"], blocked, expired), ("list_not_full_set:6/10", True, []))

    def test_expire_share_gate_blocks_and_can_be_relaxed_explicitly(self):
        answers = _answers()
        cands = []
        for n in range(1, 7):
            answers[_ref(n)] = "gone"
            cands.append((f"r{n}", _url(n)))
        rec, blocked, expired = self._go(_Prober(answers), candidates=cands, active=10, seen=4, run=_run(jobs_found=4))
        self.assertEqual((rec["blocked"], blocked, expired), ("too_many:6/10", True, []))
        rec, blocked, expired = self._go(_Prober(answers), candidates=cands, active=10, seen=4, run=_run(jobs_found=4),
                                         max_fraction=0.7)
        self.assertEqual((blocked, len(expired[0][1])), (False, 6))

    def test_candidates_of_another_portal_are_never_probed(self):
        # 行的链接不在这条源自己的门户下（归属错位 / 历史残留）：不替它下结论
        prober = _Prober({**_answers(), _ref(1, OTHER): "gone"})
        rec, blocked, expired = self._go(prober, candidates=[("r1", _url(1, OTHER))])
        self.assertEqual(expired, [])
        self.assertEqual(rec["keep_other_portal"], 1)
        self.assertNotIn(_ref(1, OTHER), prober.asked)


class ReconcileAllTest(unittest.TestCase):
    def _go(self, sources, *, past_deadline=lambda: False, robots_allowed=lambda origin: True, answers=None,
            candidates=None):
        prober = _Prober(answers if answers is not None else {**_answers(), _ref(1): "gone"})
        runs = {s["id"]: _run(source_id=s["id"]) for s in sources}
        loaded = L.Loaded(active={s["id"]: 1000 for s in sources}, seen={s["id"]: 900 for s in sources},
                          candidates=candidates if candidates is not None else {s["id"]: [("r-" + s["id"], _url(1))] for s in sources},
                          controls={s["id"]: [_url(900), _url(901)] for s in sources})
        expired = []
        report = L.reconcile_all(
            sources, runs, loaded, probe_fn=prober,
            expire_fn=lambda sid, ids, since: expired.append((sid, list(ids))) or len(ids),
            robots_allowed=robots_allowed, apply=True, max_fraction=0.5, now=NOW, past_deadline=past_deadline, threads=1)
        return report, expired, prober

    SOURCES = [{"id": "s1", "company": "甲", "source_url": BASE}, {"id": "s2", "company": "乙", "source_url": BASE}]

    def test_every_source_is_reported(self):
        report, expired, _ = self._go(self.SOURCES)
        self.assertEqual([r["company"] for r in report], ["甲", "乙"])
        self.assertEqual(expired, [("s1", ["r-s1"]), ("s2", ["r-s2"])])

    def test_sources_after_the_deadline_are_blocked_not_silently_dropped(self):
        ticks = iter([False, True])
        report, expired, prober = self._go(self.SOURCES, past_deadline=lambda: next(ticks))
        self.assertEqual(expired, [("s1", ["r-s1"])])
        self.assertEqual(report[1].get("blocked"), "deadline")

    def test_deadline_does_not_flag_sources_that_had_nothing_to_check(self):
        report, expired, _ = self._go(self.SOURCES, past_deadline=lambda: True, candidates={})
        self.assertEqual([r.get("blocked") for r in report], [None, None])

    def test_robots_disallow_skips_the_source_without_requests(self):
        report, expired, prober = self._go(self.SOURCES[:1], robots_allowed=lambda origin: False)
        self.assertEqual((report[0].get("skipped"), expired, prober.asked), ("robots", [], []))

    def test_one_source_blowing_up_does_not_stop_the_others(self):
        def boom(ref):
            raise RuntimeError("x")

        runs = {s["id"]: _run(source_id=s["id"]) for s in self.SOURCES}
        loaded = L.Loaded(active={"s1": 1000, "s2": 1000}, seen={"s1": 900, "s2": 900},
                          candidates={"s1": [("r1", _url(1))]}, controls={"s1": [_url(900)]})
        report = L.reconcile_all(self.SOURCES, runs, loaded, probe_fn=boom, expire_fn=lambda *a: 0,
                                 robots_allowed=lambda origin: True, apply=True, max_fraction=0.5, now=NOW,
                                 past_deadline=lambda: False, threads=1)
        self.assertEqual(report[0].get("blocked"), "error:RuntimeError")
        self.assertNotIn("blocked", report[1])


class _Resp:
    def __init__(self, status_code, body):
        self.status_code, self._body = status_code, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Client:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def post(self, url, json=None):
        self.calls.append((url, json))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class _NoWait:
    def wait(self):
        pass


class ProbeTest(unittest.TestCase):
    REF = L.DetailRef("https://talent.catl.com", "catlhr", 96144, "76b208c8-4a05-4a7b-842d-a33066f21cea")

    def _probe(self, replies):
        client = _Client(replies)
        with mock.patch.object(L.time, "sleep") as sleep:
            state = L.probe(client, _NoWait(), self.REF)
        return state, client, sleep

    def test_asks_the_portal_own_domain_with_the_portal_and_job_ids(self):
        state, client, _ = self._probe([_Resp(200, _GONE_BODY)])
        self.assertEqual(state, "gone")
        self.assertEqual(client.calls, [("https://talent.catl.com/api/outer/ats-apply/website/job",
                                         {"orgId": "catlhr", "jobId": "76b208c8-4a05-4a7b-842d-a33066f21cea",
                                          "siteId": 96144, "locale": "zh-CN"})])

    def test_retries_what_it_cannot_read_and_gives_up_as_unknown(self):
        state, client, sleep = self._probe([_Resp(500, None), _Resp(200, ValueError("not json")), _Resp(200, _body(400))])
        self.assertEqual((state, len(client.calls)), ("unknown", 3))
        self.assertEqual(sleep.call_count, 2)   # 最后一次失败之后不再白等

    def test_network_error_then_answer(self):
        state, client, _ = self._probe([httpx.ConnectError("x"), _Resp(200, _LIVE_BODY)])
        self.assertEqual((state, len(client.calls)), ("live", 2))


class PacerTest(unittest.TestCase):
    def test_spaces_requests_at_the_configured_rate(self):
        clock, slept = [100.0], []
        pacer = L._Pacer(4, clock=lambda: clock[0], sleep=slept.append)
        pacer.wait()
        pacer.wait()
        pacer.wait()
        self.assertEqual([round(s, 2) for s in slept], [0.25, 0.5])   # 第一个不等，之后每个排在上一个 0.25 秒之后


class _Cursor:
    def __init__(self, returning):
        self.sql, self.params, self._returning = [], [], returning

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(params)

    def fetchall(self):
        return [(i,) for i in self._returning]


class _Conn:
    def __init__(self, returning):
        self.cur = _Cursor(returning)

    def cursor(self):
        return self.cur


class ExpireRowsTest(unittest.TestCase):
    def test_statement_only_touches_active_rows_not_seen_since_the_run(self):
        conn = _Conn(returning=["r1"])
        events = []
        n = L.expire_rows(conn, "s1", ["r1", "r2"], RUN_START, record_events=lambda c, ev: events.extend(ev))
        sql = re.sub(r"\s+", " ", conn.cur.sql[0]).replace(" = ", "=")
        self.assertIn("status='expired'", sql)
        self.assertIn("status='active'", sql)
        self.assertIn("last_seen_at < %s", sql)
        self.assertIn("source_id=%s", sql)
        self.assertIn(RUN_START, conn.cur.params[0])
        self.assertEqual(n, 1)
        # 事件只给真被改到的行（r2 在核验期间被抓取刷新过，语句没改到它）
        self.assertEqual([e[1:3] for e in events], [("CLOSED", "r1")])

    def test_empty_id_list_does_not_touch_the_database(self):
        conn = _Conn(returning=[])
        self.assertEqual(L.expire_rows(conn, "s1", [], RUN_START, record_events=lambda c, ev: None), 0)
        self.assertEqual(conn.cur.sql, [])


class SqlShapeTest(unittest.TestCase):
    """三条取数 SQL 真跑要连库（上线前在本机对真库演练过）；这里只钉住不许丢的条件。"""

    @staticmethod
    def _flat(sql):
        return re.sub(r"\s+", " ", sql)

    def test_candidates_are_active_rows_not_seen_in_the_run(self):
        sql = self._flat(L._CANDIDATES_SQL)
        self.assertIn("j.status = 'active'", sql)
        self.assertIn("j.last_seen_at < r.run_start", sql)

    def test_stats_join_carries_the_status_so_it_can_use_the_active_index(self):
        # jobs 上按 source_id 的索引只有带 status='active' 条件的那一条；条件不在 join 里就是全表扫 1.1GB
        self.assertIn("on j.source_id = r.source_id and j.status = 'active'", self._flat(L._STATS_SQL))
        self.assertIn("j.last_seen_at >= r.run_start", self._flat(L._STATS_SQL))

    def test_controls_are_active_rows_seen_in_the_run(self):
        sql = self._flat(L._CONTROLS_SQL)
        self.assertIn("j.status = 'active'", sql)
        self.assertIn("j.last_seen_at >= r.run_start", sql)


class ExitCodeTest(unittest.TestCase):
    def test_clean_run_is_zero(self):
        self.assertEqual(L.exit_code([{"company": "a"}, {"company": "b", "skipped": "list_incomplete"}], apply=True), 0)

    def test_blocked_source_turns_the_run_red(self):
        self.assertEqual(L.exit_code([{"company": "a", "blocked": "control_failed"}], apply=True), L.EXIT_BLOCKED)
        self.assertEqual(L.exit_code([{"company": "a", "blocked": "control_failed"}], apply=False), L.EXIT_BLOCKED)

    def test_share_gate_alone_is_only_a_number_in_dry_run(self):
        report = [{"company": "李宁", "blocked": "too_many:168/328"}]
        self.assertEqual(L.exit_code(report, apply=False), 0)
        self.assertEqual(L.exit_code(report, apply=True), L.EXIT_BLOCKED)

    def test_no_sources_at_all_is_red(self):
        self.assertEqual(L.exit_code([], apply=False), L.EXIT_BLOCKED)

    def test_run_level_block_is_red_even_when_no_source_is_blocked(self):
        report = [{"company": "a", "skipped": "run_stale"}]
        self.assertEqual(L.exit_code(report, apply=False, run_blocked="no_usable_sources:0/1"), L.EXIT_BLOCKED)
        self.assertEqual(L.exit_code(report, apply=True, run_blocked="no_usable_sources:0/1"), L.EXIT_BLOCKED)


class WorkflowContractTest(unittest.TestCase):
    PATH = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "moka-liveness.yml")

    def setUp(self):
        with open(self.PATH, encoding="utf-8") as f:
            self.text = f.read()

    def test_manual_trigger_defaults_to_dry_run(self):
        self.assertIn("workflow_dispatch", self.text)
        self.assertRegex(self.text, r'apply:\s*\n\s*description:[^\n]*\n\s*required: false\s*\n\s*default: "false"')
        self.assertIn('if [ "${APPLY:-}" = "true" ]; then args+=(--apply); fi', self.text)

    def test_scheduled_runs_write_with_the_default_share_gate(self):
        # 定时轮次写库（创始人同意落库后加）；占比上限用默认值——清存量时的放宽只给手动那一次
        self.assertRegex(self.text, r'(?m)^\s*-\s*cron\s*:\s*"[^"]+"')
        self.assertIn("APPLY: ${{ github.event_name == 'schedule' && 'true' || github.event.inputs.apply }}", self.text)
        self.assertIn('--max-expire-fraction "${MAX_EXPIRE_FRACTION:-0.5}"', self.text)

    def test_schedule_runs_after_the_nightly_heavy_crawl(self):
        # Moka 在重档里抓：cron 写 UTC 18:00，实际 21:00~23:35 才开跑、最长 180 分钟。
        # 排在它后面才核得到当晚那一轮；还在跑的源本轮会跳过（run_in_progress），排太早就整晚白跑。
        hour = int(re.search(r'cron:\s*"\d+ (\d+) \* \* \*"', self.text).group(1))
        self.assertTrue(3 <= hour <= 6, hour)

    def test_single_flight(self):
        self.assertRegex(self.text, r"concurrency:\s*\n\s*group: moka-liveness\s*\n\s*cancel-in-progress: false")

    def test_tool_deadline_leaves_room_before_the_job_timeout(self):
        # 工具自己的总时限要早于 workflow 的超时：被外部杀掉的轮次既没有报告也没有台账
        timeout = int(re.search(r"timeout-minutes:\s*(\d+)", self.text).group(1))
        self.assertGreaterEqual(timeout - L.DEFAULT_DEADLINE_MINUTES, 20)


if __name__ == "__main__":
    unittest.main()
