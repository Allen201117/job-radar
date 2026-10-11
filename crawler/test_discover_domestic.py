"""discover_domestic moka 校招板块探测 + hotjob/wt 公司名核验单测（mock httpx client，不打真网络）。

红线：① 校招候选是独立于社招的第二条命中（各自 title-verify，互不覆盖）；
② 校招 URL 必须命中 CAMPUS_URL_RE（lib/campus-sources.ts 同款正则）才算「校招源」；
③ 租户没开校招板块（404/不存在/无 orgId）时不产出候选，不是错误；
④ hotjob_probe/wt_probe 的 verified 必须核验自报公司名，不能只看 suiteKey/岗位数
（2026-09-18 修：live 实测 ampace.hotjob.cn 同时被「新能安」「安脉时代」两个目标猜中，
两者列表接口自报 company 全是「厦门新能安（XMC）」，此前逻辑会把两个都判 verified=True）。
"""
import re
import unittest
from unittest import mock

import discover_domestic as dd

# 与 lib/campus-sources.ts 的 CAMPUS_URL_RE 等价（校招源判定口径必须两端一致）。
CAMPUS_URL_RE = re.compile(r"campus|xiaozhao|校招|校园|campus_apply|/campus", re.I)


class _FakeResponse:
    def __init__(self, url, text):
        self.url = url
        self.text = text
        self.status_code = 200


class _FakeClient:
    """按 URL 前缀匹配返回预置响应；未匹配的 URL 视为测试疏漏，直接报错方便定位。"""

    def __init__(self, routes):
        self._routes = routes  # {url_prefix: _FakeResponse}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        for prefix, resp in self._routes.items():
            if url.startswith(prefix):
                return resp
        raise AssertionError(f"unexpected GET in test: {url}")


def _patched_client(routes):
    return mock.patch.object(dd, "_client", return_value=_FakeClient(routes))


class MokaCampusProbeTest(unittest.TestCase):
    """moka_probe 命中社招后顺带探校招板块，产出独立 campus 候选。"""

    def test_social_and_campus_both_found(self):
        routes = {
            "https://app.mokahr.com/social-recruitment/jimi": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/jimi/142344",
                "<title>极米科技招聘 - 极米</title>"),
            "https://app.mokahr.com/campus-recruitment/jimi": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/jimi/150242",
                "<title>极米科技校园招聘 - 极米</title>"),
        }
        with _patched_client(routes):
            r = dd.moka_probe("jimi", "极米")
        self.assertIsNotNone(r)
        self.assertTrue(r["verified"])
        self.assertIn("campus", r)
        self.assertEqual(r["campus"]["org_id"], "150242")
        self.assertEqual(r["campus"]["url"],
                         "https://app.mokahr.com/campus-recruitment/jimi/150242")
        # 校招 org 与社招 org 不同（极米 live 实测 142344 vs 150242）
        self.assertNotEqual(r["org_id"], r["campus"]["org_id"])

    def test_campus_absent_when_tenant_has_no_campus_board(self):
        """很多租户没开校招板块——不是错误，只是没有 campus 候选。"""
        routes = {
            "https://app.mokahr.com/social-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/foo/98765",
                "<title>foo公司招聘 - foo</title>"),
            "https://app.mokahr.com/campus-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/foo",
                "<title>您访问的页面不存在</title>"),
        }
        with _patched_client(routes):
            r = dd.moka_probe("foo", "foo公司")
        self.assertIsNotNone(r)
        self.assertNotIn("campus", r)

    def test_campus_title_mismatch_rejected(self):
        """校招页面 title 命中别的公司（疑似张冠李戴/租户复用）→ 独立拒绝，不因社招验证过就照单全收。"""
        routes = {
            "https://app.mokahr.com/social-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/foo/98765",
                "<title>foo公司招聘 - foo</title>"),
            "https://app.mokahr.com/campus-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/foo/11111",
                "<title>别家公司校园招聘</title>"),
        }
        with _patched_client(routes):
            r = dd.moka_probe("foo", "foo公司")
        self.assertIsNotNone(r)
        self.assertNotIn("campus", r)


class ProbeCompanyCampusSplitTest(unittest.TestCase):
    """_probe_company：社招/校招各自产出独立命中，campus URL 命中 CAMPUS_URL_RE。"""

    def test_produces_two_separate_hits(self):
        routes = {
            "https://app.mokahr.com/social-recruitment/jimi": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/jimi/142344",
                "<title>极米科技招聘 - 极米</title>"),
            "https://app.mokahr.com/campus-recruitment/jimi": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/jimi/150242",
                "<title>极米科技校园招聘 - 极米</title>"),
        }
        target = {"company": "极米", "cn": "极米", "slugs": ["jimi"], "industry": "消费电子"}
        with _patched_client(routes):
            hits = dd._probe_company(target, {"moka"})
        self.assertEqual(len(hits), 2)
        social = next(h for h in hits if h.get("kind") != "campus")
        campus = next(h for h in hits if h.get("kind") == "campus")
        self.assertEqual(social["platform"], "moka")
        self.assertEqual(campus["platform"], "moka")
        self.assertTrue(campus["verified"])
        self.assertRegex(campus["url"], CAMPUS_URL_RE)
        self.assertNotRegex(social["url"], CAMPUS_URL_RE)  # 社招 URL 不应误判成校招

    def test_no_campus_board_yields_single_hit(self):
        routes = {
            "https://app.mokahr.com/social-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/foo/98765",
                "<title>foo公司招聘 - foo</title>"),
            "https://app.mokahr.com/campus-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/foo",
                "<title>您访问的页面不存在</title>"),
        }
        target = {"company": "foo公司", "cn": "foo公司", "slugs": ["foo"], "industry": "x"}
        with _patched_client(routes):
            hits = dd._probe_company(target, {"moka"})
        self.assertEqual(len(hits), 1)
        self.assertNotEqual(hits[0].get("kind"), "campus")


class ToMokaCandidatesCampusTest(unittest.TestCase):
    """to_moka_candidates：社招与校招命中各自转成独立候选，均通过质量门（verified）才入选。"""

    def test_both_kinds_become_candidates(self):
        hits = [
            {"platform": "moka", "company": "极米", "industry": "消费电子", "verified": True,
             "url": "https://app.mokahr.com/social-recruitment/jimi/142344"},
            {"platform": "moka", "kind": "campus", "company": "极米", "industry": "消费电子",
             "verified": True, "url": "https://app.mokahr.com/campus-recruitment/jimi/150242"},
        ]
        cands = dd.to_moka_candidates(hits)
        self.assertEqual(len(cands), 2)
        urls = {c["url"] for c in cands}
        self.assertIn("https://app.mokahr.com/campus-recruitment/jimi/150242", urls)
        campus_cand = next(c for c in cands if c["kind"] == "campus")
        self.assertRegex(campus_cand["url"], CAMPUS_URL_RE)
        self.assertEqual(campus_cand["adapter"], "moka")

    def test_unverified_dropped_even_with_campus_kind(self):
        hits = [{"platform": "moka", "kind": "campus", "company": "X", "verified": False,
                "url": "https://app.mokahr.com/campus-recruitment/x/1"}]
        self.assertEqual(dd.to_moka_candidates(hits), [])


class _FakeJsonOrHtmlResp:
    """hotjob/wt 探测用的假响应：JSON 接口传 json_payload，HTML 落地页传 text。"""

    def __init__(self, status_code=200, json_payload=None, text="", url=""):
        self.status_code = status_code
        self._json = json_payload
        self.text = text
        self.url = url

    def json(self):
        return self._json


class _FakeHotjobClient:
    """按 (method, url 前缀) 分派；路由值可以是响应本身，也可以是 callable(**kwargs)->响应
    （用于按 recruitType 等请求参数返回不同数据）。未匹配的调用直接报错，方便定位测试疏漏。"""

    def __init__(self, get_routes=None, post_routes=None):
        self._get = get_routes or {}
        self._post = post_routes or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _dispatch(self, routes, url, kwargs, method):
        for prefix, resp in routes.items():
            if url.startswith(prefix):
                return resp(**kwargs) if callable(resp) else resp
        raise AssertionError(f"unexpected {method} in test: {url}")

    def get(self, url, **kwargs):
        return self._dispatch(self._get, url, kwargs, "GET")

    def post(self, url, **kwargs):
        return self._dispatch(self._post, url, kwargs, "POST")


def _patched_hotjob_client(get_routes=None, post_routes=None):
    return mock.patch.object(dd, "_client",
                             return_value=_FakeHotjobClient(get_routes, post_routes))


def _wecruit_list_dispatch(company, social_count=1):
    """listPosition 分派器：只有 recruitType=2（社招）返回一条自报 company 的岗位，
    校招/实习渠道返回空（与真实 ampace.hotjob.cn 观测一致：某些渠道本就没开）。"""
    def _dispatch(**kwargs):
        rt = (kwargs.get("data") or {}).get("recruitType")
        if rt == 2:
            return _FakeJsonOrHtmlResp(json_payload={"data": {"pageForm": {
                "pageData": [{"postId": "1", "postName": "两轮车大客户代表", "company": company}],
                "total": social_count}}})
        return _FakeJsonOrHtmlResp(json_payload={"data": {"pageForm": {"pageData": [], "total": 0}}})
    return _dispatch


class HotjobWecruitCompanyVerifyTest(unittest.TestCase):
    """hotjob_probe 的 wecruit 分支：verified 必须核验列表接口自报的 `company` 字段。"""

    def _routes(self, company):
        host = "ampace.hotjob.cn"
        origin = f"https://{host}"
        suite_key = "SU6619d98e1eb8053acd618afb"
        post_routes = {
            f"{origin}/wecruit/common/getSLD": _FakeJsonOrHtmlResp(json_payload={
                "data": {"linkData": {"link": f"{origin}/{suite_key}/pb/index.html#/",
                                       "title": "Ampace招聘官网"}},
                "state": "200", "type": "success"}),
            f"{origin}/wecruit/positionInfo/listPosition/{suite_key}":
                _wecruit_list_dispatch(company),
        }
        return post_routes

    def test_verified_true_when_self_reported_company_matches_target(self):
        """正例：自报 company「厦门新能安（XMC）」含目标核心词「新能安」→ verified=True。"""
        with _patched_hotjob_client(post_routes=self._routes("厦门新能安（XMC）")):
            r = dd.hotjob_probe("ampace", "新能安")
        self.assertIsNotNone(r)
        self.assertEqual(r["platform"], "wecruit")
        self.assertTrue(r["verified"])
        self.assertEqual(r["sample_companies"], ["厦门新能安（XMC）"])

    def test_verified_false_when_self_reported_company_is_a_different_tenant(self):
        """反例（原洞的实况）：同一个 suiteKey 被另一个目标猜中——自报 company 不含
        「安脉时代」核心词 → verified=False，且带上不匹配的自报公司名方便人工复核。"""
        with _patched_hotjob_client(post_routes=self._routes("厦门新能安（XMC）")):
            r = dd.hotjob_probe("ampace", "安脉时代智能制造(宁德)")
        self.assertIsNotNone(r)
        self.assertFalse(r["verified"])
        self.assertIn("厦门新能安（XMC）", r["note"])

    def test_bracketed_english_name_does_not_break_matching(self):
        """自报名带括号英文名（如「宁德时代 (CATL)」）不应干扰核心词核验——
        核对的是中文核心词子串，英文缩写括号只是噪音，不参与匹配也不应导致误判。"""
        with _patched_hotjob_client(post_routes=self._routes("宁德时代 (CATL)")):
            r = dd.hotjob_probe("ampace", "宁德时代")
        self.assertTrue(r["verified"])
        with _patched_hotjob_client(post_routes=self._routes("宁德时代 (CATL)")):
            r2 = dd.hotjob_probe("ampace", "国轩高科")
        self.assertFalse(r2["verified"])


class HotjobWtBranchCompanyVerifyTest(unittest.TestCase):
    """hotjob_probe 的 wt 分支（getSLD 命中但落到老版 wt 链路）：wt 列表 JSON 没有公司字段
    （orgName 是内部部门名），核验只能靠落地页 <title>。"""

    def _routes(self, brand, portal_title, job_count=1):
        host = f"{brand}.hotjob.cn"
        origin = f"https://{host}"

        def _list_dispatch(**kwargs):
            rt = (kwargs.get("params") or {}).get("recruitType")
            if rt == 2:
                return _FakeJsonOrHtmlResp(json_payload={
                    "postList": [{"postId": "1", "postName": "某岗位"}], "rowCount": job_count})
            return _FakeJsonOrHtmlResp(json_payload={"postList": [], "rowCount": 0})

        post_routes = {
            f"{origin}/wecruit/common/getSLD": _FakeJsonOrHtmlResp(json_payload={
                "data": {"linkData": {"link": f"{origin}/wt/{brand}/web/index",
                                       "title": portal_title}},
                "state": "200", "type": "success"}),
        }
        get_routes = {
            f"{origin}/wt/{brand}/web/json/position/list": _list_dispatch,
            f"{origin}/wt/{brand}/web/index": _FakeJsonOrHtmlResp(text=f"<title>{portal_title}</title>"),
        }
        return get_routes, post_routes

    def test_verified_true_when_portal_title_matches(self):
        get_routes, post_routes = self._routes("yili", "伊利招聘官网")
        with _patched_hotjob_client(get_routes, post_routes):
            r = dd.hotjob_probe("yili", "伊利")
        self.assertEqual(r["platform"], "wt")
        self.assertTrue(r["verified"])
        self.assertEqual(r["portal_title"], "伊利招聘官网")

    def test_verified_false_when_portal_title_is_another_company(self):
        get_routes, post_routes = self._routes("yili", "伊利招聘官网")
        with _patched_hotjob_client(get_routes, post_routes):
            r = dd.hotjob_probe("yili", "蒙牛")
        self.assertFalse(r["verified"])
        self.assertIn("伊利招聘官网", r["note"])


class WtPortalTitleFallbackTest(unittest.TestCase):
    """部分 wt 租户 <title> 是模板默认值（如「首页」），不含公司名——但正文里公司名反复出现
    （live 实测兴业证券即此状态：title=「首页」，正文「兴业证券」出现 12 次）。verified 必须
    退回扫整页正文，不能只看 title 标签，否则这类租户会被误判成「张冠李戴」。"""

    def _routes(self, brand, generic_title, body_company_mentions, job_count=1):
        host = f"{brand}.hotjob.cn"
        origin = f"https://{host}"

        def _list_dispatch(**kwargs):
            if (kwargs.get("params") or {}).get("recruitType") == 2:
                return _FakeJsonOrHtmlResp(json_payload={
                    "postList": [{"postId": "1", "postName": "某岗位"}], "rowCount": job_count})
            return _FakeJsonOrHtmlResp(json_payload={"postList": [], "rowCount": 0})

        body = (f"<title>{generic_title}</title>"
                + "".join(f"<img alt='{body_company_mentions}招聘'/>" for _ in range(3)))
        get_routes = {
            f"{origin}/wt/{brand}/web/json/position/list": _list_dispatch,
            f"{origin}/wt/{brand}/web/index": _FakeJsonOrHtmlResp(text=body),
        }
        return get_routes

    def test_generic_title_falls_back_to_body_text_match(self):
        with _patched_hotjob_client(get_routes=self._routes("xyzq", "首页", "兴业证券")):
            r = dd.wt_probe("xyzq", "兴业证券")
        self.assertIsNotNone(r)
        self.assertTrue(r["verified"])
        self.assertEqual(r["portal_title"], "首页")  # title 本身仍是原样记录，供人工复核

    def test_generic_title_and_unrelated_body_still_rejected(self):
        with _patched_hotjob_client(get_routes=self._routes("xyzq", "首页", "兴业证券")):
            r = dd.wt_probe("xyzq", "国泰君安")
        self.assertFalse(r["verified"])


class WtProbeCompanyVerifyTest(unittest.TestCase):
    """标准版 wt_probe（getSLD 未命中、直连 list API 兜底）：同样必须核验落地页 title，
    此前 verified 恒为 True，是与 hotjob_probe wt 分支相同的一个洞。"""

    def _routes(self, brand, portal_title, job_count=1):
        host = f"{brand}.hotjob.cn"
        origin = f"https://{host}"

        def _list_dispatch(**kwargs):
            params = kwargs.get("params") or {}
            if params.get("recruitType") == 2:
                return _FakeJsonOrHtmlResp(json_payload={
                    "postList": [{"postId": "1", "postName": "某岗位"}], "rowCount": job_count})
            return _FakeJsonOrHtmlResp(json_payload={"postList": [], "rowCount": 0})

        get_routes = {
            f"{origin}/wt/{brand}/web/json/position/list": _list_dispatch,
            f"{origin}/wt/{brand}/web/index": _FakeJsonOrHtmlResp(text=f"<title>{portal_title}</title>"),
        }
        return get_routes

    def test_verified_true_when_portal_title_matches_target(self):
        with _patched_hotjob_client(get_routes=self._routes("yili", "伊利招聘官网")):
            r = dd.wt_probe("yili", "伊利")
        self.assertIsNotNone(r)
        self.assertTrue(r["verified"])

    def test_verified_false_when_portal_title_is_a_different_company(self):
        """猜的 brand 命中了别家真实租户（同一类张冠李戴）→ verified=False，不再无条件放行。"""
        with _patched_hotjob_client(get_routes=self._routes("yili", "伊利招聘官网")):
            r = dd.wt_probe("yili", "蒙牛")
        self.assertIsNotNone(r)
        self.assertFalse(r["verified"])
        self.assertIn("伊利招聘官网", r["note"])


def _feishu_home(title="", tenant="", keywords="", description=""):
    """飞书门户首页的最小形状（取自真实页面：<title> 可以没有，租户名在内嵌 JSON 里）。"""
    head = f"<title>{title}</title>" if title else ""
    return (f'<!doctype html><html><head>{head}'
            f'<meta name="description" content="{description}">'
            f'<meta name="keywords" content="{keywords}"></head><body><script>'
            f'window.__DATA__={{"tenant_name":"{tenant}","website_info":{{"id":"1","path":"society"}}}}'
            f'</script></body></html>')


def _feishu_routes(home_html, job_titles):
    posts = {"data": {"job_post_list": [{"id": str(i), "title": t} for i, t in enumerate(job_titles)]}}
    return ({"https://bytedance.jobs.feishu.cn/": _FakeJsonOrHtmlResp(text=home_html)},
            {"https://bytedance.jobs.feishu.cn/api/v1/search/job/posts": _FakeJsonOrHtmlResp(json_payload=posts)})


class FeishuProbeIdentityTest(unittest.TestCase):
    """飞书门户的公司名只认门户自报（<title> / 租户名 / keywords），不认岗位标题和宣传语。

    2026-10-11 实录：候选「抖音」+ slug bytedance 探到字节跳动的门户。门户首页没有 <title>，旧判据退到
    「岗位标题含公司名」——字节的岗位标题带业务线名（「…-抖音生活服务」），于是放行，字节跳动的 8,351 个在招岗
    挂成「抖音」入库。全部 137 条飞书源对拍：只认门户自报后被挡掉的只有这一条。"""

    BYTEDANCE_HOME = _feishu_home(
        tenant="ByteDance",
        keywords="字节跳动招聘官网、字节跳动招聘、字节跳动社招",
        description="字节跳动在全球推出了多款有影响力的产品，包括今日头条、抖音、西瓜视频、飞书等。")
    BYTEDANCE_JOBS = ["良率工程师（存算与AI） - 芯片研发", "独立端变现产品经理-抖音生活服务", "区域运营-抖音生活服务"]

    def _probe(self, cn, home=None, jobs=None):
        get_routes, post_routes = _feishu_routes(home or self.BYTEDANCE_HOME, jobs or self.BYTEDANCE_JOBS)
        with _patched_hotjob_client(get_routes=get_routes, post_routes=post_routes):
            return dd.feishu_probe("bytedance", cn)

    def test_product_name_in_job_titles_does_not_verify(self):
        r = self._probe("抖音")
        self.assertEqual(r["count"], 3)
        self.assertFalse(r["verified"])
        self.assertIn("ByteDance", r["note"])

    def test_product_name_in_description_does_not_verify(self):
        """宣传语会点名旗下产品；岗位标题不含产品名时也不许靠它放行。"""
        r = self._probe("西瓜视频", jobs=["财务控制治理专家（上海）"])
        self.assertFalse(r["verified"])

    def test_keywords_verify_the_tenant_itself(self):
        """租户名是英文（ByteDance）、<title> 没有时，keywords 里的中文自报名算数。"""
        self.assertTrue(self._probe("字节跳动")["verified"])

    def test_tenant_name_verifies_when_title_is_a_slogan(self):
        home = _feishu_home(title="一起做教育的梦想家和冒险家", tenant="洋葱学园", keywords="")
        self.assertTrue(self._probe("洋葱学园", home=home, jobs=["测试开发工程师（智课）"])["verified"])

    def test_portal_title_still_verifies(self):
        home = _feishu_home(title="加入蔚来", tenant="NIO", keywords="")
        self.assertTrue(self._probe("蔚来", home=home, jobs=["电池工程师"])["verified"])

    def test_unverified_hit_never_becomes_an_insert(self):
        r = self._probe("抖音")
        self.assertEqual(dd.to_passed([{**r, "company": "抖音", "industry": ""}]), [])


if __name__ == "__main__":
    unittest.main()
