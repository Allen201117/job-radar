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


class _FakeResp:
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


if __name__ == "__main__":
    unittest.main()
