"""国聘集团展开的归属核验（张冠李戴红线）。

2026-09-04 线上实锤：南方电网的子公司名单里有「海南电网有限责任公司」，adapter 拿它去
关键词搜，而**国聘的搜索是集团级模糊匹配**，回来的既有真兄弟公司（鼎和财产保险，
名字里没有「南方电网」），也有毫不相干的「中国（海南）改革发展研究院有限责任公司」
「洋浦国际投资咨询有限公司」「海南健康发展研究院」——国聘自己写着它们分别是
民营企业 / 洋浦经济开发区 / 事业单位。旧写法对 `_group_child` 直接放行、跳过核验，
于是这些公司被打上「（南方电网）」入库。

钉死三件事：
① 集团口径（group_id）是权威，名字不是——鼎和保险必须放行；
② 「查到了但没有集团」= 定论，必须拒——这正是旧修法失败的地方（当成「查不到」放行了）；
③ 「请求失败」≠「没有集团」，此时放行（下轮重查），不能因对方接口抖一下丢掉整源真岗。
"""
import unittest

from adapters.iguopin import IguopinAdapter, _row_passes_match


class _Adapter(IguopinAdapter):
    """把网络调用换成查表，其余逻辑照跑。"""

    def __init__(self, table):
        self._table = table          # company_id -> group_id / "" / None
        self.calls = []

    def _company_group_id(self, company_id, headers):
        self.calls.append(company_id)
        return self._table.get(company_id, None)


def _row(cid, name, child=None):
    row = {"company_id": cid, "company_name": name}
    if child:
        row["_group_child"] = child
    return row


GROUP = "10685309282299237"          # 南方电网


class GroupMembershipTest(unittest.TestCase):
    def setUp(self):
        self.a = _Adapter({
            "c_dinghe": GROUP,       # 鼎和财产保险：真子公司，名字里没有「南方电网」
            "c_inst": "",            # 中国（海南）改革发展研究院：查到了，无集团
            "c_yangpu": "other_grp", # 洋浦国际投资咨询：属于别的集团
            "c_boom": None,          # 接口失败
        })
        self.ok = self.a._group_membership_checker(GROUP, {})

    def test_real_subsidiary_passes_even_though_name_mismatches(self):
        row = _row("c_dinghe", "鼎和财产保险股份有限公司", child="海南电网有限责任公司")
        self.assertTrue(_row_passes_match(row, "南方电网", self.ok),
                        "名字对不上但 group_id 对得上 —— 按名字核会误杀真子公司")

    def test_company_without_group_is_rejected(self):
        row = _row("c_inst", "中国（海南）改革发展研究院有限责任公司", child="海南电网有限责任公司")
        self.assertFalse(_row_passes_match(row, "南方电网", self.ok),
                         "「查到了、但没有集团」是定论，不能当成「查不到」放行")

    def test_company_in_another_group_is_rejected(self):
        row = _row("c_yangpu", "洋浦国际投资咨询有限公司", child="海南电网有限责任公司")
        self.assertFalse(_row_passes_match(row, "南方电网", self.ok))

    def test_lookup_failure_passes_and_is_not_cached_as_membership(self):
        row = _row("c_boom", "某公司", child="海南电网有限责任公司")
        self.assertTrue(_row_passes_match(row, "南方电网", self.ok),
                        "对方接口抖一下不该丢掉整源真岗")

    def test_group_verdict_is_cached_per_company(self):
        for _ in range(5):
            _row_passes_match(_row("c_dinghe", "鼎和财产保险股份有限公司"), "南方电网", self.ok)
        self.assertEqual(self.a.calls.count("c_dinghe"), 1, "同一家公司只该查一次")

    def test_group_rule_also_applies_to_direct_keyword_rows(self):
        """有集团口径时对**所有**行生效——直接搜出来的鼎和保险同样是真子公司。"""
        row = _row("c_dinghe", "鼎和财产保险股份有限公司")     # 无 _group_child 标记
        self.assertTrue(_row_passes_match(row, "南方电网", self.ok))
        row2 = _row("c_inst", "中国（海南）改革发展研究院有限责任公司")
        self.assertFalse(_row_passes_match(row2, "南方电网", self.ok))

    def test_without_group_falls_back_to_name_match(self):
        """非集团源（没有 group_id）仍走原来的精准核名，行为不变。"""
        self.assertTrue(_row_passes_match(_row("x", "中通快递股份有限公司"), "中通", None))
        self.assertFalse(_row_passes_match(_row("x", "北京华晋中通电力有限公司"), "中通", None))

    def test_missing_company_id_passes(self):
        self.assertTrue(_row_passes_match({"company_name": "某公司"}, "南方电网", self.ok))


if __name__ == "__main__":
    unittest.main()
