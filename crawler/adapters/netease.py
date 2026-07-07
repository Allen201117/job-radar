"""网易招聘（hr.163.com）自建门户适配器（直连公开 queryPage JSON 接口，零浏览器）。

网易招聘页 JS 公开 POST `https://hr.163.com/api/hr163/position/queryPage`
（json: currentPage + pageSize）返回明文 JSON（无需登录/签名）：
  {"code":200,"data":{"total":N,"pages":M,"list":[{id, name, firstPostTypeName,
   requirement, description, reqEducationName, reqWorkYearsName,
   workPlaceList:[{name}], updateTime, recruitNum, productName}]}}
逐岗稳定详情页 = `https://hr.163.com/job-detail.html?id={id}`（id-only，过质量门）。
company 恒为「网易」（自建门户，无张冠李戴风险）。直连 httpx（无头浏览器非必需）。
"""
import json
from typing import Optional

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


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
            company=self.company_name,
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
