"""老版 WinTalent（wt）招聘站通用适配器（直连公开 position/list JSON 接口，零浏览器）。

矿脉：一批知名大企业仍用 hotjob.cn 的**老版 wt**（区别于已攻克的新版 wecruit）：
伊利(yili) / 中信证券(SEC) / 中广核(CGN) / 中国电信(CT) / 中化(Sinochem) / 现代汽车(HMGC) 等。
入口形如 `{host}.hotjob.cn/wt/{BRAND}/web/index`（302→`CompXXXPageindex` 落地页）。

可行性已 live 验证（两道闸门均过）：
  闸门①（列表 XHR）：wt 列表页 JS 公开 GET `{origin}/wt/{BRAND}/web/json/position/list`
    （query: brandCode=1 + recruitType + page），**无需 operational 签名**即返回明文 JSON：
    {"postList":[{postId, postName, workPlace, postType, workingTreatment, endDate,
     publishDate(Time), workYears, education, serviceCondition, workContent, recruitNum, orgName}],
     "rowCount":N, "pageCount":M, "rowSize":10}。服务端 rowSize 硬封顶 10/页，靠 page 翻页收齐。
  闸门②（★决定性 — 逐岗 jd_url 稳定）：详情走移动版稳定页
    `{origin}/wt/{BRAND}/mobweb/position/detail?brandCode=1&safe=Y&recruitType={rt}&postIdsAry={postId}`，
    **去掉 operational 签名、仅 postId + recruitType** 即渲染出**该岗位本身**（live 实测：
    yili 514713→"总部人力资源部HR数据分析专业经理"、522468→"酸奶苏皖…人力资源专员"，互不串页；
    HMGC 172801→"中英翻译"；无效 postId 仅回 ~1.8KB 关闭页不入坏链）。→ 过质量门，可入库。

recruitType 为 wt 平台常量（非每公司配置）：校招/campus=1 / 社招/social=2 / 实习/intern=12，
与详情页 recruitType 一致；逐 recruitType 抓取并合并，三桶归类交后置过滤 + 前端 recruitmentCategory。
company 由 sources.company 兜底（BRAND 仅用于路由，不当公司名，杜绝张冠李戴）。

直连 httpx（无头浏览器非必需），返回 PlaywrightAdapter.parse 可消费的 _intercepted 信封。
"""
import json
from typing import List, Optional
from urllib.parse import urlparse

import httpx

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


class WtAdapter(PlaywrightAdapter):
    """老版 WinTalent（wt）招聘站。source_url 填某公司 wt 入口（如
    https://yili.hotjob.cn/wt/yili/web/index 或其 …/CompyiliPageindex_social）。"""

    name = "wt"
    company_name = ""  # 由 sources.company 兜底，绝不用 BRAND 当公司名

    _LIST_PATH = "/wt/{brand}/web/json/position/list"
    # 稳定详情页（移动版，postId-only，无 operational 签名）——闸门②已 live 验证可逐岗直达。
    _DETAIL_TPL = ("{origin}/wt/{brand}/mobweb/position/detail"
                   "?brandCode=1&safe=Y&recruitType={rt}&postIdsAry={pid}")
    # recruitType 平台常量：校招=1 / 社招=2 / 实习=12（与详情页 recruitType 同口径）。
    _RECRUIT_TYPES = (2, 1, 12)
    _PAGE_CAP = 60       # 每 recruitType 最多翻页数（10/页 → 封顶 600 岗/类，足够覆盖最大租户）
    _MAX_JOBS = 1200     # 单租户总上限（防超大央企一次拉爆库）

    def _bind_source(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        parts = [p for p in (parsed.path or "").split("/") if p]
        # 路径形如 /wt/{BRAND}/web/index[/CompXXXPageindex_social]；BRAND = 第 2 段。
        if len(parts) < 2 or parts[0].lower() != "wt":
            raise RuntimeError(f"wt: bad source_url (expect /wt/{{BRAND}}/...): {source_url}")
        self._brand = parts[1]
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        self.official_hosts = (parsed.netloc,)
        # 列表页（用于 Referer，提高接口可达性）
        self._referer = f"{self._origin}/wt/{self._brand}/web/index"
        return self._brand

    def fetch(self, source_url: str) -> str:
        """直连 position/list 接口，逐 recruitType × 翻页拉全量，返回 _intercepted 信封。"""
        self._bind_source(source_url)
        api = f"{self._origin}{self._LIST_PATH.format(brand=self._brand)}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Referer": self._referer,
            "Origin": self._origin,
        }
        collected: List[dict] = []
        total = 0
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for rt in self._RECRUIT_TYPES:
                if total >= self._MAX_JOBS:
                    break
                for page in range(1, self._PAGE_CAP + 1):
                    try:
                        resp = client.get(api, params={
                            "brandCode": 1, "recruitType": rt, "page": page})
                        resp.raise_for_status()
                        payload = resp.json()
                    except (httpx.HTTPError, ValueError):
                        break  # 该 recruitType 接口异常/空 → 跳到下个类型
                    if not isinstance(payload, dict):
                        break
                    rows = payload.get("postList") or []
                    if not rows:
                        break
                    # 标记本批的 recruitType，供 _map 拼稳定详情链（详情页要 recruitType）。
                    for r in rows:
                        if isinstance(r, dict):
                            r["_wtRecruitType"] = rt
                    collected.append(payload)
                    total += len(rows)
                    page_count = payload.get("pageCount") or 0
                    if total >= self._MAX_JOBS or (page_count and page >= page_count):
                        break
                    if len(rows) < (payload.get("rowSize") or 10):
                        break  # 末页不足一页 → 收完
        if not collected:
            # 一条都没拿到 → 多半非 wt 老版 / 接口改版 / 该域被拦；交给 run.py 记 partial（不伪装成功）。
            raise RuntimeError(
                f"wt: empty position/list (brand={self._brand} host={self._host})")
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    # PlaywrightAdapter._extract_posts 的 posts_keys 含 'postList'？没有——这里覆盖 parse 用的提取，
    # 直接在 _map 前由 _extract_posts 命中。posts_keys 未含 postList，故显式加上。
    posts_keys = ("postList",) + PlaywrightAdapter.posts_keys

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        post_id = _first(post, ("postId", "id"))
        title = _first(post, ("postName", "title", "name"))
        if not (post_id and title):
            return None
        rt = post.get("_wtRecruitType") or 2
        jd_url = self._DETAIL_TPL.format(
            origin=self._origin, brand=self._brand, rt=rt, pid=post_id)

        desc = _first(post, ("workContent", "description"))
        req = _first(post, ("serviceCondition", "requirement"))
        summary = (desc + ("\n\n【任职要求】\n" + req if req else "")).strip() or None
        return RawJob(
            company=self.company_name or "",
            title=title,
            location=_first(post, ("workPlace", "workCity", "location")) or None,
            job_type=_first(post, ("postType", "postTypeName")) or None,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=(normalizer.pick_publish_date(post)
                       or normalizer.coerce_iso_date(post.get("publishDateTime"))
                       or normalizer.coerce_iso_date(post.get("publishDate"))),
            education=_first(post, ("education", "educationName")) or None,
            experience=_first(post, ("workYears", "workYearName", "workExperience")) or None,
            deadline=normalizer.coerce_iso_date(post.get("endDate")),
        )
