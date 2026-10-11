import json
import os
import subprocess
import unittest
from unittest import mock

import httpx

from adapters import byd as byd_module
from adapters.byd import BydAdapter, _list_offsets


class _StubResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


class _StubClient:
    """记录 queryDetail 调用、按 id 返回带 tagDetailList 的 detail（模拟公开接口，不打网络）。"""

    def __init__(self):
        self.calls = []

    def post(self, url, json):  # noqa: A002 (匹配 httpx.Client.post 关键字签名)
        jid = json["id"]
        self.calls.append(jid)
        return _StubResp({"id": jid, "positionName": f"岗位{jid}",
                          "tagDetailList": [{"name": "工作职责", "detail": "x"}]})


class BydAdapterTest(unittest.TestCase):
    def test_list_offsets_use_api_row_offsets_not_page_numbers(self):
        self.assertEqual(_list_offsets(total=2163, page_size=1000), [0, 1000, 2000])
        self.assertEqual(_list_offsets(total=999, page_size=1000), [0])

    def test_parse_only_emits_rows_with_browser_verified_detail_url(self):
        payload = {
            "jobs": [{
                "jd_url": (
                    "https://job.byd.com/portal/pc/#/social/"
                    "socialPositionDetails?verified-token"
                ),
                "detail": {
                    "id": "2062698235843137537",
                    "positionName": "店端服务顾问",
                    "positionTypeId": "003091",
                    "fatherOrgName": "汽车事业群",
                    "province": "广东省",
                    "city": "湛江市",
                    "publishTime": "2026-06-05",
                    "tagDetailList": [
                        {"name": "工作职责", "detail": "负责维修车辆顾客接待。"},
                        {"name": "任职要求", "detail": "沟通协调能力强。"},
                    ],
                },
            }]
        }

        jobs = BydAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "比亚迪")
        self.assertEqual(jobs[0].location, "广东省-湛江市")
        self.assertIn("沟通协调能力强", jobs[0].summary)
        self.assertIn("socialPositionDetails?", jobs[0].jd_url)

    def test_parse_keeps_batch_encrypted_list_row_without_detail_enrichment(self):
        payload = {
            "jobs": [{
                "jd_url": (
                    "https://job.byd.com/portal/pc/#/social/"
                    "socialPositionDetails?Y1KjFap0IfmxZbvDidhqr7iflfUYCzJDKePomU8QFx4="
                ),
                "row": {
                    "id": "2062698235843137537",
                    "positionName": "店端服务顾问",
                    "fatherOrgAliasName": "汽车事业群",
                    "province": "广东省",
                    "city": "湛江市",
                    "createTime": "2026-06-05 08:49:17",
                },
            }]
        }

        jobs = BydAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "店端服务顾问")
        self.assertEqual(jobs[0].job_type, "汽车事业群")
        self.assertEqual(jobs[0].posted_at, "2026-06-05")


_BASE = "https://job.byd.com/portal/pc/#/social/socialPositionDetails?"


class BydDetailUrlTest(unittest.TestCase):
    """详情链接里的密文是 base64，会带 '//'；Vue Router 的 href 会把它压成 '/'，链接就打不开了。"""

    def test_link_is_built_from_full_path_not_href(self):
        # href 只许用来取 '#' 之前的路由 base（那一段没有密文）；密文那一段必须来自 fullPath。
        self.assertIn("resolved.route.fullPath", byd_module._BUILD_DETAIL_URLS_JS)
        self.assertIn("resolved.href.split('#')[0]", byd_module._BUILD_DETAIL_URLS_JS)
        self.assertEqual(byd_module._BUILD_DETAIL_URLS_JS.count(".href"), 2)   # 上面那一处 + new URL(...).href

    def test_only_links_that_decode_back_to_the_same_id_are_kept(self):
        good = _BASE + "at2n3bDPdyn4h4S2Reo8FJW+Tg//qdaRyw9mX6SJu1o="   # 实测的带 '//' 密文，原样保留
        urls = byd_module._verified_detail_urls([
            ["2097132362952380417", good, "2097132362952380417"],
            ["2096769889925652481", _BASE + "x", None],                     # 官方路由解不回来
            ["2084078594987974657", _BASE + "y", "2084"],                   # 解回来不是同一个 id
        ])
        self.assertEqual(urls, {"2097132362952380417": good})

    def test_link_with_another_prefix_is_dropped(self):
        # 官网哪天换了路由 base：一条都不出 → fetch 报错，而不是 parse 安静丢光、记成功 0 岗
        urls = byd_module._verified_detail_urls([
            ["2097132362952380417", "https://job.byd.com/portal/pc#/social/socialPositionDetails?abc=",
             "2097132362952380417"]])
        self.assertEqual(urls, {})

    def test_fetch_is_not_complete_when_a_row_has_no_verified_link(self):
        rows = [{"id": "1", "positionName": "岗位1", "province": "广东省", "city": "深圳市"},
                {"id": "2", "positionName": "岗位2", "province": "广东省", "city": "深圳市"}]

        class _Stub(BydAdapter):
            urls = {}

            def _fetch_list_rows(self, client):
                self.reported_total = len(rows)
                return rows

            def _generate_detail_urls(self, source_url, job_ids):
                return self.urls

            def _fetch_details(self, client, job_ids):
                return {}

        with mock.patch.object(byd_module.httpx, "Client", mock.MagicMock()):
            full = _Stub()
            full.urls = {"1": _BASE + "a", "2": _BASE + "b"}
            self.assertEqual(len(json.loads(full.fetch("https://job.byd.com/portal/pc/"))["jobs"]), 2)
            self.assertTrue(full.fetch_complete)

            partial = _Stub()
            partial.urls = {"1": _BASE + "a"}            # 列表翻全了，但 2 号岗没拿到验过的链接
            self.assertEqual(len(json.loads(partial.fetch("https://job.byd.com/portal/pc/"))["jobs"]), 1)
            self.assertFalse(partial.fetch_complete)

    def test_absence_liveness_stays_off(self):
        # 撤岗走 byd_liveness（不在全量列表 + 详情空骨架）；list-absence 认的是「这轮没写库」，不是一回事。
        self.assertFalse(BydAdapter.supports_absence_liveness)


# 用一个假的 Vue Router 在 node 里真跑那两段页面脚本。假路由照搬真路由与这件事有关的三个行为：
# stringifyQuery / parseQuery 是一对严格互逆的映射（这里用查表代替 AES）；fullPath 原样带密文；
# href 要过 cleanPath（把 '//' 压成 '/'，一遍、不重叠——'///' 压完还剩 '//'）。
_ROUTER_STUB = """
let raw = '';
process.stdin.on('data', c => raw += c).on('end', () => {
  const {table, src, input} = JSON.parse(raw);
  const rev = Object.fromEntries(Object.entries(table).map(([id, token]) => [token, id]));
  const clean = p => p.split('//').join('/');
  const router = {resolve(to) {
    if (typeof to === 'string') {
      const id = rev[to.split('?')[1]];
      return {route: {fullPath: to, query: id ? {id} : {}}, href: clean('/portal/pc' + '/' + '#' + to)};
    }
    const fullPath = to.path + '?' + table[to.query.id];
    return {route: {fullPath, query: to.query}, href: clean('/portal/pc' + '/' + '#' + fullPath)};
  }};
  global.document = {querySelector: () => ({__vue__: {$router: router}})};
  global.location = {origin: 'https://job.byd.com'};
  console.log(JSON.stringify(eval('(' + src + ')')(input)));
});
"""
_A, _B, _C = "2097132362952380417", "2084078591028551682", "2096769889925652481"
_D, _E, _F = "2053673516951162882", "2080113349814685698", "2057644312329453569"
_TOKENS = {_A: "aaaa+bb//cccc=", _B: "dddd/eeee+ffff=", _C: "gg//hh//ii=",
           _D: "x//y/z=", _E: "x/y//z=",          # 两个不同的岗，坏链接压完是同一个串
           _F: "p///q=", "2084": "short="}


def _run_page_script(src, items):
    result = subprocess.run(["node", "-e", _ROUTER_STUB], check=True, capture_output=True, text=True, encoding="utf-8",
                            input=json.dumps({"table": _TOKENS, "src": src, "input": items}))
    return json.loads(result.stdout)


class BydPageScriptTest(unittest.TestCase):
    def test_built_links_keep_double_slash_and_decode_back(self):
        out = _run_page_script(byd_module._BUILD_DETAIL_URLS_JS, [_A, _B, _C])
        self.assertEqual(out, [[i, _BASE + _TOKENS[i], i] for i in (_A, _B, _C)])
        self.assertEqual(byd_module._verified_detail_urls(out), {i: _BASE + _TOKENS[i] for i in (_A, _B, _C)})

    def test_decode_good_links(self):
        out = _run_page_script(byd_module._DECODE_DETAIL_URLS_JS, [_TOKENS[_B], _TOKENS[_A]])
        self.assertEqual(out, [[_TOKENS[_B], _B, None], [_TOKENS[_A], _A, None]])

    def test_decode_repairs_collapsed_links(self):
        out = _run_page_script(byd_module._DECODE_DETAIL_URLS_JS, ["aaaa+bb/cccc=", "gg/hh/ii=", "p//q="])
        self.assertEqual(out, [["aaaa+bb/cccc=", _A, _TOKENS[_A]],     # 一处 '//' 被压
                               ["gg/hh/ii=", _C, _TOKENS[_C]],         # 两处都被压
                               ["p//q=", _F, _TOKENS[_F]]])            # '///' 被压成 '//'

    def test_decode_refuses_to_guess(self):
        out = _run_page_script(byd_module._DECODE_DETAIL_URLS_JS, ["x/y/z=", "short=", "garbage", "no/such/token="])
        self.assertEqual(out, [["x/y/z=", None, None],            # 补回去有两个岗都说得通 → 不认
                               ["short=", None, None],            # 解出来的不是 15~20 位数字
                               ["garbage", None, None],
                               ["no/such/token=", None, None]])


class BydFetchDetailsTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    def tearDown(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    def test_fetch_details_covers_all_ids_not_capped_at_20(self):
        client = _StubClient()
        ids = [str(i) for i in range(25)]  # >20：旧 DETAIL_CAP=20 只补前 20，现覆盖全量
        details = BydAdapter()._fetch_details(client, ids)
        self.assertEqual(len(details), 25)
        self.assertEqual(sorted(client.calls, key=int), sorted(ids, key=int))
        self.assertEqual(details["7"]["positionName"], "岗位7")

    def test_fetch_details_skipped_when_env_cap_zero(self):
        os.environ["CRAWL_DETAIL_CAP"] = "0"  # 快档：跳过逐岗富化
        details = BydAdapter()._fetch_details(_StubClient(), ["1", "2", "3"])
        self.assertEqual(details, {})

    def test_fetch_details_skips_failed_fetches(self):
        class _FlakyClient(_StubClient):
            def post(self, url, json):
                if json["id"] == "2":
                    raise httpx.HTTPError("boom")  # 单岗失败不阻断整批
                return super().post(url, json)

        details = BydAdapter()._fetch_details(_FlakyClient(), ["1", "2", "3"])
        self.assertEqual(set(details), {"1", "3"})


if __name__ == "__main__":
    unittest.main()
