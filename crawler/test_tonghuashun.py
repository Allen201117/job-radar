"""同花顺 adapter + 蚂蚁子公司归属派生的纯函数单测（不打真实网络）。

这些用例钉的都是**真踩过的坑**，不是形式覆盖：
  · ex_data / apply_show_do_list 信封名（取错就是空列表 → 误判「对方没开」）
  · PAGE_SIZE 必须是 10（写大了短页兜底会在第一页误判抓完，99 个岗只拿 10 个还自称抓全）
  · 蚂蚁标题前缀派生必须挡住「研究型实习生 / CTO / 产品经理」这类不是公司名的前缀
"""
import json
import unittest

from adapters.antgroup import _derive_company
from adapters.tonghuashun import TongHuaShunAdapter


def _row(job_id, name, **kw):
    row = {
        "id": job_id,
        "name": name,
        "base": "杭州",
        "intro": "【团队介绍】金融多模态基座模型预训练团队。",
        "requirement": "【职位要求】硕士及以上学历。",
        "apply_recruitment_series_name": "2027届校园招聘",
        "apply_type_first": "AI算法类",
    }
    row.update(kw)
    return row


class TongHuaShunParseTest(unittest.TestCase):
    def setUp(self):
        self.adapter = TongHuaShunAdapter()

    def test_page_size_is_ten(self):
        """服务端把 pageSize 硬顶到 10。PAGE_SIZE 写大 → paginate_all 的短页兜底把首页当末页。"""
        self.assertEqual(TongHuaShunAdapter.PAGE_SIZE, 10)

    def test_parse_maps_core_fields_and_builds_detail_url(self):
        jobs = self.adapter.parse(json.dumps({"jobs": [_row("2160", "AIME基座预训练算法工程师")]}))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.company, "同花顺")
        self.assertEqual(job.title, "AIME基座预训练算法工程师")
        self.assertEqual(job.location, "杭州")
        self.assertEqual(job.jd_url, "https://campus.10jqka.com.cn/job/detail?id=2160")
        # 正文由 intro + requirement 拼成，两段都要在
        self.assertIn("金融多模态基座模型", job.summary)
        self.assertIn("硕士及以上学历", job.summary)

    def test_job_type_carries_recruitment_series(self):
        """招聘系列直填 job_type：normalizer 只信认得出的招聘类型，认不出的自动退回正文推断。"""
        jobs = self.adapter.parse(json.dumps({"jobs": [
            _row("1", "后端开发", apply_recruitment_series_name="日常实习"),
            _row("2", "算法工程师", apply_recruitment_series_name="AIME计划"),
        ]}))
        self.assertEqual([j.job_type for j in jobs], ["日常实习", "AIME计划"])

    def test_parse_dedupes_and_drops_incomplete_rows(self):
        jobs = self.adapter.parse(json.dumps({"jobs": [
            _row("2160", "算法工程师"),
            _row("2160", "算法工程师"),      # 同 id 重复 → 只留一条
            _row("", "没有 id 的岗"),          # 缺 id → 丢
            _row("2161", ""),                  # 缺标题 → 丢
            "not-a-dict",
        ]}))
        self.assertEqual([j.jd_url for j in jobs], ["https://campus.10jqka.com.cn/job/detail?id=2160"])

    def test_parse_survives_broken_payload(self):
        self.assertEqual(self.adapter.parse("not json"), [])
        self.assertEqual(self.adapter.parse(json.dumps({})), [])


class AntGroupSubsidiaryDeriveTest(unittest.TestCase):
    """蚂蚁门户「{业务线}-{岗位名}」标题前缀 → 必投清单规范名。"""

    def test_derives_listed_subsidiary(self):
        self.assertEqual(_derive_company("网商银行-信贷风控策略岗-科创贷方向"), "网商银行")
        self.assertEqual(_derive_company("网商银行 — 前端工程师"), "网商银行")

    def test_parent_and_unlisted_business_lines_fall_back(self):
        for title in ("蚂蚁集团-Java工程师", "蚂蚁国际-风控", "OceanBase-内核研发", "蚂蚁数字科技-产品"):
            self.assertEqual(_derive_company(title), "", title)

    def test_non_company_prefixes_never_derive(self):
        """这些前缀同样长得像「{X}-{岗位}」，纯正则会造出一家叫「研究型实习生」的公司。"""
        for title in ("研究型实习生-隐私计算方向", "CTO-线技术风险", "产品经理-支付宝", "大安全事业群-安全"):
            self.assertEqual(_derive_company(title), "", title)

    def test_no_separator_or_junk_input(self):
        for title in ("网商银行BI岗", "", None, 123):
            self.assertEqual(_derive_company(title), "", repr(title))


if __name__ == "__main__":
    unittest.main()
