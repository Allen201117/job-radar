"""HotJob / wecruit 招聘站通用适配器（直连公开 listPosition 接口，零浏览器）。

典型入口（sources.source_url，{host} 为任意 hotjob.cn 子域）：
  https://{host}/{suiteKey}/pb/social.html    # 社招 society  recruitType=2
  https://{host}/{suiteKey}/pb/school.html    # 校招 campus   recruitType=1
  https://{host}/{suiteKey}/pb/interns.html   # 实习 intern   recruitType=12

页面 JS 公开调用 POST {origin}/wecruit/positionInfo/listPosition/{suiteKey}
（form: recruitType + pageIndex + pageSize），返回 data.pageForm.pageData 岗位列表。
本适配器**直接分页调用该接口**（httpx，无需无头浏览器），岗位详情页为
/{suiteKey}/pb/posDetail.html?postId={postId}&postType={society|campus|intern}。

recruitType 数值映射经各页 JS bundle（social.js / school.js / interns.js）逐一核实，
为 wecruit 平台常量（非每公司配置）：society=2 / campus=1 / intern=12。三渠道是独立入口，
逐家三条 source 分别入库，jd_url 的 postType 决定前端三桶归类（lib/china-keyword-expansion）。

注：bare 域名（如 crrc.hotjob.cn/）是 iframe 落地页，path 里无 suiteKey；真实 suiteKey 需先
POST /wecruit/common/getSLD（sld={host}）解析出 linkData.link 再取，sources 直接登记带 suiteKey 的 pb 页。
"""
import json
from typing import List, Optional
from urllib.parse import urlparse

import httpx

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter


class HotJobAdapter(PlaywrightAdapter):
    name = "hotjob"
    company_name = ""  # 由 sources.company 兜底
    intercept_match = "/wecruit/positionInfo/listPosition/"  # 仅文档用途；fetch 直连不再拦截
    posts_keys = ("data.pageForm.pageData",)

    # 页面文件名 → (详情页 postType, 列表接口 recruitType)。recruitType 由各页 JS bundle 核实。
    _CHANNEL_BY_PAGE = {
        "social.html": ("society", 2),
        "school.html": ("campus", 1),
        "interns.html": ("intern", 12),
    }
    _LIST_API = "/wecruit/positionInfo/listPosition/"
    api_page_size = 20
    api_max_pages = 6  # 每渠道最多翻页数（直连快，但有上限防库膨胀；按 totalPage 提前停）

    def __init__(self):
        self.official_hosts = ()
        self.detail_template = ""
        self.list_urls = []
        self._suite_key = ""
        self._origin = ""
        self._recruit_type = 2

    def _bind_source(self, source_url: str):
        parsed = urlparse(source_url)
        parts = [p for p in (parsed.path or "").split("/") if p]
        suite_key = parts[0] if parts else ""
        if not suite_key:
            raise RuntimeError(f"hotjob: missing suite key in source_url={source_url}")
        self._suite_key = suite_key
        self.official_hosts = (parsed.netloc,)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        self._origin = origin
        page_name = parts[2] if len(parts) > 2 else "social.html"
        post_type, recruit_type = self._CHANNEL_BY_PAGE.get(page_name, ("society", 2))
        self._recruit_type = recruit_type
        self.detail_template = f"{origin}/{suite_key}/pb/posDetail.html?postId={{id}}&postType={post_type}"
        entry = f"{origin}/{suite_key}/pb/{page_name}"
        self.list_urls = [entry]
        return suite_key

    def fetch(self, source_url: str) -> str:
        """直连公开 listPosition 接口逐页拉取（无浏览器），返回 parse() 可消费的 _intercepted 信封。"""
        self._bind_source(source_url)
        api = f"{self._origin}{self._LIST_API}{self._suite_key}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self.list_urls[0],
            "Origin": self._origin,
        }
        collected: List[dict] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for page_index in range(1, self.api_max_pages + 1):
                resp = client.post(api, data={
                    "recruitType": self._recruit_type,
                    "pageIndex": page_index,
                    "pageSize": self.api_page_size,
                })
                resp.raise_for_status()
                payload = resp.json()
                collected.append(payload)
                page_form = (payload.get("data") or {}).get("pageForm") or {}
                rows = page_form.get("pageData") or []
                total_page = page_form.get("totalPage") or 0
                if not rows or page_index >= total_page:
                    break
        if not collected:
            raise RuntimeError(f"hotjob: empty response from listPosition (suiteKey={self._suite_key})")
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        post_id = str(post.get("postId") or post.get("id") or "").strip()
        title = str(post.get("postName") or post.get("title") or "").strip()
        if not (post_id and title):
            return None
        desc = str(post.get("workContent") or post.get("description") or "").strip()
        req = str(post.get("serviceCondition") or post.get("requirement") or "").strip()
        summary = (desc + ("\n\n【任职要求】\n" + req if req else "")).strip() or None
        jd_url = self.detail_template.format(id=post_id)
        return RawJob(
            company=self.company_name or "",
            title=title,
            location=post.get("workPlaceStr") or post.get("workPlace") or None,
            job_type=post.get("postTypeName") or post.get("recruitTypeName") or None,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post) or normalizer.coerce_iso_date(post.get("publishDate")),
            education=post.get("educationName") or post.get("educationStr") or post.get("education") or None,
            experience=post.get("workYearName") or post.get("workExperience") or None,
            deadline=normalizer.coerce_iso_date(post.get("endDate")),
        )
