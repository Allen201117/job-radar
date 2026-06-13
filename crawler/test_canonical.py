"""canonicalize_jd_url 单测——必须与 lib/canonical-url.js / SQL canonicalize_jd_url 逐字一致。

测试用例与 tests/canonical-url.test.js 镜像（同输入同输出），任一处改规则两套测试同步补。
不打网络，纯函数。
"""
import unittest

from normalizer import canonicalize_jd_url


class CanonicalizeJdUrlTest(unittest.TestCase):
    def test_plain_url_unchanged(self):
        self.assertEqual(canonicalize_jd_url("https://x.com/job/123"), "https://x.com/job/123")

    def test_trailing_slash_stripped(self):
        self.assertEqual(canonicalize_jd_url("https://x.com/job/123/"), "https://x.com/job/123")
        self.assertEqual(canonicalize_jd_url("https://x.com/job/123//"), "https://x.com/job/123")

    def test_utm_stripped(self):
        self.assertEqual(
            canonicalize_jd_url("https://x.com/job/123?utm_source=li&utm_medium=x"),
            "https://x.com/job/123",
        )

    def test_tracking_key_case_insensitive(self):
        self.assertEqual(
            canonicalize_jd_url("https://x.com/job?UTM_Source=a&id=1"),
            "https://x.com/job?id=1",
        )

    def test_keeps_business_params(self):
        self.assertEqual(
            canonicalize_jd_url("https://x.com/job?id=5&utm_source=li"),
            "https://x.com/job?id=5",
        )
        self.assertEqual(
            canonicalize_jd_url("https://zhaopin.jd.com/web/job-info-detail?requementId=99&spm=abc"),
            "https://zhaopin.jd.com/web/job-info-detail?requementId=99",
        )

    def test_common_tracking_stripped(self):
        self.assertEqual(canonicalize_jd_url("https://x.com/p?spm=abc&id=9"), "https://x.com/p?id=9")
        self.assertEqual(canonicalize_jd_url("https://x.com/p?id=9&gclid=zz"), "https://x.com/p?id=9")
        self.assertEqual(canonicalize_jd_url("https://x.com/p?bd_vid=1&id=9"), "https://x.com/p?id=9")

    def test_trailing_slash_and_tracking(self):
        self.assertEqual(
            canonicalize_jd_url("https://x.com/job/1/?utm_source=a"),
            "https://x.com/job/1",
        )

    def test_spa_hash_route_untouched(self):
        moka = "https://app.mokahr.com/apply/x/123#/job/456?utm_source=li"
        self.assertEqual(canonicalize_jd_url(moka), moka)
        ctrip = "https://careers.ctrip.com/#/experienced/job-detail/789"
        self.assertEqual(canonicalize_jd_url(ctrip), ctrip)

    def test_empty_and_none_safe(self):
        self.assertIsNone(canonicalize_jd_url(None))
        self.assertEqual(canonicalize_jd_url(""), "")
        self.assertEqual(canonicalize_jd_url("   "), "")

    def test_bare_flag_param_kept(self):
        self.assertEqual(canonicalize_jd_url("https://x.com/job?foo"), "https://x.com/job?foo")

    def test_empty_param_segments_dropped(self):
        self.assertEqual(canonicalize_jd_url("https://x.com/job?a=1&&b=2"), "https://x.com/job?a=1&b=2")

    def test_trailing_question_mark_stripped(self):
        self.assertEqual(canonicalize_jd_url("https://x.com/job?"), "https://x.com/job")

    def test_whitespace_trimmed_then_normalized(self):
        self.assertEqual(canonicalize_jd_url("  https://x.com/job/1/  "), "https://x.com/job/1")


if __name__ == "__main__":
    unittest.main()
