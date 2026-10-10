"""migrate_wt_rows_to_wecruit.py 的契约：按「wt postId = wecruit externalKey」逐岗对上才改；
没发布的渠道 / 标题不同 / 分不出的一律不动；dry-run 绝不写；逐行带旧链接条件；参数绑定。

对应关系本身在真数据上全集对过（2026-10-10 兴业证券：库里 94 个旧岗位号 ↔ 新门户三个渠道 94 个
externalKey，两个方向都是 0 个落单，94 个标题逐字相同）；这里钉住判定规则与调用形状。"""
import contextlib
import io
import json
import unittest

try:
    import migrate_wt_rows_to_wecruit as mw
    from adapters.hotjob import HotJobAdapter
    from rename_job_company import like_prefix
except ModuleNotFoundError:
    from crawler import migrate_wt_rows_to_wecruit as mw
    from crawler.adapters.hotjob import HotJobAdapter
    from crawler.rename_job_company import like_prefix

WT = "https://xyzq.hotjob.cn/wt/xyzq/"
PB = "https://xyzq.hotjob.cn/SU68fb2499b7da1347a9dd852c/pb"


def old(rt, pid):
    return f"{WT}mobweb/position/detail?brandCode=1&safe=Y&recruitType={rt}&postIdsAry={pid}"


def new(post_id, post_type):
    return f"{PB}/posDetail.html?postId={post_id}&postType={post_type}"


def post(key, title, post_id, post_type, rt, published=True):
    return mw.PortalPost(key, title, new(post_id, post_type), rt, published)


class PlanTest(unittest.TestCase):
    def test_matches_by_external_key_and_title(self):
        rewrites, skipped = mw.plan(
            [("r1", old(2, "273901"), "经济与金融研究院-机械军工行业研究员")],
            [post("273901", "经济与金融研究院-机械军工行业研究员", "6ab4922d", "society", 2)])
        self.assertEqual(rewrites, [("r1", old(2, "273901"), new("6ab4922d", "society"))])
        self.assertEqual(skipped, [])

    def test_unpublished_channel_is_never_a_target(self):
        """实习渠道没发布：列表接口照常回岗，但 posDetail?postType=intern 永远转圈——换过去等于换成另一条死链。"""
        rewrites, skipped = mw.plan(
            [("r1", old(12, "273602"), "投资银行业务总部-高端智造行业部实习生（深圳）")],
            [post("273602", "投资银行业务总部-高端智造行业部实习生（深圳）", "6ab23017", "intern", 12,
                  published=False)])
        self.assertEqual(rewrites, [])
        self.assertEqual(skipped, [("r1", "channel_unpublished", "投资银行业务总部-高端智造行业部实习生（深圳）")])

    def test_same_number_with_a_different_title_is_not_the_same_job(self):
        rewrites, skipped = mw.plan([("r1", old(2, "100"), "债券交易员")],
                                    [post("100", "债券投资经理", "aaa", "society", 2)])
        self.assertEqual(rewrites, [])
        self.assertEqual([s[1] for s in skipped], ["title_mismatch"])

    def test_not_in_portal_and_unparseable_url(self):
        _, skipped = mw.plan([("r1", old(2, "999"), "甲"), ("r2", WT + "web/index", "乙")],
                             [post("100", "甲", "aaa", "society", 2)])
        self.assertEqual(sorted(s[1] for s in skipped), ["no_post_id", "not_in_portal"])

    def test_channel_changed_but_only_one_target_is_fine(self):
        """兴业证券博士后：旧版只挂在 recruitType=13，新门户挂在校招列表里 → 换成校招那条链接。"""
        rewrites, _ = mw.plan([("r1", old(13, "172401"), "兴业证券博士后")],
                              [post("172401", "兴业证券博士后", "6ac70ea3", "campus", 1)])
        self.assertEqual(rewrites, [("r1", old(13, "172401"), new("6ac70ea3", "campus"))])

    def test_two_targets_resolved_by_the_old_channel(self):
        posts = [post("5", "管培生", "soc", "society", 2), post("5", "管培生", "cam", "campus", 1)]
        rewrites, _ = mw.plan([("r1", old(1, "5"), "管培生")], posts)
        self.assertEqual(rewrites, [("r1", old(1, "5"), new("cam", "campus"))])
        rewrites, skipped = mw.plan([("r1", old(13, "5"), "管培生")], posts)
        self.assertEqual(rewrites, [])
        self.assertEqual([s[1] for s in skipped], ["ambiguous"])

    def test_two_old_rows_for_one_job_keep_the_channel_matching_one(self):
        """旧库按渠道存过多行的同一个岗（长城汽车那类）：只改渠道对得上的那行，另一行不动留给人处理。"""
        rows = [("social-row", old(2, "7"), "工程师"), ("campus-row", old(1, "7"), "工程师")]
        rewrites, skipped = mw.plan(rows, [post("7", "工程师", "cam", "campus", 1)])
        self.assertEqual(rewrites, [("campus-row", old(1, "7"), new("cam", "campus"))])
        self.assertEqual(skipped, [("social-row", "duplicate_target", "工程师")])

    def test_post_id_regex_does_not_bleed_into_other_params(self):
        self.assertEqual(mw._OLD_POST_ID.search(old(2, "273901")).group(1), "273901")
        self.assertIsNone(mw._OLD_POST_ID.search(WT + "x?myPostIdsAry2=1"))
        self.assertEqual(mw._OLD_RECRUIT_TYPE.search(old(12, "1")).group(1), "12")


class FakeCursor:
    """select 回放 rows；逐行的检查 / 更新按 blocked（会冲突的行 id）决定成不成。"""

    def __init__(self, rows, blocked=(), raced=()):
        self.rows, self.blocked, self.raced, self.executed = rows, set(blocked), set(raced), []
        self.rowcount, self._one = 0, None

    def execute(self, sql, params):
        sql = " ".join(sql.split())
        self.executed.append((sql, dict(params)))
        if "id" in params:
            if params["id"] in self.raced and sql.startswith("update"):
                raise mw.psycopg2.errors.UniqueViolation("duplicate key value")
            ok = params["id"] not in self.blocked
            self.rowcount, self._one = (1 if ok else 0), ((1,) if ok else None)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self._one


class RunTest(unittest.TestCase):
    ROWS = [("r1", old(2, "1"), "甲"), ("r2", old(1, "2"), "乙"), ("r3", old(12, "3"), "丙")]
    POSTS = [post("1", "甲", "a", "society", 2), post("2", "乙", "b", "campus", 1),
             post("3", "丙", "c", "intern", 12, published=False)]

    def test_dry_run_never_writes(self):
        cur = FakeCursor(self.ROWS)
        total, done, skipped = mw.run(cur, "兴业证券", WT, self.POSTS)
        self.assertEqual((total, done), (3, 2))
        self.assertEqual([s[:2] for s in skipped], [("r3", "channel_unpublished")])
        self.assertTrue(all(sql.startswith("select") for sql, _ in cur.executed))

    def test_select_is_scoped_to_active_company_and_escaped_prefix(self):
        cur = FakeCursor([])
        self.assertEqual(mw.run(cur, "兴业证券", WT, self.POSTS, apply=True), (0, 0, []))
        sql, params = cur.executed[0]
        self.assertIn("where status = 'active' and company = %(company)s and jd_url like %(pattern)s", sql)
        self.assertEqual(params, {"company": "兴业证券", "pattern": like_prefix(WT)})
        self.assertEqual(len(cur.executed), 1)

    def test_apply_updates_row_by_row_with_guards(self):
        cur = FakeCursor(self.ROWS, blocked={"r2"})
        total, done, skipped = mw.run(cur, "兴业证券", WT, self.POSTS, apply=True)
        self.assertEqual((total, done), (3, 1))
        self.assertEqual(sorted(s[:2] for s in skipped),
                         [("r2", "conflict_or_changed"), ("r3", "channel_unpublished")])
        updates = [(sql, p) for sql, p in cur.executed if sql.startswith("update")]
        self.assertEqual([p["id"] for _, p in updates], ["r1", "r2"], "没发布渠道的行连 update 都不发")
        sql, params = updates[0]
        self.assertEqual(params, {"id": "r1", "old": old(2, "1"), "new": new("a", "society")})
        self.assertIn("where j.id = %(id)s and j.status = 'active' and j.jd_url = %(old)s", sql,
                      "带旧链接条件：两步之间被改过的行不动")
        self.assertIn("and not (exists", sql, "冲突行跳过，不能撞唯一索引")
        self.assertIn("k.canonical_jd_url = public.canonicalize_jd_url(%(new)s)", sql)
        self.assertIn("apply_url = case when j.apply_url = %(old)s then %(new)s else j.apply_url end", sql)


class RaceTest(unittest.TestCase):
    def test_unique_violation_on_one_row_does_not_abort_the_rest(self):
        """检查与写入之间别的进程刚插了同一个链接：这一行记成不动，后面的行照常改。"""
        cur = FakeCursor(RunTest.ROWS, raced={"r1"})
        total, done, skipped = mw.run(cur, "兴业证券", WT, RunTest.POSTS, apply=True)
        self.assertEqual((total, done), (3, 1))
        self.assertIn(("r1", "conflict_or_changed"), [s[:2] for s in skipped])
        self.assertEqual([p["id"] for sql, p in cur.executed if sql.startswith("update")], ["r1", "r2"])


class StubAdapter:
    """形状同 HotJobAdapter：_gate / fetch / _map / fetch_complete / _recruit_type。"""
    skip, answered, complete, enriched = None, True, True, 0
    gate_calls, flaky_gates = 0, 0   # 前 flaky_gates 次探测没答复

    def __init__(self):
        self._recruit_type, self.fetch_complete = 1, False

    def _gate(self, url):
        cls = type(self)
        cls.gate_calls += 1
        return cls.skip, cls.answered and cls.gate_calls > cls.flaky_gates

    def _enrich_details(self, *args, **kwargs):
        type(self).enriched += 1

    def fetch(self, url):
        self._enrich_details()
        self.fetch_complete = type(self).complete
        rows = [{"postId": "aaa", "externalKey": 274308, "postName": "金融产品部-产品研究助理"},
                {"postId": "bbb", "externalKey": "", "postName": "没有旧岗位号的岗"}]
        return json.dumps({"_intercepted": [{"data": {"pageForm": {"pageData": rows}}}]}, ensure_ascii=False)

    def _map(self, row):
        return type("Job", (), {"title": row["postName"], "jd_url": new(row["postId"], "campus")})()


class FetchPortalPostsTest(unittest.TestCase):
    def setUp(self):
        StubAdapter.skip, StubAdapter.answered, StubAdapter.complete, StubAdapter.enriched = None, True, True, 0
        StubAdapter.gate_calls, StubAdapter.flaky_gates = 0, 0
        self._retry = mw._GATE_RETRY_SECONDS
        mw._GATE_RETRY_SECONDS = 0

    def tearDown(self):
        mw._GATE_RETRY_SECONDS = self._retry

    def test_list_only_and_link_comes_from_the_adapter(self):
        posts, skip = mw.fetch_portal_posts(PB + "/school.html", make_adapter=StubAdapter)
        self.assertIsNone(skip)
        self.assertEqual(posts, [mw.PortalPost("274308", "金融产品部-产品研究助理", new("aaa", "campus"), 1, True)])
        self.assertEqual(StubAdapter.enriched, 0, "对号只要列表，不该逐岗去补正文")

    def test_skipped_channel_is_still_listed_but_marked_unpublished(self):
        StubAdapter.skip = "wecruit channel not published (recruitType=12)"
        posts, skip = mw.fetch_portal_posts(PB + "/interns.html", make_adapter=StubAdapter)
        self.assertEqual(skip, StubAdapter.skip)
        self.assertEqual([p.published for p in posts], [False])

    def test_unanswered_gate_aborts(self):
        """抓取侧探测失败按「不跳过」放行；据此改库不行——没探到 ≠ 渠道发布了。"""
        StubAdapter.answered = False
        with self.assertRaises(RuntimeError):
            mw.fetch_portal_posts(PB + "/interns.html", make_adapter=StubAdapter)
        self.assertEqual(StubAdapter.gate_calls, mw._GATE_TRIES)

    def test_gate_is_retried_before_giving_up(self):
        StubAdapter.flaky_gates = 2
        posts, skip = mw.fetch_portal_posts(PB + "/school.html", make_adapter=StubAdapter)
        self.assertEqual((len(posts), skip, StubAdapter.gate_calls), (1, None, 3))

    def test_incomplete_list_aborts(self):
        """没翻完时「新门户没有这个岗」不可信（兴业证券社招每页只回 15 条，按短页收尾就会少 14 个）。"""
        StubAdapter.complete = False
        with self.assertRaises(RuntimeError):
            mw.fetch_portal_posts(PB + "/social.html", make_adapter=StubAdapter)

    def test_real_adapter_still_has_the_pieces_this_tool_leans_on(self):
        adapter = HotJobAdapter()
        adapter._probe_json = lambda api, params, referer: None   # 两道门都没探到
        self.assertEqual(adapter._gate(PB + "/interns.html"), (None, False))
        self.assertIsNone(adapter.should_skip(PB + "/interns.html"), "抓取侧照旧放行")
        adapter._probe_json = lambda api, params, referer: (
            {"state": "200"} if "search/condition" in api else {"data": {"keywords": "x"}})
        reason, answered = adapter._gate(PB + "/interns.html")
        self.assertIn("recruitType=12", reason)
        self.assertTrue(answered)
        self.assertEqual(adapter._recruit_type, 12)
        self.assertTrue(callable(adapter._enrich_details))
        job = adapter._map({"postId": "6ab23017", "postName": "实习生", "externalKey": "273602"})
        self.assertEqual(job.jd_url, new("6ab23017", "intern"))


class ParseArgsTest(unittest.TestCase):
    def _args(self, wt=WT, portals=(PB + "/social.html",)):
        out = ["--company", "兴业证券", "--wt-prefix", wt]
        for p in portals:
            out += ["--portal", p]
        return out

    def test_valid_defaults_to_dry_run(self):
        args = mw.parse_args(self._args(portals=(PB + "/social.html", PB + "/school.html")))
        self.assertFalse(args.apply)
        self.assertEqual(len(args.portal), 2)

    def test_rejects_malformed_inputs(self):
        bad = [
            self._args(wt="https://xyzq.hotjob.cn/"),                      # 旧前缀不点名租户
            self._args(wt="http://xyzq.hotjob.cn/wt/xyzq/"),               # 非 https
            self._args(portals=(PB + "/index.html",)),                     # 不是渠道页
            self._args(portals=("https://xyzq.hotjob.cn/pb/social.html",)),  # 没有租户 key
            self._args(portals=(PB + "/social.html", PB + "/social.html")),  # 重复
        ]
        for argv in bad:
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                mw.parse_args(argv)


if __name__ == "__main__":
    unittest.main()
