"""携程集团招聘（careers.ctrip.com）自建门户适配器（直连公开 JSON 接口，零鉴权）。

careers.ctrip.com 公开 POST `https://careers.ctrip.com/api/hrrecruit/getJobAd`
（json 含 condition.category / pager.index / head.language）返回明文 JSON（无需登录/签名）：
  {"retCode":"201","retValue":{"total":N,"recruitJobAdList":[{id, fromId, jobTitle,
   cityName, city, publishDate, requirements, duty, jobFamilyGroupName, buName, kind,
   kindName, category}]}}
category: 1=社招, 2=校招（实习含在 category=1 里 kind 字段区分）
逐岗稳定详情页（id-only fromId，live render-verify 过）：
  社招: https://careers.ctrip.com/#/experienced/job-detail/{fromId}
  校招: https://careers.ctrip.com/#/campus/job-detail/{fromId}
（live render-verify: 社招 MJ035500「服务产品经理」正文渲染通过；
  校招 MJ035383「Accommodation Global Trainee」正文渲染通过，过质量门）
company 恒为「携程」（自建门户，无张冠李戴风险）。
adapter 内部遍历 category 1/2 两渠道，按 fromId 去重。
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


# category → (详情页路由前缀, 三桶分类标签)
_CHANNEL = {
    1: ("experienced", "社会招聘"),
    2: ("campus", "校园招聘"),
}

_API = "https://careers.ctrip.com/api/hrrecruit/getJobAd"
_DETAIL = "https://careers.ctrip.com/#/{route}/job-detail/{from_id}"


class CtripAdapter(PlaywrightAdapter):
    """携程集团自建门户 careers.ctrip.com。source_url 填
    `https://careers.ctrip.com/`，adapter 内部遍历社招/校招两渠道。"""

    name = "ctrip"
    company_name = "携程"
    official_hosts = ("careers.ctrip.com",)

    _PAGE_SIZE = 50
    _MAX_PAGES = 20    # 50×20=1000/渠道（社招 ~613，校招 ~108，绰绰有余）
    posts_keys = ("retValue.recruitJobAdList",) + PlaywrightAdapter.posts_keys

    def fetch(self, source_url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": "https://careers.ctrip.com/",
            "Origin": "https://careers.ctrip.com",
        }
        collected = []
        seen_ids = set()
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for category in (1, 2):
                total = None
                got = 0
                for page_idx in range(1, self._MAX_PAGES + 1):
                    payload = {
                        "condition": {
                            "fromId": [], "keyword": "", "kind": [],
                            "country": [], "city": [], "bucode": [],
                            "jobFamilyCode": [], "jobFamilyGroupCode": [],
                            "category": category,
                        },
                        "pager": {"index": str(page_idx), "size": str(self._PAGE_SIZE)},
                        "head": {"language": "zh_CN", "version": "1"},
                    }
                    try:
                        resp = client.post(_API, json=payload)
                        resp.raise_for_status()
                        jdata = resp.json()
                    except (httpx.HTTPError, ValueError):
                        break
                    rv = jdata.get("retValue") or {}
                    rows = rv.get("recruitJobAdList") or []
                    if not rows:
                        break
                    fresh = []
                    for row in rows:
                        fid = row.get("fromId") or row.get("id")
                        if fid in seen_ids:
                            continue
                        seen_ids.add(fid)
                        row["_category"] = category
                        fresh.append(row)
                    if fresh:
                        collected.append({"retValue": {"recruitJobAdList": fresh}})
                    got += len(rows)
                    if total is None:
                        total = rv.get("total") or 0
                    if total and got >= total:
                        break
        if not collected:
            raise RuntimeError("ctrip: empty getJobAd (careers.ctrip.com)")
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        from_id = _first(post, ("fromId",))
        title = _first(post, ("jobTitle",))
        if not (from_id and title):
            return None
        category = post.get("_category") or 1
        route, label = _CHANNEL.get(category, _CHANNEL[1])
        jd_url = _DETAIL.format(route=route, from_id=from_id)
        # kind/kindName 区分实习（kind=I/intern）
        kind_name = _first(post, ("kindName", "kind"))
        if kind_name and any(k in kind_name.lower() for k in ("实习", "intern", "internship")):
            label = "实习"
        # 正文：duty=岗位职责, requirements=任职要求
        duty = _first(post, ("duty",))
        req = _first(post, ("requirements",))
        summary = (duty + ("\n\n【任职资格】\n" + req if req else "")).strip() or None
        city_name = _first(post, ("cityName",))
        return RawJob(
            company=self.company_name,
            title=title,
            location=city_name or None,
            job_type=label,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )
