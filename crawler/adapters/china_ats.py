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


class BeisenAdapter(ChinaSpaAdapter):
    """北森招聘（*.zhiye.com / *.italent.cn / 自有 careers 域名，由北森承载）。

    source_url 填某公司北森招聘页（如 https://chinalife.zhiye.com/custom/intern）。
    北森列表接口 GetJobAdPageList 不含 per-job URL；详情页为北森标准路由
    `{origin}{portal_prefix}/zwxq?jobAdId={Id}`（zwxq=职位详情，Id 为岗位 UUID）。
    已 live 验证（chinalife）：构造 URL 渲染对应岗位且 job-specific（A 在、B 不在）。
    portal_prefix 由列表页路径去掉最后一段（section）推导，覆盖 /custom/intern、/summer 等门户形态。
    """

    name = "beisen"
    intercept_matches = ("GetJobAdPageList", "JobAd", "Position", "position", "Recruit", "recruit", "/api/")
    detail_template = ""  # 用 _resolve_url 动态构造北森标准详情路由（见下）

    def _resolve_url(self, post: dict, job_id: str) -> str:
        # 1) 接口若直接给了 per-job 链接，仍优先用（最可靠）。
        raw = super()._resolve_url(post, job_id)
        if raw:
            return raw
        # 2) 北森标准详情路由：{origin}{portal_prefix}/zwxq?jobAdId={UUID}。优先用 Id（UUID）。
        uuid = _first_str(post, ("Id", "id", "jobAdId", "JobAdId"))
        if not uuid:
            return ""
        origin = getattr(self, "_origin", "")
        prefix = getattr(self, "_portal_prefix", "")
        return f"{origin}{prefix}/zwxq?jobAdId={uuid}"


class CompanySpaAdapter(ChinaSpaAdapter):
    """通用企业官网 SPA 招聘站（各公司自建站）。

    拦截站点自身**所有 JSON** 接口，启发式抽取岗位；仅放行接口里带**真实 per-job 链接**的行，
    绝不拼/猜 URL。覆盖「各公司站」长尾，加源零代码（填公司名 + 招聘页地址 + adapter=company_spa）。
    """

    name = "company_spa"
    intercept_matches = ()  # 拦截所有 JSON
    detail_template = ""    # 不拼链接，只用接口里的真实 URL
