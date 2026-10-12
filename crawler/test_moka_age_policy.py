"""Moka 发布年限口径（2026-10-12）：卡片上的发布日期超过 730 天的岗不收，库里已有的下架成 removed。

起因：老版门户翻页修好当晚新入库 5,324 个岗，其中 1,698 个是 2024 年及以前发布的（最早 2019 年）——
门户仍列着，分不清常年在招还是没人撤，而它们在库里的首见时间是当晚。

钉死的事：① 边界与百胜那条口径同一种算法（正好 N 天前发布的仍收）；② 没有发布日期的卡片照收；
③ 没收的岗要把链接交给 run.py，库里已有的才下得掉——整个门户都超龄、一条都没收时也一样；
④ 下架用可逆的 removed，不是 expired；⑤ 这一步失败不影响抓取。
"""
import json
import unittest
from datetime import date, timedelta
from unittest import mock

import jobs_db
import run
from adapters.china_ats import MokaAdapter, _moka_card_published

BASE = "https://app.mokahr.com/social-recruitment/demo/1"
TODAY = date(2026, 10, 12)


def _new_card(job_id, published):
    """新版卡片：标题 / 发布于 … / 字段区。"""
    return {"href": f"#/job/{job_id}", "text": f"算法工程师{job_id}\n发布于 {published}\n全职\n|\n上海市\n上海市"}


def _old_card(job_id, published):
    """老版卡片：角标粘在标题前、标签行 + 地点行、发布时间在最后。"""
    return {"href": f"#/job/{job_id}", "text": f"急营销策划{job_id}\n策划类\n北京市·朝阳区\n发布时间：{published}"}


def _parse(cards, adapter=None):
    adapter = adapter or MokaAdapter()
    with mock.patch.object(MokaAdapter, "_today", staticmethod(lambda: TODAY)):
        jobs = adapter.parse(json.dumps({"_base": BASE, "cards": cards}, ensure_ascii=False))
    return adapter, jobs


class PublishedDateTest(unittest.TestCase):
    def test_reads_the_three_label_spellings(self):
        self.assertEqual(_moka_card_published("岗\n发布于 2026-08-31\n全职"), date(2026, 8, 31))
        self.assertEqual(_moka_card_published("急岗\n策划类\n发布时间：2021-07-15"), date(2021, 7, 15))
        self.assertEqual(_moka_card_published("Engineer\nPosted on 2026-10-10\nFull-time"), date(2026, 10, 10))

    def test_no_date_or_unreadable_date_is_none(self):
        self.assertIsNone(_moka_card_published("急\n法务顾问"))            # 右栏「最新职位」只有标题
        self.assertIsNone(_moka_card_published(""))
        self.assertIsNone(_moka_card_published(None))
        self.assertIsNone(_moka_card_published("岗\n发布于 2026-13-40"))    # 不是合法日期
        # 卡片上别的数字不是发布日期：没有「发布于 / 发布时间 / Posted on」标签就不认
        self.assertIsNone(_moka_card_published("岗\n截止 2020-01-01\n工号 20190101"))

    def test_only_a_whole_line_counts(self):
        """新版卡片带正文摘要。正文里的一句话提到「发布时间：2023-…」不是这个岗的发布日期——
        认了就会把一个在招岗按超龄下架（不显示日期的门户最容易中）。"""
        body = "产品经理\n全职\n|\n杭州市\n杭州市\n负责制度发布，发布时间：2023-01-05 起执行的版本需要回溯"
        self.assertIsNone(_moka_card_published(body))
        self.assertIsNone(_moka_card_published("岗\n本制度发布于 2022-03-01，适用于全体员工"))
        # 整行就是「标签 + 日期」才认；前后有空白不影响
        self.assertEqual(_moka_card_published("岗\n  发布于 2026-08-31  \n正文提到发布时间：2020-01-01 的旧版"),
                         date(2026, 8, 31))


class AgeBoundaryTest(unittest.TestCase):
    def test_boundary_day_by_day(self):
        """正好 730 天前发布的仍收，731 天前的不收。逐日扫边界前后，新旧两种卡片都扫。"""
        for make in (_new_card, _old_card):
            for back in range(720, 741):
                published = TODAY - timedelta(days=back)
                adapter, jobs = _parse([make("x", published.isoformat())])
                kept = back <= MokaAdapter._MAX_AGE_DAYS
                self.assertEqual(len(jobs), 1 if kept else 0, (make.__name__, back))
                self.assertEqual(adapter.retire_jd_urls, () if kept else (f"{BASE}#/job/x",), (make.__name__, back))

    def test_mixed_portal_keeps_recent_and_names_the_rest(self):
        cards = [_new_card("a", "2026-10-01"), _old_card("b", "2021-07-15"),
                 _new_card("c", "2025-03-02"), _old_card("d", "2019-05-20")]
        adapter, jobs = _parse(cards)
        self.assertEqual([j.jd_url for j in jobs], [f"{BASE}#/job/a", f"{BASE}#/job/c"])
        self.assertEqual(adapter.retire_jd_urls, (f"{BASE}#/job/b", f"{BASE}#/job/d"))

    def test_cards_without_a_date_are_kept(self):
        """76 条源整个门户都不显示发布日期；右栏那几张也只有标题。没有证据说它旧，就照收。"""
        cards = [{"href": "#/job/n1", "text": "产品经理\n全职\n|\n杭州市\n杭州市"},
                 {"href": "#/job/n2", "text": "急\n法务顾问"}]
        adapter, jobs = _parse(cards)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(adapter.retire_jd_urls, ())

    def test_fully_over_age_portal_yields_nothing_but_still_names_every_url(self):
        """云从社招门户 97 张卡全部超过两年：一条都不收，但 97 个链接都要交出去，库里的旧行才下得掉。"""
        adapter, jobs = _parse([_old_card(i, "2021-03-03") for i in range(5)])
        self.assertEqual(jobs, [])
        self.assertEqual(len(adapter.retire_jd_urls), 5)

    def test_over_age_card_is_named_even_when_its_title_cannot_be_parsed(self):
        adapter, jobs = _parse([{"href": "#/job/t", "text": "\n发布时间：2020-01-01"}])
        self.assertEqual(jobs, [])
        self.assertEqual(adapter.retire_jd_urls, (f"{BASE}#/job/t",))

    def test_urls_are_reset_on_every_parse(self):
        adapter, _ = _parse([_old_card("b", "2021-07-15")])
        self.assertEqual(len(adapter.retire_jd_urls), 1)
        adapter, _ = _parse([_new_card("a", "2026-10-01")], adapter)
        self.assertEqual(adapter.retire_jd_urls, (), "上一条源点名的链接不许带到下一条源")
        adapter, _ = _parse([_old_card("b", "2021-07-15")], adapter)
        self.assertEqual(adapter.parse("not json"), [])
        self.assertEqual(adapter.retire_jd_urls, (), "这一轮的载荷读不了，也不许留着上一轮的名单")

    def test_same_job_is_never_both_collected_and_named(self):
        """同一个岗两张卡（一张写着旧日期、一张只有标题）：以写了日期的为准。
        一边点名下架、一边又收进来，库里这一行会每晚先下架再被写回。"""
        dated = _old_card("b", "2021-07-15")
        title_only = {"href": "#/job/b?from=latest", "text": "急\n营销策划b"}
        for cards in ([dated, title_only], [title_only, dated]):
            adapter, jobs = _parse(cards)
            self.assertEqual(jobs, [])
            self.assertEqual(adapter.retire_jd_urls, (f"{BASE}#/job/b",))

    def test_policy_can_be_switched_off(self):
        adapter = MokaAdapter()
        adapter._MAX_AGE_DAYS = 0
        adapter, jobs = _parse([_old_card("b", "2019-05-20")], adapter)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(adapter.retire_jd_urls, ())


class _Cur:
    def __init__(self, log, rowcount=0):
        self.log, self.rowcount = log, rowcount

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.log.append((sql, params))


class _Conn:
    def __init__(self, rowcount=0):
        self.log, self.rowcount = [], rowcount

    def cursor(self):
        return _Cur(self.log, self.rowcount)


class RetireOutOfPolicyDbTest(unittest.TestCase):
    def test_marks_active_rows_removed_by_canonical_url(self):
        conn = _Conn(rowcount=2)
        n = jobs_db.retire_out_of_policy(conn, [f"{BASE}#/job/b", f"{BASE}#/job/d", f"{BASE}#/job/b"])
        self.assertEqual(n, 2)
        sql, params = conn.log[0]
        self.assertIn("status = 'removed'", sql)
        self.assertNotIn("expired", sql)                   # expired 次日会被 purge-expired 永久删除
        self.assertIn("status = 'active'", sql)
        self.assertIn("canonical_jd_url = any", sql)       # 走 active 唯一索引
        self.assertEqual(params, ([f"{BASE}#/job/b", f"{BASE}#/job/d"],))   # 去重；hash 路由原样保留

    def test_empty_input_never_touches_the_db(self):
        conn = _Conn()
        self.assertEqual(jobs_db.retire_out_of_policy(conn, []), 0)
        self.assertEqual(jobs_db.retire_out_of_policy(conn, [None, ""]), 0)
        self.assertEqual(conn.log, [])


class _Adapter:
    def __init__(self, urls):
        self.retire_jd_urls = urls


class RunStepTest(unittest.TestCase):
    def test_retires_named_urls_when_writing_the_jobs_db(self):
        conn = _Conn(rowcount=3)
        with mock.patch.object(run.jobs_db, "enabled", return_value=True), \
                mock.patch.object(run, "_get_thread_jobs_conn", return_value=conn):
            n = run._retire_out_of_policy(_Adapter((f"{BASE}#/job/b",)))
        self.assertEqual(n, 3)
        self.assertEqual(len(conn.log), 1)

    def test_does_nothing_without_urls_or_without_the_jobs_db(self):
        conn = _Conn()
        with mock.patch.object(run.jobs_db, "enabled", return_value=True), \
                mock.patch.object(run, "_get_thread_jobs_conn", return_value=conn):
            self.assertEqual(run._retire_out_of_policy(_Adapter(())), 0)
            self.assertEqual(run._retire_out_of_policy(object()), 0)     # 别的 adapter 没有这个属性
        with mock.patch.object(run.jobs_db, "enabled", return_value=False), \
                mock.patch.object(run, "_get_thread_jobs_conn", return_value=conn):
            self.assertEqual(run._retire_out_of_policy(_Adapter(("u",))), 0)
        self.assertEqual(conn.log, [])

    def test_failure_never_blocks_the_crawl(self):
        with mock.patch.object(run.jobs_db, "enabled", return_value=True), \
                mock.patch.object(run, "_get_thread_jobs_conn", side_effect=RuntimeError("connection already closed")):
            self.assertEqual(run._retire_out_of_policy(_Adapter(("u",))), 0)

    def test_fully_over_age_source_still_retires_stored_rows(self):
        """真跑一遍主流程：整个门户都在口径外，parse 一条都不出、主流程在「没有岗」那一支就返回——
        库里的旧行照样要下架，下架行数要带在返回值里（汇总进每日台账）。"""
        class _AllTooOld:
            retire_jd_urls = ()

            def should_skip(self, url):
                return None

            def fetch(self, url):
                return "{}"

            def parse(self, html):
                self.retire_jd_urls = (f"{BASE}#/job/b", f"{BASE}#/job/d")
                return []

        conn = _Conn(rowcount=2)
        updates = []
        run.ADAPTERS["_all_too_old"] = _AllTooOld()
        try:
            with mock.patch.object(run.db, "create_crawl_run", lambda sb, sid: "run-1"), \
                    mock.patch.object(run.db, "update_crawl_run", lambda *a, **k: updates.append((a, k))), \
                    mock.patch.object(run, "check_robots", lambda url: {"allowed": True, "reason": ""}), \
                    mock.patch.object(run.jobs_db, "enabled", return_value=True), \
                    mock.patch.object(run, "_get_thread_jobs_conn", return_value=conn):
                result = run._process_one_source(
                    {"adapter_name": "_all_too_old", "company": "测试公司", "source_url": BASE, "id": "s1"},
                    supabase=None)
        finally:
            run.ADAPTERS.pop("_all_too_old", None)
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["policy_removed"], 2)
        self.assertEqual(len(conn.log), 1, "下架那条 SQL 必须真的发出去")
        self.assertEqual(conn.log[0][1], ([f"{BASE}#/job/b", f"{BASE}#/job/d"],))
        self.assertEqual(updates[-1][0][2], "success")


if __name__ == "__main__":
    unittest.main()
