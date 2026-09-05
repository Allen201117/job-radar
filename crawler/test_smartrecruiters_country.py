"""SmartRecruiters 的 location.country 是 ISO-2 码，不是国名。

这组测试守两件事：
  1. adapter 出口把码展开成国名（否则 geo 一个都认不出来，中国岗被丢、海外岗被当国内岗）；
  2. **表里每一个国名，geo 都能判对 domestic/overseas** —— 这是契约：以后往表里加国家，
     忘了同步 geo.OVERSEAS_LOCATION_TOKENS 就直接红，不会等到线上把海外岗混进国内岗才发现。
"""
import unittest

import geo
from adapters.smartrecruiters import (
    _ISO2_COUNTRY_NAMES,
    _location_str,
    SmartRecruitersAdapter,
)

# 补 CN 之后这批外企源的 regions 长这样，判 job_scope 时最容易出事的就是它
_OVERSEAS_SOURCE_WITH_CN = {"CN", "US", "SG", "Remote"}
_GREATER_CHINA_CODES = {"cn", "hk", "mo"}


class TestCountryLabel(unittest.TestCase):
    def test_remote_country_code_becomes_country_name(self):
        self.assertEqual(_location_str({"remote": True, "country": "cn"}), "Remote China")
        self.assertEqual(_location_str({"remote": True, "country": "de"}), "Remote Germany")

    def test_city_rows_also_get_country_name(self):
        # 拼音分写（合肥 = He Fei Shi）时 geo 的城市词典对不上，全靠展开后的国名兜住
        self.assertEqual(
            _location_str({"city": "He Fei Shi", "region": "An Hui Sheng", "country": "cn"}),
            "He Fei Shi, An Hui Sheng, China",
        )
        self.assertEqual(geo.derive_country_code("He Fei Shi, An Hui Sheng, China"), "CN")

    def test_unknown_code_is_passed_through(self):
        # SmartRecruiters 自己会返占位码 "xx"，认不出就原样带着，不编造国家
        self.assertEqual(_location_str({"remote": True, "country": "xx"}), "Remote xx")
        self.assertIsNone(_location_str({}))
        self.assertIsNone(_location_str(None))


class TestGeoCoversEveryCountryInTable(unittest.TestCase):
    def test_every_country_name_is_classified(self):
        for code, name in _ISO2_COUNTRY_NAMES.items():
            expected = "domestic" if code in _GREATER_CHINA_CODES else "overseas"
            for location in (name, f"Remote {name}"):
                with self.subTest(code=code, location=location):
                    self.assertEqual(
                        geo.derive_job_scope(location, _OVERSEAS_SOURCE_WITH_CN), expected,
                        f"{code} -> {location!r} 判错了：往 _ISO2_COUNTRY_NAMES 加国家时，"
                        f"必须同步 geo.OVERSEAS_LOCATION_TOKENS / _PHRASES",
                    )


class TestParseKeepsChinaRows(unittest.TestCase):
    def _parse(self, rows, regions):
        a = SmartRecruitersAdapter()
        a.regions = regions
        import json
        return a.parse(json.dumps({"content": rows}))

    def _row(self, name, loc):
        return {"name": name, "id": "1" + name, "company": {"identifier": "acme"}, "location": loc}

    def test_china_remote_row_is_kept_and_domestic_once_source_has_cn(self):
        rows = [self._row("CN Remote", {"remote": True, "country": "cn"})]
        jobs = self._parse(rows, _OVERSEAS_SOURCE_WITH_CN)
        self.assertEqual([j.location for j in jobs], ["Remote China"])
        self.assertEqual(geo.derive_job_scope(jobs[0].location, _OVERSEAS_SOURCE_WITH_CN), "domestic")

    def test_foreign_remote_row_stays_overseas_even_when_source_has_cn(self):
        rows = [self._row("DE Remote", {"remote": True, "country": "de"})]
        jobs = self._parse(rows, _OVERSEAS_SOURCE_WITH_CN)
        self.assertEqual([j.location for j in jobs], ["Remote Germany"])
        self.assertEqual(geo.derive_job_scope(jobs[0].location, _OVERSEAS_SOURCE_WITH_CN), "overseas")

    def test_every_foreign_remote_shape_seen_live_stays_overseas(self):
        """把 2026-09-05 线上真实出现过的「Remote {ISO2}」写法全部钉死。

        为什么要逐条钉：geo 的判定链被并行改动重排过好几次（中文行政区、美国州名、
        is_overseas_unspecified 都插在这条链上），**单测绿不代表这条不变量还在**。
        这里量过的实况是：补 CN 之后若少了「先判钉死海外」这一步，
        艾伯维 / 大陆集团 / Grab / Expeditors / 育碧 上共 125 个海外远程岗会被判成国内岗。
        注意 main 的 geo 只认了 "cn" 一个码，下面这些码它一个都不认 ——
        全靠 adapter 出口展开成国名 + derive_job_scope 的 _is_overseas_pinned 兜住。
        """
        for code in ("de", "ro", "lv", "cz", "my", "vn", "th", "hu", "rs", "si",
                     "bg", "hr", "ru", "ee", "ca", "pl", "es", "tr", "kr", "br"):
            location = _location_str({"remote": True, "country": code})
            with self.subTest(code=code, location=location):
                self.assertEqual(
                    geo.derive_job_scope(location, _OVERSEAS_SOURCE_WITH_CN), "overseas",
                    f"{location!r} 被判成国内岗了 —— 补了 CN 的外企源上，"
                    f"「地点已钉死在海外」必须优先于 source.regions 兜底",
                )

    def test_china_row_dropped_when_source_regions_exclude_cn(self):
        rows = [self._row("CN Remote", {"remote": True, "country": "cn"})]
        self.assertEqual(self._parse(rows, {"US", "SG", "Remote"}), [])


if __name__ == "__main__":
    unittest.main()
