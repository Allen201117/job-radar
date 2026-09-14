"""重档分片计划（shard_plan.py + run._shard_by_plan）单测。不打网络、不连库。

守的事故：2026-09-08/10/11/12 enrich (2) 连续撞 180 分钟被取消。按源数装箱不知道国聘
www.iguopin.com 28 个源同主机一队串行要跑 91~131 分钟，又往那片塞了 70 多个浏览器源，
浏览器档要等线程池跑完才开始 → 尾巴 ~80 个源当晚一行 crawl_runs 都没有。
"""
import datetime as dt
import json
import os
import pathlib
import tempfile
import unittest
import zlib
from unittest import mock

import run
import shard_plan as P

UTC = dt.timezone.utc


def _src(sid, url, adapter="_fake_httpx"):
    return {"id": sid, "source_url": url, "adapter_name": adapter, "company": sid}


def _host(s):
    from urllib.parse import urlparse
    return urlparse(s["source_url"]).netloc


class TimestampAndNightTest(unittest.TestCase):
    def test_postgres_trimmed_fraction_and_z_parse(self):
        # Postgres 会去掉小数尾零；Python 3.9 的 fromisoformat 不认 5 位小数
        self.assertEqual(P._parse_ts("2026-09-12T21:18:31.33364+00:00"),
                         dt.datetime(2026, 9, 12, 21, 18, 31, 333640, tzinfo=UTC))
        self.assertEqual(P._parse_ts("2026-09-12T21:18:31Z"),
                         dt.datetime(2026, 9, 12, 21, 18, 31, tzinfo=UTC))
        self.assertEqual(P._parse_ts("2026-09-12 21:18:31.5+08"),
                         dt.datetime(2026, 9, 12, 13, 18, 31, 500000, tzinfo=UTC))
        self.assertIsNone(P._parse_ts(None))
        self.assertIsNone(P._parse_ts("not a time"))

    def test_one_enrich_round_is_one_night_across_utc_midnight(self):
        self.assertEqual(P.night_of(dt.datetime(2026, 9, 12, 20, 2, tzinfo=UTC)), dt.date(2026, 9, 12))
        self.assertEqual(P.night_of(dt.datetime(2026, 9, 13, 0, 40, tzinfo=UTC)), dt.date(2026, 9, 12))
        self.assertEqual(P.night_of(dt.datetime(2026, 9, 13, 11, 59, tzinfo=UTC)), dt.date(2026, 9, 12))
        self.assertEqual(P.night_of(dt.datetime(2026, 9, 13, 12, 0, tzinfo=UTC)), dt.date(2026, 9, 13))


class NightlyMaxTest(unittest.TestCase):
    def test_takes_longest_row_per_night_and_ignores_unfinished(self):
        rows = [
            # 同一晚：重档全量富化 600s，campus-crawl 列表车道 skipped 1s → 取 600
            {"source_id": "ig", "started_at": "2026-09-12T20:02:53+00:00", "finished_at": "2026-09-12T20:12:53+00:00"},
            {"source_id": "ig", "started_at": "2026-09-12T21:17:01+00:00", "finished_at": "2026-09-12T21:17:02+00:00"},
            # 进程被杀留下的 running 占位符：没有 finished_at，不代表耗时
            {"source_id": "ig", "started_at": "2026-09-11T22:00:00+00:00", "finished_at": None},
            {"source_id": "ig", "started_at": "2026-09-11T20:00:00+00:00", "finished_at": "2026-09-11T20:05:00+00:00"},
            {"source_id": None, "started_at": "2026-09-11T20:00:00+00:00", "finished_at": "2026-09-11T20:05:00+00:00"},
        ]
        out = P.nightly_max_seconds(rows)
        self.assertEqual(out, {"ig": {dt.date(2026, 9, 12): 600.0, dt.date(2026, 9, 11): 300.0}})


class UpperQuantileTest(unittest.TestCase):
    def test_nearest_rank_leans_high(self):
        self.assertEqual(P.upper_quantile([5], 0.75), 5)
        self.assertEqual(P.upper_quantile([1, 9], 0.75), 9)          # n=2 取大的，不往小值偏
        self.assertEqual(P.upper_quantile([4, 1, 3, 2], 0.75), 3)
        self.assertEqual(P.upper_quantile([7, 1, 6, 2, 5, 3, 4], 0.75), 6)  # 7 晚去掉最大那一次


class EstimateTest(unittest.TestCase):
    def test_window_is_the_seven_nights_before_tonight(self):
        tonight = dt.date(2026, 9, 13)
        history = {"a": {tonight: 9999.0,                              # 当晚的不完整数据：不算
                         dt.date(2026, 9, 12): 100.0,
                         dt.date(2026, 9, 6): 200.0,                   # 7 晚前的第 7 晚：算
                         dt.date(2026, 9, 5): 8888.0}}                 # 第 8 晚：不算
        est, stats = P.estimate_source_seconds([_src("a", "https://a.com")], history, current_night=tonight)
        self.assertEqual(est["a"], 200.0)
        self.assertEqual(stats["with_history"], 1)

    def test_new_sources_default_to_adapter_median_then_global(self):
        tonight = dt.date(2026, 9, 13)
        srcs = [_src("m1", "https://app.mokahr.com/apply/t1/1", "moka"),
                _src("m2", "https://app.mokahr.com/apply/t2/1", "moka"),
                _src("m3", "https://app.mokahr.com/apply/t3/1", "moka"),
                _src("new_moka", "https://app.mokahr.com/apply/t4/1", "moka"),
                _src("new_adapter", "https://x.com", "brand_new")]
        history = {"m1": {dt.date(2026, 9, 12): 10.0}, "m2": {dt.date(2026, 9, 12): 30.0},
                   "m3": {dt.date(2026, 9, 12): 90.0}}
        est, stats = P.estimate_source_seconds(srcs, history, current_night=tonight)
        self.assertEqual(est["new_moka"], 30.0)
        self.assertEqual(est["new_adapter"], P.DEFAULT_SOURCE_SECONDS)
        self.assertEqual((stats["with_history"], stats["defaulted_by_adapter"], stats["defaulted_global"]),
                         (3, 1, 1))


class PoolWallTest(unittest.TestCase):
    def test_longest_same_host_queue_is_the_floor(self):
        self.assertEqual(P.pool_wall_seconds([6000, 10, 10, 10], 6), 6000)
        self.assertEqual(P.pool_wall_seconds([10] * 6, 2), 30)
        self.assertEqual(P.pool_wall_seconds([], 6), 0.0)

    def test_follows_queue_order_like_thread_pool_map(self):
        # 2 线程：100,100 先占满两个线程，第三队 50 排到 100 之后 → 150
        self.assertEqual(P.pool_wall_seconds([100, 100, 50], 2), 150)


def _incident_sources():
    """缩小版事故现场：
    - 慢主机 slow.example.com：10 个并发档源、每个 600s（同主机一队串行 = 100 分钟）
    - 30 个各自独立主机的并发档快源、每个 30s
    - 24 个串行浏览器源（各自独立 key）、每个 300s
    按源数装箱：慢主机 key「重 10」，第一个进 0 号片，照样分到 1/3 的串行源。"""
    srcs, secs = [], {}
    for i in range(10):
        srcs.append(_src(f"slow{i}", f"https://slow.example.com/job?company={i}"))
        secs[f"slow{i}"] = 600.0
    for i in range(30):
        srcs.append(_src(f"fast{i}", f"https://fast{i}.example.com/jobs"))
        secs[f"fast{i}"] = 30.0
    for i in range(24):
        srcs.append(_src(f"br{i}", f"https://br{i}.example.com/jobs", "_fake_browser"))
        secs[f"br{i}"] = 300.0
    return srcs, secs


def _is_conc(s):
    return s["adapter_name"] != "_fake_browser"


def _wall(members, secs, workers=6):
    queues = {}
    for s in members:
        if _is_conc(s):
            queues.setdefault(_host(s), 0.0)
            queues[_host(s)] += secs[s["id"]]
    return (P.pool_wall_seconds(list(queues.values()), workers)
            + sum(secs[s["id"]] for s in members if not _is_conc(s)))


class PlanShardsTest(unittest.TestCase):
    N = 3

    def _plan(self, srcs, secs, n=None):
        return P.plan_shards(srcs, secs, shard_count=n or self.N, workers=6, key_fn=run._shard_key_of,
                             host_fn=_host, is_concurrent_fn=_is_conc)

    def _members(self, srcs, plan, n=None):
        n = n or self.N
        return {i: [s for s in srcs if P.shard_of_key(run._shard_key_of(s), plan["keys"], n) == i]
                for i in range(n)}

    def test_slow_host_shard_no_longer_carries_browser_tail(self):
        srcs, secs = _incident_sources()
        conc = [s for s in srcs if _is_conc(s)]
        serial = [s for s in srcs if not _is_conc(s)]
        old = [_wall(run._shard_by_host(conc, i, self.N) + run._shard_by_host(serial, i, self.N), secs)
               for i in range(self.N)]
        plan = self._plan(srcs, secs)
        new = [_wall(m, secs) for m in self._members(srcs, plan).values()]
        # 旧：慢主机那片 = 100 分钟线程池 + 8 个 5 分钟浏览器源 = 140 分钟
        self.assertEqual(max(old), 6000 + 8 * 300)
        # 新：慢主机那片只剩它自己；24 个浏览器源摊到另外两片 → 最长片就是慢主机一队本身
        self.assertEqual(max(new), 6000)
        slow_shard = plan["keys"]["slow.example.com"]
        self.assertEqual(plan["shards"][slow_shard]["serial"], 0)
        self.assertAlmostEqual(plan["shards"][slow_shard]["est_minutes"], 100.0)

    def test_partition_is_exact_and_same_key_same_shard_across_tiers(self):
        srcs, secs = _incident_sources()
        # 同一个 key 同时有并发档与串行档源（beisen 那种按源分档）→ 必须同片，不能两 runner 同时打
        srcs.append(_src("mixed_c", "https://mixed.example.com/a"))
        srcs.append(_src("mixed_s", "https://mixed.example.com/b", "_fake_browser"))
        secs.update({"mixed_c": 50.0, "mixed_s": 50.0})
        members = self._members(srcs, self._plan(srcs, secs))
        ids = [s["id"] for group in members.values() for s in group]
        self.assertEqual(sorted(ids), sorted(s["id"] for s in srcs), "有源被漏抓或重抓")
        shard_of = {s["id"]: i for i, group in members.items() for s in group}
        self.assertEqual(shard_of["mixed_c"], shard_of["mixed_s"])
        slow = {shard_of[f"slow{i}"] for i in range(10)}
        self.assertEqual(len(slow), 1, "同主机被拆到多片")

    def test_moka_tenants_still_spread(self):
        srcs = [_src(f"m{i}", f"https://app.mokahr.com/apply/tenant{i}/{i}", "_fake_browser") for i in range(12)]
        secs = {s["id"]: 60.0 for s in srcs}
        sizes = [len(g) for g in self._members(srcs, self._plan(srcs, secs)).values()]
        self.assertEqual(sizes, [4, 4, 4])

    def test_deterministic_regardless_of_dict_order(self):
        srcs, secs = _incident_sources()
        a = self._plan(srcs, secs)
        b = self._plan(srcs, dict(reversed(list(secs.items()))))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_every_source_planned_once_even_when_estimate_missing(self):
        srcs, secs = _incident_sources()
        plan = self._plan(srcs, {})  # 没有任何估计 → 全用默认值，也必须是完整划分
        self.assertEqual(set(plan["keys"]), {run._shard_key_of(s) for s in srcs})
        self.assertEqual(sum(sh["sources"] for sh in plan["shards"]), len(srcs))


class PlanWarningsTest(unittest.TestCase):
    """「单个 key 自己超了」与「总量顶满」处置相反，预警必须分开说，不许一律说成单个 key 超了。"""

    def _plan(self, shards):
        return {"shard_count": len(shards), "shards": [
            {"index": i, "est_minutes": est, "top_keys": top} for i, (est, top) in enumerate(shards)]}

    def test_single_key_over_threshold_is_named(self):
        warnings = P.plan_warnings(self._plan([(175.0, [["www.iguopin.com", 172.0]]), (60.0, [["a.com", 5.0]])]))
        self.assertEqual(len(warnings), 2)
        self.assertIn("www.iguopin.com 自己预计就要 172.0", warnings[0])
        self.assertIn("1/2 片", warnings[1])

    def test_capacity_warning_does_not_blame_a_key(self):
        warnings = P.plan_warnings(self._plan([(180.7, [["job3.ccb.com", 20.1]])] * 3))
        self.assertEqual(len(warnings), 1)
        self.assertIn("3/3 片", warnings[0])
        self.assertNotIn("自己预计就要", warnings[0])

    def test_quiet_when_under_threshold(self):
        self.assertEqual(P.plan_warnings(self._plan([(120.0, [["www.iguopin.com", 110.0]])])), [])


class ShardOfKeyTest(unittest.TestCase):
    def test_planned_key_uses_plan(self):
        self.assertEqual(P.shard_of_key("a.com", {"a.com": 4}, 6), 4)

    def test_unplanned_or_invalid_falls_back_to_crc32_not_hash(self):
        # 必须是 zlib.crc32：各 runner 是独立进程，hash() 每进程加盐不同 → 映射不一致
        for i in range(50):
            key = f"late{i}.example.com"
            self.assertEqual(P.shard_of_key(key, {}, 6), zlib.crc32(key.encode()) % 6)
        self.assertEqual(P.shard_of_key("www.iguopin.com", {}, 6), 1)
        crc = zlib.crc32(b"a.com") % 6
        self.assertEqual(P.shard_of_key("a.com", {"a.com": 9}, 6), crc)      # 越界
        self.assertEqual(P.shard_of_key("a.com", {"a.com": True}, 6), crc)   # bool 不是片号
        self.assertEqual(P.shard_of_key("a.com", {"a.com": "2"}, 6), crc)


class LoadPlanTest(unittest.TestCase):
    def _write(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        self.addCleanup(os.remove, path)
        return path

    def test_rejects_mismatch_instead_of_guessing(self):
        good = {"version": P.PLAN_VERSION, "shard_count": 6, "keys": {"a.com": 0}}
        self.assertEqual(P.load_plan(self._write(good), 6)["keys"], {"a.com": 0})
        with self.assertRaises(ValueError):
            P.load_plan(self._write({**good, "shard_count": 7}), 6)
        with self.assertRaises(ValueError):
            P.load_plan(self._write({**good, "version": 999}), 6)
        with self.assertRaises(ValueError):
            P.load_plan(self._write({**good, "keys": {}}), 6)
        with self.assertRaises(ValueError):
            P.load_plan(self._write([1, 2]), 6)
        with self.assertRaises(FileNotFoundError):
            P.load_plan("/nonexistent/shard-plan.json", 6)


class BuildPlanTest(unittest.TestCase):
    def test_uses_run_tiering_and_history_window(self):
        srcs = [_src("h", "https://h.example.com/jobs", "greenhouse"),       # httpx-safe
                _src("b", "https://b.example.com/jobs", "_fake_browser")]    # 未知 adapter → 串行
        captured = {}

        def fake_history(sb, since):
            captured["since"] = since
            return [{"source_id": "b", "started_at": "2026-09-12T20:00:00+00:00",
                     "finished_at": "2026-09-12T20:10:00+00:00"}]

        now = dt.datetime(2026, 9, 13, 18, 0, tzinfo=UTC)
        with mock.patch("db.get_sources", return_value=list(srcs)), \
                mock.patch.object(P, "fetch_history_rows", side_effect=fake_history):
            plan = P.build_plan("SB", shard_count=2, workers=6, tier="browser", now=now)
        self.assertEqual(captured["since"], dt.datetime(2026, 9, 6, 12, 0, tzinfo=UTC))
        self.assertEqual(set(plan["keys"]), {"b.example.com"}, "tier=browser 不该给 httpx 源排片")
        self.assertEqual(plan["sources_total"], 1)
        self.assertEqual(max(sh["est_serial_minutes"] for sh in plan["shards"]), 10.0)


class PlanMainTest(unittest.TestCase):
    """plan job 读到 0 个源（Supabase 抖一下）时必须自己失败、不写文件：
    否则 job 绿 → 6 片带着空计划去 load_plan → 一起抛错，当晚零产出，而不是一起退回按源数装箱。"""

    def _run_main(self, plan):
        out = os.path.join(tempfile.mkdtemp(), "shard-plan.json")
        with mock.patch("db.get_supabase", return_value="SB"), \
                mock.patch.object(P, "build_plan", return_value=plan), \
                mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}):
            code = P.main(["--shard-count", "2", "--out", out])
        return code, out

    def test_empty_plan_fails_without_writing_file(self):
        code, out = self._run_main({"version": P.PLAN_VERSION, "shard_count": 2, "workers": 6, "keys": {},
                                    "shards": [], "sources_total": 0})
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(out))

    def test_valid_plan_is_written_and_loadable(self):
        srcs, secs = _incident_sources()
        plan = P.plan_shards(srcs, secs, shard_count=2, workers=6, key_fn=run._shard_key_of,
                             host_fn=_host, is_concurrent_fn=_is_conc)
        code, out = self._run_main(plan)
        self.assertEqual(code, 0)
        self.assertEqual(P.load_plan(out, 2)["keys"], plan["keys"])


class RunCrawlWithPlanTest(unittest.TestCase):
    """run_crawl 按计划分片：各片并集 = 全量、两两不相交；计划坏了整片失败而不是悄悄退回按源数分。"""

    def setUp(self):
        self.sources = [_src("a", "https://a.com/list"), _src("b", "https://b.com/list"),
                        _src("c", "https://c.com/list", "_fake_browser"),
                        _src("late", "https://www.iguopin.com/job?company=x")]  # 计划之后新增
        patches = [
            mock.patch.object(run.db, "get_supabase", return_value="SB"),
            mock.patch.object(run.db, "get_sources", side_effect=lambda sb: [dict(s) for s in self.sources]),
            mock.patch.object(run.ops_runs, "record_ops_run", return_value=True),
            mock.patch.object(run, "_HTTPX_SAFE_ADAPTERS", run._HTTPX_SAFE_ADAPTERS | {"_fake_httpx"}),
            mock.patch.object(run, "_process_one_source", side_effect=self._record),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.processed = []
        fd, self.plan_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": P.PLAN_VERSION, "shard_count": 2,
                       "keys": {"a.com": 1, "b.com": 0, "c.com": 1}}, f)
        self.addCleanup(os.remove, self.plan_path)

    def _record(self, source, supabase):
        self.processed.append(source["id"])
        return {"status": "success", "created": 1, "updated": 0}

    def test_shards_follow_plan_and_cover_everything_once(self):
        per_shard = {}
        for i in range(2):
            self.processed = []
            run.run_crawl(shard_index=i, shard_count=2, shard_plan_path=self.plan_path)
            per_shard[i] = sorted(self.processed)
        self.assertEqual(per_shard[0], ["b"])
        # iguopin 不在计划里 → crc32 兜底（% 2 == 1），两片算出来一样
        self.assertEqual(per_shard[1], ["a", "c", "late"])
        everything = per_shard[0] + per_shard[1]
        self.assertEqual(sorted(everything), sorted(s["id"] for s in self.sources))

    def test_bad_plan_fails_the_shard_instead_of_falling_back(self):
        with self.assertRaises(ValueError):
            run.run_crawl(shard_index=0, shard_count=3, shard_plan_path=self.plan_path)
        with self.assertRaises(FileNotFoundError):
            run.run_crawl(shard_index=0, shard_count=2, shard_plan_path=self.plan_path + ".missing")
        self.assertEqual(self.processed, [], "计划读不到还抓了源 = 这一片在按另一套映射跑")

    def test_without_plan_keeps_count_based_sharding(self):
        seen = []
        for i in range(2):
            self.processed = []
            run.run_crawl(shard_index=i, shard_count=2)
            seen += self.processed
        self.assertEqual(sorted(seen), sorted(s["id"] for s in self.sources))


class WorkflowWiringTest(unittest.TestCase):
    """enrich-crawl.yml 的接线：片数一处定义、matrix 长度对得上、计划只在 plan 成功时带上。"""

    @classmethod
    def setUpClass(cls):
        cls.text = (pathlib.Path(__file__).resolve().parents[1]
                    / ".github" / "workflows" / "enrich-crawl.yml").read_text(encoding="utf-8")

    def test_shard_count_matches_matrix(self):
        count = int(self.text.split('SHARD_COUNT: "', 1)[1].split('"', 1)[0])
        matrix = self.text.split("shard: [", 1)[1].split("]", 1)[0]
        self.assertEqual([int(x) for x in matrix.split(",")], list(range(count)))
        self.assertEqual(self.text.count('--shard-count "$SHARD_COUNT"'), 2, "plan job 与各片必须用同一个片数")

    def test_plan_is_only_passed_when_plan_job_succeeded(self):
        self.assertIn("needs: plan", self.text)
        self.assertIn("CRAWL_SHARD_PLAN: ${{ needs.plan.result == 'success' && 'shard-plan/shard-plan.json' || '' }}",
                      self.text)
        self.assertIn("python crawler/shard_plan.py", self.text)
        self.assertIn("name: shard-plan", self.text)


if __name__ == "__main__":
    unittest.main()
