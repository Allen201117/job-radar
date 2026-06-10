"""OPPO 招聘（careers.oppo.com）自建门户适配器（直连公开 openapi JSON 接口，零浏览器）。

OPPO 校招门户 JS 公开 POST `https://careers.oppo.com/openapi/position/pageNew`
（json: pageNum + pageSize，可选 recruitProjectId）返回明文 JSON（无需登录/签名）：
  {"code":0,"data":{"total":N,"records":[{idRecruitPosition, positionName, positionDesc,
   positionRequire, workCityName, recruitmentTypeName(博士生/应届生/实习生), projectName,
   positionTypeName}]}}
逐岗稳定详情页 = `https://careers.oppo.com/university/oppo/campus/post/{idRecruitPosition}`
（id-only；live render-verify 过：1724 渲染出「全栈开发工程师」本岗正文，过质量门）。
company 恒为「OPPO」（自建门户，无张冠李戴风险）。覆盖校招/实习渠道（社招不在此门户）。
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


class OppoAdapter(PlaywrightAdapter):
    """OPPO 校招门户 careers.oppo.com。source_url 填
    `https://careers.oppo.com/university/oppo/campus/post?recruitType=Graduate`。"""

    name = "oppo"
    company_name = "OPPO"
    official_hosts = ("careers.oppo.com",)

    _API = "https://careers.oppo.com/openapi/position/pageNew"
    _DETAIL = "https://careers.oppo.com/university/oppo/campus/post/{id}"
    _PAGE_SIZE = 50
    _MAX_PAGES = 12   # 50×12=600 封顶（实有 ~126，留余量）
    posts_keys = ("data.records",) + PlaywrightAdapter.posts_keys

    def fetch(self, source_url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Content-Type": "application/json",
            "Referer": "https://careers.oppo.com/university/oppo/campus/post",
            "Origin": "https://careers.oppo.com",
        }
        collected = []
        total = None
        got = 0
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for page in range(1, self._MAX_PAGES + 1):
                try:
                    resp = client.post(self._API, json={"pageNum": page, "pageSize": self._PAGE_SIZE})
                    resp.raise_for_status()
                    payload = resp.json()
                except (httpx.HTTPError, ValueError):
                    break
                data = payload.get("data") or {}
                rows = data.get("records") or []
                if not rows:
                    break
                collected.append(payload)
                got += len(rows)
                if total is None:
                    total = data.get("total") or 0
                if total and got >= total:
                    break
        if not collected:
            raise RuntimeError("oppo: empty pageNew (careers.oppo.com)")
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        pid = _first(post, ("idRecruitPosition",))
        title = _first(post, ("positionName", "name"))
        if not (pid and title):
            return None
        desc = _first(post, ("positionDesc",))
        req = _first(post, ("positionRequire",))
        summary = (desc + ("\n\n【任职要求】\n" + req if req else "")).strip() or None
        jd_url = self._DETAIL.format(id=pid)
        return RawJob(
            company=self.company_name,
            title=title,
            location=_first(post, ("workCityName",)) or None,
            # recruitmentTypeName=博士生/应届生/实习生 → 三桶分类的关键信号
            job_type=_first(post, ("recruitmentTypeName", "positionTypeName")) or None,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )
