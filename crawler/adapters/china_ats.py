"""
中国本土 ATS / 企业官网招聘站通用浏览器适配器（Tier-2，SPA 拦截）。

覆盖三大类「各行各业公司」来源，一套代码 + 一行 sources 记录即可扩源：
  - moka     : Moka（{tenant}.mokahr.com / app.mokahr.com）—— 大量消费/互联网/制造公司在用
  - beisen   : 北森（*.zhiye.com / *.italent.cn / careers.*）—— 大型国企/集团在用
  - company_spa : 通用企业官网 SPA —— 仅放行站点自有接口里**带真实 per-job URL** 的岗位

合规与质量（遵守 CLAUDE.md 数据质量优先级）：
  - 只加载官方公开招聘页，拦截站点**自己**发起的岗位列表接口响应；不破签名、不调私有接口、低频。
  - jd_url 优先用接口返回的**真实 per-job 链接**；仅 moka/beisen 这类已知 URL 形态才用模板兜底拼。
  - company_spa 不猜 URL：post 里没有可用 per-job 链接的行直接丢，由 normalizer 质量门再兜一层。

host / tenant 从每个 source 的 source_url 动态解析，因此**同一 adapter 覆盖任意租户公司**。
playwright 仅在 fetch() 内惰性导入。
"""
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter


def _first_str(post: dict, keys) -> str:
    for k in keys:
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


def _city_of(post: dict) -> str:
    for k in ("cityName", "city", "workCity", "location", "workPlace", "address",
              "city_name", "work_city", "locationName", "LocNames", "LocName", "Location"):
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            name = v.get("name") or v.get("cityName") or v.get("text")
            if isinstance(name, str) and name.strip():
                return name.strip()
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                name = first.get("name") or first.get("cityName")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return ""


class ChinaSpaAdapter(PlaywrightAdapter):
    """中国本土 SPA 招聘站通用基类：从 source_url 动态解析 host，启发式抽取岗位字段。"""

    # 子类可设详情链接模板（含 {host} {id}）；为空表示「只接受接口里的真实 URL，不拼模板」。
    detail_template: str = ""
    company_name = ""  # 由 sources.company 兜底填充

    def fetch(self, source_url: str) -> str:
        # 记录本次源的 origin / host / 门户前缀，供 _map 拼接相对链接与详情路由。
        parsed = urlparse(source_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        # 门户前缀 = 列表页路径去掉最后一段（section）。北森详情路由 = {origin}{prefix}/zwxq?jobAdId=
        segs = [s for s in (parsed.path or "").split("/") if s]
        self._portal_prefix = ("/" + "/".join(segs[:-1])) if len(segs) > 1 else ""
        if not self.list_urls:
            self.list_urls = [source_url]
        return super().fetch(source_url)

    def _resolve_url(self, post: dict, job_id: str) -> str:
        # 1) 接口里直接给的 per-job 链接（最可靠）
        raw = _first_str(post, ("detailUrl", "jobUrl", "positionUrl", "url",
                                "link", "href", "applyUrl", "detail_url", "job_url"))
        if raw:
            if raw.startswith("http"):
                return raw
            return urljoin(getattr(self, "_origin", "") + "/", raw.lstrip("/"))
        # 2) 已知 ATS 形态才用模板兜底（company_spa 不设模板 → 返回空 → 丢弃）
        if self.detail_template and job_id:
            return self.detail_template.format(host=getattr(self, "_host", ""), id=job_id)
        return ""

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        job_id = _first_str(post, ("id", "jobId", "positionId", "code", "postId",
                                   "job_id", "position_id", "uuid", "Id", "JobAdId"))
        title = _first_str(post, ("title", "name", "jobTitle", "positionName",
                                  "job_title", "position_name", "jobName", "JobAdName"))
        if not title:
            return None
        jd_url = self._resolve_url(post, job_id)
        if not jd_url:
            return None

        summary = _first_str(post, ("description", "jobDescription", "responsibility",
                                    "requirement", "duty", "jobDesc", "content",
                                    "job_description")) or None
        job_type = _first_str(post, ("jobType", "recruitType", "categoryName",
                                     "positionType", "type")) or None
        return RawJob(
            company=self.company_name or "",
            title=title,
            location=_city_of(post) or None,
            job_type=job_type,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )


class MokaAdapter(ChinaSpaAdapter):
    """Moka 招聘（{tenant}.mokahr.com / app.mokahr.com）。

    source_url 填某公司 Moka 公开招聘页（社招/校招列表页）。拦截 mokahr.com 下的 JSON 接口，
    岗位详情优先用接口返回链接；否则按 Moka 常见形态 /jobs/{id} 兜底（需 live 探活确认）。
    """

    name = "moka"
    intercept_matches = ("mokahr.com",)
    detail_template = "https://{host}/jobs/{id}"


# 北森详情路由按租户缓存（host → 详情页 base，如 https://chinalife.zhiye.com/custom/zwxq）。
# 启动时从 crawler/beisen_routes.json 预载（onboarding/probe 探测后落盘提交）→ 每日爬取直接读，不再现场探测。
# 未命中缓存的 host 才现场 render-verify 探测一次（慢，仅新源），结果写回内存缓存。
import json as _json
import os as _os

_BEISEN_ROUTES_FILE = _os.path.join(_os.path.dirname(__file__), "..", "beisen_routes.json")


def _load_beisen_routes() -> dict:
    try:
        with open(_BEISEN_ROUTES_FILE, encoding="utf-8") as f:
            return {k: v for k, v in _json.load(f).items()}
    except (OSError, ValueError):
        return {}


_BEISEN_ROUTE_CACHE: dict = _load_beisen_routes()
# 北森详情页常见路由名（zwxq=职位详情拼音；不同租户配置不同：chinalife=zwxq、横店/杰瑞=detail…）
_BEISEN_DETAIL_NAMES = ("zwxq", "detail", "jobdetail", "positiondetail", "jobDetail")


class BeisenAdapter(ChinaSpaAdapter):
    """北森招聘（*.zhiye.com / *.italent.cn / 自有 careers 域名，由北森承载）。

    source_url 填某公司北森招聘页（如 https://chinalife.zhiye.com/custom/intern）。
    北森列表接口 GetJobAdPageList 不含 per-job URL；详情页 query 恒为 `?jobAdId={Id}`，但 **path 因租户而异**
    （chinalife=/custom/zwxq、横店=/campus/detail…）。因此 fetch 时**逐租户自动探测**详情路由：
    用首个岗位 render-verify 候选 path（替换末段 / 追加 × 常见详情页名），命中「渲染该岗且 job-specific」
    者即为真路由，按 host 缓存。探不到则不拼 URL（丢弃，杜绝坏链）。
    """

    name = "beisen"
    intercept_matches = ("GetJobAdPageList", "JobAd", "Position", "position", "Recruit", "recruit", "/api/")
    detail_template = ""

    def fetch(self, source_url: str) -> str:
        list_json = super().fetch(source_url)  # 浏览器①：拦截 GetJobAdPageList 等列表接口
        self._detail_base = _BEISEN_ROUTE_CACHE.get(self._host)
        if self._detail_base is None and self._host not in _BEISEN_ROUTE_CACHE:
            self._detail_base = self._discover_detail_route(source_url, list_json)
            _BEISEN_ROUTE_CACHE[self._host] = self._detail_base  # 命中或 None 都缓存，避免重复探测
        return list_json

    def _discover_detail_route(self, source_url: str, list_json: str):
        """用首个岗位 render-verify 候选详情 path，返回命中的完整 detail base（origin+path，无 query）或 None。"""
        try:
            data = __import__("json").loads(list_json)
        except (ValueError, TypeError):
            return None
        posts = []
        for resp in data.get("_intercepted", []) or []:
            posts.extend(pp for pp in self._extract_posts(resp) if isinstance(pp, dict))
        jobs = [(_first_str(p, ("Id", "id", "jobAdId", "JobAdId")),
                 _first_str(p, ("JobAdName", "title", "name", "jobTitle"))) for p in posts]
        jobs = [(i, n) for i, n in jobs if i and n]
        if not jobs:
            return None
        a_id, a_name = jobs[0]
        b_name = next((n for i, n in jobs[1:] if n and n != a_name), None)

        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        segs = [s for s in (parsed.path or "").split("/") if s]
        bases = []
        if segs:
            bases.append("/" + "/".join(segs[:-1]))  # 替换末段（chinalife /custom/intern → /custom）
        bases.append("/" + "/".join(segs))            # 追加（横店 /campus/jobs → /campus/jobs?... 否则 /campus/detail）
        # 去重 + 生成候选 path
        seen, cand_paths = set(), []
        for base in bases:
            for nm in _BEISEN_DETAIL_NAMES:
                path = (base.rstrip("/") + "/" + nm) if base.strip("/") else "/" + nm
                if path not in seen:
                    seen.add(path)
                    cand_paths.append(path)

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(
                user_agent=PlaywrightAdapter.user_agent, locale="zh-CN").new_page()
            try:
                for path in cand_paths:
                    url = f"{origin}{path}?jobAdId={a_id}"
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=12000)
                        page.wait_for_timeout(2500)
                        content = page.content()
                        if a_name in content and not (b_name and b_name in content):
                            return f"{origin}{path}"  # 真详情路由（渲染该岗且 job-specific）
                    except Exception:
                        continue
            finally:
                browser.close()
        return None

    def _resolve_url(self, post: dict, job_id: str) -> str:
        # 1) 接口若直接给了 per-job 链接，优先用（最可靠）。
        raw = super()._resolve_url(post, job_id)
        if raw:
            return raw
        # 2) 用本租户探测到的详情路由：{detail_base}?jobAdId={UUID}。探不到则不拼（丢弃）。
        detail_base = getattr(self, "_detail_base", None)
        uuid = _first_str(post, ("Id", "id", "jobAdId", "JobAdId"))
        if not detail_base or not uuid:
            return ""
        return f"{detail_base}?jobAdId={uuid}"


class CompanySpaAdapter(ChinaSpaAdapter):
    """通用企业官网 SPA 招聘站（各公司自建站）。

    拦截站点自身**所有 JSON** 接口，启发式抽取岗位；仅放行接口里带**真实 per-job 链接**的行，
    绝不拼/猜 URL。覆盖「各公司站」长尾，加源零代码（填公司名 + 招聘页地址 + adapter=company_spa）。
    """

    name = "company_spa"
    intercept_matches = ()  # 拦截所有 JSON
    detail_template = ""    # 不拼链接，只用接口里的真实 URL
