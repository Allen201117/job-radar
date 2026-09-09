"""得物校招（campus.dewu.com/578078）离线单测——不打真网络。

覆盖：FeishuGenericAdapter 面对「路径段既不是 index 也不是常见子门户名，而是租户自己的数字
portal id」这种新形态（此前只见过 campus/internship/newretailing 这类语义化子门户）时，
_bind_host / _bind_website_path 的推导是否仍然正确——这是接入前 live 核验过的关键假设：
本类**不需要任何代码改动**就能覆盖 campus.dewu.com，本测试把这个假设钉成回归。
"""
import unittest

from adapters import feishu

SOURCE_URL = "https://campus.dewu.com/578078"

# 与 live 实测（2026-09-09）response shape 一致的离线 fixture（字段裁剪自真实响应）。
_FIXTURE_POST = {
    "id": "7672234301103278382",
    "title": "【27届校招】安全产品/策略开发工程师",
    "description": "1. 通过技术手段分析、验证、优化现有安全威胁的感知、入侵检测等防御能力效果；",
    "requirement": "1.2027届毕业生，本科及以上学历，对常见漏洞了解其原理和本质；",
    "job_category": None,
    "city_info": {"name": "上海"},
    "recruit_type": {
        "id": "201", "name": "正式",
        "parent": {"id": "2", "name": "校招"},
    },
    "publish_time": 1757395200000,
}

_FIXTURE_INTERN_POST = {
    "id": "7670544823561341238",
    "title": "供应链专项实习生",
    "description": "供应链专项实习岗位描述",
    "requirement": "",
    "job_category": {"name": "供应链"},
    "city_info": None,
    "city_list": [{"name": "杭州"}],
    "recruit_type": {
        "id": "202", "name": "实习",
        "parent": {"id": "2", "name": "校招"},
    },
}


class DewuCampusPathDerivationTest(unittest.TestCase):
    """路径段是数字 portal id（"578078"）时，通用层的门户/详情推导必须与 live 实测一致。"""

    def _adapter(self):
        a = feishu.FeishuGenericAdapter()
        a._bind_host(SOURCE_URL)
        return a

    def test_numeric_portal_id_is_not_treated_as_index(self):
        a = self._adapter()
        self.assertEqual(a.official_hosts, ("campus.dewu.com",))
        self.assertEqual(
            a.detail_template,
            "https://campus.dewu.com/578078/position/{id}/detail",
        )
        self.assertIn("https://campus.dewu.com/578078", a.list_urls)

    def test_website_path_header_derived_from_numeric_segment(self):
        """_bind_website_path 必须把 "578078" 当成子门户名（与 live 实测 header 一致），
        而不是像 "index"/"position" 那样归零——归零会打回社招混合池（600 岗里只 50 条校招）。"""
        a = self._adapter()
        a._bind_website_path(SOURCE_URL)
        self.assertEqual(a.website_path, "578078")
        self.assertEqual(
            a.detail_template,
            "https://campus.dewu.com/578078/position/{id}/detail",
        )

    def test_jd_url_matches_live_verified_template(self):
        a = self._adapter()
        a._bind_website_path(SOURCE_URL)
        job = a._map(_FIXTURE_POST)
        self.assertIsNotNone(job)
        self.assertEqual(
            job.jd_url,
            "https://campus.dewu.com/578078/position/7672234301103278382/detail",
        )
        self.assertEqual(job.title, "【27届校招】安全产品/策略开发工程师")
        self.assertEqual(job.location, "上海")
        self.assertIn("安全威胁", job.summary)
        self.assertIn("2027届毕业生", job.summary)

    def test_intern_post_maps_city_from_city_list_fallback(self):
        a = self._adapter()
        a._bind_website_path(SOURCE_URL)
        job = a._map(_FIXTURE_INTERN_POST)
        self.assertIsNotNone(job)
        self.assertEqual(job.location, "杭州")
        self.assertEqual(job.job_type, "供应链")

    def test_missing_id_or_title_is_dropped(self):
        a = self._adapter()
        a._bind_website_path(SOURCE_URL)
        self.assertIsNone(a._map({"id": "", "title": "无 id"}))
        self.assertIsNone(a._map({"id": "123", "title": ""}))


if __name__ == "__main__":
    unittest.main()
