"""wt（老版 WinTalent hotjob.cn）适配器单测：recruitType → job_type 的招聘类型标注。"""
import json
import unittest

from adapters.wt import WtAdapter


class WtRecruitTypeJobTypeTest(unittest.TestCase):
    def setUp(self):
        self.a = WtAdapter()
        self.a.company_name = "测试公司"
        self.a._bind_source("https://test.hotjob.cn/wt/test/web/index")

    def test_campus_and_intern_recruit_types_are_labelled(self):
        """wt 列表接口的 postType 只是职能类别（「市场营销类」），不含招聘类型词汇；
        权威的招聘类型信号是我们请求时用的 recruitType（1=校招 / 2=社招 / 12=实习）。

        2026-09-17 实锤：华发股份 9 个校招岗、李宁 1 个校招岗，因为 job_type 只有
        「职能管理类」这类职能词，被 sourceDeclaredCategory 判不出招聘类型，入库后
        全部兜底成「社招」。把 recruitType 换算的中文标签塞进 job_type 即可救回，
        职能类别保留在前面（继续喂给 classifyJobFunction）。
        """
        posts = [
            {"postId": "1", "postName": "房产开发-会计助理/专员",
             "postType": "职能管理类", "_wtRecruitType": 1},
            {"postId": "3", "postName": "财务实习生",
             "postType": "职能管理类", "_wtRecruitType": 12},
        ]
        by = {p["postId"]: self.a._map(p) for p in posts}
        self.assertEqual(by["1"].job_type, "职能管理类 校园招聘")
        self.assertEqual(by["3"].job_type, "职能管理类 实习")

    def test_social_recruit_type_is_deliberately_not_labelled(self):
        """🚫 rt=2 **不标**「社会招聘」——这是回归护栏，不是遗漏。

        社招是 recruitmentCategory 层7 的默认态，标了不增加信息；而标上会让层3（declared）
        抢在层4（url 门户）/ 层5（标题强校招标记）**之前**拍板。2026-09-17 全库计数：
        wt 源 recruitType=2 的在招岗里有 **170 个判成校招、91 个判成实习**（公司把校招岗
        挂在社招板块，靠标题「XX 届 / 应届」被层5 捞回来）——标上就当场压回社招。
        同一个取舍在 lib/china-keyword-expansion.js 层4「不对 postType=society 对称判社招」
        那条注释里已经立过一次。
        """
        job = self.a._map({"postId": "2", "postName": "客研总监",
                           "postType": "市场营销类", "_wtRecruitType": 2})
        self.assertEqual(job.job_type, "市场营销类")

    def test_overseas_recruit_type_13_is_not_labelled(self):
        """🚫 rt=13（页面模板叫「海外」板块）**不贴任何标签**。

        2026-09-18 live 扫全部 41 个 wt 租户：11 家把这个板块各自挪用——五矿 81 个
        「安全管培生（海外）-2027应届生」、TCL 40 个「EMC工程师-27届」是校招；宇通 3 个
        「研发实习生」是实习；中伟「汽修工」/ 华友「汽轮机发电工」/ 用友「实施顾问」是社招；
        海澜「声乐表演」是艺术团、兴业证券是博士后。渠道不携带招聘类型，硬标哪一种都错一半，
        交给 recruitmentCategory 按标题自己判。job_type 只保留职能类别（或为空）。
        """
        by = {p["postId"]: self.a._map(p) for p in [
            {"postId": "13a", "postName": "安全管培生（海外）-2027应届生",
             "postType": "职能管理类", "_wtRecruitType": 13},
            {"postId": "13b", "postName": "汽修工", "_wtRecruitType": 13},
        ]}
        self.assertEqual(by["13a"].job_type, "职能管理类")
        self.assertIsNone(by["13b"].job_type)
        # 详情页要带 recruitType=13 才渲染出岗位本身（五矿 / 用友 / 宇通 / 海澜用 2 只回提示页）。
        self.assertIn("recruitType=13&postIdsAry=13a", by["13a"].jd_url)

    def test_recruit_type_13_is_fetched(self):
        """加渠道只改 _RECRUIT_TYPES 一处：逐渠道判 total / complete 的两处都按它的长度算。"""
        self.assertIn(13, WtAdapter._RECRUIT_TYPES)

    def test_missing_post_type_still_gets_recruit_label(self):
        post = {"postId": "4", "postName": "某校招岗", "_wtRecruitType": 1}
        self.assertEqual(self.a._map(post).job_type, "校园招聘")

    def test_absent_recruit_type_falls_back_to_bare_function_category(self):
        """`_wtRecruitType` 缺失时旧逻辑兜底 rt=2 → 按上面的规矩同样不加标签。"""
        post = {"postId": "5", "postName": "某岗", "postType": "职能管理类"}
        self.assertEqual(self.a._map(post).job_type, "职能管理类")

    def test_end_to_end_parse_labels_per_post(self):
        payload = json.dumps({"_intercepted": [{"postList": [
            {"postId": "6", "postName": "校招岗", "postType": "职能管理类",
             "_wtRecruitType": 1},
            {"postId": "7", "postName": "社招岗", "postType": "市场营销类",
             "_wtRecruitType": 2},
        ]}]}, ensure_ascii=False)
        by = {j.title: j for j in self.a.parse(payload)}
        self.assertEqual(by["校招岗"].job_type, "职能管理类 校园招聘")
        self.assertEqual(by["社招岗"].job_type, "市场营销类")


class WtSchoolEntryGateTest(unittest.TestCase):
    """「按院校设的投递入口」不是岗位，不入库（2026-09-18 立，见 _INSTITUTION_TITLE 注释）。"""

    def setUp(self):
        self.a = WtAdapter()
        self.a.company_name = "中广核"
        self.a._bind_source("https://cgn.hotjob.cn/wt/CGN/web/index")

    def _map(self, name, content="。", cond="。", rt=1):
        return self.a._map({"postId": "1", "postName": name, "postType": "其他",
                            "workContent": content, "serviceCondition": cond,
                            "_wtRecruitType": rt})

    def test_school_name_with_empty_body_is_dropped(self):
        """中广核把校招做成「一所院校一条 post」：标题是院校名、正文只有一个句号。
        2026-09-18 live 全库 957 行全是这个形态，用户在校招专区看到的是大学名而不是岗位。"""
        for name in ("北京建筑大学", "电子科技大学", "海外院校", "其他院校",
                     "中国地质大学（武汉）", "清华大学深圳国际研究生院",
                     "中国原子能科学研究院", "哈尔滨焊接研究所"):
            self.assertIsNone(self._map(name), f"应被拦下: {name}")

    def test_real_job_whose_title_ends_with_institution_word_is_kept(self):
        """⚠️ 单看标题会误杀：特变电工「FPGA软件工程师-研究院」是真岗（live 4 行）。
        判据必须是「院校名标题」**且**「正文为空」的交集。"""
        job = self._map("FPGA软件工程师-研究院",
                        content="1、参与FPGA技术需求分析，设计相应场景下FPGA方案；")
        self.assertIsNotNone(job)
        self.assertEqual(job.title, "FPGA软件工程师-研究院")

    def test_thin_card_with_normal_title_is_kept(self):
        """⚠️ 单看正文也会误杀：三棵树「行政接待类实习生」正文同样为空，但它是真岗。
        薄卡按 CLAUDE.md §4 该留在库里（只是不计入「有效在招」），不该被这道门顺手删掉。"""
        self.assertIsNotNone(self._map("行政接待类实习生"))
        self.assertIsNotNone(self._map("实习生（客房部）", rt=12))

    def test_parse_skips_them_end_to_end_and_counts(self):
        payload = json.dumps({"_intercepted": [{"postList": [
            {"postId": "10", "postName": "上海交通大学", "postType": "其他",
             "workContent": "。", "serviceCondition": "。", "_wtRecruitType": 1},
            {"postId": "11", "postName": "核电运行值班员", "postType": "技术类",
             "workContent": "负责机组运行监盘…", "_wtRecruitType": 1},
        ]}]}, ensure_ascii=False)
        jobs = self.a.parse(payload)
        self.assertEqual([j.title for j in jobs], ["核电运行值班员"])
        self.assertEqual(self.a._skipped_school_entries, 1)


class WtDeadlineTest(unittest.TestCase):
    """endDate 只有在 isLongTermRelease == 1 且不是滚动窗口时才是截止日（2026-10-10 立）。

    当天全量 39 个租户 16,594 个岗：isLongTermRelease=0 的 15,753 个，endDate 分别是 3000-01-01
    6,827 / 请求当天 2,470 / 已过去却仍在列 590 / 550 天以外的占位 1,902 / 550 天以内的未来日期 3,964
    （多数是发布日 + 12 个月）；平台自己的前端对这一类一律显示「长期发布」，不显示日期。
    """

    def setUp(self):
        self.a = WtAdapter()
        self.a.company_name = "测试公司"
        self.a._bind_source("https://test.hotjob.cn/wt/test/web/index")

    def _deadline(self, end, flag=1, fetched_on="2026-10-10", **extra):
        post = {"postId": "1", "postName": "某岗", "endDate": end,
                "_wtFetchedOn": fetched_on, **extra}
        if flag is not None:
            post["isLongTermRelease"] = flag
        return self.a._map(post).deadline

    def test_long_term_post_never_gets_a_deadline(self):
        for end in ("2026-10-10",      # 请求当天（库里同一个岗 09-18 存的是 09-18，10-10 再问变成 10-10）
                    "3000-01-01",      # 占位
                    "2027-10-09",      # 发布日 + 12 个月
                    "2030-12-31",      # 远未来占位
                    "2023-06-26",      # 三年前，岗位照样在列、详情页照样能投
                    "2026-12-11"):     # 看着像真日期，官网页面照样写「长期发布」
            self.assertIsNone(self._deadline(end, flag=0, publishDate="2026-10-09"), end)

    def test_post_with_offline_time_keeps_it(self):
        self.assertEqual(self._deadline("2026-10-31"), "2026-10-31")
        self.assertEqual(self._deadline("2026-12-31", flag="1"), "2026-12-31")

    def test_missing_or_unknown_flag_means_no_deadline(self):
        """判不出就不写：缺字段 / 取值不认识，一律当成没有截止日。"""
        self.assertIsNone(self._deadline("2026-10-31", flag=None))
        self.assertIsNone(self._deadline("2026-10-31", flag=2))
        self.assertIsNone(self._deadline("2026-10-31", flag=True))

    def test_rolling_window_is_not_a_deadline(self):
        """isLongTermRelease=1 的岗里 535/841 个的 endDate 是「请求当天 + N 个月」，跟着请求日走：
        库里 09-18 存的值与 10-10 再问到的值 14/14 不同；同一个岗在新版接口里是另一个固定日期。"""
        for end in ("2026-10-10", "2026-11-10", "2027-01-10", "2027-04-10", "2027-10-10"):
            self.assertIsNone(self._deadline(end), end)
        # 请求日的前一天也算锚点：接口若有缓存 / 跨零点，值会停在前一天那一档。
        self.assertIsNone(self._deadline("2027-01-09"))
        # 不是整月偏移的照常保留。
        self.assertEqual(self._deadline("2027-01-11"), "2027-01-11")
        self.assertEqual(self._deadline("2027-01-08"), "2027-01-08")

    def test_rolling_window_at_month_end(self):
        """月末加月有两种算法（截到月底 / 溢出到下月），两种都算滚动窗口。"""
        self.assertIsNone(self._deadline("2027-02-28", fetched_on="2026-11-30"))
        self.assertIsNone(self._deadline("2027-03-02", fetched_on="2026-11-30"))
        self.assertEqual(self._deadline("2027-03-05", fetched_on="2026-11-30"), "2027-03-05")

    def test_unparseable_end_date_is_dropped(self):
        self.assertIsNone(self._deadline(""))
        self.assertIsNone(self._deadline(None))
        self.assertIsNone(self._deadline("长期"))


class _FakeResp:
    headers = {}

    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    """按 (recruitType, page) 回放固定列表，模拟 wt 的 position/list 接口。"""
    pages = {}

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        rows = self.pages.get((params["recruitType"], params["page"]), [])
        total = sum(len(v) for (rt, _), v in self.pages.items() if rt == params["recruitType"])
        return _FakeResp({"postList": [dict(r) for r in rows], "rowCount": total})


class WtFetchDayTest(unittest.TestCase):
    """滚动窗口是相对「对方服务器的今天」算的 → 请求日取响应头 Date（换成北京日期），不取本机时钟。"""

    def test_fetch_stamps_rows_with_server_day_in_beijing(self):
        import adapters.wt as wt
        _FakeClient.pages = {(2, 1): [
            {"postId": "R", "postName": "滚动岗", "isLongTermRelease": 1, "endDate": "2027-01-10"},
            {"postId": "F", "postName": "定日岗", "isLongTermRelease": 1, "endDate": "2026-12-31"},
        ]}
        orig_client, orig_headers = wt.httpx.Client, _FakeResp.headers
        wt.httpx.Client = _FakeClient
        # 格林尼治 10-09 17:30 = 北京 10-10 01:30：按 UTC 日期算会把 2027-01-10 当成真截止日放行。
        _FakeResp.headers = {"date": "Fri, 09 Oct 2026 17:30:00 GMT"}
        try:
            a = WtAdapter()
            a.company_name = "测试公司"
            by = {j.title: j for j in a.parse(a.fetch("https://test.hotjob.cn/wt/test/web/index"))}
        finally:
            wt.httpx.Client, _FakeResp.headers = orig_client, orig_headers
        self.assertIsNone(by["滚动岗"].deadline)
        self.assertEqual(by["定日岗"].deadline, "2026-12-31")


class WtCrossChannelDedupeTest(unittest.TestCase):
    """同一 postId 挂在多个渠道 = 一个岗，不是多个岗（2026-09-18 立）。

    live：TCL 40 个「-27届」岗四个渠道（1/2/12/13）全挂、中伟 38 个 rt=13 岗里 34 个也在社招、
    五矿 81 个里 75 个也在校招；库里 GWM 3,440 个 active 行只有 3,188 个 postId。jd_url 带
    recruitType，按 (渠道, postId) 去重就会一岗多行。补 rt=13 若不先去重，只会再多一份副本。
    """

    def _run(self, pages):
        import adapters.wt as wt
        _FakeClient.pages = pages
        orig = wt.httpx.Client
        wt.httpx.Client = _FakeClient
        try:
            a = WtAdapter()
            a.company_name = "测试公司"
            html = a.fetch("https://test.hotjob.cn/wt/test/web/index")
            return a, {j.title: j for j in a.parse(html)}
        finally:
            wt.httpx.Client = orig

    def test_first_seen_channel_owns_jd_url_and_labels_merge_across_channels(self):
        a, by = self._run({
            (2, 1): [{"postId": "A", "postName": "A岗"}, {"postId": "B", "postName": "B岗"}],
            (1, 1): [{"postId": "B", "postName": "B岗"}, {"postId": "C", "postName": "C岗"}],
            (13, 1): [{"postId": "C", "postName": "C岗"}, {"postId": "D", "postName": "D岗-27届"}],
        })
        self.assertEqual(sorted(by), ["A岗", "B岗", "C岗", "D岗-27届"])
        # 首见渠道决定 jd_url：B 首见于社招，保住存量行的链接不变。
        self.assertIn("recruitType=2&postIdsAry=B", by["B岗"].jd_url)
        self.assertIn("recruitType=1&postIdsAry=C", by["C岗"].jd_url)
        # rt=13 独有的岗只有 recruitType=13 能渲染详情页（live：五矿/用友/宇通/海澜用 2 只回提示页）。
        self.assertIn("recruitType=13&postIdsAry=D", by["D岗-27届"].jd_url)
        # 标签看全部渠道：B 同时挂在校招板块 → 校园招聘；A 只在社招、D 只在 rt=13 → 不贴标签。
        self.assertEqual(by["B岗"].job_type, "校园招聘")
        self.assertEqual(by["C岗"].job_type, "校园招聘")
        self.assertIsNone(by["A岗"].job_type)
        self.assertIsNone(by["D岗-27届"].job_type)
        self.assertTrue(a.fetch_complete)
        # 分母去掉本次看到的跨渠道重复：各渠道 rowCount 之和 2+2+2=6，B/C 各重复一次 → 4 个岗。
        self.assertEqual(a.reported_total, 4)

    def test_fully_duplicated_first_page_does_not_end_pagination_early(self):
        """rt=13 第一页全是别的渠道见过的岗时，翻页判据仍看整页，第二页独有的岗不能漏。"""
        first = [{"postId": str(i), "postName": f"岗{i}"} for i in range(10)]
        _, by = self._run({
            (2, 1): first,
            (13, 1): first,
            (13, 2): [{"postId": "only13", "postName": "只在13"}],
        })
        self.assertIn("只在13", by)
        self.assertEqual(len(by), 11)
        self.assertEqual(_.reported_total, 11)   # 10 + 11 = 21，减去 10 个重复


# 2026-10-10 xyzq.hotjob.cn 任何路径都回的那份壳页（节选：只留判据用到的那句）。
_SHELL_HTML = """<!DOCTYPE html><html><head><title>招聘官网</title></head><body><iframe id="iframeCon" src="">
</iframe></body><script>ajax('POST', `${location.origin}/wecruit/common/getSLD`, `sld=${location.host}`,
function (res) { document.getElementById('iframeCon').setAttribute('src', res.data.linkData.link); });</script></html>"""


class _HtmlResp:
    headers = {}

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class _MovedClient(_FakeClient):
    """列表接口回 HTML；getSLD 按 sld_reply 回（None = 这次请求本身失败）。"""
    html = _SHELL_HTML
    sld_reply = None
    posted = []

    def get(self, url, params=None):
        return _HtmlResp(self.html)

    def post(self, url, data=None):
        type(self).posted.append((url, dict(data or {})))
        if self.sld_reply is None:
            raise OSError("connection reset")
        return _FakeResp(self.sld_reply)


class WtNonJsonListTest(unittest.TestCase):
    """列表接口回的不是 JSON：照样记 failed，但报错要说清原因（2026-10-10 立）。

    兴业证券 10-08 起连续 8 轮 failed，error_message 只有 `JSONDecodeError: Expecting value…`——
    租户域名被改绑成新版门户的壳页，这句话里一个字都看不出来。"""

    def _fetch_error(self, html, sld_reply):
        import adapters.wt as wt
        _MovedClient.html, _MovedClient.sld_reply, _MovedClient.posted = html, sld_reply, []
        orig = wt.httpx.Client
        wt.httpx.Client = _MovedClient
        try:
            with self.assertRaises(RuntimeError) as ctx:
                WtAdapter().fetch("https://xyzq.hotjob.cn/wt/xyzq/web/index")
        finally:
            wt.httpx.Client = orig
        return str(ctx.exception)

    def test_portal_shell_names_where_the_tenant_moved(self):
        new_home = "https://xyzq.hotjob.cn/SU68fb2499b7da1347a9dd852c/pb/index.html"
        msg = self._fetch_error(_SHELL_HTML, {"state": "200", "data": {"linkData": {"link": new_home}}})
        self.assertIn("new wecruit portal shell", msg)
        self.assertIn(new_home, msg)
        self.assertIn("host=xyzq.hotjob.cn", msg)
        # 问法与壳页自己的一致：同源 POST，sld = 域名。
        self.assertEqual(_MovedClient.posted,
                         [("https://xyzq.hotjob.cn/wecruit/common/getSLD", {"sld": "xyzq.hotjob.cn"})])

    def test_shell_is_still_reported_when_the_lookup_fails_or_is_empty(self):
        self.assertIn("getSLD failed: OSError", self._fetch_error(_SHELL_HTML, None))
        self.assertIn("getSLD gave no link",
                      self._fetch_error(_SHELL_HTML, {"state": "1001", "msg": "企业信息不存在"}))

    def test_other_non_json_is_not_called_a_move(self):
        """不是壳页的 HTML（限流页 / 报错页）不许说成「租户搬家」，也不去问 getSLD。"""
        msg = self._fetch_error("<html><body>Too  Many\nRequests</body></html>", None)
        self.assertIn("returned non-JSON", msg)
        self.assertIn("Too Many Requests", msg)
        self.assertNotIn("portal shell", msg)
        self.assertEqual(_MovedClient.posted, [])


if __name__ == "__main__":
    unittest.main()
