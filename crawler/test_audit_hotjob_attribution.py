"""audit_hotjob_attribution 的契约：名字核验双向、渠道后缀与拉丁名不干扰、接口失败记 unknown 不判错。"""
import unittest

try:
    from audit_hotjob_attribution import cjk_name, names_agree, audit
except ModuleNotFoundError:
    from crawler.audit_hotjob_attribution import cjk_name, names_agree, audit


class NamesTest(unittest.TestCase):
    def test_cjk_name_strips_latin_and_channel_suffix(self):
        self.assertEqual(cjk_name("领益智造 Lingyi 实习"), "领益智造")
        self.assertEqual(cjk_name("新疆特变电工集团 校招"), "新疆特变电工集团")
        self.assertEqual(cjk_name("Shell"), "")

    def test_agree_in_either_direction(self):
        # 反向：租户名的核心 token「特变电工」落在库名里
        self.assertTrue(names_agree("新疆特变电工集团 校招", "特变电工股份有限公司"))
        # 正向：库名「领益智造」落在租户全称里
        self.assertTrue(names_agree("领益智造 Lingyi", "广东领益智造股份有限公司"))

    def test_mislabels_are_caught(self):
        self.assertFalse(names_agree("领益智造 Lingyi 实习", "特变电工股份有限公司"))   # 274
        self.assertFalse(names_agree("京东集团", "精雕科技集团股份有限公司"))            # 248

    def test_empty_side_is_not_agreement(self):
        self.assertFalse(names_agree("Shell", "壳牌中国"))
        self.assertFalse(names_agree("华夏银行", ""))


class AuditTest(unittest.TestCase):
    def test_audit_buckets_and_caches_per_tenant(self):
        rows = [
            {"company": "领益智造 Lingyi", "source_url": "https://wecruit.hotjob.cn/SU1/pb/social.html"},
            {"company": "领益智造 Lingyi 校招", "source_url": "https://wecruit.hotjob.cn/SU1/pb/school.html"},
            {"company": "华夏银行", "source_url": "https://hxb.hotjob.cn/SU2/pb/social.html"},
            {"company": "某某", "source_url": "https://x.hotjob.cn/SU3/pb/social.html"},
        ]
        answers = {"SU1": {"data": {"companyName": "特变电工股份有限公司"}},
                   "SU2": {"data": {"companyName": "华夏银行股份有限公司"}}}
        calls = []

        class Resp:
            def __init__(self, payload):
                self._p = payload

            def json(self):
                return self._p

        class Client:
            def post(self, url, headers=None):
                key = url.rsplit("/", 1)[-1]
                calls.append(key)
                if key not in answers:
                    raise RuntimeError("boom")
                return Resp(answers[key])

        mismatches, unknowns, ok = audit(rows, Client())
        self.assertEqual([m[0] for m in mismatches], ["领益智造 Lingyi", "领益智造 Lingyi 校招"])
        self.assertEqual([u[0] for u in unknowns], ["某某"])
        self.assertEqual(ok, 1)
        self.assertEqual(calls, ["SU1", "SU2", "SU3"])  # 同租户两条源只问一次


if __name__ == "__main__":
    unittest.main()
