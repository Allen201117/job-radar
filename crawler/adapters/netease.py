"""网易招聘（hr.163.com）自建门户适配器（直连公开 queryPage JSON 接口，零浏览器）。

网易招聘页 JS 公开 POST `https://hr.163.com/api/hr163/position/queryPage`
（json: currentPage + pageSize）返回明文 JSON（无需登录/签名）：
  {"code":200,"data":{"total":N,"pages":M,"list":[{id, name, firstPostTypeName,
   requirement, description, reqEducationName, reqWorkYearsName,
   workPlaceList:[{name}], updateTime, recruitNum, productName}]}}
逐岗稳定详情页 = `https://hr.163.com/job-detail.html?id={id}`（id-only，过质量门）。
直连 httpx（无头浏览器非必需）。

company 按 productName 派生子公司归属（2026-08-27 加）：hr.163.com 是网易集团**全部产品线
共用的同一个门户**（网易有道旧站 hr.youdao.com 直接 302 到这里），接口逐岗返回 productName。
2026-08-27 live 实测 2582 岗 / 15 个取值（下面条数是当日快照，随在招量天天浮动，只看量级）：
网易游戏（互娱）1240、网易游戏（雷火）540、网易云音乐 161、网易职能 136、网易有道 115、
网易智企 87、网易传媒 71、网易智邮 60、网易伏羲 44、网易严选 43、网易元气 37、其他 32、
星间工作室 8、美泰163 6、烈酷工作室 2。
必投清单把「网易有道」「网易云音乐」当独立公司统计，全部记成「网易」它们就永远算缺口——
可这些岗其实早就在库里。所以把 productName 归一到清单规范名写进 RawJob.company
（normalizer.normalize 的 `raw.company or company` ⇒ 非空即覆盖 sources.company），
归一不出的照旧记「网易」。**不为此新增 source 行**：这批岗与本源抓的是同一份数据，
拆成两条源只会让它们天天抢同一行 upsert 打架。

⚠️ 成立前提（2026-08-27 核实）：清单里「网易」的 pattern 是 `%网易%`，覆盖侧按 ILIKE
语义匹配（lib/ilike-matcher.ts）⇒「网易有道」「网易云音乐」这些派生名**仍然命中**
`%网易%`，派生子公司不会反过来把母公司「网易」变成缺口，不顾此失彼。
_load_product_company_map() 把这条前提编码成运行时守卫：清单一旦把「网易」改成非
「前后带 %」的子串模式，派生就整体自动关闭（全部回落「网易」）——宁可少认几家子公司，
也绝不能把母公司丢了。
"""
import json
import re
from typing import Optional

import httpx

import must_apply
import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter


def _first(post: dict, keys) -> str:
    for k in keys:
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_PARENT_COMPANY = "网易"
# 「网易游戏（互娱）」这类带事业部括号后缀的 productName，去掉后缀再试一次归一。
_BRACKET_SUFFIX = re.compile(r"[（(]")


def _substring_pattern_token(pattern) -> str:
    """`%网易%` → `网易`；不是「前后都带 %、中间无通配符」的纯子串模式一律返回 ""。"""
    text = pattern.strip() if isinstance(pattern, str) else ""
    if len(text) > 2 and text.startswith("%") and text.endswith("%"):
        token = text[1:-1]
        if token and "%" not in token and "_" not in token:
            return token
    return ""


def _load_product_company_map() -> dict:
    """必投清单 → {清单规范名: 清单规范名}，只收「名字含母公司 token」的行。

    只收名字含「网易」的公司有两层作用：
      ① 派生出来的名字必然仍命中母公司 `%网易%`（见文件头前提），母公司不会掉成缺口；
      ② 按「与清单规范名精确相等」而不是子串去匹配 productName，天然避开误撞——
         比如「网易元气」若做子串匹配会撞上清单里的「元气森林」。
    读清单失败 / 母公司不在清单 / 母公司 pattern 不是纯子串模式 → 返回 {}，
    派生整体关闭（fail-safe：全部回落「网易」，绝不因为清单变形而丢覆盖）。
    """
    try:
        grouped = must_apply.by_industry()
    except Exception:  # noqa: BLE001 —— 清单读不到不许拖垮抓取，退化成「全记网易」
        return {}
    rows = [row for companies in grouped.values() for row in companies if isinstance(row, dict)]
    token = ""
    for row in rows:
        if (row.get("name") or "").strip() == _PARENT_COMPANY:
            token = _substring_pattern_token(row.get("pattern"))
            break
    if not token or token not in _PARENT_COMPANY:
        return {}
    return {
        name: name
        for name in ((row.get("name") or "").strip() for row in rows)
        if name and name != _PARENT_COMPANY and token in name
    }


# 模块级只算一次（清单是随仓库走的静态文件）。当前清单实测得到
# {"网易云音乐": "网易云音乐", "网易有道": "网易有道"}。
_PRODUCT_COMPANY_MAP = _load_product_company_map()


def _derive_company(product_name) -> str:
    """productName → 必投清单规范名；归一不出返回 ""（调用方回落「网易」）。"""
    name = product_name.strip() if isinstance(product_name, str) else ""
    if not name:
        return ""
    if name in _PRODUCT_COMPANY_MAP:
        return _PRODUCT_COMPANY_MAP[name]
    # 当前清单里没有「网易游戏」，所以那 ~1780 个游戏岗仍回落「网易」；
    # 清单哪天补上「网易游戏」，这里自动生效，无需改本文件。
    base = _BRACKET_SUFFIX.split(name, 1)[0].strip()
    return _PRODUCT_COMPANY_MAP.get(base, "")


class NeteaseAdapter(PlaywrightAdapter):
    """网易招聘 hr.163.com。source_url 填 `https://hr.163.com/job-list.html`。"""

    name = "netease"
    company_name = "网易"
    official_hosts = ("hr.163.com",)

    _API = "https://hr.163.com/api/hr163/position/queryPage"
    _DETAIL = "https://hr.163.com/job-detail.html?id={id}"
    _PAGE_SIZE = 50
    # 官网实测 ~2510 岗；旧上限 16×50=800 封顶只覆盖 ~33%。提到 70×50=3500 覆盖全量
    # （分页按 page>=pages 自然停，不会真跑满 70 页）。
    _MAX_PAGES = 70
    # _extract_posts 走点路径取 data.list（与 hotjob 的 data.pageForm.pageData 同机制）
    posts_keys = ("data.list",) + PlaywrightAdapter.posts_keys

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Content-Type": "application/json",
            "Referer": "https://hr.163.com/job-list.html",
            "Origin": "https://hr.163.com",
        }
        collected = []
        fetched = 0
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for page in range(1, self._MAX_PAGES + 1):
                try:
                    resp = client.post(self._API, json={"currentPage": page, "pageSize": self._PAGE_SIZE})
                    resp.raise_for_status()
                    payload = resp.json()
                except (httpx.HTTPError, ValueError):
                    break
                data = payload.get("data") or {}
                if self.reported_total is None:
                    total = _int_or_none(data.get("total"))
                    if total is not None:
                        self.reported_total = total
                rows = data.get("list") or []
                if not rows:
                    break
                collected.append(payload)
                fetched += len(rows)
                pages = data.get("pages") or 0
                if pages and page >= pages:
                    break
        if not collected:
            raise RuntimeError("netease: empty queryPage (hr.163.com)")
        self.fetch_complete = (
            self.reported_total is not None and fetched >= self.reported_total
        )
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        jid = _first(post, ("id",))
        title = _first(post, ("name", "title"))
        if not (jid and title):
            return None
        # 工作地点：接口同时返回 workPlaceList（地点 ID 数组，如 [229]）和 workPlaceNameList
        # （中文城市名数组，如 ["杭州市"]，一一对应）。优先取 workPlaceNameList（2026-07-07 实测
        # 该字段存在）；缺失才回退旧逻辑，绝不拿纯 ID 伪造城市（遵守数据质量优先级）。
        loc = None
        wpnl = post.get("workPlaceNameList")
        if isinstance(wpnl, list) and wpnl and isinstance(wpnl[0], str) and wpnl[0].strip():
            loc = wpnl[0].strip()
        if loc is None:
            wpl = post.get("workPlaceList")
            if isinstance(wpl, list) and wpl and isinstance(wpl[0], dict):
                loc = wpl[0].get("name") or wpl[0].get("cityName") or wpl[0].get("placeName")
            elif isinstance(wpl, str) and wpl.strip():
                loc = wpl.strip()
            if loc is not None and not isinstance(loc, str):
                loc = None  # 地点 ID（int）等非字符串 → 不入 location
        desc = _first(post, ("description",))
        req = _first(post, ("requirement",))
        summary = (desc + ("\n\n【任职要求】\n" + req if req else "")).strip() or None
        jd_url = self._DETAIL.format(id=jid)
        return RawJob(
            # 归一不出子公司时保持写死的「网易」（= sources.company，与改造前逐字一致）：
            # discovery.CompanyRefreshRecipe 会拿 raw.company 进关键词/排除词的匹配袋子
            # （job_matches_query / job_excluded），留空会让「排除网易」在刷新链路上失效。
            company=_derive_company(post.get("productName")) or self.company_name,
            title=title,
            location=loc,
            job_type=_first(post, ("firstPostTypeName", "workTypeName")) or None,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.coerce_iso_date(post.get("updateTime")),
            education=_first(post, ("reqEducationName",)) or None,
            experience=_first(post, ("reqWorkYearsName",)) or None,
        )
