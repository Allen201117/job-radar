"""「连续 7 天报成功却零产出」专项（2026-09-23）的回归钉子。

三件事各钉一处：
1. 假绿体检拆成两条：需要人处理的 vs 休眠中的校招/实习入口（口径见 audit_contract.yaml 注释）；
2. Moka 校招门户换期换 id 时记 failed、不再安静地 0 岗 success（新口径的盲区对策）；
3. SuccessFactors 卡片版列表（Ferrari 已切），表格版租户行为不变。
单测不打真实网络。
"""
import inspect
import re
import unittest
from unittest import mock

import httpx

import audit_runner
import morning_digest
from adapters.china_ats import MokaAdapter
from adapters.successfactors import SuccessFactorsAdapter, _parse_list_rows


def _checks_by_id():
    return {c["id"]: c for c in audit_runner.load_contract()}


class FakeGreenContractTest(unittest.TestCase):
    def test_chronic_check_only_counts_enabled_sources(self):
        sql = _checks_by_id()["exp.fake_green_sources_chronic"]["sql"]
        # 已停用的源是「有人处理过了」，不该再在 7 天窗口里被当成没人发现的坏源（奥普特就是这么多算了一周）
        self.assertIn("s.enabled", sql)

    def test_dormant_campus_is_excluded_from_chronic_and_counted_separately(self):
        checks = _checks_by_id()
        chronic, dormant = checks["exp.fake_green_sources_chronic"], checks["exp.fake_green_campus_dormant"]
        # 两条的「休眠」判据必须是同一段，否则会有源两头都不算（藏掉）或两头都算
        dormant_rule = re.compile(
            r"exists \(\s*select 1 from crawl_runs x\s*where x\.source_id = r\.source_id and x\.jobs_found > 0"
            r"\s*and x\.started_at >= now\(\) - interval '365 days'\)")
        self.assertRegex(chronic["sql"], r"not \(coalesce\(s\.board, ''\) in \('campus', 'intern'\) and "
                         + dormant_rule.pattern)
        self.assertIn("coalesce(s.board, '') in ('campus', 'intern')", dormant["sql"])
        self.assertRegex(dormant["sql"], dormant_rule)
        # 休眠是常态：只留数不染灯
        self.assertEqual(dormant["severity"], "info")
        self.assertEqual(chronic["severity"], "warn")

    def test_both_checks_reach_the_morning_digest(self):
        for cid in ("exp.fake_green_sources_chronic", "exp.fake_green_campus_dormant"):
            self.assertIn(cid, morning_digest.SECTION_FAKE_GREEN)


class _Resp:
    def __init__(self, location):
        self.headers = {"location": location} if location is not None else {}


class _AliasPage:
    """只记录打开了哪个地址；_open_route 由测试替换。"""


class MokaCampusPortalSupersededTest(unittest.TestCase):
    def _adapter(self, current_id, alias_cards=None, alias_error=None):
        a = MokaAdapter()
        a._current_campus_portal_id = lambda host, tenant: current_id
        a.opened = []

        def fake_open(page, url):
            a.opened.append(url)
            if alias_error:
                raise alias_error
            return ("cards" if alias_cards else "empty"), alias_cards or []
        a._open_route = fake_open
        return a

    def test_empty_old_portal_with_live_newer_portal_raises_with_new_address(self):
        a = self._adapter("188032", alias_cards=[{"href": "#/job/x"}] * 10)
        with self.assertRaises(RuntimeError) as ctx:
            a._raise_if_campus_portal_superseded(_AliasPage(), "https://app.mokahr.com/campus-recruitment/dahua/118041")
        self.assertIn("superseded", str(ctx.exception))
        self.assertIn("campus_apply/dahua/188032", str(ctx.exception))
        self.assertEqual(a.opened, ["https://app.mokahr.com/campus_apply/dahua/188032#/jobs"])

    def test_newer_portal_also_empty_is_just_dormant(self):
        # 华虹：别名指向的恰恰是没配置过的空模板 —— 不能因为「别名不同」就把休眠记成失败
        self._adapter("74008")._raise_if_campus_portal_superseded(
            _AliasPage(), "https://app.mokahr.com/campus-recruitment/huahong/74036")

    def test_newer_portal_unreadable_does_not_raise(self):
        a = self._adapter("188032", alias_error=TimeoutError("render"))
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            a._raise_if_campus_portal_superseded(_AliasPage(), "https://app.mokahr.com/campus-recruitment/dahua/118041")

    def test_same_id_is_just_dormant_and_opens_nothing(self):
        # 在 25 个名单里的 7 个 Moka 校招源 live 全是这种：别名就指向自己，页面自写 0 岗 = 真休眠
        a = self._adapter("67992", alias_cards=[{"href": "#/job/x"}])
        a._raise_if_campus_portal_superseded(_AliasPage(), "https://app.mokahr.com/campus-recruitment/tuiquan/67992")
        self.assertEqual(a.opened, [])

    def test_unknown_alias_does_not_raise(self):
        # 问不到平台 ≠ 换了期：宁可漏报，不把正常休眠记成失败
        self._adapter(None, alias_cards=[{"href": "#/job/x"}])._raise_if_campus_portal_superseded(
            _AliasPage(), "https://app.mokahr.com/campus_apply/xgimi/5463")

    def test_non_campus_or_idless_or_foreign_host_is_not_checked(self):
        a = MokaAdapter()
        a._current_campus_portal_id = mock.Mock(side_effect=AssertionError("不该查"))
        for url in ("https://app.mokahr.com/social-recruitment/xgimi/142344",  # 社招
                    "https://app.mokahr.com/campus_apply/zhihu",                # 无 id 别名本身就跟着当前期走
                    "https://campus.geely.com/campus-recruitment/geely/78436"):  # 非平台域名
            a._raise_if_campus_portal_superseded(_AliasPage(), url)

    def test_alias_lookup_reads_redirect_target_without_following(self):
        a = MokaAdapter()
        with mock.patch.object(httpx, "get", return_value=_Resp(
                "https://app.mokahr.com/campus_apply/xgimi/164562")) as get:
            self.assertEqual(a._current_campus_portal_id("app.mokahr.com", "xgimi"), "164562")
        self.assertFalse(get.call_args.kwargs["follow_redirects"])
        with mock.patch.object(httpx, "get", return_value=_Resp("/campus-recruitment/xgimi/164562")):
            self.assertEqual(a._current_campus_portal_id("app.mokahr.com", "xgimi"), "164562")
        # 别的租户的 id 不许认（location 里的租户名必须是自己）
        with mock.patch.object(httpx, "get", return_value=_Resp("/campus_apply/other/1")):
            self.assertIsNone(a._current_campus_portal_id("app.mokahr.com", "xgimi"))
        with mock.patch.object(httpx, "get", return_value=_Resp(None)):
            self.assertIsNone(a._current_campus_portal_id("app.mokahr.com", "xgimi"))

    def test_alias_lookup_network_error_is_logged_and_returns_none(self):
        a = MokaAdapter()
        with mock.patch.object(httpx, "get", side_effect=httpx.ConnectTimeout("boom")), \
                self.assertLogs("adapters.china_ats", level="WARNING"):
            self.assertIsNone(a._current_campus_portal_id("app.mokahr.com", "xgimi"))

    def test_fetch_only_asks_when_portal_rendered_empty(self):
        # 一个租户常同时开好几个校招门户（全量扫 22 条别名≠存的 id，20 条照常出岗）→ 有岗时绝不查
        src = inspect.getsource(MokaAdapter.fetch)
        self.assertRegex(src, r"if best_route is None:\s*\n(\s*#.*\n)*\s*self\._raise_if_campus_portal_superseded\(page, source_url\)")


_TILE = """
<ul data-record-returned="2">
<li class="job-tile job-id-1" data-url="/job/A/1/">
  <div class="sub-section-desktop">
    <a class="jobTitle-link" href="/job/A/1/"> Accounting Specialist </a>
    <div id="job-1-desktop-section-location-value">Englewood Cliffs, New Jersey, US </div>
  </div>
  <div class="sub-section-tablet">
    <a class="jobTitle-link" href="/job/A/1/"> Accounting Specialist </a>
    <div id="job-1-tablet-section-location-value">Englewood Cliffs, New Jersey, US </div>
  </div>
</li>
<li class="job-tile job-id-2" data-url="/job/B/2/">
  <div class="sub-section-desktop">
    <a class="jobTitle-link" href="/job/B/2/">Material Planner Internship</a>
    <div id="job-2-desktop-section-location-value">Maranello, IT</div>
  </div>
</li>
</ul>
"""

_TABLE = """
<table><tr class="data-row"><td><a class="jobTitle-link" href="/job/X/9/">Engineer</a>
<span class="jobLocation">Shanghai, CN</span></td></tr>
<tr class="data-row"><td>装饰行没有链接</td></tr></table>
<ul><li class="job-tile"><a class="jobTitle-link" href="/job/Y/8/">不该被读到</a></li></ul>
"""


class SuccessFactorsListLayoutTest(unittest.TestCase):
    def test_tile_layout_is_parsed_once_per_tile(self):
        count, items = _parse_list_rows(_TILE)
        self.assertEqual(count, 2)
        self.assertEqual(items, [
            {"title": "Accounting Specialist", "href": "/job/A/1/", "location": "Englewood Cliffs, New Jersey, US"},
            {"title": "Material Planner Internship", "href": "/job/B/2/", "location": "Maranello, IT"},
        ])

    def test_table_layout_wins_and_decorative_rows_still_take_a_startrow_slot(self):
        count, items = _parse_list_rows(_TABLE)
        self.assertEqual(count, 2, "装饰行也占服务端一个 startrow 位置")
        self.assertEqual(items, [{"title": "Engineer", "href": "/job/X/9/", "location": "Shanghai, CN"}])

    def test_regions_filter_applies_to_tile_rows(self):
        a = SuccessFactorsAdapter()
        a.regions = ["CN", "US", "SG", "Remote"]
        _, items = _parse_list_rows(_TILE)
        rows = [dict(r, url="https://jobs.ferrari.com" + r["href"]) for r in items]
        jobs = a.parse(__import__("json").dumps({"jobs": rows}))
        self.assertEqual([j.title for j in jobs], ["Accounting Specialist"])


if __name__ == "__main__":
    unittest.main()
