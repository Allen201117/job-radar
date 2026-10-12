"""audit_hotjob_attribution 的契约：名字核验双向、渠道后缀与拉丁名不干扰、接口失败记 unknown 不判错。"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from audit_hotjob_attribution import (cjk_name, names_agree, audit, audit_wt, wt_identity, wt_key,
                                          wt_verdict, audit_feishu, feishu_identity, feishu_verdict)
except ModuleNotFoundError:
    from crawler.audit_hotjob_attribution import (cjk_name, names_agree, audit, audit_wt, wt_identity,
                                                  wt_key, wt_verdict, audit_feishu, feishu_identity,
                                                  feishu_verdict)


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

    def test_latin_only_name_and_place_prefix_and_keywords(self):
        self.assertTrue(names_agree("TCL 实习", ["TCL集团"]))
        self.assertTrue(names_agree("苏州凌志软件 校招", ["苏州工业园区凌志软件股份有限公司"]))
        self.assertTrue(names_agree("上海瑞金医院 Ruijin Hospital", ["上海交通大学医学院附属瑞金医院"]))
        # 品牌门户的 companyName 是母公司，keywords / 组织树才写品牌
        self.assertTrue(names_agree("一汽-大众汽车有限公司",
                                    ["中国第一汽车股份有限公司", "一汽大众招聘官网，一汽大众校招", "一汽-大众"]))
        self.assertFalse(names_agree("领益智造 Lingyi", ["特变电工股份有限公司", "特变电工招聘官网", "沈变公司"]))

    def test_industry_word_or_place_prefix_alone_is_not_agreement(self):
        # 2026-10-10 前这四组都判成「对得上」：剥地名剩两字行业词（银行 / 证券）、「地名 + 1 个字」的三字头（中国石 / 中国电）
        self.assertFalse(names_agree("中国银行", ["华夏银行招聘官网"]))
        self.assertFalse(names_agree("上海证券", ["财通证券"]))
        self.assertFalse(names_agree("中国石油", ["中国石化招聘"]))
        self.assertFalse(names_agree("中国电信", ["中国电建招聘官网"]))
        # 门户文本的前 3 个字是行业词，不能拿去库名里找
        self.assertFalse(names_agree("协鑫新能源", ["新能源汽车招聘官网"]))
        # 收紧后该对上的照样对上
        self.assertTrue(names_agree("中国银行", ["中国银行股份有限公司"]))
        self.assertTrue(names_agree("中国电信", ["中国电信招聘"]))
        self.assertTrue(names_agree("新疆特变电工集团", ["特变电工股份有限公司"]))        # 反向靠去后缀的全名，不靠三字头
        self.assertTrue(names_agree("格科微电子（上海）有限公司", ["格科微招聘"]))          # 库名这一侧的三字头照用


class AuditTest(unittest.TestCase):
    def test_audit_buckets_and_caches_per_tenant(self):
        rows = [
            {"company": "领益智造 Lingyi", "source_url": "https://wecruit.hotjob.cn/SU1/pb/social.html"},
            {"company": "领益智造 Lingyi 校招", "source_url": "https://wecruit.hotjob.cn/SU1/pb/school.html"},
            {"company": "华夏银行", "source_url": "https://hxb.hotjob.cn/SU2/pb/social.html"},
            {"company": "某某", "source_url": "https://x.hotjob.cn/SU3/pb/social.html"},
        ]
        answers = {"SU1": {"data": {"companyName": "特变电工股份有限公司", "keywords": "特变电工招聘",
                                    "suitOrgInfoPOs": [{"orgName": "沈变公司"}]}},
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


class _Resp:
    def __init__(self, url="", text="", payload=None, status_code=200):
        self.url, self.text, self._payload, self.status_code = url, text, payload, status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _WtClient:
    """假的 wt 站：pages = {首页地址: (最终地址, html)}，lists = {origin+brand: [orgName…]}，configs = {suiteKey: data}。"""

    def __init__(self, pages=None, lists=None, configs=None):
        self.pages, self.lists, self.configs = pages or {}, lists or {}, configs or {}
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append(url)
        if url.endswith("/web/json/position/list"):
            orgs = self.lists.get(url)
            if orgs is None:
                return _Resp(url)   # 非 JSON
            return _Resp(url, payload={"postList": [{"orgName": o} for o in orgs] if params["recruitType"] == 2 else []})
        if url not in self.pages:
            raise RuntimeError("boom")
        final, html, *status = self.pages[url]
        return _Resp(final, html, status_code=status[0] if status else 200)

    def post(self, url, headers=None):
        self.calls.append(url)
        return _Resp(url, payload={"data": self.configs.get(url.rsplit("/", 1)[-1], {})})


def _wt(host, brand):
    return (f"https://{host}/wt/{brand}/web/index", f"https://{host}/wt/{brand}/web/json/position/list")


class WtVerdictTest(unittest.TestCase):
    """用例全部取自 2026-10-10 对 40 个 enabled wt 源的 live 普查。"""

    def test_portal_declares_another_company(self):
        # 迁移 105：BRAND=CT 被猜成中国电信，首页跳到的门户自报财通证券
        self.assertEqual(wt_verdict("中国电信", ["财通证券", "财通证券社会招聘,财通证券校园招聘"],
                                    ["财通证券", "分支机构"]), "mismatch")
        # BRAND=JKS 被猜成晶科能源，落地页 title 与发布机构都是金科服务
        self.assertEqual(wt_verdict("晶科能源控股有限公司", ["金科服务招聘"], ["金科服务"]), "mismatch")

    def test_org_names_can_confirm_but_never_convict(self):
        # 门户没自报公司名（title 是「首页」），发布机构是城市 / 事业群 / 部门 → 判不了，不是对不上
        self.assertEqual(wt_verdict("中广核", [], ["西安", "长沙", "重庆"]), "undecidable")
        self.assertEqual(wt_verdict("浙江华友钴业", [], ["新能源产业集团", "有色产业集团"]), "undecidable")
        self.assertEqual(wt_verdict("南方基金管理股份有限公司", [], ["权益研究部", "数智科技部"]), "undecidable")
        # 发布机构对得上就算过：首页跳到的新版门户已关闭、拿不到自报名
        self.assertEqual(wt_verdict("国机集团", [], ["国机集团总部", "国机数字科技有限公司"]), "ok")

    def test_title_or_latin_brand_confirms(self):
        self.assertEqual(wt_verdict("伊利", ["伊利招聘官网"], ["总部", "液态奶事业部"]), "ok")
        self.assertEqual(wt_verdict("TCL实业控股", ["TCL招聘"], ["空调事业部", "光伏科技"]), "ok")
        # 两个字母的拉丁词不算品牌词：不能让「CT」这种代号把别家门户放行
        self.assertEqual(wt_verdict("中国电信 CT", ["CT 财通证券招聘"], []), "mismatch")
        # 泛称（Group / Ltd）不算品牌词；品牌词要整词出现，不能是别的词的一截
        self.assertEqual(wt_verdict("ABC Group", ["XYZ Group 招聘"], []), "mismatch")
        self.assertEqual(wt_verdict("某某 ACE", ["SPACE招聘"], []), "mismatch")

    def test_org_names_match_forward_only(self):
        # 发布机构的前 3 个字 / 去后缀名落在库名里不算：「新能源产业集团」对不上「协鑫新能源」
        self.assertEqual(wt_verdict("协鑫新能源", [], ["新能源产业集团"]), "undecidable")
        # 门户自报对不上、发布机构对得上（同集团下的研发公司）→ 过
        self.assertEqual(wt_verdict("现代汽车 HMGC", ["现代投资招聘官网"],
                                    ["现代汽车研发中心（中国）有限公司"]), "ok")

    def test_wt_key(self):
        self.assertEqual(wt_key("https://www.hotjob.cn/wt/CT/web/index"), "www.hotjob.cn/CT")
        self.assertEqual(wt_key("https://www.hotjob.cn/wt/HTSC/mobweb/v8/position/list?operational=x"),
                         "www.hotjob.cn/HTSC")
        self.assertIsNone(wt_key("https://wecruit.hotjob.cn/SU1/pb/social.html"))


class WtIdentityTest(unittest.TestCase):
    def test_redirect_to_new_portal_asks_its_suite_config(self):
        index, listing = _wt("www.hotjob.cn", "CT")
        client = _WtClient(
            pages={index: ("https://wecruit.hotjob.cn/SU60/pb/index.html", "<title></title>")},
            lists={listing: ["财通证券", "分支机构", "财通证券"]},
            configs={"SU60": {"companyName": "财通证券", "keywords": "财通证券招聘",
                              "suitOrgInfoPOs": [{"orgName": "财通证券"}]}})
        declared, orgs, notes = wt_identity(index, client)
        self.assertEqual(declared[0], "财通证券")
        self.assertEqual(orgs, ["财通证券", "分支机构"])   # 去重、保序
        self.assertEqual(notes, [])
        self.assertIn("https://wecruit.hotjob.cn/wecruit/suite/config/SU60", client.calls)

    def test_generic_title_is_not_a_declaration_and_failures_are_notes(self):
        index, listing = _wt("cgn.hotjob.cn", "CGN")
        client = _WtClient(pages={index: (index + "/CompCGNPageindex", "<html><title> 首页 </title></html>")},
                           lists={listing: ["西安"]})
        self.assertEqual(wt_identity(index, client), ([], ["西安"], []))
        # 落地页 title 带公司名才算自报；列表不是 JSON 只记一笔原因
        index, _ = _wt("jks.hotjob.cn", "JKS")
        client = _WtClient(pages={index: (index, "<title>金科服务招聘</title>")})
        self.assertEqual(wt_identity(index, client),
                         (["金科服务招聘"], [], ["列表 recruitType=2 ValueError", "列表 recruitType=1 ValueError"]))
        # 去掉「招聘 / 官网 / 校园…」后不剩 2 个字的 title 都不算自报；带公司名的算
        for title, declares in (("校园招聘", False), ("微官网招聘系统", False), ("招聘官网更新提示", False),
                                ("Home", False), ("格科微招聘", True), ("微软招聘", True)):
            client = _WtClient(pages={index: (index, f"<title>{title}</title>")})
            self.assertEqual(bool(wt_identity(index, client)[0]), declares, title)

    def test_error_page_title_is_not_a_declaration(self):
        # 403 / 拦截页的 title 不是门户自报：只记原因，不能让「没打通」变成「对不上」
        index, listing = _wt("jks.hotjob.cn", "JKS")
        client = _WtClient(pages={index: (index, "<title>403 Forbidden</title>", 403)}, lists={listing: ["金科服务"]})
        self.assertEqual(wt_identity(index, client), ([], ["金科服务"], ["首页 HTTP 403"]))
        self.assertEqual(audit_wt([{"company": "晶科能源控股有限公司", "source_url": index}], client)[0], [])
        # 跳到的新版门户已关闭（suite/config 没有 companyName）→ 不当成自报
        index, listing = _wt("sinomach.hotjob.cn", "sinomach")
        client = _WtClient(pages={index: ("https://wecruit.hotjob.cn/SU61/pb/index.html#/", "")},
                           lists={listing: ["国机集团总部"]})
        declared, orgs, notes = wt_identity(index, client)
        self.assertEqual((declared, orgs), ([], ["国机集团总部"]))
        self.assertEqual(len(notes), 1)


class AuditWtTest(unittest.TestCase):
    def test_buckets_cache_and_known_ok(self):
        ct, ct_list = _wt("www.hotjob.cn", "CT")
        cgn, cgn_list = _wt("cgn.hotjob.cn", "CGN")
        yili, yili_list = _wt("yili.hotjob.cn", "yili")
        zl, zl_list = _wt("zhaolian.hotjob.cn", "zhaolian")
        down, _ = _wt("down.hotjob.cn", "DOWN")
        client = _WtClient(
            pages={ct: ("https://wecruit.hotjob.cn/SU60/pb/index.html", ""),
                   cgn: (cgn, "<title>首页</title>"),
                   yili: (yili, "<title>伊利招聘官网</title>"),
                   zl: (zl, "<title>招联金融招聘</title>")},
            lists={ct_list: ["财通证券"], cgn_list: ["西安"], yili_list: ["总部"], zl_list: ["招联金融"]},
            configs={"SU60": {"companyName": "财通证券"}})
        rows = [
            {"company": "中国电信", "source_url": ct},
            {"company": "中广核", "source_url": cgn},
            {"company": "伊利", "source_url": yili},
            {"company": "伊利 校招", "source_url": yili + "/CompyiliPageindex_campus"},
            {"company": "招联消费金融有限公司", "source_url": zl},
            {"company": "某某", "source_url": down},
            {"company": "不是 wt", "source_url": "https://wecruit.hotjob.cn/SU9/pb/social.html"},
        ]
        mismatches, undecidable, unknowns, ok = audit_wt(rows, client)
        self.assertEqual(mismatches, [("中国电信", ct, "财通证券")])
        self.assertEqual([(c, orgs) for c, _, orgs in undecidable], [("中广核", "西安")])
        self.assertEqual([c for c, _, _ in unknowns], ["某某", "不是 wt"])   # 接口全打不通 / 地址形态不对
        self.assertEqual(ok, 3)                                              # 伊利两条 + 招联（人工核过的品牌名）
        self.assertEqual(client.calls.count(yili), 1)                        # 同一门户两条源只问一次


def _feishu_home(title="", tenant="", keywords="", description=""):
    head = f"<title>{title}</title>" if title else ""
    return (f'<html><head>{head}<meta name="description" content="{description}">'
            f'<meta name="keywords" content="{keywords}"></head><body>'
            f'<script>window.__DATA__={{"tenant_name":"{tenant}","use_v2_detail":"true"}}</script></body></html>')


class _FeishuClient:
    """假的飞书门户：pages = {首页地址: (html,) 或 (html, 状态码)}，没登记的地址一律抛错。"""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, params=None, headers=None):
        self.calls.append(url)
        if url not in self.pages:
            raise RuntimeError("boom")
        html, *status = self.pages[url]
        return _Resp(url, html, status_code=status[0] if status else 200)


class FeishuIdentityTest(unittest.TestCase):
    def test_reads_tenant_title_keywords_from_tenant_root_and_never_description(self):
        home = _feishu_home("", "ByteDance", "字节跳动招聘官网、字节跳动招聘、字节跳动社招",
                            "字节跳动在全球推出了多款有影响力的产品，包括今日头条、抖音、西瓜视频、飞书等。")
        client = _FeishuClient({"https://bytedance.jobs.feishu.cn/": (home,)})
        texts, err = feishu_identity("https://bytedance.jobs.feishu.cn/index/position", client)
        self.assertIsNone(err)
        self.assertEqual(texts, ["ByteDance", "字节跳动招聘官网、字节跳动招聘、字节跳动社招"])
        self.assertFalse(any("抖音" in t for t in texts))   # 宣传语里点名的产品不是门户自报的公司名

    def test_error_page_is_unknown_not_a_declaration(self):
        client = _FeishuClient({"https://didatravel.jobs.feishu.cn/": ("Not Found", 404)})
        texts, err = feishu_identity("https://didatravel.jobs.feishu.cn/index/position", client)
        self.assertIsNone(texts)
        self.assertIn("404", err)

    def test_unreachable_host_is_unknown(self):
        texts, err = feishu_identity("https://down.jobs.feishu.cn/index/position", _FeishuClient({}))
        self.assertIsNone(texts)
        self.assertIn("RuntimeError", err)


class FeishuVerdictTest(unittest.TestCase):
    def test_source_name_found_in_portal_self_report_is_ok(self):
        self.assertEqual(feishu_verdict("美图公司", ["美图公司", "加入Pixocial 像素互联"]), "ok")
        self.assertEqual(feishu_verdict("厦门艾德生物医药科技股份有限公司", ["艾德生物", "艾德生物 Careers"]), "ok")

    def test_latin_brand_in_mixed_name_is_ok(self):
        self.assertEqual(feishu_verdict("智元机器人 AGIBot",
                                        ["智元创新（上海）科技股份有限公司", "欢迎加入智元AGIBOT！"]), "ok")

    def test_another_company_is_mismatch(self):
        self.assertEqual(feishu_verdict("容知日新", ["深圳库犸创新科技集团有限公司", "加入深圳库犸科技有限公司"]),
                         "mismatch")
        self.assertEqual(feishu_verdict("千署科技", ["千曙科技", "加入千曙科技"]), "mismatch")

    def test_agreeing_only_by_finding_the_portal_name_inside_ours_is_weak_not_ok(self):
        # 2026-10-11 实锤：租户名只写「英科」，门户标题是「英科再生社会招聘官网」，库里记的是英科医疗 ——
        # 拿门户名去库名里找，两个字的租户名会对上同集团的任何一家。
        self.assertEqual(feishu_verdict("英科医疗", ["英科", "英科再生社会招聘官网", "英科招聘, 加入英科"]), "weak")


class AuditFeishuTest(unittest.TestCase):
    def test_buckets_cache_known_ok_and_undecidable(self):
        pages = {
            "https://mammotion.jobs.feishu.cn/": (_feishu_home("加入深圳库犸科技有限公司", "深圳库犸创新科技集团有限公司"),),
            "https://global-intco.jobs.feishu.cn/": (_feishu_home("英科再生社会招聘官网", "英科"),),
            "https://moonton.jobs.feishu.cn/": (_feishu_home("加入沐瞳科技", "沐瞳科技"),),
            "https://moonton.jobs.feishu.cn/campus/": (_feishu_home("加入沐瞳科技", "沐瞳科技"),),
            "https://zj-innolight.jobs.feishu.cn/": (_feishu_home("加入苏州旭创科技有限公司", "苏州旭创科技有限公司"),),
            "https://toa7dmu9bq.jobs.feishu.cn/": (_feishu_home("欢迎加入电子所", "电子所"),),
            "https://didatravel.jobs.feishu.cn/": ("Not Found", 404),
        }
        client = _FeishuClient(pages)
        rows = [
            {"company": "容知日新", "source_url": "https://mammotion.jobs.feishu.cn/index/position"},
            {"company": "英科医疗", "source_url": "https://global-intco.jobs.feishu.cn/index/position"},
            {"company": "沐瞳科技", "source_url": "https://moonton.jobs.feishu.cn/index/position"},
            {"company": "沐瞳科技", "source_url": "https://moonton.jobs.feishu.cn/"},
            {"company": "沐瞳科技", "source_url": "https://moonton.jobs.feishu.cn/campus/position"},
            {"company": "中际旭创", "source_url": "https://zj-innolight.jobs.feishu.cn/index/position"},
            {"company": "上海航天电子技术研究所", "source_url": "https://toa7dmu9bq.jobs.feishu.cn/index/position"},
            {"company": "道旅科技 Dida", "source_url": "https://didatravel.jobs.feishu.cn/index/position"},
        ]
        mismatches, weak, undecidable, unknowns, ok = audit_feishu(rows, client)
        self.assertEqual(mismatches, [("容知日新", rows[0]["source_url"], "深圳库犸创新科技集团有限公司")])
        self.assertEqual(weak, [("英科医疗", rows[1]["source_url"], "英科")])
        self.assertEqual([c for c, _, _ in undecidable], ["上海航天电子技术研究所"])
        self.assertEqual([c for c, _, _ in unknowns], ["道旅科技 Dida"])
        self.assertEqual(ok, 4)   # 沐瞳三条 + 中际旭创（人工核过：苏州旭创是它的经营主体）
        self.assertEqual(client.calls.count("https://moonton.jobs.feishu.cn/"), 1)   # 同一个门户首页两条源只取一次
        self.assertEqual(client.calls.count("https://moonton.jobs.feishu.cn/campus/"), 1)   # 子门户源读自己的首页

    def test_shared_tenant_each_source_is_checked_against_its_own_portal(self):
        # 2026-10-12 实锤：英科这个租户挂着两家上市公司的门户。租户首页是英科再生的；英科医疗官网链过去的是
        # /757263（社招）与 /840753（校招），各有各的标题。一律读租户首页时，这两条英科医疗的源只能判成弱对上。
        pages = {
            "https://global-intco.jobs.feishu.cn/": (_feishu_home("英科再生社会招聘官网", "英科"),),
            "https://global-intco.jobs.feishu.cn/757263/": (_feishu_home("英科医疗社会招聘官网", "英科"),),
            "https://global-intco.jobs.feishu.cn/840753/": (_feishu_home("英科医疗校园招聘官网", "英科"),),
        }
        client = _FeishuClient(pages)
        rows = [
            {"company": "英科再生", "source_url": "https://global-intco.jobs.feishu.cn/index/position"},
            {"company": "英科医疗", "source_url": "https://global-intco.jobs.feishu.cn/757263/position"},
            {"company": "英科医疗", "source_url": "https://global-intco.jobs.feishu.cn/840753/position"},
        ]
        mismatches, weak, undecidable, unknowns, ok = audit_feishu(rows, client)
        self.assertEqual((mismatches, weak, undecidable, unknowns, ok), ([], [], [], [], 3))
        self.assertEqual(sorted(client.calls), sorted(pages))
        # 反方向：把名字挂反了照样报出来，不会因为同一个主机上有别的门户对得上就放过。
        swapped = [
            {"company": "英科医疗", "source_url": "https://global-intco.jobs.feishu.cn/index/position"},
            {"company": "英科再生", "source_url": "https://global-intco.jobs.feishu.cn/757263/position"},
        ]
        mismatches, weak, _undecidable, _unknowns, ok = audit_feishu(swapped, _FeishuClient(pages))
        self.assertEqual(ok, 0)
        self.assertEqual(sorted(c for c, _, _ in mismatches + weak), ["英科再生", "英科医疗"])

    def test_sub_portal_page_that_does_not_load_is_unknown_not_judged_by_the_tenant_root(self):
        client = _FeishuClient({
            "https://moonton.jobs.feishu.cn/": (_feishu_home("加入沐瞳科技", "沐瞳科技"),),
            "https://moonton.jobs.feishu.cn/campus/": ("Not Found", 404),
        })
        rows = [{"company": "沐瞳科技", "source_url": "https://moonton.jobs.feishu.cn/campus/position"}]
        _m, _w, _u, unknowns, ok = audit_feishu(rows, client)
        self.assertEqual((ok, [c for c, _, _ in unknowns]), (0, ["沐瞳科技"]))
        self.assertEqual(client.calls, ["https://moonton.jobs.feishu.cn/campus/"])

    def test_known_ok_is_bound_to_the_name_it_was_reviewed_for(self):
        # 白名单按「主机 + 当时核过的源名」生效：源名之后被改成别的，要重新进人眼。
        home = _feishu_home("加入苏州旭创科技有限公司", "苏州旭创科技有限公司")
        client = _FeishuClient({"https://zj-innolight.jobs.feishu.cn/": (home,)})
        rows = [{"company": "某某光电", "source_url": "https://zj-innolight.jobs.feishu.cn/index/position"}]
        mismatches, weak, undecidable, unknowns, ok = audit_feishu(rows, client)
        self.assertEqual([c for c, _, _ in mismatches], ["某某光电"])
        self.assertEqual(ok, 0)

    def test_blank_source_name_on_an_unlisted_host_is_a_mismatch(self):
        home = _feishu_home("加入沐瞳科技", "沐瞳科技")
        client = _FeishuClient({"https://moonton.jobs.feishu.cn/": (home,)})
        rows = [{"company": "", "source_url": "https://moonton.jobs.feishu.cn/index/position"}]
        mismatches, _weak, undecidable, _unknowns, ok = audit_feishu(rows, client)
        self.assertEqual((len(mismatches), undecidable, ok), (1, [], 0))

    def test_home_page_is_requested_in_chinese(self):
        # 入库核名门（discover_domestic._client）带 Accept-Language: zh-CN；周检要读到同一种语言的标题。
        seen = []

        class _Client(_FeishuClient):
            def get(self, url, params=None, headers=None):
                seen.append(headers or {})
                return super().get(url, params=params, headers=headers)

        client = _Client({"https://moonton.jobs.feishu.cn/": (_feishu_home("加入沐瞳科技", "沐瞳科技"),)})
        feishu_identity("https://moonton.jobs.feishu.cn/index/position", client)
        self.assertTrue(seen[0].get("Accept-Language", "").startswith("zh-CN"))

    def test_undecidable_list_is_bound_to_the_name_too(self):
        home = _feishu_home("欢迎加入电子所", "电子所")
        client = _FeishuClient({"https://toa7dmu9bq.jobs.feishu.cn/": (home,)})
        rows = [{"company": "某某电子", "source_url": "https://toa7dmu9bq.jobs.feishu.cn/index/position"}]
        mismatches, _weak, undecidable, _unknowns, _ok = audit_feishu(rows, client)
        self.assertEqual([c for c, _, _ in mismatches], ["某某电子"])
        self.assertEqual(undecidable, [])


class _Query:
    def __init__(self, sb):
        self.sb, self.filters, self.start = sb, {}, 0

    def select(self, *_):
        return self

    def eq(self, col, value):
        self.filters[col] = value
        return self

    def in_(self, col, values):
        self.filters[col] = tuple(values)
        return self

    def like(self, col, pattern):
        self.filters[col] = pattern
        return self

    def order(self, *_):
        return self

    def range(self, start, _end):
        self.start = start
        return self

    def execute(self):
        self.sb.asked.append(dict(self.filters))
        rows = self.sb.rows.get(self.filters["adapter_name"], []) if self.start == 0 else []
        return SimpleNamespace(data=rows)


class _Sb:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def table(self, _name):
        return _Query(self)


class RunLedgerTest(unittest.TestCase):
    def test_run_loads_all_three_families_and_records_their_fields(self):
        M = sys.modules[audit.__module__]
        feishu_family = ("feishu", "nio_feishu", "xiaomi_feishu", "xpeng_feishu", "horizon_feishu")
        sb = _Sb({"hotjob": [{"company": "甲", "source_url": "u1"}, {"company": "丙", "source_url": "u2"}],
                  "wt": [{"company": "中国电信", "source_url": "u3"}],
                  feishu_family: [{"company": "容知日新", "source_url": "u5"}, {"company": "英科医疗", "source_url": "u6"},
                                  {"company": "道旅", "source_url": "u7"}]})
        with patch.object(M.httpx, "Client"), \
             patch.object(M, "audit", return_value=([("甲", "u1", "乙")], [("丙", "u2", "boom")], 0)), \
             patch.object(M, "audit_wt", return_value=([("中国电信", "u3", "财通证券")],
                                                       [("中广核", "u4", "西安")], [], 7)), \
             patch.object(M, "audit_feishu", return_value=([("容知日新", "u5", "深圳库犸")], [("英科医疗", "u6", "英科")],
                                                           [("电子所那条", "u8", "只报简称")], [("道旅", "u7", "首页 HTTP 404")],
                                                           4)), \
             patch.object(M.ops_runs, "record_ops_run") as rec:
            self.assertEqual(M._run(sb, SimpleNamespace(limit=None), started_at=None), 0)
        self.assertEqual(sb.asked, [
            {"adapter_name": "hotjob", "enabled": True, "source_url": "%/pb/%"},
            {"adapter_name": "wt", "enabled": True, "source_url": "%/wt/%"},
            {"adapter_name": feishu_family, "enabled": True}])
        args, _ = rec.call_args
        self.assertEqual(args[1], "audit_hotjob_attribution")
        self.assertEqual(args[2], {"sources": 2, "ok": 0, "mismatch": 1, "unknown": 1,
                                   "wt_sources": 1, "wt_ok": 7, "wt_mismatch": 1,
                                   "wt_undecidable": 1, "wt_unknown": 0,
                                   "feishu_sources": 3, "feishu_ok": 4, "feishu_mismatch": 1, "feishu_weak": 1,
                                   "feishu_undecidable": 1, "feishu_unknown": 1})
        self.assertEqual(args[3], "partial")   # 6 条源里 2 条没答复；「判不了」「弱对上」都不算失败


if __name__ == "__main__":
    unittest.main()
