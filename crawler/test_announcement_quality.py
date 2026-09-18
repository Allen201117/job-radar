"""公告可报名门 + 正文切割的回归（全部来自 2026-09-18 线上真实公告的原文片段）。"""
import unittest
from datetime import date

from announcements.body import extract_body
from announcements.deadline import extract_deadline
from announcements.quality import assess

TODAY = date(2026, 9, 18)


class TestExtractBody(unittest.TestCase):
    def test_cuts_nav_and_footer(self):
        page = ("首页 政务公开 办事服务 当前位置： 首页 > 资讯中心 > 省属事业单位招聘 "
                "某某学院2026年公开招聘工作人员公告 发布日期： 2026-09-16 "
                + "根据有关规定现将招聘事项公告如下，报名时间：2026年9月16日至2026年9月24日。" * 4
                + " 关闭本页 打印本页 业务子网 各地市人社部门网站 南京市 无锡市 徐州市")
        body = extract_body(page, "某某学院2026年公开招聘工作人员公告")
        self.assertIn("报名时间", body)
        self.assertNotIn("政务公开", body)      # 导航切掉
        self.assertNotIn("各地市人社部门网站", body)  # 页脚切掉

    def test_falls_back_to_full_text_when_anchor_missing(self):
        """锚不上标题时退回原文，绝不静默返回空串（宁可不切，不可丢正文）。"""
        page = "一段没有标题也没有页脚标记的正文，" * 12
        self.assertEqual(extract_body(page, "对不上的标题XYZ"), page.strip())

    def test_never_returns_near_empty(self):
        page = "首页 导航 某公告标题 尾巴"
        self.assertGreaterEqual(len(extract_body(page, "某公告标题")), 10)


class TestDeadlineRangeForms(unittest.TestCase):
    """2026-09-18 实测：33 条抽不到截止日的公告里 27 条正文其实写了，全栽在这几种写法上。"""

    def test_hyphen_range_month_day(self):
        # 江苏农牧「重启报名系统公告」——正文的真实写法
        d, _ = extract_deadline("1. 报名、照片上传： 9 月 16 日 09:00- 9 月 24 日 16:00",
                                published_at=date(2026, 9, 15))
        self.assertEqual(d, date(2026, 9, 24))

    def test_dash_range_full_date(self):
        d, _ = extract_deadline("报名时间:2026年9月18日9:00—2026年10月8日17:00")
        self.assertEqual(d, date(2026, 10, 8))

    def test_qi_zhi_without_deadline_word(self):
        # 首都经济贸易大学：既不写「报名时间」也不写「截止」，只有一个「至」
        d, _ = extract_deadline("三、报名方式(一)自公告发布之日起至2026年9月22日上午11:00，应聘者访问…")
        self.assertEqual(d, date(2026, 9, 22))

    def test_single_date_near_baoming_is_not_a_deadline(self):
        """只有孤零零一个日期的一律不取——那是资格审查/确认的日子，
        当成截止日会把已截止的公告继续挂在页面上（错的方向更伤）。"""
        for text in ("报名成功的应聘人员请于2026年10月8日到现场确认",
                     "报名表广东石油化工学院2026年9月1日",
                     "报名条件的岗位，并于2026年9月8日前提交材料"):
            self.assertIsNone(extract_deadline(text, published_at=date(2026, 9, 1))[0], text)


class TestPublishedDate(unittest.TestCase):
    def test_reads_bare_time_meta_line(self):
        """广东这类站元信息只写「时间：2026-09-09」，不写「发布」二字。
        抽不到发布日 = 45 天 TTL 只能从「今天首见」起算，一条 1 月发的公告会被当成新件再挂一个半月。"""
        from announcements.deadline import extract_published
        self.assertEqual(extract_published("信息来源：本网 时间：2026-09-09 分享： 字体： 正文……"),
                         date(2026, 9, 9))

    def test_does_not_mistake_registration_time_for_publish_time(self):
        """⚠️「**报名**时间」也含「时间」二字。只在正文开头元信息区找、且只认带横杠的 ISO 写法，
        中文正文写报名时间用的是「2026年9月1日」，天然分开。"""
        from announcements.deadline import extract_published
        body = "某某学院公开招聘公告 " + "正文" * 200 + " 报名时间：2026-09-01 至 2026-09-30"
        self.assertIsNone(extract_published(body))


class TestAssess(unittest.TestCase):
    def test_rejects_registration_closed_notice(self):
        v = assess("江苏省水利科学研究院2026年公开招聘工作人员关闭报名系统公告",
                   "根据规定，报名工作于2026年9月8日9:00开始。将于2026年9月17日9:00关闭报名系统。",
                   today=TODAY)
        self.assertEqual(v.action, "reject")

    def test_keeps_reopened_registration(self):
        """⚠️ 回归钉死：「**重启**报名系统公告」是一个**新开的报名窗**，不是过程通知。
        2026-09-18 第一版判据把它连同「关闭报名」一起毙了，等于白扔一条在招公告。"""
        v = assess("江苏农牧科技职业学院2026年公开招聘重启报名系统公告",
                   "部分岗位未录满，将于2026年9月16日重启考生报名系统。"
                   "1. 报名、照片上传： 9 月 16 日 09:00- 9 月 24 日 16:00",
                   published_at=date(2026, 9, 15), today=TODAY)
        self.assertEqual(v.action, "ok")
        self.assertEqual(v.deadline, date(2026, 9, 24))

    def test_quoted_document_title_is_not_a_closure_statement(self):
        """⚠️ 回归钉死（第二次抓到同一个误杀）：正文引用《…关闭报名系统公告》是在**指另一份文件**，
        不是说本公告关了。不剥书名号就会把这条正在报名（9/16-9/24）的公告判死。"""
        v = assess("江苏农牧科技职业学院2026年公开招聘重启报名系统公告",
                   "根据《江苏农牧科技职业学院2026年公开招聘工作人员公告》和"
                   "《江苏农牧科技职业学院2026年公开招聘(A类岗位)关闭报名系统公告》要求，"
                   "部分岗位未录满，以下岗位将于2026年9月16日重启考生报名系统。"
                   "1. 报名、照片上传： 9 月 16 日 09:00- 9 月 24 日 16:00",
                   published_at=date(2026, 9, 15), today=TODAY)
        self.assertEqual((v.action, v.deadline), ("ok", date(2026, 9, 24)))

    def test_real_closure_outside_quotes_still_rejects(self):
        """反方向：真正说自己关门的（关闭语句在书名号**外**）必须照样毙掉。"""
        # 标题刻意写成不含「关闭报名」的样子，确保走的是**正文**这条路而不是被标题门提前拦下。
        v = assess("江苏省水利科学研究院2026年公开招聘工作人员公告",
                   "根据《江苏省水利科学研究院2026年公开招聘工作人员公告》规定，"
                   "报名工作于2026年9月8日9:00开始。将于2026年9月17日9:00关闭报名系统。",
                   today=TODAY)
        self.assertEqual((v.action, v.reason), ("reject", "registration_closed"))

    def test_rejects_process_notices(self):
        for title in ("湖北省事业单位2026年统一公开招聘高校专职辅导员面试公告",
                      "仁济医院安徽医院2026年度公开招聘人员专业测试公告",
                      "2026年下半年陕西省省属事业单位公开招聘工作人员岗位表",
                      "河南省人社厅所属事业单位2026年公开招聘面试确认公告",
                      "关于公布重庆市事业单位2026年第三季度公开招聘报名确认人数的公告",
                      "湖南省卫健委直属事业单位2026年公开招聘部分岗位修改报名条件的公告"):
            self.assertEqual(assess(title, "正文若干。", today=TODAY).action, "reject", title)

    def test_rejects_past_deadline(self):
        v = assess("某学院2026年公开招聘公告",
                   "报名时间:2026年8月3日—2026年9月3日，逾期不再受理。", today=TODAY)
        self.assertEqual((v.action, v.reason), ("reject", "deadline_passed"))

    def test_flags_index_page_but_keeps_it(self):
        """天津全省公告都是这个形态：本页不收报名，让你去别的网站。
        标注而**不下架** —— 一刀切会让整省供给归零。"""
        v = assess("天津市部分事业单位公开招聘信息",
                   "近期，本市部分事业单位将在相关网站发布公开招聘工作人员公告，请登录查询。"
                   "序号 招聘单位 招聘岗位 公告发布网址 1 天津市宝坻区人民医院 专技岗1",
                   today=TODAY)
        self.assertEqual((v.action, v.reason), ("flag", "index_page"))

    def test_self_service_apply_page_is_not_an_index_page(self):
        """⚠️ 回归钉死：浙江音乐学院那条本页自收报名（「网上报名…登录报名网站注册」），
        却因为写了「请登录招聘报名网站下载打印**准考证**」被标成汇总索引页。
        这道门是否定性判断，收窄就误伤 —— 「报名」的各种说法必须收全。"""
        v = assess("浙江音乐学院2026年非教学岗位公开招聘公告（第三批）",
                   "（一）报名和资格初审 1.网上报名。自公告发布之日至9月30日。"
                   "应聘人员登录浙江音乐学院招聘报名网站注册个人真实信息后选择岗位报名。"
                   "4.打印准考证。通过资格初审人员请登录招聘报名网站下载打印笔试准考证。",
                   published_at=date(2026, 8, 14), today=TODAY)
        self.assertEqual((v.action, v.deadline), ("ok", date(2026, 9, 30)))

    def test_normal_announcement_passes(self):
        v = assess("湖南财政经济学院2026年第一批专任教师公开招聘公告",
                   "报名时间 自公告发布之日 至 2026年12月31日。随到随招,招满即止。"
                   "报名方式采取现场报名。总成绩=笔试成绩×60%+面试成绩×40%，"
                   "体检考察合格后公示，资格复审不合格者取消资格。", today=TODAY)
        self.assertEqual(v.action, "ok")
        self.assertEqual(v.deadline, date(2026, 12, 31))

    def test_no_apply_info_is_not_a_death_sentence(self):
        """高校人才引进常年只写个邮箱、不写「报名时间」——不许因此判死（宁可漏判不可错杀）。"""
        v = assess("某大学2026年高层次人才引进公告",
                   "诚聘海内外英才，有意者请将简历发送至 rsc@example.edu.cn。", today=TODAY)
        self.assertEqual(v.action, "ok")


if __name__ == "__main__":
    unittest.main()
